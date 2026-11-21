"""LinkedIn native content-to-ledger fixture, no real social calls."""
import json
import socket
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


def data(kind=None):
    key = {'station_id': 'fixture-station', 'channel_id': 'fixture-brand', 'campaign_id': 'fixture-campaign',
           'content_id': 'fixture-content', 'post_id': 'fixture-post', 'platform': 'linkedin',
           'account_id': 'fixture-linkedin-account-member', 'destination_id': 'fixture-linkedin-person-member',
           'occurrence_key': 'fixture-slot'}
    return {'key': key, 'author': 'urn:li:person:fixture-member', 'source': '## post:linkedin_post\nBài giả\n',
            'anchor': 'post:linkedin_post', 'api_version': '202611', 'scheduled_at': '2026-11-20T03:00:00Z',
            'media_kind': kind, 'media_urn': None if kind is None else f'urn:li:{kind}:fixture-media',
            'media_observation': None if kind is None else {'id': f'urn:li:{kind}:fixture-media',
                'owner': 'urn:li:person:fixture-member', 'status': 'AVAILABLE'}}


@pytest.mark.parametrize('kind', [None, 'image', 'video'])
def test_native_linkedin_cannot_accept_unvalidated_generic_receipt(tmp_path, kind):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data(kind))
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination='fixture-linkedin-person-member',
                          remote_id='fixture-unverified')
        assert ledger.get(item)['state'] == 'submitting'
    finally:
        con.close()


