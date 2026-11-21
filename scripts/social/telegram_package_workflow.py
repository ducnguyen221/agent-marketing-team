"""Guarded create workflow for a target-bound Telegram channel package."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.prepare_package import _unique_object
from scripts.social.prepare_standalone import (
    TELEGRAM_ALBUM_ACTION, TELEGRAM_ALBUM_COUNTS, _local_directory, _open_input,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _request, _response_object
from scripts.social.publish_package_workflow import read_package_account
from scripts.social.publish_telegram_package import (
    _CHANNEL,
    _ERROR_FIELDS,
    _MESSAGE_ID,
    _METHODS,
    _TOKEN,
    _publish_telegram_package,
    TelegramPackageApproval,
    publish_telegram_package,
)
from scripts.social.standalone_delivery import (
    SCHEMA,
    read_delivery_manifest,
    read_standalone_attachment,
    read_telegram_image_album,
    validate_standalone_target,
)

_CLAIM = b"attempt_started\n"
_RECEIPT_LIMIT = 4096
_CAMPAIGN_RECEIPT_LIMIT = 131072
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class TelegramCampaignContext:
    """Select the campaign source and operator's exact target review."""

    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    privacy: str
    text_file: str | None = None
    media_file: str | None = None
    media_files: tuple[str, ...] | None = None
    caption_files: tuple[str, ...] | None = None


