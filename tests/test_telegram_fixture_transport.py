"""Telegram publisher fixture end-to-end; no real bot or network."""
import importlib
import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


@pytest.mark.parametrize(('kind', 'filename', 'method'), [
    ('text', 'v1_facebook_to_telegram_simulation.json', 'sendMessage'),
    ('image', 'v1_to_telegram_image_simulation.json', 'sendPhoto'),
    ('video', 'v1_to_telegram_video_simulation.json', 'sendVideo'),
])
def test_v1_through_fake_telegram_transport(tmp_path, monkeypatch, kind, filename, method):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network forbidden'))
    try:
        module = importlib.import_module('scripts.social.telegram_fixture_transport')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.telegram_fixture_transport':
            pytest.fail('Telegram fixture transport is missing')
        raise
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' / filename).read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'telegram')
    response = {'message_id': 5, 'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'}}
    if kind == 'text': response['text'] = entry['args']['adapted_text']
    elif kind == 'image': response.update(photo=[{'file_id': 'fixture-photo'}], caption=entry['args']['adapted_caption'])
    else: response.update(video={'file_id': 'fixture-video'}, caption=entry['args']['adapted_caption'])
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        transport = module.FakeTelegramTransport(response=response)
        module.send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
        assert transport.last_candidate['request']['method'] == method
        assert transport.last_candidate == json.loads(ledger.get(item)['snapshot_json'])['payload']['candidate']
        assert transport.last_attempt == ledger.get(item)['attempt_id']
        assert hasattr(transport, 'last_account_id'), 'fake did not record the publishing bot'
        assert transport.last_account_id == entry['args']['key']['account_id']
        assert ledger.get(item)['state'] == 'accepted'
        with pytest.raises(ValueError):
            module.send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()


@pytest.mark.parametrize('mutation', ['lost', 'wrong_chat', 'private', 'wrong_text', 'wrong_id', 'text_caption'])
def test_untrusted_response_never_confirms_or_resends(tmp_path, mutation):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_facebook_to_telegram_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'telegram')
    response = {'message_id': 5, 'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'},
                'text': entry['args']['adapted_text']}
    if mutation == 'lost': response = None
    elif mutation == 'wrong_chat': response['chat']['id'] = -100999
    elif mutation == 'private': response['chat']['type'] = 'private'
    elif mutation == 'wrong_text': response['text'] = 'khac'
    elif mutation == 'wrong_id': response['message_id'] = True
    else: response['caption'] = 'unexpected'
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        transport = FakeTelegramTransport(response=response)
        send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()


def test_two_workers_only_call_fake_telegram_once(tmp_path):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_facebook_to_telegram_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'telegram')
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
    finally:
        con.close()
    transport = FakeTelegramTransport(response={'message_id': 5,
        'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'}, 'text': entry['args']['adapted_text']})
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
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.get(item)['attempt_id'] == transport.last_attempt
    finally:
        con.close()


def test_wrong_media_response_is_unknown(tmp_path):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_to_telegram_image_simulation.json').read_text(encoding='utf-8'))
    entry = data['entries'][0]
    response = {'message_id': 5, 'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'},
                'video': {'file_id': 'fixture-video'}, 'caption': entry['args']['adapted_caption']}
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        transport = FakeTelegramTransport(response=response)
        send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert ledger.get(item)['state'] == 'unknown'
        assert transport.calls == 1
    finally:
        con.close()


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_media_response_with_unexpected_text_is_unknown(tmp_path, kind):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       f'v1_to_telegram_{kind}_simulation.json').read_text(encoding='utf-8'))
    entry = data['entries'][0]
    media = {'photo': [{'file_id': 'fixture-photo'}]} if kind == 'image' else {'video': {'file_id': 'fixture-video'}}
    response = {'message_id': 5, 'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'},
                'caption': entry['args']['adapted_caption'], 'text': 'unexpected', **media}
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        transport = FakeTelegramTransport(response=response)
        send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()


def test_receipt_storage_failure_keeps_claim_locked(tmp_path):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_facebook_to_telegram_simulation.json').read_text(encoding='utf-8'))
    entry = next(item for item in data['entries'] if item['platform'] == 'telegram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        con.execute("CREATE TEMP TRIGGER fail_telegram_fixture BEFORE UPDATE OF state ON main.destination_fixture_intents "
                    "WHEN NEW.state='accepted' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        transport = FakeTelegramTransport(response={'message_id': 5,
            'chat': {'id': int(entry['args']['chat_id']), 'type': 'channel'}, 'text': entry['args']['adapted_text']})
        with pytest.raises(sqlite3.IntegrityError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert ledger.get(item)['state'] == 'submitting'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=transport)
        assert transport.calls == 1
    finally:
        con.close()


@pytest.mark.parametrize('case', ['no_grant', 'not_due', 'wrong_platform'])
def test_ineligible_intent_never_calls_fake_telegram(tmp_path, case):
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' /
                       'v1_facebook_to_telegram_simulation.json').read_text(encoding='utf-8'))
    platform = 'facebook' if case == 'wrong_platform' else 'telegram'
    entry = next(item for item in data['entries'] if item['platform'] == platform)
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=[entry])
        if case != 'no_grant':
            ledger.approve(item, expected_version=1)
        transport = FakeTelegramTransport(response=None)
        now = '2026-11-19T03:00:00Z' if case == 'not_due' else '2026-11-20T04:00:00Z'
        with pytest.raises(ValueError):
            send_due_fixture(ledger, item, expected_version=1, now=now, transport=transport)
        assert ledger.get(item)['state'] == 'prepared'
        assert transport.calls == 0
    finally:
        con.close()
