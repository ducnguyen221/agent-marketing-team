"""Synthetic two-stage Instagram fixture; never access an account or network."""
import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def test_v1_reel_container_and_publication_are_distinct_and_durable(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('unexpected network'))
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        assert hasattr(ledger, 'claim_due_instagram_fixture'), 'Instagram session is missing'
        attempt, candidate = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        assert candidate['request']['params']['media_type'] == 'REELS'
        ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id='101')
        assert ledger.get(item)['state'] == 'submitting'
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.instagram_session_status(item, attempt=attempt)['phase'] == 'waiting'
        ledger.instagram_observe_ready(item, attempt=attempt, container_id='101', status='FINISHED')
        publish = ledger.instagram_claim_publish(item, attempt=attempt)
        assert publish['request']['params']['creation_id'] == '101'
        ledger.instagram_accept_publish(item, attempt=attempt, container_id='101', media_id='202')
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.instagram_session_status(item, attempt=attempt)['media_id'] == '202'
    finally:
        con.close()


def test_container_is_not_publishable_until_ready_and_cannot_use_generic_finish(tmp_path):
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        attempt, _ = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id='101')
        with pytest.raises(ValueError):
            ledger.instagram_claim_publish(item, attempt=attempt)
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination=entry['args']['key']['destination_id'], remote_id='fixture-any')
        assert ledger.get(item)['state'] == 'submitting'
        assert ledger.instagram_session_status(item, attempt=attempt)['phase'] == 'waiting'
    finally:
        con.close()


@pytest.mark.parametrize('phase', ['creating', 'publishing'])
def test_explicit_recovery_locks_unknown_instagram_outcome(tmp_path, phase):
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        attempt, _ = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        if phase == 'publishing':
            ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id='101')
            ledger.instagram_observe_ready(item, attempt=attempt, container_id='101', status='FINISHED')
            ledger.instagram_claim_publish(item, attempt=attempt)
        assert hasattr(ledger, 'instagram_mark_unknown'), 'Instagram recovery is missing'
        ledger.instagram_mark_unknown(item, attempt=attempt, expected_phase=phase)
        assert ledger.get(item)['state'] == 'unknown'
        assert ledger.instagram_session_status(item, attempt=attempt)['phase'] == 'unknown'
        with pytest.raises(ValueError):
            ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('provider_status', ['ERROR', 'EXPIRED'])
def test_unusable_container_locks_publishing(tmp_path, provider_status):
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        attempt, _ = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id='101')
        ledger.instagram_observe_ready(item, attempt=attempt, container_id='101', status=provider_status)
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            ledger.instagram_claim_publish(item, attempt=attempt)
    finally:
        con.close()


@pytest.mark.parametrize('version', [3, 4, 5])
def test_legacy_fixture_session_access_fails_cleanly(tmp_path, version):
    from scripts.social.destination_ledger_fixture import _DDL, _REEL_DDL, _LINKEDIN_DDL, _LINKEDIN_MEDIA_DDL
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        con.execute(_DDL)
        con.execute(_REEL_DDL)
        if version >= 4:
            con.execute(_LINKEDIN_DDL)
        if version >= 5:
            con.execute(_LINKEDIN_MEDIA_DDL)
        con.execute(f'PRAGMA user_version={version}')
        con.commit()
        ledger = DestinationFixtureLedger.open(con)
        with pytest.raises(ValueError):
            ledger.instagram_session_status('fixture-missing', attempt='fixture-attempt')
    finally:
        con.close()


def test_two_connections_can_claim_publish_only_once(tmp_path):
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        attempt, _ = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
        ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id='101')
        ledger.instagram_observe_ready(item, attempt=attempt, container_id='101', status='FINISHED')
    finally:
        con.close()
    barrier = threading.Barrier(2)
    def worker():
        connection = sqlite3.connect(database, timeout=10)
        try:
            ledger = DestinationFixtureLedger.open(connection)
            barrier.wait(timeout=10)
            try:
                return ledger.instagram_claim_publish(item, attempt=attempt)['request']['params']['creation_id']
            except ValueError:
                return 'refused'
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(outcomes) == ['101', 'refused']
    con = sqlite3.connect(database)
    try:
        assert DestinationFixtureLedger.open(con).instagram_session_status(item, attempt=attempt)['phase'] == 'publishing'
    finally:
        con.close()


def test_duplicate_published_media_marks_second_intent_unknown(tmp_path):
    source = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                         'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in source['entries'] if item['platform'] == 'instagram')
    other = json.loads(json.dumps(entry))
    other['args']['key']['occurrence_key'] = 'fixture-second'
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry, other])
        for index, item in enumerate(items):
            ledger.approve(item, expected_version=1)
            attempt, _ = ledger.claim_due_instagram_fixture(item, expected_version=1, now='2026-11-20T04:00:00Z')
            container = str(101 + index)
            ledger.instagram_accept_container(item, attempt=attempt, user_id=entry['args']['user_id'], container_id=container)
            ledger.instagram_observe_ready(item, attempt=attempt, container_id=container, status='FINISHED')
            ledger.instagram_claim_publish(item, attempt=attempt)
            ledger.instagram_accept_publish(item, attempt=attempt, container_id=container, media_id='202')
        assert [ledger.get(item)['state'] for item in items] == ['accepted', 'unknown']
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert [ledger.get(item)['state'] for item in items] == ['accepted', 'unknown']
    finally:
        con.close()
