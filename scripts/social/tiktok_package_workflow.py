"""Guarded TikTok Inbox transfer and status-only reconciliation."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.tiktok.readonly_auth import _TOKEN, _valid_open_id, check_userinfo
from scripts.social.prepare_standalone import _local_directory
from scripts.social.publish_channel_package import AccountObservation, ChannelApproval, approved_package
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import _json, _request, _response_object
from scripts.social.publish_video_package import (
    _MAX_TIKTOK_PUBLISH_ID_LENGTH,
    _prepare_tiktok_attachment,
    _tiktok_chunks,
    _valid_tiktok_publish_id,
    upload_tiktok_inbox_package,
)
from scripts.social.standalone_delivery import SCHEMA

_API_HOST = "open.tiktokapis.com"
_UPLOAD_HOST = "open-upload.tiktokapis.com"
_INIT_URL = f"https://{_API_HOST}/v2/post/publish/inbox/video/init/"
_STATUS_URL = f"https://{_API_HOST}/v2/post/publish/status/fetch/"
_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MAX_UPLOAD_URL_LENGTH = 256
_LIMIT = 8192
_CAMPAIGN_LIMIT = 131072
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class TikTokCampaignContext:
    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    text_file: str | None = None
    media_file: str | None = None


def tiktok_inbox_options_digest(*, account_id: str, occurrence_id: str) -> str:
    """Bind creator, operation and occurrence to approval options."""
    if (
        not _valid_open_id(account_id) or not isinstance(occurrence_id, str)
        or not _OCCURRENCE.fullmatch(occurrence_id)
    ):
        raise ValueError("invalid TikTok creator or occurrence")
    return canonical_snapshot({
        "platform": "tiktok", "operation": "inbox.file_upload", "account_id": account_id,
        "occurrence_id": occurrence_id,
    })[1]


def _write_record(directory: int, name: str, value: dict[str, Any]) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical_snapshot(value)[0])
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory)


def _read_record(directory: int, name: str, *, limit: int = _LIMIT) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise OSError("invalid TikTok journal record")
        raw = stream.read(limit + 1)
        os.fsync(stream.fileno())
    os.fsync(directory)
    return raw


def _post(url: str, credential: str, body: Mapping[str, Any]) -> tuple[int, list[tuple[str, str]], dict[str, Any]]:
    status, headers, raw = _request(
        "POST", url, {"Authorization": f"Bearer {credential}", "Accept": "application/json",
                      "Content-Type": "application/json; charset=UTF-8"},
        _json(body), allowed_hosts={_API_HOST},
    )
    return status, headers, _response_object(raw)


def _read_status(publish_id: str, credential: str) -> str:
    try:
        status, _, response = _post(_STATUS_URL, credential, {"publish_id": publish_id})
    except RuntimeError:
        return "unknown"
    data = response.get("data")
    error = response.get("error")
    if (
        status != 200 or "errors" in response or not isinstance(error, dict) or error.get("code") != "ok"
        or not isinstance(data, dict) or data.get("publish_id", publish_id) != publish_id
    ):
        return "unknown"
    state = data.get("status")
    if not isinstance(state, str) or (state != "FAILED" and data.get("fail_reason") not in (None, "")):
        return "unknown"
    return {
        "PROCESSING_UPLOAD": "processing",
        "SEND_TO_USER_INBOX": "awaiting_creator",
        "PUBLISH_COMPLETE": "provider_reports_creator_completed",
        "FAILED": "provider_reports_failed",
    }.get(state, "unknown")


def _campaign_binding(
    *, account_id: str, occurrence_id: str, package_digest: str, expected_review: str,
    expected_approval_ref: str,
) -> dict[str, str]:
    attempt_key = tiktok_inbox_options_digest(account_id=account_id, occurrence_id=occurrence_id)
    if not all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in (
        package_digest, expected_review, expected_approval_ref,
    )):
        raise ValueError("invalid TikTok campaign receipt digests")
    return {
        "schema": "tiktok-campaign-inbox-upload/1", "platform": "tiktok", "operation": "inbox.file_upload",
        "account_id": account_id, "occurrence_id": occurrence_id, "attempt_key": attempt_key,
        "package_digest": package_digest, "review_digest": expected_review, "approval_ref": expected_approval_ref,
    }


def _campaign_source(
    package_dir: Path, context: TikTokCampaignContext, binding: dict[str, str],
) -> dict[str, Any]:
    from scripts.social.check_package_readiness import _check_target

    account_id = binding["account_id"]
    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": account_id,
        "destination_id": account_id, "occurrence_id": binding["occurrence_id"], "scheduled_at": None,
        "timezone": context.timezone, "privacy": "inbox", "options": {},
        "text_file": context.text_file, "media_file": context.media_file,
    }, context.approval_directory, decision=None)
    snapshot = checked["snapshot"]
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != binding["approval_ref"]
        or checked["expected_review"] != binding["review_digest"]
        or snapshot["review"]["package_digest"] != binding["package_digest"]
    ):
        raise ValueError("TikTok target approval is missing, stale, revoked or mismatched")
    return snapshot


def _validate_campaign_receipt(
    snapshot: Any, package: Any, binding: dict[str, str],
) -> None:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if (
        not isinstance(snapshot, dict) or canonical_snapshot(snapshot)[1] != binding["review_digest"]
        or not isinstance(package, dict) or canonical_snapshot(package)[1] != binding["package_digest"]
    ):
        raise ValueError("TikTok campaign receipt snapshot mismatch")
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        review["platform"] != "tiktok" or review["destination_kind"] != "profile"
        or review["action"] != "upload_video" or review["scheduled_at"] is not None
        or review["privacy"] != "inbox" or review["delivery_options"] != {}
        or review["account_id"] != binding["account_id"] or review["destination_id"] != binding["account_id"]
        or review["occurrence_key"] != binding["occurrence_id"]
        or review["package_digest"] != binding["package_digest"]
        or package.get("schema") != "social-package/1" or package.get("platform") != "tiktok"
        or package.get("destination") != "profile" or package.get("action") != "upload_video"
    ):
        raise ValueError("TikTok campaign receipt target mismatch")
    media = package["media"]
    if (
        not isinstance(media, dict) or media.get("kind") != "video" or media.get("file") != "attachment.mp4"
        or type(media.get("bytes")) is not int or media["bytes"] <= 0
        or not isinstance(media.get("sha256"), str) or not _DIGEST.fullmatch(media["sha256"])
    ):
        raise ValueError("TikTok campaign receipt media mismatch")


def _open_journal(journal_directory: Path) -> int:
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    directory = os.open(_local_directory(journal_directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("TikTok attempt journal directory must be private to its owner")
    except (OSError, ValueError):
        os.close(directory)
        raise
    return directory


def _journal_names(attempt_key: str) -> tuple[str, str, str]:
    return (f"{attempt_key}.tiktok-attempt.json", f"{attempt_key}.tiktok-init.json",
            f"{attempt_key}.tiktok-upload.json")


def _stored_campaign_result(directory: int, binding: dict[str, str]) -> dict[str, str]:
    attempt_key = binding["attempt_key"]
    unknown = {"status": "unknown", "attempt_key": attempt_key, "visibility": "unverified"}
    claim_name, receipt_name, upload_name = _journal_names(attempt_key)
    try:
        if _read_record(directory, claim_name) != canonical_snapshot(binding)[0]:
            return unknown
        raw = _read_record(directory, receipt_name, limit=_CAMPAIGN_LIMIT)
        receipt = _response_object(raw)
        publish_id = receipt["provider_id"]
        snapshot, package = receipt["campaign_snapshot"], receipt["package"]
        if not _valid_tiktok_publish_id(publish_id):
            return unknown
        _validate_campaign_receipt(snapshot, package, binding)
        fields = {**binding, "provider_id": publish_id}
        if raw != canonical_snapshot({**fields, "campaign_snapshot": snapshot, "package": package})[0]:
            return unknown
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return unknown
    result = {**unknown, "provider_id": publish_id, "receipt_status": "init_matched"}
    try:
        uploaded = _read_record(directory, upload_name)
    except FileNotFoundError:
        return result
    except OSError:
        return unknown
    if uploaded != canonical_snapshot({**fields, "status": "upload_accepted_by_provider"})[0]:
        return unknown
    return {**result, "status": "upload_accepted_by_provider", "receipt_status": "upload_matched"}


def read_tiktok_inbox_receipt(
    journal_directory: Path, *, account_id: str, occurrence_id: str, package_digest: str,
    expected_review: str, expected_approval_ref: str,
) -> dict[str, str]:
    """Read historical campaign upload evidence without contacting TikTok or reading live source files."""
    binding = _campaign_binding(
        account_id=account_id, occurrence_id=occurrence_id, package_digest=package_digest,
        expected_review=expected_review, expected_approval_ref=expected_approval_ref,
    )
    directory = _open_journal(journal_directory)
    try:
        return _stored_campaign_result(directory, binding)
    finally:
        os.close(directory)


def run_tiktok_package_workflow(
    package_dir: Path, *, account_id: str, occurrence_id: str, credential: str,
    approval: ChannelApproval, journal_directory: Path, enable_dispatch: bool = False,
    poll_only: bool = False, campaign_context: TikTokCampaignContext | None = None,
) -> dict[str, str]:
    """Transfer once, or query a journaled Inbox ID without any upload retry."""
    require_production_authority()
    if enable_dispatch is not True or type(poll_only) is not bool:
        raise ValueError("TikTok workflow is disabled")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    if not isinstance(credential, str) or not _TOKEN.fullmatch(credential):
        raise ValueError("invalid TikTok credential")
    options = tiktok_inbox_options_digest(account_id=account_id, occurrence_id=occurrence_id)
    if (
        not isinstance(approval, ChannelApproval) or not isinstance(approval.options_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", approval.options_digest)
        or not hmac.compare_digest(approval.options_digest, options)
    ):
        raise ValueError("approval does not match TikTok creator and occurrence")
    package = approved_package(
        package_dir, platform="tiktok", account_id=account_id, destination_id=account_id,
        credential=credential, approval=approval, enable_dispatch=enable_dispatch,
    )
    expected_schema = SCHEMA if campaign_context is None else "social-package/1"
    if package.get("schema") != expected_schema or package.get("action") != "upload_video":
        raise ValueError("TikTok Inbox requires a video package bound to the selected source")

    identity = {"platform": "tiktok", "operation": "inbox.file_upload", "account_id": account_id,
                "occurrence_id": occurrence_id}
    attempt_key = options
    binding = {"schema": "tiktok-inbox-upload/1", **identity, "attempt_key": attempt_key,
               "binding_digest": canonical_snapshot({"package_digest": approval.package_digest,
                                                      "options_digest": options})[1]}
    receipt_fields: dict[str, Any] = {}
    if campaign_context is not None:
        binding = _campaign_binding(
            account_id=account_id, occurrence_id=occurrence_id, package_digest=approval.package_digest,
            expected_review=campaign_context.expected_review, expected_approval_ref=approval.approval_ref,
        )
        snapshot = _campaign_source(package_dir, campaign_context, binding)
        _validate_campaign_receipt(snapshot, package, binding)
        receipt_fields = {"campaign_snapshot": snapshot, "package": package}
        if len(canonical_snapshot({
            **binding, **receipt_fields, "provider_id": "x" * _MAX_TIKTOK_PUBLISH_ID_LENGTH,
        })[0]) > _CAMPAIGN_LIMIT:
            raise ValueError("TikTok campaign receipt exceeds the size limit")
        journal_directory = _local_directory(journal_directory)
        for source in (package_dir, campaign_context.campaign, campaign_context.approval_directory):
            source = _local_directory(source)
            if journal_directory.is_relative_to(source) or source.is_relative_to(journal_directory):
                raise ValueError("TikTok attempt journal must be separate from source, package and decisions")

    def check_campaign_send() -> None:
        if campaign_context is not None and _campaign_source(
            package_dir, campaign_context, binding,
        ) != receipt_fields["campaign_snapshot"]:
            raise ValueError("TikTok target approval changed before dispatch")

    claim_name, receipt_name, upload_name = _journal_names(attempt_key)
    unknown = {"status": "unknown", "attempt_key": attempt_key, "visibility": "unverified"}
    directory = _open_journal(journal_directory)
    try:
        if poll_only:
            if campaign_context is not None:
                publish_id = _stored_campaign_result(directory, binding).get("provider_id")
            else:
                try:
                    if _read_record(directory, claim_name) != canonical_snapshot(binding)[0]:
                        return unknown
                    raw = _read_record(directory, receipt_name)
                except OSError:
                    return unknown
                publish_id = _response_object(raw).get("provider_id")
                if not _valid_tiktok_publish_id(publish_id) or raw != canonical_snapshot({
                    **binding, "provider_id": publish_id,
                })[0]:
                    return unknown
            if not _valid_tiktok_publish_id(publish_id) or publish_id == credential:
                return unknown
            if check_userinfo(credential, account_id)["identity"] != "match":
                return unknown
            check_campaign_send()
            return {**unknown, "status": _read_status(publish_id, credential), "provider_id": publish_id}

        names = (claim_name, receipt_name) if campaign_context is None else (claim_name, receipt_name, upload_name)
        for name in names:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            return unknown
        if check_userinfo(credential, account_id)["identity"] != "match":
            raise ValueError("TikTok credential does not identify the approved creator")
        upload_url: str | None = None

        def init(
            url: str, headers: Mapping[str, str], fields: Mapping[str, Any],
            files: Mapping[str, tuple[str, bytes]],
        ) -> tuple[int, list[tuple[str, str]], Mapping[str, Any]]:
            nonlocal upload_url
            if url != _INIT_URL or headers != {"Authorization": f"Bearer {credential}"} or files:
                raise ValueError("invalid TikTok Inbox initialization")
            check_campaign_send()
            _write_record(directory, claim_name, binding)
            check_campaign_send()
            status, response_headers, response = _post(_INIT_URL, credential, fields)
            data, error = response.get("data"), response.get("error")
            if (
                status != 200 or "errors" in response or not isinstance(data, dict)
                or not isinstance(error, dict) or error.get("code") != "ok"
            ):
                return status, response_headers, {}
            publish_id, candidate = data.get("publish_id"), data.get("upload_url")
            if not _valid_tiktok_publish_id(publish_id) or publish_id in (credential, candidate):
                return status, response_headers, {}
            unknown["provider_id"] = publish_id
            try:
                _write_record(directory, receipt_name, {**binding, **receipt_fields, "provider_id": publish_id})
            except OSError:
                unknown["receipt_status"] = "unconfirmed"
                return status, response_headers, {}
            unknown["receipt_status"] = "stored"
            if (
                isinstance(candidate, str) and 1 <= len(candidate) <= _MAX_UPLOAD_URL_LENGTH
                and re.fullmatch(r"[!-~]+", candidate)
                and "\\" not in candidate and "#" not in candidate
            ):
                target = urlsplit(candidate)
                if target.scheme == "https" and target.netloc == _UPLOAD_HOST and target.query:
                    upload_url = candidate
            if upload_url is None:
                return status, response_headers, {}
            return status, response_headers, response

        def put_chunk(url: str, headers: Mapping[str, str], data: bytes) -> int:
            if url != upload_url or set(headers) != {"Content-Type", "Content-Length", "Content-Range"}:
                raise ValueError("invalid TikTok chunk endpoint or headers")
            check_campaign_send()
            status, _, _ = _request("PUT", url, headers, data, allowed_hosts={_UPLOAD_HOST})
            return status

        if campaign_context is None:
            account = AccountObservation(
                "tiktok", account_id, hashlib.sha256(credential.encode()).hexdigest(), "tiktok:user-info-open-id",
            )
            result = upload_tiktok_inbox_package(
                package_dir, account_id=account_id, credential=credential, approval=approval,
                upload_host=_UPLOAD_HOST, transport=init, put_chunk=put_chunk,
                account_observation=account, enable_dispatch=enable_dispatch,
            )
        else:
            data, plan = _prepare_tiktok_attachment(package_dir, package)
            request = plan["request"]
            try:
                _, _, response = init(
                    f"https://{_API_HOST}{request['path']}", {"Authorization": f"Bearer {credential}"},
                    request["body"], {},
                )
                if not response or upload_url is None:
                    return unknown
                for headers, chunk, expected in _tiktok_chunks(data, plan):
                    if put_chunk(upload_url, headers, chunk) != expected:
                        return unknown
            except Exception:
                return unknown
            result = {"status": "upload_accepted_by_provider", "provider_id": unknown["provider_id"]}
        if (
            result["status"] != "upload_accepted_by_provider" or "provider_id" not in unknown
            or result.get("provider_id") != unknown["provider_id"]
        ):
            return unknown
        if campaign_context is not None:
            try:
                _write_record(directory, upload_name, {**binding, **result})
            except OSError:
                return {**unknown, "receipt_status": "upload_unconfirmed"}
        return {"attempt_key": attempt_key, "visibility": "unverified", **result}
    finally:
        os.close(directory)
