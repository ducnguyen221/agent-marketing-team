"""LinkedIn delivery orchestration with synthetic transport only."""
import importlib
import inspect
import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def fixture_data():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_v1_text_through_fake_transport_persists_one_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *args, **kwargs: pytest.fail('unexpected network'))
    try:
        module = importlib.import_module('scripts.social.linkedin_fixture_transport')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.linkedin_fixture_transport':
            pytest.fail('synthetic LinkedIn delivery orchestration is missing')
        raise
    source = fixture_data()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][4]])
        ledger.approve(item, expected_version=1)
        transport = module.FakeLinkedInTransport(post_urn='urn:li:share:123')
        module.send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
        assert transport.last_attempt == ledger.get(item)['attempt_id']
        assert transport.last_candidate['request']['body']['author'] == source['entries'][4]['args']['author']
        assert transport.last_candidate == json.loads(ledger.get(item)['snapshot_json'])['payload']['candidate']
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.get_linkedin_fixture_receipt(item)['post_urn'] == 'urn:li:share:123'
        with pytest.raises(ValueError):
            module.send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()


def test_lost_fake_response_is_unknown_and_never_sent_again(tmp_path):
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture
    source = fixture_data()
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][4]])
        ledger.approve(item, expected_version=1)
        assert 'outcome' in inspect.signature(FakeLinkedInTransport).parameters, 'lost response mode is missing'
        transport = FakeLinkedInTransport(post_urn='urn:li:share:123', outcome='lost')
        send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        assert DestinationFixtureLedger.open(con).get(item)['state'] == 'unknown'
    finally:
        con.close()


def test_linkedin_atomic_claim_rejects_other_platform_before_changing_state(tmp_path):
    source = fixture_data()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][0]])
        ledger.approve(item, expected_version=1)
        assert hasattr(ledger, 'claim_due_linkedin_fixture'), 'atomic LinkedIn claim is missing'
        with pytest.raises(ValueError):
            ledger.claim_due_linkedin_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


def test_two_workers_send_only_one_fake_request(tmp_path):
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture
    source = fixture_data()
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][4]])
        ledger.approve(item, expected_version=1)
    finally:
        con.close()
    transport = FakeLinkedInTransport(post_urn='urn:li:share:123')
    barrier = threading.Barrier(2)
    def worker():
        connection = sqlite3.connect(database, timeout=10)
        try:
            ledger = DestinationFixtureLedger.open(connection)
            barrier.wait(timeout=10)
            try:
                send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
                return 'accepted'
            except ValueError:
                return 'refused'
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(outcomes) == ['accepted', 'refused']
    assert transport.calls == 1
    con = sqlite3.connect(database)
    try:
        assert DestinationFixtureLedger.open(con).get(item)['state'] == 'accepted'
    finally:
        con.close()


@pytest.mark.parametrize('case', ['not_due', 'unapproved', 'other_platform'])
def test_invalid_delivery_never_calls_transport(tmp_path, case):
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture
    source = fixture_data()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        index = 0 if case == 'other_platform' else 4
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][index]])
        if case != 'unapproved':
            ledger.approve(item, expected_version=1)
        transport = FakeLinkedInTransport(post_urn='urn:li:share:123')
        now = '2026-11-19T03:00:00Z' if case == 'not_due' else '2026-11-20T04:00:00Z'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now=now, transport=transport)
        assert transport.calls == 0
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


def test_receipt_write_failure_does_not_resend(tmp_path):
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture
    source = fixture_data()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'],
                                          entries=[source['entries'][4]])
        ledger.approve(item, expected_version=1)
        con.execute("CREATE TEMP TRIGGER fail_fixture_accept BEFORE UPDATE OF state ON main.destination_fixture_intents "
                    "WHEN NEW.state='accepted' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        transport = FakeLinkedInTransport(post_urn='urn:li:share:123')
        with pytest.raises(sqlite3.IntegrityError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert ledger.get(item)['state'] == 'submitting'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()
