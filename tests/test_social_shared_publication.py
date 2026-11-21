"""One synthetic V1 publication can feed multiple isolated V2 destinations."""
import copy
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social import multichannel_fixture


def sample():
    path = Path(__file__).resolve().parents[1] / 'fixtures/social_v2/reel_short_simulation.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    publications = [entry['args'].pop('publication') for entry in data['entries']]
    assert publications[0] == publications[1]
    data['publication'] = publications[0]
    return data


def test_shared_publication_prepares_two_destinations_without_mutating_input():
    data = sample()
    original = copy.deepcopy(data)
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert [ledger.get(item)['platform'] for item in ids] == ['facebook', 'youtube']
        assert all(ledger.get(item)['grant_version'] is None for item in ids)
    assert data == original


def test_shared_publication_rejects_per_destination_override_without_partial_write():
    data = sample()
    data['entries'][1]['args']['publication'] = data['publication']
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_legacy_batch_rejects_conflicting_publications_for_same_source():
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/reel_short_simulation.json').read_text(encoding='utf-8'))
    data['entries'][1]['args']['publication']['posts'][0]['post_format'] = 'facebook_post'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_fixture_batch(ledger, source=data['source'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_legacy_batch_rejects_one_anchor_claimed_by_two_distinct_posts():
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'fixtures/social_v2/reel_short_simulation.json').read_text(encoding='utf-8'))
    first = data['entries'][0]
    first['args']['publication']['posts'] = [first['args']['publication']['posts'][0]]
    second = copy.deepcopy(first)
    second['args']['key']['post_id'] = 'fixture-other-reel'
    second['args']['publication']['posts'][0]['post_id'] = 'fixture-other-reel'
    second['args']['manifest'][0]['post_id'] = 'fixture-other-reel'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_fixture_batch(ledger, source=data['source'], entries=[first, second])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_shared_publication_rejects_duplicate_post_ids():
    data = sample()
    data['publication']['posts'][1]['post_id'] = data['publication']['posts'][0]['post_id']
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_shared_publication_simulates_lifecycle():
    result = multichannel_fixture.simulate_v1_fixture_batch(**sample())
    assert [item['state'] for item in result['items']] == ['submitting', 'submitting']
    assert result['fixture_only'] is True


def test_shared_publication_cli_accepts_one_publication():
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'simulate-v1-batch'],
                            input=json.dumps(sample()), text=True, encoding='utf-8', capture_output=True, check=False)
    assert result.returncode == 0
    assert [item['platform'] for item in json.loads(result.stdout)['items']] == ['facebook', 'youtube']


def test_shared_publication_rejects_wrong_second_media_owner_atomically():
    data = sample()
    data['entries'][1]['args']['manifest'][0]['post_id'] = 'fixture-fb-reel'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def instagram_sample():
    data = sample()
    data['source'] += '\n## post:infographic\nPrompt\n\n**Caption:** Ảnh giả\n'
    data['publication']['posts'].append({'post_id': 'fixture-fb-image', 'content_id': 'fixture-content',
        'channel': 'facebook', 'post_format': 'infographic', 'post_content': 'post:infographic',
        'asset_ref': 'infographic.png'})
    key = dict(data['entries'][0]['args']['key'], platform='instagram', post_id='fixture-fb-image',
               account_id='fixture-instagram-account-456', destination_id='fixture-instagram-456')
    data['entries'].append({'platform': 'instagram', 'args': {'key': key, 'user_id': '456',
        'api_version': 'v21.0', 'scheduled_at': '2026-11-20T03:00:00Z',
        'manifest': [{'content_id': 'fixture-content', 'post_id': 'fixture-fb-image',
                      'relative_path': 'infographic.png', 'kind': 'image', 'id': 'fixture-image',
                      'path': '/fixture/infographic.png'}]}})
    return data


def instagram_reel_sample():
    data = sample()
    key = dict(data['entries'][0]['args']['key'], platform='instagram',
               account_id='fixture-instagram-account-456', destination_id='fixture-instagram-456')
    data['entries'].append({'platform': 'instagram', 'args': {'key': key, 'user_id': '456',
        'api_version': 'v21.0', 'scheduled_at': '2026-11-20T03:00:00Z',
        'manifest': [{'content_id': 'fixture-content', 'post_id': 'fixture-fb-reel',
                      'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-ig',
                      'path': '/fixture/short.mp4'}]}})
    return data


