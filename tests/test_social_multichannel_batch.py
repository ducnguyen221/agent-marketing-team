"""Offline multi-channel planning from a single synthetic marketing source."""
import copy
import socket

import pytest


def source():
    return ('## post:facebook_post\nBài Facebook giả\n'
            '## post:instagram_reel\nReel giả\n'
            '## post:linkedin_post\nLinkedIn giả\n'
            '## post:youtube_desc\nYouTube giả\n'
            '## post:tiktok_post\nTikTok giả\n')


def entries():
    return [
        {'platform': 'facebook', 'destination': 'fixture-facebook-page-123', 'occurrence': 'fixture-slot',
         'scheduled_at': '2026-11-20T03:00:00Z',
         'options': {'anchor': 'post:facebook_post', 'page_id': '123', 'api_version': 'v27.0', 'media_type': 'TEXT'}},
        {'platform': 'instagram', 'destination': 'fixture-instagram-456', 'occurrence': 'fixture-slot',
         'scheduled_at': '2026-11-20T04:00:00Z',
         'options': {'anchor': 'post:instagram_reel', 'user_id': '456', 'api_version': 'v21.0', 'media_type': 'REELS',
                     'media_url': 'https://fixture.example.test/assets/fixture-video.mp4'}},
        {'platform': 'linkedin', 'destination': 'fixture-linkedin-person-member', 'occurrence': 'fixture-slot',
         'scheduled_at': '2026-11-20T05:00:00Z',
         'options': {'anchor': 'post:linkedin_post', 'author': 'urn:li:person:fixture-member', 'api_version': '202611'}},
        {'platform': 'youtube', 'destination': 'fixture-youtube-channel-abc', 'occurrence': 'fixture-slot',
         'scheduled_at': '2026-11-20T06:00:00Z',
         'options': {'anchor': 'post:youtube_desc', 'title': 'Video giả', 'category_id': '22', 'privacy': 'private',
                     'made_for_kids': False, 'media_id': 'fixture-video'}},
    ]


def test_multi_channel_batch_uses_channel_specific_anchors_offline(monkeypatch):
    from scripts.social.multichannel_fixture import preview_batch
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    result = preview_batch(source=source(), entries=entries())
    assert result['preview_only'] is True
    by_platform = {item['platform']: item for item in result['items']}
    assert by_platform['facebook']['candidate']['request']['params']['message'] == 'Bài Facebook giả'
    assert by_platform['instagram']['candidate']['request']['params']['caption'] == 'Reel giả'
    assert by_platform['linkedin']['candidate']['request']['body']['commentary'] == 'LinkedIn giả'
    assert by_platform['youtube']['candidate']['request']['body']['snippet']['description'] == 'YouTube giả'
    assert all(item['scheduled_at'] for item in result['items'])


def test_duplicate_occurrence_is_refused_even_if_time_differs():
    from scripts.social.multichannel_fixture import preview_batch
    items = entries()
    duplicate = copy.deepcopy(items[0])
    duplicate['scheduled_at'] = '2026-11-21T03:00:00Z'
    with pytest.raises(ValueError):
        preview_batch(source=source(), entries=items + [duplicate])


@pytest.mark.parametrize('change', ['target', 'anchor', 'time', 'missing', 'real_media'])
def test_one_invalid_destination_fails_whole_preview(change):
    from scripts.social.multichannel_fixture import preview_batch
    items = entries()
    if change == 'target': items[0]['destination'] = 'fixture-facebook-page-999'
    elif change == 'anchor': items[0]['options']['anchor'] = 'post:linkedin_post'
    elif change == 'time': items[0]['scheduled_at'] = 'tomorrow'
    elif change == 'missing': del items[0]['options']['page_id']
    else: items[1]['options']['media_url'] = 'https://real.example/video.mp4'
    with pytest.raises(ValueError):
        preview_batch(source=source(), entries=items)


@pytest.mark.parametrize('items', [[], None, [{}], [42]])
def test_invalid_batches_are_refused(items):
    from scripts.social.multichannel_fixture import preview_batch
    with pytest.raises(ValueError):
        preview_batch(source=source(), entries=items)


def test_cli_batch_accepts_synthetic_json():
    import json
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-batch'],
                            input=json.dumps({'source': source(), 'entries': entries()}),
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert len(json.loads(result.stdout)['items']) == 4


@pytest.mark.parametrize(('kind', 'url'), [('REELS', 'https://fixture.example.test/assets/fixture-image.jpg'),
                                           ('IMAGE', 'https://fixture.example.test/assets/fixture-video.mp4')])
def test_instagram_fixture_media_label_matches_kind(kind, url):
    from scripts.social.multichannel_fixture import preview_batch
    item = copy.deepcopy(entries()[1])
    item['options']['media_type'] = kind
    item['options']['media_url'] = url
    if kind == 'IMAGE':
        item['options']['anchor'] = 'post:infographic'
    body = source() + '## post:infographic\n**Caption:** Hình giả\n'
    with pytest.raises(ValueError):
        preview_batch(source=body, entries=[item])


