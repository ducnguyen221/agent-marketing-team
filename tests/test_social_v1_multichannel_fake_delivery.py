"""One synthetic V1 publication drives independent fake social destinations."""
import copy
import importlib
import json
import socket
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture as send_linkedin
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch
from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture as send_telegram


@pytest.mark.parametrize('instagram_lost', [False, True])
def test_one_v1_publication_drives_three_independent_fake_destinations(tmp_path, monkeypatch, instagram_lost):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network forbidden'))
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    ig = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'instagram'))
    li = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'linkedin'))
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        instagram, linkedin, telegram = prepare_v1_fixture_batch(
            ledger, source=source['source'], publication=source['publication'], entries=[ig, li, tg])
        ledger.approve_batch([(item, 1) for item in (instagram, linkedin, telegram)])
        ig_fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id=None if instagram_lost else '202')
        li_fake = FakeLinkedInTransport(post_urn='urn:li:share:303')
        tg_fake = FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                                   'text': 'Bài riêng cho Telegram'})
        when = '2026-11-20T04:00:00Z'
        ig_attempt = create_due_fixture(ledger, instagram, expected_version=1, now=when, transport=ig_fake)
        assert observe_fixture(ledger, instagram, attempt=ig_attempt, transport=ig_fake)
        publish_fixture(ledger, instagram, attempt=ig_attempt, transport=ig_fake)
        send_telegram(ledger, telegram, expected_version=1, now=when, transport=tg_fake)
        send_linkedin(ledger, linkedin, expected_version=1, now=when, transport=li_fake)
        assert ig_fake.create_calls == ig_fake.publish_calls == li_fake.calls == tg_fake.calls == 1
        assert ig_fake.last_create['request']['params']['media_type'] == 'REELS'
        assert ig_fake.last_create['request']['params']['caption'] == 'Reel giả trên Facebook'
        assert tg_fake.last_candidate['request']['body']['text'] == 'Bài riêng cho Telegram'
        assert li_fake.last_candidate['request']['body']['author'] == li['args']['author']
        assert li_fake.last_candidate['request']['body']['commentary'] == li['args']['adapted_text']
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(instagram)['state'] == ('unknown' if instagram_lost else 'accepted')
        assert ledger.get(linkedin)['state'] == 'accepted'
        assert ledger.get(telegram)['state'] == 'accepted'
        assert ledger.get(telegram)['remote_id'] == 'fixture-telegram-message-123-404'
        assert ledger.get_linkedin_fixture_receipt(linkedin)['post_urn'] == 'urn:li:share:303'
        ig_status = ledger.instagram_session_status(instagram, attempt=ig_attempt)
        assert ig_status['container_id'] == '101'
        assert ig_status['media_id'] == (None if instagram_lost else '202')
        if instagram_lost:
            with pytest.raises(ValueError):
                publish_fixture(ledger, instagram, attempt=ig_attempt, transport=ig_fake)
            assert ig_fake.publish_calls == 1
    finally:
        con.close()


def test_batch_fixture_dispatch_reports_each_destination_and_does_not_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network forbidden'))
    try:
        module = importlib.import_module('scripts.social.multichannel_fixture_dispatch')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.multichannel_fixture_dispatch':
            pytest.fail('multi-channel fixture dispatcher is missing')
        raise
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    ig = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'instagram'))
    li = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'linkedin'))
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        instagram, linkedin, telegram = prepare_v1_fixture_batch(
            ledger, source=source['source'], publication=source['publication'], entries=[ig, li, tg])
        ledger.approve_batch([(instagram, 1), (linkedin, 1)])
        ig_fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id=None)
        li_fake = FakeLinkedInTransport(post_urn='urn:li:share:303')
        tg_fake = FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                                   'text': 'Bài riêng cho Telegram'})
        result = module.dispatch_due_fixture_batch(ledger, jobs=[
            {'intent_id': instagram, 'version': 1, 'transport': ig_fake},
            {'intent_id': telegram, 'version': 1, 'transport': tg_fake},
            {'intent_id': linkedin, 'version': 1, 'transport': li_fake}], now='2026-11-20T04:00:00Z')
        assert [item['state'] for item in result['items']] == ['unknown', 'prepared', 'accepted']
        assert result['items'][1]['outcome'] == 'refused'
        assert tg_fake.calls == 0 and li_fake.calls == ig_fake.publish_calls == 1
        assert ledger.get(telegram)['grant_version'] is None
        repeated = module.dispatch_due_fixture_batch(ledger, jobs=[
            {'intent_id': linkedin, 'version': 1, 'transport': li_fake}], now='2026-11-20T04:00:00Z')
        assert repeated['items'][0]['outcome'] == 'already_accepted'
        assert li_fake.calls == 1
        stale = module.dispatch_due_fixture_batch(ledger, jobs=[
            {'intent_id': linkedin, 'version': 2, 'transport': li_fake}], now='2026-11-20T04:00:00Z')
        assert stale['items'][0]['outcome'] == 'refused'
        assert li_fake.calls == 1
    finally:
        con.close()


