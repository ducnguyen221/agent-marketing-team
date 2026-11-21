"""Owner-operated setup for the experimental LinkedIn member UserInfo reader."""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlencode

from scripts.social.channels.linkedin.readonly_auth import (
    _CLIENT, _PERSON, _PROFILE, _TOKEN, _SafeParser, _reject_constant, _unique,
    _unlinked, check_userinfo,
)

_HOST = 'www.linkedin.com'
_ADDRESS = '127.0.0.1'
_PORT = 8765
_PATH = '/linkedin-oauth-callback'
_AUTHORITY = f'{_ADDRESS}:{_PORT}'
_REDIRECT = f'https://{_AUTHORITY}{_PATH}'
_SCOPES = ('openid', 'profile')
_CLIENT_FILE = 'linkedin-oauth-client.json'
_NATIVE_CLIENT_FILE = 'linkedin-native-client.json'
_OUTPUT = 'linkedin-userinfo.json'
_MAX_JSON = 16384
_MAX_HEADERS = 8192
_CLOUD_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000

_CHECK_WINDOWS_ACL = r"""
$ErrorActionPreference = 'Stop'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted = @($user, 'S-1-5-18', 'S-1-5-32-544')
$paths = ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
foreach ($path in $paths) {
    $acl = Get-Acl -LiteralPath $path
    $raw = [Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(), 0)
    if (-not $acl.AreAccessRulesCanonical -or $raw.Owner.Value -ne $user -or
        $null -eq $raw.DiscretionaryAcl -or $raw.DiscretionaryAcl.Count -eq 0) { exit 1 }
    foreach ($ace in $raw.DiscretionaryAcl) {
        if ($ace -isnot [Security.AccessControl.CommonAce] -or $ace.IsCallback) { exit 1 }
        if ($ace.AceQualifier -eq 'AccessAllowed') {
            if ($ace.SecurityIdentifier.Value -notin $trusted) { exit 1 }
        }
        elseif ($ace.AceQualifier -ne 'AccessDenied') { exit 1 }
    }
}
exit 0
"""


class SetupError(Exception):
    """A fixed diagnostic safe to report without leaking OAuth data."""


def _local_location(path: Path, *, directory: bool) -> os.stat_result:
    info = _unlinked(path, directory=directory)
    if getattr(info, 'st_file_attributes', 0) & _CLOUD_ATTRIBUTES:
        raise SetupError('LinkedIn OAuth requires a local, physical profile.')
    return info


def _private_location(path: Path, *, directory: bool) -> os.stat_result:
    info = _local_location(path, directory=directory)
    if os.name != 'nt' and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise SetupError('LinkedIn OAuth profile files must be private to their owner.')
    return info


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _snapshot(folder: Path) -> tuple[tuple[int, int], ...]:
    roots = tuple(_identity(_local_location(path, directory=True)) for path in reversed(folder.parents[1:]))
    return (*roots, _identity(_private_location(folder.parent, directory=True)),
            _identity(_private_location(folder, directory=True)))


def _verify_windows_acl(*paths: Path) -> None:
    if os.name != 'nt':
        return
    system_root = os.environ.get('SystemRoot', '')
    if not re.fullmatch(r'[A-Za-z]:\\[^:]+', system_root):
        raise SetupError('Windows ACL verification is unavailable.')
    powershell = Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    command = base64.b64encode(_CHECK_WINDOWS_ACL.encode('utf-16-le')).decode('ascii')
    try:
        check = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
            input=json.dumps([str(path) for path in paths]).encode('ascii'),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise SetupError('Windows ACL verification is unavailable.') from None
    if check.returncode != 0:
        raise SetupError('Windows ACL verification rejected the LinkedIn OAuth profile.')


def _ensure_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise SetupError('LinkedIn read-only profile already exists. Choose a new profile alias.')


def _load_client_document(path: Path, snapshot: tuple[tuple[int, int], ...],
                          expected_file: tuple[int, int]) -> dict[str, object]:
    folder = path.parent
    if _identity(_private_location(path, directory=False)) != expected_file:
        raise SetupError('LinkedIn OAuth client location changed.')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        descriptor = os.fstat(stream.fileno())
        if (_identity(descriptor) != expected_file or descriptor.st_nlink != 1
                or _snapshot(folder) != snapshot or descriptor.st_size > _MAX_JSON
                or getattr(descriptor, 'st_file_attributes', 0) & (0x400 | _CLOUD_ATTRIBUTES)
                or (os.name != 'nt' and (descriptor.st_uid != os.geteuid() or descriptor.st_mode & 0o077))):
            raise SetupError('Invalid LinkedIn OAuth client location.')
        raw = stream.read(_MAX_JSON + 1)
    if len(raw) > _MAX_JSON:
        raise SetupError('Invalid LinkedIn OAuth client file.')
    document = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(document, dict):
        raise SetupError('Invalid LinkedIn OAuth client file.')
    return document


