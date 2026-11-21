"""Synthetic UI observations bound to an in-memory ledger, never a UI driver.

No browser, files, network, platform authentication or real publishing is used.
The caller supplies observations as fake data; this is not screen verification.
"""
from __future__ import annotations

import threading
import uuid
import copy
from typing import Any

from scripts.lib.delivery_anchors import _valid_identity
from scripts.social.fixture_ledger import FixtureLedger, _GROUP_UI_SEAL, _snapshot_digest

_ACTIONS = {'group_text': ('none', 'awaiting_moderation'),
            'group_image': ('image', 'awaiting_moderation'),
            'group_video': ('video', 'awaiting_moderation'),
            'video_inbox': ('video', 'awaiting_creator'),
            'duet': ('video', 'awaiting_creator'),
            'stitch': ('video', 'awaiting_creator')}


class FixtureUI:
    """One synthetic action, preserving a single occurrence across methods."""

    def __init__(self, ledger: FixtureLedger, item_id: str, snapshot: dict[str, Any]) -> None:
        if type(ledger) is not FixtureLedger or not isinstance(snapshot, dict):
            raise ValueError('fixture UI inputs required')
        action = snapshot.get('action')
        if (not isinstance(action, str) or action not in _ACTIONS
                or set(snapshot) not in ({'action', 'text', 'media_kind', 'media_id', 'destination_type',
                                          'source', 'reuse_permission'},
                                         {'action', 'text', 'media_kind', 'media_id', 'destination_type',
                                          'source', 'reuse_permission', 'v1_binding'})
                or not isinstance(snapshot['text'], str) or not snapshot['text'].strip()
                or snapshot['media_kind'] != _ACTIONS[action][0]):
            raise ValueError('invalid fixture UI action')
        if snapshot['media_kind'] == 'none':
            if snapshot['media_id'] is not None:
                raise ValueError('unexpected fixture media')
        elif not _valid_identity(snapshot['media_id']) or not snapshot['media_id'].startswith('fixture-'):
            raise ValueError('fixture media required')
        if action in ('duet', 'stitch'):
            if (not _valid_identity(snapshot['source']) or not snapshot['source'].startswith('fixture-')
                    or snapshot['reuse_permission'] is not True):
                raise ValueError('fixture source permission required')
        elif snapshot['source'] is not None or snapshot['reuse_permission'] is not False:
            raise ValueError('unexpected fixture source')
        item = ledger.get(item_id)
        digest = _snapshot_digest(snapshot)
        platform, destination_type = ('facebook', 'group') if action.startswith('group_') else ('tiktok', 'profile')
        if (item['state'] != 'prepared' or item['grant'] is None or item['digest'] != digest
                or not item['identity']['destination'].startswith('fixture-')
                or item['identity']['platform'] != platform or snapshot['destination_type'] != destination_type):
            raise ValueError('fixture intent mismatch')
        self._ledger, self._item_id = ledger, item_id
        self._target, self._digest, self._version = item['identity']['destination'], digest, item['version']
        self._expected_result = _ACTIONS[action][1]
        self._step = 'ready'
        self._lock = threading.RLock()

    def _check(self, view: Any, stage: str) -> None:
        try:
            valid = (isinstance(view, dict) and set(view) == {'stage', 'destination', 'snapshot', 'controls_present'}
                     and view['stage'] == stage and view['destination'] == self._target
                     and view['controls_present'] is True and _snapshot_digest(view['snapshot']) == self._digest)
        except (ValueError, TypeError, RecursionError):
            valid = False
        if not valid:
            self._step = 'stopped'
            raise ValueError('fixture observation mismatch')

    def observe(self, view: dict[str, Any]) -> None:
        with self._lock:
            if self._step not in ('ready', 'entered', 'preview'):
                raise ValueError('fixture UI step refused')
            step = self._step
            self._check(view, step)
            self._step = {'ready': 'entered', 'entered': 'preview', 'preview': 'confirm'}[step]

    def confirm(self, view: dict[str, Any]) -> str:
        with self._lock:
            if self._step != 'confirm':
                raise ValueError('fixture UI confirmation refused')
            self._check(view, 'preview')
            try:
                attempt = self._ledger.claim(self._item_id, method='ui', expected_version=self._version,
                                             _ui_seal=_GROUP_UI_SEAL)
            except ValueError:
                self._step = 'stopped'
                raise
            self._step = 'submitting'
            return attempt

    def finish(self, state: str, *, receipt: dict[str, str] | None = None) -> None:
        with self._lock:
            if self._step != 'submitting' or state not in ('unknown', self._expected_result):
                raise ValueError('fixture UI outcome refused')
            self._ledger.finish(self._item_id, state, receipt=receipt)
            self._step = 'finished'


