"""Offline dispatcher must never claim or submit without source-backed authority."""

from importlib.util import find_spec
import hashlib

import pytest


def fake_gate_proof(scope):
    """Synthetic test data only; this is not evidence of human approval."""
    return {'gate': scope['gate'], 'scope': scope, 'by': 'fixture',
            'quote': 'fixture approval', 'source_digest': 'a' * 64}


def test_dispatcher_refuses_when_source_authority_is_not_implemented(tmp_path):
    assert find_spec('scripts.pipeline.publish_dispatch') is not None
    from scripts.pipeline.publish_dispatch import dispatch

    result = dispatch(tmp_path / 'ledger.sqlite3', 'sample-intent')
    assert result.state == 'blocked'
    assert result.reason == 'approval_binding_unavailable'
    assert not (tmp_path / 'ledger.sqlite3').exists()


def test_existing_facebook_runner_remains_default_owner():
    from scripts.pipeline.publish_dispatch import choose_owner

    assert choose_owner('facebook', 'page-a', {}, {('facebook', 'page-a')}) == 'legacy'


def test_two_routes_for_same_target_are_rejected():
    from scripts.pipeline.publish_dispatch import choose_owner

    with pytest.raises(ValueError, match='conflicting routes'):
        choose_owner('facebook', 'page-a', {('facebook', 'page-a'): 'postiz'},
                     {('facebook', 'page-a')})


def test_owner_is_not_guessed_when_no_route_exists():
    from scripts.pipeline.publish_dispatch import choose_owner

    with pytest.raises(ValueError, match='no route'):
        choose_owner('linkedin', 'page-b', {}, set())


@pytest.mark.parametrize(('platform', 'account', 'routes'), [
    (None, 'p', {}), ('facebook', [], {}), (' ', 'p', {(' ', 'p'): 'postiz'}),
    ('facebook', ' p', {('facebook', ' p'): 'postiz'}),
])
def test_invalid_target_fails_closed(platform, account, routes):
    from scripts.pipeline.publish_dispatch import choose_owner

    with pytest.raises(ValueError, match='target'):
        choose_owner(platform, account, routes, set())


def test_offline_lost_response_stays_unknown_and_does_not_submit_again(tmp_path):
    """A successful fake side effect before crash must not be retried blindly.

    Scope bindings here are synthetic and do not prove a human approval.
    """
    from scripts.lib.delivery_ledger import DeliveryLedger
    from scripts.lib.postiz_adapter import FakePostiz

    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    ledger = DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = []
    for gate in ('g1', 'g2'):
        scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id',
                                      'content_id', 'post_id')}
        scope['post_id'] = '*' if gate == 'g1' else key['post_id']
        scope['gate'] = gate
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=fake_gate_proof)
        scopes.append((scope, 1))
    intent_id = ledger.prepare(key, 'demo-digest', 'postiz', 1, scopes=scopes)
    ledger.claim(intent_id, 1, verifier=fake_gate_proof)
    fake = FakePostiz()
    fake.submit(intent_id, scheduled=True)  # response lost before ledger.resolve()
    ledger.recover_inflight(intent_id)
    with pytest.raises(ValueError):
        ledger.claim(intent_id, 1, verifier=fake_gate_proof)
    assert ledger.get(intent_id)['state'] == 'unknown'
    assert fake.submission_count == 1


def test_scheduled_fake_receipt_survives_restart_without_marking_published(tmp_path):
    """The remote job ID is retained independently from a real platform ID."""
    from scripts.lib.delivery_ledger import DeliveryLedger
    from scripts.lib.postiz_adapter import FakePostiz

    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    path = tmp_path / 'ledger.sqlite3'
    ledger = DeliveryLedger(path)
    scopes = []
    for gate in ('g1', 'g2'):
        scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id',
                                      'content_id', 'post_id')}
        scope['post_id'] = '*' if gate == 'g1' else key['post_id']
        scope['gate'] = gate
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=fake_gate_proof)
        scopes.append((scope, 1))
    intent_id = ledger.prepare(key, 'demo-digest', 'postiz', 1, scopes=scopes)
    attempt_id = ledger.claim(intent_id, 1, verifier=fake_gate_proof)
    response = FakePostiz().submit(intent_id, scheduled=True)
    ledger.resolve(intent_id, attempt_id, response.state,
                   remote_job_id=response.remote_job_id)
    restored = DeliveryLedger(path).get(intent_id)
    assert restored['state'] == 'scheduled'
    assert restored['remote_job_id'] == response.remote_job_id
    assert restored['platform_post_id'] is None
    assert restored['platform_url'] is None


