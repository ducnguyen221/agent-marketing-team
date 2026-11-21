"""Synthetic V1 infographic and Short to Telegram channel media."""
import copy
import importlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch


def sample(kind):
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/v1_short_to_tiktok_simulation.json').read_text(encoding='utf-8'))
    old = data['entries'][1]['args']['key']
    key = dict(old, platform='telegram', account_id='fixture-telegram-publish-bot-demo',
               destination_id='fixture-telegram-channel-123')
    if kind == 'image':
        key['post_id'] = 'fixture-fb-infographic'
        data['source'] += '\n## post:infographic\n**Caption:** Nội dung infographic giả\n'
        data['publication']['posts'].append({'post_id': key['post_id'], 'content_id': key['content_id'],
            'channel': 'facebook', 'post_format': 'infographic', 'post_content': 'post:infographic', 'asset_ref': 'graphic.png'})
        filename, filekind = 'graphic.png', 'image'
    else:
        filename, filekind = 'short.mp4', 'video'
    manifest = [{'content_id': key['content_id'], 'post_id': key['post_id'], 'relative_path': filename,
                 'kind': filekind, 'id': 'fixture-media-123', 'path': '/fixture/' + filename}]
    entry = {'platform': 'telegram', 'args': {'key': key, 'chat_id': '-100123',
        'target': {'chat_id': '-100123', 'purpose': 'publish'}, 'scheduled_at': '2026-11-20T03:00:00Z',
        'manifest': manifest, 'adapted_caption': 'Nội dung riêng cho Telegram'}}
    return data['source'], data['publication'], [entry]


@pytest.mark.parametrize(('kind', 'method', 'field'), [('image', 'sendPhoto', 'photo'), ('video', 'sendVideo', 'video')])
def test_v1_media_preview_binds_original_asset_and_destination(kind, method, field):
    source, publication, entries = sample(kind)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        try:
            intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        except ValueError as exc:
            pytest.fail(f'Telegram {kind} V1 fixture unavailable: {exc}')
        payload = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        assert payload['candidate']['request']['method'] == method
        assert payload['candidate']['request']['body'][field] == 'fixture-media-123'
        assert payload['candidate']['request']['body']['caption'] == 'Nội dung riêng cho Telegram'
        assert ledger.get(intent)['grant_version'] is None
        ledger.approve(intent, expected_version=1)
        attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id='-100123', chat_type='channel',
                                           message_id='5', media_kind='image' if kind == 'video' else 'video')
        ledger.finish_telegram_fixture(intent, attempt=attempt, chat_id='-100123', chat_type='channel', message_id='5', media_kind=kind)
        assert ledger.get(intent)['state'] == 'accepted'


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_foreign_asset_is_rejected_atomically(kind):
    source, publication, entries = sample(kind)
    entries[0]['args']['manifest'][0]['post_id'] = 'fixture-other'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_short_source_caption_excludes_hook_and_script():
    source, publication, entries = sample('video')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        payload = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        assert payload['source_caption'] == 'Caption Short giả'
        assert 'Kịch bản' not in str(payload['candidate'])


@pytest.mark.parametrize(('length', 'accepted'), [(1024, True), (1025, False)])
def test_media_caption_fixture_boundaries(length, accepted):
    from scripts.social.channels.telegram.direct import preview_media
    if accepted:
        assert len(preview_media(chat_id='-100123', media_kind='image', media_id='fixture-image',
                                 caption='a' * length)['request']['body']['caption']) == length
    else:
        with pytest.raises(ValueError):
            preview_media(chat_id='-100123', media_kind='image', media_id='fixture-image', caption='a' * length)


def test_media_revision_requires_new_grant():
    source, publication, entries = sample('video')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        payload = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        payload['adapted_caption'] = 'Caption khác'
        payload['candidate']['request']['body']['caption'] = 'Caption khác'
        ledger.revise(intent, payload)
        assert ledger.get(intent)['grant_version'] is None
        with pytest.raises(ValueError): ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')


@pytest.mark.parametrize('action', ['post_image', 'post_video'])
def test_telegram_media_capability_is_offline_only(action):
    from scripts.social.capabilities import capabilities
    result = capabilities(platform='telegram', destination='channel', action=action)
    assert result['preview_schema'] == 'telegram_native'
    assert result['live_enabled'] is False


@pytest.mark.parametrize('reverse', [False, True])
def test_telegram_destinations_cannot_disagree_about_same_source_asset(reverse):
    source, publication, entries = sample('video')
    other = copy.deepcopy(entries[0])
    other['args']['key']['account_id'] = 'fixture-telegram-publish-bot-other'
    other['args']['key']['destination_id'] = 'fixture-telegram-channel-456'
    other['args']['chat_id'] = '-100456'
    other['args']['target']['chat_id'] = '-100456'
    other['args']['manifest'][0]['id'] = 'fixture-other-asset'
    entries.append(other)
    if reverse:
        entries.reverse()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_two_telegram_channels_can_share_same_declared_asset():
    source, publication, entries = sample('video')
    other = copy.deepcopy(entries[0])
    other['args']['key'].update(account_id='fixture-telegram-publish-bot-other', destination_id='fixture-telegram-channel-456')
    other['args'].update(chat_id='-100456', target={'chat_id': '-100456', 'purpose': 'publish'})
    entries.append(other)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        assert len(prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)) == 2


def test_same_receipt_cannot_be_reused_between_text_and_video():
    source, publication, entries = sample('video')
    source += '\n## post:facebook_post\nBài Facebook giả\n'
    publication['posts'].append({'post_id': 'fixture-fb-post', 'content_id': 'fixture-content', 'channel': 'facebook',
        'post_format': 'facebook_post', 'post_content': 'post:facebook_post', 'asset_ref': ''})
    key = dict(entries[0]['args']['key'], post_id='fixture-fb-post', occurrence_key='fixture-text-slot')
    entries.append({'platform': 'telegram', 'args': {'key': key, 'chat_id': '-100123',
        'target': {'chat_id': '-100123', 'purpose': 'publish'}, 'scheduled_at': '2026-11-20T03:00:00Z',
        'adapted_text': 'Bản tin Telegram riêng'}})
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        for index in (0, 1):
            ledger.approve(ids[index], expected_version=1)
            attempt = ledger.claim_due(ids[index], expected_version=1, now='2026-11-20T03:00:00Z')
            kwargs = {'attempt': attempt, 'chat_id': '-100123', 'chat_type': 'channel', 'message_id': '10'}
            if index == 0:
                ledger.finish_telegram_fixture(ids[index], media_kind='video', **kwargs)
            else:
                with pytest.raises(ValueError): ledger.finish_telegram_fixture(ids[index], **kwargs)
        assert ledger.get(ids[1])['state'] == 'unknown'
