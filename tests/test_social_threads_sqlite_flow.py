"""Synthetic marketing-to-Threads SQLite flow; no account or network access."""
import json
import hashlib
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def key(user_id='123'):
    return {'station_id': 'fixture-station', 'channel_id': 'fixture-channel', 'campaign_id': 'fixture-campaign',
            'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'threads',
            'account_id': 'fixture-threads-account-' + user_id, 'destination_id': 'fixture-threads-' + user_id,
            'occurrence_key': 'fixture-slot'}


def target(user_id='123'):
    return {'platform': 'threads', 'account_id': 'fixture-threads-account-' + user_id,
            'destination_id': 'fixture-threads-' + user_id, 'threads_user_id': user_id}


def test_threads_preview_and_time_survive_reopen(tmp_path):
    module = Path(__file__).resolve().parents[1] / 'scripts/social/threads_fixture_flow.py'
    assert module.exists(), 'Threads SQLite fixture flow is missing'
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    db = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(db)
    ledger = DestinationFixtureLedger.initialize(con)
    item = prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nHello\n',
                                   anchor='post:threads_post', api_version='v1.0', media_type='TEXT',
                                   scheduled_at='2026-11-20T03:00:00Z')
    con.close()
    con = sqlite3.connect(db)
    try:
        row = DestinationFixtureLedger.open(con).get(item)
        payload = json.loads(row['snapshot_json'])['payload']
        assert payload['scheduled_at'] == '2026-11-20T03:00:00Z'
        assert payload['candidate']['request']['params']['text'] == 'Hello'
        assert payload['source_identity'] == 'caller_text_only'
        assert payload['source_sha256'] == hashlib.sha256(b'## post:threads_post\nHello\n').hexdigest()
        assert row['state'] == 'prepared' and row['grant_version'] is None
    finally:
        con.close()


@pytest.mark.parametrize(('media_type', 'media_url', 'field'), [
    ('IMAGE', 'https://fixture.example.test/assets/fixture-image.jpg', 'image_url'),
    ('VIDEO', 'https://fixture.example.test/assets/fixture-video.mp4', 'video_url'),
])
def test_fixture_media_is_bound_into_snapshot(tmp_path, media_type, media_url, field):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nMedia\n',
                                       anchor='post:threads_post', api_version='v1.0', media_type=media_type,
                                       scheduled_at='2026-11-20T03:00:00Z', media_url=media_url)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['candidate']['request']['params'][field] == media_url
    finally:
        con.close()


def test_mismatched_target_cannot_create_intent(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=key(), target=target('124'),
                                    source='## post:threads_post\nText\n', anchor='post:threads_post',
                                    api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


@pytest.mark.parametrize('bad_time', ['2026-11-20T03:00:00', '2026-02-31T03:00:00Z', 'now', '2026-11-20T03:00:00+07:00'])
def test_invalid_or_ambiguous_schedule_refused(tmp_path, bad_time):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nText\n',
                                    anchor='post:threads_post', api_version='v1.0', media_type='TEXT',
                                    scheduled_at=bad_time)
    finally:
        con.close()


