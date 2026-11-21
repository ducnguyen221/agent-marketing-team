"""Synthetic observation workflow; never operates a browser or social account."""
import importlib

import pytest

from scripts.social.fixture_ledger import FixtureLedger


def exercise(action='group_video', media='video'):
    module = importlib.import_module('scripts.social.fixture_ui')
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-post',
                'platform': 'facebook' if action.startswith('group_') else 'tiktok',
                'account': 'fixture-account', 'destination': 'fixture-target', 'occurrence': 'fixture-slot'}
    snapshot = {'action': action, 'text': 'Noi dung gia', 'media_kind': media,
                'media_id': None if media == 'none' else 'fixture-media',
                'destination_type': 'group' if action.startswith('group_') else 'profile',
                'source': 'fixture-source' if action in ('duet', 'stitch') else None,
                'reuse_permission': action in ('duet', 'stitch')}
    ledger = FixtureLedger()
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    session = module.FixtureUI(ledger, item, snapshot)
    return session, ledger, item, snapshot


def observation(stage, snapshot, *, target='fixture-target', controls=True):
    return {'stage': stage, 'destination': target, 'snapshot': snapshot, 'controls_present': controls}


@pytest.mark.parametrize(('action', 'media', 'result'), [
    ('group_text', 'none', 'awaiting_moderation'),
    ('group_image', 'image', 'awaiting_moderation'),
    ('group_video', 'video', 'awaiting_moderation'),
    ('video_inbox', 'video', 'awaiting_creator'),
    ('duet', 'video', 'awaiting_creator'),
    ('stitch', 'video', 'awaiting_creator'),
])
def test_observed_fixture_workflow_keeps_pending_state(action, media, result):
    session, ledger, item, snapshot = exercise(action, media)
    session.observe(observation('ready', snapshot))
    session.observe(observation('entered', snapshot))
    session.observe(observation('preview', snapshot))
    attempt = session.confirm(observation('preview', snapshot))
    session.finish(result, receipt={'attempt': attempt, 'destination': 'fixture-target', 'remote_id': 'fixture-receipt'})
    assert ledger.get(item)['state'] == result
    with pytest.raises(ValueError):
        session.confirm(observation('preview', snapshot))


def test_wrong_destination_or_missing_controls_stops_before_claim():
    for kwargs in ({'target': 'fixture-other'}, {'controls': False}):
        session, ledger, item, snapshot = exercise()
        with pytest.raises(ValueError):
            session.observe(observation('ready', snapshot, **kwargs))
        assert ledger.get(item)['state'] == 'prepared'


def test_changed_snapshot_cannot_be_confirmed_after_preview():
    session, ledger, item, snapshot = exercise()
    for stage in ('ready', 'entered', 'preview'):
        session.observe(observation(stage, snapshot))
    with pytest.raises(ValueError):
        session.confirm(observation('preview', {**snapshot, 'text': 'changed'}))
    assert ledger.get(item)['state'] == 'prepared'


def test_unknown_blocks_api_retry_for_same_occurrence():
    session, ledger, item, snapshot = exercise()
    for stage in ('ready', 'entered', 'preview'):
        session.observe(observation(stage, snapshot))
    session.confirm(observation('preview', snapshot))
    session.finish('unknown')
    with pytest.raises(ValueError):
        ledger.claim(item, method='api')
    assert ledger.get(item)['state'] == 'unknown'


def test_duet_requires_source_permission_and_video():
    module = importlib.import_module('scripts.social.fixture_ui')
    session, ledger, item, snapshot = exercise('duet', 'video')
    for changed in ({**snapshot, 'source': None}, {**snapshot, 'source': 'fixture-source\nother'},
                    {**snapshot, 'reuse_permission': False},
                    {**snapshot, 'media_kind': 'image'}):
        with pytest.raises(ValueError):
            module.FixtureUI(ledger, item, changed)