def _load_client(folder: Path, snapshot: tuple[tuple[int, int], ...],
                 expected_file: tuple[int, int]) -> tuple[str, str, str]:
    document = _load_client_document(folder / _CLIENT_FILE, snapshot, expected_file)
    if set(document) != {'client_id', 'client_secret', 'person_urn'}:
        raise SetupError('Invalid LinkedIn OAuth client file.')
    client_id, client_secret, expected_author = (document[key] for key in ('client_id', 'client_secret', 'person_urn'))
    if (not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id)
            or not isinstance(client_secret, str) or not _TOKEN.fullmatch(client_secret)
            or not isinstance(expected_author, str) or not _PERSON.fullmatch(expected_author)):
        raise SetupError('Invalid LinkedIn OAuth client file.')
    return client_id, client_secret, expected_author


def _callback_query(connection: socket.socket, deadline: float,
                    authority: str = _AUTHORITY) -> dict[str, list[str]]:
    data = bytearray()
    while b'\r\n\r\n' not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(data) == _MAX_HEADERS:
            raise ValueError('invalid callback')
        connection.settimeout(remaining)
        chunk = connection.recv(min(1024, _MAX_HEADERS - len(data)))
        if not chunk:
            raise ValueError('invalid callback')
        data.extend(chunk)
    head = data.split(b'\r\n\r\n', 1)[0].decode('ascii')
    request, *headers = head.split('\r\n')
    method, target, version = request.split(' ')
    host = [value.strip() for line in headers for key, _, value in [line.partition(':')]
            if key.lower() == 'host']
    path, _, query = target.partition('?')
    if (method != 'GET' or version != 'HTTP/1.1' or path != _PATH or host != [authority]
            or '#' in query):
        raise ValueError('invalid callback')
    return parse_qs(query, keep_blank_values=True, max_num_fields=12, errors='strict')


def _reply(connection: socket.socket, status: bytes, body: bytes) -> None:
    connection.settimeout(1)
    try:
        connection.sendall(
            b'HTTP/1.1 ' + status + b'\r\nContent-Type: text/plain; charset=utf-8\r\n'
            b'Content-Security-Policy: default-src \'none\'\r\nCache-Control: no-store\r\n'
            b'Referrer-Policy: no-referrer\r\nConnection: close\r\nContent-Length: '
            + str(len(body)).encode('ascii') + b'\r\n\r\n' + body
        )
    except OSError:
        pass


def _receive_code(client_id: str, context: ssl.SSLContext) -> str:
    code, _ = _authorize(client_id, context)
    return code


def _authorize(client_id: str, context: ssl.SSLContext | None,
               *, challenge: str = '') -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((_ADDRESS, _PORT if context is not None else 0))
        authority = _AUTHORITY if context is not None else f'{_ADDRESS}:{listener.getsockname()[1]}'
        redirect = _REDIRECT if context is not None else f'http://{authority}{_PATH}'
        parameters = {
            'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect,
            'scope': ' '.join(_SCOPES), 'state': state,
        }
        auth_path = '/oauth/v2/authorization'
        if context is None:
            auth_path = '/oauth/native-pkce/authorization'
            parameters.update(code_challenge=challenge, code_challenge_method='S256')
        auth_url = f'https://{_HOST}{auth_path}?' + urlencode(parameters)
        listener.listen(4)
        deadline = time.monotonic() + 180
        # A browser launcher can block. Keep the callback deadline independent.
        threading.Thread(target=_open_browser, args=(auth_url,), daemon=True).start()
        while (remaining := deadline - time.monotonic()) > 0:
            listener.settimeout(remaining)
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                break
            with connection:
                request_deadline = min(deadline, time.monotonic() + 3)
                connection.settimeout(max(0.001, request_deadline - time.monotonic()))
                try:
                    transport = (context.wrap_socket(connection, server_side=True)
                                 if context is not None else nullcontext(connection))
                    with transport as callback:
                        query = _callback_query(callback, request_deadline, authority)
                        received = query.get('state', [])
                        if (len(received) != 1 or not received[0].isascii()
                                or not hmac.compare_digest(state, received[0])):
                            _reply(callback, b'401 Unauthorized', b'Invalid OAuth callback.')
                            continue
                        code = query.get('code', [])
                        if 'error' in query:
                            _reply(callback, b'400 Bad Request', b'LinkedIn authorization did not complete.')
                            raise SetupError('LinkedIn authorization did not complete.')
                        if len(code) == 1 and _TOKEN.fullmatch(code[0]):
                            _reply(callback, b'200 OK', b'Callback received. Return to your terminal.')
                            return code[0], redirect
                        _reply(callback, b'400 Bad Request', b'Invalid OAuth callback.')
                except (OSError, ValueError):
                    continue
    if context is None:
        raise SetupError('LinkedIn OAuth callback timed out. Check native PKCE enablement and the browser.')
    raise SetupError('LinkedIn OAuth callback timed out. Check the registered URI and browser certificate trust.')


