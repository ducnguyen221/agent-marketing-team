"""Unwired server-side TikTok Login Kit Desktop exchange."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from scripts.social.channels.linkedin.readonly_auth import (
    _CLIENT, _TOKEN, _reject_constant, _unique,
)
from scripts.social.channels.tiktok.readonly_auth import _valid_open_id, check_userinfo

_AUTHORIZE_URL = 'https://www.tiktok.com/v2/auth/authorize/'
_SCOPE = 'user.info.basic'
_TTL_SECONDS = 300
_MAX_BODY = 65536
_STATE = re.compile(r'[A-Za-z0-9_-]{43}')
_VERIFIER = re.compile(r'[A-Za-z0-9._~-]{43,128}')
_ERROR_CODES = frozenset({
    'access_denied', 'invalid_client', 'invalid_grant', 'invalid_request',
    'invalid_scope', 'unauthorized_client', 'unsupported_grant_type',
    'unsupported_response_type', 'server_error', 'temporarily_unavailable',
})


class OAuthExchangeError(ValueError):
    """Public-safe fixed failure category."""


@dataclass(frozen=True, repr=False)
class AuthorizationSession:
    state: str
    initiator: str
    client_key: str
    redirect_uri: str
    expected_open_id: str
    verifier: str
    expires_at: float


class AuthorizationStore(Protocol):
    """Private storage shared by all backend processes handling this app."""

    def insert(self, session: AuthorizationSession) -> None:
        """Create a session, refusing to replace an existing state."""

    def claim(self, state: str, initiator: str, now: float) -> AuthorizationSession | None:
        """Atomically consume and return one matching unexpired session."""


@dataclass(frozen=True, repr=False)
class ReadonlyAccess:
    """Verified access credentials for in-process backend use only."""

    access_token: str
    open_id: str
    expires_at: float


def _visible_ascii(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit
            and all('!' <= char <= '~' for char in value))


def _loopback_redirect(uri: str) -> bool:
    if not _visible_ascii(uri, 511) or any(mark in uri for mark in ('?', '#', '\\')):
        return False
    try:
        parsed = urlsplit(uri)
        return (parsed.scheme in ('http', 'https') and parsed.port is not None
                and parsed.port > 0
                and re.fullmatch(r'(?:localhost|127\.0\.0\.1):[0-9]+', parsed.netloc)
                is not None)
    except ValueError:
        return False


def begin_authorization(
    store: AuthorizationStore, *, initiator: str, client_key: str,
    redirect_uri: str, expected_open_id: str,
) -> str:
    """Register server-owned inputs and return the browser redirect location."""
    if (not _visible_ascii(initiator, 512) or not isinstance(client_key, str)
            or not _CLIENT.fullmatch(client_key)
            or not _loopback_redirect(redirect_uri) or not _valid_open_id(expected_open_id)):
        raise OAuthExchangeError('invalid_authorization_configuration')
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    session = AuthorizationSession(
        state, initiator, client_key, redirect_uri, expected_open_id,
        verifier, time.time() + _TTL_SECONDS,
    )
    try:
        store.insert(session)
    except Exception:
        raise OAuthExchangeError('authorization_store_unavailable') from None
    return _AUTHORIZE_URL + '?' + urlencode({
        'client_key': client_key,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': _SCOPE,
        'state': state,
        'code_challenge': hashlib.sha256(verifier.encode('ascii')).hexdigest(),
        'code_challenge_method': 'S256',
    })


def _positive_int64(value: object) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


def _parse_token_response(status: int, data: bytes, started_at: float) -> ReadonlyAccess:
    try:
        if len(data) > _MAX_BODY:
            raise ValueError('response_too_large')
        body = json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise OAuthExchangeError('invalid_token_response') from None
    if not isinstance(body, dict):
        raise OAuthExchangeError('invalid_token_response')
    if 'error' in body:
        error = body['error']
        if (isinstance(error, str) and error in _ERROR_CODES
                and 'access_token' not in body and 'refresh_token' not in body):
            raise OAuthExchangeError(error)
        raise OAuthExchangeError('invalid_token_response')
    if status != 200:
        raise OAuthExchangeError('token_exchange_failed')
    access = body.get('access_token')
    refresh = body.get('refresh_token')
    if (not isinstance(access, str) or not _TOKEN.fullmatch(access)
            or not isinstance(refresh, str) or not _TOKEN.fullmatch(refresh)
            or not _positive_int64(body.get('expires_in'))
            or not _positive_int64(body.get('refresh_expires_in'))
            or not _valid_open_id(body.get('open_id'))
            or body.get('scope') != _SCOPE or body.get('token_type') != 'Bearer'):
        raise OAuthExchangeError('invalid_token_response')
    return ReadonlyAccess(access, body['open_id'], started_at + body['expires_in'])


def _exchange(session: AuthorizationSession, code: str, client_secret: str) -> ReadonlyAccess:
    form = urlencode({
        'client_key': session.client_key,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': session.redirect_uri,
        'code_verifier': session.verifier,
    }).encode('ascii')
    connection = http.client.HTTPSConnection('open.tiktokapis.com', timeout=10)
    try:
        started_at = time.time()
        connection.request('POST', '/v2/oauth/token/', body=form, headers={
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        })
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise OAuthExchangeError('unexpected_token_redirect')
        content_type = response.getheader('Content-Type', '')
        if content_type.partition(';')[0].strip().lower() != 'application/json':
            raise OAuthExchangeError('invalid_token_response')
        return _parse_token_response(response.status, response.read(_MAX_BODY + 1), started_at)
    except (OSError, http.client.HTTPException):
        raise OAuthExchangeError('token_exchange_unknown') from None
    finally:
        try:
            connection.close()
        except OSError:
            pass


def complete_authorization(
    store: AuthorizationStore, *, initiator: str, client_key: str, client_secret: str,
    callback: Mapping[str, str],
) -> ReadonlyAccess:
    """Consume the session, exchange once, and verify the returned user identity."""
    state = callback.get('state')
    if (not _visible_ascii(initiator, 512) or not isinstance(state, str)
            or not _STATE.fullmatch(state)):
        raise OAuthExchangeError('invalid_authorization_session')
    now = time.time()
    try:
        session = store.claim(state, initiator, now)
    except Exception:
        raise OAuthExchangeError('authorization_store_unavailable') from None
    if (session is None or not secrets.compare_digest(session.state, state)
            or not secrets.compare_digest(session.initiator, initiator)
            or session.expires_at <= now or session.client_key != client_key
            or not _VERIFIER.fullmatch(session.verifier)):
        raise OAuthExchangeError('invalid_authorization_session')
    if 'error' in callback or 'error_description' in callback:
        raise OAuthExchangeError('authorization_rejected')
    code = callback.get('code')
    if (not isinstance(code, str) or not _visible_ascii(code, 4096)
            or callback.get('scopes') != _SCOPE):
        raise OAuthExchangeError('invalid_authorization_callback')
    if not _visible_ascii(client_secret, 4096):
        raise OAuthExchangeError('invalid_authorization_configuration')
    access = _exchange(session, code, client_secret)
    if (access.open_id != session.expected_open_id
            or check_userinfo(access.access_token, session.expected_open_id)['identity'] != 'match'):
        raise OAuthExchangeError('identity_unverified')
    if access.expires_at <= time.time():
        raise OAuthExchangeError('access_token_expired')
    return access
