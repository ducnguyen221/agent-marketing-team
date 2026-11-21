"""Exercise the existing Postiz candidate builder without external delivery."""
from scripts.lib.postiz_payload import build_postiz_create_candidate
from scripts.social.fixture_ledger import FixtureLedger
import pytest


def test_linkedin_two_target_candidates_are_bound_and_completed_independently():
    ledger = FixtureLedger()
    ids = []
    for destination in ('fixture-page-a', 'fixture-page-b'):
        candidate = build_postiz_create_candidate(
            integration_id=destination, provider='linkedin', content='Fixture content',
            uploaded_media=[], mode='schedule', date_utc='2026-11-20T03:00:00Z',
            settings={'__type': 'linkedin'})
        identity = {'station': 'fixture-station', 'brand': 'fixture-brand',
                    'campaign': 'fixture-campaign', 'content': 'fixture-content',
                    'post': 'fixture-post', 'platform': 'linkedin', 'account': 'fixture-account',
                    'destination': destination, 'occurrence': 'fixture-slot'}
        ids.append(ledger.prepare(identity, {'candidate': candidate}))
    event = ledger.approve_batch([(item, ledger.get(item)['version']) for item in ids])
    attempt = ledger.claim(ids[0])
    ledger.finish(ids[0], 'scheduled', receipt={'attempt': attempt, 'destination': 'fixture-page-a',
                                               'remote_id': 'fixture-job-a'})
    ledger.revoke(ids[1])
    assert ledger.batch_status(event) == {'complete': False, 'states': {'scheduled': 1, 'revoked': 1}}
    assert ledger.get(ids[0])['identity']['destination'] == 'fixture-page-a'


def test_candidate_for_another_destination_is_rejected():
    ledger = FixtureLedger()
    identity = {'station': 's', 'brand': 'b', 'campaign': 'c', 'content': 'x', 'post': 'p',
                'platform': 'linkedin', 'account': 'a', 'destination': 'fixture-page-a', 'occurrence': 'o'}
    candidate = build_postiz_create_candidate(integration_id='fixture-page-b', provider='linkedin',
                content='Example', uploaded_media=[], mode='schedule', date_utc='2026-11-20T03:00:00Z',
                settings={'__type': 'linkedin'})
    with pytest.raises(ValueError):
        ledger.prepare(identity, {'candidate': candidate})
