"""Synthetic TikTok native requests and status, never network or secrets."""
from pathlib import Path
import pytest


def test_inbox_upload_candidate_is_not_a_published_post():
    module = Path(__file__).resolve().parents[1] / 'scripts/social/channels/tiktok/direct.py'
    assert module.exists(), 'native TikTok preview is missing'
    from scripts.social.channels.tiktok.direct import preview_inbox_upload
    result = preview_inbox_upload(video_size=4_194_304, chunk_size=4_194_304)
    assert result['preview_only'] is True
    assert result['request']['path'] == '/v2/post/publish/inbox/video/init/'
    assert result['request']['body']['source_info']['total_chunk_count'] == 1
    assert 'creator_action_required_if_delivered' in result['warnings']


def test_final_chunk_absorbs_remainder_instead_of_adding_small_part():
    from scripts.social.channels.tiktok.direct import preview_file_chunks
    result = preview_file_chunks(video_size=50_000_123, chunk_size=10_000_000)
    assert result['source_info']['total_chunk_count'] == 5
    assert result['chunks'][-1] == {'start': 40_000_000, 'end': 50_000_122, 'length': 10_000_123}


def test_maximum_chunk_count_boundary_is_enforced():
    from scripts.social.channels.tiktok.direct import preview_file_chunks
    assert len(preview_file_chunks(video_size=10_000_000_000, chunk_size=10_000_000)['chunks']) == 1000
    with pytest.raises(ValueError):
        preview_file_chunks(video_size=10_010_000_000, chunk_size=10_000_000)


@pytest.mark.parametrize(('size', 'chunk'), [(0, 1), (True, 1), (1, 2), (4_000_000, 2_000_000),
                                            (70_000_000, 70_000_000), (5_000_000_001, 5_000_000)])
def test_bad_chunk_configuration_is_rejected(size, chunk):
    from scripts.social.channels.tiktok.direct import preview_file_chunks
    with pytest.raises(ValueError):
        preview_file_chunks(video_size=size, chunk_size=chunk)


def test_direct_post_checks_creator_settings_and_synthetic_consent():
    from scripts.social.channels.tiktok import direct
    assert hasattr(direct, 'preview_direct_post')
    creator = creator_fixture()
    post = {'title': 'Bài giả', 'privacy_level': 'SELF_ONLY', 'disable_comment': True, 'disable_duet': True,
            'disable_stitch': True, 'brand_content_toggle': False, 'brand_organic_toggle': False}
    result = direct.preview_direct_post(video_size=4_194_304, chunk_size=4_194_304, duration_sec=30,
        creator=creator, expected_creator='fixture-creator', expected_revision='fixture-revision',
        consent_fixture=True, post_info=post, **consent_args(post, creator))
    assert result['request']['path'] == '/v2/post/publish/video/init/'
    assert 'would_post_if_sent' in result['warnings']


def test_tiktok_native_inbox_status_distinguishes_inbox_from_creator_published():
    from scripts.social.channels.tiktok import direct
    assert hasattr(direct, 'observe_status')
    pending = direct.observe_status(mode='INBOX', expected_publish_id='fixture-job',
        observed_publish_id='fixture-job', http_status=200, body={'data': {'status': 'SEND_TO_USER_INBOX'}, 'error': {'code': 'ok'}})
    done = direct.observe_status(mode='INBOX', expected_publish_id='fixture-job',
        observed_publish_id='fixture-job', http_status=200, body={'data': {'status': 'PUBLISH_COMPLETE'}, 'error': {'code': 'ok'}})
    assert pending['state'] == 'awaiting_creator'
    assert done['state'] == 'provider_reports_published'
    assert done['visibility'] == 'unverified'


def creator_fixture():
    return {'fixture_only': True, 'fixture_creator_id': 'fixture-creator', 'fixture_revision': 'fixture-revision',
            'privacy_level_options': ['SELF_ONLY'], 'comment_disabled': True,
            'duet_disabled': True, 'stitch_disabled': True, 'max_video_post_duration_sec': 60}


def post_fixture():
    return {'title': 'Test', 'privacy_level': 'SELF_ONLY', 'disable_comment': True, 'disable_duet': True,
            'disable_stitch': True, 'brand_content_toggle': False, 'brand_organic_toggle': False}


def consent_args(post, creator, duration=30):
    from scripts.social.channels.tiktok.direct import fixture_consent_digest
    media = 'a' * 64
    digest = fixture_consent_digest(video_size=4_194_304, chunk_size=4_194_304, duration_sec=duration,
                                    creator=creator, post_info=post, media_sha256_fixture=media)
    return {'media_sha256_fixture': media, 'consent_digest_fixture': digest}


@pytest.mark.parametrize(('which', 'value'), [('privacy_level', 'PUBLIC_TO_EVERYONE'),
                                             ('disable_comment', False), ('disable_duet', False),
                                             ('disable_stitch', False), ('brand_content_toggle', 1),
                                             ('title', '😀' * 1101), ('title', '{{draft}}')])
