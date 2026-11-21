"""Exercise the offline social CLI with synthetic JSON via stdin."""
import json
import io
import socket
import subprocess
import sys


def run_cli(*args, value=None):
    return subprocess.run([sys.executable, '-m', 'scripts.social.cli', *args],
                          input='' if value is None else json.dumps(value),
                          text=True, capture_output=True, check=False)


def test_capabilities_cli_never_enables_live_route():
    result = run_cli('capabilities')
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data and all(item['live_enabled'] is False for item in data)


def test_prepare_cli_reads_fixture_and_does_not_publish():
    payload = {'source': '## post:threads_post\nText gia\n', 'anchor': 'post:threads_post',
               'integration_id': 'fixture-int', 'provider': 'threads', 'media': [],
               'settings': {'__type': 'threads'}, 'date_utc': '2026-11-20T03:00:00Z'}
    result = run_cli('prepare', value=payload)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['preview_only'] is True
    assert data['candidate']['posts'][0]['value'][0]['content'] == 'Text gia'


def test_prepare_threads_native_cli_uses_synthetic_marketing_anchor():
    result = run_cli('prepare-threads', value={'source': '## post:threads_post\nBai gia\n',
                     'anchor': 'post:threads_post', 'user_id': '123', 'api_version': 'v1.0',
                     'media_type': 'TEXT'})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['request']['params']['text'] == 'Bai gia'
    assert data['preview_only'] is True


def test_prepare_instagram_reel_native_cli_uses_synthetic_anchor():
    result = run_cli('prepare-instagram', value={'source': '## post:instagram_reel\nVideo gia\n',
                     'anchor': 'post:instagram_reel', 'user_id': '123', 'api_version': 'v21.0',
                     'media_type': 'REELS', 'media_url': 'https://media.example.test/video.mp4'})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['request']['params']['caption'] == 'Video gia'
    assert data['request']['params']['media_type'] == 'REELS'
    assert data['preview_only'] is True


def test_prepare_facebook_cli_keeps_comment_separate():
    result = run_cli('prepare-facebook', value={'source': '## post:facebook_post\nBai gia\n\n### comment_1\nBinh luan\n',
                     'anchor': 'post:facebook_post', 'page_id': '123', 'api_version': 'v27.0', 'media_type': 'TEXT'})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['request']['params']['message'] == 'Bai gia'
    assert data['first_comment'] == 'Binh luan'
    assert data['preview_only'] is True


def test_prepare_facebook_reel_cli_only_describes_start():
    result = run_cli('prepare-facebook-reel', value={'source': '## post:reel\nReel gia\n',
        'anchor': 'post:reel', 'page_id': '123', 'api_version': 'v27.0', 'media_id': 'fixture-video-reel'})
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['request']['params'] == {'upload_phase': 'start'}
    assert output['caption'] == 'Reel gia'
    assert output['preview_only'] is True


def test_prepare_youtube_native_cli_requires_explicit_visibility():
    result = run_cli('prepare-youtube', value={'source': '## post:youtube_desc\nMo ta gia\n',
        'anchor': 'post:youtube_desc', 'title': 'Video gia', 'category_id': '22', 'privacy': 'private',
        'made_for_kids': False, 'media_id': 'fixture-video'})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['request']['body']['status']['privacyStatus'] == 'private'
    assert data['request']['body']['snippet']['description'] == 'Mo ta gia'


def test_prepare_tiktok_inbox_is_native_and_never_publishes():
    result = run_cli('prepare-tiktok-inbox', value={'video_size': 4194304, 'chunk_size': 4194304})
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['request']['path'] == '/v2/post/publish/inbox/video/init/'
    assert data['preview_only'] is True


def test_prepare_tiktok_direct_requires_fixture_creator_choices():
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    payload = {'video_size': 4194304, 'chunk_size': 4194304, 'duration_sec': 30,
               'expected_creator': 'fixture-creator', 'expected_revision': 'fixture-revision', 'consent_fixture': True,
               'creator': {'fixture_only': True, 'fixture_creator_id': 'fixture-creator',
                           'fixture_revision': 'fixture-revision', 'privacy_level_options': ['SELF_ONLY'],
                           'comment_disabled': True, 'duet_disabled': True, 'stitch_disabled': True,
                           'max_video_post_duration_sec': 60},
               'post_info': {'title': 'Bai gia', 'privacy_level': 'SELF_ONLY', 'disable_comment': True,
                             'disable_duet': True, 'disable_stitch': True,
                             'brand_content_toggle': False, 'brand_organic_toggle': False}}
    payload['media_sha256_fixture'] = 'a' * 64
    payload['consent_digest_fixture'] = fixture_consent_digest(
        video_size=payload['video_size'], chunk_size=payload['chunk_size'], duration_sec=payload['duration_sec'],
        creator=payload['creator'], post_info=payload['post_info'], media_sha256_fixture=payload['media_sha256_fixture'])
    result = run_cli('prepare-tiktok-direct', value=payload)
    assert result.returncode == 0
    assert 'would_post_if_sent' in json.loads(result.stdout)['warnings']


def test_prepare_cli_invalid_input_does_not_echo_source():
    result = run_cli('prepare', value={'source': 'PRIVATE-SENTINEL'})
    assert result.returncode == 2
    assert 'PRIVATE-SENTINEL' not in result.stderr + result.stdout


