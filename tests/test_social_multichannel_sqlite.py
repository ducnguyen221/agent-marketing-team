"""Atomic multi-channel fixture preparation from one synthetic source."""
import copy
import json
import socket
import sqlite3

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def key(platform, account, destination, post):
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': post, 'platform': platform, 'account_id': account,
            'destination_id': destination, 'occurrence_key': 'fixture-slot'}


def source():
    return ('---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
            '## post:threads_post\nBài Threads\n'
            '## post:instagram_reel\nVideo Instagram\n')


def entries():
    return [
        {'platform': 'threads', 'args': {'key': key('threads', 'fixture-threads-account-123', 'fixture-threads-123', 'fixture-post-a'),
          'target': {'platform': 'threads', 'account_id': 'fixture-threads-account-123', 'destination_id': 'fixture-threads-123',
                     'threads_user_id': '123'}, 'anchor': 'post:threads_post', 'api_version': 'v1.0', 'media_type': 'TEXT',
          'scheduled_at': '2026-11-20T03:00:00Z'}},
        {'platform': 'instagram', 'args': {'key': key('instagram', 'fixture-instagram-account-456', 'fixture-instagram-456', 'fixture-post-b'),
          'user_id': '456', 'anchor': 'post:instagram_reel', 'api_version': 'v21.0', 'media_type': 'REELS',
          'media_url': 'https://fixture.example.test/assets/fixture-video.mp4', 'scheduled_at': '2026-11-20T04:00:00Z'}}]


def test_atomic_multichannel_prepare_and_independent_due_claim(tmp_path, monkeypatch):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_fixture_batch(ledger, source=source(), entries=entries())
        assert len(ids) == 2 and ids[0] != ids[1]
        assert all(ledger.get(item)['grant_version'] is None for item in ids)
        assert prepare_fixture_batch(ledger, source=source(), entries=entries()) == ids
        ledger.approve_batch([(ids[0], 1), (ids[1], 1)])
        ledger.revoke(ids[0], expected_version=1)
        assert ledger.scan_due(now='2026-11-20T04:00:00Z')['due'] == [ids[1]]
        assert ledger.claim_due(ids[1], expected_version=1, now='2026-11-20T04:00:00Z')
        payload = json.loads(ledger.get(ids[1])['snapshot_json'])['payload']
        assert payload['candidate']['request']['params']['caption'] == 'Video Instagram'
    finally:
        con.close()


def test_invalid_second_destination_does_not_write_first(tmp_path):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = entries()
        items[1]['args']['user_id'] = '999'
        with pytest.raises(ValueError):
            prepare_fixture_batch(ledger, source=source(), entries=items)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_existing_conflict_rolls_back_new_destination(tmp_path):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = entries()
        existing = prepare_fixture_batch(ledger, source=source(), entries=[items[1]])[0]
        with pytest.raises(ValueError):
            prepare_fixture_batch(ledger, source=source().replace('Video Instagram', 'Video thay đổi'), entries=items)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 1
        assert ledger.get(existing)['state'] == 'prepared'
    finally:
        con.close()