class FixtureUIBridge:
    """In-process protocol exercise; input is synthetic, not a screen observation."""

    def __init__(self, ledger: FixtureLedger, item_id: str, snapshot: dict[str, Any]) -> None:
        self._session = FixtureUI(ledger, item_id, snapshot)
        self._ledger, self._item_id = ledger, item_id
        self._state = 'ready'
        self._lock = threading.RLock()

    def preview(self, view: dict[str, Any]) -> None:
        with self._lock:
            if self._state != 'ready' or not isinstance(view, dict) or view.get('stage') != 'preview':
                raise ValueError('fixture preview refused')
            for stage in ('ready', 'entered', 'preview'):
                self._session.observe({**view, 'stage': stage})
            self._state = 'preview'

    def invalidate(self) -> None:
        with self._lock:
            if self._state != 'preview':
                raise ValueError('fixture invalidation refused')
            self._state = 'invalidated'

    def confirm(self, view: dict[str, Any]) -> str:
        with self._lock:
            if self._state != 'preview':
                raise ValueError('fixture confirmation refused')
            try:
                attempt = self._session.confirm(view)
            except ValueError:
                self._state = 'stopped'
                raise
            self._state = 'submitting'
            return attempt

    def finish(self, state: str, *, receipt: dict[str, str] | None = None) -> None:
        with self._lock:
            if self._state != 'submitting':
                raise ValueError('fixture finish refused')
            self._session.finish(state, receipt=receipt)
            self._state = 'finished'

    def status(self) -> dict[str, str]:
        with self._lock:
            return {'intent': self._ledger.get(self._item_id)['state'], 'preview': self._state}


class FixturePreviewCoordinator:
    """Coordinate one synthetic form in one process; no browser or transport."""

    def __init__(self, ledger: FixtureLedger) -> None:
        if type(ledger) is not FixtureLedger:
            raise ValueError('fixture ledger required')
        self._ledger = ledger
        self._lock = threading.RLock()
        self._current: tuple[str, FixtureUIBridge] | None = None
        self._revision = 0

    def preview(self, item_id: str, snapshot: dict[str, Any], view: dict[str, Any], *, revision: int) -> str:
        with self._lock:
            if type(revision) is not int or not self._revision < revision <= 2**63 - 1:
                raise ValueError('stale fixture revision')
            if self._current is not None:
                old = self._current[1]
                state = old.status()['preview']
                if state in ('submitting', 'finished'):
                    raise ValueError('fixture form locked')
                if state == 'preview':
                    old.invalidate()
                self._current = None
            self._revision = revision
            bridge = FixtureUIBridge(self._ledger, item_id, snapshot)
            bridge.preview(view)
            preview_id = str(uuid.uuid4())
            self._current = (preview_id, bridge)
            return preview_id

    def invalidate(self, preview_id: str) -> None:
        with self._lock:
            if self._current is None or self._current[0] != preview_id:
                return
            bridge = self._current[1]
            if bridge.status()['preview'] == 'preview':
                bridge.invalidate()

    def _bridge(self, preview_id: str) -> FixtureUIBridge:
        if self._current is None or self._current[0] != preview_id:
            raise ValueError('fixture preview unavailable')
        return self._current[1]

    def confirm(self, preview_id: str, view: dict[str, Any]) -> str:
        with self._lock:
            return self._bridge(preview_id).confirm(view)

    def finish(self, preview_id: str, state: str, *, receipt: dict[str, str] | None = None) -> None:
        with self._lock:
            self._bridge(preview_id).finish(state, receipt=receipt)

    def status(self, preview_id: str) -> dict[str, str]:
        with self._lock:
            return self._bridge(preview_id).status()


class FixtureGroupV1Form:
    """Test-only bridge: retain synthetic V1 binding on the Python side."""

    def __init__(self, ledger: FixtureLedger, item_id: str, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('v1_binding'), dict):
            raise ValueError('Group V1 snapshot required')
        self._snapshot = copy.deepcopy(snapshot)
        self._actor = self._snapshot['v1_binding']['identity']['account']
        self._ledger, self._item_id = ledger, item_id
        self._coordinator = FixturePreviewCoordinator(ledger)
        self._lock = threading.RLock()
        self._current: str | None = None
        self._revision = 0

    def _view(self, view: dict[str, Any], actor: str) -> dict[str, Any]:
        if (actor != self._actor or not isinstance(view, dict)
                or set(view) != {'stage', 'destination', 'snapshot', 'controls_present'}
                or not isinstance(view['snapshot'], dict) or set(view['snapshot']) != {
                    'action', 'text', 'media_kind', 'media_id', 'destination_type', 'source', 'reuse_permission'}):
            raise ValueError('Group fixture observation mismatch')
        return {**view, 'snapshot': {**view['snapshot'], 'v1_binding': copy.deepcopy(self._snapshot['v1_binding'])}}

    def preview(self, view: dict[str, Any], *, actor: str, revision: int) -> str:
        with self._lock:
            if type(revision) is not int or not self._revision < revision <= 2**63 - 1:
                raise ValueError('stale fixture revision')
            self._revision = revision
            if self._current is not None:
                self._coordinator.invalidate(self._current)
                self._current = None
            observed = self._view(view, actor)
            self._current = self._coordinator.preview(self._item_id, self._snapshot, observed, revision=revision)
            return self._current

    def invalidate(self, preview_id: str) -> None:
        with self._lock:
            self._coordinator.invalidate(preview_id)

    def confirm(self, preview_id: str, view: dict[str, Any], *, actor: str) -> str:
        with self._lock:
            try:
                observed = self._view(view, actor)
            except ValueError:
                self._coordinator.invalidate(preview_id)
                raise
            return self._coordinator.confirm(preview_id, observed)

    def finish(self, preview_id: str, state: str, *, receipt: dict[str, str] | None = None) -> None:
        self._coordinator.finish(preview_id, state, receipt=receipt)

    def status(self, preview_id: str) -> dict[str, str]:
        return self._coordinator.status(preview_id)
