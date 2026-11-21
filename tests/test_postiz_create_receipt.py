"""Create receipts must bind to the requested integration without claiming publication."""

import importlib
import pytest


def test_create_receipt_matches_integration_independent_of_response_order():
    module = importlib.import_module('scripts.lib.postiz_payload')
    convert = getattr(module, 'match_create_receipt', None)
    assert callable(convert), 'create receipt matcher is not implemented'
    receipt = convert([
        {'postId': 'post-other', 'integration': 'other'},
        {'postId': 'post-target', 'integration': 'target'},
    ], integration_id='target')
    assert receipt == {'state': 'accepted', 'remote_job_id': 'post-target', 'integration_id': 'target'}


def test_create_receipt_ambiguous_or_missing_never_returns_acceptance():
    module = importlib.import_module('scripts.lib.postiz_payload')
    convert = getattr(module, 'match_create_receipt', None)
    assert callable(convert), 'create receipt matcher is not implemented'
    for response in ([], [{'postId': 'x', 'integration': 'other'}],
                     [{'postId': 'x', 'integration': 'target'}, {'postId': 'y', 'integration': 'target'}],
                     [{'postId': '', 'integration': 'target'}],
                     [{'postId': 'same', 'integration': 'target'}, {'postId': 'same', 'integration': 'other'}], None):
        assert convert(response, integration_id='target') is None


@pytest.mark.parametrize('title,allowed', [('A', False), ('AB', True), ('A' * 100, True), ('A' * 101, False)])
def test_youtube_candidate_title_boundaries(title, allowed):
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    def make():
        return build_postiz_create_candidate(
            integration_id='youtube-demo', provider='youtube', content='Nội dung',
            uploaded_media=[{'id': 'media-demo', 'path': '/uploads/video.mp4', 'kind': 'video'}],
            mode='draft', date_utc='2026-11-19T00:00:00Z',
            settings={'__type': 'youtube', 'title': title, 'type': 'private'},
        )
    if allowed:
        assert make()['posts'][0]['settings']['title'] == title
    else:
        with pytest.raises(ValueError):
            make()


def test_discord_candidate_binds_explicit_channel():
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    candidate = build_postiz_create_candidate(
        integration_id='discord-demo', provider='discord', content='Xin chào', uploaded_media=[],
        mode='schedule', date_utc='2026-11-20T03:00:00Z',
        settings={'__type': 'discord', 'channel': '123456'},
    )
    assert candidate['posts'][0]['settings']['channel'] == '123456'
    assert candidate['type'] == 'schedule'


@pytest.mark.parametrize('channel', ['', '  ', None, 123, 'bad\nchannel', 'general', '12 34', '00123', '18446744073709551616'])
def test_discord_candidate_rejects_missing_or_invalid_channel(channel):
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    with pytest.raises(ValueError):
        build_postiz_create_candidate(
            integration_id='discord-demo', provider='discord', content='Hi', uploaded_media=[],
            mode='schedule', date_utc='2026-11-20T03:00:00Z',
            settings={'__type': 'discord', 'channel': channel},
        )


@pytest.mark.parametrize('content,comment', [('hi @everyone', None), ('a' * 2001, None), ('hello', 'reply')])
def test_discord_candidate_rejects_unverified_message_actions(content, comment):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    with pytest.raises(ValueError):
        build_postiz_create_candidate(
            integration_id='discord-demo', provider='discord', content=content, uploaded_media=[],
            mode='draft', date_utc='2026-11-20T03:00:00Z',
            settings={'__type': 'discord', 'channel': '123456'}, first_comment=comment,
        )


def test_threads_text_candidate_is_offline_and_targets_threads():
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    result = build_postiz_create_candidate(
        integration_id='threads-demo', provider='threads', content='Xin chào', uploaded_media=[],
        mode='schedule', date_utc='2026-11-20T03:00:00Z', settings={'__type': 'threads'},
    )
    assert result['posts'][0]['integration']['id'] == 'threads-demo'
    assert result['posts'][0]['settings'] == {'__type': 'threads'}


