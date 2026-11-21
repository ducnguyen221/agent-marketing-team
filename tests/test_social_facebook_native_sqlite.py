"""V1-shaped Facebook source into native SQLite fixture, no live send."""
import json
import socket
import sqlite3

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def inputs(media_type='IMAGE'):
    key = {'station_id': 'fixture-station', 'channel_id': 'fixture-brand', 'campaign_id': 'fixture-campaign',
           'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'facebook',
           'account_id': 'fixture-facebook-account-123', 'destination_id': 'fixture-facebook-page-123',
           'occurrence_key': 'fixture-slot'}
    source = ('---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
              '## post:facebook_post\nBài giả\n\n### comment_1\nBình luận giả\n')
    post = {'post_id': 'fixture-post', 'content_id': 'fixture-content', 'channel': 'facebook',
            'post_format': 'facebook_post', 'post_content': 'post:facebook_post', 'asset_ref': '',
            'review': {'status': 'approved'}}
    publication = {'schema': 'publish/2', 'post_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
                   'channel_id': 'fixture-brand', 'posts': [post]}
    manifest = ([{'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': 'thumbnail.png',
                  'kind': 'image', 'id': 'fixture-image', 'path': '/fixture/thumbnail.png'}]
                if media_type == 'IMAGE' else [])
    return {'key': key, 'source': source, 'publication': publication, 'manifest': manifest,
            'scheduled_at': '2026-11-20T03:00:00Z', 'api_version': 'v27.0', 'page_id': '123',
            'media_type': media_type}


