"""Local HTML → V1 Group snapshot → SQLite fixture, with synthetic data only."""
import importlib
import json
import queue
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest
pytest.importorskip("playwright.sync_api", reason="playwright không cài trong CI; chạy trên máy dev")
from playwright.sync_api import sync_playwright

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.facebook_group_v1_fixture import build_group_reel_snapshot


@pytest.mark.parametrize('change', ['none', 'actor', 'video', 'lost'])
def test_group_sqlite_browser_binding_and_restart(tmp_path, change):
    source = json.loads((Path(__file__).resolve().parents[1] /
                         'fixtures/social_v2/v1_reel_short_simulation.json').read_text(encoding='utf-8'))
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-fb-reel', 'platform': 'facebook',
                'account': 'fixture-facebook-account-demo', 'destination': 'fixture-group-demo', 'occurrence': 'fixture-slot'}
    manifest = source['entries'][0]['args']['manifest']
    manifest[0]['id'] = 'fixture-video'
    snapshot = build_group_reel_snapshot(identity=identity, source=source['source'], publication=source['publication'],
                                         manifest=manifest, adapted_text='Video nhóm giả.')
    key = {'station_id': identity['station'], 'channel_id': identity['brand'], 'campaign_id': identity['campaign'],
           'content_id': identity['content'], 'post_id': identity['post'], 'platform': identity['platform'],
           'account_id': identity['account'], 'destination_id': identity['destination'], 'occurrence_key': identity['occurrence']}
    path = tmp_path / 'group-ui.sqlite'
    con = sqlite3.connect(path)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = importlib.import_module('scripts.social.group_sqlite_fixture').GroupSQLiteForm(ledger, item, snapshot)

        def bridge(_source, request):
            if request['operation'] == 'preview':
                return {'preview_id': form.preview(request['view'], actor=request['actor'], revision=request['revision'])}
            if request['operation'] == 'confirm':
                attempt = form.confirm(request['preview_id'], request['view'], actor=request['actor'])
                if change == 'lost':
                    ledger.mark_unknown(item, attempt=attempt)
                    raise ValueError('synthetic lost response')
                ledger.finish_group_pending(item, attempt=attempt, destination=identity['destination'], remote_id='fixture-post')
                return {'status': form.status(request['preview_id'])}
            if request['operation'] == 'state':
                return {'status': form.status(request['preview_id'])}
            raise ValueError('unexpected fixture request')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            context.expose_binding('fixtureBridge', bridge)
            page = context.new_page()
            page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            page.locator('#scenario').select_option('group_video')
            page.locator('#actor').fill('fixture-facebook-account-other' if change == 'actor' else identity['account'])
            page.locator('#destination').fill(identity['destination'])
            page.locator('#content').fill(snapshot['text'])
            page.locator('#media').select_option('video-other' if change == 'video' else 'video')
            page.locator('#preview').click()
            if change in ('actor', 'video'):
                page.get_by_text('Không thể xem trước fixture.', exact=False).wait_for(timeout=5000)
                assert ledger.get(item)['state'] == 'prepared'
            else:
                page.locator('#confirm').click()
                page.get_by_text('Chưa rõ kết quả fixture' if change == 'lost' else 'awaiting_moderation',
                                 exact=False).wait_for(timeout=5000)
                if change == 'lost':
                    page.reload()
                    page.get_by_text('unknown', exact=False).wait_for(timeout=5000)
                    assert page.locator('#confirm').is_disabled()
            browser.close()
    finally:
        con.close()
    with sqlite3.connect(path) as reopened:
        row = DestinationFixtureLedger.open(reopened).get(item)
        assert row['state'] == ('prepared' if change in ('actor', 'video') else
                                'unknown' if change == 'lost' else 'awaiting_moderation')


