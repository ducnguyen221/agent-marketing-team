"""Timed claiming on synthetic SQLite only; never runs a provider."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def key(dest='fixture-destination'):
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'threads',
            'account_id': 'fixture-account', 'destination_id': dest, 'occurrence_key': 'fixture-slot'}


def test_due_claim_requires_time_and_grant(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        assert hasattr(ledger, 'claim_due')
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'fixture'})
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T02:59:59Z')
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert attempt == ledger.get(item)['attempt_id']
        assert ledger.get(item)['state'] == 'submitting'
    finally:
        con.close()


def test_offsets_are_compared_by_instant_and_subseconds_rejected(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T10:00:00+07:00', 'text': 'fixture'})
        ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00.1Z')
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_reschedule_invalidates_grant_and_prevents_claim(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'fixture'})
        ledger.approve(item, expected_version=1)
        ledger.revise(item, {'scheduled_at': '2026-11-21T03:00:00Z', 'text': 'fixture'})
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=2, now='2026-11-21T03:00:00Z')
        ledger.approve(item, expected_version=2)
        assert ledger.claim_due(item, expected_version=2, now='2026-11-21T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.revise(item, {'scheduled_at': '2026-11-22T03:00:00Z'})
    finally:
        con.close()


def test_tampered_snapshot_or_unzoned_time_cannot_claim(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'fixture'})
        ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00')
        con.execute("UPDATE destination_fixture_intents SET snapshot_json='{}' WHERE intent_id=?", (item,))
        con.commit()
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


def test_two_connections_race_one_due_claim(tmp_path):
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'fixture'})
    ledger.approve(item, expected_version=1)
    con.close()
    def claim():
        conn = sqlite3.connect(db, timeout=10)
        try:
            other = DestinationFixtureLedger.open(conn)
            try:
                other.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
                return 'claimed'
            except ValueError:
                return 'refused'
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == ['claimed', 'refused']


def test_scan_due_orders_by_instant_and_reports_invalid_schedule(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        later = ledger.prepare(key('fixture-later'), {'scheduled_at': '2026-11-20T04:00:00Z'})
        early = ledger.prepare(key('fixture-early'), {'scheduled_at': '2026-11-20T10:00:00+07:00'})
        future = ledger.prepare(key('fixture-future'), {'scheduled_at': '2026-11-21T00:00:00Z'})
        invalid = ledger.prepare(key('fixture-invalid'), {'scheduled_at': 'tomorrow'})
        pending = ledger.prepare(key('fixture-pending'), {'scheduled_at': '2026-11-20T01:00:00Z'})
        for item in (later, early, future, invalid):
            ledger.approve(item, expected_version=1)
        result = ledger.scan_due(now='2026-11-20T05:00:00Z')
        assert result == {'due': [early, later], 'invalid': [invalid]}
        assert ledger.get(pending)['state'] == 'prepared'
        assert ledger.get(early)['state'] == 'prepared'
    finally:
        con.close()


def test_reschedule_and_due_claim_are_serialized(tmp_path):
    import threading
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z', 'text': 'fixture'})
    ledger.approve(item, expected_version=1)
    con.close()
    barrier = threading.Barrier(2)
    def perform(action):
        conn = sqlite3.connect(db, timeout=10)
        try:
            other = DestinationFixtureLedger.open(conn)
            barrier.wait(timeout=10)
            try:
                if action == 'claim':
                    other.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
                else:
                    other.revise(item, {'scheduled_at': '2026-11-21T03:00:00Z', 'text': 'fixture'})
                return action
            except ValueError:
                return 'refused'
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(perform, ['claim', 'revise']))
    assert result.count('refused') == 1
    con = sqlite3.connect(db)
    try:
        row = DestinationFixtureLedger.open(con).get(item)
        if 'claim' in result:
            assert row['state'] == 'submitting' and row['version'] == 1
        else:
            assert row['state'] == 'prepared' and row['version'] == 2 and row['grant_version'] is None
    finally:
        con.close()


@pytest.mark.parametrize('bad', ['2026-11-20T15:00:00+12:60', '2026-11-20T15:00:00+00:99',
                                 '2026-11-20T15:00:00-00:00'])
def test_invalid_or_unknown_utc_offset_is_rejected(tmp_path, bad):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.scan_due(now=bad)
    finally:
        con.close()


def test_generic_claim_cannot_bypass_schedule_or_corrupt_snapshot(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-21T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError):
            ledger.claim(item, expected_version=1)
        con.execute("UPDATE destination_fixture_intents SET snapshot_json='{}' WHERE intent_id=?", (item,))
        con.commit()
        with pytest.raises(ValueError):
            ledger.claim(item, expected_version=1)
    finally:
        con.close()


def test_duplicate_nested_json_is_reported_as_invalid(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = ledger.prepare(key(), {'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        raw = ('{"destination_id":"fixture-destination","payload":'
               '{"scheduled_at":"2026-11-20T03:00:00Z","scheduled_at":"2026-11-20T03:00:00Z"}}')
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=? WHERE intent_id=?', (raw, item))
        con.commit()
        assert ledger.scan_due(now='2026-11-20T03:00:00Z') == {'due': [], 'invalid': [item]}
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_scan_over_limit_fails_instead_of_hiding_rows():
    con = sqlite3.connect(':memory:')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        for number in range(1001):
            item = ledger.prepare(key(f'fixture-{number}'), {'scheduled_at': '2026-11-20T03:00:00Z'})
            ledger.approve(item, expected_version=1)
        with pytest.raises(ValueError, match='limit'):
            ledger.scan_due(now='2026-11-20T03:00:00Z')
        assert not con.in_transaction
    finally:
        con.close()
