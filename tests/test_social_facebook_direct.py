"""Native Page preview from synthetic Facebook marketing output."""
import pytest


def test_page_text_keeps_first_comment_separate_from_post():
    from scripts.social.channels.facebook.direct import preview_marketing_anchor
    result = preview_marketing_anchor(source='## post:facebook_post\nBài giả\n\n### comment_1\nBình luận giả\n',
        anchor='post:facebook_post', page_id='123', api_version='v27.0', media_type='TEXT')
    assert result['request']['path'] == '/v27.0/123/feed'
    assert result['request']['params']['message'] == 'Bài giả'
    assert result['first_comment'] == 'Bình luận giả'
    assert 'Bình luận giả' not in result['request']['params']['message']
    assert result['preview_only'] is True


def test_page_photo_omits_image_prompt_from_caption():
    from scripts.social.channels.facebook.direct import preview_marketing_anchor
    result = preview_marketing_anchor(source='## post:facebook_post\nBài giả\n\n### image_prompt\nMô tả nội bộ\n',
        anchor='post:facebook_post', page_id='123', api_version='v27.0', media_type='IMAGE',
        media_url='https://media.example.test/image.jpg')
    assert result['request']['path'] == '/v27.0/123/photos'
    assert result['request']['params'] == {'caption': 'Bài giả', 'url': 'https://media.example.test/image.jpg'}
    assert result['image_prompt_present'] is True


@pytest.mark.parametrize('bad', ['', '   ', '\u200d', '{{draft}}', 'Hi\x00'])
def test_invalid_body_fails_closed(bad):
    from scripts.social.channels.facebook.direct import preview_post
    with pytest.raises(ValueError):
        preview_post(page_id='123', api_version='v27.0', media_type='TEXT', message=bad)


@pytest.mark.parametrize('url', ['http://example.test/a', 'https://127.0.0.1/a',
                                 'https://user:pass@example.test/a', 'https://example.test/a?token=secret'])
def test_invalid_media_url_is_not_returned(url):
    from scripts.social.channels.facebook.direct import preview_post
    with pytest.raises(ValueError):
        preview_post(page_id='123', api_version='v27.0', media_type='IMAGE', message='Hi', media_url=url)


def test_comment_preview_is_separate_and_requires_composite_post_id():
    from scripts.social.channels.facebook.direct import preview_comment
    result = preview_comment(page_id='123', post_id='123_456', api_version='v27.0', message='Bình luận giả')
    assert result['request']['path'] == '/v27.0/123_456/comments'
    assert 'would_comment_if_sent' in result['warnings']
    with pytest.raises(ValueError):
        preview_comment(page_id='123', post_id='999_456', api_version='v27.0', message='Bình luận giả')


@pytest.mark.parametrize('source', [
    '## post:facebook_post\nBài giả\n\n<!-- ghi chú nội bộ -->\n',
    '## post:facebook_post\nBài giả\n\n### comment_1\nBình luận <!-- ghi chú -->\n',
    '## post:facebook_post\nBài giả\n\n[link]: https://example.test\n',
])
def test_marketing_anchor_rejects_hidden_html_or_reference_definitions(source):
    from scripts.social.channels.facebook.direct import preview_marketing_anchor
    with pytest.raises(ValueError):
        preview_marketing_anchor(source=source, anchor='post:facebook_post', page_id='123',
                                 api_version='v27.0', media_type='TEXT')


@pytest.mark.parametrize('action', ['post_text', 'post_image'])
def test_registry_exposes_native_page_preview_only(action):
    from scripts.social.capabilities import capabilities
    data = capabilities(platform='facebook', destination='page', action=action)
    assert data['preview_schema'] == 'facebook_native' and data['live_enabled'] is False
def test_reel_preview_excludes_v1_instruction_and_describes_start_only():
    from scripts.social.channels.facebook.direct import preview_reel_anchor
    result = preview_reel_anchor(source='## post:reel\n> Caption NGẮN đi kèm video/Reel — khác hẳn bài dài ở trên. 1–3 câu + link + ≤6 hashtag.\n\nVideo giả 🎬\n\n#gia\n',
                                 anchor='post:reel', page_id='123', api_version='v27.0',
                                 media_id='fixture-video-reel')
    assert result['caption'] == 'Video giả 🎬\n\n#gia'
    assert result['request']['path'] == '/v27.0/123/video_reels'
    assert result['request']['params'] == {'upload_phase': 'start'}
    assert result['media_id'] == 'fixture-video-reel'
    assert 'not_uploaded' in result['warnings']


@pytest.mark.parametrize('body', [
    '> Chỉ hướng dẫn\n',
    'Nội dung\n\n> Mơ hồ\n',
    '> Trích dẫn khách hàng\n\nNội dung\n',
    'Nội dung <!-- nội bộ -->\n',
    '{{chưa điền}}',
])
def test_reel_preview_rejects_ambiguous_or_unfilled_caption(body):
    from scripts.social.channels.facebook.direct import preview_reel_anchor
    with pytest.raises(ValueError):
        preview_reel_anchor(source='## post:reel\n' + body, anchor='post:reel', page_id='123',
                            api_version='v27.0', media_id='fixture-video-reel')