def test_fake_readback_is_reconciled_and_looked_up_without_new_submit(tmp_path):
    """Only synthetic evidence is used; no dispatch or human approval is asserted."""
    from scripts.lib.delivery_ledger import DeliveryLedger
    from scripts.lib.postiz_adapter import FakePostiz, reconcile_fake

    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    ledger = DeliveryLedger(tmp_path / 'ledger.sqlite3')
    scopes = []
    for gate in ('g1', 'g2'):
        scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id',
                                      'content_id', 'post_id')}
        scope['post_id'] = '*' if gate == 'g1' else key['post_id']
        scope['gate'] = gate
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=fake_gate_proof)
        scopes.append((scope, 1))
    intent_id = ledger.prepare(key, 'demo-digest', 'postiz', 1, scopes=scopes)
    attempt_id = ledger.claim(intent_id, 1, verifier=fake_gate_proof)
    fake = FakePostiz()
    scheduled = fake.submit(intent_id, scheduled=True)
    ledger.resolve(intent_id, attempt_id, scheduled.state,
                   remote_job_id=scheduled.remote_job_id,
                   provider_instance_id=fake.instance_id, integration_id='fake-integration')
    fake.publish(scheduled.remote_job_id, platform_post_id='page_77',
                 platform_url='https://example.invalid/page/77')
    observation = reconcile_fake(fake, scheduled.remote_job_id, expected_instance_id=fake.instance_id)
    evidence = dict(state=observation.state, platform='facebook', account_id='page',
                    provider_instance_id=fake.instance_id, integration_id='fake-integration',
                    remote_job_id=observation.remote_job_id, remote_post_id=None,
                    platform_post_id=observation.platform_post_id,
                    platform_url=observation.platform_url, evidence_kind='provider_confirmed')
    assert ledger.reconcile(intent_id, 'scheduled', verifier=lambda _: evidence) == 'published'
    matches = ledger.lookup_platform('facebook', 'page', 'page_77')
    assert len(matches) == 1
    assert matches[0]['intent_id'] == intent_id
    assert matches[0]['remote_job_id'] == scheduled.remote_job_id
    assert fake.submission_count == 1


def test_offline_batch_keeps_unapproved_item_prepared_while_first_is_scheduled(tmp_path):
    """Exercise real ledger with synthetic proof; no dispatcher or human is involved."""
    from delivery_ledger import DeliveryLedger
    from postiz_adapter import FakePostiz

    ledger = DeliveryLedger(tmp_path / 'ledger.sqlite3')
    fake = FakePostiz()
    intents = []
    for post_id in ('post-a', 'post-b'):
        key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
                   content_id='content', post_id=post_id, platform='facebook',
                   account_id='page', occurrence_key='initial')
        scopes = []
        for gate in ('g1', 'g2'):
            scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id',
                                          'content_id', 'post_id')}
            scope['post_id'] = '*' if gate == 'g1' else post_id
            scope['gate'] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=fake_gate_proof)
            scopes.append((scope, 1))
        intents.append(ledger.prepare(key, 'demo-digest', 'postiz', 1, scopes=scopes))

    attempt = ledger.claim(intents[0], 1, verifier=fake_gate_proof)
    scheduled = fake.submit(intents[0], scheduled=True)
    ledger.resolve(intents[0], attempt, scheduled.state, remote_job_id=scheduled.remote_job_id,
                   provider_instance_id=fake.instance_id, integration_id='fake-integration')

    def changed_proof(scope):
        proof = fake_gate_proof(scope)
        if scope['post_id'] == 'post-b':
            proof['source_digest'] = 'b' * 64
        return proof

    with pytest.raises(ValueError, match='proof mismatch'):
        ledger.claim(intents[1], 1, verifier=changed_proof)
    assert ledger.get(intents[0])['state'] == 'scheduled'
    assert ledger.get(intents[1])['state'] == 'prepared'
    assert fake.submission_count == 1


def test_validated_media_bytes_are_frozen_to_approved_digest():
    from scripts.lib.delivery_adapters import validate_staged_bytes

    image = b'\x89PNG\r\n\x1a\n' + b'fake-image-data'
    digest = hashlib.sha256(image).hexdigest()
    frozen = validate_staged_bytes(image, kind='image/png', max_bytes=100, expected_sha256=digest)
    assert frozen == image
    with pytest.raises(ValueError, match='digest'):
        validate_staged_bytes(image + b'changed', kind='image/png', max_bytes=100,
                              expected_sha256=digest)


