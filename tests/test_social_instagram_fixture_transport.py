"""Synthetic two-step Instagram provider without network or real media."""
import importlib
import copy
import json
import socket
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


@pytest.mark.parametrize('kind', ['image', 'reel'])
def test_v1_instagram_through_fake_container_and_publish(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network forbidden'))
    try:
        module = importlib.import_module('scripts.social.instagram_fixture_transport')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.instagram_fixture_transport':
            pytest.fail('Instagram fixture transport is missing')
        raise
    filename = 'v1_to_telegram_image_simulation.json' if kind == 'image' else 'v1_six_channel_simulation.json'
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' / filename).read_text(encoding='utf-8'))
    if kind == 'image':
        old = data['entries'][0]['args']
        key = dict(old['key'], platform='instagram', account_id='fixture-instagram-account-456',
                   destination_id='fixture-instagram-456')
        entry = {'platform': 'instagram', 'args': {'key': key, 'user_id': '456', 'api_version': 'v21.0',
                 'scheduled_at': old['scheduled_at'], 'manifest': old['manifest']}}
    else:
        entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        fake = module.FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        attempt = module.create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake)
        assert getattr(fake, 'last_create_attempt', None) == attempt
        assert ledger.instagram_session_status(item, attempt=attempt)['phase'] == 'waiting'
        assert fake.create_calls == 1 and fake.publish_calls == 0
        module.observe_fixture(ledger, item, attempt=attempt, transport=fake)
        module.publish_fixture(ledger, item, attempt=attempt, transport=fake)
        assert getattr(fake, 'last_publish_attempt', None) == attempt
        assert fake.publish_calls == 1
        assert fake.last_publish['request']['params']['creation_id'] == '101'
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.instagram_session_status(item, attempt=attempt)['media_id'] == '202'
    finally:
        con.close()


@pytest.mark.parametrize('lost_phase', ['create', 'publish'])
def test_lost_side_effect_response_does_not_retry(tmp_path, lost_phase):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        fake = FakeInstagramTransport(container_id=None if lost_phase == 'create' else '101',
                                      status='FINISHED', media_id=None)
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake)
        if lost_phase == 'publish':
            assert observe_fixture(ledger, item, attempt=attempt, transport=fake)
            publish_fixture(ledger, item, attempt=attempt, transport=fake)
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake)
        assert fake.create_calls == 1
        assert fake.publish_calls == (1 if lost_phase == 'publish' else 0)
    finally:
        con.close()


def test_publish_with_other_container_response_stays_unknown(tmp_path):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        first = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='201')
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=first)
        assert observe_fixture(ledger, item, attempt=attempt, transport=first)
        other = FakeInstagramTransport(container_id='102', status='FINISHED', media_id='202')
        publish_fixture(ledger, item, attempt=attempt, transport=other)
        assert ledger.get(item)['state'] == 'unknown'
        assert ledger.instagram_session_status(item, attempt=attempt)['media_id'] is None
        with pytest.raises(ValueError):
            publish_fixture(ledger, item, attempt=attempt, transport=other)
        assert other.publish_calls == 1
    finally:
        con.close()


def test_publish_without_attempt_binding_stays_unknown_even_if_container_matches(tmp_path):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        original = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='201')
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=original)
        assert observe_fixture(ledger, item, attempt=attempt, transport=original)
        other = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        publish_fixture(ledger, item, attempt=attempt, transport=other)
        assert ledger.get(item)['state'] == 'unknown'
        assert other.publish_calls == 1
    finally:
        con.close()


@pytest.mark.parametrize('reverse', [False, True])
def test_reused_fake_keeps_publish_responses_bound_to_attempt(tmp_path, reverse):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    other = copy.deepcopy(entry)
    other['args']['key']['occurrence_key'] = 'fixture-second'
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry, other])
        fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='201')
        attempts = []
        for index, item in enumerate(items):
            fake.container_id, fake.media_id = str(101 + index), str(201 + index)
            ledger.approve(item, expected_version=1)
            attempts.append(create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake))
        for index in ([1, 0] if reverse else [0, 1]):
            fake.container_id = str(101 + index)
            assert observe_fixture(ledger, items[index], attempt=attempts[index], transport=fake)
            publish_fixture(ledger, items[index], attempt=attempts[index], transport=fake)
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        statuses = [ledger.instagram_session_status(item, attempt=attempt) for item, attempt in zip(items, attempts)]
        assert [(row['container_id'], row['media_id']) for row in statuses] == [('101', '201'), ('102', '202')]
        assert all(row['state'] == 'accepted' for row in statuses)
    finally:
        con.close()


@pytest.mark.parametrize(('status', 'expected_state'), [('IN_PROGRESS', 'submitting'), ('ERROR', 'unknown'), ('EXPIRED', 'unknown')])
def test_unready_or_failed_container_never_calls_publish(tmp_path, status, expected_state):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        fake = FakeInstagramTransport(container_id='101', status=status, media_id='201')
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake)
        assert not observe_fixture(ledger, item, attempt=attempt, transport=fake)
        assert ledger.get(item)['state'] == expected_state
        with pytest.raises(ValueError):
            publish_fixture(ledger, item, attempt=attempt, transport=fake)
        assert fake.publish_calls == 0
    finally:
        con.close()


def test_observation_by_another_fake_does_not_bind_publish_response(tmp_path):
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_six_channel_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        original = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='201')
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=original)
        other = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='999')
        assert observe_fixture(ledger, item, attempt=attempt, transport=other)
        publish_fixture(ledger, item, attempt=attempt, transport=other)
        assert ledger.get(item)['state'] == 'unknown'
        assert ledger.instagram_session_status(item, attempt=attempt)['media_id'] is None
    finally:
        con.close()
