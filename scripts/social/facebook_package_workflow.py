"""Guard Facebook Page creation and first-comment delivery."""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.facebook.direct import _check_page, _text
from scripts.social.prepare_package import _unique_object
from scripts.social.prepare_standalone import _local_directory
from scripts.social.publish_facebook_package import (
    FacebookPackageApproval,
    FacebookPostObservation,
    _POST_ID,
    _approved_package,
    _publish_facebook_first_comment,
    _publish_facebook_package,
    publish_facebook_first_comment,
    publish_facebook_package,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _request, _response_object
from scripts.social.publish_package_workflow import read_package_account
from scripts.social.standalone_delivery import SCHEMA


_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_PHOTO_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_CREATE_ACTIONS = {"post_text", "post_image", "post_video"}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_LIMIT = 131072
_CLAIM = b"attempt_started\n"
_PAGE_PRIVACY = "platform_default"


@dataclass(frozen=True)
class FacebookCampaignContext:
    """Select a campaign source and the exact target review approved by its operator."""

    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    privacy: str
    comment_file: str | None = None
    media_file: str | None = None


def _validate_campaign_source(
    source: Any, *, page_id: str, api_version: str, occurrence_id: str,
    package_digest: str, expected_review: str, approval_ref: str,
) -> dict[str, Any]:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if (
        not isinstance(source, dict) or source.keys() != {"snapshot", "approval_ref"}
        or source["approval_ref"] != approval_ref
        or not isinstance(source["snapshot"], dict) or canonical_snapshot(source["snapshot"])[1] != expected_review
    ):
        raise ValueError("Facebook campaign receipt review mismatch")
    snapshot = source["snapshot"]
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        review["platform"] != "facebook" or review["destination_kind"] != "page"
        or review["account_id"] != page_id or review["destination_id"] != page_id
        or review["occurrence_key"] != occurrence_id or review["package_digest"] != package_digest
        or review["action"] not in _CREATE_ACTIONS or review["scheduled_at"] is not None
        or review["privacy"] != _PAGE_PRIVACY
        or review["delivery_options"] != {"api_version": api_version}
    ):
        raise ValueError("Facebook campaign receipt target mismatch")
    return review


def _campaign_source(
    package_dir: Path, context: FacebookCampaignContext, *, occurrence_id: str,
    approval: FacebookPackageApproval,
) -> dict[str, Any]:
    from scripts.social.check_package_readiness import _check_target

    if context.privacy != _PAGE_PRIVACY:
        raise ValueError("Facebook campaign delivery requires Page default visibility")
    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": approval.page_id,
        "destination_id": approval.page_id, "occurrence_id": occurrence_id,
        "scheduled_at": None, "timezone": context.timezone, "privacy": context.privacy,
        "options": {"api_version": approval.api_version}, "comment_file": context.comment_file,
        "media_file": context.media_file,
    }, context.approval_directory, decision=None)
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval.approval_ref
        or checked["expected_review"] != context.expected_review
    ):
        raise ValueError("Facebook target approval is missing, stale, revoked or mismatched")
    source = {"snapshot": checked["snapshot"], "approval_ref": approval.approval_ref}
    _validate_campaign_source(
        source, page_id=approval.page_id, api_version=approval.api_version, occurrence_id=occurrence_id,
        package_digest=approval.package_digest, expected_review=context.expected_review,
        approval_ref=approval.approval_ref,
    )
    if len(canonical_snapshot(source)[0]) > _RECEIPT_LIMIT - 2048:
        raise ValueError("Facebook campaign receipt snapshot exceeds the size limit")
    return source