def tiktok_short_sample():
    data = sample()
    key = dict(data['entries'][1]['args']['key'], platform='tiktok',
               account_id='fixture-tiktok-account-demo', destination_id='fixture-tiktok-profile-demo')
    data['entries'].append({'platform': 'tiktok', 'args': {'key': key,
        'target': {'account_id': 'fixture-tiktok-account-demo', 'destination_id': 'fixture-tiktok-profile-demo',
                   'creator_id': 'fixture-tiktok-creator-demo'}, 'scheduled_at': '2026-11-20T03:00:00Z',
        'manifest': [{'content_id': 'fixture-content', 'post_id': 'fixture-yt-short', 'relative_path': 'short.mp4',
                      'kind': 'video', 'id': 'fixture-video-tiktok', 'path': '/fixture/short.mp4'}],
        'video_size': 4194304, 'chunk_size': 4194304, 'media_sha256_fixture': 'a' * 64}})
    return data


def linkedin_text_sample():
    data = sample()
    data['source'] += ('\n## post:facebook_post\nNội dung Facebook giả\n\n'
                       '### comment_1\nLink ở bình luận\n\n### image_prompt\nChỉ dẫn ảnh nội bộ\n')
    data['publication']['posts'].append({'post_id': 'fixture-fb-post', 'content_id': 'fixture-content',
        'channel': 'facebook', 'post_format': 'facebook_post', 'post_content': 'post:facebook_post', 'asset_ref': ''})
    key = dict(data['entries'][0]['args']['key'], platform='linkedin', post_id='fixture-fb-post',
               account_id='fixture-linkedin-account-demo', destination_id='fixture-linkedin-person-demo')
    data['entries'].append({'platform': 'linkedin', 'args': {'key': key, 'author': 'urn:li:person:fixture-demo',
        'api_version': '202611', 'scheduled_at': '2026-11-20T03:00:00Z',
        'adapted_text': 'Một góc nhìn riêng cho LinkedIn.'}})
    return data


def threads_text_sample():
    data = linkedin_text_sample()
    key = dict(data['entries'][2]['args']['key'], platform='threads',
               account_id='fixture-threads-account-456', destination_id='fixture-threads-456')
    data['entries'][2] = {'platform': 'threads', 'args': {'key': key,
        'target': {'platform': 'threads', 'account_id': 'fixture-threads-account-456',
                   'destination_id': 'fixture-threads-456', 'threads_user_id': '456'},
        'api_version': 'v1.0', 'scheduled_at': '2026-11-20T03:00:00Z',
        'adapted_text': 'Một góc nhìn ngắn cho Threads.'}}
    return data


def test_threads_text_uses_adaptation_and_discloses_omitted_source():
    data = threads_text_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        text = payload['candidate']['request']['params']['text']
        assert text == 'Một góc nhìn ngắn cho Threads.'
        assert payload['source_notes']['first_comment_omitted'] is True
        assert payload['source_notes']['image_prompt_omitted'] is True
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


def test_threads_selects_second_source_and_rejects_schema_switch():
    from scripts.social.threads_fixture_flow import _build as build_threads
    data = threads_text_sample()
    data['source'] += '\n## post:facebook_post#2\nBài Facebook thứ hai\n\n## post:threads_post\nBài giả Threads\n'
    data['publication']['posts'].append(dict(data['publication']['posts'][2],
        post_id='fixture-fb-second', post_content='post:facebook_post#2'))
    args = data['entries'][2]['args']
    args['key']['post_id'] = 'fixture-fb-second'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        before = ledger.get(ids[2])
        payload = json.loads(before['snapshot_json'])['payload']
        assert payload['publication']['posts'][0]['post_content'] == 'post:facebook_post#2'
        replacement = build_threads(key=args['key'], target=args['target'], source=data['source'],
            anchor='post:threads_post', api_version=args['api_version'], media_type='TEXT',
            scheduled_at=args['scheduled_at'], media_url=None)
        with pytest.raises(ValueError):
            ledger.revise(ids[2], replacement)
        assert ledger.get(ids[2])['snapshot_json'] == before['snapshot_json']


