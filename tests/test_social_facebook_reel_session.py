"""Synthetic Reel lifecycle; no network, file, credentials or real provider responses."""
import pytest

from scripts.social.channels.facebook import reel_fixture


def session():
    return reel_fixture.ReelFixtureSession(page_id='123', api_version='v27.0',
        media_id='fixture-video-reel', caption='Nội dung giả', attempt='fixture-attempt-1')


def test_reel_steps_bind_attempt_video_and_do_not_claim_publication():
    flow = session()
    upload = flow.accept_start(attempt='fixture-attempt-1', page_id='123', video_id='fixture-reel-123')
    assert upload['request']['host'] == 'rupload.facebook.com'
    assert upload['request']['path'] == '/video-upload/v27.0/fixture-reel-123'
    assert upload['request']['headers']['file_url'] == 'https://fixture.example.test/assets/fixture-video-reel.mp4'
    finish = flow.accept_upload(attempt='fixture-attempt-1', video_id='fixture-reel-123', success=True)
    assert finish['request']['params'] == {'upload_phase': 'finish', 'video_id': 'fixture-reel-123',
                                           'video_state': 'PUBLISHED', 'description': 'Nội dung giả'}
    flow.accept_finish(attempt='fixture-attempt-1', video_id='fixture-reel-123', success=True)
    assert flow.status == 'processing_unverified'


def test_lost_finish_response_stays_unknown_and_cannot_restart():
    flow = session()
    flow.accept_start(attempt='fixture-attempt-1', page_id='123', video_id='fixture-reel-123')
    flow.accept_upload(attempt='fixture-attempt-1', video_id='fixture-reel-123', success=True)
    with pytest.raises(ValueError):
        flow.finish_unknown(attempt='fixture-attempt-other', video_id='fixture-reel-123')
    with pytest.raises(ValueError):
        flow.finish_unknown(attempt='fixture-attempt-1', video_id='fixture-reel-other')
    assert flow.status == 'finish_pending'
    flow.finish_unknown(attempt='fixture-attempt-1', video_id='fixture-reel-123')
    assert flow.status == 'unknown'
    with pytest.raises(ValueError):
        flow.accept_start(attempt='fixture-attempt-1', page_id='123', video_id='fixture-reel-123')


@pytest.mark.parametrize(('attempt', 'page', 'video'), [
    ('fixture-attempt-other', '123', 'fixture-reel-123'),
    ('fixture-attempt-1', '124', 'fixture-reel-123'),
    ('fixture-attempt-1', '123', '123'),
])
def test_start_rejects_mismatched_or_real_looking_observation(attempt, page, video):
    flow = session()
    with pytest.raises(ValueError):
        flow.accept_start(attempt=attempt, page_id=page, video_id=video)


@pytest.mark.parametrize('step', ['upload_attempt', 'upload_video', 'finish_attempt', 'finish_video'])
def test_mismatched_attempt_or_video_does_not_advance(step):
    flow = session()
    flow.accept_start(attempt='fixture-attempt-1', page_id='123', video_id='fixture-reel-123')
    if step.startswith('finish'):
        flow.accept_upload(attempt='fixture-attempt-1', video_id='fixture-reel-123', success=True)
    with pytest.raises(ValueError):
        if step.startswith('upload'):
            flow.accept_upload(attempt='fixture-attempt-other' if step == 'upload_attempt' else 'fixture-attempt-1',
                               video_id='fixture-reel-other' if step == 'upload_video' else 'fixture-reel-123', success=True)
        else:
            flow.accept_finish(attempt='fixture-attempt-other' if step == 'finish_attempt' else 'fixture-attempt-1',
                               video_id='fixture-reel-other' if step == 'finish_video' else 'fixture-reel-123', success=True)
    assert flow.status == ('upload_pending' if step.startswith('upload') else 'finish_pending')