def _store_receipt(transport: GuardedPackageTransport, name: str, receipt: dict[str, Any]) -> None:
    """Persist only adapter-validated IDs in the directory that holds the claim."""
    serialized, _ = canonical_snapshot(receipt)
    directory_fd = os.open(transport._journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        journal = os.fstat(directory_fd)
        if (journal.st_dev, journal.st_ino) != transport._journal_identity:
            raise OSError("attempt journal directory changed")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "wb") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_journal_json(
    transport: GuardedPackageTransport, name: str, *, limit: int = _RECEIPT_LIMIT,
) -> dict[str, Any]:
    directory_fd = os.open(transport._journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        journal = os.fstat(directory_fd)
        if (journal.st_dev, journal.st_ino) != transport._journal_identity:
            raise ValueError("Facebook attempt journal changed")
        if _read_entry(directory_fd, transport._claim_name, len(_CLAIM)) != _CLAIM:
            raise ValueError("invalid Facebook attempt claim")
        raw = _read_entry(directory_fd, name, limit, sync=True)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    receipt = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(receipt, dict):
        raise ValueError("invalid Facebook receipt")
    return receipt


def _read_entry(directory_fd: int, name: str, limit: int, *, sync: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(name, flags, dir_fd=directory_fd), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("invalid Facebook journal entry")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size or after.st_size != before.st_size or after.st_nlink != 1
            or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns
            or not os.path.samestat(after, current)
        ):
            raise ValueError("Facebook journal entry changed")
        if sync:
            os.fsync(stream.fileno())
    return raw


def read_facebook_campaign_receipt(
    journal_directory: Path, *, page_id: str, api_version: str, occurrence_id: str,
    package_digest: str, expected_review: str, approval_ref: str,
) -> dict[str, str]:
    """Match historical evidence without consulting the current content or approval head."""
    return _read_campaign_receipt(
        journal_directory, page_id=page_id, api_version=api_version, occurrence_id=occurrence_id,
        package_digest=package_digest, expected_review=expected_review, approval_ref=approval_ref,
    )


def _read_campaign_receipt(
    journal_directory: Path, *, page_id: str, api_version: str, occurrence_id: str,
    package_digest: str, expected_review: str, approval_ref: str,
    expected_journal: tuple[int, int] | None = None,
) -> dict[str, str]:
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    _check_page(page_id, api_version)
    if not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id):
        raise ValueError("invalid Facebook delivery occurrence")
    if not all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in (
        package_digest, expected_review, approval_ref,
    )):
        raise ValueError("invalid Facebook campaign receipt references")
    occurrence = {"platform": "facebook", "page_id": page_id, "occurrence_id": occurrence_id}
    create_key = canonical_snapshot({**occurrence, "operation": "create"})[1]
    result = {"attempt_key": create_key, "post_status": "unknown", "comment_status": "unknown"}
    try:
        directory = _local_directory(journal_directory)
        transport = GuardedPackageTransport(directory, create_key)
        if expected_journal is not None and transport._journal_identity != expected_journal:
            raise ValueError("Facebook attempt journal changed")
        receipt = _read_journal_json(transport, f"{create_key}.create-receipt.json")
        source = receipt.pop("campaign_source", None)
        review = _validate_campaign_source(
            source, page_id=page_id, api_version=api_version, occurrence_id=occurrence_id,
            package_digest=package_digest, expected_review=expected_review, approval_ref=approval_ref,
        )
        action = review["action"]
        ids = {key: receipt.pop(key) for key in ("provider_id", "photo_id", "post_id") if key in receipt}
        provider_id = ids.get("provider_id")
        post_id = ids.get("post_id")
        if (
            receipt != {"schema": "facebook-create-receipt/1", **occurrence, "action": action,
                        "api_version": api_version, "package_digest": package_digest,
                        "status": "accepted_by_provider"}
            or not isinstance(provider_id, str) or not _POST_ID.fullmatch(provider_id)
            or ("post_id" in ids and (not isinstance(post_id, str) or not _page_post_id(page_id, post_id)))
            or (action == "post_text" and "post_id" in ids and post_id != provider_id)
            or (action == "post_image" and ids.get("photo_id") != provider_id)
            or (action == "post_image" and "post_id" in ids and not _PHOTO_ID.fullmatch(provider_id))
            or (action != "post_image" and "photo_id" in ids)
            or (action == "post_video" and "post_id" in ids)
        ):
            raise ValueError("invalid Facebook create receipt binding")
    except FileNotFoundError:
        return {**result, "receipt_status": "missing"}
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        return {**result, "receipt_status": "invalid"}
    result.update(ids, post_status="accepted_by_provider", receipt_status="matched")
    if action == "post_video":
        return {**result, "comment_status": "not_requested"}
    if post_id is None:
        return result
    comment_key = canonical_snapshot({**occurrence, "operation": "comment"})[1]
    try:
        comment_transport = GuardedPackageTransport(directory, comment_key)
        if comment_transport._journal_identity != transport._journal_identity:
            raise ValueError("Facebook attempt journal changed")
        comment = _read_journal_json(comment_transport, f"{comment_key}.comment-receipt.json")
        comment_id = comment.pop("provider_id", None)
        if (
            comment != {**receipt, "schema": "facebook-comment-receipt/1", "campaign_source": source,
                        "post_id": post_id}
            or not isinstance(comment_id, str) or not _POST_ID.fullmatch(comment_id)
        ):
            raise ValueError("invalid Facebook comment receipt binding")
    except FileNotFoundError:
        return {**result, "comment_receipt_status": "missing"}
    except (OSError, TypeError, ValueError, RecursionError):
        return {**result, "comment_receipt_status": "invalid"}
    return {**result, "comment_status": "accepted_by_provider", "comment_verification": "unverified",
            "comment_provider_id": comment_id, "comment_receipt_status": "matched"}


