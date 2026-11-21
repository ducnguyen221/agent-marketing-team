"""Journal a single create for a target-bound Discord package."""
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

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.discord.readonly_auth import _valid_id
from scripts.social.prepare_package import _unique_object
from scripts.social.prepare_standalone import IMAGE_ALBUM_ACTION, _local_directory, _open_input
from scripts.social.publish_channel_package import (
    ChannelApproval,
    _publish_discord_package,
    approved_package,
    discord_target_digest,
    publish_discord_package,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport
from scripts.social.standalone_delivery import SCHEMA, read_delivery_manifest

_CLAIM = b"attempt_started\n"
_RECEIPT_LIMIT = 4096
_CAMPAIGN_RECEIPT_LIMIT = 131072
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ACTIONS = {"post_text", "post_image", "post_video", "post_document", IMAGE_ALBUM_ACTION}


@dataclass(frozen=True)
class DiscordCampaignContext:
    """Select the campaign source and operator's exact direct-delivery review."""

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


def _identity(
    bot_id: str, channel_id: str, guild_id: str, occurrence_id: str, package_digest: str,
) -> dict[str, str]:
    target_digest = discord_target_digest(bot_id=bot_id, channel_id=channel_id, guild_id=guild_id)
    if (
        not isinstance(occurrence_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", occurrence_id)
        or not isinstance(package_digest, str) or not _DIGEST.fullmatch(package_digest)
    ):
        raise ValueError("invalid Discord occurrence or package digest")
    scope = {"target_digest": target_digest, "occurrence_id": occurrence_id, "operation": "create"}
    return {
        **scope, "platform": "discord", "bot_id": bot_id, "channel_id": channel_id, "guild_id": guild_id,
        "attempt_key": canonical_snapshot(scope)[1], "package_digest": package_digest,
    }


def _receipt_name(attempt_key: str) -> str:
    return f"{attempt_key}.discord-receipt.json"


def _campaign_source(
    package_dir: Path, context: DiscordCampaignContext, identity: dict[str, str], approval_ref: str,
) -> dict[str, Any]:
    # The readiness route table imports Discord's target fingerprint.
    from scripts.social.check_package_readiness import _check_target

    checked = _check_target({
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": identity["bot_id"],
        "destination_id": identity["channel_id"], "occurrence_id": identity["occurrence_id"],
        "scheduled_at": None, "timezone": context.timezone, "privacy": context.privacy,
        "options": {"guild_id": identity["guild_id"]}, "text_file": context.text_file,
        "media_file": context.media_file,
        "media_files": list(context.media_files) if context.media_files is not None else None,
    }, context.approval_directory, decision=None)
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval_ref
        or checked["expected_review"] != context.expected_review
    ):
        raise ValueError("Discord target approval is missing, stale, revoked or mismatched")
    snapshot = checked["snapshot"]
    package = read_delivery_manifest(package_dir)
    if (
        package.get("schema") != "social-package/1"
        or canonical_snapshot(package)[1] != identity["package_digest"]
    ):
        raise ValueError("Discord campaign package does not match the approved target")
    source = {
        "snapshot": snapshot, "approval_ref": approval_ref,
        "album_manifest": package if package["action"] == IMAGE_ALBUM_ACTION else None,
    }
    _validate_campaign_receipt_source(source, identity, context.expected_review, approval_ref)
    return source


def _validate_campaign_receipt_source(
    source: Any, identity: dict[str, str], expected_review: str, expected_approval_ref: str,
) -> None:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if (
        not isinstance(source, dict) or source.keys() != {"snapshot", "approval_ref", "album_manifest"}
        or source["approval_ref"] != expected_approval_ref
    ):
        raise ValueError("invalid Discord campaign receipt source")
    snapshot = source["snapshot"]
    if not isinstance(snapshot, dict) or canonical_snapshot(snapshot)[1] != expected_review:
        raise ValueError("Discord campaign receipt review mismatch")
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        set(snapshot["source_gate_digests"]) != {"g1", "g2"}
        or review["platform"] != "discord" or review["destination_kind"] != "channel"
        or review["account_id"] != identity["bot_id"] or review["destination_id"] != identity["channel_id"]
        or review["occurrence_key"] != identity["occurrence_id"]
        or review["package_digest"] != identity["package_digest"]
        or review["action"] not in _ACTIONS or review["scheduled_at"] is not None
        or review["delivery_options"] != {"guild_id": identity["guild_id"]}
    ):
        raise ValueError("Discord campaign receipt target mismatch")
    manifest = source["album_manifest"]
    if review["action"] == IMAGE_ALBUM_ACTION:
        if (
            not isinstance(manifest, dict) or manifest.get("schema") != "social-package/1"
            or manifest.get("platform") != "discord" or manifest.get("destination") != "channel"
            or manifest.get("action") != IMAGE_ALBUM_ACTION
            or not isinstance(manifest.get("media"), list) or not 2 <= len(manifest["media"]) <= 10
            or canonical_snapshot(manifest)[1] != identity["package_digest"]
        ):
            raise ValueError("invalid Discord campaign receipt album manifest")
    elif manifest is not None:
        raise ValueError("unexpected Discord campaign receipt album manifest")


