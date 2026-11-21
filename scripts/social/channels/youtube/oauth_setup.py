"""Owner-operated setup for the experimental YouTube read-only profile."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import stat
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from scripts.social.channels.linkedin.readonly_auth import _PROFILE, _TOKEN, _reject_constant, _unique, _unlinked
from scripts.social.channels.youtube.readonly_auth import _CHANNEL, _SafeParser, check_channel

_SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_PATH = '/youtube-oauth-callback'
_WAIT_SECONDS = 180
_MAX_JSON = 16384
_CLIENT_ID = re.compile(r'[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com\Z')
_CODE = re.compile(r'[A-Za-z0-9._~+/=-]{1,4096}\Z')
_CLIENT_FILE = 'youtube-oauth-client.json'
_PROFILE_FILE = 'youtube-channel-userinfo.json'
_CLOUD_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000  # Offline, recall on open, recall on data access.


class SetupError(Exception):
    """An actionable error with a fixed message safe to display."""


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _local_unlinked(path: Path, *, directory: bool) -> os.stat_result:
    info = _unlinked(path, directory=directory)
    if getattr(info, 'st_file_attributes', 0) & _CLOUD_ATTRIBUTES:
        raise SetupError('YouTube OAuth profile must be stored on a local drive.')
    return info


def _snapshot(folder: Path) -> tuple[tuple[int, int], ...]:
    paths = (*reversed(folder.parents), folder)
    locations = tuple(_local_unlinked(path, directory=True) for path in paths)
    if os.name != 'nt' and any(
        location.st_uid != os.geteuid() or location.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        for location in locations[-2:]
    ):
        raise SetupError('YouTube OAuth profile and secret directories must be owner-controlled.')
    return tuple(_identity(location) for location in locations)


def _check_location(folder: Path, snapshot: tuple[tuple[int, int], ...], path: Path, fd: int) -> None:
    current = _local_unlinked(path, directory=False)
    opened = os.fstat(fd)
    if (_snapshot(folder) != snapshot or _identity(current) != _identity(opened)
            or opened.st_nlink != 1 or getattr(opened, 'st_file_attributes', 0) & (0x400 | _CLOUD_ATTRIBUTES)):
        raise SetupError('YouTube OAuth profile location changed.')


def _must_be_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise SetupError('YouTube read-only profile already exists. Choose a fresh profile alias.')


def _load_desktop_client(folder: Path, snapshot: tuple[tuple[int, int], ...]) -> tuple[str, str]:
    path = folder / _CLIENT_FILE
    before = _local_unlinked(path, directory=False)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        _check_location(folder, snapshot, path, stream.fileno())
        opened = os.fstat(stream.fileno())
        if _identity(before) != _identity(opened) or opened.st_size > _MAX_JSON:
            raise SetupError('Invalid Google Desktop app client file.')
        if os.name != 'nt' and (opened.st_uid != os.geteuid() or opened.st_mode & 0o077):
            raise SetupError('Google Desktop app client file must be private to its owner.')
        raw = stream.read(_MAX_JSON + 1)
    if len(raw) > _MAX_JSON:
        raise SetupError('Invalid Google Desktop app client file.')
    document = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    client = document.get('installed') if isinstance(document, dict) else None
    if not isinstance(client, dict):
        raise SetupError('Expected a Google Desktop app client file.')
    client_id, client_secret = client.get('client_id'), client.get('client_secret')
    if (not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id)
            or not isinstance(client_secret, str) or not _TOKEN.fullmatch(client_secret)):
        raise SetupError('Invalid Google Desktop app client file.')
    return client_id, client_secret


class CallbackServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, state: str) -> None:
        super().__init__(('127.0.0.1', 0), CallbackHandler)
        self.state = state
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)
        self.code: str | None = None
        self.host = f'127.0.0.1:{self.server_port}'
        self.redirect_uri = f'http://{self.host}{_PATH}'

    def server_bind(self) -> None:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        # The request URL may contain an authorization code.
        pass


class CallbackHandler(BaseHTTPRequestHandler):
    server: CallbackServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._reply(code, b'Invalid OAuth callback.')

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            request_target = self.requestline.split()[1]
            if not request_target.startswith(_PATH + '?'):
                self.send_error(400)
                return
            target = urlsplit(request_target)
            query = parse_qs(target.query, keep_blank_values=True, max_num_fields=16)
        except ValueError:
            self.send_error(400)
            return
        state = query.get('state', [])
        if (self.headers.get_all('Host') != [self.server.host] or target.scheme or target.netloc
                or target.fragment or target.path != _PATH or len(state) != 1
                or not state[0].isascii() or not hmac.compare_digest(state[0], self.server.state)):
            self.send_error(400)
            return
        code = query.get('code', [])
        denied = query.get('error', [])
        if denied:
            if len(denied) != 1 or not denied[0] or code:
                self.send_error(400)
                return
        elif len(code) != 1 or not _CODE.fullmatch(code[0]):
            self.send_error(400)
            return
        with self.server.lock:
            if self.server.ready.is_set():
                self.send_error(400)
                return
            self.server.code = None if denied else code[0]
            self.server.ready.set()
        self._reply(200, b'You can close this tab and return to the terminal.')


def _receive_code(client_id: str, verifier: str) -> tuple[str, str]:
    with CallbackServer(secrets.token_urlsafe(32)) as server:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest())
        url = _AUTH_URL + '?' + urlencode({
            'client_id': client_id,
            'redirect_uri': server.redirect_uri,
            'response_type': 'code',
            'scope': _SCOPE,
            'state': server.state,
            'code_challenge': challenge.rstrip(b'=').decode('ascii'),
            'code_challenge_method': 'S256',
        })
        listener = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        listener.start()
        try:
            # A browser launcher can block on some desktop configurations.
            threading.Thread(target=_open_browser, args=(url, server), daemon=True).start()
            if not server.ready.wait(_WAIT_SECONDS):
                raise SetupError('Google OAuth callback timed out. Restart setup to try again.')
            if server.code is None:
                raise SetupError('Google OAuth consent or browser launch did not complete.')
            return server.code, server.redirect_uri
        finally:
            server.shutdown()


def _open_browser(url: str, server: CallbackServer) -> None:
    try:
        if webbrowser.open(url):
            return
    except (OSError, webbrowser.Error):
        pass
    with server.lock:
        if not server.ready.is_set():
            server.ready.set()


def _exchange_code(client_id: str, client_secret: str, verifier: str,
                   code: str, redirect_uri: str) -> tuple[str, float]:
    exchange_started = time.monotonic()
    connection = http.client.HTTPSConnection('oauth2.googleapis.com', timeout=10)
    try:
        connection.request('POST', '/token', urlencode({
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'code_verifier': verifier,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }), {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise SetupError('Google did not accept the token exchange.')
        raw = response.read(_MAX_JSON + 1)
    finally:
        connection.close()
    if len(raw) > _MAX_JSON:
        raise SetupError('Invalid Google token response.')
    result = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(result, dict) or 'error' in result:
        raise SetupError('Invalid Google token response.')
    token, token_type, scope = result.get('access_token'), result.get('token_type'), result.get('scope')
    if (not isinstance(token, str) or not _TOKEN.fullmatch(token) or not isinstance(token_type, str)
            or token_type.lower() != 'bearer' or not isinstance(scope, str) or scope.split() != [_SCOPE]
            or type(result.get('expires_in')) is not int or result['expires_in'] <= 0):
        raise SetupError('Google did not return a bearer token with exactly the YouTube read-only scope.')
    return token, exchange_started + result['expires_in']


def _save_profile(folder: Path, snapshot: tuple[tuple[int, int], ...],
                  client_id: str, channel_id: str, token: str) -> None:
    path = folder / _PROFILE_FILE
    if _snapshot(folder) != snapshot:
        raise SetupError('YouTube OAuth profile location changed.')
    _must_be_absent(path)
    fd, temp_name = tempfile.mkstemp(prefix='.youtube-oauth-', suffix='.tmp', dir=folder)
    temporary = Path(temp_name)
    opened: tuple[int, int] | None = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            opened = _identity(os.fstat(stream.fileno()))
            _check_location(folder, snapshot, temporary, stream.fileno())
            json.dump({
                'schema': 'youtube-channel-userinfo/1',
                'provider': 'youtube',
                'token_kind': 'oauth_access_token',
                'client_id': client_id,
                'expected_channel_id': channel_id,
                'access_token': token,
            }, stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if _snapshot(folder) != snapshot or _identity(_local_unlinked(temporary, directory=False)) != opened:
            raise SetupError('YouTube OAuth profile location changed.')
        if os.name == 'nt':
            # Windows rename fails when the target already exists.
            os.rename(temporary, path)
        else:
            # POSIX rename would replace the target, so publish a hard link and remove the temp name.
            os.link(temporary, path, follow_symlinks=False)
    finally:
        if opened is not None and _snapshot(folder) == snapshot:
            try:
                current = temporary.lstat()
            except FileNotFoundError:
                pass
            else:
                if _identity(current) == opened and not getattr(current, 'st_file_attributes', 0) & 0x400:
                    temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--authorize-readonly', action='store_true')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--expected-channel-id', required=True)
    args = parser.parse_args(argv)
    if not args.authorize_readonly or not sys.stdin.isatty() or not sys.stdout.isatty():
        print('YouTube OAuth requires an explicit request in an interactive terminal.', file=sys.stderr)
        return 2
    if (not _PROFILE.fullmatch(args.profile) or not _CHANNEL.fullmatch(args.expected_channel_id)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', args.profile)):
        print('Invalid profile alias or expected YouTube channel ID.', file=sys.stderr)
        return 2
    try:
        folder = Path.home() / '.secret' / args.profile
        if (not folder.is_absolute() or '..' in folder.parts or str(folder).startswith(('\\\\', '//'))
                or any(':' in component for component in folder.parts[1:])):
            raise SetupError('Invalid local YouTube OAuth profile location.')
        if input('Type authorize to open Google for YouTube read-only access: ') != 'authorize':
            raise SetupError('YouTube OAuth setup cancelled.')
        snapshot = _snapshot(folder)
        _must_be_absent(folder / _PROFILE_FILE)
        client_id, client_secret = _load_desktop_client(folder, snapshot)
        verifier = secrets.token_urlsafe(64)
        code, redirect_uri = _receive_code(client_id, verifier)
        token, expires_at = _exchange_code(client_id, client_secret, verifier, code, redirect_uri)
        if check_channel(token, args.expected_channel_id)['identity'] != 'match':
            raise SetupError('The selected Google account did not confirm the expected YouTube channel.')
        if input('Channel matched. Confirm the profile folder has private access, then type save: ') != 'save':
            raise SetupError('YouTube OAuth setup cancelled before saving.')
        if time.monotonic() >= expires_at:
            raise SetupError('The access token expired before saving. Restart setup to try again.')
        _save_profile(folder, snapshot, client_id, args.expected_channel_id, token)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, http.client.HTTPException, RecursionError, RuntimeError, EOFError, KeyboardInterrupt):
        print('YouTube OAuth setup did not complete. Check the local profile and Google Desktop app setup.',
              file=sys.stderr)
        return 1
    print('Saved a new YouTube read-only profile. Channel matched during setup.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