def _page_post_id(page_id: str, post_id: str) -> bool:
    return re.fullmatch(rf"{page_id}_[1-9][0-9]{{0,31}}", post_id) is not None


def _comment_already_attempted(transport: GuardedPackageTransport, comment_key: str) -> bool:
    return any(os.path.lexists(transport._journal_directory / name) for name in (
        transport._claim_name, f"{comment_key}.comment-receipt.json",
    ))


def _save_create_result(
    receipt: dict[str, str], *, page_id: str, action: str, comment_requested: bool,
    transport: GuardedPackageTransport, create_name: str, binding: dict[str, Any],
) -> dict[str, str]:
    result = {"post_status": receipt["status"], "comment_status": "not_requested"}
    if receipt["status"] != "accepted_by_provider":
        if comment_requested:
            result.update(comment_status="blocked", comment_reason="post_status_unknown")
        return result
    post_id = None
    if action == "post_text":
        post_id = receipt["provider_id"]
    elif action == "post_image" and _PHOTO_ID.fullmatch(receipt.get("photo_id", "")):
        post_id = receipt.get("post_id")
    if post_id and _page_post_id(page_id, post_id):
        receipt["post_id"] = post_id
    else:
        receipt.pop("post_id", None)
    result.update((key, receipt[key]) for key in ("provider_id", "photo_id", "post_id") if key in receipt)
    try:
        _store_receipt(transport, create_name, {"schema": "facebook-create-receipt/1", **binding, **receipt})
    except OSError:
        result["receipt_status"] = "unknown"
        if comment_requested:
            result.update(comment_status="blocked", comment_reason="create_receipt_not_durable")
        return result
    result["receipt_status"] = "saved"
    return result


def _read_created_post(*, page_id: str, post_id: str, api_version: str, page_access_token: str,
                       message: str, package_digest: str, create_key: str) -> FacebookPostObservation | None:
    query = urlencode({"fields": "id,from{id},message,is_published"})
    url = f"https://graph.facebook.com/{api_version}/{post_id}?{query}"
    try:
        status, _, raw = _request("GET", url, {"Authorization": f"Bearer {page_access_token}"}, b"",
                                  allowed_hosts={"graph.facebook.com"})
    except RuntimeError:
        return None
    payload = _response_object(raw)
    author = payload.get("from")
    if (
        status != 200 or {"error", "errors"} & payload.keys() or payload.get("id") != post_id
        or not isinstance(author, dict) or author.get("id") != page_id
        or payload.get("message") != message or payload.get("is_published") is not True
    ):
        return None
    return FacebookPostObservation(page_id, package_digest, post_id, f"facebook:graph-page-post:{create_key}")


