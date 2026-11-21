"""Dispatch explicit fixture jobs through built-in in-memory fakes only.

No network, real approvals, station paths or credentials are accepted here.
SQLite errors propagate; already-claimed fixture intents remain inspectable.
"""
from __future__ import annotations

from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger, _fixture_time
from scripts.social.instagram_fixture_transport import FakeInstagramTransport, create_due_fixture, observe_fixture, publish_fixture
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport, send_due_fixture as send_linkedin
from scripts.social.telegram_fixture_transport import FakeTelegramTransport, send_due_fixture as send_telegram


def dispatch_due_fixture_batch(ledger: DestinationFixtureLedger, *, jobs: list[dict[str, Any]],
                               now: str) -> dict[str, Any]:
    """Attempt each explicitly selected, already-granted synthetic destination once."""
    if type(ledger) is not DestinationFixtureLedger or not isinstance(jobs, list) or not 1 <= len(jobs) <= 100:
        raise ValueError('invalid fixture dispatch batch')
    _fixture_time(now)
    jobs = list(jobs)
    types = {'instagram': FakeInstagramTransport, 'linkedin': FakeLinkedInTransport, 'telegram': FakeTelegramTransport}
    seen_intents: set[str] = set()
    planned = []
    for job in jobs:
        if (not isinstance(job, dict) or set(job) != {'intent_id', 'version', 'transport'}
                or not isinstance(job['intent_id'], str) or type(job['version']) is not int or job['version'] < 1
                or job['intent_id'] in seen_intents):
            raise ValueError('invalid fixture dispatch job')
        row = ledger.get(job['intent_id'])
        platform = row['platform']
        if platform not in types or type(job['transport']) is not types[platform]:
            raise ValueError('fixture transport does not match destination')
        seen_intents.add(job['intent_id'])
        planned.append((job['intent_id'], job['version'], platform, job['transport']))
    outcomes = []
    for intent_id, version, platform, transport in planned:
        current = ledger.get(intent_id)
        if current['version'] != version:
            outcomes.append({'intent_id': intent_id, 'platform': platform, 'state': current['state'],
                             'outcome': 'refused'})
            continue
        if current['state'] == 'accepted':
            outcomes.append({'intent_id': intent_id, 'platform': platform, 'state': 'accepted',
                             'outcome': 'already_accepted'})
            continue
        if current['state'] == 'unknown':
            outcomes.append({'intent_id': intent_id, 'platform': platform, 'state': 'unknown', 'outcome': 'unknown'})
            continue
        error = False
        try:
            if platform == 'instagram':
                if current['state'] == 'submitting':
                    attempt = current['attempt_id']
                    phase = ledger.instagram_session_status(intent_id, attempt=attempt)['phase']
                    if phase not in ('waiting', 'ready'):
                        raise ValueError('Instagram fixture needs explicit recovery')
                else:
                    attempt = create_due_fixture(ledger, intent_id, expected_version=version, now=now, transport=transport)
                    phase = 'waiting' if ledger.get(intent_id)['state'] == 'submitting' else 'unknown'
                if phase == 'ready' or (phase == 'waiting' and observe_fixture(
                        ledger, intent_id, attempt=attempt, transport=transport)):
                    publish_fixture(ledger, intent_id, attempt=attempt, transport=transport)
            elif platform == 'linkedin':
                send_linkedin(ledger, intent_id, expected_version=version, now=now, transport=transport)
            else:
                send_telegram(ledger, intent_id, expected_version=version, now=now, transport=transport)
        except ValueError:
            error = True
        state = ledger.get(intent_id)['state']
        if state == 'unknown':
            outcome = 'unknown'
        elif state == 'accepted' and error:
            outcome = 'already_accepted'
        elif error:
            outcome = 'refused' if state == 'prepared' else 'incomplete'
        elif state == 'accepted':
            outcome = 'accepted'
        else:
            outcome = 'awaiting_observation'
        outcomes.append({'intent_id': intent_id, 'platform': platform, 'state': state, 'outcome': outcome})
    return {'fixture_only': True, 'items': outcomes}