def _store_receipt(
    directory_fd: int, identity: dict[str, str], post: dict[str, str], source: dict[str, Any] | None,
) -> None:
    attempt_key = identity["attempt_key"]
    temporary = f".{attempt_key}.{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            receipt = {**identity, **post}
            if source is not None:
                receipt["campaign_source"] = source
            stream.write((json.dumps(receipt, sort_keys=True) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, _receipt_name(attempt_key), src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory_fd)
    os.fsync(directory_fd)


def read_discord_create_receipt(
    journal_directory: Path, *, bot_id: str, channel_id: str, guild_id: str,
    occurrence_id: str, package_digest: str, expected_review: str | None = None,
    expected_approval_ref: str | None = None,
) -> dict[str, str]:
    """Read local evidence for the exact target, occurrence and package digest."""
    identity = _identity(bot_id, channel_id, guild_id, occurrence_id, package_digest)
    attempt_key = identity["attempt_key"]
    result = {"attempt_key": attempt_key, "channel_id": channel_id, "status": "unknown"}
    campaign = expected_review is not None or expected_approval_ref is not None
    if campaign and not all(
        isinstance(value, str) and _DIGEST.fullmatch(value) for value in (expected_review, expected_approval_ref)
    ):
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
        limit = _CAMPAIGN_RECEIPT_LIMIT if campaign else _RECEIPT_LIMIT
        with _open_input(directory, _receipt_name(attempt_key), limit) as stream:
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
    if expected_review is not None and expected_approval_ref is not None:
        try:
            _validate_campaign_receipt_source(
                receipt.pop("campaign_source", None), identity, expected_review, expected_approval_ref,
            )
        except (KeyError, TypeError, ValueError, RecursionError):
            return {**result, "receipt_status": "invalid"}
    provider_id = receipt.pop("provider_id", None)
    if receipt != {**identity, "status": "accepted_by_provider"} or not _valid_id(provider_id):
        return {**result, "receipt_status": "invalid"}
    return {**result, "status": "accepted_by_provider", "provider_id": provider_id, "receipt_status": "matched"}


def run_discord_package_workflow(
    package_dir: Path, *, bot_id: str, channel_id: str, guild_id: str, occurrence_id: str,
    credential: str, approval: ChannelApproval, journal_directory: Path, enable_dispatch: bool = False,
    campaign_context: DiscordCampaignContext | None = None,
) -> dict[str, str]:
    """Attempt one Discord create and preserve the claim even if the outcome is unknown."""
    require_production_authority()
    if enable_dispatch is not True:
        raise ValueError("Discord package dispatch is disabled")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    if (
        not isinstance(approval, ChannelApproval) or approval.platform != "discord"
        or approval.account_id != bot_id or not isinstance(approval.approval_ref, str)
        or not approval.approval_ref.strip() or not isinstance(approval.options_digest, str)
        or not _DIGEST.fullmatch(approval.options_digest)
        or not isinstance(credential, str)
    ):
        raise ValueError("invalid Discord approval or credential")
    identity = _identity(bot_id, channel_id, guild_id, occurrence_id, approval.package_digest)
    if not hmac.compare_digest(approval.options_digest, identity["target_digest"]):
        raise ValueError("approval does not match the Discord bot and guild channel")
    package = approved_package(
        package_dir, platform="discord", account_id=bot_id, destination_id=channel_id,
        credential=credential, approval=approval, enable_dispatch=enable_dispatch,
    )
    source = None
    if campaign_context is None:
        if package.get("schema") != SCHEMA:
            raise ValueError("Discord campaign dispatch requires the campaign context")
    else:
        if package.get("schema") != "social-package/1":
            raise ValueError("Discord campaign context requires a campaign package")
        source = _campaign_source(package_dir, campaign_context, identity, approval.approval_ref)
        if len(json.dumps(source)) > _CAMPAIGN_RECEIPT_LIMIT - 2048:
            raise ValueError("Discord campaign receipt snapshot exceeds the size limit")

    directory = _local_directory(journal_directory)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        attempt_key = identity["attempt_key"]
        transport = GuardedPackageTransport(directory, attempt_key)
        journal_stat = os.fstat(directory_fd)
        if (journal_stat.st_dev, journal_stat.st_ino) != transport._journal_identity:
            raise ValueError("attempt journal directory changed")
        for name in (transport._claim_name, _receipt_name(attempt_key)):
            try:
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            return read_discord_create_receipt(
                directory, bot_id=bot_id, channel_id=channel_id, guild_id=guild_id,
                occurrence_id=occurrence_id, package_digest=approval.package_digest,
                expected_review=campaign_context.expected_review if campaign_context is not None else None,
                expected_approval_ref=approval.approval_ref if campaign_context is not None else None,
            )

        send_args = {
            "channel_id": channel_id, "credential": credential, "approval": approval,
            "transport": transport.post, "enable_dispatch": enable_dispatch, "guild_id": guild_id,
        }
        if campaign_context is None:
            post = publish_discord_package(package_dir, **send_args)
        else:
            def check_campaign_send() -> None:
                if source != _campaign_source(package_dir, campaign_context, identity, approval.approval_ref):
                    raise ValueError("Discord target approval changed before dispatch")

            post = _publish_discord_package(package_dir, before_campaign_send=check_campaign_send, **send_args)
        result = {**post, "attempt_key": attempt_key, "channel_id": channel_id, "receipt_status": "unavailable"}
        if post["status"] != "accepted_by_provider":
            return result
        try:
            _store_receipt(directory_fd, identity, post, source)
        except OSError:
            return {**result, "receipt_status": "unconfirmed"}
        return {**result, "receipt_status": "stored"}
    finally:
        os.close(directory_fd)
