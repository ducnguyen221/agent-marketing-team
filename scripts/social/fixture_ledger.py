"""In-memory V2 exercise only; never an approval or a real delivery ledger.

No file, network, provider, station or V1 integration is available here. Values
are synthetic. This prototype cannot grant permission for external side effects.
"""
from __future__ import annotations

import hashlib
import copy
import json
import threading
import unicodedata
import uuid
from typing import Any

_FIELDS = ('station', 'brand', 'campaign', 'content', 'post', 'platform',
           'account', 'destination', 'occurrence')
_METHODS = ('ui', 'api', 'manual')
_RESULTS = ('accepted', 'scheduled', 'published', 'awaiting_creator', 'awaiting_moderation', 'unknown')
_GROUP_UI_SEAL = object()


def _snapshot_digest(snapshot: Any) -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError('invalid fixture snapshot')
    pending = [snapshot]
    count = 0
    while pending:
        value = pending.pop()
        count += 1
        if count > 10000:
            raise ValueError('fixture snapshot too complex')
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError('invalid fixture snapshot')
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif value is not None and type(value) not in (str, int, float, bool):
            raise ValueError('invalid fixture snapshot')
    try:
        raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError('invalid fixture snapshot') from None
    if len(raw) > 65536:
        raise ValueError('fixture snapshot too large')
    return hashlib.sha256(raw).hexdigest()


def _validate_fixture_candidate(identity: dict[str, str], snapshot: dict[str, Any]) -> None:
    """Fixture convention only: the integration label equals the destination label."""
    if identity.get('destination', '').startswith('fixture-group-') and 'v1_binding' not in snapshot:
        raise ValueError('Group V1 fixture binding required')
    if 'v1_binding' in snapshot:
        from scripts.social.facebook_group_v1_fixture import validate_group_reel_snapshot
        validate_group_reel_snapshot(identity, snapshot)
    if 'candidate' not in snapshot:
        return
    candidate = snapshot['candidate']
    if not isinstance(candidate, dict) or not isinstance(candidate.get('posts'), list):
        raise ValueError('invalid fixture candidate')
    posts = candidate['posts']
    if len(posts) != 1 or not isinstance(posts[0], dict):
        raise ValueError('invalid fixture candidate')
    post = posts[0]
    if (not isinstance(post.get('integration'), dict) or not isinstance(post.get('settings'), dict)
            or post['integration'].get('id') != identity['destination']
            or post['settings'].get('__type') != identity['platform']):
        raise ValueError('fixture candidate target mismatch')


