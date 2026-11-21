"""Run one guarded X V2 package upload and create sequence."""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.linkedin.readonly_auth import _reject_constant, _unique
from scripts.social.channels.x import direct
from scripts.social.publish_channel_package import (
    AccountObservation,
    ChannelApproval,
    MediaObservation,
    approved_package,
    _interpret_x_create,
    _prepare_x_create,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _json, _request
from scripts.social.publish_package_workflow import read_package_account
from scripts.social.prepare_standalone import _local_directory
from scripts.social.standalone_delivery import SCHEMA
from scripts.social.x_media_upload import (
    _ACCOUNT_ID,
    _MEDIA_ID,
    _OCCURRENCE,
    _x_upload_attempt_key,
    _lock_x_attempt,
    _media_binding,
    _open_x_journal,
    _read_x_journal_file,
    _read_x_record,
    _upload_checked_x_media,
    _write_x_record,
)

_ACTIONS = {"post_text", "post_image", "post_video"}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_LIMIT = 131072


@dataclass(frozen=True)
class XCampaignContext:
    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    privacy: str
    text_file: str | None = None
    media_file: str | None = None


def _create_key(account_id: str, destination_id: str, occurrence_id: str) -> str:
    if (
        not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id)
        or not isinstance(destination_id, str) or destination_id != account_id
        or not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id)
    ):
        raise ValueError("invalid X workflow target or occurrence")
    return canonical_snapshot({
        "platform": "x", "operation": "create", "account_id": account_id,
        "destination_id": destination_id, "occurrence_id": occurrence_id,
    })[1]


def _campaign_snapshot(
    package_dir: Path, context: XCampaignContext, *, account_id: str, occurrence_id: str,
    approval: ChannelApproval,
) -> dict[str, Any]:
    from scripts.social.check_package_readiness import _check_target

    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": account_id,
        "destination_id": account_id, "occurrence_id": occurrence_id,
        "scheduled_at": None, "timezone": context.timezone, "privacy": context.privacy,
        "options": {}, "text_file": context.text_file, "media_file": context.media_file,
    }, context.approval_directory, decision=None)
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval.approval_ref
        or checked["expected_review"] != context.expected_review
    ):
        raise ValueError("X target approval is missing, stale, revoked or mismatched")
    snapshot = checked["snapshot"]
    _validate_campaign_snapshot(snapshot, context.expected_review, account_id, occurrence_id, approval.package_digest)
    return snapshot


def _validate_campaign_snapshot(
    snapshot: dict[str, Any], expected_review: str, account_id: str, occurrence_id: str, package_digest: str,
) -> None:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if not isinstance(snapshot, dict) or canonical_snapshot(snapshot)[1] != expected_review:
        raise ValueError("X campaign review snapshot mismatch")
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        set(snapshot["source_gate_digests"]) != {"g1", "g2"}
        or review["platform"] != "x" or review["destination_kind"] != "account"
        or review["account_id"] != account_id or review["destination_id"] != account_id
        or review["occurrence_key"] != occurrence_id or review["package_digest"] != package_digest
        or review["action"] not in _ACTIONS or review["scheduled_at"] is not None
        or review["delivery_options"] != {} or review["privacy"] != "platform_default"
    ):
        raise ValueError("X campaign review target mismatch")


