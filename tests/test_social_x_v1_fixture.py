"""X text previews and V1 binding use synthetic data only."""
import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def sample():
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_linkedin_simulation.json').read_text(encoding='utf-8'))
    key = dict(data['entries'][2]['args']['key'], platform='x', account_id='fixture-x-account-123',
               destination_id='fixture-x-profile-123')
    data['entries'][2] = {'platform': 'x', 'args': {'key': key, 'user_id': '123',
        'target': {'user_id': '123'}, 'scheduled_at': '2026-11-20T03:00:00Z',
        'adapted_text': 'Góc nhìn mới cho X: tiếng Việt 👩‍💻 https://example.com'}}
    return data


def test_x_preview_marks_weighted_length_unverified():
    try:
        module = importlib.import_module('scripts.social.channels.x.direct')
    except ModuleNotFoundError:
        pytest.fail('X native preview is missing')
    result = module.preview_post(text='Xin chào 👩‍💻\r\nhttps://example.com')
    assert result['request']['body'] == {'text': 'Xin chào 👩‍💻\nhttps://example.com'}
    assert 'x_weighted_length_unchecked' in result['warnings']


def test_x_batch_binds_receipt_to_attempt_and_user():
    data = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        assert row['grant_version'] is None
        ledger.approve(ids[2], expected_version=1)
        attempt = ledger.claim_due(ids[2], expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(ids[2], attempt=attempt, destination=row['destination_id'], remote_id='fixture-fake')
        with pytest.raises(ValueError):
            ledger.finish_x_fixture(ids[2], attempt=attempt, user_id='999', post_id='45')
        ledger.finish_x_fixture(ids[2], attempt=attempt, user_id='123', post_id='45')
        assert ledger.get(ids[2])['state'] == 'accepted'


def test_bad_x_destination_rolls_back_entire_batch():
    data = sample()
    data['entries'][2]['args']['target']['user_id'] = '999'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


@pytest.mark.parametrize('text', ['', '   ', '\x00', '\ud800', 'a' * 32001])
def test_invalid_x_text_rejected(text):
    from scripts.social.channels.x.direct import preview_post
    with pytest.raises(ValueError):
        preview_post(text=text)


def test_x_native_schema_cannot_be_relabelled_as_another_platform():
    data = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        payload = json.loads(ledger.get(ids[2])['snapshot_json'])['payload']
        key = dict(data['entries'][2]['args']['key'], platform='linkedin', account_id='fixture-other',
                   destination_id='fixture-other-destination')
        with pytest.raises(ValueError):
            ledger.prepare(key, payload)


def test_duplicate_x_receipt_is_unknown_across_profiles():
    data = sample()
    other = json.loads(json.dumps(data['entries'][2]))
    args = other['args']
    args['key']['account_id'] = 'fixture-x-account-456'
    args['key']['destination_id'] = 'fixture-x-profile-456'
    args['user_id'] = '456'
    args['target']['user_id'] = '456'
    data['entries'].append(other)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        for intent, user in ((ids[2], '123'), (ids[3], '456')):
            ledger.approve(intent, expected_version=1)
            attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
            if user == '123':
                ledger.finish_x_fixture(intent, attempt=attempt, user_id=user, post_id='45')
            else:
                with pytest.raises(ValueError):
                    ledger.finish_x_fixture(intent, attempt=attempt, user_id=user, post_id='45')
                assert ledger.get(intent)['state'] == 'unknown'


def test_x_capability_describes_native_fixture_only():
    from scripts.social.capabilities import capabilities
    result = capabilities(platform='x', destination='account', action='post_text')
    assert result['preview_schema'] == 'x_native'
    assert result['live_enabled'] is False


@pytest.mark.parametrize('text', ['TODO {{name}}', 'abc\u202edef', 'abc\u061cdef', 'abc\u200edef', 'abc\u200fdef'])
def test_x_rejects_unfilled_or_misleading_display_text(text):
    from scripts.social.channels.x.direct import preview_post
    with pytest.raises(ValueError):
        preview_post(text=text)


def test_generic_x_receipt_cannot_claim_native_receipt_namespace():
    data = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        key = dict(data['entries'][2]['args']['key'], account_id='fixture-other', destination_id='fixture-other')
        intent = ledger.prepare(key, {'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(intent, expected_version=1)
        attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(intent, attempt=attempt, destination='fixture-other', remote_id='fixture-x-post-45')
        ledger.approve(ids[2], expected_version=1)
        native_attempt = ledger.claim_due(ids[2], expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_x_fixture(ids[2], attempt=native_attempt, user_id='123', post_id='45')
        with pytest.raises(ValueError):
            ledger.finish(intent, attempt=attempt, destination='fixture-other', remote_id='fixture-x-post-45')


def test_x_cli_produces_native_preview_from_synthetic_text():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-x'],
                            input=json.dumps({'text': 'Góc nhìn cho X 👩‍💻'}, ensure_ascii=False),
                            text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 0
    candidate = json.loads(result.stdout)
    assert candidate['request']['path'] == '/2/tweets'
    assert candidate['request']['body']['text'] == 'Góc nhìn cho X 👩‍💻'
    assert 'x_weighted_length_unchecked' in candidate['warnings']


def test_x_cli_rejects_unsupported_reply_field():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-x'],
                            input=json.dumps({'text': 'Bài giả', 'reply': {'in_reply_to_tweet_id': '1'}}),
                            text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 2
    assert result.stdout == ''