def test_fixture_flow_never_opens_network_and_keeps_destinations_independent(tmp_path, monkeypatch):
    import socket
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    monkeypatch.setattr(socket, 'socket', lambda *args, **kwargs: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = {'source': '## post:threads_post\nText\n', 'anchor': 'post:threads_post',
                'api_version': 'v1.0', 'media_type': 'TEXT', 'scheduled_at': '2026-11-20T03:00:00Z'}
        a = prepare_threads_fixture(ledger, key=key(), target=target(), **args)
        b = prepare_threads_fixture(ledger, key=key('124'), target=target('124'), **args)
        assert a != b
        assert prepare_threads_fixture(ledger, key=key(), target=target(), **args) == a
        ledger.approve(a, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T02:59:59Z')['due'] == []
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [a]
        ledger.claim_due(a, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == []
        assert ledger.get(b)['state'] == 'prepared' and ledger.get(b)['grant_version'] is None
    finally:
        con.close()


def test_same_native_user_cannot_be_aliased_as_another_destination(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        fake_key = {**key(), 'destination_id': 'fixture-alias', 'account_id': 'fixture-other'}
        fake_target = {**target(), 'destination_id': 'fixture-alias', 'account_id': 'fixture-other'}
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=fake_key, target=fake_target, source='## post:threads_post\nText\n',
                                    anchor='post:threads_post', api_version='v1.0', media_type='TEXT',
                                    scheduled_at='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_source_frontmatter_must_match_fixture_identity(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        source = ('---\nschema: content/1\ncontent_id: fixture-other\ncampaign_id: fixture-other\n---\n'
                  '## post:threads_post\nText\n')
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=key(), target=target(), source=source, anchor='post:threads_post',
                                    api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('user_id', ['0', '0123'])
def test_threads_user_id_requires_canonical_positive_decimal(tmp_path, user_id):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=key(user_id), target=target(user_id),
                                    source='## post:threads_post\nText\n', anchor='post:threads_post',
                                    api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_matching_caller_metadata_is_recorded_but_not_authenticated(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        source = ('---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
                  '## post:threads_post\nText\n')
        item = prepare_threads_fixture(ledger, key=key(), target=target(), source=source, anchor='post:threads_post',
                                       api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['source_identity'] == 'caller_metadata_matches_unverified'
    finally:
        con.close()


def test_real_media_url_and_changed_snapshot_are_not_silently_accepted(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = {'key': key(), 'target': target(), 'source': '## post:threads_post\nText\n', 'anchor': 'post:threads_post',
                'api_version': 'v1.0', 'media_type': 'TEXT', 'scheduled_at': '2026-11-20T03:00:00Z'}
        prepare_threads_fixture(ledger, **args)
        with pytest.raises(ValueError, match='conflict'):
            prepare_threads_fixture(ledger, **{**args, 'scheduled_at': '2026-11-21T03:00:00Z'})
        with pytest.raises(ValueError, match='fixture media'):
            prepare_threads_fixture(ledger, **{**args, 'media_type': 'IMAGE', 'media_url': 'https://real.example/image.jpg'})
    finally:
        con.close()


@pytest.mark.parametrize('change', ['candidate', 'source', 'target', 'anchor', 'schedule', 'schema'])
def test_threads_revision_rejects_inconsistent_snapshot(tmp_path, change):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nText\n',
            anchor='post:threads_post', api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'candidate': payload['candidate']['request']['params']['text'] = 'Khác'
        elif change == 'source': payload['source'] = 'changed'
        elif change == 'target': payload['target']['threads_user_id'] = '124'
        elif change == 'anchor': payload['anchor'] = 'post:threads_post#2'
        elif change == 'schedule': del payload['scheduled_at']
        else: payload.pop('fixture_schema', None)
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


def test_generic_account_cannot_reserve_threads_native_destination(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        identity = key()
        identity['account_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            ledger.prepare(identity, {'text': 'fixture'})
    finally:
        con.close()


def test_threads_due_rechecks_snapshot_even_with_new_checksum(tmp_path):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    from scripts.social.fixture_ledger import _snapshot_digest
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nText\n',
            anchor='post:threads_post', api_version='v1.0', media_type='TEXT', scheduled_at='2026-11-20T03:00:00Z')
        ledger.approve(item, expected_version=1)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])
        snapshot['payload']['candidate']['request']['params']['text'] = 'Khác'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?,snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(snapshot), _snapshot_digest(snapshot), item))
        con.commit()
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['invalid'] == [item]
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize(('kind', 'url'), [('IMAGE', 'https://fixture.example.test/assets/fixture-video.mp4'),
                                           ('VIDEO', 'https://fixture.example.test/assets/fixture-image.jpg')])
def test_fixture_media_label_must_match_kind(tmp_path, kind, url):
    from scripts.social.threads_fixture_flow import prepare_threads_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_threads_fixture(ledger, key=key(), target=target(), source='## post:threads_post\nText\n',
                anchor='post:threads_post', api_version='v1.0', media_type=kind, media_url=url,
                scheduled_at='2026-11-20T03:00:00Z')
    finally:
        con.close()
