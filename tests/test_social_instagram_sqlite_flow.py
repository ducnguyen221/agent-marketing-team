"""Instagram marketing fixtures through a disposable SQLite ledger."""
import json
import socket
import sqlite3

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def key(user='123'):
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'instagram',
            'account_id': 'fixture-instagram-account-' + user, 'destination_id': 'fixture-instagram-' + user,
            'occurrence_key': 'fixture-slot'}


def args(user='123', media_type='IMAGE'):
    image = media_type == 'IMAGE'
    return {'key': key(user), 'user_id': user, 'source': ('## post:infographic\nPrompt\n\n**Caption:** Xin chào\n'
            if image else '## post:instagram_reel\nVideo giả\n'),
            'anchor': 'post:infographic' if image else 'post:instagram_reel', 'api_version': 'v21.0',
            'media_type': media_type, 'scheduled_at': '2026-11-20T03:00:00Z',
            'media_url': 'https://fixture.example.test/assets/fixture-media.jpg' if image else
                         'https://fixture.example.test/assets/fixture-video.mp4'}


def test_existing_native_fixture_generic_finish_remains_supported(tmp_path):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_instagram_fixture(ledger, **args())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish(item, attempt=attempt, destination='fixture-instagram-123', remote_id='fixture-existing')
        assert ledger.get(item)['state'] == 'accepted'
    finally:
        con.close()


@pytest.mark.parametrize(('media_type', 'field'), [('IMAGE', 'image_url'), ('REELS', 'video_url')])
def test_marketing_media_reaches_due_fixture_without_network(tmp_path, monkeypatch, media_type, field):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw: pytest.fail('network called'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_instagram_fixture(ledger, **args(media_type=media_type))
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['candidate']['request']['params'][field] == args(media_type=media_type)['media_url']
        assert ledger.get(item)['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [item]
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['candidate', 'source', 'destination', 'schedule', 'schema'])
def test_inconsistent_snapshot_revision_is_refused(tmp_path, change):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_instagram_fixture(ledger, **args())
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'candidate': payload['candidate']['request']['params']['caption'] = 'Khác'
        elif change == 'source': payload['source'] += 'Thêm'
        elif change == 'destination': payload['user_id'] = '124'
        elif change == 'schedule': del payload['scheduled_at']
        else: del payload['fixture_schema']
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


@pytest.mark.parametrize('change', ['user', 'url', 'source_metadata'])
def test_unbound_target_real_url_and_wrong_source_cannot_prepare(tmp_path, change):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = args()
        if change == 'user': data['user_id'] = '124'
        elif change == 'url': data['media_url'] = 'https://real.example/media.jpg'
        else: data['source'] = '---\nschema: content/1\ncontent_id: other\ncampaign_id: fixture-campaign\n---\n' + data['source']
        with pytest.raises(ValueError):
            prepare_instagram_fixture(ledger, **data)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_corrupt_candidate_with_recomputed_hash_cannot_be_claimed(tmp_path):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    from scripts.social.fixture_ledger import _snapshot_digest
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_instagram_fixture(ledger, **args())
        ledger.approve(item, expected_version=1)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])
        snapshot['payload']['candidate']['request']['params']['caption'] = 'Khác'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?,snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(snapshot), _snapshot_digest(snapshot), item))
        con.commit()
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['invalid'] == [item]
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_two_accounts_and_grants_stay_separate(tmp_path):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        first = prepare_instagram_fixture(ledger, **args('123'))
        second = prepare_instagram_fixture(ledger, **args('456'))
        ledger.approve_batch([(first, 1), (second, 1)])
        ledger.revoke(first, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [second]
    finally:
        con.close()


@pytest.mark.parametrize(('kind', 'name'), [('IMAGE', 'fixture-video.mp4'), ('REELS', 'fixture-image.jpg')])
def test_fixture_media_labels_cannot_contradict_media_type(tmp_path, kind, name):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = args(media_type=kind)
        data['media_url'] = 'https://fixture.example.test/assets/' + name
        with pytest.raises(ValueError):
            prepare_instagram_fixture(ledger, **data)
    finally:
        con.close()


@pytest.mark.parametrize('missing', ['content_id', 'campaign_id'])
def test_missing_identity_has_consistent_value_error(tmp_path, missing):
    from scripts.social.instagram_fixture_flow import prepare_instagram_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        data = args()
        del data['key'][missing]
        with pytest.raises(ValueError):
            prepare_instagram_fixture(ledger, **data)
    finally:
        con.close()
