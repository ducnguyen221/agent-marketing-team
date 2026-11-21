"""Synthetic Group UI session backed by a caller-owned fixture database."""
from __future__ import annotations

import copy
import threading
import uuid
from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _GROUP_UI_SEAL
from scripts.social.fixture_ledger import _snapshot_digest


class GroupSQLiteSession:
    """One offline UI session; observations and source are caller-supplied fixtures."""

    def __init__(self, ledger: DestinationFixtureLedger, item_id: str, snapshot: dict[str, Any]) -> None:
        if type(ledger) is not DestinationFixtureLedger or not isinstance(snapshot, dict):
            raise ValueError('Group SQLite fixture required')
        snapshot = copy.deepcopy(snapshot)
        row = ledger.get(item_id)
        if (row['state'] != 'prepared' or row['grant_version'] != row['version']
                or _snapshot_digest({'destination_id': row['destination_id'], 'payload': snapshot}) != row['snapshot_digest']
                or not row['destination_id'].startswith('fixture-group-')):
            raise ValueError('Group fixture session mismatch')
        self._ledger, self._item_id, self._snapshot = ledger, item_id, snapshot
        self._version, self._destination = row['version'], row['destination_id']
        self._digest, self._stage = _snapshot_digest(snapshot), 'ready'
        self._lock = threading.RLock()

    def _check(self, view: Any, stage: str) -> None:
        try:
            valid = (isinstance(view, dict) and set(view) == {'stage', 'destination', 'snapshot', 'controls_present'}
                     and view['stage'] == stage and view['destination'] == self._destination
                     and view['controls_present'] is True and _snapshot_digest(view['snapshot']) == self._digest)
        except (ValueError, TypeError, RecursionError):
            valid = False
        if not valid:
            self._stage = 'stopped'
            raise ValueError('Group fixture observation mismatch')

    def observe(self, view: dict[str, Any]) -> None:
        with self._lock:
            if self._stage not in ('ready', 'entered', 'preview'):
                raise ValueError('Group fixture step refused')
            stage = self._stage
            self._check(view, stage)
            self._stage = {'ready': 'entered', 'entered': 'preview', 'preview': 'confirm'}[stage]

    def confirm(self, view: dict[str, Any], *, _attempt_id: str | None = None) -> str:
        with self._lock:
            if self._stage != 'confirm':
                raise ValueError('Group fixture confirmation refused')
            self._check(view, 'preview')
            try:
                attempt = self._ledger.claim_group_fixture(self._item_id, expected_version=self._version,
                    snapshot=self._snapshot, _ui_seal=_GROUP_UI_SEAL, _attempt_id=_attempt_id)
            except ValueError:
                self._stage = 'stopped'
                raise
            self._stage = 'submitting'
            return attempt


class GroupSQLiteForm:
    """In-process test bridge for one SQLite fixture intent and local form."""

    def __init__(self, ledger: DestinationFixtureLedger, item_id: str, snapshot: dict[str, Any]) -> None:
        if type(ledger) is not DestinationFixtureLedger or not isinstance(snapshot, dict):
            raise ValueError('Group fixture form required')
        self._ledger, self._item_id, self._snapshot = ledger, item_id, copy.deepcopy(snapshot)
        self._actor = self._snapshot['v1_binding']['identity']['account']
        self._lock = threading.RLock()
        self._revision = 0
        self._current: tuple[str, GroupSQLiteSession] | None = None
        self._claimed = False

    def _view(self, view: dict[str, Any], actor: str) -> dict[str, Any]:
        if (actor != self._actor or not isinstance(view, dict)
                or set(view) != {'stage', 'destination', 'snapshot', 'controls_present'}
                or not isinstance(view['snapshot'], dict) or set(view['snapshot']) != {
                    'action', 'text', 'media_kind', 'media_id', 'destination_type', 'source', 'reuse_permission'}):
            raise ValueError('Group fixture form observation mismatch')
        return {**view, 'snapshot': {**view['snapshot'], 'v1_binding': copy.deepcopy(self._snapshot['v1_binding'])}}

    def preview(self, view: dict[str, Any], *, actor: str, revision: int) -> str:
        with self._lock:
            if self._claimed:
                raise ValueError('Group fixture form locked')
            if type(revision) is not int or not self._revision < revision <= 2**63 - 1:
                raise ValueError('stale fixture revision')
            self._revision = revision
            self._current = None
            observed = self._view(view, actor)
            if observed['stage'] != 'preview':
                raise ValueError('invalid fixture preview')
            session = GroupSQLiteSession(self._ledger, self._item_id, self._snapshot)
            for stage in ('ready', 'entered', 'preview'):
                session.observe({**observed, 'stage': stage})
            preview_id = str(uuid.uuid4())
            self._current = (preview_id, session)
            return preview_id

    def invalidate(self, preview_id: str) -> None:
        with self._lock:
            if not self._claimed and self._current is not None and self._current[0] == preview_id:
                self._current = None

    def confirm(self, preview_id: str, view: dict[str, Any], *, actor: str) -> str:
        with self._lock:
            if self._current is None or self._current[0] != preview_id:
                raise ValueError('Group fixture preview unavailable')
            if self._claimed:
                raise ValueError('Group fixture already claimed')
            try:
                observed = self._view(view, actor)
                attempt = self._current[1].confirm(observed, _attempt_id=preview_id)
                self._claimed = True
                return attempt
            except ValueError:
                self._current = None
                raise

    def status(self, preview_id: str) -> dict[str, str]:
        with self._lock:
            if self._current is None or self._current[0] != preview_id:
                raise ValueError('Group fixture preview unavailable')
            row = self._ledger.get(self._item_id)
            if row['state'] != 'prepared' and row['attempt_id'] != preview_id:
                raise ValueError('Group fixture preview unavailable')
            return {'intent': row['state'], 'preview': 'sqlite_fixture'}


class GroupSQLiteRecovery:
    """Read-only test bridge for one independently selected synthetic intent."""

    def __init__(self, ledger: DestinationFixtureLedger, item_id: str) -> None:
        if type(ledger) is not DestinationFixtureLedger or not isinstance(item_id, str):
            raise ValueError('Group fixture recovery unavailable')
        self._ledger, self._item_id = ledger, item_id

    def status(self, preview_id: str) -> dict[str, str]:
        return self._ledger.recover_group_fixture(self._item_id, attempt=preview_id)
