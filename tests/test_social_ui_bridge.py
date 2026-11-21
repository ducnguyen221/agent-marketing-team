"""In-process fixture bridge contracts; no browser or network."""
import pytest

from scripts.social.fixture_ledger import FixtureLedger
from scripts.social import fixture_ui


def setup_bridge():
    identity = dict(station='fixture-station', brand='fixture-brand', campaign='fixture-campaign',
                    content='fixture-content', post='fixture-post', platform='facebook',
                    account='fixture-account', destination='fixture-target', occurrence='fixture-slot')
    snapshot = dict(action='group_video', text='Video gia', media_kind='video', media_id='fixture-video',
                    destination_type='group', source=None, reuse_permission=False)
    ledger = FixtureLedger()
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    return fixture_ui.FixtureUIBridge(ledger, item, snapshot), ledger, item, snapshot


def view(snapshot, destination='fixture-target'):
    return dict(stage='preview', destination=destination, snapshot=snapshot, controls_present=True)


def test_invalidated_preview_cannot_confirm_even_with_old_view():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    bridge.invalidate()
    assert bridge.status() == {'intent': 'prepared', 'preview': 'invalidated'}
    with pytest.raises(ValueError):
        bridge.confirm(view(snapshot))
    assert ledger.get(item)['state'] == 'prepared'


def test_unknown_state_is_recovered_from_ledger_and_blocks_repeat():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    bridge.confirm(view(snapshot))
    bridge.finish('unknown')
    assert bridge.status() == {'intent': 'unknown', 'preview': 'finished'}
    with pytest.raises(ValueError):
        bridge.confirm(view(snapshot))
    with pytest.raises(ValueError):
        ledger.claim(item, method='api')


def test_group_pending_requires_receipt_for_current_attempt_and_destination():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    attempt = bridge.confirm(view(snapshot))
    with pytest.raises(ValueError):
        bridge.finish('awaiting_moderation', receipt={'attempt': attempt, 'destination': 'fixture-other',
                                                      'remote_id': 'fixture-group-post'})
    assert ledger.get(item)['state'] == 'submitting'
    bridge.finish('awaiting_moderation', receipt={'attempt': attempt, 'destination': 'fixture-target',
                                                   'remote_id': 'fixture-group-post'})
    assert ledger.get(item)['state'] == 'awaiting_moderation'


def test_changed_target_is_rejected_before_claim():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    with pytest.raises(ValueError):
        bridge.confirm(view(snapshot, 'fixture-other'))
    assert ledger.get(item)['state'] == 'prepared'


def test_changed_snapshot_is_rejected_before_claim():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    with pytest.raises(ValueError):
        bridge.confirm(view({**snapshot, 'media_id': 'fixture-other'}))
    assert ledger.get(item)['state'] == 'prepared'


def test_revised_and_reapproved_intent_cannot_use_old_preview():
    bridge, ledger, item, snapshot = setup_bridge()
    bridge.preview(view(snapshot))
    ledger.revise(item, {**snapshot, 'text': 'khac'})
    ledger.revise(item, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    with pytest.raises(ValueError):
        bridge.confirm(view(snapshot))
    assert ledger.get(item)['state'] == 'prepared'


def test_replacement_invalidates_old_preview_and_late_invalidation_is_safe():
    _, ledger, item_a, snapshot = setup_bridge()
    identity = ledger.get(item_a)['identity'].copy()
    identity['destination'] = 'fixture-other'
    item_b = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item_b, ledger.get(item_b)['version'])])
    coordinator = fixture_ui.FixturePreviewCoordinator(ledger)
    old = coordinator.preview(item_a, snapshot, view(snapshot), revision=1)
    new = coordinator.preview(item_b, snapshot, view(snapshot, 'fixture-other'), revision=2)
    with pytest.raises(ValueError):
        coordinator.preview(item_a, snapshot, view(snapshot), revision=1)
    with pytest.raises(ValueError):
        coordinator.confirm(old, view(snapshot))
    coordinator.invalidate(old)
    coordinator.confirm(new, view(snapshot, 'fixture-other'))
    assert ledger.get(item_a)['state'] == 'prepared'
    assert ledger.get(item_b)['state'] == 'submitting'


def test_cannot_replace_preview_after_claim_until_reconciled():
    _, ledger, item, snapshot = setup_bridge()
    coordinator = fixture_ui.FixturePreviewCoordinator(ledger)
    preview_id = coordinator.preview(item, snapshot, view(snapshot), revision=1)
    coordinator.confirm(preview_id, view(snapshot))
    with pytest.raises(ValueError):
        coordinator.preview(item, snapshot, view(snapshot), revision=2)
    assert coordinator.status(preview_id)['intent'] == 'submitting'


def test_confirm_and_invalidate_race_never_accepts_after_invalidation():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, ledger, item, snapshot = setup_bridge()
    coordinator = fixture_ui.FixturePreviewCoordinator(ledger)
    preview_id = coordinator.preview(item, snapshot, view(snapshot), revision=1)
    barrier = Barrier(2)

    def confirm():
        barrier.wait(timeout=5)
        try:
            return coordinator.confirm(preview_id, view(snapshot))
        except ValueError:
            return None

    def invalidate():
        barrier.wait(timeout=5)
        coordinator.invalidate(preview_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        confirmation = pool.submit(confirm)
        invalidation = pool.submit(invalidate)
        attempt = confirmation.result()
        invalidation.result()
    status = coordinator.status(preview_id)
    if attempt is None:
        assert status == {'intent': 'prepared', 'preview': 'invalidated'}
    else:
        assert status == {'intent': 'submitting', 'preview': 'submitting'}
        assert ledger.get(item)['attempt'] == attempt
    with pytest.raises(ValueError):
        coordinator.confirm(preview_id, view(snapshot))


def test_unknown_remains_locked_in_coordinator():
    _, ledger, item, snapshot = setup_bridge()
    coordinator = fixture_ui.FixturePreviewCoordinator(ledger)
    preview_id = coordinator.preview(item, snapshot, view(snapshot), revision=1)
    coordinator.confirm(preview_id, view(snapshot))
    coordinator.finish(preview_id, 'unknown')
    assert coordinator.status(preview_id) == {'intent': 'unknown', 'preview': 'finished'}
    with pytest.raises(ValueError):
        coordinator.preview(item, snapshot, view(snapshot), revision=2)


def test_invalid_replacement_consumes_revision_and_invalidates_old_preview():
    _, ledger, item, snapshot = setup_bridge()
    coordinator = fixture_ui.FixturePreviewCoordinator(ledger)
    old = coordinator.preview(item, snapshot, view(snapshot), revision=1)
    with pytest.raises(ValueError):
        coordinator.preview(item, snapshot, view(snapshot, 'fixture-other'), revision=2)
    with pytest.raises(ValueError):
        coordinator.confirm(old, view(snapshot))
    with pytest.raises(ValueError):
        coordinator.preview(item, snapshot, view(snapshot), revision=2)
    assert ledger.get(item)['state'] == 'prepared'
