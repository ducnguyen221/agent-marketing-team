"""Disposable SQLite experiment; no V1 migration, real approval or transport.

Caller owns the connection and must supply an isolated synthetic database. This
module never opens paths and its approval/receipt values are not authoritative.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from scripts.social.fixture_ledger import _snapshot_digest

_FIELDS = ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id',
           'platform', 'account_id', 'destination_id', 'occurrence_key')
_DDL = '''CREATE TABLE destination_fixture_intents (
    intent_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, post_id TEXT NOT NULL,
    platform TEXT NOT NULL, account_id TEXT NOT NULL, destination_id TEXT NOT NULL,
    occurrence_key TEXT NOT NULL, snapshot_json TEXT NOT NULL, snapshot_digest TEXT NOT NULL,
    version INTEGER NOT NULL, grant_version INTEGER, state TEXT NOT NULL, attempt_id TEXT,
    remote_id TEXT, conflict_remote_id TEXT,
    UNIQUE(platform,account_id,remote_id),
    UNIQUE(station_id,channel_id,campaign_id,content_id,post_id,platform,destination_id,occurrence_key),
    UNIQUE(station_id,channel_id,campaign_id,content_id,post_id,platform,account_id,destination_id,occurrence_key))'''
_REEL_DDL = '''CREATE TABLE reel_fixture_progress (
    intent_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE,
    phase TEXT NOT NULL, video_id TEXT UNIQUE)'''
_LINKEDIN_DDL = '''CREATE TABLE linkedin_fixture_receipts (
    intent_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE,
    post_urn TEXT NOT NULL UNIQUE, readback TEXT NOT NULL,
    previously_reported_published INTEGER NOT NULL)'''
_LINKEDIN_MEDIA_DDL = '''CREATE TABLE linkedin_fixture_media_bindings (
    media_urn TEXT PRIMARY KEY, author TEXT NOT NULL, kind TEXT NOT NULL,
    station_id TEXT NOT NULL, channel_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
    content_id TEXT NOT NULL, post_id TEXT NOT NULL, relative_path TEXT NOT NULL,
    asset_id TEXT NOT NULL)'''
_INSTAGRAM_DDL = '''CREATE TABLE instagram_fixture_progress (
    intent_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE, phase TEXT NOT NULL,
    container_id TEXT UNIQUE, media_id TEXT UNIQUE)'''
_LINKEDIN_SCHEMAS = ('linkedin-intent/1', 'linkedin-v1-facebook-text/1', 'linkedin-v1-facebook-media/1')
_INSTAGRAM_V1_SCHEMAS = ('instagram-v1-infographic/1', 'instagram-v1-reel/1')
_SEAL = object()
_GROUP_UI_SEAL = object()
_SCHEDULE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})\Z')


def _fixture_time(value: Any) -> datetime:
    if not isinstance(value, str) or not _SCHEDULE.fullmatch(value):
        raise ValueError('invalid fixture time')
    if not value.endswith('Z'):
        offset = value[-6:]
        if int(offset[1:3]) > 23 or int(offset[4:6]) > 59 or offset == '-00:00':
            raise ValueError('invalid fixture time')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError('invalid fixture time') from None


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate fixture field')
        result[name] = value
    return result


def _verified_snapshot(destination: str, raw: str, digest: str) -> dict[str, Any]:
    try:
        snapshot = json.loads(raw, object_pairs_hook=_unique_json)
        if (not isinstance(snapshot, dict) or set(snapshot) != {'destination_id', 'payload'}
                or snapshot['destination_id'] != destination or not isinstance(snapshot['payload'], dict)
                or _snapshot_digest(snapshot) != digest):
            raise ValueError('fixture snapshot mismatch')
        return snapshot
    except (ValueError, TypeError, RecursionError):
        raise ValueError('invalid fixture schedule snapshot') from None


def _snapshot_schedule(destination: str, raw: str, digest: str) -> datetime:
    snapshot = _verified_snapshot(destination, raw, digest)
    return _fixture_time(snapshot['payload'].get('scheduled_at'))


def _bound_snapshot(snapshot: Any, *, destination: str, account: str, platform: str,
                    content: str, campaign: str, channel: str, post: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError('invalid fixture snapshot')
    snapshot = copy.deepcopy(snapshot)
    for field, expected in (('destination_id', destination), ('account_id', account), ('platform', platform)):
        if field in snapshot and snapshot[field] != expected:
            raise ValueError('fixture snapshot target mismatch')
    _validate_platform(snapshot, platform=platform, account=account, destination=destination, content=content, campaign=campaign,
                       channel=channel, post=post)
    return {'destination_id': destination, 'payload': snapshot}


def _validate_platform(payload: dict[str, Any], *, platform: str, account: str, destination: str,
                       content: str, campaign: str, channel: str, post: str) -> None:
    if (account.startswith(('fixture-linkedin-account-', 'fixture-linkedin-org-account-'))
            or destination.startswith(('fixture-linkedin-person-', 'fixture-linkedin-org-'))
            or payload.get('fixture_schema') in _LINKEDIN_SCHEMAS) and platform != 'linkedin':
        raise ValueError('invalid LinkedIn fixture platform')
    if (destination.startswith('fixture-group-') or 'v1_binding' in payload) and (
            platform != 'facebook' or not destination.startswith('fixture-group-')):
        raise ValueError('invalid Group fixture platform')
    if (destination.startswith('fixture-discord-channel-') or account.startswith('fixture-discord-bot-')
            or payload.get('fixture_schema') == 'discord-v1-facebook-text/1') and platform != 'discord':
        raise ValueError('invalid Discord fixture platform')
    if (destination.startswith('fixture-x-profile-') or account.startswith('fixture-x-account-')
            or payload.get('fixture_schema') in ('x-v1-facebook-text/1', 'x-v1-facebook-media/1')) and platform != 'x':
        raise ValueError('invalid X fixture platform')
    if (destination.startswith('fixture-telegram-channel-') or account.startswith('fixture-telegram-publish-bot-')
            or payload.get('fixture_schema') in ('telegram-v1-facebook-text/1', 'telegram-v1-image/1',
                                                 'telegram-v1-video/1')) and platform != 'telegram':
        raise ValueError('invalid Telegram fixture platform')
    if platform == 'facebook' and destination.startswith('fixture-group-'):
        from scripts.social.facebook_group_v1_fixture import validate_group_reel_snapshot
        try:
            identity = payload['v1_binding']['identity']
            if (identity['platform'] != platform or identity['account'] != account or identity['destination'] != destination
                    or identity['content'] != content or identity['campaign'] != campaign
                    or identity['brand'] != channel or identity['post'] != post):
                raise ValueError('Group fixture identity mismatch')
            validate_group_reel_snapshot(identity, payload)
        except (TypeError, KeyError, RecursionError, UnicodeError):
            raise ValueError('invalid Group fixture snapshot') from None
    elif platform == 'telegram' and (account.startswith('fixture-telegram-publish-bot-')
                                     or destination.startswith('fixture-telegram-channel-')
                                     or payload.get('fixture_schema') in ('telegram-v1-facebook-text/1',
                                         'telegram-v1-image/1', 'telegram-v1-video/1')):
        try:
            if payload.get('fixture_schema') in ('telegram-v1-image/1', 'telegram-v1-video/1'):
                from scripts.social.telegram_v1_media_fixture import validate_telegram_media_snapshot
                validator = validate_telegram_media_snapshot
            else:
                from scripts.social.telegram_v1_fixture_flow import validate_telegram_snapshot
                validator = validate_telegram_snapshot
            validator(payload, account=account, destination=destination, content=content,
                      campaign=campaign, channel=channel, post=post)
        except (TypeError, KeyError, RecursionError, UnicodeError, StopIteration):
            raise ValueError('invalid Telegram fixture snapshot') from None
    elif platform == 'x' and (account.startswith('fixture-x-account-')
                              or destination.startswith('fixture-x-profile-')
                              or payload.get('fixture_schema') in ('x-v1-facebook-text/1', 'x-v1-facebook-media/1')):
        try:
            if payload.get('fixture_schema') == 'x-v1-facebook-media/1':
                from scripts.social.x_v1_media_fixture import validate_x_media_snapshot
                validator = validate_x_media_snapshot
            else:
                from scripts.social.x_v1_fixture_flow import validate_x_v1_snapshot
                validator = validate_x_v1_snapshot
            validator(payload, account=account, destination=destination, content=content,
                      campaign=campaign, channel=channel, post=post)
        except (TypeError, KeyError, RecursionError, UnicodeError, StopIteration):
            raise ValueError('invalid X fixture snapshot') from None
    elif platform == 'discord' and (account.startswith('fixture-discord-bot-')
                                    or destination.startswith('fixture-discord-channel-')
                                    or payload.get('fixture_schema') == 'discord-v1-facebook-text/1'):
        from scripts.social.discord_v1_fixture_flow import validate_discord_v1_snapshot
        try:
            validate_discord_v1_snapshot(payload, account=account, destination=destination, content=content,
                                         campaign=campaign, channel=channel, post=post)
        except (TypeError, KeyError, RecursionError, UnicodeError, StopIteration):
            raise ValueError('invalid Discord fixture snapshot') from None
    elif platform == 'tiktok':
        from scripts.social.tiktok_fixture_flow import validate_tiktok_snapshot
        try:
            if payload.get('fixture_schema') in ('tiktok-v1-short-inbox/1', 'tiktok-v1-short-direct/1'):
                from scripts.social.tiktok_v1_fixture_flow import validate_tiktok_v1_snapshot
                validate_tiktok_v1_snapshot(payload, account=account, destination=destination, content=content,
                                            campaign=campaign, channel=channel, post=post)
            else:
                validate_tiktok_snapshot(payload, account=account, destination=destination)
        except (TypeError, KeyError, RecursionError, UnicodeError):
            raise ValueError('invalid TikTok fixture snapshot') from None
    elif platform == 'instagram':
        from scripts.social.instagram_fixture_flow import validate_instagram_snapshot
        try:
            if payload.get('fixture_schema') in ('instagram-v1-infographic/1', 'instagram-v1-reel/1'):
                from scripts.social.instagram_v1_fixture_flow import validate_instagram_v1_snapshot
                validate_instagram_v1_snapshot(payload, account=account, destination=destination, content=content,
                                               campaign=campaign, channel=channel, post=post)
            else:
                validate_instagram_snapshot(payload, account=account, destination=destination, content=content, campaign=campaign)
        except (TypeError, KeyError, RecursionError, UnicodeError):
            raise ValueError('invalid Instagram fixture snapshot') from None
    elif platform == 'threads' and (account.startswith('fixture-threads-account-')
                                    or destination.startswith('fixture-threads-')):
        from scripts.social.threads_fixture_flow import validate_threads_snapshot
        try:
            if payload.get('fixture_schema') == 'threads-v1-facebook-text/1':
                from scripts.social.threads_v1_fixture_flow import validate_threads_v1_snapshot
                validate_threads_v1_snapshot(payload, account=account, destination=destination, content=content,
                                             campaign=campaign, channel=channel, post=post)
            else:
                validate_threads_snapshot(payload, account=account, destination=destination, content=content, campaign=campaign)
        except (TypeError, KeyError, RecursionError, UnicodeError):
            raise ValueError('invalid Threads fixture snapshot') from None
    elif platform == 'linkedin' and (account.startswith(('fixture-linkedin-account-', 'fixture-linkedin-org-account-'))
                                     or destination.startswith(('fixture-linkedin-person-', 'fixture-linkedin-org-'))
                                     or payload.get('fixture_schema') in _LINKEDIN_SCHEMAS):
        from scripts.social.linkedin_fixture_flow import validate_linkedin_snapshot
        try:
            if payload.get('fixture_schema') == 'linkedin-v1-facebook-media/1':
                from scripts.social.linkedin_v1_media_fixture import validate_linkedin_v1_media_snapshot
                validate_linkedin_v1_media_snapshot(payload, account=account, destination=destination, content=content,
                                                    campaign=campaign, channel=channel, post=post)
            elif payload.get('fixture_schema') == 'linkedin-v1-facebook-text/1':
                from scripts.social.linkedin_v1_fixture_flow import validate_linkedin_v1_snapshot
                validate_linkedin_v1_snapshot(payload, account=account, destination=destination, content=content,
                                              campaign=campaign, channel=channel, post=post)
            else:
                validate_linkedin_snapshot(payload, account=account, destination=destination, content=content, campaign=campaign)
        except (TypeError, KeyError, RecursionError, UnicodeError):
            raise ValueError('invalid LinkedIn fixture snapshot') from None
    elif platform == 'youtube' and (account.startswith('fixture-youtube-account-')
                                    or destination.startswith('fixture-youtube-channel-')):
        from scripts.social.youtube_fixture_flow import validate_youtube_snapshot
        try:
            validate_youtube_snapshot(payload, account=account, destination=destination, content=content,
                                      campaign=campaign, channel=channel, post=post)
        except (TypeError, KeyError, RecursionError, UnicodeError, IndexError, StopIteration):
            raise ValueError('invalid YouTube fixture snapshot') from None
    elif platform == 'facebook' and (account.startswith('fixture-facebook-account-')
                                     or destination.startswith('fixture-facebook-page-')):
        from scripts.social.facebook_fixture_flow import validate_facebook_snapshot
        try:
            validate_facebook_snapshot(payload, account=account, destination=destination, content=content,
                                       campaign=campaign, channel=channel, post=post)
        except (TypeError, KeyError, RecursionError, UnicodeError, IndexError):
            raise ValueError('invalid Facebook fixture snapshot') from None


class DestinationFixtureLedger:
    """Destination-aware fixture state in an explicitly disposable database."""

    def __init__(self, connection: sqlite3.Connection, *, seal: object) -> None:
        if seal is not _SEAL:
            raise ValueError('use fixture initializer')
        self._connection = connection

    @staticmethod
    def _idle(connection: sqlite3.Connection) -> None:
        if (not isinstance(connection, sqlite3.Connection) or connection.in_transaction
                or getattr(connection, 'autocommit', None) is True):
            raise ValueError('idle fixture connection required')
        if connection.execute("SELECT 1 FROM sqlite_temp_master WHERE name COLLATE NOCASE IN (?,?,?,?,?)",
                              ('destination_fixture_intents', 'reel_fixture_progress', 'linkedin_fixture_receipts',
                               'linkedin_fixture_media_bindings', 'instagram_fixture_progress')).fetchone():
            raise ValueError('fixture table is shadowed')

    @classmethod
    def initialize(cls, connection: sqlite3.Connection) -> DestinationFixtureLedger:
        cls._idle(connection)
        try:
            connection.execute('BEGIN IMMEDIATE')
            objects = connection.execute("SELECT name FROM main.sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
            if objects or connection.execute('PRAGMA main.user_version').fetchone()[0] != 0:
                raise ValueError('fixture database must be empty')
            connection.execute(_DDL)
            connection.execute(_REEL_DDL)
            connection.execute(_LINKEDIN_DDL)
            connection.execute(_LINKEDIN_MEDIA_DDL)
            connection.execute(_INSTAGRAM_DDL)
            connection.execute('PRAGMA main.user_version=6')
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        return cls(connection, seal=_SEAL)

    @classmethod
    def open(cls, connection: sqlite3.Connection) -> DestinationFixtureLedger:
        cls._idle(connection)
        row = connection.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
                                 ('destination_fixture_intents',)).fetchone()
        objects = connection.execute("SELECT type,name FROM main.sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
        reel = connection.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
                                  ('reel_fixture_progress',)).fetchone()
        linkedin = connection.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
                                      ('linkedin_fixture_receipts',)).fetchone()
        media = connection.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
                                   ('linkedin_fixture_media_bindings',)).fetchone()
        instagram = connection.execute("SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
                                       ('instagram_fixture_progress',)).fetchone()
        version = connection.execute('PRAGMA main.user_version').fetchone()[0]
        expected = {('table', 'destination_fixture_intents'), ('table', 'reel_fixture_progress')}
        if version in (4, 5, 6):
            expected.add(('table', 'linkedin_fixture_receipts'))
        if version in (5, 6):
            expected.add(('table', 'linkedin_fixture_media_bindings'))
        if version == 6:
            expected.add(('table', 'instagram_fixture_progress'))
        if (row is None or row[0] != _DDL or reel is None or reel[0] != _REEL_DDL
                or {tuple(obj) for obj in objects} != expected or version not in (3, 4, 5, 6)
                or (version in (4, 5, 6) and (linkedin is None or linkedin[0] != _LINKEDIN_DDL))
                or (version in (5, 6) and (media is None or media[0] != _LINKEDIN_MEDIA_DDL))
                or (version == 6 and (instagram is None or instagram[0] != _INSTAGRAM_DDL))):
            raise ValueError('fixture schema mismatch')
        return cls(connection, seal=_SEAL)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        con = self._connection
        self._idle(con)
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.execute('COMMIT')
        except BaseException:
            if con.in_transaction:
                con.execute('ROLLBACK')
            raise

    def prepare(self, key: dict[str, str], snapshot: dict[str, Any]) -> str:
        encoded = self._encode_prepare(key, snapshot)
        with self._transaction() as con:
            return self._insert_prepare(con, encoded)

    def prepare_batch(self, entries: list[tuple[dict[str, str], dict[str, Any]]]) -> list[str]:
        """Atomically prepare explicitly supplied synthetic intents, without granting."""
        if not isinstance(entries, list):
            raise ValueError('invalid fixture prepare batch')
        entries = tuple(entries)
        if not 1 <= len(entries) <= 100:
            raise ValueError('invalid fixture prepare batch')
        entries = copy.deepcopy(entries)
        if any(not isinstance(entry, tuple) or len(entry) != 2 for entry in entries):
            raise ValueError('invalid fixture prepare batch')
        encoded = [self._encode_prepare(key, snapshot) for key, snapshot in entries]
        target_indices = [index for index, field in enumerate(_FIELDS) if field != 'account_id']
        targets = [tuple(item[0][index] for index in target_indices) for item in encoded]
        if len(set(targets)) != len(targets):
            raise ValueError('duplicate fixture destination')
        with self._transaction() as con:
            return [self._insert_prepare(con, item) for item in encoded]

    @staticmethod
    def _encode_prepare(key: dict[str, str], snapshot: dict[str, Any]) -> tuple[tuple[str, ...], str, str]:
        if isinstance(key, dict):
            key = dict(key)
        if (not isinstance(key, dict) or set(key) != set(_FIELDS)
                or any(not isinstance(key[field], str) or not re.fullmatch(r'fixture-[A-Za-z0-9][A-Za-z0-9_.-]{0,247}', key[field])
                       for field in _FIELDS
                       if field != 'platform')
                or key['platform'] not in ('facebook', 'youtube', 'instagram', 'linkedin', 'threads',
                                           'discord', 'x', 'tiktok', 'telegram')):
            raise ValueError('invalid synthetic destination key')
        values = tuple(key[field] for field in _FIELDS)
        if key['platform'] == 'facebook' and key['destination_id'].startswith('fixture-group-'):
            try:
                identity = snapshot['v1_binding']['identity']
                if identity['station'] != key['station_id'] or identity['occurrence'] != key['occurrence_key']:
                    raise ValueError('Group fixture occurrence mismatch')
            except (KeyError, TypeError):
                raise ValueError('invalid Group fixture binding') from None
        bound = _bound_snapshot(snapshot, destination=key['destination_id'], account=key['account_id'], platform=key['platform'],
                                content=key['content_id'], campaign=key['campaign_id'], channel=key['channel_id'], post=key['post_id'])
        digest = _snapshot_digest(bound)
        serialized = json.dumps(bound, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
        return values, digest, serialized

    @staticmethod
    def _media_binding(con: sqlite3.Connection, payload: dict[str, Any], *, station: str, channel: str,
                       campaign: str, content: str, post: str, create: bool) -> None:
        schema = payload.get('fixture_schema')
        if schema not in ('linkedin-v1-facebook-media/1', 'linkedin-intent/1') or payload.get('media_kind') is None:
            return
        if con.execute('PRAGMA main.user_version').fetchone()[0] not in (5, 6):
            if schema == 'linkedin-v1-facebook-media/1':
                raise ValueError('LinkedIn media requires fixture v5')
            return
        asset = payload['manifest'][0] if schema == 'linkedin-v1-facebook-media/1' else None
        source = (station, channel, campaign, content, post, asset['relative_path'], asset['id']) if asset else ('',) * 7
        values = (payload['media_urn'], payload['author'], payload['media_kind'], station, channel, campaign,
                  content, post, asset['relative_path'], asset['id']) if asset else (payload['media_urn'], payload['author'], payload['media_kind'], *source)
        row = con.execute('SELECT * FROM main.linkedin_fixture_media_bindings WHERE media_urn=?', (values[0],)).fetchone()
        if row is None:
            if not create:
                raise ValueError('LinkedIn media binding missing')
            con.execute('INSERT INTO main.linkedin_fixture_media_bindings VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        elif tuple(row[:3]) != values[:3]:
            raise ValueError('LinkedIn media binding conflict')
        elif asset and tuple(row[3:]) == ('',) * 7:
            if not create:
                raise ValueError('LinkedIn media source binding missing')
            con.execute('UPDATE main.linkedin_fixture_media_bindings SET station_id=?,channel_id=?,campaign_id=?,'
                        'content_id=?,post_id=?,relative_path=?,asset_id=? WHERE media_urn=?', (*source, values[0]))
        elif asset and tuple(row) != values:
            raise ValueError('LinkedIn media binding conflict')

    @staticmethod
    def _insert_prepare(con: sqlite3.Connection, encoded: tuple[tuple[str, ...], str, str]) -> str:
        values, digest, serialized = encoded
        key = dict(zip(_FIELDS, values))
        payload = json.loads(serialized)['payload']
        DestinationFixtureLedger._media_binding(con, payload, station=key['station_id'], channel=key['channel_id'],
                                                campaign=key['campaign_id'], content=key['content_id'],
                                                post=key['post_id'], create=True)
        where = ' AND '.join(f'{field}=?' for field in _FIELDS)
        row = con.execute(f'SELECT intent_id,snapshot_digest FROM main.destination_fixture_intents WHERE {where}', values).fetchone()
        if row:
            if row[1] != digest:
                raise ValueError('fixture intent conflict')
            return row[0]
        target_fields = tuple(field for field in _FIELDS if field != 'account_id')
        target_where = ' AND '.join(f'{field}=?' for field in target_fields)
        target_values = tuple(value for field, value in zip(_FIELDS, values) if field != 'account_id')
        if con.execute(f'SELECT 1 FROM main.destination_fixture_intents WHERE {target_where}', target_values).fetchone():
            raise ValueError('fixture destination already owned')
        intent_id = str(uuid.uuid4())
        columns = ','.join(_FIELDS)
        placeholders = ','.join('?' for _ in _FIELDS)
        con.execute(f'INSERT INTO main.destination_fixture_intents(intent_id,{columns},snapshot_json,snapshot_digest,version,state) '
                    f'VALUES (?,{placeholders},?,?,1,?)', (intent_id, *values, serialized, digest, 'prepared'))
        return intent_id

    def get(self, intent_id: str) -> dict[str, Any]:
        self._idle(self._connection)
        cursor = self._connection.execute('SELECT * FROM main.destination_fixture_intents WHERE intent_id=?', (intent_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError('fixture intent missing')
        return dict(zip((column[0] for column in cursor.description), row))

    def approve(self, intent_id: str, *, expected_version: int) -> None:
        """Record a synthetic grant; this cannot stand for a human approval."""
        self.approve_batch([(intent_id, expected_version)])

    def approve_batch(self, entries: list[tuple[str, int]]) -> None:
        """Atomically grant explicitly listed fixture intents, possibly across posts."""
        if not isinstance(entries, list):
            raise ValueError('invalid fixture grant batch')
        entries = tuple(entries)
        if (not 1 <= len(entries) <= 1000
                or any(not isinstance(entry, tuple) or len(entry) != 2
                       or not isinstance(entry[0], str) or not entry[0]
                       or type(entry[1]) is not int or not 1 <= entry[1] < 2**63 for entry in entries)
                or len({entry[0] for entry in entries}) != len(entries)):
            raise ValueError('invalid fixture grant batch')
        with self._transaction() as con:
            for intent_id, expected_version in entries:
                self._approve_one(con, intent_id, expected_version)

    @staticmethod
    def _approve_one(con: sqlite3.Connection, intent_id: str, expected_version: int) -> None:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError('invalid fixture version')
        row = con.execute('SELECT destination_id,snapshot_json,snapshot_digest,platform,account_id,content_id,campaign_id,channel_id,post_id,station_id,occurrence_key '
                          'FROM main.destination_fixture_intents WHERE intent_id=?', (intent_id,)).fetchone()
        if row is None:
            raise ValueError('fixture grant refused')
        snapshot = _verified_snapshot(row[0], row[1], row[2])
        _validate_platform(snapshot['payload'], platform=row[3], account=row[4], destination=row[0], content=row[5], campaign=row[6],
                           channel=row[7], post=row[8])
        if row[3] == 'facebook' and row[0].startswith('fixture-group-'):
            identity = snapshot['payload']['v1_binding']['identity']
            if identity['station'] != row[9] or identity['occurrence'] != row[10]:
                raise ValueError('Group fixture occurrence mismatch')
        result = con.execute("UPDATE main.destination_fixture_intents SET grant_version=version "
                             "WHERE intent_id=? AND state='prepared' AND version=? AND grant_version IS NULL",
                             (intent_id, expected_version))
        if result.rowcount != 1:
            raise ValueError('fixture grant refused')

    def revoke(self, intent_id: str, *, expected_version: int) -> None:
        """Revoke a prepared fixture grant and invalidate stale version references."""
        if (not isinstance(intent_id, str) or not intent_id or type(expected_version) is not int
                or not 1 <= expected_version < 2**63 - 1):
            raise ValueError('invalid fixture revocation')
        with self._transaction() as con:
            result = con.execute("UPDATE main.destination_fixture_intents SET grant_version=NULL,version=version+1 "
                                 "WHERE intent_id=? AND state='prepared' AND version=? AND grant_version=version",
                                 (intent_id, expected_version))
            if result.rowcount != 1:
                raise ValueError('fixture revocation refused')

    def revise(self, intent_id: str, snapshot: dict[str, Any]) -> None:
        with self._transaction() as con:
            row = con.execute('SELECT destination_id,snapshot_digest,state,account_id,platform,content_id,campaign_id,channel_id,post_id,snapshot_json,station_id,occurrence_key FROM main.destination_fixture_intents WHERE intent_id=?',
                              (intent_id,)).fetchone()
            if row is None or row[2] != 'prepared':
                raise ValueError('fixture revision refused')
            previous = _verified_snapshot(row[0], row[9], row[1])['payload']
            if row[4] == 'facebook' and row[0].startswith('fixture-group-'):
                try:
                    identity = snapshot['v1_binding']['identity']
                    if identity['station'] != row[10] or identity['occurrence'] != row[11]:
                        raise ValueError('Group fixture occurrence mismatch')
                except (KeyError, TypeError):
                    raise ValueError('invalid Group fixture binding') from None
            if (row[4] in ('instagram', 'tiktok', 'linkedin', 'threads', 'discord', 'x', 'telegram') and (not isinstance(snapshot, dict)
                    or previous.get('fixture_schema') != snapshot.get('fixture_schema'))):
                raise ValueError('fixture revision schema mismatch')
            bound = _bound_snapshot(snapshot, destination=row[0], account=row[3], platform=row[4], content=row[5], campaign=row[6],
                                    channel=row[7], post=row[8])
            self._media_binding(con, bound['payload'], station=row[10], channel=row[7], campaign=row[6],
                                content=row[5], post=row[8], create=True)
            digest = _snapshot_digest(bound)
            if digest != row[1]:
                serialized = json.dumps(bound, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
                con.execute('UPDATE main.destination_fixture_intents SET snapshot_json=?,snapshot_digest=?,version=version+1,'
                            'grant_version=NULL WHERE intent_id=?', (serialized, digest, intent_id))

    def claim(self, intent_id: str, *, expected_version: int) -> str:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError('invalid fixture version')
        attempt = str(uuid.uuid4())
        with self._transaction() as con:
            row = con.execute('SELECT destination_id,snapshot_json,snapshot_digest,platform,account_id,content_id,campaign_id,channel_id,post_id FROM main.destination_fixture_intents '
                              'WHERE intent_id=?', (intent_id,)).fetchone()
            if row is None:
                raise ValueError('fixture claim refused')
            if row[3] == 'facebook' and row[0].startswith('fixture-group-'):
                raise ValueError('Group fixture requires UI confirmation')
            snapshot = _verified_snapshot(row[0], row[1], row[2])
            _validate_platform(snapshot['payload'], platform=row[3], account=row[4], destination=row[0], content=row[5], campaign=row[6],
                               channel=row[7], post=row[8])
            if 'scheduled_at' in snapshot['payload']:
                raise ValueError('scheduled fixture requires due claim')
            result = con.execute("UPDATE main.destination_fixture_intents SET state='submitting',attempt_id=? "
                                 "WHERE intent_id=? AND state='prepared' AND version=? AND grant_version=version",
                                 (attempt, intent_id, expected_version))
            if result.rowcount != 1:
                raise ValueError('fixture claim refused')
        return attempt

    def claim_group_fixture(self, intent_id: str, *, expected_version: int, snapshot: dict[str, Any],
                            _ui_seal: object | None = None, _attempt_id: str | None = None) -> str:
        """Claim a synthetic Group occurrence after the test UI session checks its view."""
        if _ui_seal is not _GROUP_UI_SEAL or type(expected_version) is not int or expected_version < 1:
            raise ValueError('Group fixture UI required')
        attempt = str(uuid.uuid4()) if _attempt_id is None else _attempt_id
        try:
            if not isinstance(attempt, str) or str(uuid.UUID(attempt, version=4)) != attempt:
                raise ValueError('invalid Group fixture attempt')
        except (ValueError, AttributeError):
            raise ValueError('invalid Group fixture attempt') from None
        with self._transaction() as con:
            row = con.execute('SELECT destination_id,snapshot_json,snapshot_digest,platform,account_id,content_id,'
                              'campaign_id,channel_id,post_id,station_id,occurrence_key FROM main.destination_fixture_intents '
                              'WHERE intent_id=? AND state=\'prepared\' AND version=? AND grant_version=version',
                              (intent_id, expected_version)).fetchone()
            if row is None or row[3] != 'facebook' or not row[0].startswith('fixture-group-'):
                raise ValueError('Group fixture claim refused')
            stored = _verified_snapshot(row[0], row[1], row[2])
            if _snapshot_digest({'destination_id': row[0], 'payload': snapshot}) != row[2]:
                raise ValueError('Group fixture snapshot changed')
            _validate_platform(stored['payload'], platform=row[3], account=row[4], destination=row[0], content=row[5],
                               campaign=row[6], channel=row[7], post=row[8])
            identity = stored['payload']['v1_binding']['identity']
            if identity['station'] != row[9] or identity['occurrence'] != row[10]:
                raise ValueError('Group fixture occurrence mismatch')
            if con.execute('SELECT 1 FROM main.destination_fixture_intents WHERE attempt_id=?', (attempt,)).fetchone():
                raise ValueError('Group fixture attempt already used')
            updated = con.execute("UPDATE main.destination_fixture_intents SET state='submitting',attempt_id=? "
                                  "WHERE intent_id=? AND state='prepared' AND version=? AND grant_version=version",
                                  (attempt, intent_id, expected_version))
            if updated.rowcount != 1:
                raise ValueError('Group fixture claim refused')
        return attempt

    def recover_group_fixture(self, intent_id: str, *, attempt: str) -> dict[str, str]:
        """Read a committed synthetic Group attempt; never reopen or alter it."""
        if not isinstance(attempt, str):
            raise ValueError('Group fixture recovery unavailable')
        self._idle(self._connection)
        row = self._connection.execute('SELECT destination_id,snapshot_json,snapshot_digest,platform,account_id,content_id,'
                                       'campaign_id,channel_id,post_id,station_id,occurrence_key,state,attempt_id '
                                       'FROM main.destination_fixture_intents WHERE intent_id=?', (intent_id,)).fetchone()
        if (row is None or row[3] != 'facebook' or not row[0].startswith('fixture-group-')
                or row[12] != attempt or row[11] not in ('submitting', 'unknown', 'awaiting_moderation')):
            raise ValueError('Group fixture recovery unavailable')
        snapshot = _verified_snapshot(row[0], row[1], row[2])
        _validate_platform(snapshot['payload'], platform=row[3], account=row[4], destination=row[0],
                           content=row[5], campaign=row[6], channel=row[7], post=row[8])
        identity = snapshot['payload']['v1_binding']['identity']
        if identity['station'] != row[9] or identity['occurrence'] != row[10]:
            raise ValueError('Group fixture recovery unavailable')
        return {'intent': row[11], 'preview': 'recovered_fixture'}

    def claim_due(self, intent_id: str, *, expected_version: int, now: str) -> str:
        """Atomically claim one due synthetic intent; never contact a provider."""
        return self._claim_due(intent_id, expected_version=expected_version, now=now, linkedin_only=False)[0]

    def claim_due_linkedin_fixture(self, intent_id: str, *, expected_version: int,
                                   now: str) -> tuple[str, dict[str, Any]]:
        """Atomically claim a LinkedIn fixture and return its verified candidate."""
        attempt, candidate = self._claim_due(intent_id, expected_version=expected_version, now=now, linkedin_only=True)
        if candidate is None:
            raise ValueError('LinkedIn fixture candidate missing')
        return attempt, candidate

    def claim_due_telegram_fixture(self, intent_id: str, *, expected_version: int,
                                   now: str) -> tuple[str, dict[str, Any], str]:
        """Atomically claim a Telegram publisher fixture and its candidate."""
        attempt, candidate = self._claim_due(intent_id, expected_version=expected_version, now=now,
                                             linkedin_only=False, telegram_only=True)
        if candidate is None:
            raise ValueError('Telegram fixture candidate missing')
        return attempt, candidate['candidate'], candidate['account_id']

    def claim_due_instagram_fixture(self, intent_id: str, *, expected_version: int,
                                    now: str) -> tuple[str, dict[str, Any]]:
        """Claim an Instagram V1 fixture and return the approved container candidate."""
        attempt, candidate = self._claim_due(intent_id, expected_version=expected_version, now=now,
                                             linkedin_only=False, instagram_only=True)
        if candidate is None:
            raise ValueError('Instagram fixture candidate missing')
        return attempt, candidate

    def _claim_due(self, intent_id: str, *, expected_version: int, now: str,
                   linkedin_only: bool, telegram_only: bool = False,
                   instagram_only: bool = False) -> tuple[str, dict[str, Any] | None]:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError('invalid fixture version')
        current_time = _fixture_time(now)
        attempt = str(uuid.uuid4())
        with self._transaction() as con:
            row = con.execute('SELECT destination_id,snapshot_json,snapshot_digest,version,grant_version,state,platform,account_id,content_id,campaign_id,channel_id,post_id,station_id '
                              'FROM main.destination_fixture_intents WHERE intent_id=?', (intent_id,)).fetchone()
            if (row is None or row[3] != expected_version or row[4] != row[3] or row[5] != 'prepared'):
                raise ValueError('fixture due claim refused')
            if row[6] == 'facebook' and row[0].startswith('fixture-group-'):
                raise ValueError('Group fixture requires UI confirmation')
            snapshot = _verified_snapshot(row[0], row[1], row[2])
            _validate_platform(snapshot['payload'], platform=row[6], account=row[7], destination=row[0], content=row[8], campaign=row[9],
                               channel=row[10], post=row[11])
            if linkedin_only and (row[6] != 'linkedin' or snapshot['payload'].get('fixture_schema') not in _LINKEDIN_SCHEMAS):
                raise ValueError('LinkedIn fixture claim refused')
            if telegram_only and (row[6] != 'telegram' or snapshot['payload'].get('fixture_schema') not in
                                  ('telegram-v1-facebook-text/1', 'telegram-v1-image/1', 'telegram-v1-video/1')):
                raise ValueError('Telegram fixture claim refused')
            if instagram_only and (row[6] != 'instagram' or snapshot['payload'].get('fixture_schema') not in _INSTAGRAM_V1_SCHEMAS):
                raise ValueError('Instagram fixture claim refused')
            if (row[6] == 'instagram' and snapshot['payload'].get('fixture_schema') in _INSTAGRAM_V1_SCHEMAS
                    and con.execute('PRAGMA main.user_version').fetchone()[0] != 6):
                raise ValueError('Instagram V1 session requires fixture v6')
            if (row[6] == 'linkedin' and snapshot['payload'].get('fixture_schema') in _LINKEDIN_SCHEMAS
                    and con.execute('PRAGMA main.user_version').fetchone()[0] not in (4, 5, 6)):
                raise ValueError('LinkedIn claim requires fixture v4')
            self._media_binding(con, snapshot['payload'], station=row[12], channel=row[10], campaign=row[9],
                                content=row[8], post=row[11], create=False)
            scheduled_at = _snapshot_schedule(row[0], row[1], row[2])
            if scheduled_at > current_time:
                raise ValueError('fixture not due')
            if snapshot['payload'].get('fixture_schema') == 'x-v1-facebook-media/1':
                from scripts.social.x_v1_media_fixture import require_ready_at
                require_ready_at(snapshot['payload'], now)
            result = con.execute("UPDATE main.destination_fixture_intents SET state='submitting',attempt_id=? "
                                 "WHERE intent_id=? AND state='prepared' AND version=? AND grant_version=version",
                                 (attempt, intent_id, expected_version))
            if result.rowcount != 1:
                raise ValueError('fixture due claim refused')
            if row[6] == 'instagram' and snapshot['payload'].get('fixture_schema') in _INSTAGRAM_V1_SCHEMAS:
                con.execute("INSERT INTO main.instagram_fixture_progress(intent_id,attempt_id,phase) VALUES (?,?,'creating')",
                            (intent_id, attempt))
            if (row[6] == 'facebook' and row[7].startswith('fixture-facebook-account-')
                    and row[0].startswith('fixture-facebook-page-')
                    and snapshot['payload'].get('fixture_schema') == 'facebook-native-intent/1'
                    and snapshot['payload'].get('media_type') == 'REEL'):
                con.execute("INSERT INTO main.reel_fixture_progress(intent_id,attempt_id,phase) VALUES (?,?,'start_pending')",
                            (intent_id, attempt))
        if telegram_only:
            return attempt, {'candidate': copy.deepcopy(snapshot['payload']['candidate']), 'account_id': row[7]}
        return attempt, copy.deepcopy(snapshot['payload']['candidate']) if linkedin_only or instagram_only else None

    def scan_due(self, *, now: str) -> dict[str, list[str]]:
        """List due fixture IDs and invalid schedules; claim_due rechecks each."""
        current_time = _fixture_time(now)
        due: list[tuple[datetime, str]] = []
        invalid: list[str] = []
        with self._transaction() as con:
            rows = con.execute("SELECT intent_id,destination_id,snapshot_json,snapshot_digest,platform,account_id,content_id,campaign_id,channel_id,post_id,station_id "
                               "FROM main.destination_fixture_intents WHERE state='prepared' "
                               "AND grant_version=version AND NOT (platform='facebook' AND destination_id GLOB 'fixture-group-*') "
                               "ORDER BY intent_id LIMIT 1001").fetchall()
            if len(rows) > 1000:
                raise ValueError('fixture scan limit exceeded')
            for intent_id, destination, raw, digest, platform, account, content, campaign, channel, post, station in rows:
                try:
                    snapshot = _verified_snapshot(destination, raw, digest)
                    _validate_platform(snapshot['payload'], platform=platform, account=account, destination=destination,
                                       content=content, campaign=campaign, channel=channel, post=post)
                    if (platform == 'linkedin' and snapshot['payload'].get('fixture_schema') in _LINKEDIN_SCHEMAS
                            and con.execute('PRAGMA main.user_version').fetchone()[0] not in (4, 5, 6)):
                        raise ValueError('LinkedIn claim requires fixture v4')
                    if (platform == 'instagram' and snapshot['payload'].get('fixture_schema') in _INSTAGRAM_V1_SCHEMAS
                            and con.execute('PRAGMA main.user_version').fetchone()[0] != 6):
                        raise ValueError('Instagram V1 session requires fixture v6')
                    self._media_binding(con, snapshot['payload'], station=station, channel=channel,
                                        campaign=campaign, content=content, post=post, create=False)
                    scheduled_at = _snapshot_schedule(destination, raw, digest)
                    if scheduled_at <= current_time and snapshot['payload'].get('fixture_schema') == 'x-v1-facebook-media/1':
                        from scripts.social.x_v1_media_fixture import require_ready_at
                        require_ready_at(snapshot['payload'], now)
                except ValueError:
                    invalid.append(intent_id)
                    continue
                if scheduled_at <= current_time:
                    due.append((scheduled_at, intent_id))
        return {'due': [intent_id for _, intent_id in sorted(due)], 'invalid': sorted(invalid)}

    def finish(self, intent_id: str, *, attempt: str, destination: str, remote_id: str) -> None:
        if (not isinstance(remote_id, str) or not remote_id.startswith('fixture-') or len(remote_id) > 256):
            raise ValueError('invalid fixture receipt')
        conflict = False
        with self._transaction() as con:
            row = con.execute("SELECT platform,account_id FROM main.destination_fixture_intents "
                              "WHERE intent_id=? AND state='submitting' AND attempt_id=? AND destination_id=? "
                              "AND NOT (platform='facebook' AND destination_id GLOB 'fixture-group-*') "
                              "AND NOT (platform='discord' AND destination_id GLOB 'fixture-discord-channel-*') "
                              "AND NOT (platform='x' AND destination_id GLOB 'fixture-x-profile-*') "
                              "AND NOT (platform='telegram' AND destination_id GLOB 'fixture-telegram-channel-*') "
                              "AND NOT (platform='linkedin' AND (destination_id GLOB 'fixture-linkedin-person-*' "
                              "OR destination_id GLOB 'fixture-linkedin-org-*' OR account_id GLOB 'fixture-linkedin-account-*' "
                              "OR account_id GLOB 'fixture-linkedin-org-account-*')) "
                              "AND NOT EXISTS (SELECT 1 FROM main.reel_fixture_progress r WHERE r.intent_id=destination_fixture_intents.intent_id)",
                              (intent_id, attempt, destination)).fetchone()
            if (row is None or (row[0] == 'x' and remote_id.startswith('fixture-x-post-'))
                    or (row[0] == 'linkedin' and remote_id.startswith('fixture-urn:li:'))
                    or (row[0] == 'instagram' and remote_id.startswith('fixture-instagram-media-'))
                    or (row[0] == 'telegram' and remote_id.startswith('fixture-telegram-message-'))):
                raise ValueError('fixture receipt refused')
            if (row[0] == 'instagram' and con.execute('PRAGMA main.user_version').fetchone()[0] == 6
                    and con.execute('SELECT 1 FROM main.instagram_fixture_progress WHERE intent_id=?', (intent_id,)).fetchone()):
                raise ValueError('Instagram session requires its own receipt')
            conflict = con.execute('SELECT 1 FROM main.destination_fixture_intents '
                                   'WHERE platform=? AND account_id=? AND remote_id=?',
                                   (row[0], row[1], remote_id)).fetchone() is not None
            if conflict:
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?",
                            (remote_id, intent_id))
            else:
                con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?",
                            (remote_id, intent_id))
        if conflict:
            raise ValueError('fixture receipt conflict')

    def finish_linkedin_fixture(self, intent_id: str, *, attempt: str, status: int | None,
                                headers: list[tuple[str, str]]) -> None:
        """Store a synthetic create response for the claimed LinkedIn intent."""
        from scripts.social.channels.linkedin.direct import interpret_create
        receipt = interpret_create(status, headers)
        with self._transaction() as con:
            if con.execute('PRAGMA main.user_version').fetchone()[0] not in (4, 5, 6):
                raise ValueError('LinkedIn receipt requires fixture v4')
            row = con.execute("SELECT destination_id,snapshot_json,snapshot_digest,account_id,content_id,campaign_id,channel_id,post_id "
                              "FROM main.destination_fixture_intents WHERE intent_id=? AND platform='linkedin' "
                              "AND state='submitting' AND attempt_id=? AND grant_version=version", (intent_id, attempt)).fetchone()
            if row is None:
                raise ValueError('LinkedIn fixture receipt refused')
            payload = _verified_snapshot(row[0], row[1], row[2])['payload']
            _validate_platform(payload, platform='linkedin', account=row[3], destination=row[0],
                               content=row[4], campaign=row[5], channel=row[6], post=row[7])
            if payload.get('fixture_schema') not in _LINKEDIN_SCHEMAS:
                raise ValueError('LinkedIn fixture receipt refused')
            if receipt['state'] != 'accepted':
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown' WHERE intent_id=?", (intent_id,))
                return
            urn = receipt['post_urn']
            duplicate = con.execute('SELECT 1 FROM main.linkedin_fixture_receipts WHERE post_urn=?', (urn,)).fetchone()
            if duplicate:
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?",
                            ('fixture-' + urn, intent_id))
                return
            con.execute('INSERT INTO main.linkedin_fixture_receipts VALUES (?,?,?,?,?)',
                        (intent_id, attempt, urn, 'unverified', 0))
            con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?",
                        ('fixture-' + urn, intent_id))

    def get_linkedin_fixture_receipt(self, intent_id: str) -> dict[str, Any]:
        """Read the stored synthetic receipt; never claim publication."""
        self._idle(self._connection)
        if self._connection.execute('PRAGMA main.user_version').fetchone()[0] not in (4, 5, 6):
            raise ValueError('LinkedIn receipt requires fixture v4')
        row = self._connection.execute('SELECT r.post_urn,r.readback,r.previously_reported_published '
                                       'FROM main.linkedin_fixture_receipts r JOIN main.destination_fixture_intents i '
                                       'ON r.intent_id=i.intent_id AND r.attempt_id=i.attempt_id '
                                       "WHERE i.intent_id=? AND i.platform='linkedin' AND i.state='accepted' "
                                       "AND i.grant_version=i.version AND i.remote_id='fixture-' || r.post_urn", (intent_id,)).fetchone()
        if row is None:
            raise ValueError('LinkedIn fixture receipt missing')
        return {'state': 'accepted', 'post_urn': row[0], 'readback': row[1],
                'previously_reported_published': bool(row[2])}

    def observe_linkedin_fixture(self, intent_id: str, *, attempt: str, status: int | None, body: Any) -> None:
        """Record the latest synthetic readback while retaining earlier evidence."""
        from scripts.social.channels.linkedin.direct import observe_post
        with self._transaction() as con:
            if con.execute('PRAGMA main.user_version').fetchone()[0] not in (4, 5, 6):
                raise ValueError('LinkedIn receipt requires fixture v4')
            row = con.execute('SELECT i.destination_id,i.snapshot_json,i.snapshot_digest,i.account_id,i.content_id,'
                              'i.campaign_id,i.channel_id,i.post_id,r.post_urn,r.readback,r.previously_reported_published '
                              'FROM main.destination_fixture_intents i JOIN main.linkedin_fixture_receipts r '
                              'ON r.intent_id=i.intent_id AND r.attempt_id=i.attempt_id '
                              "WHERE i.intent_id=? AND i.attempt_id=? AND i.platform='linkedin' AND i.state='accepted' "
                              "AND i.grant_version=i.version AND i.remote_id='fixture-' || r.post_urn", (intent_id, attempt)).fetchone()
            if row is None:
                raise ValueError('LinkedIn fixture readback refused')
            payload = _verified_snapshot(row[0], row[1], row[2])['payload']
            _validate_platform(payload, platform='linkedin', account=row[3], destination=row[0],
                               content=row[4], campaign=row[5], channel=row[6], post=row[7])
            receipt = {'state': 'accepted', 'post_urn': row[8], 'readback': row[9],
                       'previously_reported_published': bool(row[10])}
            result = observe_post(receipt, status, body, expected_author=payload['author'])
            con.execute('UPDATE main.linkedin_fixture_receipts SET readback=?,previously_reported_published=? WHERE intent_id=?',
                        (result['readback'], int(result['previously_reported_published']), intent_id))

    def finish_telegram_fixture(self, intent_id: str, *, attempt: str, chat_id: str,
                                chat_type: str, message_id: str, media_kind: str | None = None) -> None:
        """Bind a synthetic message receipt to one channel and attempt."""
        from scripts.social.channels.telegram.direct import valid_fixture_chat_id
        if (not valid_fixture_chat_id(chat_id)
                or chat_type != 'channel' or not isinstance(message_id, str)
                or not re.fullmatch(r'[1-9][0-9]{0,19}', message_id)):
            raise ValueError('invalid Telegram fixture receipt')
        remote = 'fixture-telegram-message-' + chat_id[4:] + '-' + message_id
        conflict = False
        with self._transaction() as con:
            row = con.execute("SELECT destination_id,snapshot_json,snapshot_digest,account_id,content_id,campaign_id,channel_id,post_id "
                              "FROM main.destination_fixture_intents WHERE intent_id=? AND platform='telegram' "
                              "AND state='submitting' AND attempt_id=?", (intent_id, attempt)).fetchone()
            if row is None:
                raise ValueError('Telegram fixture receipt refused')
            payload = _verified_snapshot(row[0], row[1], row[2])['payload']
            _validate_platform(payload, platform='telegram', account=row[3], destination=row[0], content=row[4],
                               campaign=row[5], channel=row[6], post=row[7])
            schema = payload.get('fixture_schema')
            expected_kind = {'telegram-v1-facebook-text/1': None, 'telegram-v1-image/1': 'image',
                             'telegram-v1-video/1': 'video'}.get(schema, 'invalid')
            if expected_kind == 'invalid' or media_kind != expected_kind or payload['chat_id'] != chat_id:
                raise ValueError('Telegram fixture channel mismatch')
            conflict = con.execute('SELECT 1 FROM main.destination_fixture_intents WHERE platform=? AND remote_id=?',
                                   ('telegram', remote)).fetchone() is not None
            if conflict:
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?", (remote, intent_id))
            else:
                con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?", (remote, intent_id))
        if conflict:
            raise ValueError('Telegram fixture receipt conflict')

    def finish_x_fixture(self, intent_id: str, *, attempt: str, user_id: str, post_id: str) -> None:
        """Record a synthetic X receipt bound locally to the intended profile."""
        if (not isinstance(user_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', user_id)
                or not isinstance(post_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', post_id)):
            raise ValueError('invalid X fixture receipt')
        remote = 'fixture-x-post-' + post_id
        conflict = False
        with self._transaction() as con:
            row = con.execute("SELECT destination_id,snapshot_json,snapshot_digest,account_id,content_id,campaign_id,channel_id,post_id "
                              "FROM main.destination_fixture_intents WHERE intent_id=? AND platform='x' "
                              "AND state='submitting' AND attempt_id=?", (intent_id, attempt)).fetchone()
            if row is None:
                raise ValueError('X fixture receipt refused')
            payload = _verified_snapshot(row[0], row[1], row[2])['payload']
            _validate_platform(payload, platform='x', account=row[3], destination=row[0], content=row[4],
                               campaign=row[5], channel=row[6], post=row[7])
            if payload.get('fixture_schema') not in ('x-v1-facebook-text/1', 'x-v1-facebook-media/1') or payload['user_id'] != user_id:
                raise ValueError('X fixture profile mismatch')
            conflict = con.execute('SELECT 1 FROM main.destination_fixture_intents WHERE platform=? AND remote_id=?',
                                   ('x', remote)).fetchone() is not None
            if conflict:
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?", (remote, intent_id))
            else:
                con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?", (remote, intent_id))
        if conflict:
            raise ValueError('X fixture receipt conflict')

    def finish_discord_fixture(self, intent_id: str, *, attempt: str, channel_id: str, message_id: str) -> None:
        """Bind a synthetic Discord receipt to its channel and attempt."""
        if (not isinstance(channel_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', channel_id)
                or not isinstance(message_id, str) or not re.fullmatch(r'[1-9][0-9]{0,31}', message_id)):
            raise ValueError('invalid Discord fixture receipt')
        remote = 'fixture-discord-message-' + message_id
        conflict = False
        with self._transaction() as con:
            row = con.execute("SELECT destination_id,snapshot_json,snapshot_digest,account_id,content_id,campaign_id,channel_id,post_id "
                              "FROM main.destination_fixture_intents WHERE intent_id=? AND platform='discord' "
                              "AND state='submitting' AND attempt_id=?", (intent_id, attempt)).fetchone()
            if row is None:
                raise ValueError('Discord fixture receipt refused')
            payload = _verified_snapshot(row[0], row[1], row[2])['payload']
            _validate_platform(payload, platform='discord', account=row[3], destination=row[0], content=row[4],
                               campaign=row[5], channel=row[6], post=row[7])
            if payload.get('fixture_schema') != 'discord-v1-facebook-text/1' or payload['discord_channel_id'] != channel_id:
                raise ValueError('Discord fixture channel mismatch')
            conflict = con.execute('SELECT 1 FROM main.destination_fixture_intents WHERE platform=? AND remote_id=?',
                                   ('discord', remote)).fetchone() is not None
            if conflict:
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?", (remote, intent_id))
            else:
                con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?", (remote, intent_id))
        if conflict:
            raise ValueError('Discord fixture receipt conflict')

    def finish_group_pending(self, intent_id: str, *, attempt: str, destination: str, remote_id: str) -> None:
        """Record only a synthetic Group pending receipt bound to the active attempt."""
        if (not isinstance(remote_id, str) or not remote_id.startswith('fixture-') or len(remote_id) > 256
                or not isinstance(destination, str) or not destination.startswith('fixture-group-')):
            raise ValueError('invalid Group fixture receipt')
        conflict = False
        with self._transaction() as con:
            row = con.execute("SELECT account_id FROM main.destination_fixture_intents WHERE intent_id=? "
                              "AND platform='facebook' AND destination_id=? AND state='submitting' AND attempt_id=?",
                              (intent_id, destination, attempt)).fetchone()
            if row is None:
                raise ValueError('Group fixture receipt refused')
            conflict = con.execute('SELECT 1 FROM main.destination_fixture_intents WHERE platform=? AND account_id=? AND remote_id=?',
                                   ('facebook', row[0], remote_id)).fetchone() is not None
            if conflict:
                updated = con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? "
                                      "WHERE intent_id=? AND state='submitting' AND attempt_id=? AND destination_id=?",
                                      (remote_id, intent_id, attempt, destination))
            else:
                updated = con.execute("UPDATE main.destination_fixture_intents SET state='awaiting_moderation',remote_id=? "
                                      "WHERE intent_id=? AND state='submitting' AND attempt_id=? AND destination_id=?",
                                      (remote_id, intent_id, attempt, destination))
            if updated.rowcount != 1:
                raise ValueError('Group fixture receipt refused')
        if conflict:
            raise ValueError('Group fixture receipt conflict')

    @staticmethod
    def _instagram_row(con: sqlite3.Connection, intent_id: str, attempt: str) -> tuple[Any, ...]:
        if con.execute('PRAGMA main.user_version').fetchone()[0] != 6:
            raise ValueError('Instagram session requires fixture v6')
        row = con.execute('SELECT i.destination_id,i.snapshot_json,i.snapshot_digest,i.account_id,i.content_id,'
                          'i.campaign_id,i.channel_id,i.post_id,i.state,i.version,i.grant_version,'
                          'g.phase,g.container_id,g.media_id FROM main.destination_fixture_intents i '
                          'JOIN main.instagram_fixture_progress g ON g.intent_id=i.intent_id AND g.attempt_id=i.attempt_id '
                          "WHERE i.intent_id=? AND i.attempt_id=? AND i.platform='instagram'", (intent_id, attempt)).fetchone()
        if row is None or row[9] != row[10]:
            raise ValueError('Instagram fixture session unavailable')
        payload = _verified_snapshot(row[0], row[1], row[2])['payload']
        _validate_platform(payload, platform='instagram', account=row[3], destination=row[0], content=row[4],
                           campaign=row[5], channel=row[6], post=row[7])
        if payload.get('fixture_schema') not in _INSTAGRAM_V1_SCHEMAS:
            raise ValueError('Instagram fixture session unavailable')
        return (*row, payload)

    def instagram_session_status(self, intent_id: str, *, attempt: str) -> dict[str, Any]:
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            return {'state': row[8], 'phase': row[11], 'container_id': row[12], 'media_id': row[13]}

    def instagram_accept_container(self, intent_id: str, *, attempt: str, user_id: str, container_id: str) -> None:
        if not isinstance(container_id, str) or not re.fullmatch(r'[0-9]{1,32}', container_id):
            raise ValueError('invalid Instagram fixture container')
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            if row[8] != 'submitting' or row[11] != 'creating' or row[14]['user_id'] != user_id:
                raise ValueError('Instagram container receipt refused')
            duplicate = con.execute('SELECT 1 FROM main.instagram_fixture_progress WHERE container_id=?', (container_id,)).fetchone()
            if duplicate:
                con.execute("UPDATE main.instagram_fixture_progress SET phase='unknown' WHERE intent_id=?", (intent_id,))
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?",
                            ('fixture-instagram-container-' + container_id, intent_id))
            else:
                con.execute("UPDATE main.instagram_fixture_progress SET phase='waiting',container_id=? WHERE intent_id=?",
                            (container_id, intent_id))

    def instagram_observe_ready(self, intent_id: str, *, attempt: str, container_id: str, status: str) -> None:
        if status not in ('IN_PROGRESS', 'FINISHED', 'ERROR', 'EXPIRED'):
            raise ValueError('invalid Instagram fixture observation')
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            if row[8] != 'submitting' or row[11] != 'waiting' or row[12] != container_id:
                raise ValueError('Instagram observation refused')
            if status == 'FINISHED':
                con.execute("UPDATE main.instagram_fixture_progress SET phase='ready' WHERE intent_id=?", (intent_id,))
            elif status in ('ERROR', 'EXPIRED'):
                con.execute("UPDATE main.instagram_fixture_progress SET phase='unknown' WHERE intent_id=?", (intent_id,))
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown' WHERE intent_id=?", (intent_id,))

    def instagram_claim_publish(self, intent_id: str, *, attempt: str) -> dict[str, Any]:
        from scripts.social.channels.instagram.direct import preview_publish
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            if row[8] != 'submitting' or row[11] != 'ready':
                raise ValueError('Instagram publish claim refused')
            candidate = preview_publish(user_id=row[14]['user_id'], api_version=row[14]['api_version'], creation_id=row[12])
            con.execute("UPDATE main.instagram_fixture_progress SET phase='publishing' WHERE intent_id=?", (intent_id,))
            return candidate

    def instagram_accept_publish(self, intent_id: str, *, attempt: str, container_id: str, media_id: str) -> None:
        if not isinstance(media_id, str) or not re.fullmatch(r'[0-9]{1,32}', media_id):
            raise ValueError('invalid Instagram fixture media')
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            if row[8] != 'submitting' or row[11] != 'publishing' or row[12] != container_id:
                raise ValueError('Instagram publish receipt refused')
            duplicate = con.execute('SELECT 1 FROM main.instagram_fixture_progress WHERE media_id=?', (media_id,)).fetchone()
            if duplicate:
                con.execute("UPDATE main.instagram_fixture_progress SET phase='unknown' WHERE intent_id=?", (intent_id,))
                con.execute("UPDATE main.destination_fixture_intents SET state='unknown',conflict_remote_id=? WHERE intent_id=?",
                            ('fixture-instagram-media-' + media_id, intent_id))
            else:
                con.execute("UPDATE main.instagram_fixture_progress SET phase='accepted',media_id=? WHERE intent_id=?",
                            (media_id, intent_id))
                con.execute("UPDATE main.destination_fixture_intents SET state='accepted',remote_id=? WHERE intent_id=?",
                            ('fixture-instagram-media-' + media_id, intent_id))

    def instagram_mark_unknown(self, intent_id: str, *, attempt: str, expected_phase: str) -> None:
        """Record an uncertain synthetic write after caller confirms worker stopped."""
        if expected_phase not in ('creating', 'publishing'):
            raise ValueError('invalid Instagram recovery phase')
        with self._transaction() as con:
            row = self._instagram_row(con, intent_id, attempt)
            if row[8] != 'submitting' or row[11] != expected_phase:
                raise ValueError('Instagram recovery refused')
            con.execute("UPDATE main.instagram_fixture_progress SET phase='unknown' WHERE intent_id=?", (intent_id,))
            con.execute("UPDATE main.destination_fixture_intents SET state='unknown' WHERE intent_id=?", (intent_id,))

    def mark_unknown(self, intent_id: str, *, attempt: str) -> None:
        """Record uncertain outcome; caller must establish worker is stopped."""
        with self._transaction() as con:
            query = ("UPDATE main.destination_fixture_intents SET state='unknown' "
                     "WHERE intent_id=? AND state='submitting' AND attempt_id=? "
                     "AND NOT EXISTS (SELECT 1 FROM main.reel_fixture_progress r WHERE r.intent_id=destination_fixture_intents.intent_id)")
            if con.execute('PRAGMA main.user_version').fetchone()[0] == 6:
                query += " AND NOT EXISTS (SELECT 1 FROM main.instagram_fixture_progress g WHERE g.intent_id=destination_fixture_intents.intent_id)"
            result = con.execute(query, (intent_id, attempt))
            if result.rowcount != 1:
                raise ValueError('fixture recovery refused')

    @staticmethod
    def _reel_row(con: sqlite3.Connection, intent_id: str, attempt: str) -> tuple[Any, ...]:
        row = con.execute('SELECT i.destination_id,i.snapshot_json,i.snapshot_digest,i.platform,i.account_id,'
                          'i.content_id,i.campaign_id,i.channel_id,i.post_id,i.state,i.version,i.grant_version,'
                          'r.phase,r.video_id FROM main.destination_fixture_intents i '
                          'JOIN main.reel_fixture_progress r ON r.intent_id=i.intent_id AND r.attempt_id=i.attempt_id '
                          'WHERE i.intent_id=? AND i.attempt_id=?', (intent_id, attempt)).fetchone()
        if row is None or row[3] != 'facebook' or row[10] != row[11]:
            raise ValueError('Reel fixture session unavailable')
        snapshot = _verified_snapshot(row[0], row[1], row[2])
        _validate_platform(snapshot['payload'], platform=row[3], account=row[4], destination=row[0],
                           content=row[5], campaign=row[6], channel=row[7], post=row[8])
        if snapshot['payload'].get('media_type') != 'REEL':
            raise ValueError('Reel fixture session unavailable')
        return (*row, snapshot['payload'])

    def reel_status(self, intent_id: str, *, attempt: str) -> dict[str, Any]:
        with self._transaction() as con:
            row = self._reel_row(con, intent_id, attempt)
            return {'intent': row[9], 'phase': row[12], 'video_id': row[13]}

    def reel_candidate(self, intent_id: str, *, attempt: str) -> dict[str, Any]:
        """Rebuild a synthetic request; reading a preview is not authorization or dispatch."""
        from scripts.social.channels.facebook.reel_fixture import preview_finish, preview_upload
        with self._transaction() as con:
            row = self._reel_row(con, intent_id, attempt)
            if row[9] != 'submitting':
                raise ValueError('Reel candidate unavailable')
            payload = row[14]
            if row[12] == 'start_pending' and row[13] is None:
                return copy.deepcopy(payload['candidate'])
            if row[12] == 'upload_pending':
                return preview_upload(api_version=payload['api_version'], video_id=row[13],
                                      media_id=payload['candidate']['media_id'])
            if row[12] == 'finish_pending':
                return preview_finish(page_id=payload['page_id'], api_version=payload['api_version'],
                                      video_id=row[13], caption=payload['candidate']['caption'])
            raise ValueError('Reel candidate unavailable')

    def reel_accept_start(self, intent_id: str, *, attempt: str, page_id: str, video_id: str) -> None:
        if not isinstance(video_id, str) or not re.fullmatch(r'fixture-reel-[A-Za-z0-9_-]{1,100}', video_id):
            raise ValueError('invalid Reel fixture video')
        try:
            with self._transaction() as con:
                row = self._reel_row(con, intent_id, attempt)
                if row[9] != 'submitting' or row[12] != 'start_pending' or row[14]['page_id'] != page_id:
                    raise ValueError('Reel start refused')
                updated = con.execute("UPDATE main.reel_fixture_progress SET phase='upload_pending',video_id=? "
                                      "WHERE intent_id=? AND attempt_id=? AND phase='start_pending'",
                                      (video_id, intent_id, attempt))
                if updated.rowcount != 1:
                    raise ValueError('Reel start refused')
        except sqlite3.IntegrityError:
            raise ValueError('Reel fixture video conflict') from None

    def reel_accept_upload(self, intent_id: str, *, attempt: str, video_id: str) -> None:
        with self._transaction() as con:
            row = self._reel_row(con, intent_id, attempt)
            if row[9] != 'submitting' or row[12] != 'upload_pending' or row[13] != video_id:
                raise ValueError('Reel upload refused')
            updated = con.execute("UPDATE main.reel_fixture_progress SET phase='finish_pending' "
                                  "WHERE intent_id=? AND attempt_id=? AND phase='upload_pending' AND video_id=?",
                                  (intent_id, attempt, video_id))
            if updated.rowcount != 1:
                raise ValueError('Reel upload refused')

    def reel_finish_unknown(self, intent_id: str, *, attempt: str, video_id: str) -> None:
        self._reel_finish(intent_id, attempt=attempt, video_id=video_id, state='unknown')

    def reel_mark_unknown(self, intent_id: str, *, attempt: str, expected_phase: str,
                          video_id: str | None) -> None:
        """Record a synthetic uncertain START/upload after caller stops its worker."""
        if expected_phase not in ('start_pending', 'upload_pending'):
            raise ValueError('invalid Reel recovery phase')
        with self._transaction() as con:
            row = self._reel_row(con, intent_id, attempt)
            if row[9] != 'submitting' or row[12] != expected_phase or row[13] != video_id:
                raise ValueError('Reel recovery refused')
            phase = 'start_unknown' if expected_phase == 'start_pending' else 'upload_unknown'
            con.execute('UPDATE main.reel_fixture_progress SET phase=? WHERE intent_id=? AND attempt_id=?',
                        (phase, intent_id, attempt))
            con.execute("UPDATE main.destination_fixture_intents SET state='unknown' WHERE intent_id=? AND attempt_id=?",
                        (intent_id, attempt))

    def reel_accept_finish(self, intent_id: str, *, attempt: str, video_id: str) -> None:
        self._reel_finish(intent_id, attempt=attempt, video_id=video_id, state='processing_unverified')

    def _reel_finish(self, intent_id: str, *, attempt: str, video_id: str, state: str) -> None:
        if state not in ('unknown', 'processing_unverified'):
            raise ValueError('invalid Reel finish state')
        with self._transaction() as con:
            row = self._reel_row(con, intent_id, attempt)
            if row[9] != 'submitting' or row[12] != 'finish_pending' or row[13] != video_id:
                raise ValueError('Reel finish refused')
            con.execute('UPDATE main.reel_fixture_progress SET phase=? WHERE intent_id=? AND attempt_id=?',
                        (state, intent_id, attempt))
            con.execute('UPDATE main.destination_fixture_intents SET state=? WHERE intent_id=? AND attempt_id=?',
                        (state, intent_id, attempt))
