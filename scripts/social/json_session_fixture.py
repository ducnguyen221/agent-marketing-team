"""Disposable JSON fixture session, local temp only; no live transport or authority.

The caller must supply an exclusive, trusted local temporary directory. Locks
coordinate cooperating writers of this one session, not copies or V1 runners.
"""
from __future__ import annotations

import copy
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.multichannel_fixture import _validate_batch_media, preview_v1_file_batch

_SESSION = 'social-fixture-session.json'
_LOCK = 'social-fixture-session.lock'
_LIMIT = 8_000_000


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate fixture field')
        result[key] = value
    return result


def _directory(path: Path) -> Path:
    root = Path(tempfile.gettempdir()).resolve(strict=True)
    if '..' in Path(path).parts:
        raise ValueError('fixture directory cannot contain parent traversal')
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError('fixture directory must be under local temporary root') from None
    if not relative.parts:
        raise ValueError('fixture requires a dedicated directory')
    current = root
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('fixture directory must not contain links')
    return current


def _check_file(path: Path) -> os.stat_result:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('invalid fixture file')
    return info


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    lock_path = directory / _LOCK
    if lock_path.exists() or lock_path.is_symlink():
        _check_file(lock_path)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        _check_file(lock_path)
        opened = os.fstat(fd)
        if opened.st_nlink != 1 or (opened.st_ino, opened.st_dev) != (lock_path.stat().st_ino, lock_path.stat().st_dev):
            raise ValueError('fixture lock changed')
        if opened.st_size == 0:
            os.write(fd, b'0')
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _validate(data: Any) -> None:
    if (not isinstance(data, dict) or set(data) != {'schema', 'session_id', 'revision', 'items'}
            or data['schema'] not in ('social-json-fixture/1', 'social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4')
            or not isinstance(data['session_id'], str) or not re.fullmatch(r'fixture-[0-9a-f]{32}', data['session_id'])
            or type(data['revision']) is not int or data['revision'] < 1
            or not isinstance(data['items'], list) or not 1 <= len(data['items']) <= 100):
        raise ValueError('invalid fixture session')
    identities = set()
    attempts: set[str] = set()
    receipt_urns: set[str] = set()
    telegram_receipts: set[tuple[str, str]] = set()
    instagram_containers: set[str] = set()
    instagram_media: set[str] = set()
    prepared = []
    for item in data['items']:
        fields = {'key', 'snapshot', 'snapshot_sha256', 'state', 'grant', 'attempt', 'receipt'}
        if data['schema'] in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4'):
            fields |= {'claim_mode', 'conflict_urn'}
        if data['schema'] in ('social-json-fixture/3', 'social-json-fixture/4'):
            fields.add('conflict_telegram')
        if data['schema'] == 'social-json-fixture/4':
            fields.add('instagram')
        if (not isinstance(item, dict) or set(item) != fields
                or item['state'] not in ('prepared', 'submitting', 'unknown', 'accepted')
                or type(item['grant']) is not bool):
            raise ValueError('invalid fixture item')
        values, digest, _ = DestinationFixtureLedger._encode_prepare(item['key'], item['snapshot'])
        identity = values[:6] + values[7:]
        if identity in identities or digest != item['snapshot_sha256']:
            raise ValueError('fixture identity or snapshot mismatch')
        identities.add(identity)
        prepared.append((item['key'], item['snapshot']))
        attempt, receipt = item['attempt'], item['receipt']
        if item['state'] == 'prepared':
            if attempt is not None or receipt is not None:
                raise ValueError('invalid prepared fixture')
        elif (not item['grant'] or not isinstance(attempt, str) or not re.fullmatch(r'fixture-[0-9a-f]{32}', attempt)
              or (data['schema'] == 'social-json-fixture/1' and item['state'] == 'accepted'
                  and (not isinstance(receipt, str) or not re.fullmatch(r'fixture-[A-Za-z0-9_-]{1,128}', receipt)))
              or (item['state'] != 'accepted' and receipt is not None)):
            raise ValueError('invalid fixture result')
        if data['schema'] in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4'):
            from scripts.social.channels.linkedin.direct import interpret_create
            platform = item['key']['platform']
            schema = item['snapshot'].get('fixture_schema')
            allowed = ((platform == 'linkedin' and schema in ('linkedin-v1-facebook-text/1', 'linkedin-v1-facebook-media/1'))
                       or (data['schema'] in ('social-json-fixture/3', 'social-json-fixture/4') and platform == 'telegram'
                           and schema in ('telegram-v1-facebook-text/1', 'telegram-v1-image/1', 'telegram-v1-video/1'))
                       or (data['schema'] == 'social-json-fixture/4' and platform == 'instagram'
                           and schema in ('instagram-v1-infographic/1', 'instagram-v1-reel/1')))
            if ((item['state'] == 'prepared' and item['claim_mode'] is not None)
                    or (item['state'] != 'prepared' and item['claim_mode'] != 'due')
                    or (item['state'] != 'prepared' and not allowed)
                    or (platform != 'linkedin' and item['conflict_urn'] is not None)
                    or (item['state'] != 'unknown' and item['conflict_urn'] is not None)):
                raise ValueError('invalid fixture claim mode')
            if item['state'] == 'accepted' and platform == 'linkedin':
                if (item['key']['platform'] != 'linkedin' or not isinstance(receipt, dict)
                        or set(receipt) != {'post_urn', 'attempt', 'author', 'readback'}
                        or receipt['attempt'] != attempt or receipt['author'] != item['snapshot'].get('author')
                        or receipt['readback'] != 'unverified'
                        or interpret_create(201, [('x-restli-id', receipt['post_urn'])])['state'] != 'accepted'
                        or receipt['post_urn'] in receipt_urns):
                    raise ValueError('invalid fixture receipt')
                receipt_urns.add(receipt['post_urn'])
            if item['state'] == 'accepted' and platform == 'telegram':
                candidate = item['snapshot']['candidate']
                method = candidate['request']['method']
                expected_kind = {'sendMessage': None, 'sendPhoto': 'image', 'sendVideo': 'video'}.get(method, 'invalid')
                if (not isinstance(receipt, dict)
                        or set(receipt) != {'attempt', 'account_id', 'chat_id', 'message_id', 'media_kind'}
                        or receipt['attempt'] != attempt or receipt['account_id'] != item['key']['account_id']
                        or receipt['chat_id'] != candidate['request']['body']['chat_id']
                        or receipt['media_kind'] != expected_kind or expected_kind == 'invalid'
                        or not isinstance(receipt['message_id'], str)
                        or not re.fullmatch(r'[1-9][0-9]{0,19}', receipt['message_id'])
                        or (receipt['chat_id'], receipt['message_id']) in telegram_receipts):
                    raise ValueError('invalid Telegram fixture receipt')
                telegram_receipts.add((receipt['chat_id'], receipt['message_id']))
            if item['conflict_urn'] is not None and interpret_create(
                    201, [('x-restli-id', item['conflict_urn'])])['state'] != 'accepted':
                raise ValueError('invalid fixture conflict')
            if data['schema'] == 'social-json-fixture/4':
                progress = item['instagram']
                if platform != 'instagram' or item['state'] == 'prepared':
                    if progress is not None:
                        raise ValueError('invalid Instagram fixture progress')
                else:
                    if (not isinstance(progress, dict) or set(progress) != {'phase', 'container_id', 'media_id', 'conflict_container', 'conflict_media'}
                            or progress['phase'] not in ('creating', 'waiting', 'ready', 'publishing', 'accepted', 'unknown')
                            or (item['state'] == 'submitting' and progress['phase'] not in ('creating', 'waiting', 'ready', 'publishing'))
                            or (item['state'] == 'unknown' and progress['phase'] != 'unknown')
                            or (item['state'] == 'accepted' and (progress['phase'] != 'accepted' or receipt is not None))):
                        raise ValueError('invalid Instagram fixture progress')
                    container = progress['container_id']
                    if ((progress['phase'] in ('waiting', 'ready', 'publishing', 'accepted') and (not isinstance(container, str)
                         or not re.fullmatch(r'[0-9]{1,32}', container)))
                            or (container is not None and (not isinstance(container, str) or not re.fullmatch(r'[0-9]{1,32}', container)))
                            or (progress['phase'] == 'creating' and container is not None)):
                        raise ValueError('invalid Instagram fixture container')
                    if container is not None:
                        if container in instagram_containers:
                            raise ValueError('duplicate Instagram fixture container')
                        instagram_containers.add(container)
                    media = progress['media_id']
                    if ((progress['phase'] == 'accepted' and (not isinstance(media, str) or not re.fullmatch(r'[0-9]{1,32}', media)))
                            or (progress['phase'] != 'accepted' and media is not None)):
                        raise ValueError('invalid Instagram fixture media')
                    if media is not None:
                        if media in instagram_media:
                            raise ValueError('duplicate Instagram fixture media')
                        instagram_media.add(media)
        if attempt is not None:
            if attempt in attempts:
                raise ValueError('duplicate fixture attempt')
            attempts.add(attempt)
    if data['schema'] in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4') and any(
            item['conflict_urn'] is not None and item['conflict_urn'] not in receipt_urns for item in data['items']):
        raise ValueError('unmatched fixture conflict')
    if data['schema'] in ('social-json-fixture/3', 'social-json-fixture/4'):
        for item in data['items']:
            conflict = item['conflict_telegram']
            if conflict is not None and (item['state'] != 'unknown' or item['key']['platform'] != 'telegram'
                    or not isinstance(conflict, list) or len(conflict) != 2
                    or any(not isinstance(value, str) for value in conflict)
                    or conflict[0] != item['snapshot']['candidate']['request']['body']['chat_id']
                    or tuple(conflict) not in telegram_receipts):
                raise ValueError('invalid Telegram fixture conflict')
    if data['schema'] == 'social-json-fixture/4':
        for item in data['items']:
            progress = item['instagram']
            if progress is not None and progress['conflict_container'] is not None:
                if (progress['phase'] != 'unknown' or progress['container_id'] is not None
                        or progress['conflict_media'] is not None or not isinstance(progress['conflict_container'], str)
                        or progress['conflict_container'] not in instagram_containers):
                    raise ValueError('invalid Instagram container conflict')
            if progress is not None and progress['conflict_media'] is not None:
                if (progress['phase'] != 'unknown' or progress['container_id'] is None
                        or progress['conflict_container'] is not None or not isinstance(progress['conflict_media'], str)
                        or progress['conflict_media'] not in instagram_media):
                    raise ValueError('invalid Instagram media conflict')
    _validate_batch_media(prepared)


