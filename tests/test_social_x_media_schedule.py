"""Synthetic X media lifecycle must be ready and unexpired at claim."""
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger
from scripts.social.multichannel_fixture import prepare_v1_fixture_batch, simulate_v1_fixture_batch


def sample():
    data = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/social_v2/v1_facebook_to_x_video_preview.json').read_text(encoding='utf-8'))
    data['key'] = {'station_id': 'fixture-station', 'channel_id': 'fixture-brand', 'campaign_id': 'fixture-campaign',
                   'content_id': 'fixture-content', 'post_id': data.pop('post_id'), 'platform': 'x',
                   'account_id': 'fixture-x-account-123', 'destination_id': 'fixture-x-profile-123',
                   'occurrence_key': 'fixture-slot'}
    data['target'] = {'user_id': '123'}
    data['scheduled_at'] = '2026-11-20T03:00:00Z'
    data['observation'] = {'user_id': '123', 'media_id': 'fixture-x-media-456', 'asset_id': 'fixture-source-asset',
                           'media_kind': 'video', 'state': 'succeeded', 'observed_at': '2026-11-20T02:00:00Z',
                           'expires_at': '2026-11-20T04:00:00Z'}
    source, publication = data.pop('source'), data.pop('publication')
    return source, publication, [{'platform': 'x', 'args': data}]


def test_ready_x_media_claims_only_before_expiration():
    source, publication, entries = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [intent]
        attempt = ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_x_fixture(intent, attempt=attempt, user_id='123', post_id='987')
        assert ledger.get(intent)['state'] == 'accepted'


@pytest.mark.parametrize('change', ['pending', 'failed', 'expired', 'future_observation'])
def test_x_media_claim_rejects_unready_or_stale_observation(change):
    source, publication, entries = sample()
    obs = entries[0]['args']['observation']
    if change in ('pending', 'failed'):
        obs['state'] = change
    elif change == 'expired':
        obs['expires_at'] = '2026-11-20T03:00:00Z'
    else:
        obs['observed_at'] = '2026-11-20T03:30:00Z'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        assert intent not in ledger.scan_due(now='2026-11-20T03:00:00Z')['due']
        with pytest.raises(ValueError):
            ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(intent)['state'] == 'prepared'


@pytest.mark.parametrize('field', ['user_id', 'media_id', 'asset_id', 'media_kind'])
def test_x_media_observation_cannot_be_transferred(field):
    source, publication, entries = sample()
    entries[0]['args']['observation'][field] = 'fixture-other'
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        with pytest.raises(ValueError):
            prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0


def test_x_media_expiration_between_scan_and_claim_leaves_no_attempt():
    source, publication, entries = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:59:59Z')['due'] == [intent]
        with pytest.raises(ValueError):
            ledger.claim_due(intent, expected_version=1, now='2026-11-20T04:00:00Z')
        assert ledger.get(intent)['state'] == 'prepared'
        assert ledger.get(intent)['attempt_id'] is None


def test_x_media_revision_invalidates_grant():
    source, publication, entries = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        snapshot = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        snapshot['observation']['expires_at'] = '2026-11-20T05:00:00Z'
        ledger.revise(intent, snapshot)
        assert ledger.get(intent)['grant_version'] is None
        with pytest.raises(ValueError):
            ledger.claim_due(intent, expected_version=1, now='2026-11-20T03:00:00Z')


def test_x_media_schema_cannot_be_relabelled_as_another_platform():
    source, publication, entries = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        snapshot = json.loads(ledger.get(intent)['snapshot_json'])['payload']
        key = dict(entries[0]['args']['key'], platform='linkedin', account_id='fixture-other',
                   destination_id='fixture-other')
        with pytest.raises(ValueError):
            ledger.prepare(key, snapshot)


def test_x_media_simulation_reports_untrusted_observation_and_asset():
    source, publication, entries = sample()
    result = simulate_v1_fixture_batch(source=source, publication=publication, entries=entries, events=[])
    media = result['items'][0]['fixture_media']
    assert media['asset_id'] == 'fixture-source-asset'
    assert media['state'] == 'succeeded'
    assert media['expires_at'] == '2026-11-20T04:00:00Z'
    assert media['authenticated'] is False
    assert result['items'][0]['source_binding']['content_id'] == 'fixture-content'
    assert result['items'][0]['source_binding']['campaign_id'] == 'fixture-campaign'
    assert 'media_observation_not_authenticated' in result['warnings']


def test_future_x_media_is_not_reported_invalid_before_due():
    source, publication, entries = sample()
    with sqlite3.connect(':memory:') as con:
        ledger = DestinationFixtureLedger.initialize(con)
        intent = prepare_v1_fixture_batch(ledger, source=source, publication=publication, entries=entries)[0]
        ledger.approve(intent, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T01:00:00Z') == {'due': [], 'invalid': []}
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['due'] == [intent]
