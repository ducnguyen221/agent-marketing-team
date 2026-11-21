"""V1-shaped synthetic output to a destination-aware SQLite fixture."""
import json
import hashlib
import sqlite3
import copy
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def inputs():
    key = {'station_id': 'fixture-station', 'channel_id': 'fixture-brand', 'campaign_id': 'fixture-campaign',
           'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'facebook',
           'account_id': 'fixture-account', 'destination_id': 'fixture-page', 'occurrence_key': 'fixture-slot'}
    source = ('---\nschema: content/1\ncontent_id: fixture-content\ncampaign_id: fixture-campaign\n---\n'
              '## post:facebook_post\nBai gia\n')
    publication = {'schema': 'publish/2', 'post_id': 'fixture-content', 'campaign_id': 'fixture-campaign',
                   'channel_id': 'fixture-brand', 'posts': [{'post_id': 'fixture-post', 'content_id': 'fixture-content',
                       'channel': 'facebook', 'post_format': 'facebook_post', 'post_content': 'post:facebook_post', 'asset_ref': ''}]}
    manifest = [{'content_id': 'fixture-content', 'post_id': 'fixture-post', 'relative_path': 'thumbnail.png',
                 'kind': 'image', 'id': 'fixture-image', 'path': '/fixture/thumbnail.png'}]
    return key, source, publication, manifest


def test_facebook_source_and_image_are_bound_to_occurrence(tmp_path):
    module = Path(__file__).resolve().parents[1] / 'scripts/social/v1_fixture_flow.py'
    assert module.exists(), 'V1 fixture flow is missing'
    from scripts.social.v1_fixture_flow import prepare_facebook_v1_fixture
    key, source, publication, manifest = inputs()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_facebook_v1_fixture(ledger, key=key, source=source, publication=publication, manifest=manifest,
                                           scheduled_at='2026-11-20T03:00:00Z')
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['candidate']['candidate']['posts'][0]['value'][0]['content'] == 'Bai gia\n'
        assert payload['candidate']['candidate']['posts'][0]['integration']['id'] == 'fixture-page'
        assert payload['source_sha256'] == hashlib.sha256(source.encode('utf-8')).hexdigest()
        assert ledger.get(item)['grant_version'] is None
    finally:
        con.close()


@pytest.mark.parametrize('field', ['channel_id', 'campaign_id', 'content_id', 'post_id'])
def test_v1_source_key_mismatch_fails_before_writing(tmp_path, field):
    from scripts.social.v1_fixture_flow import prepare_facebook_v1_fixture
    key, source, publication, manifest = inputs()
    key[field] = 'fixture-wrong'
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_facebook_v1_fixture(ledger, key=key, source=source, publication=publication, manifest=manifest,
                                        scheduled_at='2026-11-20T03:00:00Z')
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_v1_fixture_manifest_mismatch_rejected(tmp_path):
    from scripts.social.v1_fixture_flow import prepare_facebook_v1_fixture
    key, source, publication, manifest = inputs()
    manifest[0]['post_id'] = 'fixture-wrong'
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_facebook_v1_fixture(ledger, key=key, source=source, publication=publication, manifest=manifest,
                                        scheduled_at='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_same_page_is_idempotent_and_wrong_account_cannot_duplicate(tmp_path):
    from scripts.social.v1_fixture_flow import prepare_facebook_v1_fixture
    key, source, publication, manifest = inputs()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        publication = copy.deepcopy(publication)
        publication['posts'][0]['review'] = {'status': 'approved'}
        args = {'source': source, 'publication': publication, 'manifest': manifest, 'scheduled_at': '2026-11-20T03:00:00Z'}
        item = prepare_facebook_v1_fixture(ledger, key=key, **args)
        assert prepare_facebook_v1_fixture(ledger, key=key, **args) == item
        assert ledger.get(item)['grant_version'] is None
        with pytest.raises(ValueError):
            prepare_facebook_v1_fixture(ledger, key={**key, 'account_id': 'fixture-alternate'}, **args)
    finally:
        con.close()


@pytest.mark.parametrize('scheduled_at', ['2026-11-20T03:00:00.5Z', '2026-11-20T03:00:00+00:99',
                                         '2026-11-20T03:00:00-00:00'])
def test_facebook_schedule_rejected_before_intent_if_due_scanner_cannot_use_it(tmp_path, scheduled_at):
    from scripts.social.v1_fixture_flow import prepare_facebook_v1_fixture
    key, source, publication, manifest = inputs()
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_facebook_v1_fixture(ledger, key=key, source=source, publication=publication,
                                        manifest=manifest, scheduled_at=scheduled_at)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()