def tiktok_entry(mode):
    options = {'anchor': 'post:tiktok_post', 'content_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
               'mode': mode, 'video_size': 4194304, 'chunk_size': 4194304, 'media_id': 'fixture-video',
               'media_sha256_fixture': 'a' * 64}
    if mode == 'DIRECT':
        from scripts.social.channels.tiktok.direct import fixture_consent_digest
        creator = {'fixture_only': True, 'fixture_creator_id': 'fixture-tiktok-creator-123',
                   'fixture_revision': 'fixture-revision', 'privacy_level_options': ['SELF_ONLY'],
                   'comment_disabled': True, 'duet_disabled': True, 'stitch_disabled': True,
                   'max_video_post_duration_sec': 60}
        post = {'title': 'TikTok giả', 'privacy_level': 'SELF_ONLY', 'disable_comment': True, 'disable_duet': True,
                'disable_stitch': True, 'brand_content_toggle': False, 'brand_organic_toggle': False}
        options.update({'creator': creator, 'creator_revision': 'fixture-revision', 'duration_sec': 30,
                        'post_info': post, 'consent_fixture': True,
                        'consent_digest_fixture': fixture_consent_digest(video_size=4194304, chunk_size=4194304,
                            duration_sec=30, creator=creator, post_info=post, media_sha256_fixture='a' * 64)})
    return {'platform': 'tiktok', 'destination': 'fixture-tiktok-profile-123', 'occurrence': 'fixture-slot',
            'scheduled_at': '2026-11-20T03:00:00Z', 'options': options}


@pytest.mark.parametrize('mode', ['INBOX', 'DIRECT'])
def test_tiktok_batch_reuses_mode_specific_candidate(mode, monkeypatch):
    from scripts.social.multichannel_fixture import preview_batch
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    result = preview_batch(source=source(), entries=entries() + [tiktok_entry(mode)])
    candidate = result['items'][-1]['candidate']
    assert candidate['suggested_caption'] == 'TikTok giả'
    body = candidate['candidate']['request']['body']
    if mode == 'INBOX':
        assert 'post_info' not in body
    else:
        assert body['post_info']['title'] == 'TikTok giả'


@pytest.mark.parametrize('change', ['creator', 'consent', 'destination', 'anchor'])
def test_tiktok_invalid_input_fails_entire_batch(change):
    from scripts.social.multichannel_fixture import preview_batch
    item = tiktok_entry('DIRECT')
    if change == 'creator': item['options']['creator']['fixture_creator_id'] = 'fixture-tiktok-creator-999'
    elif change == 'consent': item['options']['consent_digest_fixture'] = '0' * 64
    elif change == 'destination': item['destination'] = 'fixture-tiktok-profile-999'
    else: item['options']['anchor'] = 'post:linkedin_post'
    with pytest.raises(ValueError):
        preview_batch(source=source(), entries=entries() + [item])


def test_tiktok_batch_cli_uses_inbox_suggestion():
    import json
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare-batch'],
                            input=json.dumps({'source': source(), 'entries': [tiktok_entry('INBOX')]}),
                            capture_output=True, text=True, encoding='utf-8', check=False)
    assert result.returncode == 0
    item = json.loads(result.stdout)['items'][0]['candidate']
    assert item['suggested_caption'] == 'TikTok giả'
    assert 'post_info' not in item['candidate']['request']['body']


def test_tiktok_batch_exposes_media_binding_to_reviewer():
    from scripts.social.multichannel_fixture import preview_batch
    first = tiktok_entry('INBOX')
    second = copy.deepcopy(first)
    second['options']['media_id'] = 'fixture-video-other'
    second['options']['media_sha256_fixture'] = 'b' * 64
    a = preview_batch(source=source(), entries=[first])['items'][0]['candidate']
    b = preview_batch(source=source(), entries=[second])['items'][0]['candidate']
    assert a['source_anchor'] == 'post:tiktok_post'
    assert (a['media_id'], a['media_sha256_fixture']) != (b['media_id'], b['media_sha256_fixture'])


@pytest.mark.parametrize('mode', ['INBOX', 'DIRECT'])
def test_tiktok_batch_preview_needs_no_sqlite(mode, monkeypatch):
    import sqlite3
    from scripts.social.multichannel_fixture import preview_batch

    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: pytest.fail('SQLite used for preview'))
    result = preview_batch(source=source(), entries=[tiktok_entry(mode)])
    assert result['items'][0]['candidate']['suggested_caption'] == 'TikTok giả'


@pytest.mark.parametrize('mode', ['INBOX', 'DIRECT'])
def test_tiktok_preview_matches_ledger_snapshot(mode):
    import json
    import sqlite3
    from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
    from scripts.social.multichannel_fixture import preview_batch
    from scripts.social.tiktok_fixture_flow import prepare_tiktok_fixture

    entry = tiktok_entry(mode)
    preview = preview_batch(source=source(), entries=[entry])['items'][0]['candidate']
    options = dict(entry['options'])
    campaign = options.pop('campaign_id')
    content = options.pop('content_id')
    target = {'account_id': 'fixture-tiktok-account-123', 'destination_id': entry['destination'],
              'creator_id': 'fixture-tiktok-creator-123'}
    key = {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': campaign,
           'content_id': content, 'post_id': 'fixture-post', 'platform': 'tiktok',
           'account_id': target['account_id'], 'destination_id': target['destination_id'],
           'occurrence_key': entry['occurrence']}
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_tiktok_fixture(ledger, key=key, target=target, source=source(),
                                        scheduled_at=entry['scheduled_at'], **options)
        payload = json.loads(ledger.get(intent)['snapshot_json'])['payload']
    for field in ('candidate', 'source_anchor', 'media_id', 'media_sha256_fixture', 'mode'):
        assert preview[field] == payload[field]
