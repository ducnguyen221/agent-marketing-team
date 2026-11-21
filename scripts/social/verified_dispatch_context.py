"""Corroborate exact V2 dispatch evidence in an existing V1 campaign."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scripts.pipeline.approval_gate import (
    check_delivery_local_path,
    read_content_table,
    read_delivery_gate_proof,
    verify_delivery_payload,
)
from scripts.social.approval_package_v2 import prepare_review_draft, verify_stored_package_campaign_source
from scripts.social.dispatch_package_v2 import _prepare_bound_route
from scripts.social.schedule_v2 import _schedule_time
from scripts.social.standalone_delivery import SCHEMA, read_delivery_manifest


def campaign_binding_payload(package: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Project the exact V2 review into the existing V1 binding payload contract."""
    media = package["media"]
    artifacts = media if isinstance(media, list) else [media] if media is not None else []
    return {
        **{key: value for key, value in review["claimed_scope"].items() if key != "gate"},
        "platform": review["platform"],
        "account_id": review["account_id"],
        "occurrence_key": review["occurrence_key"],
        "timezone": review["timezone"],
        "privacy": review["privacy"],
        "scheduled_at": review["scheduled_at"],
        "text": package["content"]["text"],
        "artifacts": artifacts,
        "v2_review": review,
    }


def prepare_campaign_dispatch_review(
    *,
    package_dir: Path,
    campaign: Path,
    scope: dict[str, str],
    temporary_parent: Path,
    account_id: str,
    destination_id: str,
    occurrence_id: str,
    scheduled_at: str | None,
    timezone: str,
    privacy: str,
    options: dict[str, Any],
    text_file: str | None = None,
    comment_file: str | None = None,
    media_file: str | None = None,
    media_files: list[str] | None = None,
    caption_files: list[str] | None = None,
) -> dict[str, Any]:
    """Verify local source and prepare one exact route for operator review."""
    if read_delivery_manifest(package_dir).get("schema") == SCHEMA:
        raise ValueError("standalone_approval_source_unavailable")
    if not isinstance(timezone, str) or not timezone or len(timezone) > 128:
        raise ValueError("invalid_review_timezone")
    if scheduled_at is not None:
        _schedule_time(scheduled_at, timezone)
    else:
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("invalid_review_timezone") from exc
    package, package_digest = verify_stored_package_campaign_source(
        package_dir=package_dir, campaign=campaign, scope=scope, temporary_parent=temporary_parent,
        text_file=text_file, comment_file=comment_file, media_file=media_file,
        media_files=media_files, caption_files=caption_files,
    )
    route = _prepare_bound_route(
        package_dir, package, package_digest=package_digest, account_id=account_id,
        destination_id=destination_id, occurrence_id=occurrence_id, options=options,
    )
    if "privacy" in route["binding"]["options"] and route["binding"]["options"]["privacy"] != privacy:
        raise ValueError("review_privacy_mismatch")
    review, review_digest = prepare_review_draft(
        package, claimed_scope=scope, account_id=account_id, destination_id=destination_id,
        occurrence_key=occurrence_id, scheduled_at=scheduled_at, timezone=timezone,
        privacy=privacy, delivery_options=route["binding"]["options"],
    )
    return {**route, "review": review, "review_digest": review_digest, "package": package}


def inspect_campaign_dispatch_evidence(**arguments: Any) -> dict[str, Any]:
    """Corroborate the existing V1 binding without granting production authority."""
    prepared = prepare_campaign_dispatch_review(**arguments)
    campaign, scope = arguments["campaign"], arguments["scope"]
    package, review = prepared.pop("package"), prepared.pop("review")
    payload = campaign_binding_payload(package, review)
    gates = _read_gate_evidence(campaign, scope, package["platform"], payload)
    if gates != _read_gate_evidence(campaign, scope, package["platform"], payload):
        raise ValueError("campaign_approval_evidence_changed")
    return {
        **prepared,
        "reason": "authenticated_approval_and_revocation_unavailable",
        "campaign_evidence": gates,
    }


def approved_content_columns(campaign: Path, content_id: str) -> list[str]:
    """Require one currently approved Content row and return the table columns."""
    check_delivery_local_path(campaign / "campaign.md", file=True)
    _, _, columns, rows = read_content_table(campaign)
    matching = [row for row in rows if row.get("content_id") == content_id]
    if len(matching) != 1 or matching[0].get("status") != "approved":
        raise ValueError("campaign_content_approval_unavailable")
    return columns


def _read_gate_evidence(
    campaign: Path, scope: dict[str, str], platform: str, payload: dict[str, Any],
) -> dict[str, str]:
    columns = approved_content_columns(campaign, scope["content_id"])
    required = ("g1", "g3") if "g3" in columns and platform in {"facebook", "youtube"} else ("g1",)
    proofs = {
        gate: read_delivery_gate_proof(campaign, {**scope, "gate": gate, "post_id": "*"})
        for gate in required
    }
    proofs["g2"] = verify_delivery_payload(campaign, scope, payload)
    return {gate: proof["source_digest"] for gate, proof in proofs.items()}


