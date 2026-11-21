"""LinkedIn-native media preparation and reconciliation without IO."""
import importlib

import pytest


def media():
    try:
        return importlib.import_module('scripts.social.channels.linkedin.media')
    except ModuleNotFoundError as exc:
        if exc.name == 'scripts.social.channels.linkedin.media':
            pytest.fail('LinkedIn native media preparation missing')
        raise


@pytest.mark.parametrize(('kind', 'size', 'path'), [
    ('image', None, '/rest/images?action=initializeUpload'),
    ('video', 1055736, '/rest/videos?action=initializeUpload'),
])
def test_initialize_native_media_preview(kind, size, path):
    result = media().preview_initialize(kind=kind, owner='urn:li:organization:12345',
                                        api_version='202611', file_size=size)
    assert result['preview_only'] is True
    assert result['request']['path'] == path
    assert result['request']['body']['initializeUploadRequest']['owner'] == 'urn:li:organization:12345'
    assert 'not_authorized' in result['warnings']


@pytest.mark.parametrize(('kind', 'size'), [('image', 1), ('video', None), ('video', 0),
                                            ('video', True), ('video', 5000000001)])
def test_initialize_rejects_wrong_or_unbounded_size(kind, size):
    with pytest.raises(ValueError):
        media().preview_initialize(kind=kind, owner='urn:li:organization:12345',
                                   api_version='202611', file_size=size)


def test_video_ranges_are_inclusive_and_clamp_final_part_at_eof():
    result = media().video_ranges(file_size=1055736,
                                  instructions=[{'firstByte': 0, 'lastByte': 4194303}])
    assert result == [{'index': 0, 'start': 0, 'end': 1055735, 'length': 1055736}]


@pytest.mark.parametrize('instructions', [
    [], [{'firstByte': 1, 'lastByte': 9}],
    [{'firstByte': 0, 'lastByte': 3}, {'firstByte': 5, 'lastByte': 9}],
    [{'firstByte': 0, 'lastByte': 5}, {'firstByte': 5, 'lastByte': 9}],
    [{'firstByte': 0, 'lastByte': 10}, {'firstByte': 11, 'lastByte': 20}],
    [{'firstByte': False, 'lastByte': 9}],
])
def test_video_ranges_refuse_missing_overlap_gaps_or_outside(instructions):
    with pytest.raises(ValueError):
        media().video_ranges(file_size=10, instructions=instructions)


def fixture_session():
    return media().video_fixture_session(owner='urn:li:organization:12345',
        video_urn='urn:li:video:fixture-video', session_id='fixture-session', file_size=10,
        instructions=[{'firstByte': 0, 'lastByte': 4}, {'firstByte': 5, 'lastByte': 12}],
        expires_at_ms=2000, file_sha256='a' * 64, upload_token='fixture-token')


def part(session, index, etag):
    entry = session['ranges'][index]
    return {'session_id': session['session_id'], 'video_urn': session['video_urn'],
            'owner': session['owner'], 'file_sha256': session['file_sha256'], 'session_digest': session['session_digest'],
            'index': index, 'start': entry['start'], 'end': entry['end'], 'etag': etag}


def test_fake_finalize_orders_part_ids_by_instruction_not_completion_order():
    session = fixture_session()
    result = media().preview_fixture_finalize(session=session, api_version='202611',
                completed=[part(session, 1, '"fixture-b"'), part(session, 0, 'fixture-a')],
                upload_token='fixture-token', now_ms=1999)
    request = result['request']['body']['finalizeUploadRequest']
    assert request['uploadedPartIds'] == ['fixture-a', 'fixture-b']
    assert result['preview_only'] is True


@pytest.mark.parametrize('variant', ['missing', 'duplicate', 'nonsynthetic', 'wrong_session',
                                     'wrong_owner', 'wrong_video', 'truncated', 'expired'])
def test_fake_finalize_rejects_incomplete_wrong_or_expired_parts(variant):
    session = fixture_session()
    completed = [part(session, 0, 'fixture-a'), part(session, 1, 'fixture-b')]
    if variant == 'missing': completed.pop()
    if variant == 'duplicate': completed[1] = dict(completed[0])
    if variant == 'nonsynthetic': completed[0]['etag'] = 'real-token'
    if variant == 'wrong_session': completed[0]['session_id'] = 'fixture-other'
    if variant == 'wrong_owner': completed[0]['owner'] = 'urn:li:organization:999'
    if variant == 'wrong_video': completed[0]['video_urn'] = 'urn:li:video:fixture-other'
    if variant == 'truncated': completed[1]['end'] -= 1
    with pytest.raises(ValueError):
        media().preview_fixture_finalize(session=session, api_version='202611', completed=completed,
                                         upload_token='fixture-token', now_ms=2000 if variant == 'expired' else 1999)


def test_readiness_requires_matching_id_owner_and_available():
    result = media().inspect_media(status=200, body={'id': 'urn:li:video:fixture-video',
              'owner': 'urn:li:organization:12345', 'status': 'AVAILABLE'},
              expected_urn='urn:li:video:fixture-video', expected_owner='urn:li:organization:12345')
    assert result == {'state': 'provider_reports_available', 'authenticated': False}


