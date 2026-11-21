"""One-shot synthetic JSON dispatch: temp files only, no network or credentials."""
from __future__ import annotations

import copy
import re
import tempfile
from pathlib import Path
from typing import Any

from scripts.social.destination_ledger_fixture import _fixture_time
from scripts.social.instagram_fixture_transport import FakeInstagramTransport
from scripts.social.json_session_dispatch import dispatch_fixture_batch
from scripts.social.json_session_fixture import FixtureJsonSession
from scripts.social.linkedin_fixture_transport import FakeLinkedInTransport
from scripts.social.telegram_fixture_transport import FakeTelegramTransport


def simulate_json_dispatch(*, source: str, publication: dict[str, Any], entries: list[dict[str, Any]],
                           now: str, fakes: list[dict[str, Any]], grant_fixture: bool = False) -> dict[str, Any]:
    """Execute one disposable fixture session; `grant_fixture` grants every item only in this simulation."""
    _fixture_time(now)
    if (type(grant_fixture) is not bool or not isinstance(entries, list) or not 1 <= len(entries) <= 100
            or not isinstance(fakes, list) or len(fakes) != len(entries)):
        raise ValueError('invalid simulation batch')
    source, publication, entries, fakes = copy.deepcopy((source, publication, entries, fakes))
    transports: list[Any] = []
    for entry, fake in zip(entries, fakes):
        if (not isinstance(entry, dict) or not isinstance(fake, dict) or not isinstance(fake.get('platform'), str)
                or entry.get('platform') != fake.get('platform')):
            raise ValueError('invalid synthetic transport')
        platform = fake['platform']
        if platform == 'instagram':
            if (set(fake) != {'platform', 'container_id', 'status', 'media_id'}
                    or fake['status'] not in ('IN_PROGRESS', 'FINISHED', 'ERROR', 'EXPIRED')
                    or any(value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,32}', value))
                           for value in (fake['container_id'], fake['media_id']))):
                raise ValueError('invalid Instagram fake')
            transports.append(FakeInstagramTransport(container_id=fake['container_id'], status=fake['status'],
                                                     media_id=fake['media_id']))
        elif platform == 'linkedin' and set(fake) == {'platform', 'post_urn', 'outcome'}:
            transports.append(FakeLinkedInTransport(post_urn=fake['post_urn'], outcome=fake['outcome']))
        elif platform == 'telegram' and set(fake) == {'platform', 'response'}:
            transports.append(FakeTelegramTransport(response=fake['response']))
        else:
            raise ValueError('unsupported synthetic transport')
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='social-json-fixture-', dir=temporary_root) as directory:
        session = FixtureJsonSession.create(Path(directory), source=source, publication=publication,
                                            entries=entries, delivery_fixture=True)
        if grant_fixture:
            session.grant_all()
        rows = session.inspect()['items']
        jobs = [{'index': i, 'key': row['key'], 'digest': row['snapshot_sha256'], 'transport': transports[i]}
                for i, row in enumerate(rows)]
        result = dispatch_fixture_batch(session, jobs=jobs, now=now)
        states = session.inspect()['items']
        items = []
        for outcome, row in zip(result['items'], states):
            items.append({**outcome, 'receipt': row['receipt'],
                          'instagram': row.get('instagram') if row['key']['platform'] == 'instagram' else None})
        return {'fixture_only': True, 'persistent': False, 'items': items,
                'warnings': ['synthetic_grant_not_authority', 'not_a_real_delivery',
                             'temporary_session_discarded', 'no_network_or_scheduler']}