class FixtureLedger:
    """Isolated synthetic identity, binding and lifecycle for one process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_key: dict[tuple[str, ...], str] = {}
        self._items: dict[str, dict[str, Any]] = {}
        self._batches: dict[str, tuple[tuple[str, int], ...]] = {}
        self._linkedin_ids: dict[str, str] = {}

    def prepare(self, identity: dict[str, str], snapshot: dict[str, Any]) -> str:
        if (not isinstance(identity, dict) or set(identity) != set(_FIELDS)
                or any(not isinstance(identity[field], str) or not identity[field]
                       or identity[field] != identity[field].strip() or len(identity[field]) > 256
                       or any(unicodedata.category(c).startswith('C') for c in identity[field])
                       for field in _FIELDS) or not isinstance(snapshot, dict)):
            raise ValueError('invalid fixture input')
        snapshot = copy.deepcopy(snapshot)
        key = tuple(identity[field] for field in _FIELDS)
        digest = _snapshot_digest(snapshot)
        _validate_fixture_candidate(identity, snapshot)
        with self._lock:
            if key in self._by_key:
                item_id = self._by_key[key]
                if self._items[item_id]['digest'] != digest:
                    raise ValueError('fixture intent conflict')
                return item_id
            item_id = str(uuid.uuid4())
            self._by_key[key] = item_id
            self._items[item_id] = {'identity': dict(identity), 'digest': digest, 'version': 1,
                                    'v1_group_bound': 'v1_binding' in snapshot,
                                    'state': 'prepared', 'grant': None, 'method': None,
                                    'attempt': None, 'receipt': None, 'late_receipt': None,
                                    'fixture_author': snapshot.get('author') if isinstance(snapshot.get('author'), str) else None,
                                    'linkedin_receipt': None, 'linkedin_conflict': None}
            return item_id

    def approve_batch(self, references: list[tuple[str, int]]) -> str:
        """Issue a synthetic binding for each item; never a human decision."""
        with self._lock:
            if not isinstance(references, list):
                raise ValueError('invalid fixture batch')
            references = tuple(references)
            if (not references or len(references) > 100
                    or any(not isinstance(ref, tuple) or len(ref) != 2
                           or not isinstance(ref[0], str) or type(ref[1]) is not int for ref in references)):
                raise ValueError('invalid fixture batch')
            item_ids = [ref[0] for ref in references]
            if (len(set(item_ids)) != len(item_ids)
                    or any(item not in self._items or self._items[item]['state'] != 'prepared'
                           or self._items[item]['grant'] is not None
                           or self._items[item]['version'] != version for item, version in references)):
                raise ValueError('invalid fixture batch')
            event = str(uuid.uuid4())
            self._batches[event] = references
            for item_id in item_ids:
                self._items[item_id]['grant'] = event
            return event

    def revise(self, item_id: str, snapshot: dict[str, Any]) -> None:
        snapshot = copy.deepcopy(snapshot)
        digest = _snapshot_digest(snapshot)
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item['state'] != 'prepared':
                raise ValueError('fixture revision refused')
            if item['v1_group_bound'] != ('v1_binding' in snapshot):
                raise ValueError('fixture binding kind mismatch')
            _validate_fixture_candidate(item['identity'], snapshot)
            if item['digest'] != digest:
                item['digest'] = digest
                item['fixture_author'] = snapshot.get('author') if isinstance(snapshot.get('author'), str) else None
                item['version'] += 1
                item['grant'] = None

    def batch_status(self, event: str) -> dict[str, Any]:
        with self._lock:
            members = self._batches.get(event)
            if members is None:
                raise ValueError('fixture batch missing')
            states: dict[str, int] = {}
            for item_id, version in members:
                item = self._items[item_id]
                state = item['state'] if item['version'] == version else 'superseded'
                states[state] = states.get(state, 0) + 1
            return {'complete': len(states) == 1 and states.get('published') == len(members), 'states': states}

    def revoke_batch(self, event: str) -> None:
        with self._lock:
            members = self._batches.get(event)
            if members is None:
                raise ValueError('fixture batch missing')
            for item_id, _ in members:
                item = self._items[item_id]
                if item['grant'] == event and item['state'] in ('prepared', 'submitting'):
                    item['grant'] = None
                    item['state'] = 'unknown' if item['state'] == 'submitting' else 'revoked'

    def claim(self, item_id: str, *, method: str = 'api', expected_version: int | None = None,
              _ui_seal: object | None = None) -> str:
        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] != 'prepared' or item['grant'] is None
                    or method not in _METHODS
                    or (item['v1_group_bound'] and (method != 'ui' or _ui_seal is not _GROUP_UI_SEAL))
                    or (expected_version is not None and
                        (type(expected_version) is not int or item['version'] != expected_version))):
                raise ValueError('fixture claim refused')
            item['state'] = 'submitting'
            item['method'] = method
            item['attempt'] = str(uuid.uuid4())
            return item['attempt']

    @staticmethod
    def _receipt_matches(item: dict[str, Any], receipt: Any) -> bool:
        return (isinstance(receipt, dict) and set(receipt) == {'attempt', 'destination', 'remote_id'}
                and receipt['attempt'] == item['attempt']
                and receipt['destination'] == item['identity']['destination']
                and isinstance(receipt['remote_id'], str) and receipt['remote_id'].startswith('fixture-')
                and len(receipt['remote_id']) <= 256)

    def finish(self, item_id: str, state: str, *, receipt: dict[str, str] | None = None) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] != 'submitting' or state not in _RESULTS
                    or (item['v1_group_bound'] and state not in ('awaiting_moderation', 'unknown'))
                    or (state == 'accepted' and item['identity']['platform'] == 'linkedin')
                    or (state != 'unknown' and not self._receipt_matches(item, receipt))
                    or (state == 'unknown' and receipt is not None)):
                raise ValueError('fixture finish refused')
            item['state'] = state
            item['receipt'] = dict(receipt) if receipt is not None else None

    def finish_linkedin_fixture(self, item_id: str, *, attempt: str, destination: str,
                                author: str, status: int | None, headers: list[tuple[str, str]]) -> None:
        """Bind a synthetic response to its claim; no authentication or transport."""
        from scripts.social.channels.linkedin.direct import interpret_create, preview_post

        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] != 'submitting' or item['method'] != 'api'
                    or item['identity']['platform'] != 'linkedin' or item['attempt'] != attempt
                    or item['identity']['destination'] != destination or item['fixture_author'] != author):
                raise ValueError('fixture response binding refused')
            # Reuse native author validation; all other arguments are synthetic constants.
            preview_post(author=author, text='fixture', api_version='202601')
            parsed = interpret_create(status, headers)
            if parsed['state'] != 'accepted':
                self.finish(item_id, 'unknown')
                return
            previous = self._linkedin_ids.get(parsed['post_urn'])
            if previous is not None and previous != attempt:
                item['linkedin_conflict'] = dict(parsed)
                self.finish(item_id, 'unknown')
                return
            receipt = {'attempt': attempt, 'destination': destination, 'remote_id': 'fixture-' + parsed['post_urn']}
            self._linkedin_ids[parsed['post_urn']] = attempt
            item['state'] = 'accepted'
            item['receipt'] = receipt
            item['linkedin_receipt'] = parsed

    def observe_linkedin_fixture(self, item_id: str, *, attempt: str, destination: str,
                                 status: int | None, body: Any) -> None:
        """Inspect a synthetic readback without asserting an authenticated publish."""
        from scripts.social.channels.linkedin.direct import observe_post

        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] != 'accepted' or item['linkedin_receipt'] is None
                    or item['attempt'] != attempt or item['identity']['destination'] != destination):
                raise ValueError('fixture readback binding refused')
            item['linkedin_receipt'] = observe_post(item['linkedin_receipt'], status, body,
                                                     expected_author=item['fixture_author'])

    def observe_late(self, item_id: str, receipt: dict[str, str]) -> None:
        """Retain synthetic evidence after uncertainty without reopening send."""
        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] != 'unknown' or not self._receipt_matches(item, receipt)
                    or (item['late_receipt'] is not None and item['late_receipt'] != receipt)):
                raise ValueError('fixture observation refused')
            item['late_receipt'] = dict(receipt)

    def observe_published(self, item_id: str, receipt: dict[str, str]) -> None:
        """Apply a matching synthetic observation to a known pending fixture."""
        with self._lock:
            item = self._items.get(item_id)
            if (item is None or item['state'] not in ('scheduled', 'awaiting_creator', 'awaiting_moderation')
                    or not self._receipt_matches(item, receipt) or item['receipt'] != receipt):
                raise ValueError('fixture observation refused')
            item['state'] = 'published'

    def revoke(self, item_id: str) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item['grant'] is None or item['state'] not in ('prepared', 'submitting'):
                raise ValueError('fixture revoke refused')
            item['grant'] = None
            item['state'] = 'unknown' if item['state'] == 'submitting' else 'revoked'

    def get(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            if item_id not in self._items:
                raise ValueError('fixture item missing')
            item = self._items[item_id]
            return {**item, 'identity': dict(item['identity']),
                    'receipt': dict(item['receipt']) if item['receipt'] is not None else None,
                    'late_receipt': dict(item['late_receipt']) if item['late_receipt'] is not None else None,
                    'linkedin_receipt': dict(item['linkedin_receipt']) if item['linkedin_receipt'] is not None else None,
                    'linkedin_conflict': dict(item['linkedin_conflict']) if item['linkedin_conflict'] is not None else None}