def _load(directory: Path) -> dict[str, Any]:
    path = directory / _SESSION
    checked = _check_file(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        current = _check_file(path)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or getattr(opened, 'st_file_attributes', 0) & 0x400
                or (opened.st_ino, opened.st_dev) != (current.st_ino, current.st_dev)
                or (opened.st_ino, opened.st_dev) != (checked.st_ino, checked.st_dev)):
            raise ValueError('fixture session file changed')
        raw = stream.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ValueError('fixture session too large')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))
        _validate(data)
        return data
    except (UnicodeError, json.JSONDecodeError, RecursionError, KeyError, TypeError):
        raise ValueError('invalid fixture session') from None


def _save(directory: Path, data: dict[str, Any]) -> None:
    _validate(data)
    raw = (json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n').encode('utf-8')
    if len(raw) > _LIMIT:
        raise ValueError('fixture session too large')
    fd, temporary = tempfile.mkstemp(prefix='.social-fixture-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / _SESSION)
        if os.name != 'nt':
            parent = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class FixtureJsonSession:
    """Persist test-only lifecycle state; this class never calls a transport."""

    def __init__(self, directory: Path) -> None:
        self._directory = _directory(directory)
        self._session_id: str | None = None

    def _read(self) -> dict[str, Any]:
        data = _load(self._directory)
        if self._session_id is None or data['session_id'] != self._session_id:
            raise ValueError('fixture session identity changed')
        return data

    @classmethod
    def create(cls, directory: Path, *, source: str, publication: dict[str, Any],
               entries: list[dict[str, Any]], delivery_fixture: bool = False) -> FixtureJsonSession:
        if type(delivery_fixture) is not bool:
            raise ValueError('invalid fixture mode')
        preview = preview_v1_file_batch(source=source, publication=publication, entries=entries)
        session = cls(directory)
        version = ('social-json-fixture/4' if delivery_fixture and any(
            item['key']['platform'] == 'instagram' for item in preview['items']) else
            'social-json-fixture/3' if delivery_fixture and any(
            item['key']['platform'] == 'telegram' for item in preview['items']) else
            'social-json-fixture/2' if delivery_fixture else 'social-json-fixture/1')
        data = {'schema': version,
                'session_id': 'fixture-' + uuid.uuid4().hex, 'revision': 1,
                'items': [dict(item, state='prepared', grant=False, attempt=None, receipt=None)
                          for item in preview['items']]}
        if delivery_fixture:
            for item in data['items']:
                item.update(claim_mode=None, conflict_urn=None)
                if version in ('social-json-fixture/3', 'social-json-fixture/4'):
                    item['conflict_telegram'] = None
                if version == 'social-json-fixture/4':
                    item['instagram'] = None
        with _locked(session._directory):
            path = session._directory / _SESSION
            if path.exists() or path.is_symlink():
                raise ValueError('fixture session already exists')
            _save(session._directory, data)
            session._session_id = data['session_id']
        return session

    @classmethod
    def open(cls, directory: Path) -> FixtureJsonSession:
        session = cls(directory)
        with _locked(session._directory):
            session._session_id = _load(session._directory)['session_id']
        return session

    def inspect(self) -> dict[str, Any]:
        _directory(self._directory)
        with _locked(self._directory):
            return copy.deepcopy(self._read())

    def grant_all(self) -> None:
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if any(item['state'] != 'prepared' or item['grant'] for item in data['items']):
                raise ValueError('fixture grant refused')
            for item in data['items']:
                item['grant'] = True
            data['revision'] += 1
            _save(self._directory, data)

    def claim(self, index: int) -> str:
        return self._claim(index, now=None, expected_digest=None, expected_key=None)

    def claim_due(self, index: int, *, now: str, expected_digest: str, expected_key: dict[str, str]) -> str:
        """Claim a due synthetic snapshot with its caller-expected digest."""
        current = _fixture_time(now)
        if not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
            raise ValueError('invalid fixture digest')
        if not isinstance(expected_key, dict):
            raise ValueError('invalid fixture key')
        return self._claim(index, now=current, expected_digest=expected_digest, expected_key=copy.deepcopy(expected_key))

    def _claim(self, index: int, *, now: Any, expected_digest: str | None, expected_key: dict[str, str] | None) -> str:
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/1':
                raise ValueError('manual claim unavailable for delivery fixture')
            if type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid fixture item')
            item = data['items'][index]
            if item['state'] != 'prepared' or not item['grant']:
                raise ValueError('fixture claim refused')
            if now is not None and (item['key'] != expected_key or item['snapshot_sha256'] != expected_digest
                                    or _fixture_time(item['snapshot']['scheduled_at']) > now):
                raise ValueError('fixture not due or snapshot changed')
            item['state'], item['attempt'] = 'submitting', 'fixture-' + uuid.uuid4().hex
            data['revision'] += 1
            _save(self._directory, data)
            return item['attempt']

    def finish(self, index: int, attempt: str, *, outcome: str, receipt: str | None = None) -> None:
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/1':
                raise ValueError('manual finish unavailable for delivery fixture')
            if type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid fixture item')
            item = data['items'][index]
            if item['state'] != 'submitting' or item['attempt'] != attempt or outcome not in ('accepted', 'unknown'):
                raise ValueError('fixture finish refused')
            item['state'], item['receipt'] = outcome, receipt
            data['revision'] += 1
            _save(self._directory, data)

    def send_due_linkedin(self, index: int, *, now: str, expected_key: dict[str, str],
                          expected_digest: str, transport: Any) -> None:
        """Send once through the built-in fake only; never a real provider."""
        from scripts.social.channels.linkedin.direct import interpret_create
        from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

        if type(transport) is not FakeLinkedInTransport or not isinstance(expected_key, dict):
            raise ValueError('invalid fixture transport or key')
        current = _fixture_time(now)
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] not in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4') or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            snapshot = item['snapshot']
            if (item['state'] != 'prepared' or not item['grant'] or item['key'] != expected_key
                    or item['snapshot_sha256'] != expected_digest or item['key']['platform'] != 'linkedin'
                    or snapshot.get('fixture_schema') not in ('linkedin-v1-facebook-text/1', 'linkedin-v1-facebook-media/1')
                    or _fixture_time(snapshot['scheduled_at']) > current):
                raise ValueError('fixture send refused')
            item['state'], item['claim_mode'], item['attempt'] = 'submitting', 'due', 'fixture-' + uuid.uuid4().hex
            data['revision'] += 1
            _save(self._directory, data)
            status, headers = transport._send(snapshot['candidate'], item['attempt'])
            result = interpret_create(status, headers)
            if result['state'] == 'accepted':
                urn = result['post_urn']
                if any(other['key']['platform'] == 'linkedin' and other['state'] == 'accepted' and isinstance(other['receipt'], dict)
                       and other['receipt']['post_urn'] == urn for other in data['items']):
                    item['state'], item['conflict_urn'] = 'unknown', urn
                else:
                    item['state'] = 'accepted'
                    item['receipt'] = {'post_urn': urn, 'attempt': item['attempt'],
                                       'author': snapshot['author'], 'readback': 'unverified'}
            else:
                item['state'] = 'unknown'
            data['revision'] += 1
            _save(self._directory, data)

    def mark_delivery_unknown(self, index: int, *, expected_key: dict[str, str], attempt: str) -> None:
        """After an abandoned send, preserve its attempt and prohibit another send."""
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] not in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4') or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            if item['state'] != 'submitting' or item['attempt'] != attempt or item['key'] != expected_key:
                raise ValueError('fixture reconciliation refused')
            item['state'] = 'unknown'
            if data['schema'] == 'social-json-fixture/4' and item['key']['platform'] == 'instagram':
                raise ValueError('Instagram recovery requires phase-specific handling')
            data['revision'] += 1
            _save(self._directory, data)

    def send_due_telegram(self, index: int, *, now: str, expected_key: dict[str, str],
                          expected_digest: str, transport: Any) -> None:
        """Send to the in-process Telegram fake after a durable due claim."""
        from scripts.social.telegram_fixture_transport import FakeTelegramTransport, _receipt

        if type(transport) is not FakeTelegramTransport or not isinstance(expected_key, dict):
            raise ValueError('invalid fixture transport or key')
        current = _fixture_time(now)
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] not in ('social-json-fixture/3', 'social-json-fixture/4') or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            snapshot = item['snapshot']
            if (item['state'] != 'prepared' or not item['grant'] or item['key'] != expected_key
                    or item['snapshot_sha256'] != expected_digest or item['key']['platform'] != 'telegram'
                    or snapshot.get('fixture_schema') not in ('telegram-v1-facebook-text/1',
                        'telegram-v1-image/1', 'telegram-v1-video/1')
                    or snapshot['target'].get('purpose') != 'publish'
                    or _fixture_time(snapshot['scheduled_at']) > current):
                raise ValueError('fixture send refused')
            item['state'], item['claim_mode'], item['attempt'] = 'submitting', 'due', 'fixture-' + uuid.uuid4().hex
            data['revision'] += 1
            _save(self._directory, data)
            candidate = snapshot['candidate']
            response = transport._send(candidate, item['attempt'], item['key']['account_id'])
            parsed = _receipt(candidate, response)
            if parsed is None:
                item['state'] = 'unknown'
            else:
                chat, message, kind = parsed
                duplicate = any(other['key']['platform'] == 'telegram' and other['state'] == 'accepted'
                                and (other['receipt']['chat_id'], other['receipt']['message_id']) == (chat, message)
                                for other in data['items'])
                if duplicate:
                    item['state'], item['conflict_telegram'] = 'unknown', [chat, message]
                else:
                    item['state'] = 'accepted'
                    item['receipt'] = {'attempt': item['attempt'], 'account_id': item['key']['account_id'],
                                       'chat_id': chat, 'message_id': message, 'media_kind': kind}
            data['revision'] += 1
            _save(self._directory, data)

    def create_due_instagram(self, index: int, *, now: str, expected_key: dict[str, str],
                             expected_digest: str, transport: Any) -> None:
        """Create a synthetic Instagram container once; never a real API call."""
        from scripts.social.instagram_fixture_transport import FakeInstagramTransport, _fixture_id

        if type(transport) is not FakeInstagramTransport or not isinstance(expected_key, dict):
            raise ValueError('invalid fixture transport or key')
        current = _fixture_time(now)
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/4' or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            snapshot = item['snapshot']
            if (item['state'] != 'prepared' or not item['grant'] or item['key'] != expected_key
                    or item['snapshot_sha256'] != expected_digest or item['key']['platform'] != 'instagram'
                    or snapshot.get('fixture_schema') not in ('instagram-v1-infographic/1', 'instagram-v1-reel/1')
                    or _fixture_time(snapshot['scheduled_at']) > current):
                raise ValueError('fixture create refused')
            item['state'], item['claim_mode'], item['attempt'] = 'submitting', 'due', 'fixture-' + uuid.uuid4().hex
            item['instagram'] = {'phase': 'creating', 'container_id': None, 'media_id': None,
                                 'conflict_container': None, 'conflict_media': None}
            data['revision'] += 1
            _save(self._directory, data)
            container = _fixture_id(transport._create(snapshot['candidate'], item['attempt']))
            if container is None:
                item['state'], item['instagram']['phase'] = 'unknown', 'unknown'
            elif any(other['instagram'] is not None and other['instagram']['container_id'] == container
                     for other in data['items']):
                item['state'], item['instagram']['phase'] = 'unknown', 'unknown'
                item['instagram']['conflict_container'] = container
            else:
                item['instagram']['phase'], item['instagram']['container_id'] = 'waiting', container
            data['revision'] += 1
            _save(self._directory, data)

    def observe_instagram(self, index: int, *, expected_key: dict[str, str], attempt: str, transport: Any) -> bool:
        """Observe a synthetic container; return whether it is ready."""
        from scripts.social.instagram_fixture_transport import FakeInstagramTransport

        if type(transport) is not FakeInstagramTransport:
            raise ValueError('invalid Instagram fixture transport')
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/4' or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            progress = item['instagram']
            if (item['key'] != expected_key or item['attempt'] != attempt or item['state'] != 'submitting'
                    or not isinstance(progress, dict) or progress['phase'] != 'waiting'):
                raise ValueError('Instagram observation refused')
            response = transport._observe()
            if not isinstance(response, dict) or response.get('id') != progress['container_id']:
                return False
            status = response.get('status_code')
            if status == 'FINISHED':
                progress['phase'] = 'ready'
            elif status in ('ERROR', 'EXPIRED'):
                item['state'], progress['phase'] = 'unknown', 'unknown'
            else:
                return False
            data['revision'] += 1
            _save(self._directory, data)
            return status == 'FINISHED'

    def publish_instagram(self, index: int, *, expected_key: dict[str, str], attempt: str, transport: Any) -> None:
        """Publish a ready container through its originating in-process fake."""
        from scripts.social.channels.instagram.direct import preview_publish
        from scripts.social.instagram_fixture_transport import FakeInstagramTransport, _fixture_id

        if type(transport) is not FakeInstagramTransport:
            raise ValueError('invalid Instagram fixture transport')
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/4' or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            progress, snapshot = item['instagram'], item['snapshot']
            if (item['key'] != expected_key or item['attempt'] != attempt or item['state'] != 'submitting'
                    or not isinstance(progress, dict) or progress['phase'] != 'ready'
                    or transport._bindings.get(attempt) != progress['container_id']):
                raise ValueError('Instagram publish refused')
            candidate = preview_publish(user_id=snapshot['user_id'], api_version=snapshot['api_version'],
                                        creation_id=progress['container_id'])
            progress['phase'] = 'publishing'
            data['revision'] += 1
            _save(self._directory, data)
            media = _fixture_id(transport._publish(candidate, attempt))
            if media is None:
                item['state'], progress['phase'] = 'unknown', 'unknown'
            elif any(other['instagram'] is not None and other['instagram']['media_id'] == media
                     for other in data['items']):
                item['state'], progress['phase'], progress['conflict_media'] = 'unknown', 'unknown', media
            else:
                item['state'], progress['phase'], progress['media_id'] = 'accepted', 'accepted', media
            data['revision'] += 1
            _save(self._directory, data)

    def mark_instagram_unknown(self, index: int, *, expected_key: dict[str, str],
                               attempt: str, expected_phase: str) -> None:
        """After a stopped writer, lock an uncertain create or publish attempt."""
        if expected_phase not in ('creating', 'publishing'):
            raise ValueError('invalid Instagram recovery phase')
        expected_key = copy.deepcopy(expected_key)
        _directory(self._directory)
        with _locked(self._directory):
            data = self._read()
            if data['schema'] != 'social-json-fixture/4' or type(index) is not int or not 0 <= index < len(data['items']):
                raise ValueError('invalid delivery fixture')
            item = data['items'][index]
            progress = item['instagram']
            if (item['key'] != expected_key or item['attempt'] != attempt or item['state'] != 'submitting'
                    or not isinstance(progress, dict) or progress['phase'] != expected_phase):
                raise ValueError('Instagram recovery refused')
            item['state'], progress['phase'] = 'unknown', 'unknown'
            data['revision'] += 1
            _save(self._directory, data)