def test_threads_normalizes_windows_text_and_accepts_500_character_boundary():
    data = threads_text_sample()
    data['entries'][2]['args']['adapted_text'] = 'x' * 498 + '\r\ny'
    result = multichannel_fixture.simulate_v1_fixture_batch(**data)
    assert result['items'][2]['candidate']['request']['params']['text'] == 'x' * 498 + '\ny'


@pytest.mark.parametrize('change', ['copy', 'target', 'format', 'asset', 'unsafe', 'long'])
def test_threads_v1_rejects_unadapted_or_invalid_inputs_atomically(change):
    data = threads_text_sample()
    args = data['entries'][2]['args']
    if change == 'copy': args['adapted_text'] = 'Nội dung Facebook giả'
    if change == 'target': args['target']['threads_user_id'] = '999'
    if change == 'format': data['publication']['posts'][2]['post_format'] = 'reel'
    if change == 'asset': data['publication']['posts'][2]['asset_ref'] = 'image.png'
    if change == 'unsafe': args['adapted_text'] = '<!-- nội dung ẩn -->'
    if change == 'long': args['adapted_text'] = 'x' * 501
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_linkedin_text_uses_adapted_text_and_discloses_omitted_parts():
    data = linkedin_text_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        text = payload['candidate']['request']['body']['commentary']
        assert 'Một góc nhìn riêng' in text and 'Link ở bình luận' not in text and 'Chỉ dẫn ảnh' not in text
        assert payload['source_notes']['first_comment_omitted'] is True
        assert payload['source_notes']['image_prompt_omitted'] is True
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


def test_linkedin_organization_uses_second_facebook_post_and_source_notes():
    data = linkedin_text_sample()
    data['source'] += '\n## post:facebook_post#2\nBài Facebook thứ hai\n'
    data['publication']['posts'].append(dict(data['publication']['posts'][2],
        post_id='fixture-fb-second', post_content='post:facebook_post#2'))
    args = data['entries'][2]['args']
    args['key'].update(post_id='fixture-fb-second', account_id='fixture-linkedin-org-account-123',
                       destination_id='fixture-linkedin-org-123')
    args['author'] = 'urn:li:organization:123'
    result = multichannel_fixture.simulate_v1_fixture_batch(**data)
    item = result['items'][2]
    assert item['source_binding']['post_id'] == 'fixture-fb-second'
    assert item['source_binding']['anchor'] == 'post:facebook_post#2'
    assert item['source_notes']['first_comment_omitted'] is False
    assert item['candidate']['request']['body']['author'] == 'urn:li:organization:123'


def test_linkedin_rejects_copy_with_different_line_endings():
    data = linkedin_text_sample()
    data['source'] = data['source'].replace('Nội dung Facebook giả', 'Dòng đầu\r\nDòng sau')
    data['entries'][2]['args']['adapted_text'] = 'Dòng đầu\nDòng sau'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])


@pytest.mark.parametrize('change', ['copy', 'author', 'format', 'asset', 'unsafe'])
def test_linkedin_v1_rejects_unadapted_or_invalid_inputs_without_partial_batch(change):
    data = linkedin_text_sample()
    args = data['entries'][2]['args']
    if change == 'copy': args['adapted_text'] = 'Nội dung Facebook giả'
    if change == 'author': args['author'] = 'urn:li:person:fixture-other'
    if change == 'format': data['publication']['posts'][2]['post_format'] = 'reel'
    if change == 'asset': data['publication']['posts'][2]['asset_ref'] = 'image.png'
    if change == 'unsafe': args['adapted_text'] = '<!-- nội dung ẩn -->'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def tiktok_direct_short_sample():
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    data = tiktok_short_sample()
    creator = {'fixture_only': True, 'fixture_creator_id': 'fixture-tiktok-creator-demo',
               'fixture_revision': 'fixture-rev', 'privacy_level_options': ['SELF_ONLY'],
               'comment_disabled': True, 'duet_disabled': True, 'stitch_disabled': True,
               'max_video_post_duration_sec': 60}
    post_info = {'title': 'Caption Short giả', 'privacy_level': 'SELF_ONLY', 'disable_comment': True,
                 'disable_duet': True, 'disable_stitch': True, 'brand_content_toggle': False,
                 'brand_organic_toggle': False}
    consent = fixture_consent_digest(video_size=4194304, chunk_size=4194304, duration_sec=30,
                                     creator=creator, post_info=post_info, media_sha256_fixture='a' * 64)
    data['entries'][2]['args']['direct'] = {'creator': creator, 'creator_revision': 'fixture-rev',
        'duration_sec': 30, 'post_info': post_info, 'consent_fixture': True, 'consent_digest_fixture': consent}
    return data


