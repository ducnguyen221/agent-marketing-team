"""Offline Discord candidate and V1 source binding; never sends a message."""
import importlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def data():
    result = json.loads((Path(__file__).resolve().parents[1] /
                         'fixtures/social_v2/v1_facebook_to_linkedin_simulation.json').read_text(encoding='utf-8'))
    key = dict(result['entries'][2]['args']['key'], platform='discord', account_id='fixture-discord-bot-demo',
               destination_id='fixture-discord-channel-456')
    result['entries'][2] = {'platform': 'discord', 'args': {'key': key, 'guild_id': '123', 'channel_id': '456',
        'target': {'guild_id': '123', 'channel_id': '456'},
        'scheduled_at': '2026-11-20T03:00:00Z', 'adapted_text': 'Chào cộng đồng @everyone <@123>!'}}
    return result


def test_discord_preview_never_resolves_mentions():
    module = importlib.import_module('scripts.social.channels.discord.direct')
    candidate = module.preview_message(channel_id='456', text='Chào @everyone <@123> <@&456>')
    assert candidate['request']['body']['allowed_mentions'] == {'parse': []}
    assert candidate['request']['body']['content'] == 'Chào @everyone <@123> <@&456>'


def test_discord_v1_fixture_binds_destination_and_receipt():
    sample = data()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=sample['source'], publication=sample['publication'], entries=sample['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        assert payload['candidate']['request']['body']['allowed_mentions'] == {'parse': []}
        ledger.approve(ids[2], expected_version=1)
        attempt = ledger.claim_due(ids[2], expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(ids[2], attempt=attempt, destination=row['destination_id'], remote_id='fixture-fake')
        with pytest.raises(ValueError):
            ledger.finish_discord_fixture(ids[2], attempt=attempt, channel_id='999', message_id='12345')
        assert ledger.get(ids[2])['state'] == 'submitting'
        ledger.finish_discord_fixture(ids[2], attempt=attempt, channel_id='456', message_id='12345')
        assert ledger.get(ids[2])['state'] == 'accepted'


def test_discord_v1_bad_guild_rolls_back_entire_batch():
    sample = data()
    sample['entries'][2]['args']['guild_id'] = '999'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=sample['source'], publication=sample['publication'], entries=sample['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_discord_reserved_destination_cannot_be_relabelled_as_another_platform():
    sample = data()
    original = sample['entries'][2]['args']['key']
    forged = dict(original, platform='x')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            ledger.prepare(forged, {'scheduled_at': '2026-11-20T03:00:00Z'})


def test_discord_native_schema_cannot_bypass_validation_with_other_namespaces():
    sample = data()
    key = dict(sample['entries'][2]['args']['key'], account_id='fixture-other', destination_id='fixture-other')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            ledger.prepare(key, {'fixture_schema': 'discord-v1-facebook-text/1', 'scheduled_at': '2026-11-20T03:00:00Z'})


def test_discord_grant_is_per_destination_and_receipt_channel_is_checked():
    sample = data()
    first = sample['entries'][2]
    import copy
    second = copy.deepcopy(first)
    second['args']['channel_id'] = '789'
    second['args']['target']['channel_id'] = '789'
    second['args']['key']['destination_id'] = 'fixture-discord-channel-789'
    sample['entries'].append(second)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=sample['source'], publication=sample['publication'], entries=sample['entries'])
        ledger.approve(ids[2], expected_version=1)
        due = ledger.scan_due(now='2026-11-20T03:00:00Z')['due']
        assert ids[2] in due and ids[3] not in due
        attempt = ledger.claim_due(ids[2], expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish_discord_fixture(ids[2], attempt=attempt, channel_id='789', message_id='100')
        assert ledger.get(ids[2])['state'] == 'submitting'
        assert ledger.get(ids[3])['state'] == 'prepared'


def test_discord_capability_and_cli_use_native_preview():
    from scripts.social.capabilities import capabilities
    capability = capabilities(platform='discord', destination='channel', action='post_text')
    assert capability['preview_schema'] == 'discord_native' and capability['live_enabled'] is False
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-discord'],
        input=json.dumps({'channel_id': '456', 'text': '@everyone fixture'}), text=True,
        encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['request']['body']['allowed_mentions'] == {'parse': []}


def test_packaged_discord_example_runs_through_cli():
    import subprocess
    import sys
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_discord_simulation.json'
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-v1-batch'],
        input=path.read_text(encoding='utf-8'), text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['items'][2]['platform'] == 'discord'


def test_discord_same_channel_cannot_be_duplicated_by_changing_guild():
    import copy
    sample = data()
    second = copy.deepcopy(sample['entries'][2])
    second['args']['guild_id'] = '124'
    second['args']['target']['guild_id'] = '124'
    sample['entries'].append(second)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=sample['source'], publication=sample['publication'], entries=sample['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_discord_rejects_invisible_only_text():
    from scripts.social.channels.discord.direct import preview_message
    with pytest.raises(ValueError):
        preview_message(channel_id='456', text='\u200d')


def test_discord_message_id_conflict_across_bots_is_unknown():
    import copy
    sample = data()
    second = copy.deepcopy(sample['entries'][2])
    second['args']['channel_id'] = '789'
    second['args']['target']['channel_id'] = '789'
    second['args']['key'].update(account_id='fixture-discord-bot-other', destination_id='fixture-discord-channel-789')
    sample['entries'].append(second)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=sample['source'], publication=sample['publication'], entries=sample['entries'])
        ledger.approve_batch([(ids[2], 1), (ids[3], 1)])
        first = ledger.claim_due(ids[2], expected_version=1, now='2026-11-20T03:00:00Z')
        second_attempt = ledger.claim_due(ids[3], expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_discord_fixture(ids[2], attempt=first, channel_id='456', message_id='100')
        with pytest.raises(ValueError):
            ledger.finish_discord_fixture(ids[3], attempt=second_attempt, channel_id='789', message_id='100')
        assert ledger.get(ids[3])['state'] == 'unknown'
        assert ledger.get(ids[3])['conflict_remote_id'] == 'fixture-discord-message-100'