@pytest.mark.parametrize(('data', 'kind', 'size'), [
    (b'not-an-image', 'image/png', 100),
    (b'\x89PNG\r\n\x1a\nmore', 'image/png', 8),
    (b'\x89PNG\r\n\x1a\nmore', 'video/mp4', 100),
    (b'\x89PNG\r\n\x1a\nmore', [], 100),
])
def test_media_validation_rejects_bad_type_or_size(data, kind, size):
    from scripts.lib.delivery_adapters import validate_staged_bytes

    with pytest.raises(ValueError):
        validate_staged_bytes(data, kind=kind, max_bytes=size,
                              expected_sha256=hashlib.sha256(data).hexdigest())


def test_fake_dispatch_rejects_filesystem_before_reading(tmp_path):
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_fake

    class NeverReadLedger:
        @property
        def path(self):
            raise AssertionError('ledger must not be accessed')

    with pytest.raises(ValueError, match='filesystem-backed fake dispatch disabled'):
        dispatch_fake(tmp_path / 'user-data', tmp_path, NeverReadLedger(),
                      'intent', {'artifacts': []}, FakePostiz())




def _fixture_verifier(payload):
    from delivery_contract import canonical_snapshot
    _, digest = canonical_snapshot(payload)
    def verify(scope):
        proof = fake_gate_proof(scope)
        if scope['gate'] == 'g2':
            proof['source_digest'] = digest
        return proof
    return verify


def _synthetic_ledger_and_intent(*, extra=None):
    from delivery_ledger import DeliveryLedger
    ledger = DeliveryLedger.synthetic_memory()
    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    payload = {**key, 'text': 'Example', 'artifacts': [], 'mode': 'scheduled',
               'scheduled_at': '2026-11-18T03:00:00Z', 'timezone': 'Asia/Ho_Chi_Minh',
               'privacy': 'public', **(extra or {})}
    scopes = []
    for gate in ('g1', 'g2'):
        scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
        scope['post_id'] = '*' if gate == 'g1' else key['post_id']
        scope['gate'] = gate
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=_fixture_verifier(payload))
        scopes.append((scope, 1))
    intent = ledger.prepare_fixture(key, payload, 'channel/campaign/content', 'postiz', 1, scopes=scopes)
    return ledger, intent, payload


def test_synthetic_dispatch_claims_once_and_records_scheduled_without_platform_id():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        result = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        assert result.state == 'scheduled'
        stored = ledger.get(intent)
        assert stored['state'] == 'scheduled'
        assert stored['remote_job_id'] == result.remote_job_id
        assert stored['provider_instance_id'] == fake.instance_id
        assert fake.get_payload(result.remote_job_id) == payload
        assert stored['platform_post_id'] is None
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_dispatch_rejects_changed_occurrence_before_submit():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, {**payload, 'occurrence_key': 'extra'}, fake,
                               verifier=_fixture_verifier(payload))
        assert fake.submission_count == 0
        assert ledger.get(intent)['state'] == 'prepared'
    finally:
        ledger.close()


def test_synthetic_dispatch_rejects_nonfake_provider_and_real_ledger(tmp_path):
    from delivery_ledger import DeliveryLedger
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    try:
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, object(), verifier=_fixture_verifier(payload))
        real_ledger = DeliveryLedger(tmp_path / 'ledger.sqlite3')
        with pytest.raises(ValueError):
            dispatch_synthetic(real_ledger, intent, payload, FakePostiz(), verifier=_fixture_verifier(payload))
    finally:
        ledger.close()