def test_tiktok_direct_short_binds_fixture_consent_and_caption():
    data = tiktok_direct_short_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        assert payload['fixture_schema'] == 'tiktok-v1-short-direct/1'
        assert payload['candidate']['request']['body']['post_info']['title'] == 'Caption Short giả'
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


@pytest.mark.parametrize('change', ['caption', 'digest', 'creator', 'media', 'consent', 'privacy'])
def test_tiktok_direct_short_rejects_mismatched_fixture_consent(change):
    data = tiktok_direct_short_sample()
    args = data['entries'][2]['args']
    if change == 'caption': args['direct']['post_info']['title'] = 'Khác'
    if change == 'digest': args['direct']['consent_digest_fixture'] = 'b' * 64
    if change == 'creator': args['direct']['creator']['fixture_creator_id'] = 'fixture-tiktok-creator-other'
    if change == 'media': args['media_sha256_fixture'] = 'b' * 64
    if change == 'consent': args['direct']['consent_fixture'] = False
    if change == 'privacy': args['direct']['post_info']['privacy_level'] = 'PUBLIC_TO_EVERYONE'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_tiktok_direct_revised_fixture_revokes_old_grant():
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    from scripts.social.tiktok_v1_fixture_flow import prepare_tiktok_v1_fixture
    data = tiktok_direct_short_sample()
    args = data['entries'][2]['args']
    with sqlite3.connect(':memory:') as con, sqlite3.connect(':memory:') as other:
        ledger = DestinationFixtureLedger.initialize(con)
        alternate = DestinationFixtureLedger.initialize(other)
        item = prepare_tiktok_v1_fixture(ledger, source=data['source'], publication=data['publication'], **args)
        ledger.approve(item, expected_version=1)
        changed = copy.deepcopy(args)
        options = changed['direct']
        options['duration_sec'] = 31
        options['consent_digest_fixture'] = fixture_consent_digest(
            video_size=changed['video_size'], chunk_size=changed['chunk_size'], duration_sec=31,
            creator=options['creator'], post_info=options['post_info'], media_sha256_fixture=changed['media_sha256_fixture'])
        other_item = prepare_tiktok_v1_fixture(alternate, source=data['source'], publication=data['publication'], **changed)
        payload = json.loads(alternate.get(other_item)['snapshot_json'])['payload']
        ledger.revise(item, payload)
        assert ledger.get(item)['version'] == 2
        assert ledger.get(item)['grant_version'] is None
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')


def test_tiktok_inbox_uses_youtube_short_caption_and_bound_manifest():
    data = tiktok_short_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        assert payload['suggested_caption'] == 'Caption Short giả'
        assert payload['media_id'] == 'fixture-video-tiktok'
        assert 'post_info' not in payload['candidate']['request']['body']
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


def test_tiktok_and_youtube_use_default_short_asset_when_reference_omitted():
    data = tiktok_short_sample()
    del data['publication']['posts'][1]['asset_ref']
    result = multichannel_fixture.simulate_v1_fixture_batch(**data)
    assert [item['platform'] for item in result['items']] == ['facebook', 'youtube', 'tiktok']
    assert result['items'][2]['fixture_media']['media_id'] == 'fixture-video-tiktok'