def test_linkedin_schema_cannot_use_generic_account_and_destination(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        key = data()['key']
        key.update(account_id='fixture-generic-account', destination_id='fixture-generic-destination')
        payload.update(account_id=key['account_id'], destination_id=key['destination_id'])
        with pytest.raises(ValueError):
            ledger.prepare(key, payload)
    finally:
        con.close()


def test_linkedin_destination_cannot_be_used_by_another_platform(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        key = data()['key']
        key['platform'] = 'facebook'
        with pytest.raises(ValueError):
            ledger.prepare(key, {'scheduled_at': '2026-11-20T03:00:00Z'})
    finally:
        con.close()


def test_organization_cannot_accept_unvalidated_generic_receipt(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data()
        args['author'] = 'urn:li:organization:12345'
        args['key']['account_id'] = 'fixture-linkedin-org-account-12345'
        args['key']['destination_id'] = 'fixture-linkedin-org-12345'
        item = prepare_linkedin_fixture(ledger, **args)
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination=args['key']['destination_id'], remote_id='fixture-unverified')
        assert ledger.get(item)['state'] == 'submitting'
    finally:
        con.close()


def test_linkedin_valid_receipt_survives_reopening_fixture_database(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert hasattr(ledger, 'finish_linkedin_fixture'), 'durable LinkedIn receipt is missing'
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                       headers=[('x-restli-id', 'urn:li:share:123')])
    finally:
        con.close()
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.get_linkedin_fixture_receipt(item)['post_urn'] == 'urn:li:share:123'
    finally:
        con.close()


def test_linkedin_readback_retains_previous_success_after_unavailable_response(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                       headers=[('x-restli-id', 'urn:li:share:123')])
        assert hasattr(ledger, 'observe_linkedin_fixture'), 'persistent readback is missing'
        ledger.observe_linkedin_fixture(item, attempt=attempt, status=200,
                                        body={'id': 'urn:li:share:123', 'author': 'urn:li:person:fixture-member',
                                              'lifecycleState': 'PUBLISHED', 'visibility': 'PUBLIC'})
        ledger.observe_linkedin_fixture(item, attempt=attempt, status=403, body={})
        receipt = ledger.get_linkedin_fixture_receipt(item)
        assert receipt['readback'] == 'unverified'
        assert receipt['previously_reported_published'] is True
        assert ledger.get(item)['state'] == 'accepted'
    finally:
        con.close()


@pytest.mark.parametrize('status,headers', [(None, []), (201, []), (201, [('x-restli-id', 'bad')])])
def test_ambiguous_linkedin_response_cannot_be_retried(tmp_path, status, headers):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=status, headers=headers)
        assert ledger.get(item)['state'] == 'unknown'
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


def test_duplicate_linkedin_urn_is_not_assigned_to_second_intent(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        first = prepare_linkedin_fixture(ledger, **data())
        args = data()
        args['key']['occurrence_key'] = 'fixture-second'
        second = prepare_linkedin_fixture(ledger, **args)
        for item in (first, second):
            ledger.approve(item, expected_version=1)
            attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
            ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                           headers=[('x-restli-id', 'urn:li:share:123')])
        assert ledger.get(first)['state'] == 'accepted'
        assert ledger.get(second)['state'] == 'unknown'
        assert ledger.get(second)['conflict_remote_id'] == 'fixture-urn:li:share:123'
        with pytest.raises(ValueError):
            ledger.get_linkedin_fixture_receipt(second)
    finally:
        con.close()


def test_exited_worker_leaves_claim_locked_until_explicit_recovery(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
    finally:
        con.close()
    script = ('import os,sqlite3,sys; from scripts.social.destination_ledger_fixture import DestinationFixtureLedger; '
              'c=sqlite3.connect(sys.argv[1]); l=DestinationFixtureLedger.open(c); '
              "l.claim_due(sys.argv[2],expected_version=1,now='2026-11-20T03:00:00Z'); os._exit(0)")
    subprocess.run([sys.executable, '-c', script, str(database), item], check=True, timeout=30)
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        row = ledger.get(item)
        assert row['state'] == 'submitting'
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.mark_unknown(item, attempt=row['attempt_id'])
        assert ledger.get(item)['state'] == 'unknown'
    finally:
        con.close()


def test_generic_linkedin_cannot_reserve_native_receipt_id(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        key = data()['key']
        key.update(account_id='fixture-generic-account', destination_id='fixture-generic-target')
        item = ledger.prepare(key, {'scheduled_at': '2026-11-20T03:00:00Z'})
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        with pytest.raises(ValueError):
            ledger.finish(item, attempt=attempt, destination=key['destination_id'], remote_id='fixture-urn:li:share:123')
    finally:
        con.close()


def test_receipt_reader_rejects_inconsistent_intent(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                       headers=[('x-restli-id', 'urn:li:share:123')])
        con.execute("UPDATE destination_fixture_intents SET state='unknown' WHERE intent_id=?", (item,))
        con.commit()
        with pytest.raises(ValueError):
            ledger.get_linkedin_fixture_receipt(item)
    finally:
        con.close()


def test_v3_fixture_refuses_linkedin_claim_before_state_change(tmp_path):
    from scripts.social.destination_ledger_fixture import _DDL, _REEL_DDL
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        con.execute(_DDL)
        con.execute(_REEL_DDL)
        con.execute('PRAGMA user_version=3')
        con.commit()
        ledger = DestinationFixtureLedger.open(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        assert ledger.scan_due(now='2026-11-20T03:00:00Z') == {'due': [], 'invalid': [item]}
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        assert ledger.get(item)['state'] == 'prepared'
    finally:
        con.close()


def test_receipt_insert_rolls_back_if_intent_update_fails(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
        con.execute("CREATE TEMP TRIGGER fail_fixture_accept BEFORE UPDATE OF state ON main.destination_fixture_intents "
                    "WHEN NEW.state='accepted' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.finish_linkedin_fixture(item, attempt=attempt, status=201,
                                           headers=[('x-restli-id', 'urn:li:share:123')])
        assert ledger.get(item)['state'] == 'submitting'
        assert con.execute('SELECT count(*) FROM linkedin_fixture_receipts').fetchone()[0] == 0
    finally:
        con.close()


def test_concurrent_linkedin_receipts_assign_urn_only_once(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        first = prepare_linkedin_fixture(ledger, **data())
        args = data()
        args['key']['occurrence_key'] = 'fixture-second'
        second = prepare_linkedin_fixture(ledger, **args)
        attempts = []
        for item in (first, second):
            ledger.approve(item, expected_version=1)
            attempts.append(ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z'))
    finally:
        con.close()
    barrier = threading.Barrier(2)
    def submit(pair):
        connection = sqlite3.connect(database, timeout=10)
        try:
            session = DestinationFixtureLedger.open(connection)
            barrier.wait(timeout=10)
            session.finish_linkedin_fixture(pair[0], attempt=pair[1], status=201,
                                            headers=[('x-restli-id', 'urn:li:share:123')])
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(submit, zip((first, second), attempts)))
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert sorted(ledger.get(item)['state'] for item in (first, second)) == ['accepted', 'unknown']
        assert con.execute('SELECT count(*) FROM linkedin_fixture_receipts').fetchone()[0] == 1
    finally:
        con.close()


def test_receipt_is_durable_after_worker_exits(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    database = tmp_path / 'fixture.sqlite'
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        attempt = ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()
    script = ('import os,sqlite3,sys; from scripts.social.destination_ledger_fixture import DestinationFixtureLedger; '
              'c=sqlite3.connect(sys.argv[1]); l=DestinationFixtureLedger.open(c); '
              "l.finish_linkedin_fixture(sys.argv[2],attempt=sys.argv[3],status=201,headers=[('x-restli-id','urn:li:share:123')]); "
              'os._exit(0)')
    subprocess.run([sys.executable, '-c', script, str(database), item, attempt], check=True, timeout=30)
    con = sqlite3.connect(database)
    try:
        ledger = DestinationFixtureLedger.open(con)
        assert ledger.get(item)['state'] == 'accepted'
        assert ledger.get_linkedin_fixture_receipt(item)['post_urn'] == 'urn:li:share:123'
    finally:
        con.close()


@pytest.mark.parametrize('kind', [None, 'image', 'video'])
def test_linkedin_candidate_is_bound_to_due_fixture(tmp_path, monkeypatch, kind):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network'))
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data(kind))
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        assert payload['candidate']['request']['body']['author'] == 'urn:li:person:fixture-member'
        if kind:
            assert payload['candidate']['request']['body']['content']['media']['id'] == f'urn:li:{kind}:fixture-media'
        assert ledger.get(item)['grant_version'] is None
        ledger.approve(item, expected_version=1)
        assert ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()


@pytest.mark.parametrize('change', ['candidate', 'source', 'author', 'schema', 'schedule', 'media'])
def test_revision_rejects_inconsistent_snapshot(tmp_path, change):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data('image'))
        ledger.approve(item, expected_version=1)
        payload = json.loads(ledger.get(item)['snapshot_json'])['payload']
        if change == 'candidate': payload['candidate']['request']['body']['commentary'] = 'Khác'
        elif change == 'source': payload['source'] += 'Khác'
        elif change == 'author': payload['author'] = 'urn:li:person:fixture-other'
        elif change == 'schema': del payload['fixture_schema']
        elif change == 'schedule': del payload['scheduled_at']
        else: payload['media_urn'] = 'urn:li:image:fixture-other'
        with pytest.raises(ValueError):
            ledger.revise(item, payload)
        assert ledger.get(item)['grant_version'] == 1
    finally:
        con.close()


def test_generic_account_cannot_reserve_native_destination(tmp_path):
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        key = data()['key']
        key['account_id'] = 'fixture-other'
        with pytest.raises(ValueError):
            ledger.prepare(key, {'text': 'fixture'})
    finally:
        con.close()


@pytest.mark.parametrize('change', ['author', 'real_media', 'metadata'])
def test_mismatched_inputs_do_not_create_record(tmp_path, change):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data('image')
        if change == 'author': args['author'] = 'urn:li:person:fixture-other'
        elif change == 'real_media': args['media_urn'] = 'urn:li:image:real-image'
        else: args['source'] = '---\nschema: content/1\ncontent_id: other\ncampaign_id: fixture-campaign\n---\n' + args['source']
        with pytest.raises(ValueError):
            prepare_linkedin_fixture(ledger, **args)
        assert con.execute('SELECT count(*) FROM destination_fixture_intents').fetchone()[0] == 0
    finally:
        con.close()


def test_organization_target_is_bound_to_numeric_author(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data('video')
        args['author'] = 'urn:li:organization:12345'
        args['media_observation']['owner'] = args['author']
        args['key']['account_id'] = 'fixture-linkedin-org-account-12345'
        args['key']['destination_id'] = 'fixture-linkedin-org-12345'
        item = prepare_linkedin_fixture(ledger, **args)
        assert json.loads(ledger.get(item)['snapshot_json'])['payload']['author'] == args['author']
        args['author'] = 'urn:li:organization:12346'
        with pytest.raises(ValueError):
            prepare_linkedin_fixture(ledger, **args)
    finally:
        con.close()


@pytest.mark.parametrize('change', ['wrong_owner', 'processing', 'missing'])
def test_media_requires_matching_available_fixture_observation(tmp_path, change):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        args = data('image')
        if change == 'wrong_owner': args['media_observation']['owner'] = 'urn:li:person:fixture-other'
        elif change == 'processing': args['media_observation']['status'] = 'PROCESSING'
        else: args['media_observation'] = None
        with pytest.raises(ValueError):
            prepare_linkedin_fixture(ledger, **args)
    finally:
        con.close()


def test_due_scan_rejects_modified_candidate_with_new_checksum(tmp_path):
    from scripts.social.linkedin_fixture_flow import prepare_linkedin_fixture
    from scripts.social.fixture_ledger import _snapshot_digest
    con = sqlite3.connect(tmp_path / 'fixture.sqlite')
    try:
        ledger = DestinationFixtureLedger.initialize(con)
        item = prepare_linkedin_fixture(ledger, **data())
        ledger.approve(item, expected_version=1)
        snapshot = json.loads(ledger.get(item)['snapshot_json'])
        snapshot['payload']['candidate']['request']['body']['author'] = 'urn:li:person:fixture-other'
        con.execute('UPDATE destination_fixture_intents SET snapshot_json=?,snapshot_digest=? WHERE intent_id=?',
                    (json.dumps(snapshot), _snapshot_digest(snapshot), item))
        con.commit()
        assert ledger.scan_due(now='2026-11-20T03:00:00Z')['invalid'] == [item]
        with pytest.raises(ValueError):
            ledger.claim_due(item, expected_version=1, now='2026-11-20T03:00:00Z')
    finally:
        con.close()