def _open_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        print('Could not open the browser for LinkedIn authorization.', file=sys.stderr)


def _exchange_code(client_id: str, client_secret: str, code: str) -> tuple[str, float]:
    return _request_token({
        'grant_type': 'authorization_code', 'client_id': client_id, 'client_secret': client_secret,
        'code': code, 'redirect_uri': _REDIRECT,
    })


def _request_token(parameters: dict[str, str]) -> tuple[str, float]:
    started = time.monotonic()
    connection = http.client.HTTPSConnection(_HOST, timeout=10)
    try:
        connection.request('POST', '/oauth/v2/accessToken', urlencode(parameters),
                           {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise SetupError('LinkedIn rejected the token exchange.')
        raw = response.read(_MAX_JSON + 1)
    finally:
        connection.close()
    if len(raw) > _MAX_JSON:
        raise SetupError('Invalid LinkedIn token response.')
    result = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(result, dict) or 'error' in result:
        raise SetupError('Invalid LinkedIn token response.')
    token, scope, expiry = result.get('access_token'), result.get('scope'), result.get('expires_in')
    token_type = result.get('token_type', 'Bearer')  # LinkedIn's documented response can omit token_type.
    if (not isinstance(token, str) or not _TOKEN.fullmatch(token)
            or not isinstance(scope, str) or sorted(unquote_plus(scope).split()) != list(_SCOPES)
            or not isinstance(token_type, str) or token_type.lower() != 'bearer'
            or type(expiry) is not int or not 0 < expiry <= 2**31 - 1):
        raise SetupError('LinkedIn did not return an access token with exactly the requested scopes.')
    return token, started + expiry


def _native_token(folder: Path, snapshot: tuple[tuple[int, int], ...]) -> tuple[str, str, str, float]:
    path = folder / _NATIVE_CLIENT_FILE
    expected_file = _identity(_private_location(path, directory=False))
    _verify_windows_acl(folder.parent, folder, path)
    document = _load_client_document(path, snapshot, expected_file)
    if set(document) != {'client_id', 'person_urn'}:
        raise SetupError('Invalid LinkedIn native PKCE client file.')
    client_id, expected_author = document['client_id'], document['person_urn']
    if (not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id)
            or not isinstance(expected_author, str) or not _PERSON.fullmatch(expected_author)):
        raise SetupError('Invalid LinkedIn native PKCE client file.')

    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    code, redirect = _authorize(client_id, None, challenge=challenge)
    token, expires_at = _request_token({
        'grant_type': 'authorization_code', 'client_id': client_id,
        'code': code, 'redirect_uri': redirect, 'code_verifier': verifier,
    })
    return client_id, expected_author, token, expires_at


def _standard_token(folder: Path, snapshot: tuple[tuple[int, int], ...]) -> tuple[str, str, str, float]:
    certificate, key = folder / 'linkedin-callback-cert.pem', folder / 'linkedin-callback-key.pem'
    checked_inputs = (folder / _CLIENT_FILE, certificate, key)
    inputs = tuple(_identity(_private_location(path, directory=False)) for path in checked_inputs)
    _verify_windows_acl(folder.parent, folder, *checked_inputs)
    if (_snapshot(folder) != snapshot
            or tuple(_identity(_private_location(path, directory=False)) for path in checked_inputs) != inputs):
        raise SetupError('LinkedIn OAuth profile location changed.')
    client_id, client_secret, expected_author = _load_client(folder, snapshot, inputs[0])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key, password=lambda: b'')
    if (_snapshot(folder) != snapshot
            or tuple(_identity(_private_location(path, directory=False)) for path in checked_inputs) != inputs):
        raise SetupError('LinkedIn OAuth profile location changed.')
    code = _receive_code(client_id, context)
    token, expires_at = _exchange_code(client_id, client_secret, code)
    return client_id, expected_author, token, expires_at


