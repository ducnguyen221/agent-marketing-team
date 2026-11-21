"""Threads native payload previews, entirely offline."""
from pathlib import Path
import pytest


def test_text_container_preview_is_native_and_never_auto_publishes():
    path = Path(__file__).resolve().parents[1] / 'scripts/social/channels/threads/direct.py'
    assert path.exists(), 'native Threads preview is missing'
    from scripts.social.channels.threads.direct import preview_container
    candidate = preview_container(user_id='123', api_version='v1.0', media_type='TEXT', text='Xin chào')
    assert candidate['request']['path'] == '/v1.0/123/threads'
    assert candidate['request']['params'] == {'media_type': 'TEXT', 'text': 'Xin chào'}
    assert candidate['preview_only'] is True


@pytest.mark.parametrize(('kind', 'field'), [('IMAGE', 'image_url'), ('VIDEO', 'video_url')])
def test_media_container_uses_correct_url_field(kind, field):
    from scripts.social.channels.threads.direct import preview_container
    result = preview_container(user_id='123', api_version='v1.0', media_type=kind, text='caption',
                               media_url='https://media.example.test/fixture.jpg')
    assert result['request']['params'][field] == 'https://media.example.test/fixture.jpg'
    assert 'auto_publish_text' not in result['request']['params']


@pytest.mark.parametrize('url', ['http://example.test/a', 'https://localhost/a', 'https://127.0.0.1/a',
                                 'https://user:password@example.test/a', 'https://example.test/a?token=secret',
                                 'https://example.test/a#fragment'])
def test_media_url_rejects_obvious_unsafe_or_secret_bearing_values(url):
    from scripts.social.channels.threads.direct import preview_container
    with pytest.raises(ValueError):
        preview_container(user_id='123', api_version='v1.0', media_type='IMAGE', media_url=url)


@pytest.mark.parametrize('kwargs', [
    {'user_id': '../me', 'api_version': 'v1.0', 'media_type': 'TEXT', 'text': 'A'},
    {'user_id': '123', 'api_version': 'v1.0', 'media_type': 'TEXT', 'text': ' '},
    {'user_id': '123', 'api_version': 'v1.0', 'media_type': 'TEXT', 'text': 'A', 'media_url': 'https://example.test/a'},
    {'user_id': '123', 'api_version': 'v1.0', 'media_type': 'IMAGE'},
    {'user_id': '123', 'api_version': 'v1.0', 'media_type': 'VIDEO', 'text': 'a\x00b'},
])
def test_invalid_inputs_are_rejected(kwargs):
    from scripts.social.channels.threads.direct import preview_container
    with pytest.raises(ValueError):
        preview_container(**kwargs)


def test_publish_preview_requires_container_and_warns_it_would_publish():
    from scripts.social.channels.threads.direct import preview_publish
    result = preview_publish(user_id='123', api_version='v1.0', creation_id='456')
    assert result['request']['params'] == {'creation_id': '456'}
    assert 'would_publish_if_sent' in result['warnings']
    with pytest.raises(ValueError):
        preview_publish(user_id='123', api_version='v1.0', creation_id='bad')


def test_marketing_anchor_preserves_text_and_rejects_internal_heading():
    from scripts.social.channels.threads import direct
    assert hasattr(direct, 'preview_marketing_anchor')
    result = direct.preview_marketing_anchor(source='## post:threads_post\nBài thử\n', anchor='post:threads_post',
                                            user_id='123', api_version='v1.0', media_type='TEXT')
    assert result['request']['params']['text'] == 'Bài thử'
    with pytest.raises(ValueError):
        direct.preview_marketing_anchor(source='## post:threads_post\n### Nội bộ\nBài\n', anchor='post:threads_post',
                                       user_id='123', api_version='v1.0', media_type='TEXT')


@pytest.mark.parametrize('action', ['post_text', 'post_image', 'post_video'])
def test_registry_exposes_native_preview_without_live(action):
    from scripts.social.capabilities import capabilities
    result = capabilities(platform='threads', destination='account', action=action)
    assert result['preview_schema'] == 'threads_native'
    assert result['live_enabled'] is False


@pytest.mark.parametrize('text', ['\u200d', '{{draft}}', ' \u200d '])
def test_empty_joiner_or_unresolved_placeholder_rejected(text):
    from scripts.social.channels.threads.direct import preview_container
    with pytest.raises(ValueError):
        preview_container(user_id='123', api_version='v1.0', media_type='TEXT', text=text)


def test_windows_newline_and_emoji_are_preserved():
    from scripts.social.channels.threads.direct import preview_container
    result = preview_container(user_id='123', api_version='v1.0', media_type='TEXT', text='Một\r\n👩\u200d💻')
    assert result['request']['params']['text'] == 'Một\n👩\u200d💻'
