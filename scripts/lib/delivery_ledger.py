"""Offline SQLite delivery intents. This module performs no remote operations.

The approval check itself remains the responsibility of the caller; this ledger
serializes a generation check with its claim/revocation, not external file edits.
"""

from __future__ import annotations

import sqlite3
import subprocess
import threading
import hashlib
import copy
import json
import re
from datetime import datetime, timezone
import os
import tempfile
import uuid
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

KEY_FIELDS = ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id',
              'platform', 'account_id', 'occurrence_key')
SCOPE_FIELDS = ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id', 'gate')
_RESOLUTIONS = {'submitted', 'scheduled', 'published', 'failed', 'unknown'}
# A borrowed fixture connection has one wrapper for its lifetime. This guards
# wrapper users only; the caller must not use its raw connection concurrently.
_FIXTURE_CONNECTIONS = {}
_FIXTURE_REGISTRY_LOCK = threading.Lock()
_FIXTURE_MARKER = '_opcos_delivery_fixture_owner_v1'
_SOURCE_SNAPSHOT_SCHEMA_KEY = 'source_snapshot_schema_version'
_SOURCE_SNAPSHOT_DDL = '''CREATE TABLE delivery_source_snapshots (
    intent_id TEXT NOT NULL PRIMARY KEY REFERENCES intents(intent_id),
    schema_version TEXT NOT NULL,
    snapshot_json BLOB NOT NULL CHECK(typeof(snapshot_json) = 'blob'),
    payload_digest TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    prepared_at TEXT NOT NULL
)'''


def _station_uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('invalid station anchor')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('invalid station anchor') from None
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError('invalid station anchor')
    return value


def create_station_identity(connection: sqlite3.Connection) -> str:
    """Initialize one random station UUID in an already-open trusted test DB.

    This pure prototype establishes no physical path, cloud, or authority claim.
    The caller owns the connection and must not have an open transaction.
    """
    if connection.in_transaction:
        raise ValueError('connection already in transaction')
    try:
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute("SELECT 1 FROM main.sqlite_master WHERE name COLLATE NOCASE='station_identity'").fetchone()
        if existing:
            raise ValueError('station identity already initialized')
        # Never assign a fresh namespace to pre-existing state. A separate,
        # explicit migration must establish provenance before this is allowed.
        for table in ('intents', 'approval_scopes', 'intent_scopes', 'scope_proofs', 'scope_events',
                      'attempts', 'cancel_attempts', 'deliveries', 'events', 'legacy_import_evidence',
                      'delivery_source_snapshots'):
            definition = connection.execute('SELECT type FROM main.sqlite_master WHERE name COLLATE NOCASE=?', (table,)).fetchone()
            if definition is not None:
                if definition[0] != 'table' or connection.execute(f'SELECT 1 FROM main.{table} LIMIT 1').fetchone():
                    raise ValueError('populated ledger requires explicit identity migration')
        connection.execute('''CREATE TABLE main.station_identity (
                           singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                           station_uuid TEXT NOT NULL)''')
        station_id = str(uuid.uuid4())
        connection.execute('INSERT INTO main.station_identity(singleton,station_uuid) VALUES (1,?)', (station_id,))
        # Explicit SQL ends BEGIN even when sqlite3's autocommit=True makes
        # Connection.commit() a no-op.
        connection.execute('COMMIT')
        return station_id
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise


def open_station_identity(connection: sqlite3.Connection, expected_station_id: str) -> str:
    """Compare UUID with an independently established anchor; never creates one.

    Caller-supplied anchors are not authenticated here. A copied database and a
    copied anchor cannot be distinguished; do not use this alone for authority.
    """
    expected = _station_uuid(expected_station_id)
    exists = connection.execute("SELECT 1 FROM main.sqlite_master WHERE name COLLATE NOCASE='station_identity' AND type='table'").fetchone()
    if exists is None:
        raise ValueError('station identity missing')
    rows = connection.execute('SELECT station_uuid FROM main.station_identity WHERE singleton=1').fetchall()
    if len(rows) != 1:
        raise ValueError('station identity missing or corrupt')
    actual = _station_uuid(rows[0][0])
    if actual != expected:
        raise ValueError('station identity mismatch')
    return actual


def initialize_source_snapshot_schema(connection: sqlite3.Connection) -> None:
    """Explicitly initialize the empty source-snapshot schema on a trusted DB.

    This only creates storage; it does not open a station, inspect source files,
    write snapshots, authenticate an approval, or enable any dispatch. Existing
    intents are not backfilled. The caller must own a connection without an open
    transaction and is responsible for verifying the DB path and backup first.
    Future snapshot writers must enable foreign_keys on their own connection.
    """
    if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
        raise ValueError('an idle SQLite connection is required')
    try:
        connection.execute('BEGIN IMMEDIATE')
        cursor = connection.cursor()
        cursor.row_factory = None
        shadows = cursor.execute(
            "SELECT name FROM sqlite_temp_master WHERE name COLLATE NOCASE IN "
            "('intents','metadata','delivery_source_snapshots')"
        ).fetchall()
        if shadows:
            raise ValueError('temporary tables shadow the delivery ledger')
        required = cursor.execute(
            "SELECT name,type FROM main.sqlite_master WHERE name IN ('intents','metadata')"
        ).fetchall()
        if {tuple(row) for row in required} != {('intents', 'table'), ('metadata', 'table')}:
            raise ValueError('delivery ledger schema is unavailable')
        intent_cols = {row[1]: row for row in cursor.execute('PRAGMA main.table_info(intents)')}
        metadata_cols = {row[1]: row for row in cursor.execute('PRAGMA main.table_info(metadata)')}
        if ([row[1] for row in intent_cols.values() if row[5]] != ['intent_id']
                or [row[1] for row in metadata_cols.values() if row[5]] != ['key']
                or 'value' not in metadata_cols):
            raise ValueError('delivery ledger schema is unsupported')
        marker = cursor.execute('SELECT value FROM main.metadata WHERE key=?',
                                    (_SOURCE_SNAPSHOT_SCHEMA_KEY,)).fetchone()
        table = cursor.execute("SELECT type,sql FROM main.sqlite_master WHERE name COLLATE NOCASE=?",
                                   ('delivery_source_snapshots',)).fetchone()
        if marker is None and table is None:
            connection.execute(_SOURCE_SNAPSHOT_DDL)
            connection.execute('INSERT INTO main.metadata(key,value) VALUES (?,?)',
                               (_SOURCE_SNAPSHOT_SCHEMA_KEY, '1'))
        elif (marker is None or table is None or marker[0] != '1'
              or table[0] != 'table' or table[1] != _SOURCE_SNAPSHOT_DDL):
            raise ValueError('source snapshot schema is unsupported or inconsistent')
        connection.execute('COMMIT')
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise


