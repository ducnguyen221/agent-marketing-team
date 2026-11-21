"""Group V1 recovery with caller-owned SQLite fixtures, never a real station."""
import json
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.facebook_group_v1_fixture import build_group_reel_snapshot


def data():
    source = json.loads((Path(__file__).resolve().parents[1] /
                         'fixtures/social_v2/v1_reel_short_simulation.json').read_text(encoding='utf-8'))
    identity = {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
                'content': 'fixture-content', 'post': 'fixture-fb-reel', 'platform': 'facebook',
                'account': 'fixture-facebook-account-demo', 'destination': 'fixture-group-demo',
                'occurrence': 'fixture-slot'}
    snapshot = build_group_reel_snapshot(identity=identity, source=source['source'], publication=source['publication'],
        manifest=source['entries'][0]['args']['manifest'], adapted_text='Video chia sẻ trong nhóm giả.')
    key = {'station_id': identity['station'], 'channel_id': identity['brand'], 'campaign_id': identity['campaign'],
           'content_id': identity['content'], 'post_id': identity['post'], 'platform': identity['platform'],
           'account_id': identity['account'], 'destination_id': identity['destination'], 'occurrence_key': identity['occurrence']}
    return key, snapshot


def test_group_sqlite_requires_binding_and_special_claim():
    key, snapshot = data()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        assert ledger.get(item)['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z') == {'due': [], 'invalid': []}
        with pytest.raises(ValueError):
            ledger.claim(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
        tampered = dict(key, station_id='fixture-other')
        with pytest.raises(ValueError):
            ledger.prepare(tampered, snapshot)
        with pytest.raises(ValueError):
            ledger.prepare(dict(key, platform='discord'), snapshot)


def test_invalid_group_observation_stops_session():
    from scripts.social.group_sqlite_fixture import GroupSQLiteSession
    key, snapshot = data()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        session = GroupSQLiteSession(ledger, item, snapshot)
        with pytest.raises(ValueError):
            session.observe({'stage': 'ready', 'destination': key['destination_id'], 'snapshot': None, 'controls_present': True})
        with pytest.raises(ValueError):
            session.observe({'stage': 'ready', 'destination': key['destination_id'], 'snapshot': snapshot, 'controls_present': True})


def test_non_group_case_variant_is_not_hidden_from_due_scan():
    key, _ = data()
    key.update(destination_id='fixture-Group-demo', account_id='fixture-account')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, {'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [item]
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish(item, attempt=attempt, destination=key['destination_id'], remote_id='fixture-receipt')
        assert ledger.get(item)['state'] == 'accepted'


def test_group_sqlite_claim_survives_process_exit_and_unknown_blocks_retry(tmp_path):
    key, snapshot = data()
    path = tmp_path / 'group-fixture.sqlite'
    request = json.dumps({'path': str(path), 'key': key, 'snapshot': snapshot}, ensure_ascii=False)
    script = '''import json, sqlite3, sys
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.group_sqlite_fixture import GroupSQLiteSession
r=json.load(sys.stdin)
with sqlite3.connect(r['path']) as con:
    ledger=DestinationFixtureLedger.initialize(con)
    item=ledger.prepare(r['key'], r['snapshot'])
    ledger.approve(item, expected_version=1)
    session=GroupSQLiteSession(ledger, item, r['snapshot'])
    for stage in ('ready','entered','preview'):
        session.observe({'stage':stage,'destination':r['key']['destination_id'],'snapshot':r['snapshot'],'controls_present':True})
    attempt=session.confirm({'stage':'preview','destination':r['key']['destination_id'],'snapshot':r['snapshot'],'controls_present':True})
    print(json.dumps({'item':item,'attempt':attempt}))
'''
    result = subprocess.run([sys.executable, '-c', script], input=request, text=True, encoding='utf-8',
                            capture_output=True, check=True)
    saved = json.loads(result.stdout)
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.open(con)
        row = ledger.get(saved['item'])
        assert row['state'] == 'submitting' and row['attempt_id'] == saved['attempt']
        ledger.mark_unknown(saved['item'], attempt=saved['attempt'])
        with pytest.raises(ValueError):
            ledger.claim_group_fixture(saved['item'], expected_version=1, snapshot=snapshot)
        with pytest.raises(ValueError):
            ledger.claim(saved['item'], expected_version=1)
        assert ledger.get(saved['item'])['state'] == 'unknown'


def test_group_sqlite_pending_receipt_survives_reopen_and_is_bound(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteSession
    key, snapshot = data()
    path = tmp_path / 'group-pending.sqlite'
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        session = GroupSQLiteSession(ledger, item, snapshot)
        for stage in ('ready', 'entered', 'preview'):
            session.observe({'stage': stage, 'destination': key['destination_id'], 'snapshot': snapshot, 'controls_present': True})
        attempt = session.confirm({'stage': 'preview', 'destination': key['destination_id'], 'snapshot': snapshot, 'controls_present': True})
        with pytest.raises(ValueError):
            ledger.finish_group_pending(item, attempt=attempt, destination='fixture-group-other', remote_id='fixture-receipt')
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination=key['destination_id'], remote_id='fixture-receipt')
        ledger.finish_group_pending(item, attempt=attempt, destination=key['destination_id'], remote_id='fixture-receipt')
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'awaiting_moderation'
        assert ledger.get(item)['attempt_id'] == attempt
        with pytest.raises(ValueError):
            ledger.mark_unknown(item, attempt=attempt)
        with pytest.raises(ValueError):
            ledger.claim_group_fixture(item, expected_version=1, snapshot=snapshot)


def test_group_sqlite_pending_and_unknown_race_has_one_winner(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteSession
    key, snapshot = data()
    path = tmp_path / 'group-race.sqlite'
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        session = GroupSQLiteSession(ledger, item, snapshot)
        for stage in ('ready', 'entered', 'preview'):
            session.observe({'stage': stage, 'destination': key['destination_id'], 'snapshot': snapshot, 'controls_present': True})
        attempt = session.confirm({'stage': 'preview', 'destination': key['destination_id'], 'snapshot': snapshot, 'controls_present': True})
    barrier, outcomes = threading.Barrier(2), []

    def worker(action):
        with sqlite3.connect(path, timeout=5) as con:
            ledger = DestinationFixtureLedger.open(con)
            barrier.wait(timeout=5)
            try:
                if action == 'unknown':
                    ledger.mark_unknown(item, attempt=attempt)
                else:
                    ledger.finish_group_pending(item, attempt=attempt, destination=key['destination_id'], remote_id='fixture-receipt')
                outcomes.append((action, 'ok'))
            except ValueError:
                outcomes.append((action, 'refused'))

    threads = [threading.Thread(target=worker, args=(action,)) for action in ('unknown', 'pending')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(result for _, result in outcomes) == ['ok', 'refused']
    winner = next(action for action, result in outcomes if result == 'ok')
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.open(con)
        row = ledger.get(item)
        assert row['state'] == ('unknown' if winner == 'unknown' else 'awaiting_moderation')
        assert row['remote_id'] == (None if winner == 'unknown' else 'fixture-receipt')


def test_group_conflicting_receipt_is_recorded_as_unknown():
    from scripts.social.group_sqlite_fixture import GroupSQLiteSession
    key, snapshot = data()
    other_key = dict(key, destination_id='fixture-group-other')
    binding = snapshot['v1_binding']
    other_identity = dict(binding['identity'], destination='fixture-group-other')
    other_snapshot = build_group_reel_snapshot(identity=other_identity, source=binding['source'],
        publication=binding['publication'], manifest=binding['manifest'], adapted_text=snapshot['text'])
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        attempts = []
        for current_key, current_snapshot in ((key, snapshot), (other_key, other_snapshot)):
            item = ledger.prepare(current_key, current_snapshot)
            ledger.approve(item, expected_version=1)
            session = GroupSQLiteSession(ledger, item, current_snapshot)
            for stage in ('ready', 'entered', 'preview'):
                session.observe({'stage': stage, 'destination': current_key['destination_id'],
                                 'snapshot': current_snapshot, 'controls_present': True})
            attempt = session.confirm({'stage': 'preview', 'destination': current_key['destination_id'],
                                       'snapshot': current_snapshot, 'controls_present': True})
            attempts.append((item, attempt, current_key['destination_id']))
        first, second = attempts
        ledger.finish_group_pending(first[0], attempt=first[1], destination=first[2], remote_id='fixture-receipt')
        with pytest.raises(ValueError):
            ledger.finish_group_pending(second[0], attempt=second[1], destination=second[2], remote_id='fixture-receipt')
        assert ledger.get(second[0])['state'] == 'unknown'
        assert ledger.get(second[0])['conflict_remote_id'] == 'fixture-receipt'


def test_group_sqlite_form_rejects_old_preview_after_new_form_or_changed_actor(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm
    key, snapshot = data()
    path = tmp_path / 'group-form.sqlite'
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = GroupSQLiteForm(ledger, item, snapshot)
        preview_id = form.preview(view, actor=key['account_id'], revision=1)
        with pytest.raises(ValueError):
            form.confirm(preview_id, view, actor='fixture-facebook-account-other')
        with pytest.raises(ValueError):
            form.confirm(preview_id, view, actor=key['account_id'])
        preview_id = form.preview(view, actor=key['account_id'], revision=2)
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.open(con)
        new_form = GroupSQLiteForm(ledger, item, snapshot)
        with pytest.raises(ValueError):
            new_form.status(preview_id)
        with pytest.raises(ValueError):
            new_form.confirm(preview_id, view, actor=key['account_id'])
        assert ledger.get(item)['state'] == 'prepared'


def test_two_sqlite_forms_can_preview_but_only_one_can_claim(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm
    key, snapshot = data()
    path = tmp_path / 'group-two-forms.sqlite'
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(path) as con_a, sqlite3.connect(path) as con_b:
        ledger_a = DestinationFixtureLedger.initialize(con_a)
        ledger_b = DestinationFixtureLedger.open(con_b)
        item = ledger_a.prepare(key, snapshot)
        ledger_a.approve(item, expected_version=1)
        form_a, form_b = GroupSQLiteForm(ledger_a, item, snapshot), GroupSQLiteForm(ledger_b, item, snapshot)
        preview_a = form_a.preview(view, actor=key['account_id'], revision=1)
        preview_b = form_b.preview(view, actor=key['account_id'], revision=1)
        attempt = form_a.confirm(preview_a, view, actor=key['account_id'])
        assert form_a.status(preview_a)['intent'] == 'submitting'
        with pytest.raises(ValueError):
            form_b.status(preview_b)
        with pytest.raises(ValueError):
            form_b.confirm(preview_b, view, actor=key['account_id'])
        assert ledger_b.get(item)['attempt_id'] == attempt


def test_group_sqlite_form_keeps_status_after_claim_and_repeated_actions():
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm
    key, snapshot = data()
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = GroupSQLiteForm(ledger, item, snapshot)
        preview = form.preview(view, actor=key['account_id'], revision=1)
        attempt = form.confirm(preview, view, actor=key['account_id'])
        ledger.mark_unknown(item, attempt=attempt)
        with pytest.raises(ValueError):
            form.confirm(preview, view, actor=key['account_id'])
        form.invalidate(preview)
        with pytest.raises(ValueError):
            form.preview(view, actor=key['account_id'], revision=2)
        assert form.status(preview)['intent'] == 'unknown'
        assert ledger.get(item)['attempt_id'] == attempt


def test_group_recovery_matches_preview_to_committed_attempt_after_reopen(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm, GroupSQLiteRecovery
    key, snapshot = data()
    path = tmp_path / 'group-recovery.sqlite'
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = GroupSQLiteForm(ledger, item, snapshot)
        preview = form.preview(view, actor=key['account_id'], revision=1)
        attempt = form.confirm(preview, view, actor=key['account_id'])
        assert attempt == preview
    with sqlite3.connect(path) as con:
        ledger = DestinationFixtureLedger.open(con)
        recovery = GroupSQLiteRecovery(ledger, item)
        assert recovery.status(preview)['intent'] == 'submitting'
        with pytest.raises(ValueError):
            recovery.status('00000000-0000-0000-0000-000000000000')
        ledger.mark_unknown(item, attempt=attempt)
        assert recovery.status(preview)['intent'] == 'unknown'


def test_group_form_rejects_changed_preview_id_before_confirm():
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm
    key, snapshot = data()
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = GroupSQLiteForm(ledger, item, snapshot)
        form.preview(view, actor=key['account_id'], revision=1)
        with pytest.raises(ValueError):
            form.confirm('00000000-0000-0000-0000-000000000000', view, actor=key['account_id'])
        assert ledger.get(item)['state'] == 'prepared' and ledger.get(item)['attempt_id'] is None


def test_group_recovery_does_not_accept_other_occurrence_preview():
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm, GroupSQLiteRecovery
    key, snapshot = data()
    other_key = dict(key, occurrence_key='fixture-other-slot')
    binding = snapshot['v1_binding']
    other_identity = dict(binding['identity'], occurrence='fixture-other-slot')
    other_snapshot = build_group_reel_snapshot(identity=other_identity, source=binding['source'],
        publication=binding['publication'], manifest=binding['manifest'], adapted_text=snapshot['text'])
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        items = [ledger.prepare(key, snapshot), ledger.prepare(other_key, other_snapshot)]
        ledger.approve_batch([(items[0], 1), (items[1], 1)])
        previews = []
        for item, bound in zip(items, (snapshot, other_snapshot)):
            visible = {field: value for field, value in bound.items() if field != 'v1_binding'}
            view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
            form = GroupSQLiteForm(ledger, item, bound)
            preview = form.preview(view, actor=key['account_id'], revision=1)
            form.confirm(preview, view, actor=key['account_id'])
            previews.append(preview)
        with pytest.raises(ValueError):
            GroupSQLiteRecovery(ledger, items[0]).status(previews[1])
        assert GroupSQLiteRecovery(ledger, items[0]).status(previews[0])['intent'] == 'submitting'


def test_group_recovery_reads_while_another_connection_holds_write_reservation(tmp_path):
    from scripts.social.group_sqlite_fixture import GroupSQLiteForm, GroupSQLiteRecovery
    key, snapshot = data()
    path = tmp_path / 'group-reader.sqlite'
    visible = {field: value for field, value in snapshot.items() if field != 'v1_binding'}
    view = {'stage': 'preview', 'destination': key['destination_id'], 'snapshot': visible, 'controls_present': True}
    with sqlite3.connect(path) as con, sqlite3.connect(path) as writer:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key, snapshot)
        ledger.approve(item, expected_version=1)
        form = GroupSQLiteForm(ledger, item, snapshot)
        preview = form.preview(view, actor=key['account_id'], revision=1)
        form.confirm(preview, view, actor=key['account_id'])
        writer.execute('BEGIN IMMEDIATE')
        try:
            assert GroupSQLiteRecovery(ledger, item).status(preview)['intent'] == 'submitting'
        finally:
            writer.rollback()