def run_facebook_package_workflow(
    package_dir: Path,
    *,
    page_id: str,
    api_version: str,
    occurrence_id: str,
    page_access_token: str,
    approval: FacebookPackageApproval,
    journal_directory: Path,
    enable_dispatch: bool = False,
    campaign_context: FacebookCampaignContext | None = None,
) -> dict[str, str]:
    """Create once per Page occurrence and require live readback before commenting."""
    if enable_dispatch is not True:
        raise ValueError("Facebook workflow dispatch is disabled")
    require_production_authority()
    if not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id):
        raise ValueError("invalid Facebook delivery occurrence")
    package = _approved_package(package_dir, page_id, api_version, page_access_token, approval)
    expected_schema = SCHEMA if campaign_context is None else "social-package/1"
    if package["schema"] != expected_schema or package["action"] not in _CREATE_ACTIONS:
        raise ValueError("Facebook workflow requires a text, image, or video Page package for its source")
    action = package["action"]
    message = _text(package["content"]["text"])
    comment_requested = "first_comment" in package["content"]
    if comment_requested:
        _text(package["content"]["first_comment"])
        if campaign_context is not None and action == "post_video":
            raise ValueError("Facebook campaign video does not support a first comment")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")

    occurrence = {"platform": "facebook", "page_id": page_id, "occurrence_id": occurrence_id}
    create_key = canonical_snapshot({**occurrence, "operation": "create"})[1]
    comment_key = canonical_snapshot({**occurrence, "operation": "comment"})[1]
    source = None
    campaign_send = {}
    result = None
    create_name = f"{create_key}.create-receipt.json"
    if campaign_context is not None:
        journal_directory = _local_directory(journal_directory)
    transport = GuardedPackageTransport(journal_directory, create_key)
    if campaign_context is not None:
        context = campaign_context
        if any(os.path.lexists(journal_directory / name) for name in (transport._claim_name, create_name)):
            result = _read_campaign_receipt(
                journal_directory, page_id=page_id, api_version=api_version, occurrence_id=occurrence_id,
                package_digest=approval.package_digest, expected_review=context.expected_review,
                approval_ref=approval.approval_ref, expected_journal=transport._journal_identity,
            )
            if (
                result["receipt_status"] != "matched" or not comment_requested
                or result.get("comment_receipt_status") != "missing"
            ):
                if result["receipt_status"] == "matched" and not comment_requested:
                    result["comment_status"] = "not_requested"
                return result
        source = _campaign_source(package_dir, context, occurrence_id=occurrence_id, approval=approval)

        def check_campaign_send() -> None:
            if source != _campaign_source(package_dir, context, occurrence_id=occurrence_id, approval=approval):
                raise ValueError("Facebook target approval changed before dispatch")

        campaign_send = {"before_campaign_send": check_campaign_send}
    account = read_package_account(
        platform="facebook", account_id=page_id, credential=page_access_token,
        api_version=api_version, enable_provider_read=True,
    )
    binding: dict[str, Any] = {**occurrence, "action": action, "api_version": api_version,
                               "package_digest": approval.package_digest}
    if source is not None:
        binding["campaign_source"] = source
    if result is None:
        create = publish_facebook_package if source is None else _publish_facebook_package
        receipt = create(
            package_dir, page_id=page_id, api_version=api_version, page_access_token=page_access_token,
            approval=approval, transport=transport.post_form, account_observation=account, enable_dispatch=True,
            **campaign_send,
        )
        result = _save_create_result(
            receipt, page_id=page_id, action=action, comment_requested=comment_requested,
            transport=transport, create_name=create_name, binding=binding,
        )
    if not comment_requested or result.get("receipt_status") not in {"saved", "matched"}:
        return result
    post_id = result.get("post_id")
    if post_id is None:
        result.update(comment_status="blocked", comment_reason="page_post_id_unavailable")
        return result

    try:
        comment_transport = GuardedPackageTransport(journal_directory, comment_key)
    except (OSError, ValueError):
        result.update(comment_status="blocked", comment_reason="attempt_journal_unavailable")
        return result
    if (comment_transport._journal_directory, comment_transport._journal_identity) != (
        transport._journal_directory, transport._journal_identity,
    ):
        result.update(comment_status="blocked", comment_reason="attempt_journal_changed")
        return result
    if source is not None and _comment_already_attempted(comment_transport, comment_key):
        result.update(comment_status="unknown", comment_reason="existing_comment_attempt")
        return result
    observation = _read_created_post(page_id=page_id, post_id=post_id, api_version=api_version,
                                     page_access_token=page_access_token, message=message,
                                     package_digest=approval.package_digest, create_key=create_key)
    if observation is None:
        result.update(comment_status="blocked", comment_reason="post_readback_unverified")
        return result
    send_comment = publish_facebook_first_comment if source is None else _publish_facebook_first_comment
    try:
        comment = send_comment(
            package_dir, page_id=page_id, api_version=api_version, page_access_token=page_access_token,
            approval=approval, transport=comment_transport.post_form, observation=observation,
            account_observation=account, enable_dispatch=True, **campaign_send,
        )
    except (OSError, ValueError):
        if source is None:
            raise
        result.update(comment_status="blocked", comment_reason="campaign_evidence_unverified")
        return result
    result["comment_status"] = comment["status"]
    if comment["status"] == "accepted_by_provider":
        result["comment_provider_id"] = comment["provider_id"]
        result["comment_verification"] = "unverified"
        if source is not None:
            try:
                _store_receipt(comment_transport, f"{comment_key}.comment-receipt.json", {
                    "schema": "facebook-comment-receipt/1", **binding, "post_id": post_id, **comment,
                })
                result["comment_receipt_status"] = "saved"
            except OSError:
                result["comment_receipt_status"] = "unknown"
    return result
