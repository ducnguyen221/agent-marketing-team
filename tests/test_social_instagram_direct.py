"""Instagram native preview from synthetic marketing content, without network."""
import pytest


def test_image_uses_infographic_caption_not_internal_prompt():
    from scripts.social.channels.instagram.direct import preview_marketing_anchor
    result = preview_marketing_anchor(source='## post:infographic\nPrompt nội bộ\n\n**Caption:** Xin chào\n',
        anchor='post:infographic', user_id='123', api_version='v21.0', media_type='IMAGE',
        media_url='https://media.example.test/image.jpg')
    assert result['request']['params'] == {'image_url': 'https://media.example.test/image.jpg', 'caption': 'Xin chào'}
    assert result['request']['path'] == '/v21.0/123/media'
    assert result['preview_only'] is True


def test_reel_uses_video_and_synthetic_anchor():
    from scripts.social.channels.instagram.direct import preview_marketing_anchor
    result = preview_marketing_anchor(source='## post:instagram_reel\nVideo giả\n', anchor='post:instagram_reel',
        user_id='123', api_version='v21.0', media_type='REELS', media_url='https://media.example.test/reel.mp4')
    assert result['request']['params'] == {'media_type': 'REELS', 'video_url': 'https://media.example.test/reel.mp4',
                                          'caption': 'Video giả'}
    assert 'synthetic_anchor_not_v1_enum' in result['warnings']


@pytest.mark.parametrize('url', ['http://example.test/a', 'https://127.0.0.1/a', 'https://localhost/a',
                                  'https://user:pass@example.test/a', 'https://example.test/a?token=secret'])
def test_unsafe_media_urls_are_rejected(url):
    from scripts.social.channels.instagram.direct import preview_container
    with pytest.raises(ValueError):
        preview_container(user_id='123', api_version='v21.0', media_type='IMAGE', media_url=url, caption='Hi')


@pytest.mark.parametrize('source', ['## post:infographic\nNo caption\n',
    '## post:infographic\n**Caption:** One\n\n**Caption:** Two\n',
    '## post:infographic\n**Caption:** One\nHidden continuation\n'])
def test_ambiguous_infographic_fails_closed(source):
    from scripts.social.channels.instagram.direct import preview_marketing_anchor
    with pytest.raises(ValueError):
        preview_marketing_anchor(source=source, anchor='post:infographic', user_id='123', api_version='v21.0',
                                 media_type='IMAGE', media_url='https://media.example.test/image.jpg')


def test_publish_preview_does_not_claim_readiness():
    from scripts.social.channels.instagram.direct import preview_publish
    result = preview_publish(user_id='123', api_version='v21.0', creation_id='456')
    assert result['request']['params'] == {'creation_id': '456'}
    assert 'would_publish_if_sent' in result['warnings']


@pytest.mark.parametrize('caption', ['\u200d', '\u0301', '   '])
def test_nonempty_invisible_caption_is_rejected(caption):
    from scripts.social.channels.instagram.direct import preview_container
    with pytest.raises(ValueError):
        preview_container(user_id='123', api_version='v21.0', media_type='IMAGE',
                          media_url='https://media.example.test/image.jpg', caption=caption)


def test_empty_caption_and_visible_emoji_are_supported():
    from scripts.social.channels.instagram.direct import preview_container
    args = {'user_id': '123', 'api_version': 'v21.0', 'media_type': 'IMAGE',
            'media_url': 'https://media.example.test/image.jpg'}
    assert 'caption' not in preview_container(**args, caption='')['request']['params']
    assert preview_container(**args, caption='👩\u200d💻')['request']['params']['caption'] == '👩\u200d💻'


@pytest.mark.parametrize('action', ['post_image', 'post_video'])
def test_registry_marks_instagram_native_offline(action):
    from scripts.social.capabilities import capabilities
    result = capabilities(platform='instagram', destination='account', action=action)
    assert result['preview_schema'] == 'instagram_native' and result['live_enabled'] is False