def test_threads_candidate_rejects_unverified_media():
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    with pytest.raises(ValueError):
        build_postiz_create_candidate(
            integration_id='threads-demo', provider='threads', content='Hi',
            uploaded_media=[{'id': 'image', 'path': '/image.jpg', 'kind': 'image'}],
            mode='draft', date_utc='2026-11-20T03:00:00Z', settings={'__type': 'threads'},
        )


@pytest.mark.parametrize('content,settings,allowed', [
    ('a' * 500, {'__type': 'threads'}, True),
    ('a' * 501, {'__type': 'threads'}, False),
    ('hello', {'__type': 'threads', 'unknown': True}, False),
])
def test_threads_candidate_restricts_text_and_settings(content, settings, allowed):
    from scripts.lib.postiz_payload import build_postiz_create_candidate

    def make():
        return build_postiz_create_candidate(
            integration_id='threads-demo', provider='threads', content=content, uploaded_media=[],
            mode='draft', date_utc='2026-11-20T03:00:00Z', settings=settings,
        )
    if allowed:
        assert make()['posts'][0]['value'][0]['content'] == content
    else:
        with pytest.raises(ValueError):
            make()


@pytest.mark.parametrize('provider', ['instagram', 'instagram-standalone'])
def test_instagram_candidate_accepts_single_image_feed(provider):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    result = build_postiz_create_candidate(
        integration_id='ig-demo', provider=provider, content='Ảnh mới',
        uploaded_media=[{'id': 'img', 'path': '/uploads/a.jpg', 'kind': 'image'}],
        mode='schedule', date_utc='2026-11-20T03:00:00Z',
        settings={'__type': provider, 'post_type': 'post'},
    )
    assert result['posts'][0]['settings']['post_type'] == 'post'
    assert result['posts'][0]['value'][0]['image'][0]['id'] == 'img'


@pytest.mark.parametrize('media,settings', [
    ([], {'__type': 'instagram', 'post_type': 'post'}),
    ([{'id': 'i', 'path': '/a.jpg', 'kind': 'image'}], {'__type': 'instagram', 'post_type': 'story'}),
    ([{'id': 'i', 'path': '/a.jpg', 'kind': 'image'}], {'__type': 'instagram', 'post_type': 'post', 'audio': {}}),
])
def test_instagram_candidate_rejects_unverified_combinations(media, settings):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    with pytest.raises(ValueError):
        build_postiz_create_candidate(integration_id='ig', provider='instagram', content='Ảnh',
            uploaded_media=media, mode='draft', date_utc='2026-11-20T03:00:00Z', settings=settings)


@pytest.mark.parametrize('posting_method', ['DIRECT_POST', 'UPLOAD'])
def test_tiktok_candidate_preserves_explicit_posting_method(posting_method):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    settings = {'__type': 'tiktok', 'title': 'Video', 'privacy_level': 'SELF_ONLY',
                'duet': False, 'stitch': False, 'comment': False, 'autoAddMusic': 'no',
                'brand_content_toggle': False, 'brand_organic_toggle': False,
                'content_posting_method': posting_method}
    result = build_postiz_create_candidate(integration_id='tt', provider='tiktok', content='Mô tả',
        uploaded_media=[{'id': 'video', 'path': '/uploads/a.mp4', 'kind': 'video'}],
        mode='schedule', date_utc='2026-11-20T03:00:00Z', settings=settings)
    assert result['posts'][0]['settings']['content_posting_method'] == posting_method


@pytest.mark.parametrize('field,value', [('content_posting_method', 'other'), ('content_posting_method', []),
                                         ('privacy_level', 'unknown'), ('privacy_level', []),
                                         ('duet', 'false'), ('autoAddMusic', 'yes'), ('title', 'a' * 91)])
def test_tiktok_candidate_rejects_invalid_video_settings(field, value):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    settings = {'__type': 'tiktok', 'title': 'Video', 'privacy_level': 'SELF_ONLY',
                'duet': False, 'stitch': False, 'comment': False, 'autoAddMusic': 'no',
                'brand_content_toggle': False, 'brand_organic_toggle': False,
                'content_posting_method': 'DIRECT_POST'}
    settings[field] = value
    with pytest.raises(ValueError):
        build_postiz_create_candidate(integration_id='tt', provider='tiktok', content='Mô tả',
            uploaded_media=[{'id': 'video', 'path': '/uploads/a.mp4', 'kind': 'video'}],
            mode='schedule', date_utc='2026-11-20T03:00:00Z', settings=settings)