@pytest.mark.parametrize('after_receipt', [False, True])
def test_group_browser_recovers_through_new_subprocess_after_committed_claim(tmp_path, after_receipt):
    import runpy
    key, snapshot = runpy.run_path(str(Path(__file__).parent / 'test_social_group_sqlite_fixture.py'))['data']()
    binding = snapshot['v1_binding']
    binding['manifest'][0]['id'] = 'fixture-video'
    snapshot = build_group_reel_snapshot(identity=binding['identity'], source=binding['source'],
        publication=binding['publication'], manifest=binding['manifest'], adapted_text=snapshot['text'])
    path = tmp_path / 'browser-restart.sqlite'
    con = sqlite3.connect(path)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        worker_script = '''import json, os, sqlite3, sys
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.group_sqlite_fixture import GroupSQLiteForm
r=json.loads(sys.stdin.readline())
con=sqlite3.connect(r['path'])
ledger=DestinationFixtureLedger.open(con)
form=GroupSQLiteForm(ledger,r['item'],r['snapshot'])
print(json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    if request['operation']=='preview':
        preview=form.preview(request['view'],actor=request['actor'],revision=request['revision'])
        print(json.dumps({'preview_id':preview}),flush=True)
    elif request['operation']=='confirm':
        attempt=form.confirm(request['preview_id'],request['view'],actor=request['actor'])
        if r['after_receipt']:
            ledger.finish_group_pending(r['item'],attempt=attempt,destination=r['destination'],remote_id='fixture-post')
        os._exit(41)
    else:
        raise ValueError('unexpected operation')
'''
        recovery_script = '''import json, sqlite3, sys
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.group_sqlite_fixture import GroupSQLiteRecovery
r=json.load(sys.stdin)
with sqlite3.connect(r['path']) as con:
    print(json.dumps(GroupSQLiteRecovery(DestinationFixtureLedger.open(con),r['item']).status(r['preview'])))
'''
        mode = {'recovery': False}
        worker = subprocess.Popen([sys.executable, '-u', '-c', worker_script], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        worker.stdin.write(json.dumps({'path': str(path), 'item': item, 'snapshot': snapshot,
                                       'destination': key['destination_id'], 'after_receipt': after_receipt}) + '\n')
        worker.stdin.flush()

        def worker_line():
            received = queue.Queue(maxsize=1)
            threading.Thread(target=lambda: received.put(worker.stdout.readline()), daemon=True).start()
            try:
                return received.get(timeout=10)
            except queue.Empty:
                worker.terminate()
                worker.wait(timeout=10)
                raise AssertionError('synthetic worker response timeout') from None

        assert json.loads(worker_line())['ready'] is True

        def bridge(_source, request):
            if request['operation'] == 'preview' and not mode['recovery']:
                worker.stdin.write(json.dumps(request) + '\n')
                worker.stdin.flush()
                return json.loads(worker_line())
            if request['operation'] == 'confirm' and not mode['recovery']:
                worker.stdin.write(json.dumps(request) + '\n')
                worker.stdin.flush()
                assert worker.wait(timeout=10) == 41, worker.stderr.read()
                mode['recovery'] = True
                raise ValueError('fixture worker exited before replying')
            if request['operation'] == 'state' and mode['recovery']:
                payload = {'path': str(path), 'item': item, 'preview': request['preview_id']}
                completed = subprocess.run([sys.executable, '-c', recovery_script], input=json.dumps(payload),
                    text=True, encoding='utf-8', capture_output=True, timeout=10, check=True)
                return {'status': json.loads(completed.stdout)}
            raise ValueError('unexpected fixture operation')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            context.expose_binding('fixtureBridge', bridge)
            page = context.new_page()
            page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
            page.locator('#scenario').select_option('group_video')
            page.locator('#actor').fill(key['account_id'])
            page.locator('#destination').fill(key['destination_id'])
            page.locator('#content').fill(snapshot['text'])
            page.locator('#media').select_option('video')
            page.locator('#preview').click()
            page.locator('#confirm').click()
            page.get_by_text('Chưa rõ kết quả fixture', exact=False).wait_for(timeout=5000)
            if after_receipt:
                original = page.evaluate("sessionStorage.getItem('social-ui-bridge-id')")
                page.evaluate("sessionStorage.setItem('social-ui-bridge-id', '00000000-0000-0000-0000-000000000000')")
                page.reload()
                page.get_by_text('Phiên fixture không khả dụng', exact=False).wait_for(timeout=5000)
                assert page.locator('#confirm').is_disabled()
                page.evaluate("value => sessionStorage.setItem('social-ui-bridge-id', value)", original)
            page.reload()
            expected = 'awaiting_moderation' if after_receipt else 'submitting'
            page.get_by_text(expected, exact=False).wait_for(timeout=5000)
            assert page.locator('#confirm').is_disabled()
            row = ledger.get(item)
            assert row['state'] == expected and row['attempt_id']
            browser.close()
    finally:
        if 'worker' in locals():
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=10)
            for stream in (worker.stdin, worker.stdout, worker.stderr):
                if stream is not None:
                    stream.close()
        con.close()


