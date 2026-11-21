"""YouTube videos.insert metadata preview from synthetic source."""
import pytest


def test_marketing_description_builds_native_candidate_without_media_bytes():
    from scripts.social.channels.youtube.direct import preview_marketing_anchor
    result = preview_marketing_anchor(source='## post:youtube_desc\nMô tả giả\n', anchor='post:youtube_desc',
        title='Video giả', category_id='22', privacy='private', made_for_kids=False, media_id='fixture-video')
    body = result['request']['body']
    assert body['snippet']['description'] == 'Mô tả giả'
    assert body['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}
    assert result['request']['path'] == '/upload/youtube/v3/videos'
    assert result['media_id'] == 'fixture-video' and result['preview_only'] is True
    assert 'would_upload_if_sent' in result['warnings']


@pytest.mark.parametrize('privacy', [None, '', 'friends'])
def test_privacy_must_be_explicit_and_valid(privacy):
    from scripts.social.channels.youtube.direct import preview_video
    with pytest.raises(ValueError):
        preview_video(title='Video', description='Mô tả', category_id='22', privacy=privacy,
                      made_for_kids=False, media_id='fixture-video')


def test_description_limit_is_bytes_not_characters():
    from scripts.social.channels.youtube.direct import preview_video
    args = {'title': 'Video', 'category_id': '22', 'privacy': 'private', 'made_for_kids': False,
            'media_id': 'fixture-video'}
    preview_video(**args, description='é' * 2500)
    with pytest.raises(ValueError):
        preview_video(**args, description='é' * 2501)


@pytest.mark.parametrize('source', ['## post:youtube_desc\nMô tả\n<!-- nội bộ -->\n',
                                   '## post:youtube_desc\nMô tả {{BLOG_URL}}\n'])
def test_hidden_metadata_and_unresolved_placeholder_are_refused(source):
    from scripts.social.channels.youtube.direct import preview_marketing_anchor
    with pytest.raises(ValueError):
        preview_marketing_anchor(source=source, anchor='post:youtube_desc', title='Video', category_id='22',
                                 privacy='private', made_for_kids=False, media_id='fixture-video')


def test_registry_reports_native_preview_without_live():
    from scripts.social.capabilities import capabilities
    item = capabilities(platform='youtube', destination='channel', action='post_video')
    assert item['preview_schema'] == 'youtube_native'
    assert item['live_enabled'] is False


@pytest.mark.parametrize('text', ['\u200d', '\u0301', '  '])
def test_nonempty_invisible_description_is_rejected(text):
    from scripts.social.channels.youtube.direct import preview_video
    with pytest.raises(ValueError):
        preview_video(title='Video', description=text, category_id='22', privacy='private',
                      made_for_kids=False, media_id='fixture-video')


def test_subscriber_notification_default_is_flagged():
    from scripts.social.channels.youtube.direct import preview_video
    result = preview_video(title='Video', description='', category_id='22', privacy='public',
                           made_for_kids=False, media_id='fixture-video')
    assert 'notify_subscribers_defaults_true_delivery_unverified' in result['warnings']
@pytest.mark.parametrize('body', [
    'Hook giả',
    '**Caption:** Một\n\n**Caption:** Hai',
    ' **Caption:** Một\n\n**Caption:** Hai',
    '**Caption:** Một\nDòng hai',
    '**Caption:** Một <!-- nội bộ -->',
])
def test_short_rejects_missing_or_ambiguous_caption(body):
    from scripts.social.channels.youtube.direct import preview_marketing_anchor
    with pytest.raises(ValueError):
        preview_marketing_anchor(source='## post:youtube_short\n' + body, anchor='post:youtube_short',
                                 title='Short giả', category_id='22', privacy='private',
                                 made_for_kids=False, media_id='fixture-video')
