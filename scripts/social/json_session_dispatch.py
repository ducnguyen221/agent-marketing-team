"""Sequential dispatch of explicit JSON fixtures to built-in in-memory fakes.

No real providers, credentials, scheduler, or station files are accessed.
Storage and unexpected state errors propagate; inspect the session before retry.
"""
from __future__ import annotations

import copy
from typing import Any

from scripts.social.destination_ledger_fixture import _fixture_time
from scripts.social.instagram_fixture_transport import FakeInstagramTransport
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
from scripts.social.telegram_fixture_transport import FakeTelegramTransport


def dispatch_fixture_batch(session: FixtureJsonSession, *, jobs: list[dict[str, Any]], now: str) -> dict[str, Any]:
    """Dispatch selected synthetic items, one at a time, without granting them."""
    if type(session) is not FixtureJsonSession or not isinstance(jobs, list) or not 1 <= len(jobs) <= 100:
        raise ValueError('invalid fixture batch')
    current_time = _fixture_time(now)
    view = session.inspect()
    if view['schema'] not in ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4'):
        raise ValueError('delivery fixture required')
    types = {'instagram': FakeInstagramTransport, 'linkedin': FakeLinkedInTransport, 'telegram': FakeTelegramTransport}
    versions = {'linkedin': ('social-json-fixture/2', 'social-json-fixture/3', 'social-json-fixture/4'),
                'telegram': ('social-json-fixture/3', 'social-json-fixture/4'),
                'instagram': ('social-json-fixture/4',)}
    schemas = {'linkedin': ('linkedin-v1-facebook-text/1', 'linkedin-v1-facebook-media/1'),
               'telegram': ('telegram-v1-facebook-text/1', 'telegram-v1-image/1', 'telegram-v1-video/1'),
               'instagram': ('instagram-v1-infographic/1', 'instagram-v1-reel/1')}
    selected = []
    seen = set()
    for job in tuple(jobs):
        if (not isinstance(job, dict) or set(job) != {'index', 'key', 'digest', 'transport'}
                or type(job['index']) is not int or not 0 <= job['index'] < len(view['items'])
                or job['index'] in seen or not isinstance(job['key'], dict) or not isinstance(job['digest'], str)):
            raise ValueError('invalid fixture job')
        index = job['index']
        row = view['items'][index]
        platform = row['key']['platform']
        if (platform not in types or type(job['transport']) is not types[platform]
                or row['key'] != job['key'] or row['snapshot_sha256'] != job['digest']
                or view['schema'] not in versions[platform] or row['snapshot'].get('fixture_schema') not in schemas[platform]):
            raise ValueError('fixture job does not match destination')
        seen.add(index)
        selected.append((index, copy.deepcopy(job['key']), job['digest'], platform, job['transport']))
    outcomes = []
    for index, key, digest, platform, transport in selected:
        row = session.inspect()['items'][index]
        if row['key'] != key or row['snapshot_sha256'] != digest:
            raise ValueError('fixture destination changed')
        state = row['state']
        if state == 'accepted':
            outcome = 'already_accepted'
        elif state == 'unknown':
            outcome = 'unknown'
        elif state == 'prepared' and (not row['grant'] or _fixture_time(row['snapshot']['scheduled_at']) > current_time):
            outcome = 'not_due_or_not_granted'
        elif state == 'submitting' and platform != 'instagram':
            outcome = 'requires_recovery'
        else:
            own_publish = False
            if platform == 'instagram':
                if state == 'prepared':
                    session.create_due_instagram(index, now=now, expected_key=key, expected_digest=digest, transport=transport)
                    row = session.inspect()['items'][index]
                phase = row['instagram']['phase']
                if row['state'] == 'submitting' and phase == 'waiting':
                    session.observe_instagram(index, expected_key=key, attempt=row['attempt'], transport=transport)
                    row = session.inspect()['items'][index]
                    phase = row['instagram']['phase']
                if row['state'] == 'submitting' and phase == 'ready':
                    if transport._bindings.get(row['attempt']) != row['instagram']['container_id']:
                        outcomes.append({'index': index, 'platform': platform, 'state': row['state'],
                                         'outcome': 'requires_original_fake'})
                        continue
                    session.publish_instagram(index, expected_key=key, attempt=row['attempt'], transport=transport)
                    own_publish = True
                elif row['state'] == 'submitting' and phase in ('creating', 'publishing'):
                    outcomes.append({'index': index, 'platform': platform, 'state': row['state'],
                                     'outcome': 'requires_recovery'})
                    continue
            elif platform == 'linkedin':
                session.send_due_linkedin(index, now=now, expected_key=key, expected_digest=digest, transport=transport)
                own_publish = True
            else:
                session.send_due_telegram(index, now=now, expected_key=key, expected_digest=digest, transport=transport)
                own_publish = True
            final = session.inspect()['items'][index]
            state = final['state']
            if state == 'accepted':
                outcome = 'accepted' if own_publish else 'already_accepted'
            elif state == 'unknown':
                outcome = 'unknown'
            elif platform == 'instagram' and final['instagram']['phase'] in ('creating', 'publishing'):
                outcome = 'requires_recovery'
            elif platform == 'instagram' and final['instagram']['phase'] == 'ready':
                outcome = ('ready_to_publish' if transport._bindings.get(final['attempt']) == final['instagram']['container_id']
                           else 'requires_original_fake')
            else:
                outcome = 'awaiting_observation'
        outcomes.append({'index': index, 'platform': platform, 'state': state, 'outcome': outcome})
    return {'fixture_only': True, 'items': outcomes}