def run_x_package_workflow(
    package_dir: Path,
    *,
    account_id: str,
    destination_id: str,
    occurrence_id: str,
    credential: str,
    approval: ChannelApproval,
    journal_directory: Path,
    enable_dispatch: bool = False,
    campaign_context: XCampaignContext | None = None,
) -> dict[str, str | float]:
    """Create at most one X post per occurrence after upload or video reconciliation."""
    require_production_authority()
    if os.name != "posix":
        raise ValueError("X attempt journal unavailable on this platform")
    create_key = _create_key(account_id, destination_id, occurrence_id)
    package = approved_package(
        package_dir, platform="x", account_id=account_id, destination_id=destination_id,
        credential=credential, approval=approval, enable_dispatch=enable_dispatch,
    )
    action = package.get("action")
    if action not in _ACTIONS or (package.get("schema") == SCHEMA) != (campaign_context is None):
        raise ValueError("X workflow requires text, one image or one video and the matching source context")
    direct.preview_post(text=package["content"]["text"])
    snapshot = None
    if campaign_context is not None:
        snapshot = _campaign_snapshot(
            package_dir, campaign_context, account_id=account_id, occurrence_id=occurrence_id, approval=approval,
        )

    def check_campaign_send() -> None:
        if campaign_context is not None and snapshot != _campaign_snapshot(
            package_dir, campaign_context, account_id=account_id, occurrence_id=occurrence_id, approval=approval,
        ):
            raise ValueError("X campaign approval changed before dispatch")

    journal_directory = _local_directory(journal_directory)
    if campaign_context is not None:
        for location in (package_dir, campaign_context.campaign, campaign_context.approval_directory):
            location = _local_directory(location)
            if journal_directory.is_relative_to(location) or location.is_relative_to(journal_directory):
                raise ValueError("X attempt journal must be separate from source and target approvals")
        if len(_json({"snapshot": snapshot, "package": package})) > _RECEIPT_LIMIT - 1024:
            raise ValueError("X campaign receipt snapshot exceeds the size limit")
    create_transport = GuardedPackageTransport(journal_directory, create_key)
    binding = {"version": 1, "package_digest": approval.package_digest, "action": action}
    if campaign_context is not None:
        binding.update(review_digest=campaign_context.expected_review, approval_ref=approval.approval_ref)
    result: dict[str, str | float] = {
        "post_status": "not_attempted",
        "media_status": "not_required" if action == "post_text" else "not_attempted",
    }
    try:
        with _open_x_journal(create_transport) as directory_fd:
            claim_name = create_transport._claim_name
            with _lock_x_attempt(directory_fd, f"{claim_name}.workflow.lock"):
                if _has_attempt_record(directory_fd, claim_name):
                    if campaign_context is not None:
                        return read_x_create_receipt(
                            journal_directory, account_id=account_id, destination_id=destination_id,
                            occurrence_id=occurrence_id, package_digest=approval.package_digest,
                            expected_review=campaign_context.expected_review, expected_approval_ref=approval.approval_ref,
                        )
                    result["post_status"] = "already_attempted"
                    return result
                binding_name = f"{claim_name}.workflow"
                try:
                    existing = _read_x_record(directory_fd, binding_name)
                except FileNotFoundError:
                    existing = None
                else:
                    if existing != binding or type(existing["version"]) is not int:
                        result["post_status"] = "already_attempted"
                        return result
                account = read_package_account(
                    platform="x", account_id=account_id, credential=credential, enable_provider_read=True,
                )
                if existing is None:
                    _write_x_record(directory_fd, binding_name, binding)
                else:
                    os.fsync(directory_fd)
                return _run_claimed_x_workflow(
                    package_dir, package=package, account_id=account_id, occurrence_id=occurrence_id,
                    credential=credential, approval=approval, account=account, journal_directory=journal_directory,
                    create_transport=create_transport, result=result, check_campaign_send=check_campaign_send,
                    directory_fd=directory_fd, snapshot=snapshot,
                )
    except (OSError, ValueError, RecursionError):
        result["post_status"] = "unknown"
        return result