def test_synthetic_dispatch_after_lost_response_is_unknown_and_not_retried():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    original = fake.submit

    def lost_response(intent_id, *, scheduled, payload):
        original(intent_id, scheduled=scheduled, payload=payload)
        raise RuntimeError('simulated secret must not appear')

    fake.submit = lost_response
    try:
        with pytest.raises(ValueError, match='synthetic outcome unknown') as error:
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        assert 'simulated secret' not in str(error.value)
        assert ledger.get(intent)['state'] == 'unknown'
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_dispatch_through_readback_and_projection():
    """This exercises real components with synthetic approval, not campaign files."""
    from postiz_adapter import FakePostiz, reconcile_fake
    from register_publish import project_delivery_fixture
    from scripts.pipeline.publish_dispatch import dispatch_synthetic

    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        submitted = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        fake.publish(submitted.remote_job_id, platform_post_id='page_77',
                     platform_url='https://example.invalid/page/77')
        observed = reconcile_fake(fake, submitted.remote_job_id,
                                  expected_instance_id=fake.instance_id)
        evidence = dict(state=observed.state, platform='facebook', account_id='page',
                        provider_instance_id=fake.instance_id, integration_id='synthetic-integration',
                        remote_job_id=observed.remote_job_id, remote_post_id=None,
                        platform_post_id=observed.platform_post_id,
                        platform_url=observed.platform_url, evidence_kind='provider_confirmed',
                        published_at='2026-11-18T03:00:00Z')
        assert ledger.reconcile(intent, 'scheduled', verifier=lambda _: evidence) == 'published'
        original = {'channel_id': 'channel', 'campaign_id': 'campaign', 'post_id': 'content',
                    'posts': [{'post_id': 'post', 'channel': 'facebook',
                               'post_format': 'picture', 'publish': {'plan': ''}}]}
        projected = project_delivery_fixture(ledger, intent, original)
        assert projected['posts'][0]['publish']['platform_id'] == 'page_77'
        assert projected['posts'][0]['publish']['link'] == 'https://example.invalid/page/77'
        assert 'status' not in original['posts'][0]['publish']
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_dispatch_sends_frozen_fixture_even_if_caller_mutates_during_claim():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    stable_verifier = _fixture_verifier(payload)
    def mutating_verifier(scope):
        payload['text'] = 'changed after snapshot'
        return stable_verifier(scope)
    try:
        result = dispatch_synthetic(ledger, intent, payload, fake, verifier=mutating_verifier)
        assert fake.get_payload(result.remote_job_id)['text'] == 'Example'
    finally:
        ledger.close()


def test_synthetic_batch_dispatches_approved_item_and_blocks_changed_proof():
    """One stale fixture must not cause the other item to be sent twice."""
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic

    ledger, first, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        second_key = {k: payload[k] for k in ('station_id', 'channel_id', 'campaign_id',
                       'content_id', 'post_id', 'platform', 'account_id', 'occurrence_key')}
        second_key['post_id'] = 'other-post'
        second_payload = {**payload, 'post_id': 'other-post'}
        scopes = []
        for gate in ('g1', 'g2'):
            scope = {k: second_key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
            scope['post_id'] = '*' if gate == 'g1' else second_key['post_id']
            scope['gate'] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=(_fixture_verifier(payload) if gate == 'g1' else _fixture_verifier(second_payload)))
            scopes.append((scope, 1))
        second = ledger.prepare_fixture(second_key, second_payload, 'channel/campaign/other',
                                        'postiz', 1, scopes=scopes)
        result = dispatch_synthetic(ledger, first, payload, fake, verifier=_fixture_verifier(payload))
        def changed(scope):
            proof = (_fixture_verifier(second_payload) if scope['post_id'] == 'other-post' else _fixture_verifier(payload))(scope)
            if scope['post_id'] == 'other-post':
                proof['source_digest'] = 'b' * 64
            return proof
        with pytest.raises(ValueError, match='scope proof verification failed'):
            dispatch_synthetic(ledger, second, second_payload, fake, verifier=changed)
        assert result.state == 'scheduled'
        assert ledger.get(second)['state'] == 'prepared'
        assert fake.submission_count == 1
    finally:
        ledger.close()