@pytest.mark.parametrize('change', ['platform', 'source_override', 'duplicate', 'content', 'campaign'])
def test_batch_rejects_cross_platform_override_and_duplicate(tmp_path, change):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        items = entries()
        if change == 'platform': items[1]['platform'] = 'threads'
        elif change == 'source_override': items[1]['args']['source'] = 'other'
        elif change == 'duplicate': items.append(copy.deepcopy(items[0]))
        elif change == 'content': items[1]['args']['key']['content_id'] = 'fixture-other'
        else: items[1]['args']['key']['campaign_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            prepare_fixture_batch(ledger, source='## post:threads_post\nBài Threads\n## post:instagram_reel\nVideo Instagram\n', entries=items)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_batch_builds_all_six_platforms_from_one_fixture_source(tmp_path):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    shared = (source() + '## post:facebook_post\nBài Facebook\n'
              '## post:linkedin_post\nBài LinkedIn\n'
              '## post:tiktok_post\nBài TikTok\n'
              '## post:youtube_desc\nMô tả YouTube\n')
    items = entries()
    fb_key = key('facebook', 'fixture-facebook-account-789', 'fixture-facebook-page-789', 'fixture-post-fb')
    yt_key = key('youtube', 'fixture-youtube-account-one', 'fixture-youtube-channel-one', 'fixture-post-yt')
    def publication(identity, platform, post_format, anchor):
        return {'schema': 'publish/2', 'post_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
                'channel_id': 'fixture-channel', 'posts': [{'post_id': identity['post_id'], 'content_id': 'fixture-content',
                 'channel': platform, 'post_format': post_format, 'post_content': anchor, 'asset_ref': ''}]}
    manifest = [{'content_id': 'fixture-content', 'post_id': yt_key['post_id'], 'relative_path': name, 'kind': kind,
                 'id': 'fixture-' + kind, 'path': '/fixture/' + name}
                for name, kind in [('video.mp4', 'video'), ('thumbnail.png', 'image')]]
    items.extend([
        {'platform': 'facebook', 'args': {'key': fb_key, 'publication': publication(fb_key, 'facebook', 'facebook_post', 'post:facebook_post'),
         'manifest': [], 'scheduled_at': '2026-11-20T03:00:00Z', 'page_id': '789', 'api_version': 'v27.0', 'media_type': 'TEXT'}},
        {'platform': 'linkedin', 'args': {'key': key('linkedin', 'fixture-linkedin-account-a', 'fixture-linkedin-person-a', 'fixture-post-li'),
         'author': 'urn:li:person:fixture-a', 'anchor': 'post:linkedin_post', 'api_version': '202611', 'scheduled_at': '2026-11-20T03:00:00Z'}},
        {'platform': 'youtube', 'args': {'key': yt_key, 'publication': publication(yt_key, 'youtube', 'youtube_video', 'post:youtube_desc'),
         'manifest': manifest, 'scheduled_at': '2026-11-20T03:00:00Z', 'title': 'Video giả', 'category_id': '22',
         'privacy': 'private', 'made_for_kids': False}},
        {'platform': 'tiktok', 'args': {'key': key('tiktok', 'fixture-tiktok-account-1', 'fixture-tiktok-profile-1', 'fixture-post-tt'),
         'target': {'account_id': 'fixture-tiktok-account-1', 'destination_id': 'fixture-tiktok-profile-1',
                    'creator_id': 'fixture-tiktok-creator-1'}, 'anchor': 'post:tiktok_post', 'mode': 'INBOX',
         'scheduled_at': '2026-11-20T03:00:00Z', 'video_size': 4194304, 'chunk_size': 4194304,
         'media_id': 'fixture-video', 'media_sha256_fixture': 'a' * 64}}])
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = prepare_fixture_batch(ledger, source=shared, entries=items)
        assert len(ids) == 6
        assert {ledger.get(item)['platform'] for item in ids} == {'threads', 'instagram', 'facebook', 'linkedin', 'youtube', 'tiktok'}
        assert all(ledger.get(item)['grant_version'] is None for item in ids)
    finally:
        con.close()


def test_batch_accepts_identity_with_dot_as_ledger_does(tmp_path):
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = entries()[0]
        item['args']['key']['content_id'] = 'fixture-content.v2'
        text = source().replace('content_id: fixture-content', 'content_id: fixture-content.v2')
        assert len(prepare_fixture_batch(ledger, source=text, entries=[item])) == 1
    finally:
        con.close()


def test_reel_and_short_sample_uses_one_v1_publication_and_correct_assets():
    from pathlib import Path
    from scripts.social.multichannel_fixture import simulate_fixture_batch
    payload = json.loads((Path(__file__).parents[1] / 'fixtures/social_v2/reel_short_simulation.json').read_text(encoding='utf-8'))
    assert payload['entries'][0]['args']['publication'] == payload['entries'][1]['args']['publication']
    result = simulate_fixture_batch(**payload)
    reel, short = result['items']
    assert reel['platform'] == 'facebook' and short['platform'] == 'youtube'
    assert reel['candidate']['source_anchor'] == 'post:reel'
    assert reel['candidate']['media_id'] == 'fixture-video-facebook'
    assert short['candidate']['source_anchor'] == 'post:youtube_short'
    assert short['candidate']['media_id'] == 'fixture-video-youtube'
    assert short['candidate']['request']['body']['snippet']['description'] == 'Caption Short giả'
    assert reel['state'] == 'submitting' and short['state'] == 'submitting'


def test_reel_and_short_batch_rolls_back_when_short_media_belongs_to_reel(tmp_path):
    from pathlib import Path
    from scripts.social.multichannel_fixture import prepare_fixture_batch
    payload = json.loads((Path(__file__).parents[1] / 'fixtures/social_v2/reel_short_simulation.json').read_text(encoding='utf-8'))
    payload['entries'][1]['args']['manifest'][0]['post_id'] = 'fixture-fb-reel'
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_fixture_batch(ledger, source=payload['source'], entries=payload['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()