def _save_profile(folder: Path, snapshot: tuple[tuple[int, int], ...], client_id: str,
                  expected_author: str, token: str) -> None:
    path = folder / _OUTPUT
    if _snapshot(folder) != snapshot:
        raise SetupError('LinkedIn OAuth profile location changed.')
    _verify_windows_acl(folder.parent, folder)
    _ensure_absent(path)
    fd, name = tempfile.mkstemp(prefix='.linkedin-oauth-', suffix='.tmp', dir=folder)
    temporary = Path(name)
    opened = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            opened = _identity(os.fstat(stream.fileno()))
            if _snapshot(folder) != snapshot or _identity(_private_location(temporary, directory=False)) != opened:
                raise SetupError('LinkedIn OAuth profile location changed.')
            _verify_windows_acl(folder.parent, folder, temporary)
            json.dump({
                'schema': 'linkedin-userinfo/1', 'provider': 'linkedin', 'token_kind': 'oauth_access_token',
                'client_id': client_id, 'person_urn': expected_author, 'access_token': token,
            }, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if _snapshot(folder) != snapshot or _identity(_private_location(temporary, directory=False)) != opened:
            raise SetupError('LinkedIn OAuth profile location changed.')
        if os.name == 'nt':
            os.rename(temporary, path)  # Windows refuses to replace an existing target.
        else:
            os.link(temporary, path, follow_symlinks=False)
    finally:
        if opened is not None and _snapshot(folder) == snapshot:
            try:
                info = temporary.lstat()
            except FileNotFoundError:
                pass
            else:
                if _identity(info) == opened:
                    temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--authorize-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--mode', choices=('standard', 'native-pkce'), default='standard')
    args = parser.parse_args(argv)
    if not args.authorize_readonly or not sys.stdin.isatty() or not sys.stdout.isatty():
        print('LinkedIn OAuth requires an explicit request in an interactive terminal.', file=sys.stderr)
        return 2
    if (not _PROFILE.fullmatch(args.profile)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', args.profile)):
        print('Invalid LinkedIn profile alias.', file=sys.stderr)
        return 2
    try:
        folder = Path.home() / '.secret' / args.profile
        if (not folder.is_absolute() or '..' in folder.parts or str(folder).startswith(('\\\\', '//'))
                or any(':' in component for component in folder.parts[1:])):
            raise SetupError('Invalid local LinkedIn OAuth profile location.')
        print('Use a dedicated read-only app. LinkedIn can invalidate existing access tokens when scopes change.')
        native = args.mode == 'native-pkce'
        condition = 'LinkedIn enabled native PKCE for this app' if native else 'the registered HTTPS callback'
        if input(f'Confirm private profile access and {condition}. Type authorize: ') != 'authorize':
            raise SetupError('LinkedIn OAuth setup cancelled.')
        snapshot = _snapshot(folder)
        _ensure_absent(folder / _OUTPUT)
        acquire_token = _native_token if native else _standard_token
        client_id, expected_author, token, expires_at = acquire_token(folder, snapshot)
        if check_userinfo(token, expected_author)['identity'] != 'match':
            raise SetupError('LinkedIn UserInfo did not confirm the expected member for this app.')
        if input('LinkedIn member matched. Type save to store the read-only profile: ') != 'save':
            raise SetupError('LinkedIn OAuth setup cancelled before saving.')
        if time.monotonic() >= expires_at:
            raise SetupError('The access token expired before saving.')
        _save_profile(folder, snapshot, client_id, expected_author, token)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, http.client.HTTPException, RecursionError, RuntimeError, EOFError, KeyboardInterrupt):
        callback = 'native PKCE callback' if args.mode == 'native-pkce' else 'HTTPS callback'
        print(f'LinkedIn OAuth setup did not complete. Check the local profile, {callback} and app settings.',
              file=sys.stderr)
        return 1
    print('Saved a new LinkedIn read-only profile. Member matched during setup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