def _create_identity(bot_id: str, channel_id: str, occurrence_id: str, package_digest: str) -> dict[str, str]:
    if (
        not isinstance(bot_id, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", bot_id)
        or int(bot_id).bit_length() > 52
        or not isinstance(channel_id, str) or not _CHANNEL.fullmatch(channel_id)
        or abs(int(channel_id)).bit_length() > 52
        or not isinstance(occurrence_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", occurrence_id)
        or not isinstance(package_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", package_digest)
    ):
        raise ValueError("invalid Telegram target, occurrence or package digest")
    identity = {
        "platform": "telegram", "bot_id": bot_id, "channel_id": channel_id,
        "occurrence_id": occurrence_id, "operation": "create",
    }
    return {**identity, "attempt_key": canonical_snapshot(identity)[1], "package_digest": package_digest}


def _get_result(bot_token: str, method: str, fields: dict[str, str]) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/{method}?{urlencode(fields)}"
    try:
        status, _, raw = _request(
            "GET", url, {"Accept": "application/json"}, b"", allowed_hosts={"api.telegram.org"},
        )
    except (OSError, RuntimeError, ValueError):
        return {}
    response = _response_object(raw)
    result = response.get("result")
    if (
        status == 200 and response.get("ok") is True and isinstance(result, dict)
        and not _ERROR_FIELDS & response.keys()
    ):
        return result
    return {}


def _channel_can_post(bot_token: str, bot_id: str, channel_id: str) -> bool:
    chat = _get_result(bot_token, "getChat", {"chat_id": channel_id})
    if chat.get("type") != "channel" or type(chat.get("id")) is not int or str(chat["id"]) != channel_id:
        return False
    membership = _get_result(bot_token, "getChatMember", {"chat_id": channel_id, "user_id": bot_id})
    user = membership.get("user")
    return (
        isinstance(user, dict) and type(user.get("id")) is int and str(user["id"]) == bot_id
        and user.get("is_bot") is True and membership.get("status") == "administrator"
        and membership.get("can_post_messages") is True
    )


def _store_receipt(
    directory_fd: int, identity: dict[str, str], post: dict[str, Any],
    campaign_source: dict[str, Any] | None,
) -> None:
    attempt_key = identity["attempt_key"]
    receipt_name = f"{attempt_key}.telegram-receipt.json"
    temporary = f".{attempt_key}.{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            receipt = {**identity, **post}
            if campaign_source is not None:
                receipt["campaign_source"] = campaign_source
            stream.write((json.dumps(receipt, sort_keys=True) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, receipt_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _validate_package(
    package_dir: Path, *, bot_id: str, channel_id: str, package_digest: str,
) -> int | None:
    """Validate the standalone target and all payload bytes, returning album size if applicable."""
    package = read_delivery_manifest(package_dir)
    validate_standalone_target(
        package_dir, package, platform="telegram", account_id=bot_id,
        destination_id=channel_id, package_digest=package_digest,
    )
    action = package["action"]
    _, _, kind, limit = _METHODS[action]
    if len(package["content"]["text"].encode("utf-16-le")) // 2 > limit:
        raise ValueError("Telegram text exceeds the package limit")
    if action == TELEGRAM_ALBUM_ACTION:
        photos, _ = read_telegram_image_album(package_dir, package)
        return len(photos)
    read_standalone_attachment(package_dir, package, kind)
    return None


def _campaign_source(
    package_dir: Path, context: TelegramCampaignContext, identity: dict[str, str], approval_ref: str,
) -> dict[str, Any]:
    # The readiness module imports the route table, which shares Telegram's attempt identity.
    from scripts.social.check_package_readiness import _check_target

    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": identity["bot_id"],
        "destination_id": identity["channel_id"], "occurrence_id": identity["occurrence_id"],
        "scheduled_at": None, "timezone": context.timezone, "privacy": context.privacy,
        "options": {}, "text_file": context.text_file, "media_file": context.media_file,
        "media_files": list(context.media_files) if context.media_files is not None else None,
        "caption_files": list(context.caption_files) if context.caption_files is not None else None,
    }, context.approval_directory, decision=None)
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval_ref
        or checked["expected_review"] != context.expected_review
    ):
        raise ValueError("Telegram target approval is missing, stale, revoked or mismatched")
    snapshot = checked["snapshot"]
    package = read_delivery_manifest(package_dir)
    review = snapshot["review"]
    if (
        review["platform"] != "telegram" or review["destination_kind"] != "channel"
        or review["package_digest"] != identity["package_digest"]
        or package.get("schema") != "social-package/1"
        or not hmac.compare_digest(canonical_snapshot(package)[1], identity["package_digest"])
    ):
        raise ValueError("Telegram campaign package does not match the approved target")
    return {
        "snapshot": snapshot, "approval_ref": approval_ref,
        "album_manifest": package if review["action"] == TELEGRAM_ALBUM_ACTION else None,
    }


def _campaign_receipt_album_count(
    source: Any, identity: dict[str, str], expected_review: str, expected_approval_ref: str | None,
) -> int | None:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if (
        not isinstance(source, dict) or source.keys() != {"snapshot", "approval_ref", "album_manifest"}
        or not isinstance(expected_approval_ref, str) or not _DIGEST.fullmatch(expected_approval_ref)
        or source["approval_ref"] != expected_approval_ref
    ):
        raise ValueError("invalid Telegram campaign receipt source")
    snapshot = source["snapshot"]
    if not isinstance(snapshot, dict) or canonical_snapshot(snapshot)[1] != expected_review:
        raise ValueError("Telegram campaign receipt review mismatch")
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        review["platform"] != "telegram" or review["destination_kind"] != "channel"
        or review["account_id"] != identity["bot_id"] or review["destination_id"] != identity["channel_id"]
        or review["occurrence_key"] != identity["occurrence_id"]
        or review["package_digest"] != identity["package_digest"]
        or review["action"] not in _METHODS or review["scheduled_at"] is not None
        or review["delivery_options"]
    ):
        raise ValueError("Telegram campaign receipt target mismatch")
    manifest = source["album_manifest"]
    if review["action"] == TELEGRAM_ALBUM_ACTION:
        if (
            not isinstance(manifest, dict) or manifest.get("schema") != "social-package/1"
            or manifest.get("platform") != "telegram" or manifest.get("destination") != "channel"
            or manifest.get("action") != TELEGRAM_ALBUM_ACTION
            or canonical_snapshot(manifest)[1] != identity["package_digest"]
            or not isinstance(manifest.get("media"), list)
            or len(manifest["media"]) not in TELEGRAM_ALBUM_COUNTS
        ):
            raise ValueError("invalid Telegram campaign receipt album manifest")
        return len(manifest["media"])
    if manifest is not None:
        raise ValueError("unexpected Telegram campaign receipt album manifest")
    return None


def read_telegram_create_receipt(
    journal_directory: Path, *, package_dir: Path | None = None, bot_id: str, channel_id: str,
    occurrence_id: str, package_digest: str, expected_review: str | None = None,
    expected_approval_ref: str | None = None,
) -> dict[str, Any]:
    """Read local evidence for one exact package and occurrence without provider access."""
    identity = _create_identity(bot_id, channel_id, occurrence_id, package_digest)
    attempt_key = identity["attempt_key"]
    result = {"attempt_key": attempt_key, "status": "unknown"}
    if expected_review is None:
        if package_dir is None or expected_approval_ref is not None:
            return {**result, "receipt_status": "unverified_package"}
        try:
            album_count = _validate_package(
                package_dir, bot_id=bot_id, channel_id=channel_id, package_digest=package_digest,
            )
        except (OSError, ValueError, RecursionError):
            return {**result, "receipt_status": "unverified_package"}
    elif not isinstance(expected_review, str) or not _DIGEST.fullmatch(expected_review):
        return {**result, "receipt_status": "invalid"}
    claim_name = f"{hashlib.sha256(attempt_key.encode('ascii')).hexdigest()}.attempt"
    try:
        directory = _local_directory(journal_directory)
        with _open_input(directory, claim_name, len(_CLAIM)) as stream:
            if stream.read(len(_CLAIM) + 1) != _CLAIM:
                return {**result, "receipt_status": "invalid_claim"}
    except FileNotFoundError:
        return {**result, "receipt_status": "missing_journal_or_claim"}
    except (OSError, ValueError):
        return {**result, "receipt_status": "unverified_claim"}
    try:
        limit = _RECEIPT_LIMIT if expected_review is None else _CAMPAIGN_RECEIPT_LIMIT
        with _open_input(directory, f"{attempt_key}.telegram-receipt.json", limit) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            return {**result, "receipt_status": "invalid"}
        receipt = json.loads(raw, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return {**result, "receipt_status": "missing"}
    except (OSError, ValueError, RecursionError):
        return {**result, "receipt_status": "invalid"}
    if not isinstance(receipt, dict):
        return {**result, "receipt_status": "invalid"}
    if expected_review is not None:
        try:
            album_count = _campaign_receipt_album_count(
                receipt.pop("campaign_source", None), identity, expected_review, expected_approval_ref,
            )
        except (KeyError, TypeError, ValueError, RecursionError):
            return {**result, "receipt_status": "invalid"}
    provider_id = receipt.pop("provider_id", None)
    album = {}
    if album_count is not None:
        group_id, message_ids = receipt.pop("media_group_id", None), receipt.pop("message_ids", None)
        if (
            not isinstance(group_id, str) or not re.fullmatch(r"[!-~]{1,128}", group_id)
            or not isinstance(message_ids, list) or len(message_ids) != album_count
            or any(not isinstance(item, str) or not _MESSAGE_ID.fullmatch(item) for item in message_ids)
            or message_ids[0] != provider_id or len(set(message_ids)) != len(message_ids)
        ):
            return {**result, "receipt_status": "invalid"}
        album = {"media_group_id": group_id, "message_ids": message_ids}
    if (
        receipt != {**identity, "status": "accepted_by_provider"}
        or not isinstance(provider_id, str) or not _MESSAGE_ID.fullmatch(provider_id)
    ):
        return {**result, "receipt_status": "invalid"}
    return {**result, **album, "status": "accepted_by_provider", "provider_id": provider_id,
            "receipt_status": "matched"}


def run_telegram_package_workflow(
    package_dir: Path,
    *,
    bot_id: str,
    channel_id: str,
    occurrence_id: str,
    bot_token: str,
    approval: TelegramPackageApproval,
    journal_directory: Path,
    enable_dispatch: bool = False,
    campaign_context: TelegramCampaignContext | None = None,
) -> dict[str, Any]:
    """Create one channel post using a verified bot and a durable create claim."""
    require_production_authority()
    if enable_dispatch is not True:
        raise ValueError("Telegram package dispatch is disabled")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    if (
        not isinstance(approval, TelegramPackageApproval) or approval.bot_id != bot_id
        or approval.channel_id != channel_id or not isinstance(approval.approval_ref, str)
        or not approval.approval_ref.strip()
        or not isinstance(bot_token, str) or not _TOKEN.fullmatch(bot_token)
        or bot_token.partition(":")[0] != bot_id
    ):
        raise ValueError("invalid Telegram approval or credential")
    identity = _create_identity(bot_id, channel_id, occurrence_id, approval.package_digest)
    source = None
    campaign_send_check = None
    if campaign_context is None:
        _validate_package(
            package_dir, bot_id=bot_id, channel_id=channel_id, package_digest=approval.package_digest,
        )
    else:
        source = _campaign_source(package_dir, campaign_context, identity, approval.approval_ref)
        if len(json.dumps(source)) > _CAMPAIGN_RECEIPT_LIMIT - 2048:
            raise ValueError("Telegram campaign receipt snapshot exceeds the size limit")

        def check_campaign_send() -> None:
            if source != _campaign_source(package_dir, campaign_context, identity, approval.approval_ref):
                raise ValueError("Telegram target approval changed before dispatch")

        campaign_send_check = check_campaign_send

    directory = _local_directory(journal_directory)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        attempt_key = identity["attempt_key"]
        transport = GuardedPackageTransport(directory, attempt_key)
        journal_stat = os.fstat(directory_fd)
        if (journal_stat.st_dev, journal_stat.st_ino) != transport._journal_identity:
            raise ValueError("attempt journal directory changed")
        account = read_package_account(
            platform="telegram", account_id=bot_id, credential=bot_token, enable_provider_read=True,
        )
        if not _channel_can_post(bot_token, bot_id, channel_id):
            raise ValueError("Telegram channel posting permission could not be verified")

        send_args = {
            "channel_id": channel_id, "bot_token": bot_token, "approval": approval,
            "transport": transport.post_form, "account_observation": account, "enable_dispatch": enable_dispatch,
        }
        if campaign_send_check is None:
            post = publish_telegram_package(package_dir, **send_args)
        else:
            post = _publish_telegram_package(package_dir, before_campaign_send=campaign_send_check, **send_args)
        result = {**post, "attempt_key": attempt_key, "receipt_status": "unavailable"}
        if post["status"] != "accepted_by_provider":
            return result
        try:
            _store_receipt(directory_fd, identity, post, source)
        except OSError:
            return {**result, "receipt_status": "unconfirmed"}
        return {**result, "receipt_status": "stored"}
    finally:
        os.close(directory_fd)
