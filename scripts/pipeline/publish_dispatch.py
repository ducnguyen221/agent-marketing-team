"""Fail-closed placeholder for the offline delivery dispatcher.

No delivery action is enabled until source-backed approval binding and its
generation are wired to the ledger and independently tested.
"""

from pathlib import Path
from collections.abc import Mapping, Set
from dataclasses import dataclass
import math
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from delivery_adapters import DeliveryResult, DispatchResult  # noqa: E402


def choose_owner(platform: str, account_id: str,
                 routes: Mapping[tuple[str, str], str],
                 legacy_targets: Set[tuple[str, str]]) -> str:
    """Select one configured owner for an exact target, without contacting it."""
    if any(not isinstance(value, str) or not value or value != value.strip()
           for value in (platform, account_id)):
        raise ValueError('target is required')
    target = (platform, account_id)
    configured = routes.get(target)
    if configured is not None and configured not in {'legacy', 'postiz'}:
        raise ValueError('unsupported route')
    if configured == 'postiz' and target in legacy_targets:
        raise ValueError('conflicting routes for target')
    if configured is not None:
        return configured
    if target in legacy_targets:
        return 'legacy'
    raise ValueError('no route for target')


def dispatch(ledger_path: Path | str, intent_id: str) -> DispatchResult:
    """Refuse without opening the ledger or invoking an adapter."""
    return DispatchResult(state='blocked', reason='approval_binding_unavailable')


def dispatch_fake(campaign: Path, station_root: Path, ledger, intent_id: str,
                  payload: dict, provider):
    """Reject before accessing filesystem; safe fixture isolation is unverified.

    Fake-provider unit tests are independent of user files. The source-backed
    fake flow must stay disabled until isolation from cloud placeholders and
    unrelated user data can be established; it is not a production route.
    """
    raise ValueError('filesystem-backed fake dispatch disabled')


def _exact_fixture_type(value, canonical, alternate_module):
    """Accept either supported import name for the same module file, not subclasses.

    Import names are not a security boundary against code running as this user;
    this avoids rejecting legitimate package imports while still refusing a
    network-capable subclass in this synthetic-only route.
    """
    if type(value) is canonical:
        return True
    alternate = sys.modules.get(alternate_module)
    original = sys.modules.get(canonical.__module__)
    if alternate is None or original is None:
        return False
    alternate_file = getattr(alternate, '__file__', None)
    original_file = getattr(original, '__file__', None)
    return (isinstance(alternate_file, str) and isinstance(original_file, str)
            and os.path.normcase(os.path.abspath(alternate_file))
            == os.path.normcase(os.path.abspath(original_file))
            and type(value) is getattr(alternate, canonical.__name__, None))