def test_tiktok_inbox_selects_second_short_and_revalidates_media():
    data = tiktok_short_sample()
    data['source'] += '\n## post:youtube_short#2\n**Hook:** Nội bộ\n\n**Caption:** Short thứ hai\n'
    data['publication']['posts'].append(dict(data['publication']['posts'][1],
        post_id='fixture-short-second', post_content='post:youtube_short#2'))
    entry = data['entries'][2]['args']
    entry['key']['post_id'] = 'fixture-short-second'
    entry['manifest'][0].update(post_id='fixture-short-second', id='fixture-video-second')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        payload = json.loads(ledger.get(ids[2])['snapshot_json'])['payload']
        assert payload['suggested_caption'] == 'Short thứ hai'
        assert payload['source_anchor'] == 'post:youtube_short#2'
        assert payload['media_id'] == 'fixture-video-second'
        payload['manifest'][0]['post_id'] = 'fixture-fb-reel'
        with pytest.raises(ValueError):
            ledger.revise(ids[2], payload)


@pytest.mark.parametrize('change', ['owner', 'channel', 'anchor', 'caption', 'direct'])
def test_tiktok_inbox_rejects_invalid_source_atomically(change):
    data = tiktok_short_sample()
    if change == 'owner': data['entries'][2]['args']['manifest'][0]['post_id'] = 'fixture-fb-reel'
    if change == 'channel': data['publication']['posts'][1]['channel'] = 'facebook'
    if change == 'anchor': data['publication']['posts'][1]['post_content'] = 'post:reel'
    if change == 'caption': data['source'] = data['source'].replace('**Caption:** Caption Short giả', 'không có caption')
    if change == 'direct': data['entries'][2]['args']['mode'] = 'DIRECT'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_instagram_reel_uses_v1_caption_and_selected_video():
    data = instagram_reel_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        assert payload['candidate']['request']['params']['caption'] == 'Reel giả trên Facebook'
        assert payload['candidate']['request']['params']['video_url'].endswith('/fixture-video-ig.mp4')
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


def test_instagram_reel_second_source_disclosed_and_manifest_bound():
    data = instagram_reel_sample()
    data['source'] += '\n## post:reel#2\nCaption video thứ hai\n'
    data['publication']['posts'].append(dict(data['publication']['posts'][0], post_id='fixture-fb-reel-2',
                                              post_content='post:reel#2'))
    entry = data['entries'][2]['args']
    entry['key']['post_id'] = 'fixture-fb-reel-2'
    entry['manifest'][0].update(post_id='fixture-fb-reel-2', id='fixture-video-second')
    result = multichannel_fixture.simulate_v1_fixture_batch(**data)
    item = result['items'][2]
    assert item['source_binding']['post_id'] == 'fixture-fb-reel-2'
    assert item['source_binding']['anchor'] == 'post:reel#2'
    assert item['candidate']['request']['params']['caption'] == 'Caption video thứ hai'
    assert item['candidate']['request']['params']['video_url'].endswith('/fixture-video-second.mp4')
    entry['manifest'][0]['post_id'] = 'fixture-fb-reel'
    with pytest.raises(ValueError):
        multichannel_fixture.simulate_v1_fixture_batch(**data)


@pytest.mark.parametrize('style', ['bom', 'crlf'])
def test_instagram_reel_supports_windows_source(style):
    data = instagram_reel_sample()
    data['source'] = ('\ufeff' + data['source'] if style == 'bom'
                      else data['source'].replace('\n', '\r\n'))
    assert len(multichannel_fixture.simulate_v1_fixture_batch(**data)['items']) == 3


def test_instagram_reel_direct_prepare_and_revise_reject_oversized_source():
    from scripts.social.instagram_v1_fixture_flow import prepare_instagram_v1_fixture
    data = instagram_reel_sample()
    args = data['entries'][2]['args']
    oversized = data['source'] + 'x' * 33000
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_instagram_v1_fixture(ledger, source=oversized, publication=data['publication'], **args)
        item = prepare_instagram_v1_fixture(ledger, source=data['source'], publication=data['publication'], **args)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])['payload']
        snapshot['source'] = oversized
        with pytest.raises(ValueError):
            ledger.revise(item, snapshot)