@pytest.mark.parametrize('privacy', ['SELF_ONLY', 'FOLLOWER_OF_CREATOR'])
def test_tiktok_direct_branded_video_rejects_private_visibility(privacy):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    settings = {'__type': 'tiktok', 'title': 'Video', 'privacy_level': privacy,
                'duet': False, 'stitch': False, 'comment': False, 'autoAddMusic': 'no',
                'brand_content_toggle': True, 'brand_organic_toggle': False,
                'content_posting_method': 'DIRECT_POST'}
    with pytest.raises(ValueError):
        build_postiz_create_candidate(integration_id='tt', provider='tiktok', content='Mô tả',
            uploaded_media=[{'id': 'video', 'path': '/uploads/a.mp4', 'kind': 'video'}],
            mode='schedule', date_utc='2026-11-20T03:00:00Z', settings=settings)


@pytest.mark.parametrize('provider', ['instagram', 'instagram-standalone'])
@pytest.mark.parametrize('size,allowed', [(2200, True), (2201, False)])
def test_instagram_caption_size(provider, size, allowed):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    def make():
        return build_postiz_create_candidate(integration_id='ig', provider=provider, content='a' * size,
            uploaded_media=[{'id': 'i', 'path': '/a.jpg', 'kind': 'image'}], mode='draft',
            date_utc='2026-11-20T03:00:00Z', settings={'__type': provider, 'post_type': 'post'})
    if allowed:
        assert len(make()['posts'][0]['value'][0]['content']) == size
    else:
        with pytest.raises(ValueError):
            make()


def test_tiktok_inbox_success_never_implies_publication():
    module = importlib.import_module('scripts.lib.postiz_payload')
    interpret_tiktok_status = getattr(module, 'interpret_tiktok_status', None)
    assert callable(interpret_tiktok_status), 'TikTok status interpretation is not implemented'
    assert interpret_tiktok_status('UPLOAD', 'published') == 'awaiting_creator'
    assert interpret_tiktok_status('UPLOAD', 'PUBLISHED') == 'awaiting_creator'
    assert interpret_tiktok_status('DIRECT_POST', 'published') == 'unknown'
    assert interpret_tiktok_status('UPLOAD', 'unknown') == 'unknown'


def test_batch_preview_prepares_multiple_channels_in_order():
    module = importlib.import_module('scripts.lib.postiz_payload')
    preview = getattr(module, 'build_postiz_batch_preview', None)
    assert callable(preview), 'batch preview is not implemented'
    requests = [
        {'ref': 'slot-a', 'integration_id': 'threads-one', 'provider': 'threads',
         'content': 'Xin chào', 'uploaded_media': [], 'mode': 'schedule',
         'date_utc': '2026-11-20T03:00:00Z', 'settings': {'__type': 'threads'}},
        {'ref': 'slot-b', 'integration_id': 'discord-one', 'provider': 'discord',
         'content': 'Tin mới', 'uploaded_media': [], 'mode': 'schedule',
         'date_utc': '2026-11-20T04:00:00Z', 'settings': {'__type': 'discord', 'channel': '123'}},
    ]
    result = preview(requests)
    assert [item['ref'] for item in result] == ['slot-a', 'slot-b']
    assert [item['candidate']['date'] for item in result] == ['2026-11-20T03:00:00Z', '2026-11-20T04:00:00Z']
    assert [item['candidate']['posts'][0]['integration']['id'] for item in result] == ['threads-one', 'discord-one']


@pytest.mark.parametrize('requests', [[], [{'ref': 'x'}, {'ref': 'x'}], None])
def test_batch_preview_rejects_invalid_input_without_partial_results(requests):
    module = importlib.import_module('scripts.lib.postiz_payload')
    preview = getattr(module, 'build_postiz_batch_preview', None)
    assert callable(preview), 'batch preview is not implemented'
    with pytest.raises(ValueError):
        preview(requests)


def test_batch_preview_rejects_duplicate_refs_after_a_valid_item():
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    item = {'ref': 'same', 'integration_id': 'threads-one', 'provider': 'threads',
            'content': 'Xin chào', 'uploaded_media': [], 'mode': 'schedule',
            'date_utc': '2026-11-20T03:00:00Z', 'settings': {'__type': 'threads'}}
    with pytest.raises(ValueError):
        build_postiz_batch_preview([item, dict(item)])