def _run_claimed_x_workflow(
    package_dir: Path, *, package: dict[str, Any], account_id: str, occurrence_id: str,
    credential: str, approval: ChannelApproval, account: AccountObservation, journal_directory: Path,
    create_transport: GuardedPackageTransport, result: dict[str, str | float],
    check_campaign_send: Callable[[], None], directory_fd: int, snapshot: dict[str, Any] | None,
) -> dict[str, str | float]:
    media_observation = None
    expires_at = None
    if package["action"] in {"post_image", "post_video"}:
        upload = _upload_checked_x_media(
            package_dir, package=package, account_id=account_id, occurrence_id=occurrence_id,
            credential=credential, package_digest=approval.package_digest, journal_directory=journal_directory,
            resume=package["action"] == "post_video", before_upload=check_campaign_send,
        )
        result.update(media_status=upload.state, media_stage=upload.stage)
        if (
            upload.account_id != account_id or upload.package_digest != approval.package_digest
            or upload.file_sha256 != package["media"]["sha256"] or upload.occurrence_id != occurrence_id
            or upload.attempt_key != _x_upload_attempt_key(account_id, occurrence_id)
        ):
            result["media_status"] = "unknown"
            return result
        if upload.state != "available":
            if upload.reconciliation_id is not None and _MEDIA_ID.fullmatch(upload.reconciliation_id):
                result["media_reconciliation_id"] = upload.reconciliation_id
            if upload.expires_at is not None and math.isfinite(upload.expires_at):
                result["media_expires_at"] = upload.expires_at
            return result
        if (
            not isinstance(upload.provider_id, str) or not _MEDIA_ID.fullmatch(upload.provider_id)
            or not isinstance(upload.expires_at, (int, float)) or not math.isfinite(upload.expires_at)
        ):
            result["media_status"] = "unknown"
            return result
        expires_at = upload.expires_at
        if time.time() >= expires_at:
            result["media_status"] = "expired"
            result["media_reconciliation_id"] = upload.provider_id
            result["media_expires_at"] = expires_at
            return result
        media_observation = MediaObservation(
            account_id, upload.file_sha256, upload.provider_id, f"x-media-upload:{upload.attempt_key}",
        )

    receipt = None
    if snapshot is not None:
        receipt = {
            "version": 1, "status": "accepted_by_provider", "snapshot": snapshot,
            "approval_ref": approval.approval_ref, "package": package,
            "media_id": media_observation.provider_id if media_observation else None,
            "media_expires_at": expires_at,
        }
        if len(_json(receipt)) > _RECEIPT_LIMIT - 256:
            raise ValueError("X campaign receipt snapshot exceeds the size limit")

    path, fields = _prepare_x_create(
        package_dir, package=package, account_id=account_id, credential=credential,
        account_observation=account, media_observation=media_observation,
    )
    if path != "/2/tweets":
        raise ValueError("invalid X create request")
    body = _json(fields)
    try:
        check_campaign_send()
    except (OSError, ValueError, RecursionError):
        return {**result, "post_status": "blocked", "reason": "campaign_approval_changed"}
    try:
        create_transport._claim_attempt()
    except FileExistsError:
        return {**result, "post_status": "already_attempted"}
    if media_observation is not None and expires_at is not None and time.time() >= expires_at:
        return {**result, "media_status": "expired", "media_reconciliation_id": media_observation.provider_id,
                "media_expires_at": expires_at}
    result["post_status"] = "unknown"
    try:
        status, _, raw = _request(
            "POST", "https://api.x.com/2/tweets",
            {"Authorization": f"Bearer {credential}", "Content-Type": "application/json"}, body,
            allowed_hosts={"api.x.com"},
        )
        response = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_reject_constant)
    except Exception:
        return result
    if (
        not isinstance(response, dict) or response.get("errors") not in (None, [])
        or any(key in response for key in ("error", "code", "status", "title", "detail", "type"))
    ):
        return result
    data = response.get("data")
    if not isinstance(data, dict) or ("text" in data and data["text"] != fields["text"]):
        return result
    post = _interpret_x_create(status, response, credential)
    if post["status"] == "accepted_by_provider":
        result.update(post_status=post["status"], provider_id=post["provider_id"])
        if receipt is not None:
            try:
                _write_x_record(directory_fd, _receipt_name(create_transport._claim_name), {
                    **receipt, "provider_id": post["provider_id"],
                }, exclusive=True)
                result["receipt_status"] = "stored"
            except OSError:
                result["receipt_status"] = "unconfirmed"
    return result


def _receipt_name(claim_name: str) -> str:
    return f"{claim_name}.x-receipt.json"


def _has_attempt_record(directory_fd: int, claim_name: str) -> bool:
    for name in (claim_name, _receipt_name(claim_name)):
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        return True
    return False