def test_revision_and_reapproval_do_not_authorize_old_preview():
    session, ledger, item, snapshot = exercise()
    for stage in ('ready', 'entered', 'preview'):
        session.observe(observation(stage, snapshot))
    ledger.revise(item, {**snapshot, 'text': 'B'})
    ledger.revise(item, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    with pytest.raises(ValueError):
        session.confirm(observation('preview', snapshot))
    assert ledger.get(item)['state'] == 'prepared'


def test_malformed_observation_stops_session_even_if_next_observation_is_valid():
    session, ledger, item, snapshot = exercise()
    with pytest.raises(ValueError):
        session.observe(observation('ready', {}))
    with pytest.raises(ValueError):
        session.observe(observation('ready', snapshot))
    assert ledger.get(item)['state'] == 'prepared'


def test_pending_outcome_cannot_claim_publication():
    session, ledger, item, snapshot = exercise()
    for stage in ('ready', 'entered', 'preview'):
        session.observe(observation(stage, snapshot))
    attempt = session.confirm(observation('preview', snapshot))
    with pytest.raises(ValueError):
        session.finish('published', receipt={'attempt': attempt, 'destination': 'fixture-target', 'remote_id': 'fixture-id'})
    assert ledger.get(item)['state'] == 'submitting'


def test_observation_with_different_media_id_stops():
    session, ledger, item, snapshot = exercise()
    with pytest.raises(ValueError):
        session.observe(observation('ready', {**snapshot, 'media_id': 'fixture-other-video'}))
    assert ledger.get(item)['state'] == 'prepared'


def test_two_concurrent_confirms_do_not_orphan_winner():
    from concurrent.futures import ThreadPoolExecutor
    session, ledger, item, snapshot = exercise()
    for stage in ('ready', 'entered', 'preview'):
        session.observe(observation(stage, snapshot))
    def confirm():
        try:
            return session.confirm(observation('preview', snapshot))
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: confirm(), range(2)))
    winner = next(value for value in attempts if value is not None)
    assert sum(value is not None for value in attempts) == 1
    session.finish('awaiting_moderation', receipt={'attempt': winner, 'destination': 'fixture-target', 'remote_id': 'fixture-id'})
    assert ledger.get(item)['state'] == 'awaiting_moderation'


def test_two_ui_sessions_share_one_claim_and_unknown_blocks_api():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    module = importlib.import_module('scripts.social.fixture_ui')
    first, ledger, item, snapshot = exercise('duet', 'video')
    second = module.FixtureUI(ledger, item, snapshot)
    for session in (first, second):
        for stage in ('ready', 'entered', 'preview'):
            session.observe(observation(stage, snapshot))

    barrier = Barrier(2)

    def confirm(session):
        barrier.wait(timeout=5)
        try:
            return session, session.confirm(observation('preview', snapshot)), None
        except ValueError as exc:
            return session, None, str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, (first, second)))
    winners = [(session, attempt) for session, attempt, _ in results if attempt is not None]
    assert len(winners) == 1
    assert [error for _, _, error in results if error is not None] == ['fixture claim refused']
    assert ledger.get(item)['attempt'] == winners[0][1]
    winners[0][0].finish('unknown')
    assert ledger.get(item)['state'] == 'unknown'
    with pytest.raises(ValueError):
        ledger.claim(item, method='api')
    with pytest.raises(ValueError):
        module.FixtureUI(ledger, item, snapshot)


def test_duet_source_identifier_cannot_contain_control_characters():
    module = importlib.import_module('scripts.social.fixture_ui')
    _, _, _, snapshot = exercise('duet', 'video')
    snapshot['source'] = 'fixture-source\nother'
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-post', 'platform': 'tiktok',
                'account': 'fixture-account', 'destination': 'fixture-target', 'occurrence': 'fixture-slot'}
    ledger = FixtureLedger()
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, ledger.get(item)['version'])])
    with pytest.raises(ValueError):
        module.FixtureUI(ledger, item, snapshot)