def test_batch_preflight_rejects_mismatched_fake_before_any_claim(tmp_path):
    from scripts.social.multichannel_fixture_dispatch import dispatch_due_fixture_batch
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    ig = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'instagram'))
    li = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'linkedin'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        instagram, linkedin = prepare_v1_fixture_batch(ledger, source=source['source'],
                                                       publication=source['publication'], entries=[ig, li])
        ledger.approve_batch([(instagram, 1), (linkedin, 1)])
        ig_fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        wrong = FakeTelegramTransport(response=None)
        with pytest.raises(ValueError):
            dispatch_due_fixture_batch(ledger, jobs=[{'intent_id': instagram, 'version': 1, 'transport': ig_fake},
                                                     {'intent_id': linkedin, 'version': 1, 'transport': wrong}],
                                       now='2026-11-20T04:00:00Z')
        assert ig_fake.create_calls == wrong.calls == 0
        assert ledger.get(instagram)['state'] == ledger.get(linkedin)['state'] == 'prepared'
    finally:
        con.close()


def test_batch_sqlite_error_propagates_without_resending_completed_jobs(tmp_path):
    from scripts.social.multichannel_fixture_dispatch import dispatch_due_fixture_batch
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    ig = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'instagram'))
    li = copy.deepcopy(next(entry for entry in source['entries'] if entry['platform'] == 'linkedin'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        instagram, linkedin = prepare_v1_fixture_batch(ledger, source=source['source'],
                                                       publication=source['publication'], entries=[ig, li])
        ledger.approve_batch([(instagram, 1), (linkedin, 1)])
        con.execute("CREATE TEMP TRIGGER fail_linkedin_receipt BEFORE UPDATE OF state ON main.destination_fixture_intents "
                    "WHEN NEW.platform='linkedin' AND NEW.state='accepted' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        ig_fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        li_fake = FakeLinkedInTransport(post_urn='urn:li:share:303')
        jobs = [{'intent_id': instagram, 'version': 1, 'transport': ig_fake},
                {'intent_id': linkedin, 'version': 1, 'transport': li_fake}]
        with pytest.raises(sqlite3.IntegrityError):
            dispatch_due_fixture_batch(ledger, jobs=jobs, now='2026-11-20T04:00:00Z')
        assert ledger.get(instagram)['state'] == 'accepted'
        assert ledger.get(linkedin)['state'] == 'submitting'
        result = dispatch_due_fixture_batch(ledger, jobs=jobs, now='2026-11-20T04:00:00Z')
        assert [item['outcome'] for item in result['items']] == ['already_accepted', 'incomplete']
        assert ig_fake.publish_calls == li_fake.calls == 1
    finally:
        con.close()


def test_batch_instagram_waiting_can_resume_without_recreating_container(tmp_path):
    from scripts.social.multichannel_fixture_dispatch import dispatch_due_fixture_batch
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in source['entries'] if entry['platform'] == 'instagram')
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        fake = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
        jobs = [{'intent_id': item, 'version': 1, 'transport': fake}]
        first = dispatch_due_fixture_batch(ledger, jobs=jobs, now='2026-11-20T04:00:00Z')
        assert first['items'][0]['outcome'] == 'awaiting_observation'
        fake.status = 'FINISHED'
        second = dispatch_due_fixture_batch(ledger, jobs=jobs, now='2026-11-20T04:00:00Z')
        assert second['items'][0]['outcome'] == 'accepted'
        assert fake.create_calls == fake.publish_calls == 1
    finally:
        con.close()


def test_batch_duplicate_telegram_receipt_reports_unknown(tmp_path):
    from scripts.social.multichannel_fixture_dispatch import dispatch_due_fixture_batch
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in source['entries'] if entry['platform'] == 'telegram')
    other = copy.deepcopy(entry)
    other['args']['key']['occurrence_key'] = 'fixture-second'
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry, other])
        ledger.approve_batch([(item, 1) for item in items])
        response = {'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'}, 'text': entry['args']['adapted_text']}
        shared = FakeTelegramTransport(response=response)
        fakes = [shared, shared]
        jobs = [{'intent_id': item, 'version': 1, 'transport': fake} for item, fake in zip(items, fakes)]
        result = dispatch_due_fixture_batch(ledger, jobs=jobs, now='2026-11-20T04:00:00Z')
        assert [row['state'] for row in result['items']] == ['accepted', 'unknown']
        assert [row['outcome'] for row in result['items']] == ['accepted', 'unknown']
        assert shared.calls == 2
    finally:
        con.close()


def test_batch_reports_already_accepted_if_other_worker_wins_publish(tmp_path, monkeypatch):
    from scripts.social.multichannel_fixture_dispatch import dispatch_due_fixture_batch
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in source['entries'] if entry['platform'] == 'instagram')
    database = tmp_path / 'fixture.sqlite'
    first = sqlite3.connect(database)
    second = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(first)
        observer = DestinationFixtureLedger.open(second)
        item, = prepare_v1_fixture_batch(ledger, source=source['source'], publication=source['publication'], entries=[entry])
        ledger.approve(item, expected_version=1)
        fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        attempt = create_due_fixture(ledger, item, expected_version=1, now='2026-11-20T04:00:00Z', transport=fake)
        assert observe_fixture(ledger, item, attempt=attempt, transport=fake)
        original_status = observer.instagram_session_status
        def concurrent_winner(intent_id, *, attempt):
            result = original_status(intent_id, attempt=attempt)
            publish_fixture(ledger, intent_id, attempt=attempt, transport=fake)
            return result
        monkeypatch.setattr(observer, 'instagram_session_status', concurrent_winner)
        result = dispatch_due_fixture_batch(observer, jobs=[{'intent_id': item, 'version': 1, 'transport': fake}],
                                            now='2026-11-20T04:00:00Z')
        assert result['items'][0]['state'] == 'accepted'
        assert result['items'][0]['outcome'] == 'already_accepted'
        assert fake.publish_calls == 1
    finally:
        first.close()
        second.close()
