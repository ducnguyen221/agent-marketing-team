"""Source-backed V2 preflight. Live dispatch remains blocked by the approval ledger."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.approval_package_v2 import verify_stored_package_campaign_source
from scripts.social.channels.facebook.readonly_auth import check_identity as check_facebook
from scripts.social.channels.instagram.readonly_auth import check_link as check_instagram
from scripts.social.channels.linkedin.readonly_auth import check_userinfo as check_linkedin
from scripts.social.channels.telegram.readonly_auth import check_bot as check_telegram
from scripts.social.channels.threads.readonly_auth import check_identity as check_threads
from scripts.social.channels.tiktok.readonly_auth import check_userinfo as check_tiktok
from scripts.social.channels.x.readonly_auth import check_userinfo as check_x
from scripts.social.channels.youtube.readonly_auth import check_channel as check_youtube
from scripts.social.publish_channel_package import AccountObservation


_IDENTITY_READERS = {
    "linkedin": check_linkedin,
    "telegram": check_telegram,
    "tiktok": check_tiktok,
    "x": check_x,
    "youtube": check_youtube,
}
_VERSIONED_IDENTITY_READERS = {"facebook": check_facebook, "threads": check_threads}
_OPERATIONS = {"create", "comment", "container", "publish_container"}


def read_package_account(
    *, platform: str, account_id: str, credential: str, enable_provider_read: bool = False,
    api_version: str | None = None, linked_page_id: str | None = None,
) -> AccountObservation:
    """Compare the supplied credential's provider subject, without granting dispatch."""
    if enable_provider_read is not True:
        raise ValueError("provider identity read is disabled")
    if linked_page_id is not None and platform != "instagram":
        raise ValueError("linked Page ID applies only to Instagram")
    if platform == "instagram":
        if not api_version or not linked_page_id:
            raise ValueError("Instagram identity requires an API version and linked Page ID")
        result = check_instagram(credential, linked_page_id, account_id, api_version=api_version)
    elif platform in _VERSIONED_IDENTITY_READERS:
        if not api_version:
            raise ValueError("provider identity requires an API version")
        result = _VERSIONED_IDENTITY_READERS[platform](credential, account_id, api_version=api_version)
    elif platform in _IDENTITY_READERS:
        if api_version is not None:
            raise ValueError("API version does not apply to this identity reader")
        result = _IDENTITY_READERS[platform](credential, account_id)
    else:
        raise ValueError("no supported identity reader for the requested platform")
    if result.get("identity") != "match":
        raise ValueError("provider account identity could not be verified")
    return AccountObservation(platform, account_id, hashlib.sha256(credential.encode()).hexdigest(),
                              f"{platform}:provider-identity-read")


def stable_attempt_key(payload: dict[str, Any], operation: str) -> str:
    """Keep the same claim key across reapproval or package edits for one occurrence."""
    if operation not in _OPERATIONS:
        raise ValueError("unsupported delivery operation")
    required = ("station_id", "channel_id", "campaign_id", "content_id", "post_id",
                "platform", "account_id", "destination_id", "occurrence_key")
    if any(not isinstance(payload.get(field), str) or not payload[field].strip() for field in required):
        raise ValueError("missing delivery occurrence identity")
    occurrence = {field: payload[field] for field in required}
    occurrence["operation"] = operation
    return canonical_snapshot(occurrence)[1]


def inspect_source_approval(
    *, campaign: Path, package_dir: Path, scope: dict[str, str], delivery_payload: dict[str, Any],
    temporary_parent: Path, text_file: str | None = None, comment_file: str | None = None,
    media_file: str | None = None,
    media_files: list[str] | None = None, caption_files: list[str] | None = None,
) -> dict[str, str]:
    """Check exact V1 source and approval evidence without granting dispatch."""
    from scripts.pipeline import approval_gate

    for directory in (campaign, package_dir):
        absolute = Path(os.path.abspath(directory))
        if absolute.drive.startswith(("\\\\", "//")) or any(
            part.casefold() == ".secret" for part in absolute.parts
        ):
            raise ValueError("approval inspection requires local public-intent directories")
        approval_gate.check_delivery_local_path(directory)
    package, package_digest = verify_stored_package_campaign_source(
        package_dir=package_dir, campaign=campaign, scope=scope,
        temporary_parent=temporary_parent, text_file=text_file, comment_file=comment_file,
        media_file=media_file, media_files=media_files, caption_files=caption_files,
    )
    if package["platform"] != delivery_payload.get("platform"):
        raise ValueError("approval does not identify this V2 package")
    approved_digest = delivery_payload.get("social_package_digest")
    if not isinstance(approved_digest, str) or not hmac.compare_digest(package_digest, approved_digest):
        raise ValueError("exact V2 package digest is required in the bound payload")

    campaign = campaign.resolve(strict=True)
    approval_gate.check_delivery_local_path(campaign / "campaign.md", file=True)
    _, _, columns, rows = approval_gate.read_content_table(campaign)
    matches = [row for row in rows if row.get("content_id") == scope.get("content_id")]
    if len(matches) != 1:
        raise ValueError("V1 approval content item is missing or ambiguous")
    gates = approval_gate.delivery_required_gates(matches[0], package["platform"], content_columns=columns)
    for gate in gates:
        if gate != "g2":
            approval_gate.read_delivery_gate_proof(campaign, {**scope, "gate": gate, "post_id": "*"})
    proof = approval_gate.verify_delivery_payload(campaign, scope, delivery_payload)
    return {
        "status": "blocked", "reason": "production_approval_generation_unavailable",
        "binding_event_id": proof["binding_event_id"], "package_digest": package_digest,
        "attempt_key": stable_attempt_key(delivery_payload, "create"),
    }
