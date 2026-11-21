"""Canonical review data shared by package review and schedule drafts."""

import json
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot

DRAFT_SCHEMA = "social-package-review-draft/2"
SOURCE_STATUS = "unverified"
DRAFT_FIELDS = frozenset({
    "schema", "source_status", "claimed_scope", "platform", "destination_kind", "action", "account_id",
    "destination_id", "occurrence_key", "scheduled_at", "timezone", "privacy", "delivery_options", "package_digest",
})


def canonical_review(
    *, claimed_scope: dict[str, str], platform: str, destination_kind: str,
    action: str, account_id: str, destination_id: str, occurrence_key: str,
    scheduled_at: str | None, timezone: str, privacy: str,
    delivery_options: dict[str, Any], package_digest: str,
) -> tuple[dict[str, Any], str]:
    canonical, digest = canonical_snapshot({
        "schema": DRAFT_SCHEMA,
        "source_status": SOURCE_STATUS,
        "claimed_scope": claimed_scope,
        "platform": platform,
        "destination_kind": destination_kind,
        "action": action,
        "account_id": account_id,
        "destination_id": destination_id,
        "occurrence_key": occurrence_key,
        "scheduled_at": scheduled_at,
        "timezone": timezone,
        "privacy": privacy,
        "delivery_options": delivery_options,
        "package_digest": package_digest,
    })
    return json.loads(canonical), digest
