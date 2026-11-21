"""Synthetic V1-shaped video output to a native YouTube ledger fixture."""
import json
import socket
import sqlite3

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def data():
    key = {'station_id': 'fixture-station', 'channel_id': 'fixture-brand', 'campaign_id': 'fixture-campaign',
           'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'youtube',
           'account_id': 'fixture-youtube-account-abc', 'destination_id': 'fixture-youtube-channel-abc',
           'occurrence_key': 'fixture-slot'}
    source = ('---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
              '## post:youtube_desc\nMô tả giả\n')
    post = {'post_id': 'fixture-post', 'content_id': 'fixture-content', 'channel': 'youtube',
            'post_format': 'youtube_video', 'post_content': 'post:youtube_desc', 'asset_ref': '',
            'review': {'status': 'approved'}}
    publication = {'schema': 'publish/2', 'post_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
                   'channel_id': 'fixture-brand', 'posts': [post]}
    manifest = [{'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': path, 'kind': kind,
                 'id': 'fixture-' + kind, 'path': '/fixture/' + path}
                for path, kind in [('video.mp4', 'video'), ('thumbnail.png', 'image')]]
    return {'key': key, 'source': source, 'publication': publication, 'manifest': manifest,
            'scheduled_at': '2026-11-20T03:00:00Z', 'title': 'Video giả', 'category_id': '22',
            'privacy': 'private', 'made_for_kids': False}


def test_video_and_thumbnail_are_separate_and_grant_not_inherited(tmp_path, monkeypatch):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_youtube_native_fixture(ledger, **data())
        row = ledger.get(item)
        payload = json.loads(row['snapshot_json'])['payload']
        assert payload['candidate']['media_id'] == 'fixture-video'
        assert payload['thumbnail']['id'] == 'fixture-image'
        assert 'thumbnail' not in payload['candidate']['request']['body']
        assert 'review' not in payload['publication']['posts'][0] and row['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['candidate', 'source', 'thumbnail', 'schema', 'schedule'])
def test_revision_rejects_inconsistent_snapshot(tmp_path, change):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_youtube_native_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'candidate': payload['candidate']['request']['body']['snippet']['title'] = 'Khác'
        elif change == 'source': payload['source'] += 'Khác'
        elif change == 'thumbnail': payload['thumbnail']['id'] = 'fixture-other'
        elif change == 'schema': del payload['fixture_schema']
        else: del payload['scheduled_at']
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


@pytest.mark.parametrize('change', ['metadata', 'manifest', 'target', 'anchor'])
def test_mismatched_source_and_assets_refused_before_write(tmp_path, change):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data()
        if change == 'metadata': args['source'] = args['source'].replace('content_id: fixture-content', 'content_id: fixture-other')
        elif change == 'manifest': args['manifest'][1]['post_id'] = 'fixture-other'
        elif change == 'target': args['key']['destination_id'] = 'fixture-youtube-channel-other'
        else: args['publication']['posts'][0]['post_content'] = 'post:facebook_post'
        with pytest.raises(ValueError):
            prepare_youtube_native_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_recomputed_hash_does_not_hide_corrupted_metadata(tmp_path):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    from scripts.social.fixture_ledger import _snapshot_digest
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_youtube_native_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])
        snapshot['payload']['candidate']['request']['body']['status']['privacyStatus'] = 'public'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?,snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(snapshot), _snapshot_digest(snapshot), item))
        con.commit()
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['invalid'] == [item]
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_reserved_youtube_channel_rejects_generic_account(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        key = data()['key']
        key['account_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            ledger.prepare(key, {'text': 'fixture'})
    finally:
        con.close()


@pytest.mark.parametrize('reverse', [False, True])
def test_video_and_thumbnail_cannot_share_fixture_id(tmp_path, reverse):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data()
        args['manifest'][1]['id'] = args['manifest'][0]['id']
        if reverse:
            args['manifest'].reverse()
        with pytest.raises(ValueError):
            prepare_youtube_native_fixture(ledger, **args)
    finally:
        con.close()


def test_selects_short_and_long_from_same_v1_source_without_inheriting_approval(tmp_path):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        long = data()
        long['source'] += '\n## post:youtube_short\n**Hook (1–3s):** Không công khai\n\n**Caption:** Short giả\n'
        short = json.loads(json.dumps(long))
        short['key']['post_id'] = 'fixture-short'
        short['publication']['posts'].append({'post_id': 'fixture-short', 'content_id': 'fixture-content',
            'channel': 'youtube', 'post_format': 'youtube_short', 'post_content': 'post:youtube_short',
            'asset_ref': '', 'review': {'status': 'approved'}})
        long['publication'] = short['publication']
        short['manifest'] = [{'content_id': 'fixture-content', 'post_id': 'fixture-short',
            'relative_path': 'short.mp4', 'kind': 'video', 'id': 'fixture-video-short', 'path': '/fixture/short.mp4'}]
        long_item = prepare_youtube_native_fixture(ledger, **long)
        short_item = prepare_youtube_native_fixture(ledger, **short)
        long_payload = json.loads(ledger.get(long_item)['snapshot_json'])['payload']
        short_payload = json.loads(ledger.get(short_item)['snapshot_json'])['payload']
        assert long_payload['candidate']['source_anchor'] == 'post:youtube_desc'
        assert long_payload['candidate']['media_id'] == 'fixture-video'
        assert short_payload['candidate']['source_anchor'] == 'post:youtube_short'
        assert short_payload['candidate']['media_id'] == 'fixture-video-short'
        assert short_payload['candidate']['request']['body']['snippet']['description'] == 'Short giả'
        assert 'shorts_classification_unverified' in short_payload['candidate']['warnings']
        assert short_payload['thumbnail'] is None
        assert ledger.get(short_item)['grant_version'] is None
        ledger.approve(short_item, expected_version=1)
        assert ledger.claim_due(short_item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['anchor', 'owner', 'missing', 'wrong_file', 'custom_ref', 'extra'])
def test_short_rejects_wrong_anchor_or_asset_before_write(tmp_path, change):
    from scripts.social.youtube_fixture_flow import prepare_youtube_native_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data()
        args['source'] += '\n## post:youtube_short\n**Caption:** Short giả\n'
        row = args['publication']['posts'][0]
        row.update(post_format='youtube_short', post_content='post:youtube_short')
        entry = {'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': 'short.mp4',
                 'kind': 'video', 'id': 'fixture-video-short', 'path': '/fixture/short.mp4'}
        args['manifest'] = [entry]
        if change == 'anchor': row['post_content'] = 'post:youtube_desc'
        elif change == 'owner': entry['post_id'] = 'fixture-other'
        elif change == 'missing': args['manifest'] = []
        elif change == 'wrong_file': entry.update(relative_path='video.mp4', path='/fixture/video.mp4')
        elif change == 'custom_ref': row['asset_ref'] = 'custom.mp4'
        else: args['manifest'].append(entry.copy())
        with pytest.raises(ValueError):
            prepare_youtube_native_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()
