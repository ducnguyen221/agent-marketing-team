"""Exercise synthetic V1 content anchors through offline Postiz candidates."""
import importlib

import pytest


def preview(**kwargs):
    try:
        module = importlib.import_module('scripts.social.fixture_preview')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.fixture_preview':
            pytest.fail('offline marketing-content preview not implemented')
        raise
    return module.preview_fixture(**kwargs)


@pytest.mark.parametrize(('provider', 'anchor', 'media', 'settings'), [
    ('linkedin', 'post:linkedin_post', [], {'__type': 'linkedin'}),
    ('facebook', 'post:facebook_post', [{'id': 'fixture-image', 'path': '/fixture/image.png', 'kind': 'image'}], {'__type': 'facebook'}),
    ('youtube', 'post:youtube_desc', [{'id': 'fixture-video', 'path': '/fixture/video.mp4', 'kind': 'video'}], {'__type': 'youtube', 'title': 'Fixture video', 'type': 'private'}),
])
def test_v1_anchor_content_and_fake_media_become_preview_candidates(provider, anchor, media, settings):
    source = f'# Fixture\n\n## {anchor}\n\nNoi dung gia\n'
    result = preview(source=source, anchor=anchor, integration_id='fixture-integration', provider=provider,
                     media=media, settings=settings, date_utc='2026-11-20T03:00:00Z')
    assert result['preview_only'] is True
    assert result['candidate']['posts'][0]['value'][0]['content'].strip() == 'Noi dung gia'
    assert len(result['candidate']['posts'][0]['value'][0]['image']) == len(media)


def test_facebook_metadata_is_not_sent_as_post_body():
    result = preview(source='## post:facebook_post\nBody\n### comment_1\nLink gia\n### image_prompt\nVe anh\n',
                     anchor='post:facebook_post', integration_id='fixture-fb', provider='facebook',
                     media=[], settings={'__type': 'facebook'}, date_utc='2026-11-20T03:00:00Z')
    values = result['candidate']['posts'][0]['value']
    assert values[0]['content'].strip() == 'Body'
    assert values[1]['content'].strip() == 'Link gia'
    assert 'Ve anh' not in str(values)


def test_real_media_reference_rejected():
    with pytest.raises(ValueError):
        preview(source='## post:infographic\nNoi dung\n', anchor='post:infographic',
                integration_id='fixture-ig', provider='instagram',
                media=[{'id': 'fixture-image', 'path': 'https://example.com/a.png', 'kind': 'image'}],
                settings={'__type': 'instagram', 'post_type': 'post'}, date_utc='2026-11-20T03:00:00Z')


def test_instagram_infographic_does_not_leak_internal_sections():
    source = '## post:infographic\n**Tiêu đề trên hình:** Nội bộ\n\n**Các khối nội dung:** Nội bộ\n\n**Caption:** Noi dung gia\n'
    result = preview(source=source, anchor='post:infographic', integration_id='fixture-ig', provider='instagram',
                     media=[{'id': 'fixture-image', 'path': '/fixture/image.png', 'kind': 'image'}],
                     settings={'__type': 'instagram', 'post_type': 'post'}, date_utc='2026-11-20T03:00:00Z')
    assert result['candidate']['posts'][0]['value'][0]['content'] == 'Noi dung gia'


def test_reject_cross_channel_anchor():
    with pytest.raises(ValueError):
        preview(source='## post:facebook_post\nNoi dung\n### image_prompt\nBi mat\n',
                anchor='post:facebook_post', integration_id='fixture-li', provider='linkedin', media=[],
                settings={'__type': 'linkedin'}, date_utc='2026-11-20T03:00:00Z')


@pytest.mark.parametrize('body', [
    '```\n**Caption:** Not a caption\n```',
    '**Caption:** One\n\n**Caption:** Two',
    '**Caption:** First line\nSecond line',
    '**Caption:** First\nSecond\n\n**Caption:** Other',
    '**Caption:** Caption <!-- internal note -->',
    '**Caption:** First\n\nSecond paragraph',
])
def test_instagram_caption_must_be_an_unambiguous_top_level_single_line(body):
    with pytest.raises(ValueError):
        preview(source='## post:infographic\n' + body + '\n', anchor='post:infographic',
                integration_id='fixture-ig', provider='instagram',
                media=[{'id': 'fixture-image', 'path': '/fixture/image.png', 'kind': 'image'}],
                settings={'__type': 'instagram', 'post_type': 'post'}, date_utc='2026-11-20T03:00:00Z')


@pytest.mark.parametrize(('provider', 'anchor', 'media', 'settings'), [
    ('threads', 'post:threads_post', [], {'__type': 'threads'}),
    ('discord', 'post:discord_post', [], {'__type': 'discord', 'channel': '123456'}),
    ('x', 'post:x_post', [], {'__type': 'x', 'who_can_reply_post': 'everyone'}),
    ('tiktok', 'post:tiktok_post', [{'id': 'fixture-video', 'path': '/fixture/video.mp4', 'kind': 'video'}],
     {'__type': 'tiktok', 'title': 'Fixture', 'privacy_level': 'SELF_ONLY', 'duet': False,
      'stitch': False, 'comment': True, 'autoAddMusic': 'no', 'brand_content_toggle': False,
      'brand_organic_toggle': False, 'content_posting_method': 'UPLOAD'}),
])
def test_additional_channel_formats_are_offline_candidates(provider, anchor, media, settings):
    result = preview(source=f'## {anchor}\nSynthetic text\n', anchor=anchor,
                     integration_id='fixture-destination', provider=provider, media=media,
                     settings=settings, date_utc='2026-11-20T03:00:00Z')
    assert result['candidate']['posts'][0]['value'][0]['content'].strip() == 'Synthetic text'
    assert result['preview_only'] is True
    if provider == 'tiktok':
        assert 'awaiting_creator' in result['warnings']
        assert 'upload_ignores_some_settings' in result['warnings']


@pytest.mark.parametrize('body', ['Hello\n### image_prompt\nInternal', 'Hello <!-- internal -->'])
def test_experimental_text_anchor_rejects_embedded_metadata(body):
    with pytest.raises(ValueError):
        preview(source=f'## post:x_post\n{body}\n', anchor='post:x_post', integration_id='fixture-x',
                provider='x', media=[], settings={'__type': 'x', 'who_can_reply_post': 'everyone'},
                date_utc='2026-11-20T03:00:00Z')


def test_threads_limit_excludes_only_final_markdown_linebreak():
    result = preview(source='## post:threads_post\n' + 'a' * 500 + '\n', anchor='post:threads_post',
                     integration_id='fixture-t', provider='threads', media=[], settings={'__type': 'threads'},
                     date_utc='2026-11-20T03:00:00Z')
    assert len(result['candidate']['posts'][0]['value'][0]['content']) == 500


def test_discord_settings_cannot_include_internal_metadata():
    with pytest.raises(ValueError):
        preview(source='## post:discord_post\nHi\n', anchor='post:discord_post', integration_id='fixture-d',
                provider='discord', media=[], settings={'__type': 'discord', 'channel': '123456',
                                                         'operator_note': 'internal'},
                date_utc='2026-11-20T03:00:00Z')
