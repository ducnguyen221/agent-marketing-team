"""Synthetic Telegram channel publishing is separate from approval bots."""
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
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_facebook_to_discord_simulation.json').read_text(encoding='utf-8'))
    key = dict(data['entries'][2]['args']['key'], platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    data['entries'][2] = {'platform': 'telegram', 'args': {'key': key, 'chat_id': '-100123',
        'target': {'chat_id': '-100123', 'purpose': 'publish'}, 'scheduled_at': '2026-11-20T03:00:00Z',
        'adapted_text': 'Bản tin riêng cho Telegram 👋'}}
    return data


def test_native_text_preview_has_no_credential_or_markup_mode():
    try:
        direct = importlib.import_module('scripts.social.channels.telegram.direct')
    except ModuleNotFoundError:
        pytest.fail('Telegram native preview is missing')
    result = direct.preview_message(chat_id='-100123', text='Bản tin <test>')
    assert result['request']['method'] == 'sendMessage'
    assert result['request']['body'] == {'chat_id': '-100123', 'text': 'Bản tin <test>'}
    assert result['preview_only'] is True


def test_v1_telegram_binding_requires_separate_grant_and_receipt():
    data = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])[2]
        assert ledger.get(intent)['grant_version'] is None
        ledger.approve(intent, expected_version=1)
        attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(intent, attempt=attempt, destination='fixture-telegram-channel-123', remote_id='fixture-fake')
        with pytest.raises(ValueError):
            ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id='-100999', chat_type='channel', message_id='44')
        ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id='-100123', chat_type='channel', message_id='44')
        assert ledger.get(intent)['state'] == 'accepted'


def test_approval_bot_is_rejected_and_batch_remains_empty():
    data = sample()
    data['entries'][2]['args']['target']['purpose'] = 'approval'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_telegram_normalizes_windows_newlines():
    from scripts.social.channels.telegram.direct import preview_message
    assert preview_message(chat_id='-100123', text='Một\r\nHai')['request']['body']['text'] == 'Một\nHai'


def test_telegram_message_ids_are_scoped_to_channel():
    data = sample()
    other = json.loads(json.dumps(data['entries'][2]))
    other['args']['key']['account_id'] = 'fixture-telegram-publish-bot-other'
    other['args']['key']['destination_id'] = 'fixture-telegram-channel-456'
    other['args']['chat_id'] = '-100456'
    other['args']['target']['chat_id'] = '-100456'
    data['entries'].append(other)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        for intent, chat in ((ids[2], '-100123'), (ids[3], '-100456')):
            ledger.approve(intent, expected_version=1)
            attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
            with pytest.raises(ValueError):
                ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id=chat, chat_type='private', message_id='44')
            ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id=chat, chat_type='channel', message_id='44')
            assert ledger.get(intent)['state'] == 'accepted'


def test_telegram_schema_cannot_be_relabelled_as_another_platform():
    data = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])[2]
        payload = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        key = dict(data['entries'][2]['args']['key'], platform='linkedin', account_id='fixture-other', destination_id='fixture-other')
        with pytest.raises(ValueError): ledger.prepare(key, payload)


def test_telegram_capability_and_cli_are_preview_only():
    from scripts.social.capabilities import capabilities
    result = capabilities(platform='telegram', destination='channel', action='post_text')
    assert result['preview_schema'] == 'telegram_native' and result['live_enabled'] is False
    process = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-telegram'],
                             input=json.dumps({'chat_id': '-100123', 'text': 'Tin giả'}), text=True,
                             encoding='utf-8', capture_output=True, check=False)
    assert process.returncode == 0
    assert json.loads(process.stdout)['request']['method'] == 'sendMessage'


def test_chat_id_outside_52_bit_range_is_rejected():
    from scripts.social.channels.telegram.direct import preview_message
    with pytest.raises(ValueError): preview_message(chat_id='-10099999999999999999999', text='Bản tin giả')


def test_duplicate_message_id_same_chat_is_unknown():
    data = sample()
    other = json.loads(json.dumps(data['entries'][2]))
    other['args']['key']['account_id'] = 'fixture-telegram-publish-bot-other'
    other['args']['key']['occurrence_key'] = 'fixture-other-slot'
    data['entries'].append(other)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        for index in (2, 3):
            ledger.approve(ids[index], expected_version=1)
            attempt = ledger.claim_due(ids[index], expected_version=1, now='2026-11-20T03:00:00Z')
            if index == 2:
                ledger.finish_telegram_fixture(ids[index], attempt=attempt, chat_id='-100123', chat_type='channel', message_id='44')
            else:
                with pytest.raises(ValueError):
                    ledger.finish_telegram_fixture(ids[index], attempt=attempt, chat_id='-100123', chat_type='channel', message_id='44')
        assert ledger.get(ids[2])['state'] == 'accepted'
        assert ledger.get(ids[3])['state'] == 'unknown'
        assert ledger.get(ids[3])['conflict_remote_id'] == 'fixture-telegram-message-123-44'