def test_cli_has_no_submit_action():
    result = run_cli('submit')
    assert result.returncode != 0


def test_prepare_v1_cli_maps_fixture_source_to_fake_image():
    payload = {'source': '---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
                         '## post:facebook_post\nText gia\n',
               'publication': {'schema': 'publish/2', 'post_id': 'fixture-content',
                               'campaign_id': 'fixture-campaign', 'channel_id': 'fixture-brand', 'posts': [
                                   {'post_id': 'fixture-post', 'content_id': 'fixture-content',
                                    'channel': 'facebook', 'post_format': 'facebook_post',
                                    'post_content': 'post:facebook_post', 'asset_ref': ''}]},
               'post_id': 'fixture-post', 'integration_id': 'fixture-int', 'provider': 'facebook',
               'manifest': [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
                             'relative_path': 'thumbnail.png', 'kind': 'image', 'id': 'fixture-image',
                             'path': '/fixture/thumbnail.png'}],
               'settings': {'__type': 'facebook'}, 'date_utc': '2026-11-20T03:00:00Z'}
    result = run_cli('prepare-v1', value=payload)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['candidate']['posts'][0]['value'][0]['image'][0]['id'] == 'fixture-image'
    assert data['preview_only'] is True


def test_duplicate_json_key_is_rejected_without_echo():
    raw = '{"source":"PRIVATE-SENTINEL","source":"different"}'
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare'],
                            input=raw, text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert 'PRIVATE-SENTINEL' not in result.stderr + result.stdout


def test_invalid_argument_is_not_echoed():
    result = run_cli('PRIVATE-SENTINEL')
    assert result.returncode == 2
    assert 'PRIVATE-SENTINEL' not in result.stderr + result.stdout


def test_prepare_accepts_utf8_bom():
    payload = {'source': '## post:threads_post\nBai gia\n', 'anchor': 'post:threads_post',
               'integration_id': 'fixture-int', 'provider': 'threads', 'media': [],
               'settings': {'__type': 'threads'}, 'date_utc': '2026-11-20T03:00:00Z'}
    result = subprocess.run([sys.executable, '-m', 'scripts.social.cli', 'prepare'],
                            input=b'\xef\xbb\xbf' + json.dumps(payload).encode('utf-8'),
                            capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['preview_only'] is True


def test_prepare_does_not_open_network(monkeypatch, capsys):
    from scripts.social.cli import main
    def no_network(*args, **kwargs):
        raise AssertionError('network access is forbidden')
    monkeypatch.setattr(socket, 'socket', no_network)
    payload = {'source': '## post:threads_post\nSynthetic\n', 'anchor': 'post:threads_post',
               'integration_id': 'fixture-int', 'provider': 'threads', 'media': [],
               'settings': {'__type': 'threads'}, 'date_utc': '2026-11-20T03:00:00Z'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    assert main(['prepare']) == 0
    assert json.loads(capsys.readouterr().out)['preview_only'] is True


def test_prepare_linkedin_uses_direct_schema(monkeypatch):
    payload = {'source': '## post:linkedin_post\nBài giả\n', 'anchor': 'post:linkedin_post',
               'author': 'urn:li:person:fixture-member', 'api_version': '202611'}
    result = run_cli('prepare-linkedin', value=payload)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['preview_only'] is True
    assert output['request']['path'] == '/rest/posts'
    assert output['request']['body']['author'] == 'urn:li:person:fixture-member'


def test_prepare_linkedin_works_when_postiz_import_is_disabled(monkeypatch, capsys):
    from scripts.social.cli import main
    monkeypatch.setitem(sys.modules, 'scripts.lib.postiz_payload', None)
    payload = {'source': '## post:linkedin_post\nText giả\n', 'anchor': 'post:linkedin_post',
               'author': 'urn:li:person:fixture-member', 'api_version': '202611'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    assert main(['prepare-linkedin']) == 0
    assert json.loads(capsys.readouterr().out)['preview_only'] is True


def test_prepare_linkedin_does_not_use_network(monkeypatch, capsys):
    from scripts.social.cli import main
    def no_network(*args, **kwargs):
        raise AssertionError('network is forbidden')
    monkeypatch.setattr(socket, 'socket', no_network)
    payload = {'source': '## post:linkedin_post\nBài giả\n', 'anchor': 'post:linkedin_post',
               'author': 'urn:li:person:fixture-member', 'api_version': '202611',
               'media_kind': 'image', 'media_urn': 'urn:li:image:fixture-image'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    assert main(['prepare-linkedin']) == 0
    assert json.loads(capsys.readouterr().out)['preview_only'] is True


def test_fresh_cli_process_does_not_import_postiz_for_linkedin():
    payload = {'source': '## post:linkedin_post\nText gia\n', 'anchor': 'post:linkedin_post',
               'author': 'urn:li:person:fixture-member', 'api_version': '202611'}
    code = ("import sys; sys.modules['scripts.lib.postiz_payload'] = None; "
            "from scripts.social.cli import main; raise SystemExit(main(['prepare-linkedin']))")
    result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['preview_only'] is True


def test_cli_previews_linkedin_video_initialization_without_posting():
    payload = {'kind': 'video', 'owner': 'urn:li:organization:12345',
               'api_version': '202611', 'file_size': 1055736}
    result = run_cli('prepare-linkedin-media', value=payload)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output['preview_only'] is True
    assert output['request']['path'] == '/rest/videos?action=initializeUpload'
