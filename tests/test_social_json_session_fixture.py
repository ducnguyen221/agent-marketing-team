"""Persistent, synthetic-only multi-destination session exercises."""
import copy
import json
import queue
import socket
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def sample():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_six_channel_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['entries'] = [entry for entry in data['entries'] if entry['platform'] in ('instagram', 'linkedin', 'threads')]
    return data


def test_session_reopens_three_destinations_and_blocks_unknown_retry(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    original = copy.deepcopy(data)
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: pytest.fail('sqlite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    first = session.claim(0)
    session.finish(0, first, outcome='unknown')
    second = session.claim(1)
    session.finish(1, second, outcome='accepted', receipt='fixture-linkedin-123')
    third = session.claim(2)
    session.finish(2, third, outcome='accepted', receipt='fixture-threads-456')
    reopened = FixtureJsonSession.open(tmp_path)
    assert [row['state'] for row in reopened.inspect()['items']] == ['unknown', 'accepted', 'accepted']
    assert [row['receipt'] for row in reopened.inspect()['items']] == [None, 'fixture-linkedin-123', 'fixture-threads-456']
    with pytest.raises(ValueError):
        reopened.claim(0)
    assert data == original


def test_submitting_after_reopen_cannot_be_claimed_again(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    attempt = session.claim(0)
    reopened = FixtureJsonSession.open(tmp_path)
    assert reopened.inspect()['items'][0]['attempt'] == attempt
    with pytest.raises(ValueError):
        reopened.claim(0)


def test_failed_claim_write_does_not_record_attempt(tmp_path, monkeypatch):
    from scripts.social import json_session_fixture as module

    data = sample()
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=data['entries'])
    session.grant_all()
    def fail_replace(*args):
        raise OSError('fixture disk failure')
    with monkeypatch.context() as patch:
        patch.setattr(module.os, 'replace', fail_replace)
        with pytest.raises(OSError):
            session.claim(0)
    item = module.FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert item['state'] == 'prepared' and item['attempt'] is None
    assert not list(tmp_path.glob('.social-fixture-*.tmp'))


def test_duplicate_fields_in_session_fail_closed(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'], entries=data['entries'])
    path = tmp_path / 'social-fixture-session.json'
    raw = path.read_text(encoding='utf-8')
    path.write_text(raw.replace('"revision": 1', '"revision": 1, "revision": 1'), encoding='utf-8')
    with pytest.raises(ValueError):
        FixtureJsonSession.open(tmp_path)


def test_other_process_cannot_enter_lock_after_session_replace(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'], entries=data['entries'])
    code = ("import sys\nfrom pathlib import Path\n"
            "from scripts.social.json_session_fixture import _locked, _load, _save\n"
            "p=Path(sys.argv[1])\nwith _locked(p):\n"
            " d=_load(p); d['revision']+=1; _save(p,d); print('locked',flush=True); sys.stdin.readline()\n")
    process = subprocess.Popen([sys.executable, '-u', '-c', code, str(tmp_path)], text=True,
                               encoding='utf-8', stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == 'locked'
        with pytest.raises(OSError):
            FixtureJsonSession.open(tmp_path)
    finally:
        process.stdin.write('\n')
        process.stdin.flush()
        process.communicate(timeout=15)
    assert process.returncode == 0
    assert FixtureJsonSession.open(tmp_path).inspect()['revision'] == 2


def test_path_with_parent_traversal_is_refused_before_lock(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    path = tmp_path / '..' / tmp_path.name
    with pytest.raises(ValueError):
        FixtureJsonSession.create(path, source=data['source'], publication=data['publication'], entries=data['entries'])
    assert not (tmp_path / 'social-fixture-session.lock').exists()


def test_old_handle_rejects_replaced_session_identity(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    path = tmp_path / 'social-fixture-session.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['session_id'] = 'fixture-' + 'a' * 32
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        session.grant_all()


def test_session_rejects_duplicate_attempts_on_reopen(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    first, second = session.claim(0), session.claim(1)
    assert first != second
    path = tmp_path / 'social-fixture-session.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['items'][1]['attempt'] = first
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        FixtureJsonSession.open(tmp_path)


def test_process_exit_after_claim_keeps_attempt_and_blocks_repeat(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    code = ("import os,sys\nfrom pathlib import Path\n"
            "from scripts.social.json_session_fixture import FixtureJsonSession\n"
            "s=FixtureJsonSession.open(Path(sys.argv[1])); s.claim(0); os._exit(0)\n")
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 0
    reopened = FixtureJsonSession.open(tmp_path)
    assert reopened.inspect()['items'][0]['state'] == 'submitting'
    with pytest.raises(ValueError):
        reopened.claim(0)


def test_v1_input_files_remain_byte_identical(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    content = tmp_path / 'content.md'
    publication = tmp_path / 'publish.json'
    content.write_text(data['source'], encoding='utf-8')
    publication.write_text(json.dumps(data['publication'], ensure_ascii=False), encoding='utf-8')
    before = (content.read_bytes(), publication.read_bytes())
    FixtureJsonSession.create(tmp_path, source=content.read_text(encoding='utf-8'),
                              publication=json.loads(publication.read_text(encoding='utf-8')), entries=data['entries'])
    assert (content.read_bytes(), publication.read_bytes()) == before


def test_session_file_replaced_between_check_and_open_is_refused(tmp_path, monkeypatch):
    from scripts.social import json_session_fixture as module

    data = sample()
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=data['entries'])
    path = tmp_path / 'social-fixture-session.json'
    replacement = tmp_path / 'replacement.json'
    replacement.write_bytes(path.read_bytes())
    original = module._check_file
    def replace_after_check(candidate):
        result = original(candidate)
        if candidate == path and replacement.exists():
            replacement.replace(path)
        return result
    monkeypatch.setattr(module, '_check_file', replace_after_check)
    with pytest.raises(ValueError):
        session.inspect()


def test_claim_due_checks_time_and_digest_before_persisting(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    item = session.inspect()['items'][0]
    digest = item['snapshot_sha256']
    with pytest.raises(ValueError):
        session.claim_due(0, now='2026-11-20T02:59:59Z', expected_digest=digest, expected_key=item['key'])
    with pytest.raises(ValueError):
        session.claim_due(0, now='2026-11-20T03:00:00Z', expected_digest='0' * 64, expected_key=item['key'])
    assert session.inspect()['items'][0]['state'] == 'prepared'
    attempt = session.claim_due(0, now='2026-11-20T10:00:00+07:00', expected_digest=digest, expected_key=item['key'])
    assert session.inspect()['items'][0]['attempt'] == attempt
    with pytest.raises(ValueError):
        session.claim_due(0, now='2026-11-20T04:00:00Z', expected_digest=digest, expected_key=item['key'])


@pytest.mark.parametrize('now', ['tomorrow', '2026-11-20T03:00:00', '2026-11-20T03:00:00-00:00'])
def test_claim_due_rejects_ambiguous_time_without_changing_state(tmp_path, now):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    before = session.inspect()
    with pytest.raises(ValueError):
        session.claim_due(0, now=now, expected_digest=before['items'][0]['snapshot_sha256'], expected_key=before['items'][0]['key'])
    assert session.inspect() == before


def test_claim_due_rejects_missing_grant(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    before = session.inspect()
    with pytest.raises(ValueError):
        session.claim_due(0, now='2026-11-20T04:00:00Z', expected_digest=before['items'][0]['snapshot_sha256'], expected_key=before['items'][0]['key'])
    assert session.inspect() == before


def test_claim_due_rejects_other_occurrence_with_identical_snapshot(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    other = copy.deepcopy(data['entries'][0])
    other['args']['key']['occurrence_key'] = 'fixture-another-occurrence'
    data['entries'].append(other)
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'])
    session.grant_all()
    before = session.inspect()
    assert before['items'][0]['snapshot_sha256'] == before['items'][-1]['snapshot_sha256']
    with pytest.raises(ValueError):
        session.claim_due(len(before['items']) - 1, now='2026-11-20T04:00:00Z',
                          expected_digest=before['items'][0]['snapshot_sha256'], expected_key=before['items'][0]['key'])
    assert session.inspect() == before


@pytest.mark.parametrize('outcome', ['accepted', 'lost'])
def test_linkedin_delivery_fixture_records_verified_fake_receipt(tmp_path, monkeypatch, outcome):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    data['entries'] = [entry for entry in data['entries'] if entry['platform'] == 'linkedin']
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeLinkedInTransport(post_urn='urn:li:share:123', outcome=outcome)
    session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                              expected_digest=item['snapshot_sha256'], transport=fake)
    row = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert row['state'] == ('accepted' if outcome == 'accepted' else 'unknown')
    if outcome == 'accepted':
        assert row['receipt']['post_urn'] == 'urn:li:share:123'
        assert row['receipt']['attempt'] == row['attempt']
        assert row['receipt']['author'] == item['snapshot']['author']
        assert row['receipt']['readback'] == 'unverified'
    else:
        assert row['receipt'] is None
    assert fake.calls == 1
    with pytest.raises(ValueError):
        session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 1


def test_linkedin_duplicate_urn_marks_second_unknown(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    first = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    second = copy.deepcopy(first)
    second['args']['key']['occurrence_key'] = 'fixture-second'
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[first, second], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    for index in (0, 1):
        session.send_due_linkedin(index, now='2026-11-20T04:00:00Z', expected_key=items[index]['key'],
                                  expected_digest=items[index]['snapshot_sha256'],
                                  transport=FakeLinkedInTransport(post_urn='urn:li:share:123'))
    rows = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['accepted', 'unknown']
    assert rows[1]['conflict_urn'] == rows[0]['receipt']['post_urn']
    path = tmp_path / 'social-fixture-session.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['items'][1]['conflict_urn'] = 'urn:li:share:999'
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        FixtureJsonSession.open(tmp_path)


def test_linkedin_write_failure_after_fake_does_not_repeat(tmp_path, monkeypatch):
    from scripts.social import json_session_fixture as module
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeLinkedInTransport(post_urn='urn:li:share:123')
    original = module._save
    def fail_receipt(directory, value):
        if value['items'][0]['state'] == 'accepted':
            raise OSError('fixture disk failure')
        return original(directory, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_save', fail_receipt)
        with pytest.raises(OSError):
            session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                      expected_digest=item['snapshot_sha256'], transport=fake)
    assert module.FixtureJsonSession.open(tmp_path).inspect()['items'][0]['state'] == 'submitting'
    with pytest.raises(ValueError):
        session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 1


def test_delivery_session_rejects_claimed_non_linkedin_on_reopen(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=data['entries'], delivery_fixture=True)
    session.grant_all()
    path = tmp_path / 'social-fixture-session.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['items'][0].update(state='submitting', claim_mode='due', attempt='fixture-' + 'a' * 32)
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        FixtureJsonSession.open(tmp_path)


def test_delivery_submitting_can_be_marked_unknown_without_resend(tmp_path, monkeypatch):
    from scripts.social import json_session_fixture as module
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeLinkedInTransport(post_urn='urn:li:share:123')
    original = module._save
    def fail_receipt(directory, value):
        if value['items'][0]['state'] == 'accepted':
            raise OSError('fixture disk failure')
        return original(directory, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_save', fail_receipt)
        with pytest.raises(OSError):
            session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                      expected_digest=item['snapshot_sha256'], transport=fake)
    attempt = session.inspect()['items'][0]['attempt']
    session.mark_delivery_unknown(0, expected_key=item['key'], attempt=attempt)
    assert module.FixtureJsonSession.open(tmp_path).inspect()['items'][0]['state'] == 'unknown'
    with pytest.raises(ValueError):
        session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 1


def test_delivery_fixture_refuses_manual_claim_and_early_send(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeLinkedInTransport(post_urn='urn:li:share:123')
    with pytest.raises(ValueError):
        session.claim(0)
    with pytest.raises(ValueError):
        session.send_due_linkedin(0, now='2026-11-20T02:59:59Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 0
    assert session.inspect()['items'][0]['state'] == 'prepared'


def test_old_session_cannot_send_linkedin_with_fake(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'], entries=[entry])
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeLinkedInTransport(post_urn='urn:li:share:123')
    with pytest.raises(ValueError):
        session.send_due_linkedin(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 0


@pytest.mark.parametrize('filename,kind', [
    ('v1_facebook_to_telegram_simulation.json', 'text'),
    ('v1_to_telegram_image_simulation.json', 'image'),
    ('v1_to_telegram_video_simulation.json', 'video'),
])
def test_telegram_fake_delivery_persists_checked_receipt(tmp_path, monkeypatch, filename, kind):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2' / filename).read_text(encoding='utf-8'))
    entries = [entry for entry in data['entries'] if entry['platform'] == 'telegram']
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=entries, delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    body = item['snapshot']['candidate']['request']['body']
    response = {'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}}
    if kind == 'text':
        response['text'] = body['text']
    else:
        response['caption'] = body.get('caption', '')
        response['photo' if kind == 'image' else 'video'] = ([{'file_id': 'fixture-photo'}]
                                                              if kind == 'image' else {'file_id': 'fixture-video'})
    fake = FakeTelegramTransport(response=response)
    session.send_due_telegram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                              expected_digest=item['snapshot_sha256'], transport=fake)
    row = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert row['state'] == 'accepted'
    assert row['receipt']['chat_id'] == body['chat_id']
    assert row['receipt']['message_id'] == '404'
    assert row['receipt']['media_kind'] == (None if kind == 'text' else kind)
    assert row['receipt']['attempt'] == row['attempt']
    assert fake.calls == 1


@pytest.mark.parametrize('telegram_first', [True, False])
def test_linkedin_and_telegram_in_same_session_both_orders(tmp_path, monkeypatch, telegram_first):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[li, tg], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    linkedin = FakeLinkedInTransport(post_urn='urn:li:share:123')
    telegram = FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                               'text': 'Bài riêng cho Telegram'})
    for index in ([1, 0] if telegram_first else [0, 1]):
        method, fake = (session.send_due_linkedin, linkedin) if index == 0 else (session.send_due_telegram, telegram)
        method(index, now='2026-11-20T04:00:00Z', expected_key=items[index]['key'],
               expected_digest=items[index]['snapshot_sha256'], transport=fake)
    reopened = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [item['state'] for item in reopened] == ['accepted', 'accepted']
    assert reopened[0]['receipt']['post_urn'] == 'urn:li:share:123'
    assert reopened[1]['receipt']['message_id'] == '404'
    assert linkedin.calls == telegram.calls == 1


def test_telegram_duplicate_chat_and_message_becomes_unknown(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    first = next(entry for entry in data['entries'] if entry['platform'] == 'telegram')
    second = copy.deepcopy(first)
    second['args']['key']['occurrence_key'] = 'fixture-another-occurrence'
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[first, second], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    body = items[0]['snapshot']['candidate']['request']['body']
    response = {'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}, 'text': body['text']}
    for index in (0, 1):
        session.send_due_telegram(index, now='2026-11-20T04:00:00Z', expected_key=items[index]['key'],
                                  expected_digest=items[index]['snapshot_sha256'],
                                  transport=FakeTelegramTransport(response=response))
    rows = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['accepted', 'unknown']
    assert rows[1]['conflict_telegram'] == [body['chat_id'], '404']


@pytest.mark.parametrize('response', [None, {'message_id': 404, 'chat': {'id': -100999, 'type': 'channel'},
                                             'text': 'không khớp'}])
def test_telegram_missing_or_wrong_response_stays_unknown(tmp_path, response):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'telegram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeTelegramTransport(response=response)
    session.send_due_telegram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                              expected_digest=item['snapshot_sha256'], transport=fake)
    assert FixtureJsonSession.open(tmp_path).inspect()['items'][0]['state'] == 'unknown'
    with pytest.raises(ValueError):
        session.send_due_telegram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                  expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 1


def test_telegram_conflict_cannot_reference_other_chat_receipt(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    first = next(entry for entry in data['entries'] if entry['platform'] == 'telegram')
    second = copy.deepcopy(first)
    second['args']['chat_id'] = '-100999'
    second['args']['target']['chat_id'] = '-100999'
    second['args']['key']['destination_id'] = 'fixture-telegram-channel-999'
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[first, second], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    body = items[0]['snapshot']['candidate']['request']['body']
    response = {'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}, 'text': body['text']}
    session.send_due_telegram(0, now='2026-11-20T04:00:00Z', expected_key=items[0]['key'],
                              expected_digest=items[0]['snapshot_sha256'], transport=FakeTelegramTransport(response=response))
    session.send_due_telegram(1, now='2026-11-20T04:00:00Z', expected_key=items[1]['key'],
                              expected_digest=items[1]['snapshot_sha256'], transport=FakeTelegramTransport(response=None))
    session_file = tmp_path / 'social-fixture-session.json'
    raw = json.loads(session_file.read_text(encoding='utf-8'))
    raw['items'][1]['conflict_telegram'] = [body['chat_id'], '404']
    session_file.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        FixtureJsonSession.open(tmp_path)


def test_instagram_json_fixture_creates_once_and_retains_container(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                 expected_digest=item['snapshot_sha256'], transport=fake)
    row = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert row['state'] == 'submitting'
    assert row['instagram']['phase'] == 'waiting'
    assert row['instagram']['container_id'] == '101'
    assert fake.create_calls == 1


def test_instagram_json_waits_then_publishes_one_container(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                 expected_digest=item['snapshot_sha256'], transport=fake)
    attempt = session.inspect()['items'][0]['attempt']
    assert session.observe_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake) is False
    fake.status = 'FINISHED'
    assert session.observe_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake) is True
    session.publish_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake)
    row = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert row['state'] == 'accepted'
    assert row['instagram']['container_id'] == '101'
    assert row['instagram']['media_id'] == '202'
    assert fake.create_calls == fake.publish_calls == 1
    with pytest.raises(ValueError):
        session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                     expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.create_calls == 1


def test_instagram_new_fake_cannot_publish_old_container(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    original = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                 expected_digest=item['snapshot_sha256'], transport=original)
    attempt = session.inspect()['items'][0]['attempt']
    replacement = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    reopened = FixtureJsonSession.open(tmp_path)
    assert reopened.observe_instagram(0, expected_key=item['key'], attempt=attempt, transport=replacement)
    with pytest.raises(ValueError):
        reopened.publish_instagram(0, expected_key=item['key'], attempt=attempt, transport=replacement)
    assert replacement.publish_calls == 0


def test_instagram_expired_container_is_not_reused(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    first = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    second = copy.deepcopy(first)
    second['args']['key']['occurrence_key'] = 'fixture-second'
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[first, second], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    fake = FakeInstagramTransport(container_id='101', status='EXPIRED', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=items[0]['key'],
                                 expected_digest=items[0]['snapshot_sha256'], transport=fake)
    attempt = session.inspect()['items'][0]['attempt']
    assert not session.observe_instagram(0, expected_key=items[0]['key'], attempt=attempt, transport=fake)
    session.create_due_instagram(1, now='2026-11-20T04:00:00Z', expected_key=items[1]['key'],
                                 expected_digest=items[1]['snapshot_sha256'], transport=fake)
    rows = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['unknown', 'unknown']
    assert rows[0]['instagram']['container_id'] == rows[1]['instagram']['conflict_container'] == '101'


@pytest.mark.parametrize('phase', ['creating', 'publishing'])
def test_instagram_abandoned_write_can_only_mark_unknown(tmp_path, monkeypatch, phase):
    from scripts.social import json_session_fixture as module
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    if phase == 'publishing':
        session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                     expected_digest=item['snapshot_sha256'], transport=fake)
        attempt = session.inspect()['items'][0]['attempt']
        session.observe_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake)
    original_save = module._save
    def fail_final(directory, value):
        if value['items'][0]['instagram']['phase'] == ('waiting' if phase == 'creating' else 'accepted'):
            raise OSError('fixture write failure')
        return original_save(directory, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_save', fail_final)
        with pytest.raises(OSError):
            if phase == 'creating':
                session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                             expected_digest=item['snapshot_sha256'], transport=fake)
            else:
                session.publish_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake)
    reopened = module.FixtureJsonSession.open(tmp_path)
    attempt = reopened.inspect()['items'][0]['attempt']
    reopened.mark_instagram_unknown(0, expected_key=item['key'], attempt=attempt, expected_phase=phase)
    assert reopened.inspect()['items'][0]['state'] == 'unknown'
    assert fake.create_calls == 1 and fake.publish_calls == (1 if phase == 'publishing' else 0)


def test_three_channel_json_fixture_continues_after_instagram_unknown(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    ig = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[ig, li, tg], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    instagram = FakeInstagramTransport(container_id='101', status='FINISHED', media_id=None)
    linkedin = FakeLinkedInTransport(post_urn='urn:li:share:303')
    telegram = FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                               'text': 'Bài riêng cho Telegram'})
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=items[0]['key'],
                                 expected_digest=items[0]['snapshot_sha256'], transport=instagram)
    attempt = session.inspect()['items'][0]['attempt']
    session.observe_instagram(0, expected_key=items[0]['key'], attempt=attempt, transport=instagram)
    session.publish_instagram(0, expected_key=items[0]['key'], attempt=attempt, transport=instagram)
    session.send_due_linkedin(1, now='2026-11-20T04:00:00Z', expected_key=items[1]['key'],
                              expected_digest=items[1]['snapshot_sha256'], transport=linkedin)
    session.send_due_telegram(2, now='2026-11-20T04:00:00Z', expected_key=items[2]['key'],
                              expected_digest=items[2]['snapshot_sha256'], transport=telegram)
    rows = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['unknown', 'accepted', 'accepted']
    assert rows[0]['instagram']['container_id'] == '101'
    assert rows[1]['receipt']['post_urn'] == 'urn:li:share:303'
    assert rows[2]['receipt']['message_id'] == '404'
    assert instagram.create_calls == instagram.publish_calls == linkedin.calls == telegram.calls == 1


def test_instagram_two_workers_publish_at_most_once(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=item['key'],
                                 expected_digest=item['snapshot_sha256'], transport=fake)
    attempt = session.inspect()['items'][0]['attempt']
    session.observe_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake)
    barrier = threading.Barrier(2)
    def publish():
        barrier.wait(timeout=5)
        try:
            FixtureJsonSession.open(tmp_path).publish_instagram(0, expected_key=item['key'], attempt=attempt, transport=fake)
            return 'sent'
        except (ValueError, OSError):
            return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(results) == ['refused', 'sent']
    assert fake.publish_calls == 1
    assert FixtureJsonSession.open(tmp_path).inspect()['items'][0]['state'] == 'accepted'


def test_instagram_duplicate_media_receipt_stays_unknown(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    first = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    second = copy.deepcopy(first)
    second['args']['key']['occurrence_key'] = 'fixture-second'
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[first, second], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    for index, container in enumerate(('101', '102')):
        fake = FakeInstagramTransport(container_id=container, status='FINISHED', media_id='202')
        session.create_due_instagram(index, now='2026-11-20T04:00:00Z', expected_key=items[index]['key'],
                                     expected_digest=items[index]['snapshot_sha256'], transport=fake)
        attempt = session.inspect()['items'][index]['attempt']
        assert session.observe_instagram(index, expected_key=items[index]['key'], attempt=attempt, transport=fake)
        session.publish_instagram(index, expected_key=items[index]['key'], attempt=attempt, transport=fake)
    rows = FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['accepted', 'unknown']
    assert rows[0]['instagram']['media_id'] == rows[1]['instagram']['conflict_media'] == '202'


@pytest.mark.parametrize('platform', ['linkedin', 'telegram', 'instagram'])
def test_two_processes_claim_same_destination_at_most_once(tmp_path, platform):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    if platform == 'telegram':
        path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
        data = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in data['entries'] if entry['platform'] == platform)
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    code = '''
import json, socket, sqlite3, sys
from pathlib import Path
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
from scripts.social.telegram_fixture_transport import FakeTelegramTransport
from scripts.social.instagram_fixture_transport import FakeInstagramTransport
def forbidden(*args, **kwargs):
    raise AssertionError('network or SQLite')
socket.socket = sqlite3.connect = forbidden
sys.stdin.readline()
platform = sys.argv[2]
fake = None
try:
    s = FixtureJsonSession.open(Path(sys.argv[1]))
    row = s.inspect()['items'][0]
    if platform == 'linkedin':
        fake = FakeLinkedInTransport(post_urn='urn:li:share:123')
        method = s.send_due_linkedin
    elif platform == 'telegram':
        body = row['snapshot']['candidate']['request']['body']
        fake = FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}, 'text': body['text']})
        method = s.send_due_telegram
    else:
        fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
        method = s.create_due_instagram
    method(0, now='2026-11-20T04:00:00Z', expected_key=row['key'], expected_digest=row['snapshot_sha256'], transport=fake)
    outcome = 'sent'
except (OSError, ValueError):
    outcome = 'refused'
    error = sys.exc_info()[1]
    if isinstance(error, OSError) and error.errno not in (11, 13, 35):
        raise
    if isinstance(error, ValueError) and str(error) not in ('fixture send refused', 'fixture create refused'):
        raise
calls = 0 if fake is None else (fake.create_calls if platform == 'instagram' else fake.calls)
print(json.dumps({'outcome': outcome, 'calls': calls}), flush=True)
'''
    processes = [subprocess.Popen([sys.executable, '-u', '-c', code, str(tmp_path), platform],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding='utf-8') for _ in range(2)]
    barrier = threading.Barrier(2)
    def release(process):
        barrier.wait(timeout=10)
        return process.communicate(input='go\n', timeout=20)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(release, processes))
        assert all(process.returncode == 0 for process in processes), results
        outputs = [json.loads(stdout) for stdout, _ in results]
        assert sorted(output['outcome'] for output in outputs) == ['refused', 'sent']
        assert sum(output['calls'] for output in outputs) == 1
        state = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
        assert state['state'] == ('submitting' if platform == 'instagram' else 'accepted')
        if platform == 'instagram':
            assert state['instagram']['phase'] == 'waiting'
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


@pytest.mark.parametrize('platform', ['linkedin', 'telegram'])
def test_process_dies_after_fake_received_before_receipt(tmp_path, platform):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    if platform == 'telegram':
        path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
        data = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in data['entries'] if entry['platform'] == platform)
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    key = session.inspect()['items'][0]['key']
    code = '''
import json, os, socket, sqlite3, sys
from pathlib import Path
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
from scripts.social.telegram_fixture_transport import FakeTelegramTransport
def forbidden(*args, **kwargs):
    raise AssertionError('network or SQLite')
socket.socket = sqlite3.connect = forbidden
s = FixtureJsonSession.open(Path(sys.argv[1]))
row = s.inspect()['items'][0]
if sys.argv[2] == 'linkedin':
    cls = FakeLinkedInTransport
    fake = cls(post_urn='urn:li:share:123')
    method = s.send_due_linkedin
else:
    cls = FakeTelegramTransport
    body = row['snapshot']['candidate']['request']['body']
    fake = cls(response={'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}, 'text': body['text']})
    method = s.send_due_telegram
original = cls._send
def stop_after_fake(self, candidate, attempt, *rest):
    original(self, candidate, attempt, *rest)
    print(json.dumps({'attempt': attempt, 'calls': self.calls}), flush=True)
    os._exit(41)
cls._send = stop_after_fake
method(0, now='2026-11-20T04:00:00Z', expected_key=row['key'], expected_digest=row['snapshot_sha256'], transport=fake)
raise AssertionError('expected crash')
'''
    result = subprocess.run([sys.executable, '-u', '-c', code, str(tmp_path), platform],
                            text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 41, result.stderr
    event = json.loads(result.stdout)
    assert event['calls'] == 1
    reopened = FixtureJsonSession.open(tmp_path)
    item = reopened.inspect()['items'][0]
    assert item['state'] == 'submitting' and item['attempt'] == event['attempt']
    fake = (FakeLinkedInTransport(post_urn='urn:li:share:123') if platform == 'linkedin'
            else FakeTelegramTransport(response=None))
    method = reopened.send_due_linkedin if platform == 'linkedin' else reopened.send_due_telegram
    with pytest.raises(ValueError):
        method(0, now='2026-11-20T04:00:00Z', expected_key=key,
               expected_digest=item['snapshot_sha256'], transport=fake)
    assert fake.calls == 0
    with pytest.raises(ValueError):
        reopened.mark_delivery_unknown(0, expected_key=key, attempt='fixture-' + '0' * 32)
    reopened.mark_delivery_unknown(0, expected_key=key, attempt=event['attempt'])
    assert FixtureJsonSession.open(tmp_path).inspect()['items'][0]['state'] == 'unknown'


@pytest.mark.parametrize('phase', ['creating', 'publishing'])
def test_instagram_process_dies_after_fake_received(tmp_path, phase):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    code = '''
import json, os, socket, sqlite3, sys
from pathlib import Path
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.instagram_fixture_transport import FakeInstagramTransport
def forbidden(*args, **kwargs):
    raise AssertionError('network or SQLite')
socket.socket = sqlite3.connect = forbidden
s = FixtureJsonSession.open(Path(sys.argv[1]))
row = s.inspect()['items'][0]
fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
name = '_create' if sys.argv[2] == 'creating' else '_publish'
original = getattr(FakeInstagramTransport, name)
def stop_after_fake(self, candidate, attempt):
    original(self, candidate, attempt)
    print(json.dumps({'attempt': attempt, 'create_calls': self.create_calls, 'publish_calls': self.publish_calls}), flush=True)
    os._exit(42)
setattr(FakeInstagramTransport, name, stop_after_fake)
s.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=row['key'], expected_digest=row['snapshot_sha256'], transport=fake)
attempt = s.inspect()['items'][0]['attempt']
s.observe_instagram(0, expected_key=row['key'], attempt=attempt, transport=fake)
s.publish_instagram(0, expected_key=row['key'], attempt=attempt, transport=fake)
raise AssertionError('expected crash')
'''
    result = subprocess.run([sys.executable, '-u', '-c', code, str(tmp_path), phase],
                            text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 42, result.stderr
    event = json.loads(result.stdout)
    assert event['create_calls'] == 1 and event['publish_calls'] == (phase == 'publishing')
    reopened = FixtureJsonSession.open(tmp_path)
    row = reopened.inspect()['items'][0]
    assert row['state'] == 'submitting' and row['instagram']['phase'] == phase
    assert row['attempt'] == event['attempt']
    new_fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    with pytest.raises(ValueError):
        reopened.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=row['key'],
                                      expected_digest=row['snapshot_sha256'], transport=new_fake)
    if phase == 'publishing':
        with pytest.raises(ValueError):
            reopened.publish_instagram(0, expected_key=row['key'], attempt=event['attempt'], transport=new_fake)
        assert new_fake.publish_calls == 0
    with pytest.raises(ValueError):
        reopened.mark_instagram_unknown(0, expected_key=row['key'], attempt=event['attempt'],
                                         expected_phase='publishing' if phase == 'creating' else 'creating')
    reopened.mark_instagram_unknown(0, expected_key=row['key'], attempt=event['attempt'], expected_phase=phase)
    final = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
    assert final['state'] == 'unknown' and final['instagram']['phase'] == 'unknown'
    assert final['instagram']['container_id'] == ('101' if phase == 'publishing' else None)
    assert new_fake.create_calls == new_fake.publish_calls == 0


@pytest.mark.parametrize('platform', ['linkedin', 'telegram'])
def test_process_holds_writer_lock_during_fake_send(tmp_path, platform):
    from scripts.social.json_session_fixture import FixtureJsonSession

    data = sample()
    if platform == 'telegram':
        path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_telegram_simulation.json'
        data = json.loads(path.read_text(encoding='utf-8'))
    entry = next(entry for entry in data['entries'] if entry['platform'] == platform)
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    code = '''
import json, socket, sqlite3, sys
from pathlib import Path
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
from scripts.social.telegram_fixture_transport import FakeTelegramTransport
def forbidden(*args, **kwargs):
    raise AssertionError('network or SQLite')
socket.socket = sqlite3.connect = forbidden
s = FixtureJsonSession.open(Path(sys.argv[1]))
row = s.inspect()['items'][0]
if sys.argv[2] == 'linkedin':
    cls = FakeLinkedInTransport
    fake = cls(post_urn='urn:li:share:123')
    method = s.send_due_linkedin
else:
    cls = FakeTelegramTransport
    body = row['snapshot']['candidate']['request']['body']
    fake = cls(response={'message_id': 404, 'chat': {'id': int(body['chat_id']), 'type': 'channel'}, 'text': body['text']})
    method = s.send_due_telegram
original = cls._send
def wait_in_fake(self, candidate, attempt, *rest):
    response = original(self, candidate, attempt, *rest)
    print(json.dumps({'attempt': attempt, 'calls': self.calls}), flush=True)
    sys.stdin.readline()
    return response
cls._send = wait_in_fake
method(0, now='2026-11-20T04:00:00Z', expected_key=row['key'], expected_digest=row['snapshot_sha256'], transport=fake)
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code, str(tmp_path), platform], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    messages = queue.Queue()
    reader = threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        event = json.loads(messages.get(timeout=20))
        assert event['calls'] == 1
        with pytest.raises(OSError) as error:
            FixtureJsonSession.open(tmp_path)
        assert error.value.errno in (11, 13, 35)
        process.stdin.write('continue\n')
        process.stdin.flush()
        _, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        row = FixtureJsonSession.open(tmp_path).inspect()['items'][0]
        assert row['state'] == 'accepted' and row['attempt'] == event['attempt']
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        reader.join(timeout=5)


def test_json_batch_dispatch_continues_after_unknown_and_does_not_resend(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    ig = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: pytest.fail('SQLite'))
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[ig, li, tg], delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    fakes = [FakeInstagramTransport(container_id='101', status='FINISHED', media_id=None),
             FakeLinkedInTransport(post_urn='urn:li:share:303'),
             FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                             'text': 'Bài riêng cho Telegram'})]
    jobs = [{'index': i, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fakes[i]}
            for i, row in enumerate(items)]
    result = dispatch_fixture_batch(session, jobs=jobs, now='2026-11-20T04:00:00Z')
    assert [item['state'] for item in result['items']] == ['unknown', 'accepted', 'accepted']
    assert fakes[0].publish_calls == fakes[1].calls == fakes[2].calls == 1
    repeat = dispatch_fixture_batch(session, jobs=jobs, now='2026-11-20T04:00:00Z')
    assert [item['outcome'] for item in repeat['items']] == ['unknown', 'already_accepted', 'already_accepted']
    assert fakes[0].publish_calls == fakes[1].calls == fakes[2].calls == 1


@pytest.mark.parametrize('change', ['type', 'key', 'digest'])
def test_json_batch_rejects_invalid_last_job_before_any_send(tmp_path, change):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport

    data = sample()
    entries = [entry for entry in data['entries'] if entry['platform'] in ('instagram', 'linkedin')]
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=entries, delivery_fixture=True)
    session.grant_all()
    items = session.inspect()['items']
    ig = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    li = FakeLinkedInTransport(post_urn='urn:li:share:303')
    jobs = [{'index': i, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fake}
            for i, (row, fake) in enumerate(zip(items, (ig, li)))]
    if change == 'type':
        jobs[-1]['transport'] = ig
    elif change == 'key':
        jobs[-1]['key']['occurrence_key'] = 'fixture-wrong'
    else:
        jobs[-1]['digest'] = '0' * 64
    with pytest.raises(ValueError):
        dispatch_fixture_batch(session, jobs=jobs, now='2026-11-20T04:00:00Z')
    assert ig.create_calls == ig.publish_calls == li.calls == 0


def test_json_batch_resumes_waiting_without_recreating_container(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
    job = {'index': 0, 'key': item['key'], 'digest': item['snapshot_sha256'], 'transport': fake}
    first = dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')
    assert first['items'][0]['outcome'] == 'awaiting_observation'
    fake.status = 'FINISHED'
    second = dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')
    assert second['items'][0]['state'] == 'accepted'
    assert fake.create_calls == fake.publish_calls == 1


def test_json_batch_checks_all_session_schemas_before_first_send(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'], entries=[li, tg],
                              delivery_fixture=True)
    file = tmp_path / 'social-fixture-session.json'
    data_file = json.loads(file.read_text(encoding='utf-8'))
    data_file['schema'] = 'social-json-fixture/2'
    for item in data_file['items']:
        del item['conflict_telegram']
    file.write_text(json.dumps(data_file), encoding='utf-8')
    session = FixtureJsonSession.open(tmp_path)
    session.grant_all()
    rows = session.inspect()['items']
    fakes = [FakeLinkedInTransport(post_urn='urn:li:share:303'), FakeTelegramTransport(response=None)]
    jobs = [{'index': i, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fakes[i]}
            for i, row in enumerate(rows)]
    with pytest.raises(ValueError):
        dispatch_fixture_batch(session, jobs=jobs, now='2026-11-20T04:00:00Z')
    assert fakes[0].calls == fakes[1].calls == 0


def test_json_batch_does_not_claim_credit_for_other_worker_publish(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    row = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    original = session.observe_instagram
    def observe_then_other_publishes(index, *, expected_key, attempt, transport):
        ready = original(index, expected_key=expected_key, attempt=attempt, transport=transport)
        FixtureJsonSession.open(tmp_path).publish_instagram(index, expected_key=expected_key,
                                                            attempt=attempt, transport=transport)
        return ready
    monkeypatch.setattr(session, 'observe_instagram', observe_then_other_publishes)
    job = {'index': 0, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fake}
    result = dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')
    assert result['items'][0]['outcome'] == 'already_accepted'
    assert fake.publish_calls == 1


def test_json_batch_propagates_write_failure_and_stops_later_jobs(tmp_path, monkeypatch):
    from scripts.social import json_session_fixture as module
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport
    from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
    from scripts.social.telegram_fixture_transport import FakeTelegramTransport

    data = sample()
    li = next(entry for entry in data['entries'] if entry['platform'] == 'linkedin')
    ig = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    key = dict(li['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    tg = {'platform': 'telegram', 'args': {'key': key, 'target': {'chat_id': '-100123', 'purpose': 'publish'},
          'chat_id': '-100123', 'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Bài riêng cho Telegram'}}
    session = module.FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                               entries=[li, tg, ig], delivery_fixture=True)
    session.grant_all()
    rows = session.inspect()['items']
    fakes = [FakeLinkedInTransport(post_urn='urn:li:share:303'),
             FakeTelegramTransport(response={'message_id': 404, 'chat': {'id': -100123, 'type': 'channel'},
                                             'text': 'Bài riêng cho Telegram'}),
             FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')]
    jobs = [{'index': i, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fakes[i]}
            for i, row in enumerate(rows)]
    original = module._save
    def fail_telegram_receipt(directory, value):
        if value['items'][1]['state'] == 'accepted':
            raise OSError('fixture disk failure')
        return original(directory, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, '_save', fail_telegram_receipt)
        with pytest.raises(OSError):
            dispatch_fixture_batch(session, jobs=jobs, now='2026-11-20T04:00:00Z')
    rows = module.FixtureJsonSession.open(tmp_path).inspect()['items']
    assert [row['state'] for row in rows] == ['accepted', 'submitting', 'prepared']
    assert rows[0]['receipt']['post_urn'] == 'urn:li:share:303'
    assert fakes[0].calls == fakes[1].calls == 1 and fakes[2].create_calls == 0


def test_json_batch_reports_missing_instagram_fake_binding(tmp_path):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    item = session.inspect()['items'][0]
    old = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
    job = {'index': 0, 'key': item['key'], 'digest': item['snapshot_sha256'], 'transport': old}
    assert dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')['items'][0]['outcome'] == 'awaiting_observation'
    new = FakeInstagramTransport(container_id='101', status='FINISHED', media_id='202')
    job['transport'] = new
    result = dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')
    assert result['items'][0]['outcome'] == 'requires_original_fake'
    assert new.create_calls == new.publish_calls == 0


def test_json_batch_reports_recovery_if_other_worker_stops_publishing(tmp_path, monkeypatch):
    from scripts.social.json_session_fixture import FixtureJsonSession
    from scripts.social.json_session_dispatch import dispatch_fixture_batch
    from scripts.social.instagram_fixture_transport import FakeInstagramTransport

    data = sample()
    entry = next(entry for entry in data['entries'] if entry['platform'] == 'instagram')
    session = FixtureJsonSession.create(tmp_path, source=data['source'], publication=data['publication'],
                                        entries=[entry], delivery_fixture=True)
    session.grant_all()
    row = session.inspect()['items'][0]
    fake = FakeInstagramTransport(container_id='101', status='IN_PROGRESS', media_id='202')
    session.create_due_instagram(0, now='2026-11-20T04:00:00Z', expected_key=row['key'],
                                 expected_digest=row['snapshot_sha256'], transport=fake)
    original = session.inspect
    reads = 0
    def inspect_then_worker_stops():
        nonlocal reads
        reads += 1
        if reads == 4:
            current = original()['items'][0]
            fake.status = 'FINISHED'
            FixtureJsonSession.open(tmp_path).observe_instagram(0, expected_key=row['key'],
                                                                 attempt=current['attempt'], transport=fake)
            with monkeypatch.context() as patch:
                def stopped(*args):
                    raise RuntimeError('simulated worker stop')
                patch.setattr(fake, '_publish', stopped)
                with pytest.raises(RuntimeError):
                    FixtureJsonSession.open(tmp_path).publish_instagram(0, expected_key=row['key'],
                                                                        attempt=current['attempt'], transport=fake)
        return original()
    monkeypatch.setattr(session, 'inspect', inspect_then_worker_stops)
    job = {'index': 0, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': fake}
    result = dispatch_fixture_batch(session, jobs=[job], now='2026-11-20T04:00:00Z')
    assert result['items'][0]['outcome'] == 'requires_recovery'
    assert session.inspect()['items'][0]['instagram']['phase'] == 'publishing'