@pytest.mark.parametrize(('field', 'changed'), [
    ('text', 'different copy'), ('account_id', 'another-page'),
    ('occurrence_key', 'second-run'),
])
def test_synthetic_dispatch_rejects_reuse_of_approval_for_different_payload(field, changed):
    """The same G2 evidence must not authorize a different snapshot or target."""
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, _, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        changed_payload = {**payload, field: changed}
        key_names = ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id',
                     'platform', 'account_id', 'occurrence_key')
        key = {name: changed_payload[name] for name in key_names}
        scopes = []
        for gate in ('g1', 'g2'):
            scope = {name: key[name] for name in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
            scope['post_id'] = '*' if gate == 'g1' else key['post_id']
            scope['gate'] = gate
            scopes.append((scope, 1))
        if field == 'text':
            key['occurrence_key'] = 'text-change-attempt'
            changed_payload['occurrence_key'] = 'text-change-attempt'
        intent = ledger.prepare_fixture(key, changed_payload, 'channel/campaign/content', 'postiz', 1, scopes=scopes)
        with pytest.raises(ValueError, match='scope proof verification failed'):
            dispatch_synthetic(ledger, intent, changed_payload, fake, verifier=_fixture_verifier(payload))
        assert ledger.get(intent)['state'] == 'prepared'
        assert fake.submission_count == 0
    finally:
        ledger.close()


def test_synthetic_dispatch_reports_unknown_if_revoked_during_submission():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    original = fake.submit
    def submit_then_revoke(intent_id, *, scheduled, payload):
        result = original(intent_id, scheduled=scheduled, payload=payload)
        assert ledger.revoke(intent_id, 1, by='fixture', quote='withdraw fixture', gate='g2') == 'unknown'
        return result
    fake.submit = submit_then_revoke
    try:
        result = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        stored = ledger.get(intent)
        assert stored['state'] == 'unknown'
        assert result.state == 'unknown'
        assert stored['remote_job_id'] == result.remote_job_id
        assert fake.submission_count == 1
    finally:
        ledger.close()


@pytest.mark.parametrize(('field','value'), [
    ('text', None), ('text', ''), ('scheduled_at', 'not-a-time'),
    ('scheduled_at', '2026-11-18T03:00:00'), ('timezone', 'Mars/Olympus'),
    ('privacy', 'unknown-privacy'),
])
def test_synthetic_dispatch_rejects_invalid_preview_even_when_bound(field, value):
    """A matching digest must not authorize an invalid synthetic preview."""
    from delivery_ledger import DeliveryLedger
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger = DeliveryLedger.synthetic_memory()
    fake = FakePostiz()
    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    payload = {**key, 'text': 'Example', 'artifacts': [], 'mode': 'scheduled',
               'scheduled_at': '2026-11-18T03:00:00Z', 'timezone': 'Asia/Ho_Chi_Minh',
               'privacy': 'public', field: value}
    verifier = _fixture_verifier(payload)
    try:
        scopes = []
        for gate in ('g1','g2'):
            scope = {k:key[k] for k in ('station_id','channel_id','campaign_id','content_id','post_id')}
            scope['post_id'] = '*' if gate == 'g1' else key['post_id']
            scope['gate'] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=verifier)
            scopes.append((scope, 1))
        intent = ledger.prepare_fixture(key, payload, 'channel/campaign/content', 'postiz', 1, scopes=scopes)
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, fake, verifier=verifier)
        assert ledger.get(intent)['state'] == 'prepared'
        assert fake.submission_count == 0
    finally:
        ledger.close()


def test_synthetic_dispatch_refuses_wildcard_g2_scope():
    from delivery_ledger import DeliveryLedger
    ledger = DeliveryLedger.synthetic_memory()
    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    payload = {**key, 'text':'Example', 'artifacts':[], 'mode':'scheduled',
               'scheduled_at':'2026-11-18T03:00:00Z','timezone':'Asia/Ho_Chi_Minh', 'privacy':'public'}
    verifier = _fixture_verifier(payload)
    scopes=[]
    try:
        for gate in ('g1','g2'):
            scope = {k:key[k] for k in ('station_id','channel_id','campaign_id','content_id','post_id')}
            scope.update(gate=gate, post_id='*')
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=verifier)
            scopes.append((scope,1))
        with pytest.raises(ValueError):
            ledger.prepare_fixture(key, payload, 'channel/campaign/content', 'postiz', 1, scopes=scopes)
        with ledger._connect() as con:
            assert con.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 0
    finally:
        ledger.close()


def test_synthetic_dispatch_sanitizes_failure_when_revoke_has_already_marked_unknown():
    """Recovery races must not expose provider errors or trigger another submit."""
    import traceback
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    original = fake.submit
    def submit_revoke_raise(intent_id, *, scheduled, payload):
        original(intent_id, scheduled=scheduled, payload=payload)
        ledger.revoke(intent_id, 1, by='fixture', quote='fixture revoke', gate='g2')
        raise RuntimeError('SYNTHETIC_UPSTREAM_SECRET_MARKER')
    fake.submit = submit_revoke_raise
    try:
        with pytest.raises(ValueError, match='synthetic outcome unknown') as error:
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        output = ''.join(traceback.format_exception(error.type, error.value, error.tb))
        assert 'SYNTHETIC_UPSTREAM_SECRET_MARKER' not in output
        assert ledger.get(intent)['state'] == 'unknown'
        assert fake.submission_count == 1
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_dispatch_sanitizes_recovery_failure_without_retry():
    import traceback
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    def fail_submit(*args, **kwargs):
        raise RuntimeError('SYNTHETIC_PROVIDER_MARKER')
    def fail_recovery(*args, **kwargs):
        raise RuntimeError('SYNTHETIC_RECOVERY_MARKER')
    fake.submit = fail_submit
    ledger.recover_inflight = fail_recovery
    try:
        with pytest.raises(ValueError, match='synthetic recovery failed') as error:
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        output = ''.join(traceback.format_exception(error.type, error.value, error.tb))
        assert 'SYNTHETIC_PROVIDER_MARKER' not in output
        assert 'SYNTHETIC_RECOVERY_MARKER' not in output
        assert ledger.get(intent)['state'] == 'submitting'
        with pytest.raises(ValueError):
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
    finally:
        ledger.close()