@pytest.mark.parametrize('change', ['owner', 'format', 'anchor', 'hidden'])
def test_instagram_reel_rejects_unbound_or_hidden_source(change):
    data = instagram_reel_sample()
    if change == 'owner': data['entries'][2]['args']['manifest'][0]['post_id'] = 'fixture-yt-short'
    if change == 'format': data['publication']['posts'][0]['post_format'] = 'infographic'
    if change == 'anchor': data['publication']['posts'][0]['post_content'] = 'post:youtube_short'
    if change == 'hidden': data['source'] = data['source'].replace('Reel giả trên Facebook', '<!--ẩn-->')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_instagram_uses_selected_v1_infographic_and_its_image():
    data = instagram_sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        row = ledger.get(ids[2])
        payload = json.loads(row['snapshot_json'])['payload']
        assert row['grant_version'] is None
        assert payload['candidate']['request']['params']['caption'] == 'Ảnh giả'
        assert payload['candidate']['request']['params']['image_url'].endswith('/fixture-image.png')
        ledger.approve(ids[2], expected_version=1)
        assert ids[2] in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']


def test_simulation_reports_instagram_cross_platform_source():
    result = multichannel_fixture.simulate_v1_fixture_batch(**instagram_sample())
    assert result['items'][2]['source_binding'] == {'channel': 'facebook', 'post_id': 'fixture-fb-image',
                                                     'post_format': 'infographic', 'anchor': 'post:infographic'}


def test_instagram_selects_second_infographic_and_revalidates_snapshot():
    data = instagram_sample()
    data['source'] += '\n## post:infographic#2\nPrompt 2\n\n**Caption:** Ảnh thứ hai\n'
    second = dict(data['publication']['posts'][2], post_id='fixture-image-second',
                  post_content='post:infographic#2', asset_ref='second.png')
    data['publication']['posts'].append(second)
    entry = data['entries'][2]['args']
    entry['key']['post_id'] = 'fixture-image-second'
    entry['manifest'][0].update(post_id='fixture-image-second', relative_path='second.png',
                                id='fixture-second', path='/fixture/second.png')
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        payload = json.loads(ledger.get(ids[2])['snapshot_json'])['payload']
        assert payload['candidate']['request']['params']['caption'] == 'Ảnh thứ hai'
        assert payload['candidate']['request']['params']['image_url'].endswith('/fixture-second.png')
        payload['manifest'][0]['post_id'] = 'fixture-fb-image'
        with pytest.raises(ValueError):
            ledger.revise(ids[2], payload)


@pytest.mark.parametrize('prefix', ['\ufeff', 'crlf'])
def test_instagram_accepts_v1_frontmatter_in_windows_text(prefix):
    data = instagram_sample()
    data['source'] = (data['source'].replace('\n', '\r\n') if prefix == 'crlf' else prefix + data['source'])
    assert len(multichannel_fixture.simulate_v1_fixture_batch(**data)['items']) == 3


def test_instagram_v1_cannot_be_revised_to_unbound_schema():
    from scripts.social.instagram_fixture_flow import _build
    data = instagram_sample()
    args = data['entries'][2]['args']
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        ids = multichannel_fixture.prepare_v1_fixture_batch(
            ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        before = ledger.get(ids[2])
        replacement = _build(key=args['key'], source=data['source'], user_id='456', anchor='post:infographic',
                             api_version='v21.0', media_type='IMAGE', scheduled_at=args['scheduled_at'],
                             media_url='https://fixture.example.test/assets/fixture-other.png')
        with pytest.raises(ValueError):
            ledger.revise(ids[2], replacement)
        assert ledger.get(ids[2])['snapshot_json'] == before['snapshot_json']


@pytest.mark.parametrize('change', ['owner', 'channel', 'asset', 'anchor'])
def test_instagram_rejects_unbound_v1_infographic_atomically(change):
    data = instagram_sample()
    post = data['publication']['posts'][2]
    if change == 'owner': data['entries'][2]['args']['manifest'][0]['post_id'] = 'fixture-fb-reel'
    if change == 'channel': post['channel'] = 'youtube'
    if change == 'asset': post['asset_ref'] = ''
    if change == 'anchor': post['post_content'] = 'post:reel'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            multichannel_fixture.prepare_v1_fixture_batch(
                ledger, source=data['source'], publication=data['publication'], entries=data['entries'])
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
