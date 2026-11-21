"""Owner-operated OAuth 2.0 PKCE setup for the X read-only identity check."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from scripts.social.channels.linkedin.oauth_setup import (
    SetupError as ProfileSecurityError,
    _identity,
    _private_location,
    _snapshot,
    _verify_windows_acl,
)
from scripts.social.channels.x.readonly_auth import (
    _CLIENT,
    _PROFILE,
    _TOKEN,
    _USER_ID,
    _SafeParser,
    _reject_constant,
    _unique,
    interpret_userinfo,
)

_ADDRESS = '127.0.0.1'
_PORT = 8767
_CALLBACK = '/x-oauth-callback'
_AUTHORITY = f'{_ADDRESS}:{_PORT}'
_REDIRECT = f'http://{_AUTHORITY}{_CALLBACK}'
_SCOPES = frozenset(('tweet.read', 'users.read'))
_AUTHORIZATION_URL = 'https://x.com/i/oauth2/authorize'
_OUTPUT = 'x-userinfo.json'
_MAX_HEADER = 8192
_MAX_BODY = 65536


class SetupError(Exception):
    """A fixed diagnostic safe to report without revealing OAuth data."""


def _callback(connection: socket.socket, deadline: float, state: str) -> str | None:
    request = bytearray()
    while b'\r\n\r\n' not in request:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(request) == _MAX_HEADER:
            return None
        connection.settimeout(remaining)
        chunk = connection.recv(min(1024, _MAX_HEADER - len(request)))
        if not chunk:
            return None
        request.extend(chunk)
    head, trailing = request.split(b'\r\n\r\n', 1)
    first_line, *headers = head.decode('ascii').split('\r\n')
    method, target, protocol = first_line.split(' ')
    parsed = [header.partition(':') for header in headers]
    if any(not sep or not re.fullmatch(r'[A-Za-z0-9-]+', key) for key, sep, _ in parsed):
        return None
    hosts = [value.strip() for key, _, value in parsed if key.lower() == 'host']
    path, separator, query = target.partition('?')
    if (method != 'GET' or protocol != 'HTTP/1.1' or hosts != [_AUTHORITY]
            or trailing or path != _CALLBACK or not separator or '#' in query
            or any(key.lower() in ('transfer-encoding', 'content-length') for key, _, _ in parsed)):
        return None
    fields = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=8,
                      encoding='ascii', errors='strict')
    states = fields.get('state', [])
    if len(states) != 1 or not hmac.compare_digest(states[0], state):
        return None
    if set(fields) <= {'state', 'error', 'error_description', 'error_uri'} and len(fields.get('error', [])) == 1:
        raise SetupError('X authorization was refused or failed.')
    codes = fields.get('code', [])
    if set(fields) == {'state', 'code'} and len(codes) == 1 and _TOKEN.fullmatch(codes[0]):
        return codes[0]
    return None


def _reply(connection: socket.socket, accepted: bool) -> None:
    status = b'200 OK' if accepted else b'400 Bad Request'
    body = b'Return to the terminal.' if accepted else b'Invalid OAuth callback.'
    try:
        connection.settimeout(1)
        connection.sendall(
            b'HTTP/1.1 ' + status + b'\r\nContent-Type: text/plain; charset=utf-8\r\n'
            b'Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n'
            b"Content-Security-Policy: default-src 'none'\r\nConnection: close\r\nContent-Length: "
            + str(len(body)).encode('ascii') + b'\r\n\r\n' + body
        )
    except OSError:
        pass


def _open_browser(url: str, failed: threading.Event) -> None:
    try:
        if webbrowser.open(url):
            return
    except (OSError, webbrowser.Error):
        pass
    failed.set()


def _receive_code(client_id: str, verifier: str) -> str:
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=')
    url = _AUTHORIZATION_URL + '?' + urlencode({
        'response_type': 'code', 'client_id': client_id, 'redirect_uri': _REDIRECT,
        'scope': ' '.join(sorted(_SCOPES)), 'state': state, 'code_challenge': challenge.decode('ascii'),
        'code_challenge_method': 'S256',
    })
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((_ADDRESS, _PORT))
        listener.listen(4)
        deadline = time.monotonic() + 180
        browser_failed = threading.Event()
        threading.Thread(target=_open_browser, args=(url, browser_failed), daemon=True).start()
        while (remaining := deadline - time.monotonic()) > 0:
            if browser_failed.is_set():
                raise SetupError('The browser could not be opened. Check the default browser.')
            listener.settimeout(min(remaining, 0.25))
            try:
                connection, peer = listener.accept()
            except TimeoutError:
                continue
            with connection:
                if peer[0] != _ADDRESS:
                    continue
                try:
                    code = _callback(connection, min(deadline, time.monotonic() + 2), state)
                except SetupError:
                    _reply(connection, True)
                    raise
                except (OSError, ValueError):
                    continue
                _reply(connection, bool(code))
                if code is not None:
                    return code
    raise SetupError('The registered X callback was not received within three minutes.')


def _request_json(method: str, path: str, *, headers: dict[str, str], body: str | None = None) -> object:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    connection = http.client.HTTPSConnection('api.x.com', timeout=10, context=context)
    try:
        connection.request(method, path, body=body, headers={'Accept': 'application/json', **headers})
        response = connection.getresponse()
        if response.status != 200:
            raise SetupError('X did not accept the OAuth or identity request. Check the Native App configuration.')
        raw = response.read(_MAX_BODY + 1)
        if len(raw) > _MAX_BODY:
            raise SetupError('X returned an invalid response.')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_reject_constant)
    finally:
        connection.close()


def _exchange_code(client_id: str, verifier: str, code: str) -> tuple[str, float]:
    started = time.monotonic()
    response = _request_json('POST', '/2/oauth2/token',
                             headers={'Content-Type': 'application/x-www-form-urlencoded'},
                             body=urlencode({'grant_type': 'authorization_code', 'client_id': client_id,
                                             'redirect_uri': _REDIRECT, 'code_verifier': verifier, 'code': code}))
    if (not isinstance(response, dict)
            or {'error', 'errors', 'error_description', 'error_uri', 'refresh_token', 'id_token',
                'status', 'title', 'detail', 'type'} & response.keys()):
        raise SetupError('X returned an invalid read-only token response.')
    token, scopes, duration = (response.get(key) for key in ('access_token', 'scope', 'expires_in'))
    token_type = response.get('token_type')
    if (not isinstance(token, str) or not _TOKEN.fullmatch(token)
            or not isinstance(token_type, str) or token_type.lower() != 'bearer'
            or not isinstance(scopes, str) or sorted(scopes.split(' ')) != sorted(_SCOPES)
            or type(duration) is not int or not (0 < duration <= 86400)):
        raise SetupError('X returned an invalid read-only token response.')
    return token, started + duration


def _check_profile_location(folder: Path, expected: tuple[tuple[int, int], ...]) -> None:
    if _snapshot(folder) != expected:
        raise SetupError('The X profile location changed.')
    _verify_windows_acl(folder.parent, folder)
    try:
        (folder / _OUTPUT).lstat()
    except FileNotFoundError:
        return
    raise SetupError('The X read-only profile exists. Choose a new alias.')


def _require_local_drive(folder: Path) -> None:
    if os.name == 'nt':
        get_drive_type = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        get_drive_type.argtypes = (ctypes.c_wchar_p,)
        get_drive_type.restype = ctypes.c_uint
        if get_drive_type(folder.anchor) != 3:  # DRIVE_FIXED
            raise SetupError('X OAuth setup requires a fixed local Windows drive.')


def _save_profile(folder: Path, expected: tuple[tuple[int, int], ...], client_id: str,
                  expected_user_id: str, token: str, expires_at: float) -> None:
    _check_profile_location(folder, expected)
    fd, name = tempfile.mkstemp(prefix='.x-oauth-', suffix='.tmp', dir=folder)
    staged = Path(name)
    opened = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            opened = _identity(os.fstat(stream.fileno()))
            if _snapshot(folder) != expected or _identity(_private_location(staged, directory=False)) != opened:
                raise SetupError('The X profile location changed.')
            _verify_windows_acl(folder.parent, folder, staged)
            json.dump({'schema': 'x-userinfo/1', 'provider': 'x', 'token_kind': 'oauth2_user_access_token',
                       'client_id': client_id, 'expected_user_id': expected_user_id, 'access_token': token}, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        _check_profile_location(folder, expected)
        if _identity(_private_location(staged, directory=False)) != opened:
            raise SetupError('The X profile location changed.')
        _verify_windows_acl(staged)
        if time.monotonic() >= expires_at:
            raise SetupError('The X access token expired before saving.')
        if os.name == 'nt':
            os.rename(staged, folder / _OUTPUT)  # Windows rename refuses to replace an existing file.
        else:
            os.link(staged, folder / _OUTPUT, follow_symlinks=False)
    finally:
        if opened is not None and _snapshot(folder) == expected:
            try:
                if _identity(staged.lstat()) == opened:
                    staged.unlink()
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--authorize-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args(argv)
    if not args.authorize_readonly or not sys.stdin.isatty() or not sys.stdout.isatty():
        print('X setup requires an explicit request in an interactive terminal.', file=sys.stderr)
        return 2
    if (not _PROFILE.fullmatch(args.profile)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', args.profile)):
        print('Invalid X profile alias.', file=sys.stderr)
        return 2
    try:
        folder = Path.home() / '.secret' / args.profile
        if (not folder.is_absolute() or '..' in folder.parts or str(folder).startswith(('\\\\', '//'))
                or any(':' in part for part in folder.parts[1:])):
            raise SetupError('Invalid local X profile location.')
        prompt = f'Confirm X Native App redirect {_REDIRECT} and private profile access. Type authorize: '
        if input(prompt) != 'authorize':
            raise SetupError('X OAuth setup cancelled.')
        _require_local_drive(folder)
        snapshot = _snapshot(folder)
        _check_profile_location(folder, snapshot)
        client_id = input('Public X OAuth Client ID: ')
        expected_user_id = input('Independently verified numeric X user ID: ')
        if not _CLIENT.fullmatch(client_id) or not _USER_ID.fullmatch(expected_user_id):
            raise SetupError('Invalid public client ID or expected user ID.')
        verifier = secrets.token_urlsafe(32)
        code = _receive_code(client_id, verifier)
        token, expires_at = _exchange_code(client_id, verifier, code)
        response = _request_json('GET', '/2/users/me', headers={'Authorization': 'Bearer ' + token})
        if interpret_userinfo(200, response, expected_user_id=expected_user_id)['identity'] != 'match':
            raise SetupError('X did not confirm the expected user.')
        if input('X user matched. Type save to store the read-only profile: ') != 'save':
            raise SetupError('X OAuth setup cancelled before saving.')
        _save_profile(folder, snapshot, client_id, expected_user_id, token, expires_at)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ProfileSecurityError:
        print('X profile ownership or permissions could not be verified.', file=sys.stderr)
        return 1
    except (OSError, ValueError, http.client.HTTPException, RuntimeError, EOFError, KeyboardInterrupt):
        print('X OAuth setup did not complete. Check the local profile, callback and app settings.', file=sys.stderr)
        return 1
    print('Saved a new X read-only profile. The expected user matched during setup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