def test_synthetic_dispatch_sanitizes_recovery_and_status_read_failure():
    import traceback
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    original_get = ledger.get
    def fail_submit(*args, **kwargs):
        ledger.get = lambda *_: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_STATUS_MARKER'))
        raise RuntimeError('SYNTHETIC_PROVIDER_MARKER')
    fake.submit = fail_submit
    ledger.recover_inflight = lambda *_: (_ for _ in ()).throw(RuntimeError('SYNTHETIC_RECOVERY_MARKER'))
    try:
        with pytest.raises(ValueError, match='synthetic recovery failed') as error:
            dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        output = ''.join(traceback.format_exception(error.type, error.value, error.tb))
        assert 'SYNTHETIC_PROVIDER_MARKER' not in output
        assert 'SYNTHETIC_RECOVERY_MARKER' not in output
        assert 'SYNTHETIC_STATUS_MARKER' not in output
        assert original_get(intent)['state'] == 'submitting'
    finally:
        ledger.close()


def test_synthetic_dispatch_accepts_package_imported_fixture_types_without_subclasses():
    """The supported package imports must not be rejected solely by module alias."""
    from scripts.lib.delivery_ledger import DeliveryLedger
    from scripts.lib.postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    ledger = DeliveryLedger.synthetic_memory()
    key = dict(station_id='station', channel_id='channel', campaign_id='campaign',
               content_id='content', post_id='post', platform='facebook',
               account_id='page', occurrence_key='initial')
    payload = {**key, 'text': 'Example', 'artifacts': [], 'mode': 'scheduled',
               'scheduled_at': '2026-11-18T03:00:00Z', 'timezone': 'Asia/Ho_Chi_Minh',
               'privacy': 'public'}
    verifier = _fixture_verifier(payload)
    try:
        scopes = []
        for gate in ('g1', 'g2'):
            scope = {k: key[k] for k in ('station_id', 'channel_id', 'campaign_id', 'content_id', 'post_id')}
            scope['post_id'] = '*' if gate == 'g1' else key['post_id']
            scope['gate'] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=verifier)
            scopes.append((scope, 1))
        intent = ledger.prepare_fixture(key, payload, 'channel/campaign/content', 'postiz', 1, scopes=scopes)
        fake = FakePostiz()
        result = dispatch_synthetic(ledger, intent, payload, fake, verifier=verifier)
        assert result.state == 'scheduled'
        from postiz_adapter import reconcile_fake
        from scripts.pipeline.register_publish import project_delivery_fixture
        fake.publish(result.remote_job_id, platform_post_id='page_77',
                     platform_url='https://example.invalid/page/77')
        observed = reconcile_fake(fake, result.remote_job_id,
                                  expected_instance_id=fake.instance_id)
        evidence = dict(state=observed.state, platform='facebook', account_id='page',
                        provider_instance_id=fake.instance_id, integration_id='synthetic-integration',
                        remote_job_id=observed.remote_job_id, remote_post_id=None,
                        platform_post_id=observed.platform_post_id, platform_url=observed.platform_url,
                        evidence_kind='provider_confirmed', published_at='2026-11-18T03:00:00Z')
        assert ledger.reconcile(intent, 'scheduled', verifier=lambda _: evidence) == 'published'
        doc = {'channel_id':'channel', 'campaign_id':'campaign', 'post_id':'content',
               'posts':[{'post_id':'post', 'channel':'facebook', 'post_format':'picture',
                         'publish': {'plan':''}}]}
        assert project_delivery_fixture(ledger, intent, doc)['posts'][0]['publish']['platform_id'] == 'page_77'
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_dispatch_rejects_subclass_of_package_fake_provider():
    from scripts.lib.delivery_ledger import DeliveryLedger
    from scripts.lib.postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic
    class NetworkLikeFake(FakePostiz):
        def submit(self, *args, **kwargs):
            raise AssertionError('subclass must never be invoked')
    ledger = DeliveryLedger.synthetic_memory()
    try:
        with pytest.raises(ValueError, match='synthetic memory ledger'):
            dispatch_synthetic(ledger, 'missing', {}, NetworkLikeFake(), verifier=lambda _: {})
    finally:
        ledger.close()