def test_batch_preview_caps_total_text_before_constructing_candidates():
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    item = {'ref': 'one', 'integration_id': 'li', 'provider': 'linkedin',
            'content': 'a' * 1_000_000, 'uploaded_media': [], 'mode': 'draft',
            'date_utc': '2026-11-20T03:00:00Z', 'settings': {'__type': 'linkedin'}}
    with pytest.raises(ValueError):
        build_postiz_batch_preview([item, dict(item, ref='two'), dict(item, ref='three')])


def test_batch_preview_rejects_invalid_item_after_valid_one():
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    item = {'ref': 'one', 'integration_id': 'i', 'provider': 'threads', 'content': 'Hi',
            'uploaded_media': [], 'mode': 'draft', 'date_utc': '2026-11-20T03:00:00Z',
            'settings': {'__type': 'threads'}}
    with pytest.raises(ValueError):
        build_postiz_batch_preview([item, dict(item, ref='two', settings={'__type': 'wrong'})])


@pytest.mark.parametrize('count,allowed', [(100, True), (101, False)])
def test_batch_preview_item_count_boundary(count, allowed):
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    item = {'integration_id': 'i', 'provider': 'threads', 'content': 'Hi',
            'uploaded_media': [], 'mode': 'draft', 'date_utc': '2026-11-20T03:00:00Z',
            'settings': {'__type': 'threads'}}
    batch = [dict(item, ref='slot-' + str(index)) for index in range(count)]
    if allowed:
        assert len(build_postiz_batch_preview(batch)) == count
    else:
        with pytest.raises(ValueError):
            build_postiz_batch_preview(batch)


def test_x_candidate_preserves_reply_policy_for_text_post():
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    candidate = build_postiz_create_candidate(
        integration_id='x-demo', provider='x', content='Một thông tin mới', uploaded_media=[],
        mode='schedule', date_utc='2026-11-20T03:00:00Z',
        settings={'__type': 'x', 'who_can_reply_post': 'everyone', 'made_with_ai': False},
    )
    assert candidate['posts'][0]['settings']['who_can_reply_post'] == 'everyone'
    assert candidate['posts'][0]['value'][0]['content'] == 'Một thông tin mới'


@pytest.mark.parametrize('settings', [
    {'__type': 'x'},
    {'__type': 'x', 'who_can_reply_post': 'unknown'},
    {'__type': 'x', 'who_can_reply_post': []},
    {'__type': 'x', 'who_can_reply_post': 'everyone', 'post_type': 'article'},
    {'__type': 'x', 'who_can_reply_post': 'everyone', 'made_with_ai': 'false'},
    {'__type': 'x', 'who_can_reply_post': 'everyone', 'community': 'https://example.invalid'},
])
def test_x_candidate_rejects_unverified_settings(settings):
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    with pytest.raises(ValueError):
        build_postiz_create_candidate(integration_id='x', provider='x', content='Nội dung',
            uploaded_media=[], mode='draft', date_utc='2026-11-20T03:00:00Z', settings=settings)


def test_x_preview_does_not_claim_weighted_length_validation():
    from scripts.lib.postiz_payload import build_postiz_create_candidate
    content = 'Long URL: https://example.invalid/' + 'a' * 300
    candidate = build_postiz_create_candidate(
        integration_id='x', provider='x', content=content, uploaded_media=[], mode='draft',
        date_utc='2026-11-20T03:00:00Z', settings={'__type': 'x', 'who_can_reply_post': 'everyone'})
    assert candidate['posts'][0]['value'][0]['content'] == content


def test_batch_preview_warns_when_x_length_has_not_been_verified():
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    result = build_postiz_batch_preview([{
        'ref': 'x1', 'integration_id': 'x', 'provider': 'x', 'content': 'Hello', 'uploaded_media': [],
        'mode': 'draft', 'date_utc': '2026-11-20T03:00:00Z',
        'settings': {'__type': 'x', 'who_can_reply_post': 'everyone'},
    }])
    assert 'x_weighted_length_unchecked' in result[0]['warnings']