def test_direct_post_rejects_unavailable_choices_and_invalid_title(which, value):
    from scripts.social.channels.tiktok.direct import preview_direct_post
    post = post_fixture()
    post[which] = value
    with pytest.raises(ValueError):
        preview_direct_post(video_size=4_194_304, chunk_size=4_194_304, duration_sec=30,
                            creator=creator_fixture(), expected_creator='fixture-creator', expected_revision='fixture-revision',
                            consent_fixture=True, post_info=post, **consent_args(post, creator_fixture()))


def test_direct_requires_fixture_consent_and_creator_duration_limit():
    from scripts.social.channels.tiktok.direct import preview_direct_post
    for consent, duration in [(False, 30), (True, 61), (1, 30)]:
        with pytest.raises(ValueError):
            preview_direct_post(video_size=4_194_304, chunk_size=4_194_304, duration_sec=duration,
                                creator=creator_fixture(), expected_creator='fixture-creator', expected_revision='fixture-revision',
                                consent_fixture=consent, post_info=post_fixture(),
                                **consent_args(post_fixture(), creator_fixture(), duration))


@pytest.mark.parametrize(('mode', 'status', 'expected'), [
    ('INBOX', 'PROCESSING_UPLOAD', 'processing'), ('DIRECT', 'PROCESSING_DOWNLOAD', 'unknown'),
    ('DIRECT', 'SEND_TO_USER_INBOX', 'unknown'), ('DIRECT', 'PUBLISH_COMPLETE', 'provider_reports_published'),
    ('INBOX', 'FAILED', 'provider_reports_failed'), ('INBOX', 'OTHER', 'unknown'),
])
def test_native_status_mapping_never_claims_authenticated_or_public(mode, status, expected):
    from scripts.social.channels.tiktok.direct import observe_status
    result = observe_status(mode=mode, expected_publish_id='fixture-job', observed_publish_id='fixture-job',
                            http_status=200, body={'data': {'status': status}, 'error': {'code': 'ok'}})
    assert result == {'state': expected, 'visibility': 'unverified', 'authenticated': False}


def test_wrong_job_or_error_cannot_mark_published():
    from scripts.social.channels.tiktok.direct import observe_status
    body = {'data': {'status': 'PUBLISH_COMPLETE'}, 'error': {'code': 'ok'}}
    assert observe_status(mode='INBOX', expected_publish_id='fixture-job', observed_publish_id='fixture-other',
                          http_status=200, body=body)['state'] == 'unknown'
    body['error']['code'] = 'invalid_token'
    assert observe_status(mode='INBOX', expected_publish_id='fixture-job', observed_publish_id='fixture-job',
                          http_status=200, body=body)['state'] == 'unknown'


def test_direct_rejects_branded_private_and_wrong_creator():
    from scripts.social.channels.tiktok.direct import preview_direct_post
    args = {'video_size': 4_194_304, 'chunk_size': 4_194_304, 'duration_sec': 30, 'creator': creator_fixture(),
            'expected_creator': 'fixture-creator', 'expected_revision': 'fixture-revision', 'consent_fixture': True,
            'post_info': {**post_fixture(), 'brand_content_toggle': True}}
    args.update(consent_args(args['post_info'], args['creator']))
    with pytest.raises(ValueError):
        preview_direct_post(**args)
    with pytest.raises(ValueError):
        preview_direct_post(**{**args, 'post_info': post_fixture(), 'expected_creator': 'fixture-other',
                               **consent_args(post_fixture(), args['creator'])})


def test_status_rejects_http_failure_contradiction_and_wrong_transfer():
    from scripts.social.channels.tiktok.direct import observe_status
    args = {'mode': 'INBOX', 'expected_publish_id': 'fixture-job', 'observed_publish_id': 'fixture-job',
            'body': {'data': {'status': 'PUBLISH_COMPLETE'}, 'error': {'code': 'ok'}}}
    assert observe_status(**args, http_status=403)['state'] == 'unknown'
    args['body']['data']['fail_reason'] = 'auth_removed'
    assert observe_status(**args, http_status=200)['state'] == 'unknown'
    args['body']['data'] = {'status': 'PROCESSING_DOWNLOAD'}
    assert observe_status(**args, http_status=200)['state'] == 'unknown'


def test_fixture_consent_must_match_exact_post_and_media():
    from scripts.social.channels.tiktok import direct
    assert hasattr(direct, 'fixture_consent_digest')
    args = {'video_size': 4_194_304, 'chunk_size': 4_194_304, 'duration_sec': 30, 'creator': creator_fixture(),
            'expected_creator': 'fixture-creator', 'expected_revision': 'fixture-revision',
            'consent_fixture': True, 'post_info': post_fixture(), 'media_sha256_fixture': 'a' * 64}
    digest = direct.fixture_consent_digest(video_size=args['video_size'], chunk_size=args['chunk_size'],
        duration_sec=args['duration_sec'], creator=args['creator'], post_info=args['post_info'],
        media_sha256_fixture=args['media_sha256_fixture'])
    direct.preview_direct_post(**args, consent_digest_fixture=digest)
    with pytest.raises(ValueError):
        direct.preview_direct_post(**{**args, 'post_info': {**args['post_info'], 'title': 'changed'}},
                                   consent_digest_fixture=digest)
    with pytest.raises(ValueError):
        direct.preview_direct_post(**{**args, 'video_size': 4_194_305, 'chunk_size': 4_194_305},
                                   consent_digest_fixture=digest)