def test_dispatch_module_imports_in_fresh_interpreter_without_pythonpath():
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    program = ('from scripts.pipeline.publish_dispatch import dispatch_synthetic; '
               'from scripts.lib.delivery_ledger import DeliveryLedger; '
               'from scripts.lib.postiz_adapter import FakePostiz; '
               'assert callable(dispatch_synthetic); assert callable(DeliveryLedger.synthetic_memory); '
               'assert FakePostiz().submission_count == 0')
    result = subprocess.run([sys.executable, '-c', program], cwd=root, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


class _SyntheticClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
    def monotonic(self):
        return self.now
    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def test_poll_synthetic_backoff_and_published_readback_never_resubmit():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        sent = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        def sleep_and_publish(delay):
            clock.sleep(delay)
            if len(clock.sleeps) == 2:
                fake.publish(sent.remote_job_id, platform_post_id='page_90',
                             platform_url='https://example.invalid/page/90',
                             published_at='2026-11-18T03:00:00Z')
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=sleep_and_publish)
        assert (result.state, result.reason, result.attempts) == ('published', 'confirmed', 3)
        assert clock.sleeps == [1.0, 2.0]
        assert ledger.get(intent)['state'] == 'published'
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_budget_timeout_does_not_fake_failure_or_resubmit():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=2.0)
        assert result.state == 'unknown'
        assert result.reason == 'budget_exhausted'
        assert result.attempts == 2
        assert clock.sleeps == [1.0]
        assert ledger.get(intent)['state'] == 'scheduled'
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_honours_fake_rate_limit_without_resubmit():
    from postiz_adapter import FakePostiz, SyntheticRateLimitError
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        original = fake.get_delivery
        calls = []
        def rate_limited_once(job_id):
            calls.append(clock.now)
            if len(calls) == 1:
                raise SyntheticRateLimitError(5.0)
            return original(job_id)
        fake.get_delivery = rate_limited_once
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=10, max_attempts=2)
        assert (result.state, result.reason, result.attempts) == ('unknown', 'attempt_limit', 2)
        assert clock.sleeps == [5.0]
        assert calls == [0.0, 5.0]
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_never_exposes_readback_exception_or_retries_submit():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        def fail_read(_):
            raise RuntimeError('SYNTHETIC_TOKEN_MARKER')
        fake.get_delivery = fail_read
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=10, max_attempts=3)
        assert (result.state, result.reason, result.attempts) == ('unknown', 'attempt_limit', 3)
        assert clock.sleeps == [1.0, 2.0]
        assert ledger.get(intent)['state'] == 'scheduled'
        assert fake.submission_count == 1
        assert 'SYNTHETIC_TOKEN_MARKER' not in repr(result)
    finally:
        ledger.close()


def test_poll_synthetic_stuck_clock_never_bypasses_minimum_interval():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        original = fake.get_delivery
        reads = []
        def count_read(job_id):
            reads.append(job_id)
            return original(job_id)
        fake.get_delivery = count_read
        with pytest.raises(ValueError, match='clock did not advance'):
            poll_synthetic(ledger, intent, fake, clock=lambda: 0.0, sleep=lambda _: None)
        assert len(reads) == 1
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_two_invocations_share_minimum_interval():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    calls = []
    original = fake.get_delivery
    def track(job_id):
        calls.append(clock.now)
        return original(job_id)
    fake.get_delivery = track
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep, max_attempts=1)
        poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep, max_attempts=1)
        assert calls == [0.0, 1.0]
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_concurrent_invocation_is_rejected_without_reading():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    import threading
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake = FakePostiz()
    entered, release = threading.Event(), threading.Event()
    original = fake.get_delivery
    def paused_read(job_id):
        entered.set()
        assert release.wait(5)
        return original(job_id)
    fake.get_delivery = paused_read
    thread = None
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        thread = threading.Thread(target=lambda: poll_synthetic(ledger, intent, fake, max_attempts=1))
        thread.start()
        assert entered.wait(5)
        with pytest.raises(ValueError, match='poll already running'):
            poll_synthetic(ledger, intent, fake, max_attempts=1)
        assert fake.submission_count == 1
    finally:
        release.set()
        if thread:
            thread.join(5)
        ledger.close()


def test_poll_synthetic_retry_after_is_shared_across_invocations():
    from postiz_adapter import FakePostiz, SyntheticRateLimitError
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    reads = []
    def limited(job_id):
        reads.append(clock.now)
        raise SyntheticRateLimitError(20)
    fake.get_delivery = limited
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        first = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                               budget_seconds=5)
        second = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=3)
        assert (first.reason, first.attempts) == ('budget_exhausted', 1)
        assert (second.reason, second.attempts) == ('budget_exhausted', 0)
        assert reads == [0.0]
        assert clock.sleeps == []
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_invalid_fake_retry_after_blocks_further_readbacks():
    from postiz_adapter import FakePostiz, SyntheticRateLimitError
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    reads=[]
    def invalid(job_id):
        reads.append(job_id)
        raise SyntheticRateLimitError(float('nan'))
    fake.get_delivery = invalid
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        first=poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        second=poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        assert (first.state, first.reason, first.attempts) == ('unknown','invalid_rate_limit',1)
        assert (second.state, second.reason, second.attempts) == ('unknown','invalid_rate_limit',0)
        assert len(reads) == 1
    finally:
        ledger.close()


