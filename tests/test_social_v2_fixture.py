"""Offline V2 exercise: fixture grants are never live publication authority."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib

import pytest


def ledger_class():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'social' / 'fixture_ledger.py'
    assert path.exists(), 'V2 fixture ledger is not implemented'
    return importlib.import_module('scripts.social.fixture_ledger').FixtureLedger


def target(destination):
    return {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
            'content': 'fixture-content', 'post': 'fixture-post', 'platform': 'linkedin',
            'account': 'fixture-account', 'destination': destination, 'occurrence': 'fixture-slot'}


def test_one_approved_batch_binds_two_destinations_independently():
    ledger = ledger_class()()
    a = ledger.prepare(target('page-a'), {'text': 'Xin chào', 'scheduled_at': '2026-11-20T03:00:00Z'})
    b = ledger.prepare(target('page-b'), {'text': 'Xin chào', 'scheduled_at': '2026-11-20T03:00:00Z'})
    ledger.approve_batch([(a, ledger.get(a)['version']), (b, ledger.get(b)['version'])])
    ledger.revoke(a)
    with pytest.raises(ValueError):
        ledger.claim(a)
    ledger.claim(b)
    assert ledger.get(a)['state'] == 'revoked'
    assert ledger.get(b)['state'] == 'submitting'


def test_same_occurrence_is_idempotent_but_changed_snapshot_conflicts():
    ledger = ledger_class()()
    identity = target('page-a')
    first = ledger.prepare(identity, {'text': 'A', 'scheduled_at': '2026-11-20T03:00:00Z'})
    assert ledger.prepare(identity, {'text': 'A', 'scheduled_at': '2026-11-20T03:00:00Z'}) == first
    with pytest.raises(ValueError):
        ledger.prepare(identity, {'text': 'B', 'scheduled_at': '2026-11-20T03:00:00Z'})


def test_two_concurrent_claims_allow_only_one():
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    def claim():
        try:
            ledger.claim(item)
            return 'claimed'
        except ValueError:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == ['blocked', 'claimed']


def test_unknown_result_blocks_resubmission_even_if_method_changes():
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    ledger.claim(item, method='ui')
    ledger.finish(item, 'unknown')
    with pytest.raises(ValueError):
        ledger.claim(item, method='api')
    assert ledger.get(item)['state'] == 'unknown'


def test_batch_summary_remains_incomplete_when_another_target_is_waiting():
    ledger = ledger_class()()
    a = ledger.prepare(target('page-a'), {'text': 'A'})
    b = ledger.prepare(target('page-b'), {'text': 'A'})
    event = ledger.approve_batch([(a, ledger.get(a)['version']), (b, ledger.get(b)['version'])])
    attempt = ledger.claim(a)
    ledger.finish(a, 'published', receipt={'attempt': attempt, 'destination': 'page-a', 'remote_id': 'fixture-post-a'})
    assert ledger.batch_status(event) == {'complete': False, 'states': {'published': 1, 'prepared': 1}}


def test_revise_invalidates_only_changed_target_binding():
    ledger = ledger_class()()
    a = ledger.prepare(target('page-a'), {'text': 'A'})
    b = ledger.prepare(target('page-b'), {'text': 'A'})
    ledger.approve_batch([(a, ledger.get(a)['version']), (b, ledger.get(b)['version'])])
    ledger.revise(a, {'text': 'B'})
    with pytest.raises(ValueError):
        ledger.claim(a)
    ledger.claim(b)
    ledger.approve_batch([(a, ledger.get(a)['version'])])
    ledger.claim(a)
    assert ledger.get(a)['state'] == 'submitting'


def test_revoke_batch_preserves_members_and_blocks_each_claim():
    ledger = ledger_class()()
    a = ledger.prepare(target('page-a'), {'text': 'A'})
    b = ledger.prepare(target('page-b'), {'text': 'A'})
    event = ledger.approve_batch([(a, ledger.get(a)['version']), (b, ledger.get(b)['version'])])
    ledger.revoke_batch(event)
    for item in (a, b):
        with pytest.raises(ValueError):
            ledger.claim(item)
    assert ledger.batch_status(event) == {'complete': False, 'states': {'revoked': 2}}


@pytest.mark.parametrize('snapshot', [{}, {'text': 'A', 1: 'ambiguous'}, {'text': ('A', 'B')}])
def test_fixture_snapshot_rejects_ambiguous_non_json_shapes(snapshot):
    ledger = ledger_class()()
    with pytest.raises(ValueError):
        ledger.prepare(target('page-a'), snapshot)


def test_synthetic_publication_requires_matching_receipt():
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    attempt = ledger.claim(item)
    with pytest.raises(ValueError):
        ledger.finish(item, 'published')
    with pytest.raises(ValueError):
        ledger.finish(item, 'published', receipt={'attempt': attempt, 'destination': 'page-b', 'remote_id': 'fixture-id'})
    assert ledger.get(item)['state'] == 'submitting'


def test_late_receipt_is_recorded_without_reopening_unknown():
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    attempt = ledger.claim(item, method='ui')
    ledger.revoke(item)
    with pytest.raises(ValueError):
        ledger.observe_late(item, {'attempt': attempt, 'destination': 'page-b', 'remote_id': 'fixture-id'})
    ledger.observe_late(item, {'attempt': attempt, 'destination': 'page-a', 'remote_id': 'fixture-id'})
    assert ledger.get(item)['state'] == 'unknown'
    assert ledger.get(item)['late_receipt']['remote_id'] == 'fixture-id'
    with pytest.raises(ValueError):
        ledger.claim(item, method='api')


def test_batch_rejects_stale_preview_atomically():
    ledger = ledger_class()()
    a = ledger.prepare(target('page-a'), {'text': 'A'})
    b = ledger.prepare(target('page-b'), {'text': 'A'})
    refs = [(a, ledger.get(a)['version']), (b, ledger.get(b)['version'])]
    ledger.revise(a, {'text': 'B'})
    with pytest.raises(ValueError):
        ledger.approve_batch(refs)
    assert ledger.get(a)['grant'] is None
    assert ledger.get(b)['grant'] is None


def test_old_batch_does_not_inherit_completion_after_reverting_content():
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    old = ledger.approve_batch([(item, ledger.get(item)['version'])])
    ledger.revise(item, {'text': 'B'})
    ledger.revise(item, {'text': 'A'})
    new = ledger.approve_batch([(item, ledger.get(item)['version'])])
    attempt = ledger.claim(item)
    ledger.finish(item, 'published', receipt={'attempt': attempt, 'destination': 'page-a', 'remote_id': 'fixture-1'})
    assert ledger.batch_status(old) == {'complete': False, 'states': {'superseded': 1}}
    assert ledger.batch_status(new) == {'complete': True, 'states': {'published': 1}}


@pytest.mark.parametrize('pending', ['scheduled', 'awaiting_creator', 'awaiting_moderation'])
def test_pending_result_needs_matching_publication_observation(pending):
    ledger = ledger_class()()
    item = ledger.prepare(target('page-a'), {'text': 'A'})
    event = ledger.approve_batch([(item, ledger.get(item)['version'])])
    attempt = ledger.claim(item)
    receipt = {'attempt': attempt, 'destination': 'page-a', 'remote_id': 'fixture-id'}
    ledger.finish(item, pending, receipt=receipt)
    with pytest.raises(ValueError):
        ledger.observe_published(item, {**receipt, 'remote_id': 'fixture-other'})
    assert not ledger.batch_status(event)['complete']
    ledger.observe_published(item, receipt)
    assert ledger.batch_status(event)['complete']