def read_x_create_receipt(
    journal_directory: Path, *, account_id: str, destination_id: str, occurrence_id: str,
    package_digest: str, expected_review: str, expected_approval_ref: str,
) -> dict[str, str]:
    """Read historical provider acceptance from the journal without reopening the source."""
    create_key = _create_key(account_id, destination_id, occurrence_id)
    result = {"post_status": "unknown", "attempt_key": create_key}
    if not all(isinstance(digest, str) and _DIGEST.fullmatch(digest)
               for digest in (package_digest, expected_review, expected_approval_ref)):
        return {**result, "receipt_status": "invalid"}
    try:
        directory = _local_directory(journal_directory)
        transport = GuardedPackageTransport(directory, create_key)
        with _open_x_journal(transport) as directory_fd:
            name = transport._claim_name
            if _read_x_journal_file(directory_fd, name, 16) != b"attempt_started\n":
                return {**result, "receipt_status": "invalid_claim"}
            binding = _read_x_record(directory_fd, f"{name}.workflow")
            raw = _read_x_journal_file(directory_fd, _receipt_name(name), _RECEIPT_LIMIT)
            receipt = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
            _validate_campaign_receipt(receipt, binding, account_id, occurrence_id, package_digest,
                                       expected_review, expected_approval_ref)
            if receipt["media_id"] is not None:
                _validate_receipt_upload(directory_fd, directory, receipt, account_id, occurrence_id, package_digest)
    except FileNotFoundError:
        return {**result, "receipt_status": "missing"}
    except (OSError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
        return {**result, "receipt_status": "invalid"}
    return {**result, "post_status": "accepted_by_provider", "provider_id": receipt["provider_id"],
            "receipt_status": "matched"}


def _validate_campaign_receipt(
    receipt: dict[str, Any], binding: dict[str, Any], account_id: str, occurrence_id: str,
    package_digest: str, expected_review: str, expected_approval_ref: str,
) -> None:
    if not isinstance(receipt, dict) or receipt.keys() != {
        "version", "status", "snapshot", "approval_ref", "package", "media_id", "media_expires_at", "provider_id",
    }:
        raise ValueError("invalid X campaign receipt")
    _validate_campaign_snapshot(receipt["snapshot"], expected_review, account_id, occurrence_id, package_digest)
    action = receipt["snapshot"]["review"]["action"]
    package = receipt["package"]
    if (
        type(receipt["version"]) is not int or receipt["version"] != 1
        or receipt["status"] != "accepted_by_provider" or not _MEDIA_ID.fullmatch(receipt["provider_id"])
        or receipt["approval_ref"] != expected_approval_ref or type(binding["version"]) is not int
        or binding != {"version": 1, "package_digest": package_digest, "action": action,
                       "review_digest": expected_review, "approval_ref": expected_approval_ref}
        or not isinstance(package, dict) or package.get("schema") != "social-package/1"
        or package.get("action") != action or canonical_snapshot(package)[1] != package_digest
    ):
        raise ValueError("X campaign receipt approval or package mismatch")
    media_id, deadline = receipt["media_id"], receipt["media_expires_at"]
    if action == "post_text":
        if media_id is not None or deadline is not None or package["media"] is not None:
            raise ValueError("unexpected X text receipt media")
    elif (
        not _MEDIA_ID.fullmatch(media_id) or type(deadline) not in (int, float)
        or not math.isfinite(deadline) or deadline <= 0 or not _DIGEST.fullmatch(package["media"]["sha256"])
    ):
        raise ValueError("invalid X media receipt")


def _validate_receipt_upload(
    directory_fd: int, directory: Path, receipt: dict[str, Any], account_id: str, occurrence_id: str,
    package_digest: str,
) -> None:
    package = receipt["package"]
    kind = package["action"].removeprefix("post_")
    binding = _media_binding(account_id, package_digest, package["media"]["sha256"], occurrence_id, kind)
    transport = GuardedPackageTransport(directory, binding["attempt_key"])
    claim_name = transport._claim_name
    record = _read_x_record(directory_fd, f"{claim_name}.media")
    if (
        _read_x_journal_file(directory_fd, claim_name, 16) != b"attempt_started\n"
        or record.keys() != binding.keys() | {"version", "media_id", "expires_at", "state", "next_poll_at"}
        or any(record[key] != value for key, value in binding.items())
        or type(record["version"]) is not int or record["version"] != 1 or record["state"] != "available"
        or record["media_id"] != receipt["media_id"] or type(record["expires_at"]) not in (int, float)
        or record["expires_at"] != receipt["media_expires_at"]
    ):
        raise ValueError("X campaign receipt upload does not match the journal")
