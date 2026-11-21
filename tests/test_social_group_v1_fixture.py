"""V1 Reel to synthetic Group UI: source and occurrence remain bound."""
import copy
import importlib
import json
from pathlib import Path

import pytest

from scripts.social.fixture_ledger import FixtureLedger
from scripts.social.fixture_ui import FixtureGroupV1Form, FixtureUI


def inputs():
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_reel_short_simulation.json').read_text(encoding='utf-8'))
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-fb-reel', 'platform': 'facebook',
                'account': 'fixture-facebook-account-demo', 'destination': 'fixture-group-demo',
                'occurrence': 'fixture-slot'}
    return {'identity': identity, 'source': data['source'], 'publication': data['publication'],
            'manifest': data['entries'][0]['args']['manifest'], 'adapted_text': 'Video chia sẻ trong nhóm giả.'}


def make_snapshot(data):
    module = importlib.import_module('scripts.social.facebook_group_v1_fixture')
    return module.build_group_reel_snapshot(**data)


def view(snapshot, stage, destination='fixture-group-demo'):
    return {'stage': stage, 'destination': destination, 'snapshot': snapshot, 'controls_present': True}


def test_v1_reel_group_binding_reaches_pending_only_after_fake_grant():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    assert ledger.get(item)['grant'] is None
    ledger.approve_batch([(item, 1)])
    session = FixtureUI(ledger, item, snapshot)
    for stage in ('ready', 'entered', 'preview'):
        session.observe(view(snapshot, stage))
    attempt = session.confirm(view(snapshot, 'preview'))
    session.finish('awaiting_moderation', receipt={'attempt': attempt, 'destination': 'fixture-group-demo',
                                                  'remote_id': 'fixture-receipt'})
    assert ledger.get(item)['state'] == 'awaiting_moderation'


@pytest.mark.parametrize('change', ['media_owner', 'group', 'account', 'source', 'asset'])
def test_v1_group_rejects_mismatched_source_or_target(change):
    data = inputs()
    if change == 'media_owner': data['manifest'][0]['post_id'] = 'fixture-yt-short'
    if change == 'group': data['identity']['destination'] = 'fixture-facebook-page-123'
    if change == 'account': data['identity']['account'] = 'fixture-real-account'
    if change == 'source': data['identity']['content'] = 'fixture-other'
    if change == 'asset': data['publication']['posts'][0]['asset_ref'] = 'wrong.mp4'
    with pytest.raises(ValueError):
        make_snapshot(data)


def test_group_v1_snapshot_cannot_be_stripped_or_claimed_by_api():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    with pytest.raises(ValueError):
        ledger.revise(item, {key: value for key, value in snapshot.items() if key != 'v1_binding'})
    ledger.approve_batch([(item, 1)])
    with pytest.raises(ValueError):
        ledger.claim(item, method='api', expected_version=1)
    assert ledger.get(item)['state'] == 'prepared'


def test_group_v1_namespace_requires_binding_before_prepare():
    data = inputs()
    snapshot = make_snapshot(data)
    del snapshot['v1_binding']
    with pytest.raises(ValueError):
        FixtureLedger().prepare(data['identity'], snapshot)


def test_group_v1_direct_ui_claim_is_refused_without_ui_session():
    data = inputs()
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], make_snapshot(data))
    ledger.approve_batch([(item, 1)])
    with pytest.raises(ValueError):
        ledger.claim(item, method='ui', expected_version=1)
    assert ledger.get(item)['state'] == 'prepared'


def test_group_v1_cannot_jump_from_submitting_to_published():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    ledger.approve_batch([(item, 1)])
    session = FixtureUI(ledger, item, snapshot)
    for stage in ('ready', 'entered', 'preview'):
        session.observe(view(snapshot, stage))
    attempt = session.confirm(view(snapshot, 'preview'))
    with pytest.raises(ValueError):
        ledger.finish(item, 'published', receipt={'attempt': attempt, 'destination': 'fixture-group-demo',
                                                 'remote_id': 'fixture-receipt'})
    assert ledger.get(item)['state'] == 'submitting'


def test_group_v1_accepts_windows_caption_and_rejects_integer_false():
    data = inputs()
    data['adapted_text'] = 'Dòng đầu\r\nDòng sau'
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    ledger.prepare(data['identity'], snapshot)
    snapshot['reuse_permission'] = 0
    with pytest.raises(ValueError):
        FixtureLedger().prepare(data['identity'], snapshot)


def test_group_v1_rejects_binding_mutated_after_prepare():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    ledger.approve_batch([(item, 1)])
    changed = copy.deepcopy(snapshot)
    changed['v1_binding']['manifest'][0]['post_id'] = 'fixture-yt-short'
    with pytest.raises(ValueError):
        FixtureUI(ledger, item, changed)


def test_group_v1_changed_source_revokes_old_grant_and_preview():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    ledger.approve_batch([(item, 1)])
    session = FixtureUI(ledger, item, snapshot)
    for stage in ('ready', 'entered', 'preview'):
        session.observe(view(snapshot, stage))
    changed = dict(data, source=data['source'].replace('Kịch bản nội bộ', 'Kịch bản giả khác'))
    ledger.revise(item, make_snapshot(changed))
    assert ledger.get(item)['version'] == 2 and ledger.get(item)['grant'] is None
    with pytest.raises(ValueError):
        session.confirm(view(snapshot, 'preview'))
    assert ledger.get(item)['state'] == 'prepared'


def test_group_v1_selects_second_reel_without_crossing_media_owner():
    data = inputs()
    data['source'] += '\n## post:reel#2\nVideo thứ hai\n'
    second = dict(data['publication']['posts'][0], post_id='fixture-fb-second', post_content='post:reel#2')
    data['publication']['posts'].append(second)
    data['identity']['post'] = 'fixture-fb-second'
    data['manifest'][0].update(post_id='fixture-fb-second', id='fixture-video-second')
    snapshot = make_snapshot(data)
    assert snapshot['media_id'] == 'fixture-video-second'
    assert snapshot['v1_binding']['publication']['posts'][0]['post_content'] == 'post:reel#2'
    data['manifest'][0]['post_id'] = 'fixture-fb-reel'
    with pytest.raises(ValueError):
        make_snapshot(data)


def test_group_v1_stale_preview_does_not_invalidate_newer_preview():
    data = inputs()
    snapshot = make_snapshot(data)
    ledger = FixtureLedger()
    item = ledger.prepare(data['identity'], snapshot)
    ledger.approve_batch([(item, 1)])
    form = FixtureGroupV1Form(ledger, item, snapshot)
    visible = {key: value for key, value in snapshot.items() if key != 'v1_binding'}
    observed = view(visible, 'preview')
    current = form.preview(observed, actor=data['identity']['account'], revision=3)
    with pytest.raises(ValueError):
        form.preview(observed, actor=data['identity']['account'], revision=2)
    assert form.status(current)['preview'] == 'preview'
    form.confirm(current, observed, actor=data['identity']['account'])
    assert ledger.get(item)['state'] == 'submitting'