def test_two_group_tabs_reject_each_others_occurrence_after_recovery(tmp_path):
    import runpy
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm
    key_a, snapshot_a = runpy.run_path(str(Path(__file__).parent / 'test_social_group_sqlite_fixture.py'))['data']()
    binding = snapshot_a['v1_binding']
    binding['manifest'][0]['id'] = 'fixture-video'
    snapshot_a = build_group_reel_snapshot(identity=binding['identity'], source=binding['source'],
        publication=binding['publication'], manifest=binding['manifest'], adapted_text=snapshot_a['text'])
    identity_b = dict(binding['identity'], occurrence='fixture-slot-b')
    snapshot_b = build_group_reel_snapshot(identity=identity_b, source=binding['source'],
        publication=binding['publication'], manifest=binding['manifest'], adapted_text=snapshot_a['text'])
    key_b = dict(key_a, occurrence_key='fixture-slot-b')
    path = tmp_path / 'two-tabs.sqlite'
    con = sqlite3.connect(path)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item_a, item_b = ledger.prepare(key_a, snapshot_a), ledger.prepare(key_b, snapshot_b)
        ledger.approve_batch([(item_a, 1), (item_b, 1)])
        forms = {item_a: GroupSQLiteForm(ledger, item_a, snapshot_a),
                 item_b: GroupSQLiteForm(ledger, item_b, snapshot_b)}
        mode = {'recovery': False}
        tabs = {}
        recovery_script = '''import json, sqlite3, sys
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.group_sqlite_fixture import GroupSQLiteRecovery
r=json.load(sys.stdin)
with sqlite3.connect(r['path']) as con:
    print(json.dumps(GroupSQLiteRecovery(DestinationFixtureLedger.open(con),r['item']).status(r['preview'])))
'''

        def bridge(source, request):
            if source['page'] not in tabs or source['frame'] != source['page'].main_frame:
                raise ValueError('unregistered fixture surface')
            item = tabs[source['page']]
            if mode['recovery']:
                if request['operation'] != 'state':
                    raise ValueError('fixture recovery is read-only')
                result = subprocess.run([sys.executable, '-c', recovery_script],
                    input=json.dumps({'path': str(path), 'item': item, 'preview': request['preview_id']}),
                    text=True, encoding='utf-8', capture_output=True, timeout=10, check=True)
                return {'status': json.loads(result.stdout)}
            form = forms[item]
            if request['operation'] == 'preview':
                return {'preview_id': form.preview(request['view'], actor=request['actor'], revision=request['revision'])}
            if request['operation'] == 'confirm':
                attempt = form.confirm(request['preview_id'], request['view'], actor=request['actor'])
                if item == item_a:
                    ledger.finish_group_pending(item, attempt=attempt, destination=key_a['destination_id'], remote_id='fixture-a')
                else:
                    ledger.mark_unknown(item, attempt=attempt)
                return {'status': form.status(request['preview_id'])}
            raise ValueError('unexpected fixture operation')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            context.expose_binding('fixtureBridge', bridge)
            pages = [context.new_page(), context.new_page()]
            tabs.update({pages[0]: item_a, pages[1]: item_b})
            for page in pages:
                page.goto((Path(__file__).parent / 'fixtures' / 'social_ui_simulator.html').resolve().as_uri())
                page.locator('#scenario').select_option('group_video')
                page.locator('#actor').fill(key_a['account_id'])
                page.locator('#destination').fill(key_a['destination_id'])
                page.locator('#content').fill(snapshot_a['text'])
                page.locator('#media').select_option('video')
                page.locator('#preview').click()
                page.locator('#confirm').click()
            pages[0].get_by_text('awaiting_moderation', exact=False).wait_for(timeout=5000)
            pages[1].get_by_text('unknown', exact=False).wait_for(timeout=5000)
            tokens = [page.evaluate("sessionStorage.getItem('social-ui-bridge-id')") for page in pages]
            assert tokens[0] != tokens[1]
            before = [ledger.get(item) for item in (item_a, item_b)]
            mode['recovery'] = True
            with pytest.raises(ValueError, match='read-only'):
                bridge({'page': pages[0], 'frame': pages[0].main_frame}, {'operation': 'confirm'})
            for page, token in zip(pages, reversed(tokens)):
                page.evaluate("value => sessionStorage.setItem('social-ui-bridge-id', value)", token)
                page.reload()
                page.get_by_text('Phiên fixture không khả dụng', exact=False).wait_for(timeout=5000)
                assert page.locator('#confirm').is_disabled()
            for page, token, expected in zip(pages, tokens, ('awaiting_moderation', 'unknown')):
                page.evaluate("value => sessionStorage.setItem('social-ui-bridge-id', value)", token)
                page.reload()
                page.get_by_text(expected, exact=False).wait_for(timeout=5000)
                assert page.locator('#confirm').is_disabled()
            after = [ledger.get(item) for item in (item_a, item_b)]
            assert [(row['state'], row['attempt_id'], row['remote_id']) for row in after] == [
                (row['state'], row['attempt_id'], row['remote_id']) for row in before]
            assert [row['attempt_id'] for row in after] == tokens
            assert [row['remote_id'] for row in after] == ['fixture-a', None]
            browser.close()
    finally:
        con.close()
