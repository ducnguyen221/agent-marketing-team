"""End-to-end synthetic LinkedIn receipts, without network or credentials."""
import pytest

from scripts.social.fixture_ledger import FixtureLedger


def identity(destination):
    return {'station': 'fixture-station', 'brand': 'fixture-brand', 'campaign': 'fixture-campaign',
            'content': 'fixture-content', 'post': 'fixture-post', 'platform': 'linkedin',
            'account': 'fixture-account', 'destination': destination, 'occurrence': 'fixture-slot'}


def test_receipt_from_other_attempt_does_not_attach():
    assert hasattr(FixtureLedger, 'finish_linkedin_fixture')
    ledger = FixtureLedger()
    a = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    b = ledger.prepare(identity('b'), {'author': 'urn:li:person:b', 'text': 'A'})
    ledger.approve_batch([(a, 1), (b, 1)])
    attempt_a, attempt_b = ledger.claim(a), ledger.claim(b)
    with pytest.raises(ValueError):
        ledger.finish_linkedin_fixture(a, attempt=attempt_b, destination='b', author='urn:li:person:b',
                                       status=201, headers=[('x-restli-id', 'urn:li:share:123')])
    assert ledger.get(a)['state'] == 'submitting'
    ledger.finish_linkedin_fixture(a, attempt=attempt_a, destination='a', author='urn:li:person:a',
                                   status=201, headers=[('x-restli-id', 'urn:li:share:123')])
    assert ledger.get(a)['state'] == 'accepted'


def test_lost_response_locks_attempt_and_blocks_resubmit():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    ledger.approve_batch([(item, 1)])
    attempt = ledger.claim(item)
    ledger.finish_linkedin_fixture(item, attempt=attempt, destination='a', author='urn:li:person:a',
                                   status=None, headers=[])
    assert ledger.get(item)['state'] == 'unknown'
    with pytest.raises(ValueError):
        ledger.claim(item)


def test_accepted_readback_matches_author_and_preserves_previous_observation():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    batch = ledger.approve_batch([(item, 1)])
    attempt = ledger.claim(item)
    ledger.finish_linkedin_fixture(item, attempt=attempt, destination='a', author='urn:li:person:a',
                                   status=201, headers=[('x-restli-id', 'urn:li:share:123')])
    body = {'id': 'urn:li:share:123', 'author': 'urn:li:person:b', 'lifecycleState': 'PUBLISHED',
            'visibility': 'PUBLIC'}
    ledger.observe_linkedin_fixture(item, attempt=attempt, destination='a', status=200, body=body)
    assert ledger.get(item)['linkedin_receipt']['readback'] == 'unverified'
    body['author'] = 'urn:li:person:a'
    ledger.observe_linkedin_fixture(item, attempt=attempt, destination='a', status=200, body=body)
    assert ledger.get(item)['linkedin_receipt']['readback'] == 'provider_reports_published'
    ledger.observe_linkedin_fixture(item, attempt=attempt, destination='a', status=403, body={})
    result = ledger.get(item)
    assert result['linkedin_receipt']['readback'] == 'unverified'
    assert result['linkedin_receipt']['previously_reported_published'] is True
    assert result['state'] == 'accepted'
    assert not ledger.batch_status(batch)['complete']


def test_wrong_attempt_readback_is_refused():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    ledger.approve_batch([(item, 1)])
    attempt = ledger.claim(item)
    ledger.finish_linkedin_fixture(item, attempt=attempt, destination='a', author='urn:li:person:a',
                                   status=201, headers=[('x-restli-id', 'urn:li:share:123')])
    with pytest.raises(ValueError):
        ledger.observe_linkedin_fixture(item, attempt='other', destination='a', status=403, body={})


def test_approval_does_not_survive_changed_author():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    ledger.approve_batch([(item, 1)])
    ledger.revise(item, {'author': 'urn:li:person:b', 'text': 'A'})
    with pytest.raises(ValueError):
        ledger.claim(item)


def test_same_native_post_id_cannot_be_accepted_for_two_attempts():
    ledger = FixtureLedger()
    a = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    b = ledger.prepare(identity('b'), {'author': 'urn:li:person:b', 'text': 'A'})
    ledger.approve_batch([(a, 1), (b, 1)])
    attempt_a, attempt_b = ledger.claim(a), ledger.claim(b)
    headers = [('x-restli-id', 'urn:li:share:123')]
    ledger.finish_linkedin_fixture(a, attempt=attempt_a, destination='a', author='urn:li:person:a',
                                   status=201, headers=headers)
    ledger.finish_linkedin_fixture(b, attempt=attempt_b, destination='b', author='urn:li:person:b',
                                   status=201, headers=headers)
    assert ledger.get(a)['state'] == 'accepted'
    assert ledger.get(b)['state'] == 'unknown'
    with pytest.raises(ValueError):
        ledger.claim(b)


def test_generic_finish_cannot_bypass_linkedin_receipt_binding():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': 'urn:li:person:a', 'text': 'A'})
    ledger.approve_batch([(item, 1)])
    attempt = ledger.claim(item)
    with pytest.raises(ValueError):
        ledger.finish(item, 'accepted', receipt={'attempt': attempt, 'destination': 'a', 'remote_id': 'fixture-any'})
    assert ledger.get(item)['state'] == 'submitting'


def test_mutable_author_is_not_exposed_through_get():
    ledger = FixtureLedger()
    item = ledger.prepare(identity('a'), {'author': {'invalid': []}, 'text': 'A'})
    result = ledger.get(item)
    assert result['fixture_author'] is None