def _publication_time(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('invalid publication timestamp')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid publication timestamp') from None


def _evidence_locator(value: str) -> str:
    """Accept only a conservative relative reference, never URLs or secret paths."""
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError('invalid evidence reference')
    for segment in value.split('/'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', segment):
            raise ValueError('invalid evidence reference')
        if (segment.endswith('.') or '..' in segment
                or re.search(r'(^|[._-])(env|pem|key|token|secret|credentials?|password|auth|cookie)([._-]|$)',
                             segment, re.IGNORECASE)):
            raise ValueError('invalid evidence reference')
    return value


class DeliveryLedger:
    """Durable claim/attempt ledger; constructed with a caller-validated local path."""

    def __init__(self, db_path: Path | str):
        # Freeze relative paths before another component can change cwd.
        self.path = Path(db_path).absolute()
        self._memory_uri = None
        self._keeper = None
        self._fixture_connection = None
        self._fixture_lock = None
        self._fixture_mode = False
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def synthetic_memory(cls):
        """Build an isolated, disposable SQLite ledger for synthetic tests only.

        This does not authenticate a station, person, source, or provider.
        """
        instance = cls.__new__(cls)
        instance.path = None
        instance._memory_uri = f'file:delivery-fixture-{uuid.uuid4()}?mode=memory&cache=shared'
        instance._keeper = sqlite3.connect(instance._memory_uri, uri=True)
        instance._fixture_connection = None
        instance._fixture_lock = None
        instance._fixture_mode = True
        instance._closed = False
        instance._fixture_workers = {}
        try:
            instance._initialize()
        except BaseException:
            instance._keeper.close()
            instance._closed = True
            raise
        return instance

    @classmethod
    def synthetic_connection(cls, connection: sqlite3.Connection):
        """Wrap an already-open, caller-owned SQLite connection for fixture tests.

        The caller supplies a disposable local database and must not use its raw
        connection while the wrapper is active. This method does not open a path
        or authenticate origin, station, approval, or provider. Never use it to
        enable a real dispatch.
        """
        if not isinstance(connection, sqlite3.Connection):
            raise ValueError('fixture connection required')
        if getattr(connection, 'autocommit', None) is True:
            raise ValueError('fixture connection autocommit mode unsupported')
        if connection.in_transaction:
            raise ValueError('fixture connection already in transaction')
        instance = cls.__new__(cls)
        instance.path = None
        instance._memory_uri = None
        instance._keeper = None
        instance._fixture_connection = connection
        instance._fixture_lock = threading.RLock()
        instance._fixture_mode = True
        instance._closed = False
        instance._fixture_workers = {}
        with _FIXTURE_REGISTRY_LOCK:
            if id(connection) in _FIXTURE_CONNECTIONS:
                raise ValueError('fixture connection already wrapped')
            # The connection-local TEMP marker also works when the same module is
            # imported under different names, each with its own Python registry.
            try:
                connection.execute(f'CREATE TEMP TABLE {_FIXTURE_MARKER} (owner INTEGER)')
            except sqlite3.OperationalError:
                raise ValueError('fixture connection already wrapped or unavailable') from None
            _FIXTURE_CONNECTIONS[id(connection)] = instance
        try:
            instance._initialize()
        except BaseException:
            with _FIXTURE_REGISTRY_LOCK:
                if _FIXTURE_CONNECTIONS.get(id(connection)) is instance:
                    del _FIXTURE_CONNECTIONS[id(connection)]
                    connection.execute(f'DROP TABLE temp.{_FIXTURE_MARKER}')
            instance._closed = True
            raise
        return instance

    def close(self):
        """Release fixture ownership without closing a borrowed connection."""
        with self._fixture_lock if self._fixture_lock is not None else nullcontext():
            if self._closed:
                return
            if self._fixture_connection is not None and self._fixture_connection.in_transaction:
                raise ValueError('fixture connection already in transaction')
            if self._keeper is not None:
                self._keeper.close()
                self._keeper = None
            if self._fixture_connection is not None:
                with _FIXTURE_REGISTRY_LOCK:
                    if _FIXTURE_CONNECTIONS.get(id(self._fixture_connection)) is self:
                        self._fixture_connection.execute(f'DROP TABLE temp.{_FIXTURE_MARKER}')
                        del _FIXTURE_CONNECTIONS[id(self._fixture_connection)]
                self._fixture_connection = None
            self._closed = True

    def _initialize(self):
        with self._connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS intents (
                    intent_id TEXT PRIMARY KEY, station_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL, campaign_id TEXT NOT NULL,
                    content_id TEXT NOT NULL, post_id TEXT NOT NULL,
                    platform TEXT NOT NULL, account_id TEXT NOT NULL,
                    occurrence_key TEXT NOT NULL, payload_digest TEXT NOT NULL,
                    owner TEXT NOT NULL, approval_generation INTEGER NOT NULL,
                    state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(station_id,channel_id,campaign_id,content_id,post_id,
                           platform,account_id,occurrence_key));
                CREATE TABLE IF NOT EXISTS fixture_grants (
                    event_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL REFERENCES approval_scopes,
                    generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS fixture_snapshots (
                    intent_id TEXT PRIMARY KEY REFERENCES intents,
                    snapshot_json TEXT NOT NULL, payload_digest TEXT NOT NULL,
                    source_locator TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES intents,
                    state TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES intents,
                    kind TEXT NOT NULL, state TEXT NOT NULL, actor TEXT, quote TEXT, gate TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata(key,value) VALUES ('recovery_required','0');
                CREATE TABLE IF NOT EXISTS approval_scopes (
                    scope_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS intent_scopes (
                    intent_id TEXT NOT NULL REFERENCES intents, scope_id TEXT NOT NULL REFERENCES approval_scopes,
                    generation INTEGER NOT NULL, PRIMARY KEY(intent_id,scope_id));
                CREATE TABLE IF NOT EXISTS scope_events (
                    event_id INTEGER PRIMARY KEY, scope_id TEXT NOT NULL REFERENCES approval_scopes,
                    old_generation INTEGER NOT NULL, actor TEXT NOT NULL, quote TEXT NOT NULL,
                    gate TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS scope_proofs (
                    scope_id TEXT NOT NULL REFERENCES approval_scopes, generation INTEGER NOT NULL,
                    source_digest TEXT NOT NULL, proof_digest TEXT NOT NULL, actor TEXT NOT NULL,
                    quote_digest TEXT NOT NULL, PRIMARY KEY(scope_id,generation),
                    UNIQUE(scope_id,source_digest));
                CREATE TABLE IF NOT EXISTS deliveries (
                    intent_id TEXT PRIMARY KEY REFERENCES intents, remote_job_id TEXT, remote_post_id TEXT,
                    platform_post_id TEXT, platform_url TEXT, integration_id TEXT, evidence_kind TEXT,
                    provider_instance_id TEXT);
                CREATE TABLE IF NOT EXISTS cancel_attempts (
                    cancel_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES intents,
                    state TEXT NOT NULL, actor TEXT NOT NULL, quote TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS legacy_import_evidence (
                    import_id TEXT NOT NULL, intent_id TEXT NOT NULL REFERENCES intents,
                    reference_sha256 TEXT NOT NULL, evidence_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(import_id,intent_id));
            ''')
            con.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in con.execute('PRAGMA table_info(deliveries)')}
            for column in ('provider_instance_id', 'comment_id', 'published_at'):
                if column not in columns:
                    con.execute(f'ALTER TABLE deliveries ADD COLUMN {column} TEXT')
            evidence_columns = {row['name'] for row in con.execute('PRAGMA table_info(legacy_import_evidence)')}
            if 'evidence_sha256' in evidence_columns and 'reference_sha256' not in evidence_columns:
                con.execute('ALTER TABLE legacy_import_evidence RENAME COLUMN evidence_sha256 TO reference_sha256')
            if 'evidence_ref' not in evidence_columns:
                # Existing unverified rows remain NULL; never invent their locator.
                con.execute('ALTER TABLE legacy_import_evidence ADD COLUMN evidence_ref TEXT')

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # The lock covers the complete borrowed-connection transaction, not just
        # BEGIN. The caller must not bypass it via raw-connection operations.
        with self._fixture_lock if self._fixture_lock is not None else nullcontext():
            if self._closed:
                raise ValueError('ledger is closed')
            borrowed = self._fixture_connection is not None
            if borrowed:
                con = self._fixture_connection
                if con.in_transaction:
                    raise ValueError('fixture connection already in transaction')
            elif self._memory_uri is not None:
                con = sqlite3.connect(self._memory_uri, timeout=5.0, uri=True)
            else:
                con = sqlite3.connect(str(self.path), timeout=5.0)
            con.row_factory = sqlite3.Row
            try:
                con.execute('PRAGMA foreign_keys=ON')
                if self._memory_uri is not None:
                    con.execute('PRAGMA temp_store=MEMORY')
                con.execute('PRAGMA journal_mode=DELETE')
                con.execute('PRAGMA synchronous=FULL')
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise
            finally:
                if not borrowed:
                    con.close()

    def prepare(self, key: dict[str, str], payload_digest: str, owner: str,
                approval_generation: int, *, scopes: list[tuple[dict[str, str], int]] | None = None,
                _fixture_binding: tuple[str, str, str] | None = None,
                _source_binding: tuple[bytes, str, str, str, str] | None = None) -> str:
        try:
            key = dict(key)
            scopes = [(dict(scope), generation) for scope, generation in scopes] if scopes is not None else None
            if _source_binding is not None:
                _source_binding = tuple(_source_binding)
        except (TypeError, ValueError):
            raise ValueError('invalid intent') from None
        if _fixture_binding is not None and not self._fixture_mode:
            raise ValueError('fixture-only operation')
        if _source_binding is not None and (self._fixture_mode or self.path is None or _fixture_binding is not None):
            raise ValueError('source snapshot requires a source ledger')
        if _source_binding is not None:
            self._validate_source_binding(key, payload_digest, owner, _source_binding)
        if (set(key) != set(KEY_FIELDS) or any(not isinstance(key[k], str) or not key[k].strip()
                                               for k in KEY_FIELDS)
                or key.get('post_id') == '*'
                or not isinstance(payload_digest, str) or not payload_digest.strip()
                or owner not in {'legacy', 'postiz'} or type(approval_generation) is not int
                or approval_generation < 1 or not scopes
                or not {'g1', 'g2'}.issubset({scope.get('gate') for scope, _ in scopes})):
            raise ValueError('invalid intent')
        values = tuple(key[k] for k in KEY_FIELDS)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if _source_binding is not None:
                self._validate_source_binding(key, payload_digest, owner, _source_binding)
                open_station_identity(con, _source_binding[4])
            scope_bindings = []
            for scope, generation in scopes or []:
                if type(generation) is not int or generation < 1:
                    raise ValueError('invalid scope generation')
                scope_id = self._scope_id(scope)
                if (any(scope[field] != key[field] for field in SCOPE_FIELDS[:4])
                        or scope['post_id'] not in ('*', key['post_id'])
                        or (scope['gate'] in {'g1', 'g3'} and scope['post_id'] != '*')
                        or (scope['gate'] == 'g2' and scope['post_id'] != key['post_id'])):
                    raise ValueError('scope does not match intent')
                current = con.execute('SELECT generation,active FROM approval_scopes WHERE scope_id=?',
                                      (scope_id,)).fetchone()
                if current is None or current['generation'] != generation or not current['active']:
                    raise ValueError('scope generation mismatch')
                scope_bindings.append((scope_id, generation))
            query = ' AND '.join(f'{field}=?' for field in KEY_FIELDS)
            existing = con.execute(f'SELECT * FROM intents WHERE {query}', values).fetchone()
            if existing:
                if (existing['payload_digest'], existing['owner'], existing['approval_generation']) != (
                        payload_digest, owner, approval_generation):
                    raise ValueError('intent conflicts with existing record')
                stored = con.execute('SELECT scope_id,generation FROM intent_scopes WHERE intent_id=?',
                                     (existing['intent_id'],)).fetchall()
                if set(map(tuple, stored)) != set(scope_bindings):
                    raise ValueError('intent scope mismatch')
                if _fixture_binding is not None:
                    self._bind_fixture(con, existing['intent_id'], _fixture_binding, allow_create=False)
                if _source_binding is not None:
                    self._bind_source(con, existing['intent_id'], _source_binding, allow_create=False)
                return existing['intent_id']
            intent = str(uuid.uuid4())
            placeholders = ','.join('?' for _ in range(14))
            con.execute(f'INSERT INTO intents VALUES ({placeholders})',
                        (intent, *values, payload_digest, owner, approval_generation, 'prepared', 0))
            con.executemany('INSERT INTO intent_scopes(intent_id,scope_id,generation) VALUES (?,?,?)',
                            [(intent, scope_id, gen) for scope_id, gen in scope_bindings])
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent, 'prepare', 'prepared'))
            if _fixture_binding is not None:
                self._bind_fixture(con, intent, _fixture_binding, allow_create=True)
            if _source_binding is not None:
                self._bind_source(con, intent, _source_binding, allow_create=True)
            return intent

    @staticmethod
    def _validate_source_binding(key, payload_digest, owner, binding) -> None:
        if __package__:
            from .delivery_contract import MAX_SOURCE_SNAPSHOT_BYTES, canonical_snapshot, validate_source_envelope_basics
        else:
            from delivery_contract import MAX_SOURCE_SNAPSHOT_BYTES, canonical_snapshot, validate_source_envelope_basics
        try:
            raw, digest, locator, prepared_at, station_id = binding
            if not isinstance(raw, bytes) or len(raw) > MAX_SOURCE_SNAPSHOT_BYTES:
                raise ValueError('invalid bytes')
            payload = json.loads(raw.decode('utf-8'))
            canonical, actual_digest = canonical_snapshot(payload)
            if (not isinstance(key, dict) or set(key) != set(KEY_FIELDS)
                    or canonical != raw or actual_digest != digest or digest != payload_digest
                    or any(payload.get(field) != key[field] for field in KEY_FIELDS)
                    or payload.get('provider') != owner or payload.get('source_locator') != locator
                    or key['station_id'] != _station_uuid(station_id)):
                raise ValueError('binding mismatch')
            payload['prepared_at'] = prepared_at
            validate_source_envelope_basics(payload)
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError):
            raise ValueError('invalid source snapshot binding') from None

    @staticmethod
    def _bind_source(con, intent: str, binding: tuple[bytes, str, str, str, str], *, allow_create: bool) -> None:
        """Persist only inside the caller's intent transaction; not authorization."""
        raw, digest, locator, prepared_at, _station_id = binding
        marker = con.execute('SELECT value FROM main.metadata WHERE key=?',
                             (_SOURCE_SNAPSHOT_SCHEMA_KEY,)).fetchone()
        table = con.execute('SELECT type,sql FROM main.sqlite_master WHERE name COLLATE NOCASE=?',
                            ('delivery_source_snapshots',)).fetchone()
        if marker is None or marker[0] != '1' or table is None or tuple(table) != ('table', _SOURCE_SNAPSHOT_DDL):
            raise ValueError('source snapshot schema is unavailable')
        row = con.execute('SELECT snapshot_json,payload_digest,source_locator,prepared_at,schema_version '
                          'FROM main.delivery_source_snapshots WHERE intent_id=?', (intent,)).fetchone()
        expected = (raw, digest, locator, 'marketing-publish/1')
        if row is not None:
            if (row[0], row[1], row[2], row[4]) != expected:
                raise ValueError('source snapshot conflicts with existing record')
            _publication_time(row[3])
            try:
                old_time = datetime.fromisoformat(row[3].replace('Z', '+00:00'))
                if (not row[3].endswith(('Z', '+00:00'))
                        or old_time.utcoffset() != timezone.utc.utcoffset(old_time)):
                    raise ValueError('invalid time')
            except (AttributeError, TypeError, ValueError):
                raise ValueError('stored preparation timestamp is invalid') from None
        elif not allow_create:
            raise ValueError('source snapshot missing for existing intent')
        else:
            con.execute('INSERT INTO main.delivery_source_snapshots '
                        '(intent_id,schema_version,snapshot_json,payload_digest,source_locator,prepared_at) '
                        'VALUES (?,?,?,?,?,?)', (intent, 'marketing-publish/1', raw, digest, locator, prepared_at))

    def _prepare_source_snapshot(self, key: dict[str, str], payload: dict, owner: str,
                                 approval_generation: int, *, scopes, expected_station_id: str) -> str:
        """Storage primitive only; never establishes authority or enables dispatch.

        No product caller may use this until source authority, data policy, locks,
        and recovery have been independently established.
        """
        if __package__:
            from .delivery_contract import canonical_snapshot, validate_source_envelope_basics
        else:
            from delivery_contract import canonical_snapshot, validate_source_envelope_basics
        try:
            frozen = copy.deepcopy(payload)
        except (TypeError, ValueError, RuntimeError, RecursionError):
            raise ValueError('invalid source snapshot') from None
        validate_source_envelope_basics(frozen)
        if (not isinstance(key, dict) or set(key) != set(KEY_FIELDS)
                or any(frozen.get(field) != key[field] for field in KEY_FIELDS)
                or frozen.get('provider') != owner or key['station_id'] != expected_station_id):
            raise ValueError('source snapshot does not match intent')
        raw, digest = canonical_snapshot(frozen)
        locator = _evidence_locator(frozen['source_locator'])
        binding = (raw, digest, locator, frozen['prepared_at'], _station_uuid(expected_station_id))
        return self.prepare(key, digest, owner, approval_generation, scopes=scopes, _source_binding=binding)

    @staticmethod
    def _bind_fixture(con, intent: str, binding: tuple[str, str, str], *, allow_create: bool) -> None:
        old = con.execute('SELECT snapshot_json,payload_digest,source_locator FROM fixture_snapshots '
                          'WHERE intent_id=?', (intent,)).fetchone()
        if old:
            if tuple(old) != binding:
                raise ValueError('fixture binding mismatch')
        elif not allow_create:
            raise ValueError('fixture snapshot missing')
        else:
            con.execute('INSERT INTO fixture_snapshots VALUES (?,?,?,?)', (intent, *binding))

    def prepare_fixture(self, key: dict[str, str], payload: dict, source_locator: str,
                        owner: str, approval_generation: int, *, scopes) -> str:
        """Store a synthetic snapshot for fixture tests; never a source approval."""
        if not self._fixture_mode:
            raise ValueError('fixture-only operation')
        if __package__:
            from .delivery_contract import canonical_snapshot
        else:
            from delivery_contract import canonical_snapshot
        locator = _evidence_locator(source_locator)
        data, digest = canonical_snapshot(payload)
        return self.prepare(key, digest, owner, approval_generation, scopes=scopes,
                            _fixture_binding=(data.decode('utf-8'), digest, locator))

    def fixture_snapshot(self, intent_id: str) -> dict:
        """Return a synthetic snapshot; absence fails closed after interrupted prepare."""
        if not self._fixture_mode:
            raise ValueError('fixture-only operation')
        with self._connect() as con:
            row = con.execute('SELECT snapshot_json,payload_digest,source_locator FROM fixture_snapshots '
                              'WHERE intent_id=?', (intent_id,)).fetchone()
            if row is None:
                raise ValueError('fixture snapshot missing')
            return {'snapshot': json.loads(row['snapshot_json']), 'payload_digest': row['payload_digest'],
                    'source_locator': row['source_locator']}

    def source_snapshot(self, intent_id: str) -> dict:
        """Read and check a stored source snapshot, without authorizing dispatch.

        This verifies storage consistency only, not human approval, station
        identity, file safety, secret/PII absence, or media bytes. The caller
        must already have established a trusted local ledger connection.
        """
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError('invalid intent')
        if self._closed or self._fixture_mode or self.path is None:
            raise ValueError('source ledger is unavailable')
        if __package__:
            from .delivery_contract import MAX_SOURCE_SNAPSHOT_BYTES, canonical_snapshot
        else:
            from delivery_contract import MAX_SOURCE_SNAPSHOT_BYTES, canonical_snapshot
        # A read-only URI avoids _connect() changing the persistent journal mode.
        # It is not a replacement for platform-specific path/cloud validation.
        with closing(sqlite3.connect(self.path.absolute().as_uri() + '?mode=ro',
                                     timeout=5.0, uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute('BEGIN')
            marker = con.execute('SELECT value FROM main.metadata WHERE key=?',
                                 (_SOURCE_SNAPSHOT_SCHEMA_KEY,)).fetchone()
            table = con.execute('SELECT type,sql FROM main.sqlite_master WHERE name COLLATE NOCASE=?',
                                ('delivery_source_snapshots',)).fetchone()
            if (marker is None or marker['value'] != '1' or table is None
                    or table['type'] != 'table' or table['sql'] != _SOURCE_SNAPSHOT_DDL):
                raise ValueError('source snapshot schema is unavailable')
            row = con.execute('''SELECT i.*, s.schema_version, s.snapshot_json,
                                 s.payload_digest AS snapshot_digest, s.source_locator, s.prepared_at
                                 FROM main.intents AS i
                                 JOIN main.delivery_source_snapshots AS s ON s.intent_id=i.intent_id
                                 WHERE i.intent_id=? AND length(s.snapshot_json)<=?''',
                              (intent_id, MAX_SOURCE_SNAPSHOT_BYTES)).fetchone()
            if row is None:
                raise ValueError('source snapshot is unavailable')
            raw = row['snapshot_json']
            if not isinstance(raw, bytes) or row['schema_version'] != 'marketing-publish/1':
                raise ValueError('source snapshot is invalid')
            try:
                payload = json.loads(raw.decode('utf-8'))
                canonical, digest = canonical_snapshot(payload)
                locator = _evidence_locator(row['source_locator'])
                if not isinstance(row['prepared_at'], str):
                    raise ValueError('timestamp is invalid')
                _publication_time(row['prepared_at'])
                prepared = datetime.fromisoformat(row['prepared_at'].replace('Z', '+00:00'))
                if (not row['prepared_at'].endswith(('Z', '+00:00'))
                        or prepared.utcoffset() != timezone.utc.utcoffset(prepared)):
                    raise ValueError('timestamp is not UTC')
            except (TypeError, ValueError, UnicodeError, RecursionError):
                raise ValueError('source snapshot is invalid') from None
            if (canonical != raw or digest != row['payload_digest'] or digest != row['snapshot_digest']
                    or payload.get('schema') != row['schema_version']
                    or payload.get('source_locator') != locator
                    or row['owner'] not in ('legacy', 'postiz') or payload.get('provider') != row['owner']
                    or any(payload.get(field) != row[field] for field in KEY_FIELDS)):
                raise ValueError('source snapshot is invalid')
            return {'snapshot': payload, 'payload_digest': digest, 'source_locator': locator,
                    'prepared_at': row['prepared_at']}

    def get(self, intent_id: str) -> dict:
        with self._connect() as con:
            row = con.execute('SELECT * FROM intents WHERE intent_id=?', (intent_id,)).fetchone()
            if row is None:
                raise ValueError('unknown intent')
            result = dict(row)
            delivery = con.execute('SELECT * FROM deliveries WHERE intent_id=?', (intent_id,)).fetchone()
            if delivery:
                result.update(dict(delivery))
            return result

    def claim(self, intent_id: str, approval_generation: int, *, verifier=None) -> str:
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute("SELECT value FROM metadata WHERE key='recovery_required'").fetchone()[0] != '0':
                raise ValueError('recovery required before dispatch')
            stale = con.execute('''SELECT 1 FROM intent_scopes s LEFT JOIN approval_scopes a ON a.scope_id=s.scope_id
                                 WHERE s.intent_id=? AND (a.scope_id IS NULL OR s.generation != a.generation OR a.active != 1) LIMIT 1''',
                                (intent_id,)).fetchone()
            if stale:
                raise ValueError('scope generation mismatch')
            if con.execute('SELECT COUNT(*) FROM intent_scopes WHERE intent_id=?', (intent_id,)).fetchone()[0] < 2:
                raise ValueError('approval scope missing')
            scopes = con.execute('''SELECT s.scope_id,s.generation,p.proof_digest FROM intent_scopes s
                                  LEFT JOIN scope_proofs p ON p.scope_id=s.scope_id AND p.generation=s.generation
                                  WHERE s.intent_id=?''', (intent_id,)).fetchall()
            intent = con.execute('SELECT station_id,channel_id,campaign_id,content_id,post_id '
                                 'FROM intents WHERE intent_id=?', (intent_id,)).fetchone()
            if intent is None or intent['post_id'] == '*':
                raise ValueError('intent post scope is invalid')
            decoded_scopes = []
            for row in scopes:
                try:
                    values = json.loads(row['scope_id'])
                except (TypeError, ValueError):
                    raise ValueError('intent approval scopes are invalid') from None
                if not isinstance(values, list) or len(values) != len(SCOPE_FIELDS):
                    raise ValueError('intent approval scopes are invalid')
                scope = dict(zip(SCOPE_FIELDS, values))
                if (self._scope_id(scope) != row['scope_id']
                        or any(scope[field] != intent[field] for field in SCOPE_FIELDS[:4])
                        or scope['post_id'] not in ('*', intent['post_id'])
                        or (scope['gate'] in {'g1', 'g3'} and scope['post_id'] != '*')):
                    raise ValueError('intent approval scopes are invalid')
                decoded_scopes.append(scope)
            if (not {'g1', 'g2'}.issubset({scope.get('gate') for scope in decoded_scopes})
                    or any(scope.get('gate') == 'g2' and scope.get('post_id') != intent['post_id']
                           for scope in decoded_scopes)):
                raise ValueError('intent approval scopes are invalid')
            for row, scope in zip(scopes, decoded_scopes):
                _, _, digest, _ = self._verified_proof(scope, verifier)
                if not row['proof_digest'] or row['proof_digest'] != digest:
                    raise ValueError('scope proof mismatch')
            changed = con.execute('''UPDATE intents SET state='submitting',version=version+1
                                  WHERE intent_id=? AND state='prepared' AND approval_generation=?''',
                                  (intent_id, approval_generation)).rowcount
            if changed != 1:
                raise ValueError('intent cannot be claimed')
            attempt = str(uuid.uuid4())
            con.execute('INSERT INTO attempts(attempt_id,intent_id,state) VALUES (?,?,?)',
                        (attempt, intent_id, 'submitting'))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'claim', 'submitting'))
            return attempt

    def resolve(self, intent_id: str, attempt_id: str, state: str, *,
                remote_job_id: str | None = None, remote_post_id: str | None = None,
                platform_post_id: str | None = None, platform_url: str | None = None,
                integration_id: str | None = None, evidence_kind: str | None = None,
                provider_instance_id: str | None = None, comment_id: str | None = None,
                published_at: str | None = None) -> None:
        if state not in _RESOLUTIONS:
            raise ValueError('invalid result state')
        ids = (remote_job_id, remote_post_id, platform_post_id, integration_id, provider_instance_id, comment_id)
        if any(value is not None and (not isinstance(value, str) or not value or len(value) > 512
                                     or any(ord(c) < 32 for c in value)) for value in ids):
            raise ValueError('invalid remote identifier')
        if platform_url is not None:
            if not isinstance(platform_url, str) or len(platform_url) > 2048:
                raise ValueError('invalid platform URL')
            parsed = urlsplit(platform_url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('invalid platform URL')
        if state == 'published' and (not (platform_post_id or platform_url)
                                     or evidence_kind not in {'platform_readback', 'provider_confirmed'}):
            raise ValueError('published requires platform evidence')
        _publication_time(published_at)
        if state != 'published' and published_at is not None:
            raise ValueError('publication timestamp before publication')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            attempt = con.execute('SELECT state FROM attempts WHERE intent_id=? AND attempt_id=?',
                                  (intent_id, attempt_id)).fetchone()
            if attempt is None or attempt['state'] not in {'submitting', 'unknown'}:
                raise ValueError('attempt cannot be resolved')
            intent_row = con.execute('SELECT state FROM intents WHERE intent_id=?', (intent_id,)).fetchone()
            if intent_row and intent_row['state'] == 'unknown':
                # A revoke/recovery may win after a request was sent. Preserve a late
                # receipt for readback, but never use it to grant or publish locally.
                if not (remote_job_id or remote_post_id or platform_post_id):
                    raise ValueError('late response has no remote identity')
                fields = ('remote_job_id', 'remote_post_id', 'platform_post_id', 'platform_url',
                          'integration_id', 'evidence_kind', 'provider_instance_id', 'comment_id', 'published_at')
                incoming = (remote_job_id, remote_post_id, platform_post_id, platform_url,
                            integration_id, evidence_kind, provider_instance_id, comment_id, published_at)
                prior = con.execute('SELECT * FROM deliveries WHERE intent_id=?', (intent_id,)).fetchone()
                if prior is not None:
                    for field, value in zip(fields, incoming):
                        if prior[field] is not None and value is not None and prior[field] != value:
                            raise ValueError('late receipt conflict')
                    if not any(prior[field] is None and value is not None for field, value in zip(fields, incoming)):
                        raise ValueError('late receipt already exists')
                changed = con.execute('''UPDATE intents SET version=version+1
                                      WHERE intent_id=? AND state='unknown' ''', (intent_id,)).rowcount
                if changed != 1:
                    raise ValueError('intent state changed')
                con.execute("UPDATE attempts SET state='unknown' WHERE attempt_id=?", (attempt_id,))
                if prior is None:
                    con.execute('''INSERT INTO deliveries(intent_id,remote_job_id,remote_post_id,platform_post_id,
                                platform_url,integration_id,evidence_kind,provider_instance_id,comment_id,published_at)
                                VALUES (?,?,?,?,?,?,?,?,?,?)''', (intent_id, *incoming))
                else:
                    # Fill only absent fields; never overwrite an existing namespace or ID.
                    con.execute('''UPDATE deliveries SET remote_job_id=COALESCE(remote_job_id,?),
                                remote_post_id=COALESCE(remote_post_id,?),
                                platform_post_id=COALESCE(platform_post_id,?),
                                platform_url=COALESCE(platform_url,?), integration_id=COALESCE(integration_id,?),
                                evidence_kind=COALESCE(evidence_kind,?),
                                provider_instance_id=COALESCE(provider_instance_id,?),
                                comment_id=COALESCE(comment_id,?), published_at=COALESCE(published_at,?)
                                WHERE intent_id=?''', (*incoming, intent_id))
                con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                            (intent_id, 'late_receipt', 'unknown'))
                return
            if attempt['state'] != 'submitting':
                raise ValueError('attempt cannot be resolved')
            changed = con.execute('''UPDATE intents SET state=?,version=version+1
                                  WHERE intent_id=? AND state='submitting' ''',
                                  (state, intent_id)).rowcount
            if changed != 1:
                raise ValueError('intent cannot be resolved')
            con.execute('UPDATE attempts SET state=? WHERE attempt_id=?', (state, attempt_id))
            con.execute('''INSERT INTO deliveries(intent_id,remote_job_id,remote_post_id,platform_post_id,
                        platform_url,integration_id,evidence_kind,provider_instance_id,comment_id,published_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (intent_id, remote_job_id, remote_post_id, platform_post_id,
                         platform_url, integration_id, evidence_kind, provider_instance_id, comment_id, published_at))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'resolve', state))

    def reconcile(self, intent_id: str, expected_state: str, *, verifier) -> str:
        """CAS a pending record using pre-fetched evidence; verifier must perform no I/O.

        This checks consistency only, not the truth of a caller-supplied verifier.
        A missing remote identity cannot be guessed or reconciled automatically.
        """
        if expected_state not in {'submitted', 'scheduled', 'unknown'} or not callable(verifier):
            raise ValueError('invalid reconciliation request')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('''SELECT i.*,d.remote_job_id,d.remote_post_id,d.platform_post_id,
                               d.platform_url,d.integration_id,d.provider_instance_id
                               FROM intents i LEFT JOIN deliveries d ON d.intent_id=i.intent_id
                               WHERE i.intent_id=?''', (intent_id,)).fetchone()
            if row is None or row['state'] != expected_state:
                raise ValueError('intent state changed')
            if (not row['provider_instance_id'] or not row['integration_id']
                    or not (row['remote_job_id'] or row['remote_post_id'] or row['platform_post_id'])):
                raise ValueError('remote identity unavailable')
            try:
                evidence = verifier(dict(row))
            except Exception:
                raise ValueError('reconciliation evidence unavailable') from None
            required = {'state', 'platform', 'account_id', 'provider_instance_id', 'integration_id',
                        'remote_job_id', 'remote_post_id', 'platform_post_id', 'platform_url', 'evidence_kind'}
            if (not isinstance(evidence, dict) or not required.issubset(evidence)
                    or set(evidence) - required - {'comment_id', 'published_at'}
                    or evidence['state'] not in {'published', 'failed'}
                    or evidence['evidence_kind'] not in {'platform_readback', 'provider_confirmed'}):
                raise ValueError('invalid reconciliation evidence')
            for field in ('platform', 'account_id', 'provider_instance_id', 'integration_id'):
                if row[field] != evidence[field]:
                    raise ValueError('remote identity mismatch')
            for field in ('remote_job_id', 'remote_post_id', 'platform_post_id'):
                value = evidence[field]
                if value is not None and (not isinstance(value, str) or not value or len(value) > 512
                                          or any(ord(c) < 32 for c in value)):
                    raise ValueError('invalid remote identifier')
                if row[field] and row[field] != value:
                    raise ValueError('remote identity mismatch')
            url = evidence['platform_url']
            if url is not None:
                if not isinstance(url, str) or len(url) > 2048:
                    raise ValueError('invalid platform URL')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('invalid platform URL')
            if evidence['state'] == 'published' and not (evidence['platform_post_id'] or url):
                raise ValueError('published requires platform evidence')
            comment_id = evidence.get('comment_id')
            if comment_id is not None and (not isinstance(comment_id, str) or not comment_id
                                           or len(comment_id) > 512 or any(ord(c) < 32 for c in comment_id)):
                raise ValueError('invalid remote identifier')
            published_at = evidence.get('published_at')
            _publication_time(published_at)
            if evidence['state'] != 'published' and published_at is not None:
                raise ValueError('publication timestamp before publication')
            con.execute('''UPDATE deliveries SET remote_job_id=?,remote_post_id=?,platform_post_id=?,
                        platform_url=?,evidence_kind=?,comment_id=?,published_at=? WHERE intent_id=?''',
                        (evidence['remote_job_id'], evidence['remote_post_id'], evidence['platform_post_id'],
                         url, evidence['evidence_kind'], comment_id, published_at, intent_id))
            con.execute('UPDATE intents SET state=?,version=version+1 WHERE intent_id=? AND state=?',
                        (evidence['state'], intent_id, expected_state))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'reconcile', evidence['state']))
            return evidence['state']

    def enrich_published(self, intent_id: str, expected_version: int, *, verifier) -> bool:
        """Fill absent publication metadata from pre-fetched, consistent readback.

        The verifier must not perform I/O and its evidence is not authenticated by
        this method. Existing receipt fields and evidence kind are never changed.
        """
        if type(expected_version) is not int or expected_version < 0 or not callable(verifier):
            raise ValueError('invalid enrichment request')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("""SELECT i.*,d.remote_job_id,d.remote_post_id,d.platform_post_id,
                               d.integration_id,d.provider_instance_id,d.comment_id,d.published_at
                               FROM intents i JOIN deliveries d ON d.intent_id=i.intent_id
                               WHERE i.intent_id=?""", (intent_id,)).fetchone()
            if row is None or row['state'] != 'published' or row['version'] != expected_version:
                raise ValueError('intent state or version changed')
            if not row['provider_instance_id'] or not row['integration_id'] or not any(
                    row[name] for name in ('remote_job_id', 'remote_post_id', 'platform_post_id')):
                raise ValueError('remote identity unavailable')
            try:
                evidence = verifier(dict(row))
            except Exception:
                raise ValueError('enrichment evidence unavailable') from None
            required = {'state', 'platform', 'account_id', 'provider_instance_id', 'integration_id',
                        'remote_job_id', 'remote_post_id', 'platform_post_id', 'comment_id',
                        'published_at', 'evidence_kind'}
            if (not isinstance(evidence, dict) or set(evidence) != required
                    or evidence['state'] != 'published'
                    or evidence['evidence_kind'] not in {'platform_readback', 'provider_confirmed'}):
                raise ValueError('invalid enrichment evidence')
            for name in ('platform', 'account_id', 'provider_instance_id', 'integration_id'):
                if row[name] != evidence[name]:
                    raise ValueError('remote identity mismatch')
            for name in ('remote_job_id', 'remote_post_id', 'platform_post_id'):
                value = evidence[name]
                if value is not None and (not isinstance(value, str) or not value or len(value) > 512
                                          or any(ord(char) < 32 for char in value)):
                    raise ValueError('invalid remote identifier')
                if row[name] is not None and row[name] != value:
                    raise ValueError('remote identity mismatch')
            comment = evidence['comment_id']
            if comment is not None and (not isinstance(comment, str) or not comment or len(comment) > 512
                                        or any(ord(char) < 32 for char in comment)):
                raise ValueError('invalid remote identifier')
            published_at = evidence['published_at']
            _publication_time(published_at)
            for name, value in (('comment_id', comment), ('published_at', published_at)):
                if row[name] is not None and value is not None and row[name] != value:
                    raise ValueError('enrichment metadata conflict')
            if not ((row['comment_id'] is None and comment is not None)
                    or (row['published_at'] is None and published_at is not None)):
                return False
            changed = con.execute("UPDATE intents SET version=version+1 WHERE intent_id=? "
                                  "AND state='published' AND version=?", (intent_id, expected_version)).rowcount
            if changed != 1:
                raise ValueError('intent state or version changed')
            con.execute('UPDATE deliveries SET comment_id=COALESCE(comment_id,?), '
                        'published_at=COALESCE(published_at,?) WHERE intent_id=?',
                        (comment, published_at, intent_id))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'receipt_enriched', 'published'))
            return True

    def lookup_platform(self, platform: str, account_id: str, platform_post_id: str) -> list[dict]:
        if any(not isinstance(v, str) or not v.strip() for v in (platform, account_id, platform_post_id)):
            raise ValueError('platform lookup namespace required')
        with self._connect() as con:
            rows = con.execute('''SELECT i.*,d.remote_job_id,d.remote_post_id,d.platform_post_id,d.platform_url,
                                d.integration_id,d.provider_instance_id,d.evidence_kind,d.comment_id,d.published_at FROM intents i
                                JOIN deliveries d ON d.intent_id=i.intent_id
                                WHERE i.platform=? AND i.account_id=? AND d.platform_post_id=?''',
                               (platform, account_id, platform_post_id)).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def lookup_platform_source(ledger_path: Path | str, platform: str, account_id: str,
                               platform_post_id: str, *, expected_station_id: str) -> list[dict]:
        """Read source lineage for an exact platform ID without changing the ledger.

        Matching the station UUID is a consistency check, not station authority or
        proof that a provider receipt is authentic. The caller must validate the
        local DB path and its provenance before calling. Ambiguous
        matches are returned separately; absence is not proof of non-publication.
        """
        if not isinstance(ledger_path, (str, Path)) or not str(ledger_path).strip():
            raise ValueError('source ledger is unavailable')
        for value in (platform, account_id, platform_post_id):
            if (not isinstance(value, str) or not value or value != value.strip() or len(value) > 512
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError('platform lookup namespace required')
        expected = _station_uuid(expected_station_id)
        path = Path(ledger_path).absolute()
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro',
                                     timeout=5.0, uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute('BEGIN')
            open_station_identity(con, expected)
            rows = con.execute('''SELECT i.station_id,i.channel_id,i.campaign_id,i.content_id,i.post_id,
                                  i.platform,i.account_id,i.occurrence_key,i.intent_id,i.state,i.payload_digest,
                                  d.provider_instance_id,d.integration_id,d.remote_job_id,d.remote_post_id,
                                  d.platform_post_id,d.platform_url,d.published_at,d.evidence_kind
                                  FROM main.intents AS i JOIN main.deliveries AS d ON d.intent_id=i.intent_id
                                  WHERE i.station_id=? AND i.platform=? AND i.account_id=? AND d.platform_post_id=?
                                  ORDER BY i.intent_id LIMIT 101''',
                               (expected, platform, account_id, platform_post_id)).fetchall()
            if len(rows) > 100:
                raise ValueError('platform lookup has too many matches')
            return [dict(row) for row in rows]

    def begin_cancel(self, intent_id: str, *, by: str, quote: str) -> str:
        """Persist a cancellation intent before caller invokes any remote action."""
        if any(not isinstance(v, str) or not v.strip() for v in (by, quote)):
            raise ValueError('cancellation evidence required')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('''SELECT i.state,d.remote_job_id,d.remote_post_id,d.integration_id,
                               d.provider_instance_id FROM intents i LEFT JOIN deliveries d
                               ON d.intent_id=i.intent_id WHERE i.intent_id=?''', (intent_id,)).fetchone()
            if row is None or row['state'] not in {'submitted', 'scheduled', 'cancelling'}:
                raise ValueError('intent cannot be cancelled')
            if not (row['remote_job_id'] or row['remote_post_id']) or not row['integration_id'] or not row['provider_instance_id']:
                raise ValueError('remote identity unavailable')
            if con.execute('SELECT 1 FROM cancel_attempts WHERE intent_id=?', (intent_id,)).fetchone():
                raise ValueError('cancellation attempt already exists')
            con.execute("UPDATE intents SET state='cancelling',version=version+1 WHERE intent_id=?", (intent_id,))
            cancel_id = str(uuid.uuid4())
            con.execute('INSERT INTO cancel_attempts(cancel_id,intent_id,state,actor,quote) VALUES (?,?,?,?,?)',
                        (cancel_id, intent_id, 'pending', by, quote))
            con.execute('INSERT INTO events(intent_id,kind,state,actor,quote) VALUES (?,?,?,?,?)',
                        (intent_id, 'cancel_claim', 'cancelling', by, quote))
            return cancel_id

    def finish_cancel(self, intent_id: str, cancel_id: str, *, outcome: str, verifier=None) -> str:
        """Record a cancel result; verifier handles only pre-fetched data, not network I/O."""
        if outcome not in {'confirmed', 'unknown'}:
            raise ValueError('invalid cancellation outcome')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('''SELECT i.*,d.remote_job_id,d.remote_post_id,d.integration_id,
                               d.provider_instance_id FROM intents i LEFT JOIN deliveries d
                               ON d.intent_id=i.intent_id WHERE i.intent_id=?''', (intent_id,)).fetchone()
            attempt = con.execute('SELECT state FROM cancel_attempts WHERE intent_id=? AND cancel_id=?',
                                  (intent_id, cancel_id)).fetchone()
            allowed = (row is not None and attempt is not None and (
                (row['state'] == 'cancelling' and attempt['state'] == 'pending')
                or (outcome == 'confirmed' and row['state'] == 'unknown' and attempt['state'] == 'unknown')))
            if not allowed:
                raise ValueError('cancellation state changed')
            state = 'unknown'
            if outcome == 'confirmed':
                if not callable(verifier):
                    raise ValueError('cancellation evidence required')
                try:
                    evidence = verifier(dict(row))
                except Exception:
                    raise ValueError('cancellation evidence unavailable') from None
                required = {'state', 'platform', 'account_id', 'provider_instance_id', 'integration_id',
                            'remote_job_id', 'remote_post_id', 'evidence_kind'}
                if (not isinstance(evidence, dict) or set(evidence) != required
                        or evidence['state'] != 'cancelled' or evidence['evidence_kind'] != 'provider_confirmed'):
                    raise ValueError('invalid cancellation evidence')
                for field in ('platform', 'account_id', 'provider_instance_id', 'integration_id',
                              'remote_job_id', 'remote_post_id'):
                    if row[field] != evidence[field]:
                        raise ValueError('remote identity mismatch')
                state = 'cancelled'
            con.execute('UPDATE intents SET state=?,version=version+1 WHERE intent_id=? AND state=?',
                        (state, intent_id, row['state']))
            con.execute('UPDATE cancel_attempts SET state=? WHERE cancel_id=? AND state=?',
                        (state, cancel_id, attempt['state']))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'cancel_result', state))
            return state

    def lookup_remote(self, provider_instance_id: str, integration_id: str, remote_post_id: str) -> list[dict]:
        if any(not isinstance(v, str) or not v.strip() for v in (provider_instance_id, integration_id, remote_post_id)):
            raise ValueError('remote lookup namespace required')
        with self._connect() as con:
            rows = con.execute('''SELECT i.*,d.remote_job_id,d.remote_post_id,d.platform_post_id,d.platform_url,
                                d.integration_id,d.provider_instance_id,d.evidence_kind,d.comment_id,d.published_at FROM intents i
                                JOIN deliveries d ON d.intent_id=i.intent_id
                                WHERE d.provider_instance_id=? AND d.integration_id=? AND d.remote_post_id=?''',
                               (provider_instance_id, integration_id, remote_post_id)).fetchall()
            return [dict(row) for row in rows]

    def track_fixture_worker(self, intent_id: str, action_id: str, *, kind: str, worker) -> None:
        """Associate a caller-owned process handle with a synthetic in-flight action.

        This does not establish which process performed an action in production.
        """
        if not self._fixture_mode:
            raise ValueError('fixture-only operation')
        if self._closed or kind not in {'submit', 'cancel'} or type(worker) is not subprocess.Popen:
            raise ValueError('invalid fixture worker')
        if worker.poll() is not None:
            raise ValueError('worker not running')
        with self._connect() as con:
            if kind == 'submit':
                row = con.execute("SELECT 1 FROM attempts a JOIN intents i ON a.intent_id=i.intent_id "
                                  "WHERE i.intent_id=? AND a.attempt_id=? AND i.state='submitting' "
                                  "AND a.state='submitting'", (intent_id, action_id)).fetchone()
            else:
                row = con.execute("SELECT 1 FROM cancel_attempts a JOIN intents i ON a.intent_id=i.intent_id "
                                  "WHERE i.intent_id=? AND a.cancel_id=? AND i.state='cancelling' "
                                  "AND a.state='pending'", (intent_id, action_id)).fetchone()
            if row is None:
                raise ValueError('fixture action not in flight')
        key = (kind, intent_id, action_id)
        if key in self._fixture_workers:
            raise ValueError('fixture worker already tracked')
        self._fixture_workers[key] = worker

    def recover_fixture_worker(self, intent_id: str, action_id: str, *, kind: str, worker) -> None:
        """Conservatively recover a tracked, stopped synthetic process to unknown."""
        if not self._fixture_mode:
            raise ValueError('fixture-only operation')
        if self._closed:
            raise ValueError('ledger is closed')
        key = (kind, intent_id, action_id)
        if self._fixture_workers.get(key) is not worker or type(worker) is not subprocess.Popen:
            raise ValueError('fixture worker not tracked')
        if worker.poll() is None:
            raise ValueError('worker still running')
        if kind == 'submit':
            self.recover_inflight(intent_id)
        elif kind == 'cancel':
            self.finish_cancel(intent_id, action_id, outcome='unknown')
        else:
            raise ValueError('invalid fixture worker')
        self._fixture_workers.pop(key, None)

    def recover_inflight(self, intent_id: str) -> None:
        """Caller must ensure the original process is dead before recovery."""
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            changed = con.execute('''UPDATE intents SET state='unknown',version=version+1
                                  WHERE intent_id=? AND state='submitting' ''', (intent_id,)).rowcount
            if changed != 1:
                raise ValueError('intent is not in flight')
            con.execute("UPDATE attempts SET state='unknown' WHERE intent_id=? AND state='submitting'",
                        (intent_id,))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent_id, 'recover', 'unknown'))

    def revoke(self, intent_id: str, expected_generation: int, *, by: str, quote: str, gate: str) -> str:
        if any(not isinstance(v, str) or not v.strip() for v in (by, quote, gate)):
            raise ValueError('revocation evidence required')
        if gate not in {'g1', 'g2', 'g3'}:
            raise ValueError('invalid gate')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT state,approval_generation FROM intents WHERE intent_id=?',
                              (intent_id,)).fetchone()
            if row is None or row['approval_generation'] != expected_generation:
                raise ValueError('approval generation mismatch')
            state = {'prepared': 'cancelled', 'submitting': 'unknown',
                     'submitted': 'cancelling', 'scheduled': 'cancelling'}.get(row['state'])
            if state is None:
                raise ValueError('intent cannot be revoked')
            con.execute('''UPDATE intents SET state=?,approval_generation=approval_generation+1,
                        version=version+1 WHERE intent_id=?''', (state, intent_id))
            con.execute('''INSERT INTO events(intent_id,kind,state,actor,quote,gate)
                        VALUES (?,?,?,?,?,?)''', (intent_id, 'revoke', state, by, quote, gate))
            return state

    def clone_fixture_for_restore(self):
        """Clone a fixture ledger into RAM, quarantining all dispatch after restore.

        This does not prove the restored history is complete, nor unlock it.
        """
        if not self._fixture_mode or self._closed:
            raise ValueError('fixture-only operation')
        clone = type(self).synthetic_memory()
        try:
            with self._connect() as source:
                with clone._connect() as destination:
                    source.backup(destination)
                    destination.execute("UPDATE metadata SET value='1' WHERE key='recovery_required'")
            return clone
        except BaseException:
            clone.close()
            raise

    def backup(self, destination: Path | str) -> None:
        if self._fixture_mode:
            raise ValueError('fixture-only ledger does not write backups')
        dest_path = Path(destination)
        if dest_path.resolve() == self.path.resolve() or dest_path.exists():
            raise ValueError('backup destination already exists or is source')
        fd, temporary = tempfile.mkstemp(prefix='.delivery-backup-', suffix='.tmp',
                                         dir=str(dest_path.parent))
        os.close(fd)
        try:
            with self._connect() as source:
                with closing(sqlite3.connect(temporary)) as dest:
                    with dest:
                        source.backup(dest)
                        dest.execute("UPDATE metadata SET value='1' WHERE key='recovery_required'")
            # Publishing a hard link is atomic and cannot overwrite an existing path.
            os.link(temporary, str(dest_path))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def import_legacy(self, key: dict[str, str], evidence: str) -> str:
        """Create a non-dispatchable initial tombstone for a known legacy record."""
        if (set(key) != set(KEY_FIELDS) or key.get('occurrence_key') != 'initial'
                or any(not isinstance(key[k], str) or not key[k].strip() for k in KEY_FIELDS)
                or not isinstance(evidence, str) or not evidence.strip()):
            raise ValueError('invalid legacy mapping')
        evidence_ref = _evidence_locator(evidence)
        reference_sha256 = hashlib.sha256(evidence_ref.encode('utf-8')).hexdigest()
        import_id = str(uuid.uuid4())
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            values = tuple(key[k] for k in KEY_FIELDS)
            query = ' AND '.join(f'{field}=?' for field in KEY_FIELDS)
            existing = con.execute(f'SELECT intent_id FROM intents WHERE {query}', values).fetchone()
            if existing:
                raise ValueError('legacy mapping conflicts with existing intent')
            intent = str(uuid.uuid4())
            placeholders = ','.join('?' for _ in range(14))
            con.execute(f'INSERT INTO intents VALUES ({placeholders})',
                        (intent, *values, reference_sha256, 'legacy', 0, 'migration_review', 0))
            con.execute('''INSERT INTO legacy_import_evidence(import_id,intent_id,reference_sha256,evidence_ref)
                        VALUES (?,?,?,?)''', (import_id, intent, reference_sha256, evidence_ref))
            con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                        (intent, 'legacy_import', 'migration_review'))
            return intent

    def import_legacy_ambiguous(self, candidates: list[dict[str, str]], evidence: str) -> list[str]:
        """Atomically quarantine every explicitly supplied possible initial intent."""
        if (not isinstance(candidates, list) or not candidates or not isinstance(evidence, str)
                or not evidence.strip() or len(evidence) > 512):
            raise ValueError('invalid legacy candidates')
        evidence_ref = _evidence_locator(evidence)
        keys = []
        for key in candidates:
            if (not isinstance(key, dict) or set(key) != set(KEY_FIELDS) or key.get('occurrence_key') != 'initial'
                    or any(not isinstance(key[k], str) or not key[k].strip() for k in KEY_FIELDS)):
                raise ValueError('invalid legacy candidates')
            values = tuple(key[k] for k in KEY_FIELDS)
            if values not in keys:
                keys.append(values)
        query = ' AND '.join(f'{field}=?' for field in KEY_FIELDS)
        intents = []
        import_id = str(uuid.uuid4())
        reference_sha256 = hashlib.sha256(evidence.encode('utf-8')).hexdigest()
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for values in keys:
                row = con.execute(f'SELECT intent_id,state FROM intents WHERE {query}', values).fetchone()
                if row:
                    if row['state'] not in {'prepared', 'migration_review'}:
                        raise ValueError('in-flight or completed intent requires manual review')
                    intent = row['intent_id']
                    con.execute("UPDATE intents SET state='migration_review',version=version+1 WHERE intent_id=?",
                                (intent,))
                else:
                    intent = str(uuid.uuid4())
                    placeholders = ','.join('?' for _ in range(14))
                    con.execute(f'INSERT INTO intents VALUES ({placeholders})',
                                (intent, *values, reference_sha256, 'legacy', 0, 'migration_review', 0))
                # The relative locator is data, not proof that the file is safe or exists.
                con.execute('''INSERT INTO legacy_import_evidence(import_id,intent_id,reference_sha256,evidence_ref)
                            VALUES (?,?,?,?)''', (import_id, intent, reference_sha256, evidence_ref))
                con.execute('INSERT INTO events(intent_id,kind,state) VALUES (?,?,?)',
                            (intent, 'legacy_ambiguous', 'migration_review'))
                intents.append(intent)
            return intents

    @staticmethod
    def _scope_id(scope: dict[str, str]) -> str:
        if (set(scope) != set(SCOPE_FIELDS)
                or any(not isinstance(scope[k], str) or not scope[k].strip() for k in SCOPE_FIELDS)
                or scope['gate'] not in {'g1', 'g2', 'g3'}):
            raise ValueError('invalid approval scope')
        return json.dumps([scope[k] for k in SCOPE_FIELDS], ensure_ascii=False, separators=(',', ':'))

    @classmethod
    def _verified_proof(cls, scope: dict[str, str], verifier):
        """Check a verifier result's consistency; this does not authenticate a human."""
        if not callable(verifier):
            raise ValueError('scope proof verifier required')
        try:
            result = verifier(dict(scope))
        except Exception:
            # External errors may include credentials or full upstream responses.
            raise ValueError('scope proof verification failed') from None
        if (not isinstance(result, dict) or set(result) != {'gate', 'scope', 'by', 'quote', 'source_digest'}
                or result['scope'] != scope or result['gate'] != scope['gate']
                or any(not isinstance(result[k], str) or not result[k].strip() for k in ('by', 'quote', 'source_digest'))):
            raise ValueError('invalid scope proof')
        source = result['source_digest']
        if len(source) != 64 or any(c not in '0123456789abcdef' for c in source):
            raise ValueError('invalid scope proof digest')
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return source, result['by'], hashlib.sha256(raw).hexdigest(), hashlib.sha256(result['quote'].encode('utf-8')).hexdigest()

    def bind_scope_proof(self, scope: dict[str, str], generation: int, *, verifier) -> None:
        """Bind a verified source snapshot to an existing active generation.

        The verifier is a dependency, not an authentication boundary. Do not use
        this alone to enable real dispatch while source files can change independently.
        """
        scope_id = self._scope_id(scope)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT generation,active FROM approval_scopes WHERE scope_id=?', (scope_id,)).fetchone()
            if row is None or row['generation'] != generation or row['active'] != 1:
                raise ValueError('scope generation mismatch')
            source, actor, digest, quote_digest = self._verified_proof(scope, verifier)
            old = con.execute('SELECT proof_digest FROM scope_proofs WHERE scope_id=? AND generation=?',
                              (scope_id, generation)).fetchone()
            if old:
                if old['proof_digest'] != digest:
                    raise ValueError('scope proof mismatch')
                return
            con.execute('INSERT INTO scope_proofs VALUES (?,?,?,?,?,?)',
                        (scope_id, generation, source, digest, actor, quote_digest))

    def grant_fixture(self, scope: dict[str, str], expected_generation: int, *, event_id: str, verifier) -> int:
        """Advance a scope for a synthetic fixture event; not an authorization."""
        if not self._fixture_mode:
            raise ValueError('fixture-only operation')
        if not isinstance(event_id, str):
            raise ValueError('invalid fixture event')
        try:
            parsed = uuid.UUID(event_id)
        except (ValueError, AttributeError):
            raise ValueError('invalid fixture event') from None
        if parsed.version != 4 or str(parsed) != event_id:
            raise ValueError('invalid fixture event')
        scope_id = self._scope_id(scope)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute('SELECT 1 FROM fixture_grants WHERE event_id=?', (event_id,)).fetchone():
                raise ValueError('fixture event already used')
            row = con.execute('SELECT generation,active FROM approval_scopes WHERE scope_id=?',
                              (scope_id,)).fetchone()
            if row is None or row['generation'] != expected_generation or not row['active']:
                raise ValueError('scope generation mismatch')
            source, actor, digest, quote_digest = self._verified_proof(scope, verifier)
            if con.execute('SELECT 1 FROM scope_proofs WHERE scope_id=? AND source_digest=?',
                           (scope_id, source)).fetchone():
                raise ValueError('fixture grant requires new synthetic proof')
            generation = expected_generation + 1
            con.execute('UPDATE approval_scopes SET generation=? WHERE scope_id=?', (generation, scope_id))
            con.execute('INSERT INTO scope_proofs VALUES (?,?,?,?,?,?)',
                        (scope_id, generation, source, digest, actor, quote_digest))
            con.execute('INSERT INTO fixture_grants VALUES (?,?,?)', (event_id, scope_id, generation))
            return generation

    def reapprove_scope(self, scope: dict[str, str], expected_generation: int, *, verifier) -> int:
        """Fail closed until the source writer supplies a fresh approval event ID.

        A changed source digest alone can reflect an unrelated edit and does not
        establish that a new human approval took place.
        """
        scope_id = self._scope_id(scope)
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT generation,active FROM approval_scopes WHERE scope_id=?', (scope_id,)).fetchone()
            if row is None or row['generation'] != expected_generation or row['active'] != 0:
                raise ValueError('scope generation mismatch')
            raise ValueError('fresh approval proof identity unavailable')

    def bind_scope(self, scope: dict[str, str], generation: int) -> None:
        """Initialize a generation cache; never constitutes or grants approval."""
        scope_id = self._scope_id(scope)
        if type(generation) is not int or generation < 1:
            raise ValueError('invalid scope generation')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT generation FROM approval_scopes WHERE scope_id=?', (scope_id,)).fetchone()
            if row and row['generation'] != generation:
                raise ValueError('scope generation mismatch')
            con.execute('INSERT OR IGNORE INTO approval_scopes(scope_id,generation) VALUES (?,?)', (scope_id, generation))

    def revoke_scope(self, scope: dict[str, str], expected_generation: int, *, by: str,
                     quote: str, gate: str) -> int:
        scope_id = self._scope_id(scope)
        if gate != scope['gate'] or any(not isinstance(v, str) or not v.strip() for v in (by, quote)):
            raise ValueError('revocation evidence required')
        with self._connect() as con:
            con.execute('BEGIN IMMEDIATE')
            updated = con.execute('''UPDATE approval_scopes SET generation=generation+1,active=0
                                   WHERE scope_id=? AND generation=? AND active=1''',
                                  (scope_id, expected_generation)).rowcount
            if updated != 1:
                raise ValueError('scope generation mismatch')
            con.execute('''INSERT INTO scope_events(scope_id,old_generation,actor,quote,gate)
                        VALUES (?,?,?,?,?)''', (scope_id, expected_generation, by, quote, gate))
            rows = con.execute('''SELECT i.intent_id,i.state FROM intents i JOIN intent_scopes s
                                ON i.intent_id=s.intent_id WHERE s.scope_id=?''', (scope_id,)).fetchall()
            for row in rows:
                state = {'prepared': 'cancelled', 'submitting': 'unknown',
                         'submitted': 'cancelling', 'scheduled': 'cancelling'}.get(row['state'])
                if state:
                    con.execute('UPDATE intents SET state=?,version=version+1 WHERE intent_id=?',
                                (state, row['intent_id']))
                    con.execute('''INSERT INTO events(intent_id,kind,state,actor,quote,gate)
                                VALUES (?,?,?,?,?,?)''', (row['intent_id'], 'scope_revoke', state, by, quote, gate))
            return expected_generation + 1