def dispatch_synthetic(ledger, intent_id, payload, provider, *, verifier):
    """Run one in-memory synthetic delivery; this is not source approval.

    The ledger must be created by synthetic_memory() and the provider must be
    the in-memory FakePostiz class. Neither route reads campaign files or calls
    a platform. The supplied verifier represents fixture data, not a person.
    """
    from delivery_contract import canonical_snapshot
    from delivery_ledger import DeliveryLedger, KEY_FIELDS
    from postiz_adapter import FakePostiz

    if (not _exact_fixture_type(ledger, DeliveryLedger, 'scripts.lib.delivery_ledger')
            or ledger._memory_uri is None or ledger._keeper is None
            or not _exact_fixture_type(provider, FakePostiz, 'scripts.lib.postiz_adapter')):
        raise ValueError('synthetic memory ledger and FakePostiz are required')
    if not isinstance(payload, dict):
        raise ValueError('invalid synthetic payload')
    if payload.get('artifacts') != [] or payload.get('mode') not in {'scheduled', 'immediate'}:
        raise ValueError('synthetic dispatcher supports text-only fixtures')
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not isinstance(payload.get('text'), str) or not payload['text'].strip():
        raise ValueError('synthetic text preview is required')
    if payload.get('privacy') not in ('public', 'private', 'unlisted'):
        raise ValueError('unsupported synthetic privacy')
    try:
        zone = payload.get('timezone')
        if not isinstance(zone, str):
            raise ValueError('invalid timezone')
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('invalid synthetic timezone') from None
    time_value = payload.get('scheduled_at')
    if payload['mode'] == 'scheduled':
        try:
            if not isinstance(time_value, str):
                raise ValueError('invalid schedule')
            parsed = datetime.fromisoformat(time_value.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise ValueError('schedule is not UTC')
        except (TypeError, ValueError, OverflowError):
            raise ValueError('invalid synthetic schedule') from None
    elif time_value is not None:
        raise ValueError('immediate fixture cannot specify a schedule')
    intent = ledger.get(intent_id)
    fixture = ledger.fixture_snapshot(intent_id)
    _, digest = canonical_snapshot(payload)
    if (any(payload.get(field) != intent[field] for field in KEY_FIELDS)
            or intent['owner'] != 'postiz' or digest != intent['payload_digest']
            or digest != fixture['payload_digest']):
        raise ValueError('synthetic payload does not match prepared intent')
    frozen = fixture['snapshot']

    def bound_fixture_verifier(scope):
        proof = verifier(scope)
        # Synthetic G2 evidence is defined as the approved snapshot digest.
        # It is not a human signature and must never authorize a real provider.
        if scope.get('gate') == 'g2' and (scope.get('post_id') != intent['post_id']
                                          or not isinstance(proof, dict)
                                          or proof.get('source_digest') != digest):
            raise ValueError('synthetic approval does not bind snapshot')
        return proof

    attempt = ledger.claim(intent_id, intent['approval_generation'], verifier=bound_fixture_verifier)
    try:
        result = provider.submit(intent_id, scheduled=frozen['mode'] == 'scheduled', payload=frozen)
        if result.state not in {'submitted', 'scheduled'} or not result.remote_job_id:
            raise ValueError('invalid fake provider response')
        ledger.resolve(intent_id, attempt, result.state, remote_job_id=result.remote_job_id,
                       provider_instance_id=provider.instance_id,
                       integration_id='synthetic-integration')
    except Exception:
        # The fake side effect may have happened; never silently retry it.
        try:
            ledger.recover_inflight(intent_id)
        except Exception:
            try:
                current = ledger.get(intent_id)['state']
            except Exception:
                current = None
            if current != 'unknown':
                # Do not leak provider or recovery exceptions via traceback.
                raise ValueError('synthetic recovery failed; manual inspection required') from None
        raise ValueError('synthetic outcome unknown') from None
    observed = ledger.get(intent_id)
    # State may have changed while the provider was processing (e.g. revoke).
    # This is an observation, not a guarantee that a later revoke cannot occur.
    if observed['state'] != result.state:
        return DeliveryResult(state=observed['state'], remote_job_id=observed.get('remote_job_id'))
    return result


@dataclass(frozen=True)
class SyntheticPollResult:
    """Observation from a bounded fixture poll, never a real platform result."""
    state: str
    reason: str
    attempts: int


def _poll_synthetic_locked(ledger, intent_id, provider, *, clock, sleep,
                           budget_seconds, max_attempts):
    """Bounded readback only for an in-memory fake; never calls submit.

    Per invocation: at most five reads by default, hard ceiling ten, delays
    1, 2, 4, 8 seconds (capped at 8), minimum gap one second and budget 30
    seconds (hard ceiling 300). Separate calls share a per-fake-instance lock,
    next-read deadline and backoff in this process only. A timeout/error is
    reported as unknown without asserting remote failure or
    changing an existing scheduled ledger record.
    """
    from delivery_ledger import DeliveryLedger
    from postiz_adapter import FakePostiz, SyntheticRateLimitError, reconcile_fake

    if (not _exact_fixture_type(ledger, DeliveryLedger, 'scripts.lib.delivery_ledger')
            or ledger._memory_uri is None or ledger._keeper is None
            or not _exact_fixture_type(provider, FakePostiz, 'scripts.lib.postiz_adapter')):
        raise ValueError('synthetic memory ledger and FakePostiz are required')
    if (type(max_attempts) is not int or not 1 <= max_attempts <= 10
            or type(budget_seconds) not in (int, float) or not math.isfinite(budget_seconds)
            or not 0 < budget_seconds <= 300 or not callable(clock) or not callable(sleep)):
        raise ValueError('invalid synthetic polling limits')

    def now():
        try:
            value = clock()
        except Exception:
            raise ValueError('synthetic clock failed') from None
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('invalid monotonic clock')
        return float(value)

    start = now()
    previous = start
    deadline = start + float(budget_seconds)
    attempts = 0
    if provider._poll_clock is None:
        provider._poll_clock = clock
    elif provider._poll_clock != clock:
        raise ValueError('synthetic poll clock domain changed')
    if provider._poll_blocked:
        return SyntheticPollResult('unknown', 'invalid_rate_limit', 0)
    next_allowed = max(start, provider._poll_next_allowed or start)
    while attempts < max_attempts:
        current = now()
        if current < next_allowed:
            if next_allowed >= deadline:
                return SyntheticPollResult('unknown', 'budget_exhausted', attempts)
            try:
                sleep(next_allowed - current)
            except Exception:
                raise ValueError('synthetic poll sleep failed') from None
            current = now()
            if current < next_allowed:
                raise ValueError('synthetic poll clock did not advance')
        if current < previous:
            raise ValueError('monotonic clock moved backwards')
        previous = current
        if current >= deadline:
            return SyntheticPollResult('unknown', 'budget_exhausted', attempts)
        row = ledger.get(intent_id)
        if row['state'] == 'published':
            snapshot = ledger.fixture_snapshot(intent_id)['snapshot']
            incomplete = (not row.get('published_at') or not row.get('platform_post_id')
                          or not row.get('platform_url') or
                          (row['platform'] == 'facebook' and snapshot.get('post_format') == 'facebook_post'
                           and not row.get('comment_id')))
            return SyntheticPollResult('published', 'sync_pending' if incomplete else 'already_recorded', attempts)
        if row['state'] not in {'submitted', 'scheduled', 'unknown'}:
            return SyntheticPollResult(row['state'], 'not_pollable', attempts)
        if (not row.get('remote_job_id') or not row.get('integration_id')
                or row.get('provider_instance_id') != provider.instance_id):
            return SyntheticPollResult('unknown', 'remote_identity_unavailable', attempts)
        attempts += 1
        retry_after = None
        try:
            observation = reconcile_fake(provider, row['remote_job_id'],
                                         expected_instance_id=row['provider_instance_id'])
        except Exception as exc:
            observation = None
            if _exact_fixture_type(exc, SyntheticRateLimitError, 'scripts.lib.postiz_adapter'):
                retry_after = exc.retry_after
                if (type(retry_after) not in (int, float) or not math.isfinite(retry_after)
                        or retry_after < 0):
                    provider._poll_blocked = True
                    return SyntheticPollResult('unknown', 'invalid_rate_limit', attempts)
        # A synchronous callback cannot be forcibly interrupted by this budget;
        # account for its elapsed time immediately on return and do not invent
        # a result if it outlived the observation window.
        current = now()
        if current < previous:
            raise ValueError('monotonic clock moved backwards')
        previous = current
        minimum_wait = max(1.0, float(retry_after)) if retry_after is not None else 1.0
        provider._poll_next_allowed = max(provider._poll_next_allowed or current,
                                          current + minimum_wait)
        if current >= deadline:
            return SyntheticPollResult('unknown', 'budget_exhausted', attempts)
        if observation is not None and observation.state == 'published':
            evidence = {'state': 'published', 'platform': row['platform'],
                        'account_id': row['account_id'],
                        'provider_instance_id': row['provider_instance_id'],
                        'integration_id': row['integration_id'],
                        'remote_job_id': observation.remote_job_id,
                        'remote_post_id': row.get('remote_post_id'),
                        'platform_post_id': observation.platform_post_id,
                        'platform_url': observation.platform_url,
                        'published_at': observation.published_at,
                        'comment_id': observation.comment_id,
                        'evidence_kind': 'provider_confirmed'}
            try:
                ledger.reconcile(intent_id, row['state'], verifier=lambda _: evidence)
            except Exception:
                raise ValueError('synthetic reconciliation failed') from None
            provider._poll_failures = 0
            provider._poll_next_allowed = current + 1.0
            snapshot = ledger.fixture_snapshot(intent_id)['snapshot']
            incomplete = (not observation.published_at or not observation.platform_post_id
                          or not observation.platform_url or
                          (row['platform'] == 'facebook' and snapshot.get('post_format') == 'facebook_post'
                           and not observation.comment_id))
            return SyntheticPollResult('published', 'sync_pending' if incomplete else 'confirmed', attempts)
        current = now()
        if current < previous:
            raise ValueError('monotonic clock moved backwards')
        previous = current
        provider._poll_failures += 1
        delay = float(min(2 ** min(provider._poll_failures - 1, 3), 8))
        if retry_after is not None:
            delay = max(delay, float(retry_after))
        provider._poll_next_allowed = current + delay
        if attempts >= max_attempts:
            return SyntheticPollResult('unknown', 'attempt_limit', attempts)
        if provider._poll_next_allowed >= deadline:
            return SyntheticPollResult('unknown', 'budget_exhausted', attempts)
        next_allowed = provider._poll_next_allowed
        try:
            sleep(delay)
        except Exception:
            raise ValueError('synthetic poll sleep failed') from None
    raise AssertionError('unreachable')


def poll_synthetic(ledger, intent_id, provider, *, clock=time.monotonic, sleep=time.sleep,
                   budget_seconds=30.0, max_attempts=5):
    """Poll one synthetic provider; serializes its callers and shares backoff.

    Limits are 5 reads/30s by default, at most 10 reads/300s per invocation;
    backoff is 1/2/4/8s and shared per fake provider instance. No cross-process
    or production-provider rate limit is claimed.
    """
    from postiz_adapter import FakePostiz
    if not _exact_fixture_type(provider, FakePostiz, 'scripts.lib.postiz_adapter'):
        raise ValueError('synthetic memory ledger and FakePostiz are required')
    if not provider._poll_lock.acquire(blocking=False):
        raise ValueError('synthetic poll already running')
    try:
        return _poll_synthetic_locked(ledger, intent_id, provider, clock=clock, sleep=sleep,
                                      budget_seconds=budget_seconds, max_attempts=max_attempts)
    finally:
        provider._poll_lock.release()
