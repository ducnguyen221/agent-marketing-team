"""Synthetic V1 Reel through the local browser simulator and RAM ledger."""
import importlib
import json
from pathlib import Path

import pytest
pytest.importorskip("playwright.sync_api", reason="playwright không cài trong CI; chạy trên máy dev")
from playwright.sync_api import sync_playwright

from scripts.social.facebook_group_v1_fixture import build_group_reel_snapshot
from scripts.social.fixture_ledger import FixtureLedger


@pytest.mark.parametrize('change', ['none', 'actor', 'group', 'video', 'actor_dom', 'source_revision', 'lost_response'])
def test_v1_group_browser_observes_actor_target_and_video(change):
    source = json.loads((Path(__file__).resolve().parents[1] /
                         'fixtures/social_v2/v1_reel_short_simulation.json').read_text(encoding='utf-8'))
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-fb-reel', 'platform': 'facebook',
                'account': 'fixture-facebook-account-demo', 'destination': 'fixture-group-demo',
                'occurrence': 'fixture-slot'}
    manifest = source['entries'][0]['args']['manifest']
    manifest[0]['id'] = 'fixture-video'
    snapshot = build_group_reel_snapshot(identity=identity, source=source['source'], publication=source['publication'],
        manifest=manifest, adapted_text='Video chia sẻ trong nhóm giả.')
    ledger = FixtureLedger()
    item = ledger.prepare(identity, snapshot)
    ledger.approve_batch([(item, 1)])
    form = importlib.import_module('scripts.social.fixture_ui').FixtureGroupV1Form(ledger, item, snapshot)

    def bridge(_source, request):
        if request['operation'] == 'preview':
            return {'preview_id': form.preview(request['view'], actor=request['actor'], revision=request['revision'])}
        if request['operation'] == 'confirm':
            attempt = form.confirm(request['preview_id'], request['view'], actor=request['actor'])
            if change == 'lost_response':
                form.finish(request['preview_id'], 'unknown')
                raise ValueError('synthetic lost response')
            form.finish(request['preview_id'], 'awaiting_moderation', receipt={
                'attempt': attempt, 'destination': 'fixture-group-demo', 'remote_id': 'fixture-group-post'})
            return {'status': form.status(request['preview_id'])}
        if request['operation'] == 'state':
            return {'status': form.status(request['preview_id'])}
        raise ValueError('unexpected fixture operation')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.expose_binding('fixtureBridge', bridge)
        page = context.new_page()
        page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
        page.locator('#scenario').select_option('group_video')
        page.locator('#actor').fill('fixture-facebook-account-other' if change == 'actor' else identity['account'])
        page.locator('#destination').fill('fixture-group-other' if change == 'group' else identity['destination'])
        page.locator('#content').fill(snapshot['text'])
        page.locator('#media').select_option('video-other' if change == 'video' else 'video')
        page.locator('#preview').click()
        if change in ('actor', 'group', 'video'):
            page.get_by_text('Không thể xem trước fixture.', exact=False).wait_for(timeout=5000)
            assert ledger.get(item)['state'] == 'prepared'
        else:
            page.get_by_text('Xem trước giả:', exact=False).wait_for(timeout=5000)
            if change == 'actor_dom':
                page.locator('#actor').evaluate("element => { element.value = 'fixture-facebook-account-other'; }")
            if change == 'source_revision':
                revised = build_group_reel_snapshot(identity=identity,
                    source=source['source'].replace('Kịch bản nội bộ', 'Kịch bản đã đổi'),
                    publication=source['publication'], manifest=manifest, adapted_text=snapshot['text'])
                ledger.revise(item, revised)
                ledger.approve_batch([(item, 2)])
            page.locator('#confirm').click()
            if change == 'none':
                page.get_by_text('awaiting_moderation', exact=False).wait_for(timeout=5000)
                assert ledger.get(item)['state'] == 'awaiting_moderation'
            elif change == 'lost_response':
                page.get_by_text('Chưa rõ kết quả fixture', exact=False).wait_for(timeout=5000)
                page.reload()
                page.get_by_text('unknown', exact=False).wait_for(timeout=5000)
                assert page.locator('#confirm').is_disabled()
                assert ledger.get(item)['state'] == 'unknown'
            else:
                page.get_by_text('Thông tin thay đổi' if change == 'actor_dom' else 'Chưa rõ kết quả fixture',
                                 exact=False).wait_for(timeout=5000)
                assert ledger.get(item)['state'] == 'prepared'
                assert ledger.get(item)['attempt'] is None
        browser.close()
