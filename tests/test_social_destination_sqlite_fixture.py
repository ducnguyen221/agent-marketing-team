"""Persistent multi-destination V2 exercise on disposable SQLite files only."""
import sqlite3
import multiprocessing
from pathlib import Path

import pytest


def key(destination):
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'discord',
            'account_id': 'fixture-account', 'destination_id': 'fixture-' + destination, 'occurrence_key': 'fixture-slot'}


def test_other_platform_cannot_be_misclassified_as_reel(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key('discord'), {'fixture_schema': 'facebook-native-intent/1', 'media_type': 'REEL',
                                               'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert con.execute('SELECT count(*) FROM reel_fixture_progress').fetchone()[0] == 0
        ledger.finish(item, attempt=attempt, destination='fixture-discord', remote_id='fixture-receipt')
        assert ledger.get(item)['state'] == 'accepted'
    finally:
        con.close()


def claim_process(db, item, start, results):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(db, timeout=10)
    try:
        ledger = DestinationFixtureLedger.open(con)
        results.put('ready')
        if not start.wait(10):
            results.put('timeout')
            return
        try:
            ledger.claim(item, expected_version=1)
            results.put('claimed')
        except ValueError:
            results.put('refused')
    finally:
        con.close()


def test_two_destinations_survive_reopen_and_remain_distinct(tmp_path):
    module = Path(__file__).resolve().parents[1] / 'scripts/social/destination_ledger_fixture.py'
    assert module.exists(), 'destination-aware SQLite fixture is missing'
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    a = ledger.prepare(key('channel-a'), {'text': 'synthetic'})
    b = ledger.prepare(key('channel-b'), {'text': 'synthetic'})
    assert a != b
    assert ledger.prepare(key('channel-a'), {'text': 'synthetic'}) == a
    con.close()
    con = sqlite3.connect(db)
    try:
        reopened = DestinationFixtureLedger.open(con)
        assert reopened.get(a)['destination_id'] == 'fixture-channel-a'
        assert reopened.get(b)['destination_id'] == 'fixture-channel-b'
    finally:
        con.close()


def test_independent_approval_revision_and_wrong_receipt(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        a = ledger.prepare(key('a'), {'text': 'one'})
        b = ledger.prepare(key('b'), {'text': 'one'})
        ledger.approve(a, expected_version=1)
        ledger.approve(b, expected_version=1)
        ledger.revise(b, {'text': 'two'})
        with pytest.raises(ValueError):
            ledger.claim(b, expected_version=2)
        attempt = ledger.claim(a, expected_version=1)
        with pytest.raises(ValueError):
            ledger.finish(a, attempt=attempt, destination='fixture-b', remote_id='fixture-remote-a')
        ledger.finish(a, attempt=attempt, destination='fixture-a', remote_id='fixture-remote-a')
        assert ledger.get(a)['state'] == 'accepted'
        assert ledger.get(b)['state'] == 'prepared'
    finally:
        con.close()


def test_interrupted_claim_recovers_as_unknown_after_reopen(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    item = ledger.prepare(key('a'), {'text': 'one'})
    ledger.approve(item, expected_version=1)
    attempt = ledger.claim(item, expected_version=1)
    con.close()
    con = sqlite3.connect(db)
    try:
        reopened = DestinationFixtureLedger.open(con)
        reopened.mark_unknown(item, attempt=attempt)
        assert reopened.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            reopened.claim(item, expected_version=1)
    finally:
        con.close()


def test_never_initialize_on_nonempty_database(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        con.execute('CREATE TABLE existing(value TEXT)')
        with pytest.raises(ValueError):
            DestinationFixtureLedger.initialize(con)
        assert con.execute('SELECT name FROM sqlite_master').fetchall() == [('existing',)]
    finally:
        con.close()


def test_two_processes_claim_one_destination_only_once(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    a = ledger.prepare(key('a'), {'text': 'one'})
    b = ledger.prepare(key('b'), {'text': 'one'})
    ledger.approve(a, expected_version=1)
    ledger.approve(b, expected_version=1)
    con.close()
    context = multiprocessing.get_context('spawn')
    start = context.Event()
    results = context.Queue()
    processes = [context.Process(target=claim_process, args=(str(db), a, start, results)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        assert [results.get(timeout=15) for _ in processes].count('ready') == 2
        start.set()
        assert sorted(results.get(timeout=15) for _ in processes) == ['claimed', 'refused']
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        con = sqlite3.connect(db)
        try:
            reopened = DestinationFixtureLedger.open(con)
            assert reopened.get(a)['state'] == 'submitting'
            assert reopened.claim(b, expected_version=1)
        finally:
            con.close()
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        results.close()


def test_remote_receipt_cannot_be_shared_between_destinations(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        a = ledger.prepare(key('a'), {'text': 'one'})
        b = ledger.prepare(key('b'), {'text': 'one'})
        ledger.approve(a, expected_version=1)
        ledger.approve(b, expected_version=1)
        aa = ledger.claim(a, expected_version=1)
        bb = ledger.claim(b, expected_version=1)
        ledger.finish(a, attempt=aa, destination='fixture-a', remote_id='fixture-same')
        with pytest.raises(ValueError, match='conflict'):
            ledger.finish(b, attempt=bb, destination='fixture-b', remote_id='fixture-same')
        assert ledger.get(b)['state'] == 'unknown'
        assert ledger.get(b)['conflict_remote_id'] == 'fixture-same'
    finally:
        con.close()


@pytest.mark.parametrize('bad', ['', 'fixture-', 'fixture-a\x00b', 'fixture-a\n', 'fixture-a/b'])
def test_destination_ids_are_safe_nonempty_fixture_labels(tmp_path, bad):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = key('a')
        item['destination_id'] = bad
        with pytest.raises(ValueError):
            ledger.prepare(item, {'text': 'one'})
    finally:
        con.close()


def test_temp_table_cannot_shadow_fixture_table(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        DestinationFixtureLedger.initialize(con)
        con.execute('CREATE TEMP TABLE destination_fixture_intents (intent_id TEXT)')
        with pytest.raises(ValueError):
            DestinationFixtureLedger.open(con)
    finally:
        con.close()


@pytest.mark.parametrize('snapshot', [None, [], {}, {'destination_id': 'fixture-b'},
                                      {'account_id': 'fixture-other'}, {'platform': 'threads'}])
def test_snapshot_must_be_nonempty_and_consistent_with_destination(tmp_path, snapshot):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            ledger.prepare(key('a'), snapshot)
    finally:
        con.close()


def test_constructor_cannot_bypass_schema_check(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        with pytest.raises((TypeError, ValueError)):
            DestinationFixtureLedger(con)
    finally:
        con.close()


def test_open_rejects_extra_database_objects(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        DestinationFixtureLedger.initialize(con)
        con.execute('CREATE TABLE unrelated(value TEXT)')
        with pytest.raises(ValueError):
            DestinationFixtureLedger.open(con)
    finally:
        con.close()


def test_schema_version_marker_is_required(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        DestinationFixtureLedger.initialize(con)
        assert con.execute('PRAGMA user_version').fetchone()[0] == 6
        con.execute('PRAGMA user_version=7')
        with pytest.raises(ValueError):
            DestinationFixtureLedger.open(con)
    finally:
        con.close()


def test_similar_but_noninternal_sqlite_name_is_not_treated_as_empty(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        con.execute('CREATE TABLE sqlitexfixture(value TEXT)')
        with pytest.raises(ValueError):
            DestinationFixtureLedger.initialize(con)
        assert con.execute("SELECT count(*) FROM main.sqlite_master WHERE name='destination_fixture_intents'").fetchone()[0] == 0
    finally:
        con.close()


def test_same_occurrence_and_destination_cannot_use_two_account_aliases(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        ledger.prepare(key('a'), {'text': 'one'})
        different_account = {**key('a'), 'account_id': 'fixture-other-account'}
        with pytest.raises(ValueError):
            ledger.prepare(different_account, {'text': 'one'})
    finally:
        con.close()


def test_batch_grant_and_revoke_one_destination_before_due_claim(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        a = ledger.prepare(key('a'), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'one'})
        b = ledger.prepare(key('b'), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'one'})
        ledger.approve_batch([(a, 1), (b, 1)])
        ledger.revoke(a, expected_version=1)
        assert ledger.get(a)['version'] == 2
        with pytest.raises(ValueError):
            ledger.approve(a, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [b]
        with pytest.raises(ValueError):
            ledger.claim_due(a, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.claim_due(a, expected_version=2, now='2026-11-20T03:00:00Z')
        assert ledger.claim_due(b, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_batch_grant_rolls_back_when_one_version_is_stale(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        a = ledger.prepare(key('a'), {'text': 'one'})
        b = ledger.prepare(key('b'), {'text': 'one'})
        ledger.revise(b, {'text': 'two'})
        with pytest.raises(ValueError):
            ledger.approve_batch([(a, 1), (b, 1)])
        assert ledger.get(a)['grant_version'] is None
        assert ledger.get(b)['grant_version'] is None
    finally:
        con.close()


@pytest.mark.parametrize('batch', [[], [('x', 1), ('x', 1)], [('x', True)], [('x', 0)], [('x', 1, 2)], None])
def test_batch_grant_rejects_invalid_input(tmp_path, batch):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            ledger.approve_batch(batch)
    finally:
        con.close()


def test_revoke_cannot_cancel_an_inflight_attempt(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key('a'), {'text': 'one'})
        ledger.approve(item, expected_version=1)
        ledger.claim(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.revoke(item, expected_version=1)
        assert ledger.get(item)['state'] == 'submitting'
    finally:
        con.close()


def test_revoke_and_due_claim_race_has_one_winner(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    item = ledger.prepare(key('a'), {'scheduled_at': '2026-11-20T03:00:00Z'})
    ledger.approve(item, expected_version=1)
    con.close()
    barrier = threading.Barrier(2)
    def act(action):
        conn = sqlite3.connect(db, timeout=10)
        try:
            other = DestinationFixtureLedger.open(conn)
            barrier.wait(timeout=10)
            try:
                if action == 'revoke':
                    other.revoke(item, expected_version=1)
                else:
                    other.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
                return action
            except ValueError:
                return 'refused'
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(act, ['revoke', 'claim']))
    assert outcomes.count('refused') == 1
    con = sqlite3.connect(db)
    try:
        row = DestinationFixtureLedger.open(con).get(item)
        if 'claim' in outcomes:
            assert row['state'] == 'submitting' and row['version'] == 1
        else:
            assert row['state'] == 'prepared' and row['version'] == 2 and row['grant_version'] is None
    finally:
        con.close()


def test_batch_uses_input_snapshot_even_if_caller_mutates_list(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        a = ledger.prepare(key('a'), {'text': 'one'})
        b = ledger.prepare(key('b'), {'text': 'one'})
        entries = [(a, 1)]
        def mutate(sql):
            if sql == 'BEGIN IMMEDIATE':
                entries[:] = [(b, 1)]
        con.set_trace_callback(mutate)
        ledger.approve_batch(entries)
        con.set_trace_callback(None)
        assert ledger.get(a)['grant_version'] == 1
        assert ledger.get(b)['grant_version'] is None
    finally:
        con.close()


def test_out_of_range_version_is_rejected_as_value_error(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key('a'), {'text': 'one'})
        with pytest.raises(ValueError):
            ledger.approve(item, expected_version=2**63)
        with pytest.raises(ValueError):
            ledger.revoke(item, expected_version=2**63)
    finally:
        con.close()


def test_prepare_batch_is_atomic_and_remains_unapproved(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        records = [(key('a'), {'text': 'one'}), (key('b'), {'text': 'two'})]
        ids = ledger.prepare_batch(records)
        assert len(ids) == 2 and ids[0] != ids[1]
        assert all(ledger.get(item)['grant_version'] is None for item in ids)
        assert ledger.prepare_batch(records) == ids
    finally:
        con.close()


def test_prepare_batch_rolls_back_when_later_target_conflicts(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        existing = ledger.prepare(key('b'), {'text': 'existing'})
        with pytest.raises(ValueError):
            ledger.prepare_batch([(key('a'), {'text': 'new'}), (key('b'), {'text': 'conflict'})])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
        assert ledger.get(existing)['state'] == 'prepared'
    finally:
        con.close()


@pytest.mark.parametrize('records', [[], None, [(key('a'), {'text': 'x'}), (key('a'), {'text': 'x'})],
                                     [(key('a'), {})], [('not-a-key', {'text': 'x'})]])
def test_prepare_batch_rejects_invalid_or_duplicate_entries(tmp_path, records):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            ledger.prepare_batch(records)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_prepare_batch_uses_snapshot_when_caller_mutates_during_transaction(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        records = [(key('a'), {'text': 'original'})]
        def mutate(sql):
            if sql == 'BEGIN IMMEDIATE':
                records[0][1]['text'] = 'changed'
                records.append((key('b'), {'text': 'extra'}))
        con.set_trace_callback(mutate)
        ids = ledger.prepare_batch(records)
        con.set_trace_callback(None)
        assert len(ids) == 1
        import json
        assert json.loads(ledger.get(ids[0])['snapshot_json'])['payload']['text'] == 'original'
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
    finally:
        con.close()


def test_prepare_batch_allows_different_platforms_with_independent_grants(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        first = key('a')
        second = {**key('b'), 'platform': 'x'}
        a, b = ledger.prepare_batch([(first, {'text': 'discord'}), (second, {'text': 'x'})])
        ledger.approve_batch([(a, 1), (b, 1)])
        ledger.revoke(a, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim(a, expected_version=1)
        assert ledger.claim(b, expected_version=1)
    finally:
        con.close()


def test_prepare_batch_freezes_membership_before_deep_copy(tmp_path):
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    class MutatingList(list):
        def __deepcopy__(self, memo):
            return []
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = ledger.prepare_batch(MutatingList([(key('a'), {'text': 'one'})]))
        assert len(ids) == 1
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
    finally:
        con.close()