def test_synthetic_poll_preserves_observed_publication_metadata_for_projection():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.register_publish import project_delivery_fixture
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        sent = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        fake.publish(sent.remote_job_id, platform_post_id='page_91',
                     platform_url='https://example.invalid/page/91',
                     published_at='2026-11-18T03:00:00Z', comment_id='comment_9')
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        assert result.state == 'published'
        record = ledger.get(intent)
        assert record['published_at'] == '2026-11-18T03:00:00Z'
        assert record['comment_id'] == 'comment_9'
        doc = {'channel_id':'channel', 'campaign_id':'campaign', 'post_id':'content',
               'posts':[{'post_id':'post', 'channel':'facebook', 'post_format':'facebook_post',
                         'publish':{'plan':''}}]}
        projected = project_delivery_fixture(ledger, intent, doc)
        assert projected['posts'][0]['publish']['comment_id'] == 'comment_9'
        assert projected['posts'][0]['publish']['at'] == '2026-11-18T03:00:00Z'
    finally:
        ledger.close()


def test_synthetic_poll_without_metadata_does_not_fabricate_projection_evidence():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.register_publish import project_delivery_fixture
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        sent = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        fake.publish(sent.remote_job_id, platform_post_id='page_91',
                     platform_url='https://example.invalid/page/91')
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        assert (result.state, result.reason) == ('published', 'sync_pending')
        record = ledger.get(intent)
        assert record['published_at'] is None
        assert record['comment_id'] is None
        doc = {'channel_id':'channel', 'campaign_id':'campaign', 'post_id':'content',
               'posts':[{'post_id':'post', 'channel':'facebook', 'post_format':'facebook_post',
                         'publish':{'plan':''}}]}
        with pytest.raises(ValueError, match='evidence incomplete'):
            project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def test_poll_synthetic_counts_slow_read_toward_budget_before_attempt_limit():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        original = fake.get_delivery
        def slow_read(job_id):
            clock.now += 6.0
            return original(job_id)
        fake.get_delivery = slow_read
        result = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=5, max_attempts=1)
        assert (result.state, result.reason, result.attempts) == ('unknown', 'budget_exhausted', 1)
        assert ledger.get(intent)['state'] == 'scheduled'
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_synthetic_facebook_missing_comment_remains_sync_pending():
    from postiz_adapter import FakePostiz
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent(extra={'post_format':'facebook_post'})
    fake, clock = FakePostiz(), _SyntheticClock()
    try:
        sent = dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        fake.publish(sent.remote_job_id, platform_post_id='page_91',
                     platform_url='https://example.invalid/page/91',
                     published_at='2026-11-18T03:00:00Z')
        first = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        second = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep)
        assert (first.state, first.reason) == ('published', 'sync_pending')
        assert (second.state, second.reason) == ('published', 'sync_pending')
        assert ledger.get(intent)['comment_id'] is None
        assert fake.submission_count == 1
    finally:
        ledger.close()


def test_poll_synthetic_slow_rate_limit_keeps_retry_deadline_after_budget():
    from postiz_adapter import FakePostiz, SyntheticRateLimitError
    from scripts.pipeline.publish_dispatch import dispatch_synthetic, poll_synthetic
    ledger, intent, payload = _synthetic_ledger_and_intent()
    fake, clock = FakePostiz(), _SyntheticClock()
    reads = []
    def slow_limited(job_id):
        reads.append(clock.now)
        clock.now += 6.0
        raise SyntheticRateLimitError(20.0)
    fake.get_delivery = slow_limited
    try:
        dispatch_synthetic(ledger, intent, payload, fake, verifier=_fixture_verifier(payload))
        first = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                               budget_seconds=5.0)
        second = poll_synthetic(ledger, intent, fake, clock=clock.monotonic, sleep=clock.sleep,
                                budget_seconds=5.0)
        assert (first.state, first.reason, first.attempts) == ('unknown', 'budget_exhausted', 1)
        assert (second.state, second.reason, second.attempts) == ('unknown', 'budget_exhausted', 0)
        assert reads == [0.0]
        assert fake.submission_count == 1
    finally:
        ledger.close()