def test_batch_preview_warns_tiktok_inbox_is_not_publication():
    from scripts.lib.postiz_payload import build_postiz_batch_preview
    settings = {'__type': 'tiktok', 'title': 'Video', 'privacy_level': 'SELF_ONLY',
                'duet': False, 'stitch': False, 'comment': False, 'autoAddMusic': 'no',
                'brand_content_toggle': False, 'brand_organic_toggle': False,
                'content_posting_method': 'UPLOAD'}
    result = build_postiz_batch_preview([{
        'ref': 'tt1', 'integration_id': 'tt', 'provider': 'tiktok', 'content': 'Video',
        'uploaded_media': [{'id': 'v', 'path': '/a.mp4', 'kind': 'video'}], 'mode': 'draft',
        'date_utc': '2026-11-20T03:00:00Z', 'settings': settings,
    }])
    assert 'tiktok_upload_awaits_creator_and_ignores_settings' in result[0]['warnings']


def test_postiz_list_observation_matches_exact_post_and_integration():
    module = importlib.import_module('scripts.lib.postiz_payload')
    observe = getattr(module, 'inspect_postiz_list_response', None)
    assert callable(observe), 'Postiz list observer is not implemented'
    response = {'posts': [
        {'id': 'other', 'state': 'PUBLISHED', 'integration': {'id': 'i'}},
        {'id': 'job-1', 'state': 'QUEUE', 'integration': {'id': 'i'}},
    ]}
    assert observe(response, remote_job_id='job-1', integration_id='i') == 'accepted'
    assert observe(response, remote_job_id='job-1', integration_id='wrong') == 'unknown'


def test_postiz_list_observation_never_guesses_after_lost_ack():
    module = importlib.import_module('scripts.lib.postiz_payload')
    observe = getattr(module, 'inspect_postiz_list_response', None)
    assert callable(observe), 'Postiz list observer is not implemented'
    item = {'id': 'job', 'state': 'PUBLISHED', 'integration': {'id': 'i'}}
    assert observe({'posts': [item]}, remote_job_id=None, integration_id='i') == 'unknown'
    assert observe({'posts': [item, dict(item)]}, remote_job_id='job', integration_id='i') == 'unknown'
    assert observe({'posts': [item]}, remote_job_id='job', integration_id='i') == 'unknown'


def test_postiz_list_observation_recognizes_tiktok_inbox_only_with_matching_mode():
    module = importlib.import_module('scripts.lib.postiz_payload')
    observe = getattr(module, 'inspect_postiz_list_response', None)
    assert callable(observe), 'Postiz list observer is not implemented'
    item = {'id': 'job', 'state': 'PUBLISHED', 'integration': {'id': 'i', 'providerIdentifier': 'tiktok'},
            'settings': {'content_posting_method': 'UPLOAD'}}
    assert observe({'posts': [item]}, remote_job_id='job', integration_id='i',
                   expected_posting_method='UPLOAD') == 'awaiting_creator'
    assert observe({'posts': [item]}, remote_job_id='job', integration_id='i',
                   expected_posting_method='DIRECT_POST') == 'unknown'


def test_postiz_list_observation_rejects_conflicting_error_and_provider():
    from scripts.lib.postiz_payload import inspect_postiz_list_response
    item = {'id': 'job', 'state': 'QUEUE', 'integration': {'id': 'i'}, 'error': 'upstream error'}
    assert inspect_postiz_list_response({'posts': [item]}, remote_job_id='job', integration_id='i') == 'unknown'
    tiktok = {'id': 'job', 'state': 'PUBLISHED', 'integration': {'id': 'i', 'providerIdentifier': 'tiktok'},
              'settings': {'__type': 'facebook', 'content_posting_method': 'UPLOAD'}}
    assert inspect_postiz_list_response({'posts': [tiktok]}, remote_job_id='job', integration_id='i',
                                        expected_posting_method='UPLOAD') == 'unknown'
    tiktok['settings']['__type'] = 'tiktok'
    tiktok['error'] = 'upstream error'
    assert inspect_postiz_list_response({'posts': [tiktok]}, remote_job_id='job', integration_id='i',
                                        expected_posting_method='UPLOAD') == 'unknown'