@pytest.mark.parametrize(('status', 'body'), [
    (403, {}), (200, {'id': 'urn:li:video:fixture-video', 'owner': 'urn:li:organization:999', 'status': 'AVAILABLE'}),
    (200, {'id': 'urn:li:video:other', 'owner': 'urn:li:organization:12345', 'status': 'AVAILABLE'}),
])
def test_readiness_never_assumes_ready(status, body):
    result = media().inspect_media(status=status, body=body, expected_urn='urn:li:video:fixture-video',
                                   expected_owner='urn:li:organization:12345')
    assert result == {'state': 'unverified', 'authenticated': False}


@pytest.mark.parametrize(('state', 'expected'), [
    ('WAITING_UPLOAD', 'provider_reports_waiting_upload'),
    ('PROCESSING', 'provider_reports_processing'),
    ('PROCESSING_FAILED', 'provider_reports_processing_failed'),
])
def test_matching_provider_observation_preserves_processing_state(state, expected):
    body = {'id': 'urn:li:video:fixture-video', 'owner': 'urn:li:organization:12345', 'status': state}
    assert media().inspect_media(status=200, body=body, expected_urn='urn:li:video:fixture-video',
                                 expected_owner='urn:li:organization:12345') == {
                                     'state': expected, 'authenticated': False}


def test_available_with_contradictory_failure_or_invalid_status_is_unverified():
    for provider_status, failure in [('AVAILABLE', 'ENCODING_FAILED'), ({'unexpected': 'object'}, None)]:
        body = {'id': 'urn:li:video:fixture-video', 'owner': 'urn:li:organization:12345',
                'status': provider_status, 'processingFailureReason': failure}
        result = media().inspect_media(status=200, body=body, expected_urn='urn:li:video:fixture-video',
                                       expected_owner='urn:li:organization:12345')
        assert result['state'] == 'unverified'


def test_ready_fixture_media_is_bound_to_native_post_author():
    owner = 'urn:li:organization:12345'
    urn = 'urn:li:video:fixture-video'
    result = media().preview_fixture_media_post(owner=owner, text='Video giả', api_version='202611',
                                                media_kind='video', media_urn=urn, status=200,
                                                observation={'id': urn, 'owner': owner, 'status': 'AVAILABLE'})
    assert result['preview_only'] is True
    assert result['request']['body']['author'] == owner
    assert result['request']['body']['content']['media']['id'] == urn
    assert 'fixture_observation_not_authenticated' in result['warnings']


@pytest.mark.parametrize('observation', [
    {'id': 'urn:li:video:fixture-video', 'owner': 'urn:li:organization:999', 'status': 'AVAILABLE'},
    {'id': 'urn:li:video:fixture-video', 'owner': 'urn:li:organization:12345', 'status': 'PROCESSING'},
    {'id': 'urn:li:video:other', 'owner': 'urn:li:organization:12345', 'status': 'AVAILABLE'},
])
def test_media_post_does_not_use_mismatched_or_unready_fixture(observation):
    with pytest.raises(ValueError):
        media().preview_fixture_media_post(owner='urn:li:organization:12345', text='Text', api_version='202611',
                                           media_kind='video', media_urn='urn:li:video:fixture-video',
                                           status=200, observation=observation)


def test_fixture_finalize_rejects_modified_expiry_and_wrong_token():
    session = fixture_session()
    completed = [part(session, 0, 'fixture-a'), part(session, 1, 'fixture-b')]
    altered = {**session, 'expires_at_ms': 3000}
    with pytest.raises(ValueError):
        media().preview_fixture_finalize(session=altered, api_version='202611', completed=completed,
                                         upload_token='fixture-token', now_ms=2500)
    with pytest.raises(ValueError):
        media().preview_fixture_finalize(session=session, api_version='202611', completed=completed,
                                         upload_token='fixture-other', now_ms=1999)


def test_empty_provider_token_is_supported_when_bound_to_same_fixture_session():
    session = media().video_fixture_session(owner='urn:li:organization:12345',
        video_urn='urn:li:video:fixture-video', session_id='fixture-session', file_size=10,
        instructions=[{'firstByte': 0, 'lastByte': 9}], expires_at_ms=2000,
        file_sha256='a' * 64, upload_token='')
    result = media().preview_fixture_finalize(session=session, api_version='202611',
                                               completed=[part(session, 0, 'fixture-a')],
                                               upload_token='', now_ms=1999)
    assert result['request']['body']['finalizeUploadRequest']['uploadToken'] == ''


def test_matching_body_from_403_cannot_authorize_fixture_post():
    owner, urn = 'urn:li:organization:12345', 'urn:li:video:fixture-video'
    with pytest.raises(ValueError):
        media().preview_fixture_media_post(owner=owner, text='Text', api_version='202611',
                                           media_kind='video', media_urn=urn, status=403,
                                           observation={'id': urn, 'owner': owner, 'status': 'AVAILABLE'})
