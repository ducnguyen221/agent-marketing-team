import importlib
import importlib.util
import hashlib
import sqlite3
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

import pytest


def module():
    assert importlib.util.find_spec('delivery_ledger') is not None, 'ledger implementation missing'
    return importlib.import_module('delivery_ledger')


@pytest.fixture
def key():
    return dict(station_id='station', channel_id='channel', campaign_id='campaign',
                content_id='content', post_id='post', platform='facebook',
                account_id='page', occurrence_key='initial')


def bindings(ledger, key, *, with_proof=True):
    scopes = []
    for gate in ('g1', 'g2'):
        scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
        scope['post_id'] = '*' if gate == 'g1' else key['post_id']
        scope['gate'] = gate
        ledger.bind_scope(scope, 1)
        if with_proof:
            ledger.bind_scope_proof(scope, 1, verifier=proof)
        scopes.append((scope, 1))
    return scopes


def test_same_intent_claimed_once_across_connections(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    scopes = bindings(ledger, key)
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    assert ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes) == intent
    def claim():
        try:
            return Ledger(db).claim(intent, 1, verifier=proof)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert ledger.get(intent)['state'] == 'submitting'


def test_inflight_recovery_is_unknown_and_cannot_be_claimed(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    ledger.claim(intent, 1, verifier=proof)
    Ledger(db).recover_inflight(intent)
    assert ledger.get(intent)['state'] == 'unknown'
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_revoke_serializes_against_claim(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    assert ledger.revoke(intent, 1, by='Reviewer', quote='Thu hồi bài này', gate='g2') == 'cancelled'
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_changed_payload_or_owner_does_not_create_new_intent(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    with pytest.raises(ValueError):
        ledger.prepare(key, 'other', 'postiz', 1, scopes=scopes)


def test_imported_legacy_tombstone_blocks_initial_claim(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.import_legacy(key, 'legacy-record')
    assert ledger.get(intent)['state'] == 'migration_review'
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_backup_requires_reconciliation_before_claim(tmp_path, key):
    Ledger = module().DeliveryLedger
    ledger = Ledger(tmp_path / 'live.sqlite3')
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    ledger.backup(tmp_path / 'backup.sqlite3')
    restored = Ledger(tmp_path / 'backup.sqlite3')
    with pytest.raises(ValueError, match='recovery'):
        restored.claim(intent, 1, verifier=proof)


def test_revoke_inflight_preserves_unknown(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    assert ledger.revoke(intent, 1, by='Duc', quote='Dừng', gate='g2') == 'unknown'
    with pytest.raises(ValueError):
        ledger.resolve(intent, attempt, 'published')


def test_late_response_after_revoke_retains_remote_id_but_stays_unknown(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    assert ledger.revoke(intent, 1, by='Duc', quote='Dừng', gate='g2') == 'unknown'
    ledger.resolve(intent, attempt, 'submitted', remote_job_id='late-job',
                   provider_instance_id='instance', integration_id='integration')
    result = ledger.get(intent)
    assert result['state'] == 'unknown'
    assert result['remote_job_id'] == 'late-job'
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_late_published_response_does_not_auto_publish_after_revoke(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.revoke(intent, 1, by='Duc', quote='Dừng', gate='g2')
    ledger.resolve(intent, attempt, 'published', remote_job_id='late-job',
                   platform_post_id='late-post', evidence_kind='platform_readback')
    assert ledger.get(intent)['state'] == 'unknown'
    assert ledger.get(intent)['platform_post_id'] == 'late-post'


def test_revoke_racing_response_never_loses_job_id(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)

    def revoke():
        return Ledger(db).revoke(intent, 1, by='Duc', quote='Dừng', gate='g2')

    def respond():
        return Ledger(db).resolve(intent, attempt, 'submitted', remote_job_id='job-race',
                                  provider_instance_id='instance', integration_id='integration')

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(revoke), pool.submit(respond)]
        for task in tasks:
            task.result()
    result = ledger.get(intent)
    assert result['state'] in {'unknown', 'cancelling'}
    assert result['remote_job_id'] == 'job-race'


def test_revoked_scope_cannot_authorize_new_occurrence(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    scope = scopes[1][0]
    original = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    ledger.revoke_scope(scope, 1, by='Duc', quote='Thu hồi', gate='g2')
    assert ledger.get(original)['state'] == 'cancelled'
    key['occurrence_key'] = 'repost-2'
    with pytest.raises(ValueError, match='generation'):
        ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    with pytest.raises(ValueError, match='generation'):
        ledger.prepare(key, 'digest', 'legacy', 2, scopes=[scopes[0], (scope, 2)])


def test_scope_revoke_without_intents_is_audited(tmp_path, key):
    db = tmp_path / 'ledger.sqlite3'
    ledger = module().DeliveryLedger(db)
    scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
    scope['gate'] = 'g2'
    ledger.bind_scope(scope, 1)
    ledger.revoke_scope(scope, 1, by='Duc', quote='Thu hồi', gate='g2')
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT actor,quote,gate FROM scope_events').fetchone() == ('Duc', 'Thu hồi', 'g2')


def test_receipt_ids_survive_restart(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'published', remote_job_id='job-fake',
                   remote_post_id='postiz-fake', platform_post_id='facebook-fake',
                   platform_url='https://example.org/post/fake', integration_id='integration-fake',
                   evidence_kind='platform_readback')
    result = Ledger(db).get(intent)
    assert (result['remote_job_id'], result['remote_post_id'], result['platform_post_id']) == (
        'job-fake', 'postiz-fake', 'facebook-fake')
    assert result['platform_url'] == 'https://example.org/post/fake'


def test_published_requires_platform_evidence(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    with pytest.raises(ValueError, match='evidence'):
        ledger.resolve(intent, attempt, 'published', remote_job_id='job-fake')


def test_backup_closes_destination_connection(tmp_path, monkeypatch):
    ledger_module = module()
    ledger = ledger_module.DeliveryLedger(tmp_path / 'live.sqlite3')
    real_connect = sqlite3.connect
    destination = tmp_path / 'backup.sqlite3'
    connections = []

    class Connection(sqlite3.Connection):
        def close(self):
            connections.append('closed')
            super().close()

    def connect(*args, **kwargs):
        if str(args[0]) != str(ledger.path):
            kwargs['factory'] = Connection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ledger_module.sqlite3, 'connect', connect)
    ledger.backup(destination)
    assert connections == ['closed']


def test_failed_backup_mark_never_publishes_claimable_copy(tmp_path, key, monkeypatch):
    ledger_module = module()
    ledger = ledger_module.DeliveryLedger(tmp_path / 'live.sqlite3')
    ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    destination = tmp_path / 'backup.sqlite3'
    real_connect = sqlite3.connect

    class BrokenDestination(sqlite3.Connection):
        def execute(self, statement, parameters=()):
            if 'recovery_required' in statement:
                raise sqlite3.OperationalError('injected marker failure')
            return super().execute(statement, parameters)

    def connect(*args, **kwargs):
        if str(args[0]) != str(ledger.path):
            kwargs['factory'] = BrokenDestination
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ledger_module.sqlite3, 'connect', connect)
    with pytest.raises(sqlite3.OperationalError, match='marker failure'):
        ledger.backup(destination)
    assert not destination.exists()
    assert not list(tmp_path.glob('.delivery-backup-*.tmp'))


def test_backup_does_not_overwrite_concurrent_destination(tmp_path, monkeypatch):
    ledger_module = module()
    ledger = ledger_module.DeliveryLedger(tmp_path / 'live.sqlite3')
    destination = tmp_path / 'backup.sqlite3'
    real_link = ledger_module.os.link

    def race(source, target):
        destination.write_bytes(b'other owner')
        return real_link(source, target)

    monkeypatch.setattr(ledger_module.os, 'link', race)
    with pytest.raises(FileExistsError):
        ledger.backup(destination)
    assert destination.read_bytes() == b'other owner'
    assert not list(tmp_path.glob('.delivery-backup-*.tmp'))


def proof(scope, digest='a' * 64):
    return {'gate': scope['gate'], 'scope': scope.copy(), 'by': 'Duc',
            'quote': 'Duyet', 'source_digest': digest}


def test_unverified_cached_scopes_cannot_claim(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key, with_proof=False)
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    with pytest.raises(ValueError, match='proof'):
        ledger.claim(intent, 1)


def test_claim_requires_unchanged_proof_for_each_gate(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    for scope, generation in scopes:
        ledger.bind_scope_proof(scope, generation, verifier=proof)
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    with pytest.raises(ValueError, match='proof'):
        ledger.claim(intent, 1, verifier=lambda scope: proof(scope, 'b' * 64))
    assert ledger.get(intent)['state'] == 'prepared'
    assert ledger.claim(intent, 1, verifier=proof)


def test_reapprove_rejects_changed_source_without_new_approval_identity(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    scope = scopes[1][0]
    ledger.bind_scope_proof(scope, 1, verifier=proof)
    assert ledger.revoke_scope(scope, 1, by='Duc', quote='Dung', gate='g2') == 2
    with pytest.raises(ValueError, match='proof'):
        ledger.reapprove_scope(scope, 2, verifier=proof)
    with pytest.raises(ValueError, match='proof'):
        ledger.reapprove_scope(scope, 2, verifier=lambda s: proof(s, 'b' * 64))


def test_verifier_error_does_not_leak_exception_details(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key, with_proof=False)

    def raises(_scope):
        raise RuntimeError('fake-credential-in-error')

    with pytest.raises(ValueError) as error:
        ledger.bind_scope_proof(scopes[0][0], 1, verifier=raises)
    formatted = ''.join(traceback.format_exception(error.value))
    assert 'fake-credential-in-error' not in formatted


def test_reconcile_scheduled_to_published_and_lookup_namespaces(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job-1',
                   integration_id='integration-1', provider_instance_id='instance-1')

    def readback(_):
        return {'state': 'published', 'platform': 'facebook', 'account_id': 'page',
                'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
                'remote_job_id': 'job-1', 'remote_post_id': 'postiz-1',
                'platform_post_id': 'fb-1', 'platform_url': 'https://example.org/p/1',
                'evidence_kind': 'platform_readback'}

    assert Ledger(db).reconcile(intent, 'scheduled', verifier=readback) == 'published'
    assert ledger.get(intent)['platform_post_id'] == 'fb-1'
    assert [row['intent_id'] for row in ledger.lookup_platform('facebook', 'page', 'fb-1')] == [intent]
    assert [row['intent_id'] for row in ledger.lookup_remote('instance-1', 'integration-1', 'postiz-1')] == [intent]
    assert ledger.lookup_platform('facebook', 'other-page', 'fb-1') == []


def test_reconcile_unknown_without_known_remote_identity_is_blocked(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    ledger.claim(intent, 1, verifier=proof)
    ledger.recover_inflight(intent)
    evidence = {'state': 'published', 'platform': 'facebook', 'account_id': 'page',
                'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
                'remote_job_id': 'job-1', 'remote_post_id': 'postiz-1',
                'platform_post_id': 'fb-1', 'platform_url': 'https://example.org/p/1',
                'evidence_kind': 'platform_readback'}
    with pytest.raises(ValueError, match='identity'):
        ledger.reconcile(intent, 'unknown', verifier=lambda _: evidence)
    assert ledger.get(intent)['state'] == 'unknown'


def test_reconciliation_compare_and_set_allows_one_writer(tmp_path, key):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'ledger.sqlite3'
    ledger = Ledger(db)
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'submitted', remote_job_id='job-1',
                   integration_id='integration-1', provider_instance_id='instance-1')
    def readback(_):
        return {'state': 'published', 'platform': 'facebook', 'account_id': 'page',
                'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
                'remote_job_id': 'job-1', 'remote_post_id': 'postiz-1',
                'platform_post_id': 'fb-1', 'platform_url': None, 'evidence_kind': 'provider_confirmed'}
    def reconcile():
        try:
            return Ledger(db).reconcile(intent, 'submitted', verifier=readback)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reconcile(), range(2)))
    assert sorted(value for value in results if value) == ['published']


def test_receipt_retains_real_publication_timestamp_and_comment_id(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'published', platform_post_id='fb-post',
                   evidence_kind='platform_readback', comment_id='fb-comment',
                   published_at='2026-11-16T08:00:00Z')
    receipt = ledger.get(intent)
    assert receipt['comment_id'] == 'fb-comment'
    assert receipt['published_at'] == '2026-11-16T08:00:00Z'


def test_receipt_rejects_publication_timestamp_without_timezone(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    with pytest.raises(ValueError, match='timestamp'):
        ledger.resolve(intent, attempt, 'published', platform_post_id='fb-post',
                       evidence_kind='platform_readback', published_at='2026-11-16T08:00:00')


def test_lookup_returns_all_occurrences_for_same_external_identifier(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    intents = []
    for occurrence in ('initial', 'repost-2'):
        current = dict(key, occurrence_key=occurrence)
        intent = ledger.prepare(current, 'digest', 'postiz', 1, scopes=scopes)
        attempt = ledger.claim(intent, 1, verifier=proof)
        ledger.resolve(intent, attempt, 'published', platform_post_id='fb-shared',
                       evidence_kind='platform_readback')
        intents.append(intent)
    found = ledger.lookup_platform('facebook', 'page', 'fb-shared')
    assert {row['intent_id'] for row in found} == set(intents)


def test_reconcile_rejects_mismatched_account_without_state_change(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job-1',
                   integration_id='integration-1', provider_instance_id='instance-1')
    result = {'state': 'published', 'platform': 'facebook', 'account_id': 'wrong-page',
              'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
              'remote_job_id': 'job-1', 'remote_post_id': 'postiz-1',
              'platform_post_id': 'fb-1', 'platform_url': None, 'evidence_kind': 'platform_readback'}
    with pytest.raises(ValueError, match='identity mismatch'):
        ledger.reconcile(intent, 'scheduled', verifier=lambda _: result)
    assert ledger.get(intent)['state'] == 'scheduled'


def scheduled_ledger(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job-1',
                   provider_instance_id='instance-1', integration_id='integration-1')
    return ledger, intent


def test_cancel_claim_is_durable_and_only_matching_confirmation_cancels(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    cancel_id = ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    assert ledger.get(intent)['state'] == 'cancelling'
    with pytest.raises(ValueError):
        ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    evidence = {'state': 'cancelled', 'platform': 'facebook', 'account_id': 'page',
                'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
                'remote_job_id': 'job-1', 'remote_post_id': None,
                'evidence_kind': 'provider_confirmed'}
    assert ledger.finish_cancel(intent, cancel_id, outcome='confirmed',
                                verifier=lambda _: evidence) == 'cancelled'
    assert ledger.get(intent)['state'] == 'cancelled'


def test_cancel_timeout_is_unknown_and_cannot_retry(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    cancel_id = ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    assert ledger.finish_cancel(intent, cancel_id, outcome='unknown') == 'unknown'
    assert ledger.get(intent)['state'] == 'unknown'
    with pytest.raises(ValueError):
        ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')


def test_cancel_two_workers_only_one_claims(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    Ledger = module().DeliveryLedger
    def claim_cancel():
        try:
            return Ledger(ledger.path).begin_cancel(intent, by='Duc', quote='Hủy lịch')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim_cancel(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert ledger.get(intent)['state'] == 'cancelling'


def test_crash_after_cancel_claim_recovers_as_unknown(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    cancel_id = ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    restarted = module().DeliveryLedger(ledger.path)
    assert restarted.finish_cancel(intent, cancel_id, outcome='unknown') == 'unknown'
    with pytest.raises(ValueError):
        restarted.finish_cancel(intent, cancel_id, outcome='unknown')


def test_cancel_confirmation_must_match_remote_job(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    cancel_id = ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    wrong = {'state': 'cancelled', 'platform': 'facebook', 'account_id': 'page',
             'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
             'remote_job_id': 'wrong', 'remote_post_id': None, 'evidence_kind': 'provider_confirmed'}
    with pytest.raises(ValueError, match='identity'):
        ledger.finish_cancel(intent, cancel_id, outcome='confirmed', verifier=lambda _: wrong)
    assert ledger.get(intent)['state'] == 'cancelling'


def test_ambiguous_legacy_import_atomically_blocks_all_candidates(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = bindings(ledger, key)
    prior = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    second = dict(key, account_id='second-page')
    intents = ledger.import_legacy_ambiguous([key, second], 'legacy-reference')
    assert set(intents) >= {prior}
    assert all(ledger.get(intent)['state'] == 'migration_review' for intent in intents)
    with pytest.raises(ValueError):
        ledger.claim(prior, 1, verifier=proof)


def test_ambiguous_import_does_not_overwrite_inflight_or_partially_lock(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    ledger.claim(intent, 1, verifier=proof)
    second = dict(key, account_id='second-page')
    with pytest.raises(ValueError, match='in-flight'):
        ledger.import_legacy_ambiguous([second, key], 'legacy-reference')
    assert ledger.get(intent)['state'] == 'submitting'
    with sqlite3.connect(ledger.path) as con:
        assert con.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 1
        assert con.execute('SELECT COUNT(*) FROM legacy_import_evidence').fetchone()[0] == 0


def test_ambiguous_import_persists_filtered_provenance_for_each_candidate(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    existing = ledger.prepare(key, 'original-digest', 'legacy', 1, scopes=bindings(ledger, key))
    second = dict(key, account_id='second-page')
    ids = ledger.import_legacy_ambiguous([key, second], 'legacy-reference')
    with sqlite3.connect(ledger.path) as con:
        rows = con.execute('SELECT import_id,intent_id,reference_sha256,evidence_ref FROM legacy_import_evidence').fetchall()
    assert {row[1] for row in rows} == set(ids)
    assert len({row[0] for row in rows}) == 1
    assert {row[2] for row in rows} == {hashlib.sha256(b'legacy-reference').hexdigest()}
    assert {row[3] for row in rows} == {'legacy-reference'}
    assert ledger.get(existing)['payload_digest'] == 'original-digest'


@pytest.mark.parametrize('invalid', ['', '../source.json', '/source.json', 'https://example.org/token',
                                     'x/.env', 'x/private.key', 'x/credentials.json', 'x\\file'])
def test_ambiguous_import_rejects_unsafe_evidence_locator(tmp_path, key, invalid):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    with pytest.raises(ValueError):
        ledger.import_legacy_ambiguous([key], invalid)
    with sqlite3.connect(ledger.path) as con:
        assert con.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 0


def test_single_legacy_import_retains_safe_reference_separate_from_digest(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.import_legacy(key, 'records/legacy-01.json')
    with sqlite3.connect(ledger.path) as con:
        row = con.execute('SELECT intent_id,evidence_ref,reference_sha256 FROM legacy_import_evidence').fetchone()
    assert row == (intent, 'records/legacy-01.json', hashlib.sha256(b'records/legacy-01.json').hexdigest())
    assert ledger.get(intent)['payload_digest'] != 'records/legacy-01.json'


def test_prototype_provenance_column_renamed_without_losing_hash(tmp_path):
    db = tmp_path / 'ledger.sqlite3'
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE legacy_import_evidence (import_id TEXT, intent_id TEXT, evidence_sha256 TEXT, evidence_ref TEXT)')
        con.execute('INSERT INTO legacy_import_evidence VALUES (?,?,?,?)', ('batch', 'intent', 'abc', None))
    module().DeliveryLedger(db)
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT reference_sha256,evidence_ref FROM legacy_import_evidence').fetchone() == ('abc', None)


@pytest.mark.parametrize('invalid', ['https://example.org/file?token=FAKE', 'records/token-FAKE.json',
                                     '../source', 'records/fake.key'])
def test_single_legacy_import_rejects_unsafe_reference(tmp_path, key, invalid):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    with pytest.raises(ValueError):
        ledger.import_legacy(key, invalid)
    with sqlite3.connect(ledger.path) as con:
        assert con.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 0


def test_late_cancel_confirmation_can_resolve_unknown_without_retry(tmp_path, key):
    ledger, intent = scheduled_ledger(tmp_path, key)
    cancel_id = ledger.begin_cancel(intent, by='Duc', quote='Hủy lịch')
    assert ledger.finish_cancel(intent, cancel_id, outcome='unknown') == 'unknown'
    evidence = {'state': 'cancelled', 'platform': 'facebook', 'account_id': 'page',
                'provider_instance_id': 'instance-1', 'integration_id': 'integration-1',
                'remote_job_id': 'job-1', 'remote_post_id': None,
                'evidence_kind': 'provider_confirmed'}
    wrong = dict(evidence, remote_job_id='other')
    with pytest.raises(ValueError, match='identity'):
        ledger.finish_cancel(intent, cancel_id, outcome='confirmed', verifier=lambda _: wrong)
    assert ledger.get(intent)['state'] == 'unknown'
    assert ledger.finish_cancel(intent, cancel_id, outcome='confirmed', verifier=lambda _: evidence) == 'cancelled'
    with pytest.raises(ValueError):
        ledger.begin_cancel(intent, by='Duc', quote='Hủy lại')


def test_station_identity_create_once_and_reopen_with_independent_anchor(tmp_path):
    db = tmp_path / 'station.sqlite3'
    with sqlite3.connect(db) as connection:
        station_id = module().create_station_identity(connection)
        assert station_id
        with pytest.raises(ValueError, match='initialized'):
            module().create_station_identity(connection)
    with sqlite3.connect(db) as connection:
        assert module().open_station_identity(connection, station_id) == station_id


def test_copied_station_identity_rejects_other_station_anchor(tmp_path):
    first = tmp_path / 'first.sqlite3'
    second = tmp_path / 'second.sqlite3'
    copied = tmp_path / 'copied.sqlite3'
    with sqlite3.connect(first) as source, sqlite3.connect(second) as other:
        original_id = module().create_station_identity(source)
        other_id = module().create_station_identity(other)
        with sqlite3.connect(copied) as target:
            source.backup(target)
    with sqlite3.connect(copied) as connection:
        with pytest.raises(ValueError, match='identity mismatch'):
            module().open_station_identity(connection, other_id)
        assert module().open_station_identity(connection, original_id) == original_id


def test_station_identity_never_initializes_on_open_or_accepts_malformed_anchor(tmp_path):
    with sqlite3.connect(tmp_path / 'empty.sqlite3') as connection:
        with pytest.raises(ValueError, match='missing'):
            module().open_station_identity(connection, '00000000-0000-4000-8000-000000000000')
        with pytest.raises(ValueError, match='anchor'):
            module().open_station_identity(connection, 'invalid')


def test_ledger_backup_preserves_identity_but_requires_recovery(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    with sqlite3.connect(ledger.path) as connection:
        station_id = module().create_station_identity(connection)
    key['station_id'] = station_id
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    backup = tmp_path / 'restored.sqlite3'
    ledger.backup(backup)
    with sqlite3.connect(backup) as connection:
        assert module().open_station_identity(connection, station_id) == station_id
    with pytest.raises(ValueError, match='recovery'):
        module().DeliveryLedger(backup).claim(intent, 1, verifier=proof)


def test_station_identity_creation_refuses_populated_ledger(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=bindings(ledger, key))
    with sqlite3.connect(ledger.path) as connection:
        with pytest.raises(ValueError, match='populated'):
            module().create_station_identity(connection)
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='station_identity'").fetchone()[0] == 0
    assert ledger.get(intent)['state'] == 'prepared'


def test_station_identity_creation_refuses_existing_scope_without_intent(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    bindings(ledger, key)
    with sqlite3.connect(ledger.path) as connection:
        with pytest.raises(ValueError, match='populated'):
            module().create_station_identity(connection)
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='station_identity'").fetchone()[0] == 0


@pytest.mark.skipif(sys.version_info < (3, 12), reason='sqlite3 autocommit argument requires Python 3.12')
def test_station_identity_persists_with_sqlite_autocommit_true(tmp_path):
    db = tmp_path / 'autocommit.sqlite3'
    connection = sqlite3.connect(db, autocommit=True)
    try:
        station_id = module().create_station_identity(connection)
    finally:
        connection.close()
    with sqlite3.connect(db) as reopened:
        assert module().open_station_identity(reopened, station_id) == station_id


def test_synthetic_memory_keeps_data_without_filesystem(key, monkeypatch):
    Ledger = module().DeliveryLedger
    def forbidden(*args, **kwargs):
        raise AssertionError('synthetic ledger must not access filesystem')
    monkeypatch.setattr('pathlib.Path.mkdir', forbidden)
    ledger = Ledger.synthetic_memory()
    scopes = bindings(ledger, key)
    intent = ledger.prepare(key, 'digest', 'legacy', 1, scopes=scopes)
    assert ledger.get(intent)['state'] == 'prepared'
    ledger.close()
    with pytest.raises(ValueError, match='closed'):
        ledger.get(intent)


def test_fixture_snapshot_bound_to_digest_and_locator_without_leaking_secret(key):
    Ledger = module().DeliveryLedger
    snapshot_module = importlib.import_module('delivery_contract')
    ledger = Ledger.synthetic_memory()
    payload = {'text': 'Synthetic only', 'occurrence_key': 'initial'}
    _, digest = snapshot_module.canonical_snapshot(payload)
    scopes = bindings(ledger, key)
    intent = ledger.prepare_fixture(key, payload, 'demo/content', 'postiz', 1, scopes=scopes)
    record = ledger.fixture_snapshot(intent)
    assert record == {'snapshot': payload, 'payload_digest': digest, 'source_locator': 'demo/content'}
    with pytest.raises(ValueError):
        ledger.prepare_fixture(key, {'access_token': 'dummy'}, 'demo/content', 'postiz', 1, scopes=scopes)
    with pytest.raises(ValueError):
        ledger.prepare_fixture(key, payload, '../outside', 'postiz', 1, scopes=scopes)
    ledger.close()


def test_fixture_snapshot_fails_closed_after_naked_prepare(key):
    ledger = module().DeliveryLedger.synthetic_memory()
    try:
        intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
        with pytest.raises(ValueError, match='snapshot missing'):
            ledger.fixture_snapshot(intent)
    finally:
        ledger.close()


def test_fixture_snapshot_is_unavailable_on_file_ledger(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'ledger.sqlite3')
    with pytest.raises(ValueError, match='fixture-only'):
        ledger.prepare_fixture(key, {'text': 'fixture'}, 'demo/post', 'postiz', 1, scopes=[])
    with pytest.raises(ValueError, match='fixture-only'):
        ledger.fixture_snapshot('anything')


def test_synthetic_memory_uses_memory_temp_store():
    ledger = module().DeliveryLedger.synthetic_memory()
    try:
        with ledger._connect() as con:
            assert con.execute('PRAGMA temp_store').fetchone()[0] == 2
    finally:
        ledger.close()


def test_synthetic_ledger_refuses_backup_to_path_before_touching_it(monkeypatch):
    ledger = module().DeliveryLedger.synthetic_memory()
    try:
        def forbidden(*args, **kwargs):
            raise AssertionError('filesystem must not be touched')
        monkeypatch.setattr('pathlib.Path.resolve', forbidden)
        with pytest.raises(ValueError, match='fixture-only'):
            ledger.backup('any-path')
    finally:
        ledger.close()


def test_fixture_snapshot_failure_rolls_back_intent_and_attempt(monkeypatch, key):
    ledger = module().DeliveryLedger.synthetic_memory()
    try:
        scopes = bindings(ledger, key)
        def interrupted(*args, **kwargs):
            raise RuntimeError('synthetic failure')
        monkeypatch.setattr(ledger, '_bind_fixture', interrupted, raising=False)
        with pytest.raises(RuntimeError, match='synthetic failure'):
            ledger.prepare_fixture(key, {'text': 'fixture'}, 'demo/post', 'postiz', 1, scopes=scopes)
        with ledger._connect() as con:
            assert con.execute('SELECT count(*) FROM intents').fetchone()[0] == 0
            assert con.execute('SELECT count(*) FROM fixture_snapshots').fetchone()[0] == 0
    finally:
        ledger.close()


def test_late_receipt_fills_unknown_placeholder_without_resubmission(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'late.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'unknown', provider_instance_id='provider-a', integration_id='integration-a')
    ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job-a',
                   provider_instance_id='provider-a', integration_id='integration-a')
    result = ledger.get(intent)
    assert result['state'] == 'unknown'
    assert result['remote_job_id'] == 'job-a'
    assert result['provider_instance_id'] == 'provider-a'
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_late_receipt_rejects_namespace_or_identifier_conflicts(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'late-conflict.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'unknown', provider_instance_id='provider-a',
                   integration_id='integration-a', remote_job_id='job-a')
    with pytest.raises(ValueError, match='conflict'):
        ledger.resolve(intent, attempt, 'scheduled', remote_post_id='post-a',
                       provider_instance_id='provider-b', integration_id='integration-a')
    with pytest.raises(ValueError, match='conflict'):
        ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job-b',
                       provider_instance_id='provider-a', integration_id='integration-a')
    result = ledger.get(intent)
    assert result['state'] == 'unknown'
    assert result['remote_job_id'] == 'job-a'
    assert result['remote_post_id'] is None


def test_fixture_new_grant_enables_only_new_occurrence_and_rejects_replay(key):
    ledger = module().DeliveryLedger.synthetic_memory()
    try:
        scopes = bindings(ledger, key)
        first = ledger.prepare(key, 'digest-a', 'postiz', 1, scopes=scopes)
        g2 = scopes[1][0]
        event = '00000000-0000-4000-8000-000000000001'
        def new_proof(scope):
            return proof(scope, digest='b' * 64 if scope['gate'] == 'g2' else 'a' * 64)
        assert ledger.grant_fixture(g2, 1, event_id=event, verifier=new_proof) == 2
        with pytest.raises(ValueError):
            ledger.claim(first, 1, verifier=new_proof)
        second_key = dict(key, occurrence_key='explicit-repost')
        second = ledger.prepare(second_key, 'digest-b', 'postiz', 2,
                                scopes=[scopes[0], (g2, 2)])
        assert ledger.claim(second, 2, verifier=new_proof)
        with pytest.raises(ValueError):
            ledger.grant_fixture(g2, 2, event_id=event, verifier=new_proof)
    finally:
        ledger.close()


def test_fixture_grant_is_unavailable_on_file_ledger(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'prod.sqlite3')
    scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
    scope['gate'] = 'g2'
    with pytest.raises(ValueError, match='fixture-only'):
        ledger.grant_fixture(scope, 1, event_id='00000000-0000-4000-8000-000000000001', verifier=proof)


def test_fixture_prepare_package_import_works_in_fresh_interpreter():
    import subprocess
    from pathlib import Path
    script = """
import os, sys
sys.path.insert(0, os.getcwd())
from scripts.lib.delivery_ledger import DeliveryLedger
ledger = DeliveryLedger.synthetic_memory()
try:
    try:
        ledger.prepare_fixture({}, {'text': 'synthetic'}, 'demo/post', 'postiz', 1, scopes=[])
    except ValueError as exc:
        assert 'invalid intent' in str(exc)
    else:
        raise AssertionError('invalid intent unexpectedly accepted')
finally:
    ledger.close()
"""
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('kind', ['submit', 'cancel'])
def test_fixture_worker_recovery_waits_for_exact_stopped_process(key, kind):
    import subprocess
    ledger = module().DeliveryLedger.synthetic_memory()
    worker = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
        attempt = ledger.claim(intent, 1, verifier=proof)
        if kind == 'cancel':
            ledger.resolve(intent, attempt, 'scheduled', remote_job_id='job',
                           provider_instance_id='instance', integration_id='integration')
            action = ledger.begin_cancel(intent, by='Fixture', quote='Synthetic cancel')
        else:
            action = attempt
        ledger.track_fixture_worker(intent, action, kind=kind, worker=worker)
        with pytest.raises(ValueError, match='worker still running'):
            ledger.recover_fixture_worker(intent, action, kind=kind, worker=worker)
        assert ledger.get(intent)['state'] == ('submitting' if kind == 'submit' else 'cancelling')
        worker.terminate()
        worker.wait(timeout=10)
        ledger.recover_fixture_worker(intent, action, kind=kind, worker=worker)
        assert ledger.get(intent)['state'] == 'unknown'
        with pytest.raises(ValueError):
            ledger.claim(intent, 1, verifier=proof)
        with pytest.raises(ValueError):
            ledger.recover_fixture_worker(intent, action, kind=kind, worker=worker)
    finally:
        if worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=10)
        ledger.close()


def test_fixture_recovery_refuses_unrelated_process_and_file_ledger(tmp_path, key):
    import subprocess
    ledger = module().DeliveryLedger(tmp_path / 'file.sqlite3')
    worker = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with pytest.raises(ValueError, match='fixture-only'):
            ledger.track_fixture_worker('id', 'action', kind='submit', worker=worker)
    finally:
        worker.terminate()
        worker.wait(timeout=10)


def test_fixture_recovery_requires_same_tracked_process(key):
    import subprocess
    ledger = module().DeliveryLedger.synthetic_memory()
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    worker = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], **options)
    other = subprocess.Popen([sys.executable, '-I', '-c', 'pass'], **options)
    try:
        other.wait(timeout=10)
        intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
        attempt = ledger.claim(intent, 1, verifier=proof)
        ledger.track_fixture_worker(intent, attempt, kind='submit', worker=worker)
        with pytest.raises(ValueError, match='not tracked'):
            ledger.recover_fixture_worker(intent, attempt, kind='submit', worker=other)
        assert ledger.get(intent)['state'] == 'submitting'
    finally:
        for child in (worker, other):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
        ledger.close()


def test_synthetic_restore_quarantines_claims_without_touching_filesystem(key, monkeypatch):
    ledger = module().DeliveryLedger.synthetic_memory()
    restored = None
    try:
        intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
        def forbidden(*args, **kwargs):
            raise AssertionError('fixture restore must not touch filesystem')
        monkeypatch.setattr('pathlib.Path.mkdir', forbidden)
        monkeypatch.setattr('pathlib.Path.resolve', forbidden)
        restored = ledger.clone_fixture_for_restore()
        assert restored.get(intent)['state'] == 'prepared'
        with pytest.raises(ValueError, match='recovery'):
            restored.claim(intent, 1, verifier=proof)
        assert ledger.claim(intent, 1, verifier=proof)
    finally:
        if restored is not None:
            restored.close()
        ledger.close()


def published_for_enrichment(tmp_path, key):
    ledger = module().DeliveryLedger(tmp_path / 'enrich.sqlite3')
    intent = ledger.prepare(key, 'digest', 'postiz', 1, scopes=bindings(ledger, key))
    attempt = ledger.claim(intent, 1, verifier=proof)
    ledger.resolve(intent, attempt, 'published', remote_job_id='job', remote_post_id='remote-post',
                   platform_post_id='fb-post', provider_instance_id='instance', integration_id='integration',
                   evidence_kind='provider_confirmed')
    return ledger, intent


def fixture_published_evidence():
    return {'state': 'published', 'platform': 'facebook', 'account_id': 'page',
            'provider_instance_id': 'instance', 'integration_id': 'integration',
            'remote_job_id': 'job', 'remote_post_id': 'remote-post', 'platform_post_id': 'fb-post',
            'comment_id': 'comment-1', 'published_at': '2026-11-16T08:00:00Z',
            'evidence_kind': 'platform_readback'}


def test_published_receipt_enrichment_only_fills_missing_fields(tmp_path, key):
    ledger, intent = published_for_enrichment(tmp_path, key)
    original = ledger.get(intent)
    assert ledger.enrich_published(intent, original['version'], verifier=lambda _: fixture_published_evidence())
    updated = ledger.get(intent)
    assert updated['state'] == 'published'
    assert updated['comment_id'] == 'comment-1'
    assert updated['published_at'] == '2026-11-16T08:00:00Z'
    assert updated['evidence_kind'] == original['evidence_kind']
    assert updated['version'] == original['version'] + 1
    assert not ledger.enrich_published(intent, updated['version'], verifier=lambda _: fixture_published_evidence())
    assert ledger.get(intent)['version'] == updated['version']
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=proof)


def test_enrichment_rejects_stale_version_and_conflicting_identity_or_metadata(tmp_path, key):
    ledger, intent = published_for_enrichment(tmp_path, key)
    version = ledger.get(intent)['version']
    wrong = fixture_published_evidence()
    wrong['account_id'] = 'wrong-page'
    with pytest.raises(ValueError):
        ledger.enrich_published(intent, version, verifier=lambda _: wrong)
    wrong = fixture_published_evidence()
    wrong['remote_job_id'] = 'another-job'
    with pytest.raises(ValueError):
        ledger.enrich_published(intent, version, verifier=lambda _: wrong)
    assert ledger.enrich_published(intent, version, verifier=lambda _: fixture_published_evidence())
    with pytest.raises(ValueError):
        ledger.enrich_published(intent, version, verifier=lambda _: fixture_published_evidence())
    wrong = fixture_published_evidence()
    wrong['comment_id'] = 'other-comment'
    current = ledger.get(intent)
    with pytest.raises(ValueError):
        ledger.enrich_published(intent, current['version'], verifier=lambda _: wrong)
    assert ledger.get(intent)['comment_id'] == 'comment-1'


def test_two_enrichers_only_one_updates_and_audits(tmp_path, key):
    ledger, intent = published_for_enrichment(tmp_path, key)
    version = ledger.get(intent)['version']
    def enrich():
        try:
            return ledger.enrich_published(intent, version, verifier=lambda _: fixture_published_evidence())
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: enrich(), range(2)))
    assert sorted(results) == [False, True]
    with ledger._connect() as con:
        assert con.execute("SELECT count(*) FROM events WHERE intent_id=? AND kind='receipt_enriched'",
                           (intent,)).fetchone()[0] == 1
    assert ledger.get(intent)['state'] == 'published'


def test_enrichment_sanitizes_provider_exception_and_rejects_bad_time(tmp_path, key):
    ledger, intent = published_for_enrichment(tmp_path, key)
    version = ledger.get(intent)['version']
    def broken(_):
        raise RuntimeError('SYNTHETIC_SECRET_MARKER')
    try:
        ledger.enrich_published(intent, version, verifier=broken)
    except ValueError as exc:
        assert 'SYNTHETIC_SECRET_MARKER' not in ''.join(traceback.format_exception(exc))
    else:
        pytest.fail('exception should be reported')
    evidence = fixture_published_evidence()
    evidence['published_at'] = 'tomorrow'
    with pytest.raises(ValueError, match='timestamp'):
        ledger.enrich_published(intent, version, verifier=lambda _: evidence)
    assert ledger.get(intent)['version'] == version


def test_synthetic_connection_persists_snapshot_without_opening_file_itself(tmp_path, key, monkeypatch):
    Ledger = module().DeliveryLedger
    db = tmp_path / 'fixture.sqlite3'
    conn = sqlite3.connect(db)
    try:
        with monkeypatch.context() as patch:
            patch.setattr('sqlite3.connect', lambda *a, **k: pytest.fail('fixture API must not open a path'))
            ledger = Ledger.synthetic_connection(conn)
            scope = bindings(ledger, key)
            intent = ledger.prepare_fixture(key, {'text': 'synthetic', 'occurrence_key': 'initial'},
                                            'demo/post', 'postiz', 1, scopes=scope)
            ledger.close()
        assert conn.execute('SELECT count(*) FROM intents').fetchone()[0] == 1
    finally:
        conn.close()
    conn2 = sqlite3.connect(db)
    try:
        ledger2 = Ledger.synthetic_connection(conn2)
        assert ledger2.fixture_snapshot(intent)['snapshot']['text'] == 'synthetic'
        assert ledger2.get(intent)['state'] == 'prepared'
        ledger2.close()
    finally:
        conn2.close()


def test_synthetic_connection_refuses_open_transaction_without_committing():
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE TABLE unrelated(value TEXT)')
        conn.execute("INSERT INTO unrelated VALUES ('pending')")
        with pytest.raises(ValueError, match='transaction'):
            module().DeliveryLedger.synthetic_connection(conn)
        conn.rollback()
        assert conn.execute('SELECT count(*) FROM unrelated').fetchone()[0] == 0
    finally:
        conn.close()


def test_synthetic_file_connection_snapshot_failure_rolls_back(tmp_path, key, monkeypatch):
    conn = sqlite3.connect(tmp_path / 'fixture.sqlite3')
    ledger = None
    try:
        ledger = module().DeliveryLedger.synthetic_connection(conn)
        scopes = bindings(ledger, key)
        def interrupted(*args, **kwargs):
            raise RuntimeError('synthetic failure')
        monkeypatch.setattr(ledger, '_bind_fixture', interrupted)
        with pytest.raises(RuntimeError, match='synthetic failure'):
            ledger.prepare_fixture(key, {'text': 'fixture'}, 'demo/post', 'postiz', 1, scopes=scopes)
        assert conn.execute('SELECT count(*) FROM intents').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM fixture_snapshots').fetchone()[0] == 0
    finally:
        if ledger is not None:
            ledger.close()
        conn.close()


@pytest.mark.skipif(sys.version_info < (3, 12), reason='sqlite autocommit argument requires Python 3.12')
def test_synthetic_connection_rejects_autocommit_true_before_writes(tmp_path):
    conn = sqlite3.connect(tmp_path / 'autocommit.sqlite3', autocommit=True)
    try:
        with pytest.raises(ValueError, match='autocommit'):
            module().DeliveryLedger.synthetic_connection(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='intents'").fetchone()[0] == 0
    finally:
        conn.close()


def test_synthetic_connection_serializes_transaction_against_reader(tmp_path, key, monkeypatch):
    import threading
    conn = sqlite3.connect(tmp_path / 'fixture.sqlite3', check_same_thread=False)
    ledger = module().DeliveryLedger.synthetic_connection(conn)
    scopes = bindings(ledger, key)
    in_writer = threading.Event()
    release_writer = threading.Event()
    reader_done = threading.Event()
    writer_errors = []
    reader_errors = []
    def interrupted(*args, **kwargs):
        in_writer.set()
        assert release_writer.wait(10)
        raise RuntimeError('synthetic rollback')
    monkeypatch.setattr(ledger, '_bind_fixture', interrupted)
    def writer():
        try:
            ledger.prepare_fixture(key, {'text': 'fixture'}, 'demo/post', 'postiz', 1, scopes=scopes)
        except Exception as exc:
            writer_errors.append(exc)
    def reader():
        try:
            with ledger._connect() as con:
                con.execute('SELECT count(*) FROM intents').fetchone()
        except Exception as exc:
            reader_errors.append(exc)
        finally:
            reader_done.set()
    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    try:
        writer_thread.start()
        assert in_writer.wait(10)
        reader_thread.start()
        assert not reader_done.wait(0.25), 'reader must wait for writer transaction'
    finally:
        release_writer.set()
        writer_thread.join(timeout=10)
        reader_thread.join(timeout=10)
    try:
        assert not writer_thread.is_alive() and not reader_thread.is_alive()
        assert len(writer_errors) == 1 and isinstance(writer_errors[0], RuntimeError)
        assert not reader_errors
        assert conn.execute('SELECT count(*) FROM intents').fetchone()[0] == 0
    finally:
        ledger.close()
        conn.close()


def test_synthetic_connection_rejects_duplicate_wrapper():
    conn = sqlite3.connect(':memory:')
    first = module().DeliveryLedger.synthetic_connection(conn)
    try:
        with pytest.raises(ValueError, match='already wrapped'):
            module().DeliveryLedger.synthetic_connection(conn)
    finally:
        first.close()
    second = module().DeliveryLedger.synthetic_connection(conn)
    second.close()
    conn.close()


def test_borrowed_connection_cannot_be_wrapped_across_distinct_module_imports():
    from pathlib import Path
    original = module()
    spec = importlib.util.spec_from_file_location('isolated_delivery_ledger',
                                                   Path(original.__file__))
    alternate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alternate)
    conn = sqlite3.connect(':memory:')
    first = original.DeliveryLedger.synthetic_connection(conn)
    try:
        with pytest.raises(ValueError, match='already wrapped'):
            alternate.DeliveryLedger.synthetic_connection(conn)
    finally:
        first.close()
    second = alternate.DeliveryLedger.synthetic_connection(conn)
    second.close()
    conn.close()
