"""LinkedIn scheduling experiment using only an in-process fake provider.

No network, credentials, OAuth or real publication are implemented here.
"""
from __future__ import annotations

import copy
from typing import Any

from scripts.social.channels.linkedin.direct import interpret_create
from scripts.social.destination_ledger_fixture import DestinationFixtureLedger


class FakeLinkedInTransport:
    """Return a predetermined synthetic receipt and retain the observed candidate."""

    def __init__(self, *, post_urn: str, outcome: str = 'accepted') -> None:
        if (outcome not in ('accepted', 'lost')
                or interpret_create(201, [('x-restli-id', post_urn)])['state'] != 'accepted'):
            raise ValueError('invalid synthetic LinkedIn receipt')
        self._post_urn = post_urn
        self._outcome = outcome
        self.calls = 0
        self.last_candidate: dict[str, Any] | None = None
        self.last_attempt: str | None = None

    def _send(self, candidate: dict[str, Any], attempt: str) -> tuple[int | None, list[tuple[str, str]]]:
        self.calls += 1
        self.last_candidate = copy.deepcopy(candidate)
        self.last_attempt = attempt
        return (201, [('x-restli-id', self._post_urn)]) if self._outcome == 'accepted' else (None, [])


def send_due_fixture(ledger: DestinationFixtureLedger, intent_id: str, *, expected_version: int,
                     now: str, transport: FakeLinkedInTransport) -> None:
    """Claim once and pass a verified fixture to the built-in fake provider."""
    if type(ledger) is not DestinationFixtureLedger or type(transport) is not FakeLinkedInTransport:
        raise ValueError('synthetic transport required')
    attempt, candidate = ledger.claim_due_linkedin_fixture(intent_id, expected_version=expected_version, now=now)
    status, headers = transport._send(candidate, attempt)
    ledger.finish_linkedin_fixture(intent_id, attempt=attempt, status=status, headers=headers)
