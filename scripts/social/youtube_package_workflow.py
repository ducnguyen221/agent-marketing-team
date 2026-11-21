"""One guarded YouTube upload per delivery occurrence."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.youtube import direct
from scripts.social.channels.youtube.readonly_auth import _CHANNEL, _TOKEN, interpret_channels
from scripts.social.prepare_standalone import _local_directory
from scripts.social.publish_channel_package import AccountObservation, ChannelApproval, approved_package
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import _post, _request, _response_object
from scripts.social.publish_video_package import _prepare_youtube_upload, _youtube_upload_result
from scripts.social.standalone_delivery import SCHEMA

_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_HOST = "www.googleapis.com"
_IDENTITY_URL = f"https://{_HOST}/youtube/v3/channels?part=id&mine=true&maxResults=50"
_RECEIPT_LIMIT = 4096
_CAMPAIGN_RECEIPT_LIMIT = 131072
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class YouTubeCampaignContext:
    """Select the campaign source and the exact direct-delivery review."""

    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    text_file: str | None = None
    media_file: str | None = None


def _identity(channel_id: str, occurrence_id: str) -> dict[str, str]:
    if (
        not isinstance(channel_id, str) or not _CHANNEL.fullmatch(channel_id)
        or not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id)
    ):
        raise ValueError("invalid YouTube channel or occurrence")
    return {"platform": "youtube", "operation": "videos.insert",
            "channel_id": channel_id, "occurrence_id": occurrence_id}


def _campaign_source(
    package_dir: Path, context: YouTubeCampaignContext, identity: dict[str, str],
    approval: ChannelApproval, options: dict[str, Any],
) -> dict[str, Any]:
    from scripts.social.check_package_readiness import _check_target

    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": identity["channel_id"],
        "destination_id": identity["channel_id"], "occurrence_id": identity["occurrence_id"],
        "scheduled_at": None, "timezone": context.timezone, "privacy": options["privacy"],
        "options": options, "text_file": context.text_file, "media_file": context.media_file,
    }, context.approval_directory, decision=None)
    snapshot = checked["snapshot"]
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval.approval_ref
        or checked["expected_review"] != context.expected_review
        or snapshot["review"]["package_digest"] != approval.package_digest
    ):
        raise ValueError("YouTube target approval is missing, stale, revoked or mismatched")
    return snapshot


def _validate_receipt_snapshot(
    snapshot: Any, binding: dict[str, str], options: dict[str, Any],
) -> None:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if not isinstance(snapshot, dict) or canonical_snapshot(snapshot)[1] != binding["review_digest"]:
        raise ValueError("YouTube campaign receipt review mismatch")
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        review["platform"] != "youtube" or review["destination_kind"] != "channel"
        or review["action"] != "post_video" or review["scheduled_at"] is not None
        or review["account_id"] != binding["channel_id"] or review["destination_id"] != binding["channel_id"]
        or review["occurrence_key"] != binding["occurrence_id"]
        or review["package_digest"] != binding["package_digest"]
        or canonical_snapshot(review["delivery_options"])[1] != canonical_snapshot(options)[1]
    ):
        raise ValueError("YouTube campaign receipt target or options mismatch")


def _read_upload_account(channel_id: str, credential: str) -> AccountObservation:
    status, _, raw = _request(
        "GET", _IDENTITY_URL, {"Accept": "application/json", "Authorization": f"Bearer {credential}"},
        b"", allowed_hosts={_HOST},
    )
    payload = _response_object(raw)
    if (
        interpret_channels(status, payload, expected_channel_id=channel_id)["identity"] != "match"
        or len(payload["items"]) != 1 or "nextPageToken" in payload or "prevPageToken" in payload
    ):
        raise ValueError("YouTube credential does not identify one matching channel")
    page = payload.get("pageInfo")
    if (
        not isinstance(page, dict) or type(page.get("totalResults")) is not int
        or page["totalResults"] != 1
    ):
        raise ValueError("YouTube channel list completeness could not be verified")
    return AccountObservation(
        "youtube", channel_id, hashlib.sha256(credential.encode()).hexdigest(),
        "youtube:single-mine-channel",
    )


def _write_record(directory: int, name: str, record: dict[str, Any]) -> None:
    body, _ = canonical_snapshot(record)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory)


def _read_record(directory: int, name: str, *, limit: int = _RECEIPT_LIMIT, sync: bool = False) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise OSError("invalid YouTube journal record")
        raw = stream.read(limit + 1)
        if sync:
            # A concurrent writer may have written the bytes before syncing them.
            os.fsync(stream.fileno())
            os.fsync(directory)
        return raw


def _stored_result(
    directory: int, claim_name: str, receipt_name: str, binding: dict[str, str],
) -> dict[str, str]:
    attempt_key = binding["attempt_key"]
    campaign = "review_digest" in binding
    unknown = {"status": "unknown", "attempt_key": attempt_key, "receipt_status": "unverified"}
    try:
        if _read_record(directory, claim_name) != canonical_snapshot(binding)[0]:
            return unknown
        limit = _CAMPAIGN_RECEIPT_LIMIT if campaign else _RECEIPT_LIMIT
        raw = _read_record(directory, receipt_name, limit=limit, sync=True)
        stored = _response_object(raw)
        identifier = stored.get("provider_id")
        if not isinstance(identifier, str) or not _VIDEO_ID.fullmatch(identifier):
            return unknown
        receipt = {**binding, "status": "accepted_by_provider", "provider_id": identifier}
        if campaign:
            snapshot, metadata = stored["campaign_snapshot"], stored["metadata"]
            snippet, status = metadata["snippet"], metadata["status"]
            options = {"title": snippet["title"], "category_id": snippet["categoryId"],
                       "privacy": status["privacyStatus"], "made_for_kids": status["selfDeclaredMadeForKids"]}
            if (
                canonical_snapshot(metadata)[1] != binding["metadata_digest"]
                or metadata != direct.preview_video(
                    description=snippet["description"], media_id="fixture-video", **options,
                )["request"]["body"]
            ):
                return unknown
            _validate_receipt_snapshot(snapshot, binding, options)
            receipt.update(campaign_snapshot=snapshot, metadata=metadata)
        if raw != canonical_snapshot(receipt)[0]:
            return unknown
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return unknown
    return {"status": receipt["status"], "provider_id": identifier,
            "attempt_key": attempt_key, "receipt_status": "matched"}


def _campaign_binding(
    identity: dict[str, str], *, package_digest: str, metadata_digest: str,
    expected_review: str, expected_approval_ref: str,
) -> dict[str, str]:
    if not all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in (
        package_digest, metadata_digest, expected_review, expected_approval_ref,
    )):
        raise ValueError("invalid YouTube campaign receipt digests")
    return {
        "schema": "youtube-campaign-package-upload/1", **identity,
        "attempt_key": canonical_snapshot(identity)[1], "package_digest": package_digest,
        "metadata_digest": metadata_digest, "review_digest": expected_review,
        "approval_ref": expected_approval_ref,
    }


def _open_journal(journal_directory: Path) -> int:
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    directory = os.open(_local_directory(journal_directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("YouTube attempt journal directory must be private to its owner")
    except (OSError, ValueError):
        os.close(directory)
        raise
    return directory


def read_youtube_upload_receipt(
    journal_directory: Path, *, channel_id: str, occurrence_id: str, package_digest: str,
    metadata_digest: str, expected_review: str, expected_approval_ref: str,
) -> dict[str, str]:
    """Read historical campaign upload evidence using the original review and decision digests."""
    binding = _campaign_binding(
        _identity(channel_id, occurrence_id), package_digest=package_digest, metadata_digest=metadata_digest,
        expected_review=expected_review, expected_approval_ref=expected_approval_ref,
    )
    attempt_key = binding["attempt_key"]
    directory = _open_journal(journal_directory)
    try:
        return _stored_result(
            directory, f"{attempt_key}.youtube-attempt.json", f"{attempt_key}.youtube-receipt.json", binding,
        )
    finally:
        os.close(directory)


def run_youtube_package_workflow(
    package_dir: Path, *, channel_id: str, occurrence_id: str, credential: str,
    approval: ChannelApproval, title: str, category_id: str, privacy: str, made_for_kids: bool,
    journal_directory: Path, enable_dispatch: bool = False,
    campaign_context: YouTubeCampaignContext | None = None,
) -> dict[str, str]:
    """Use a code-owned channel check, exclusive claim and narrow upload receipt."""
    require_production_authority()
    if enable_dispatch is not True:
        raise ValueError("YouTube workflow dispatch is disabled")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    identity = _identity(channel_id, occurrence_id)
    if (
        not isinstance(credential, str) or not _TOKEN.fullmatch(credential)
        or not isinstance(approval, ChannelApproval)
        or not isinstance(approval.options_digest, str)
    ):
        raise ValueError("invalid YouTube workflow channel, credential, approval or occurrence")
    package = approved_package(
        package_dir, platform="youtube", account_id=channel_id, destination_id=channel_id,
        credential=credential, approval=approval, enable_dispatch=enable_dispatch,
    )
    expected_schema = SCHEMA if campaign_context is None else "social-package/1"
    if package.get("schema") != expected_schema or package.get("action") != "post_video":
        raise ValueError("YouTube workflow requires a video package bound to the selected source")
    options = {"title": title, "category_id": category_id, "privacy": privacy, "made_for_kids": made_for_kids}
    metadata = direct.preview_video(
        description=package["content"]["text"], media_id="fixture-video", **options,
    )["request"]["body"]
    metadata_digest = canonical_snapshot(metadata)[1]
    if not hmac.compare_digest(approval.options_digest, metadata_digest):
        raise ValueError("approval does not match YouTube metadata")

    attempt_key = canonical_snapshot(identity)[1]
    receipt_fields: dict[str, Any] = {}
    snapshot = None
    if campaign_context is None:
        binding_digest = canonical_snapshot({
            "package_digest": approval.package_digest, "metadata_digest": metadata_digest,
        })[1]
        binding = {"schema": "youtube-package-upload/1", **identity,
                   "attempt_key": attempt_key, "binding_digest": binding_digest}
    else:
        binding = _campaign_binding(
            identity, package_digest=approval.package_digest, metadata_digest=metadata_digest,
            expected_review=campaign_context.expected_review, expected_approval_ref=approval.approval_ref,
        )
        snapshot = _campaign_source(package_dir, campaign_context, identity, approval, options)
        _validate_receipt_snapshot(snapshot, binding, options)
        receipt_fields = {"campaign_snapshot": snapshot, "metadata": metadata}
        if len(canonical_snapshot({**binding, **receipt_fields, "status": "accepted_by_provider",
                                   "provider_id": "x" * 11})[0]) > _CAMPAIGN_RECEIPT_LIMIT:
            raise ValueError("YouTube campaign receipt exceeds the size limit")
    claim_name = f"{attempt_key}.youtube-attempt.json"
    receipt_name = f"{attempt_key}.youtube-receipt.json"
    directory = _open_journal(journal_directory)
    try:
        for name in (claim_name, receipt_name):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            stored = _stored_result(directory, claim_name, receipt_name, binding)
            if campaign_context is None and stored["status"] == "accepted_by_provider":
                _read_upload_account(channel_id, credential)
            return stored

        account = _read_upload_account(channel_id, credential)
        request = _prepare_youtube_upload(
            package_dir, channel_id=channel_id, credential=credential, approval=approval, **options,
            account_observation=account, enable_dispatch=enable_dispatch, expected_schema=expected_schema,
        )

        def check_campaign_send() -> None:
            if (
                campaign_context is not None
                and _campaign_source(package_dir, campaign_context, identity, approval, options) != snapshot
            ):
                raise ValueError("YouTube target approval changed before dispatch")

        check_campaign_send()
        try:
            _write_record(directory, claim_name, binding)
        except OSError:
            return _stored_result(directory, claim_name, receipt_name, binding)
        try:
            check_campaign_send()
        except Exception:
            return {"status": "blocked_before_send", "attempt_key": attempt_key, "receipt_status": "unavailable"}

        try:
            status, _, response = _post(*request)
            provider_status = response.get("status")
            if (
                "error" in response or "errors" in response
                or ("kind" in response and response["kind"] != "youtube#video")
                or not isinstance(provider_status, dict) or provider_status.get("privacyStatus") != privacy
            ):
                response = {}
            post = _youtube_upload_result(status, response, channel_id=channel_id, credential=credential)
        except Exception:
            return _stored_result(directory, claim_name, receipt_name, binding)
        if post["status"] != "accepted_by_provider":
            return _stored_result(directory, claim_name, receipt_name, binding)
        receipt = {**binding, **post, **receipt_fields}
        try:
            _write_record(directory, receipt_name, receipt)
        except OSError:
            return {"status": "unknown", "provider_id": post["provider_id"],
                    "attempt_key": attempt_key, "receipt_status": "unconfirmed"}
        return {**post, "attempt_key": attempt_key, "receipt_status": "stored"}
    finally:
        os.close(directory)
