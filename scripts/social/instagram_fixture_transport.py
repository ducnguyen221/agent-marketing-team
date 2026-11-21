"""Two-step Instagram simulation with an in-memory fake, never a network client."""
from __future__ import annotations

import copy
import re
from typing import Any

from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


class FakeInstagramTransport:
    """Return predetermined synthetic responses for create, observe and publish."""

    def __init__(self, *, container_id: str | None, status: str, media_id: str | None) -> None:
        self.container_id = container_id
        self.status = status
        self.media_id = media_id
        self.create_calls = 0
        self.publish_calls = 0
        self.last_create: dict[str, Any] | None = None
        self.last_publish: dict[str, Any] | None = None
        self.last_create_attempt: str | None = None
        self.last_publish_attempt: str | None = None
        self._bindings: dict[str, str] = {}
        self._publish_responses: dict[tuple[str, str], str | None] = {}

    def _create(self, candidate: dict[str, Any], attempt: str) -> dict[str, str] | None:
        self.create_calls += 1
        self.last_create = copy.deepcopy(candidate)
        self.last_create_attempt = attempt
        if isinstance(self.container_id, str):
            self._bindings[attempt] = self.container_id
            self._publish_responses[(attempt, self.container_id)] = self.media_id
        return {'id': self.container_id} if self.container_id is not None else None

    def _observe(self) -> dict[str, str] | None:
        return {'id': self.container_id, 'status_code': self.status} if self.container_id is not None else None

    def _publish(self, candidate: dict[str, Any], attempt: str) -> dict[str, str] | None:
        self.publish_calls += 1
        self.last_publish = copy.deepcopy(candidate)
        self.last_publish_attempt = attempt
        key = (attempt, candidate['request']['params']['creation_id'])
        media_id = self._publish_responses.get(key)
        return {'id': media_id} if media_id is not None else None


def _fixture_id(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    value = response.get('id')
    return value if isinstance(value, str) and re.fullmatch(r'[0-9]{1,32}', value) else None


def create_due_fixture(ledger: DestinationFixtureLedger, intent_id: str, *, expected_version: int,
                       now: str, transport: FakeInstagramTransport) -> str:
    if type(ledger) is not DestinationFixtureLedger or type(transport) is not FakeInstagramTransport:
        raise ValueError('synthetic Instagram transport required')
    attempt, candidate = ledger.claim_due_instagram_fixture(intent_id, expected_version=expected_version, now=now)
    container_id = _fixture_id(transport._create(candidate, attempt))
    if container_id is None:
        ledger.instagram_mark_unknown(intent_id, attempt=attempt, expected_phase='creating')
    else:
        user_id = candidate['request']['path'].split('/')[-2]
        ledger.instagram_accept_container(intent_id, attempt=attempt, user_id=user_id, container_id=container_id)
    return attempt


def observe_fixture(ledger: DestinationFixtureLedger, intent_id: str, *, attempt: str,
                    transport: FakeInstagramTransport) -> bool:
    if type(ledger) is not DestinationFixtureLedger or type(transport) is not FakeInstagramTransport:
        raise ValueError('synthetic Instagram transport required')
    current = ledger.instagram_session_status(intent_id, attempt=attempt)
    if current['phase'] != 'waiting':
        raise ValueError('Instagram fixture is not waiting')
    response = transport._observe()
    if (not isinstance(response, dict) or response.get('id') != current['container_id']
            or response.get('status_code') not in ('IN_PROGRESS', 'FINISHED', 'ERROR', 'EXPIRED')):
        return False
    ledger.instagram_observe_ready(intent_id, attempt=attempt, container_id=current['container_id'],
                                   status=response['status_code'])
    return response['status_code'] == 'FINISHED'


def publish_fixture(ledger: DestinationFixtureLedger, intent_id: str, *, attempt: str,
                    transport: FakeInstagramTransport) -> None:
    if type(ledger) is not DestinationFixtureLedger or type(transport) is not FakeInstagramTransport:
        raise ValueError('synthetic Instagram transport required')
    candidate = ledger.instagram_claim_publish(intent_id, attempt=attempt)
    media_id = _fixture_id(transport._publish(candidate, attempt))
    container_id = candidate['request']['params']['creation_id']
    if media_id is None or transport._bindings.get(attempt) != container_id:
        ledger.instagram_mark_unknown(intent_id, attempt=attempt, expected_phase='publishing')
    else:
        ledger.instagram_accept_publish(intent_id, attempt=attempt,
                                        container_id=container_id, media_id=media_id)