@pytest.mark.parametrize(('kind', 'operation'), [('TEXT', 'feed'), ('IMAGE', 'photos')])
def test_native_fixture_binds_v1_without_inheriting_grant(tmp_path, monkeypatch, kind, operation):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_facebook_native_fixture(ledger, **inputs(kind))
        row = ledger.get(item)
        payload = json.loads(row['snapshot_json'])['payload']
        assert payload['candidate']['request']['path'] == f'/v27.0/123/{operation}'
        assert payload['candidate']['first_comment'] == 'Bình luận giả'
        assert 'review' not in payload['publication']['posts'][0]
        assert row['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['candidate', 'source', 'page', 'schema', 'schedule'])
def test_revision_rejects_mismatched_native_snapshot(tmp_path, change):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_facebook_native_fixture(ledger, **inputs())
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'candidate': payload['candidate']['request']['params']['caption'] = 'Sai'
        elif change == 'source': payload['source'] += 'Sai'
        elif change == 'page': payload['page_id'] = '124'
        elif change == 'schema': del payload['fixture_schema']
        else: del payload['scheduled_at']
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


def test_wrong_publication_or_media_cannot_prepare(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs()
        data['publication']['posts'][0]['content_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
        data = inputs()
        data['manifest'][0]['post_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_text_cannot_drop_explicit_v1_asset(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['publication']['posts'][0]['asset_ref'] = 'assets/required.jpg'
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
    finally:
        con.close()


def test_unrelated_malformed_publication_entry_fails_consistently(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs()
        data['publication']['posts'].append({})
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
    finally:
        con.close()


def test_generic_account_cannot_claim_reserved_native_page_namespace(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs()
        data['key']['account_id'] = 'fixture-account-other'
        with pytest.raises(ValueError):
            ledger.prepare(data['key'], {'text': 'fixture'})
    finally:
        con.close()


def test_video_asset_from_v1_post_creates_native_page_video_preview(tmp_path, monkeypatch):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['media_type'] = 'VIDEO'
        data['publication']['posts'][0]['asset_ref'] = 'video.mp4'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
                             'relative_path': 'video.mp4', 'kind': 'video',
                             'id': 'fixture-video', 'path': '/fixture/video.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        row = ledger.get(item)
        payload = json.loads(row['snapshot_json'])['payload']
        assert payload['candidate']['request']['path'] == '/v27.0/123/videos'
        assert payload['candidate']['request']['params'] == {
            'description': 'Bài giả', 'file_url': 'https://fixture.example.test/assets/fixture-video.mp4'}
        assert row['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['missing_ref', 'wrong_owner', 'wrong_kind', 'wrong_extension', 'extra_asset'])
def test_video_requires_one_explicit_matching_video_asset(tmp_path, change):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['media_type'] = 'VIDEO'
        data['publication']['posts'][0]['asset_ref'] = 'video.mp4'
        entry = {'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': 'video.mp4',
                 'kind': 'video', 'id': 'fixture-video', 'path': '/fixture/video.mp4'}
        data['manifest'] = [entry]
        if change == 'missing_ref': data['publication']['posts'][0]['asset_ref'] = ''
        elif change == 'wrong_owner': entry['post_id'] = 'fixture-other'
        elif change == 'wrong_kind': entry['kind'] = 'image'
        elif change == 'wrong_extension': data['publication']['posts'][0]['asset_ref'] = 'video.jpg'
        else: data['manifest'].append(entry.copy())
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_reel_binds_v1_anchor_and_short_asset_without_approval_transfer(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\n> Caption NGẮN đi kèm video/Reel — khác hẳn bài dài ở trên. 1–3 câu + link + ≤6 hashtag.\n\nReel giả 🎬\n'
        data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        row = ledger.get(item)
        payload = json.loads(row['snapshot_json'])['payload']
        assert payload['candidate']['caption'] == 'Reel giả 🎬'
        assert payload['candidate']['source_anchor'] == 'post:reel'
        assert payload['candidate']['request']['path'] == '/v27.0/123/video_reels'
        assert row['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['owner', 'file', 'anchor', 'source_id', 'custom_ref', 'duplicate'])
def test_reel_rejects_mismatched_source_or_media(tmp_path, change):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\nReel giả\n'
        row = data['publication']['posts'][0]
        row.update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        asset = {'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': 'short.mp4',
                 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}
        data['manifest'] = [asset]
        if change == 'owner': asset['post_id'] = 'fixture-other'
        elif change == 'file': asset.update(relative_path='video.mp4', path='/fixture/video.mp4')
        elif change == 'anchor': row['post_content'] = 'post:facebook_post'
        elif change == 'source_id': data['source'] = data['source'].replace('content_id: fixture-content', 'content_id: fixture-other')
        elif change == 'custom_ref': row['asset_ref'] = 'short.mp4'
        else: data['publication']['posts'].append(row.copy())
        with pytest.raises(ValueError):
            prepare_facebook_native_fixture(ledger, **data)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


@pytest.mark.parametrize('outcome', ['unknown', 'processing'])
def test_reel_lifecycle_persists_unknown_and_rejects_generic_finish(tmp_path, outcome):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\nReel giả\n'
        data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.reel_status(item, attempt=attempt)['phase'] == 'start_pending'
        assert ledger.reel_candidate(item, attempt=attempt)['request']['params'] == {'upload_phase': 'start'}
        with pytest.raises(ValueError):
            ledger.reel_candidate(item, attempt='fixture-attempt-other')
        with pytest.raises(ValueError):
            ledger.reel_accept_start(item, attempt=attempt, page_id='124', video_id='fixture-reel-123')
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination='fixture-facebook-page-123', remote_id='fixture-bypass')
        ledger.reel_accept_start(item, attempt=attempt, page_id='123', video_id='fixture-reel-123')
        con.close()
        con = sqlite3.connect(db)
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.reel_status(item, attempt=attempt)['phase'] == 'upload_pending'
        upload = ledger.reel_candidate(item, attempt=attempt)
        assert upload['request']['path'] == '/video-upload/v27.0/fixture-reel-123'
        assert upload['request']['headers']['file_url'] == 'https://fixture.example.test/assets/fixture-video-reel.mp4'
        assert ledger.reel_candidate(item, attempt=attempt) == upload
        assert ledger.reel_status(item, attempt=attempt)['phase'] == 'upload_pending'
        with pytest.raises(ValueError):
            ledger.reel_accept_upload(item, attempt=attempt, video_id='fixture-reel-other')
        ledger.reel_accept_upload(item, attempt=attempt, video_id='fixture-reel-123')
        con.close()
        con = sqlite3.connect(db)
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.reel_status(item, attempt=attempt)['phase'] == 'finish_pending'
        finish = ledger.reel_candidate(item, attempt=attempt)
        assert finish['request']['params']['description'] == 'Reel giả'
        assert finish['request']['params']['video_id'] == 'fixture-reel-123'
        if outcome == 'unknown':
            ledger.reel_finish_unknown(item, attempt=attempt, video_id='fixture-reel-123')
        else:
            ledger.reel_accept_finish(item, attempt=attempt, video_id='fixture-reel-123')
        con.close()
        con = sqlite3.connect(db)
        ledger = DestinationFixtureLedger.open(con)
        expected = 'unknown' if outcome == 'unknown' else 'processing_unverified'
        assert ledger.reel_status(item, attempt=attempt)['phase'] == expected
        assert ledger.get(item)['state'] == expected
        with pytest.raises(ValueError):
            ledger.reel_candidate(item, attempt=attempt)
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_reel_claim_rolls_back_when_progress_insert_fails(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\nReel giả\n'
        data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        ledger.approve(item, expected_version=1)
        def deny_insert(action, name, *_):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and name == 'reel_fixture_progress' else sqlite3.SQLITE_OK
        con.set_authorizer(deny_insert)
        with pytest.raises(sqlite3.DatabaseError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        con.set_authorizer(None)
        assert ledger.get(item)['state'] == 'prepared'
        assert ledger.get(item)['attempt_id'] is None
    finally:
        con.set_authorizer(None)
        con.close()


@pytest.mark.parametrize('phase', ['start_pending', 'upload_pending'])
def test_reel_early_unknown_persists_and_blocks_retry(tmp_path, phase):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\nReel giả\n'
        data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        video = None
        if phase == 'upload_pending':
            video = 'fixture-reel-123'
            ledger.reel_accept_start(item, attempt=attempt, page_id='123', video_id=video)
        with pytest.raises(ValueError):
            ledger.reel_mark_unknown(item, attempt=attempt, expected_phase=phase, video_id='fixture-reel-other')
        ledger.reel_mark_unknown(item, attempt=attempt, expected_phase=phase, video_id=video)
        con.close()
        con = sqlite3.connect(db)
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'unknown'
        assert ledger.reel_status(item, attempt=attempt)['phase'] == phase.replace('_pending', '_unknown')
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.reel_accept_start(item, attempt=attempt, page_id='123', video_id='fixture-reel-123')
    finally:
        con.close()


def test_reel_start_and_unknown_race_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    data = inputs('TEXT')
    data['source'] += '\n## post:reel\nReel giả\n'
    data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
    data['media_type'] = 'REEL'
    data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
        'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
    item = prepare_facebook_native_fixture(ledger, **data)
    ledger.approve(item, expected_version=1)
    attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    con.close()
    barrier = Barrier(2)

    def execute(action):
        connection = sqlite3.connect(db, timeout=10)
        try:
            session = DestinationFixtureLedger.open(connection)
            barrier.wait(timeout=5)
            try:
                if action == 'start':
                    session.reel_accept_start(item, attempt=attempt, page_id='123', video_id='fixture-reel-123')
                else:
                    session.reel_mark_unknown(item, attempt=attempt, expected_phase='start_pending', video_id=None)
                return action
            except ValueError:
                return 'refused'
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, ['start', 'unknown']))
    assert outcomes.count('refused') == 1
    con = sqlite3.connect(db)
    try:
        ledger = DestinationFixtureLedger.open(con)
        state = ledger.reel_status(item, attempt=attempt)
        if 'start' in outcomes:
            assert (state['intent'], state['phase']) == ('submitting', 'upload_pending')
        else:
            assert (state['intent'], state['phase']) == ('unknown', 'start_unknown')
    finally:
        con.close()


def test_reel_candidate_rejects_corrupted_snapshot_even_if_hash_recomputed(tmp_path):
    from scripts.social.facebook_fixture_flow import prepare_facebook_native_fixture
    from scripts.social.fixture_ledger import _snapshot_digest
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = inputs('TEXT')
        data['source'] += '\n## post:reel\nReel giả\n'
        data['publication']['posts'][0].update(post_format='reel', post_content='post:reel')
        data['media_type'] = 'REEL'
        data['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-post',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-reel', 'path': '/fixture/short.mp4'}]
        item = prepare_facebook_native_fixture(ledger, **data)
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        saved = json.loads(ledger.get(item)['snapshot_json'])
        saved['payload']['candidate']['caption'] = 'Thay nội dung'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?, snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(saved), _snapshot_digest(saved), item))
        con.commit()
        with pytest.raises(ValueError):
            ledger.reel_candidate(item, attempt=attempt)
    finally:
        con.close()
