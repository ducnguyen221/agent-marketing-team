"""Resolve and bind standalone V2 delivery intents while production is blocked."""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.discord.direct import preview_message as preview_discord_message
from scripts.social.channels.facebook.direct import _check_page, _text as validate_facebook_text
from scripts.social.channels.linkedin.direct import preview_post as preview_linkedin_post
from scripts.social.channels.linkedin.media import preview_initialize
from scripts.social.channels.threads.direct import preview_container
from scripts.social.channels.tiktok.direct import preview_inbox_upload
from scripts.social.channels.x.direct import preview_post as preview_x_post
from scripts.social.channels.youtube.direct import preview_video
from scripts.social.channels.youtube.readonly_auth import _CHANNEL as _YOUTUBE_CHANNEL
from scripts.social.linkedin_package_workflow import _attempt_identity as _linkedin_identity
from scripts.social.prepare_standalone import IMAGE_ALBUM_ACTION, TELEGRAM_ALBUM_ACTION
from scripts.social.publish_channel_package import discord_target_digest
from scripts.social.publish_telegram_package import _METHODS as _TELEGRAM_METHODS
from scripts.social.standalone_delivery import (
    SCHEMA,
    _KINDS,
    _identifier,
    read_delivery_manifest,
    read_standalone_attachment,
    read_discord_image_album,
    read_telegram_image_album,
    validate_standalone_target,
)
from scripts.social.telegram_package_workflow import _create_identity as _telegram_identity
from scripts.social.tiktok_package_workflow import tiktok_inbox_options_digest
from scripts.social.x_media_upload import _ACCOUNT_ID as _X_ACCOUNT, _MAX_IMAGE_BYTES as _X_MAX_IMAGE

_TEXT_IMAGE_VIDEO = frozenset({"post_text", "post_image", "post_video"})
_WITH_DOCUMENT = _TEXT_IMAGE_VIDEO | {"post_document"}
_ROUTES = {
    "facebook": ("page", _TEXT_IMAGE_VIDEO, "facebook_package_workflow"),
    "telegram": ("channel", _WITH_DOCUMENT | {TELEGRAM_ALBUM_ACTION}, "telegram_package_workflow"),
    "linkedin": ("account", _TEXT_IMAGE_VIDEO, "linkedin_package_workflow"),
    "x": ("account", _TEXT_IMAGE_VIDEO, "x_package_workflow"),
    "youtube": ("channel", frozenset({"post_video"}), "youtube_package_workflow"),
    "tiktok": ("profile", frozenset({"upload_video"}), "tiktok_package_workflow"),
    "threads": ("account", frozenset({"post_text"}), "meta_package_workflow"),
    "discord": ("channel", _WITH_DOCUMENT | {IMAGE_ALBUM_ACTION}, "discord_package_workflow"),
}
_BLOCKED_ROUTES = {
    ("facebook", "group"): "facebook_group_delivery_unsupported",
    ("facebook", "page", "post_reel"): "facebook_reel_delivery_unsupported",
    ("instagram", "account"): "verified_immutable_hosted_media_unavailable",
    ("threads", "account", "post_image"): "verified_immutable_hosted_media_unavailable",
    ("threads", "account", "post_video"): "verified_immutable_hosted_media_unavailable",
    ("tiktok", "profile", "post_video"): "tiktok_direct_post_unsupported",
}
_OPTION_FIELDS = {
    "facebook": {"api_version"},
    "linkedin": {"api_version"},
    "threads": {"api_version"},
    "youtube": {"title", "category_id", "privacy", "made_for_kids"},
    "discord": {"guild_id"},
}
_SEPARATE_DESTINATIONS = {"telegram", "discord"}
_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "Social V2 dispatch intent rejected (invalid_arguments).\n")


def prepare_dispatch_intent(
    package_dir: Path,
    *,
    package_digest: str,
    account_id: str,
    destination_id: str,
    occurrence_id: str,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify local package bytes and prepare an exact route for later authorization."""
    package = read_delivery_manifest(package_dir)
    if package.get("schema") != SCHEMA:
        raise ValueError("dispatch intent requires a standalone V2 package")
    return _prepare_bound_route(
        package_dir, package, package_digest=package_digest, account_id=account_id,
        destination_id=destination_id, occurrence_id=occurrence_id, options=options,
    )


def _prepare_bound_route(
    package_dir: Path,
    package: dict[str, Any],
    *,
    package_digest: str,
    account_id: str,
    destination_id: str,
    occurrence_id: str,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve a route for a package already verified by its source-specific reader."""
    platform, destination, action = (package.get(key) for key in ("platform", "destination", "action"))
    if not all(isinstance(value, str) for value in (platform, destination, action)):
        raise ValueError("invalid standalone route")
    reason = _BLOCKED_ROUTES.get((platform, destination, action)) or _BLOCKED_ROUTES.get((platform, destination))
    if reason:
        raise ValueError(reason)
    route = _ROUTES.get(platform)
    if route is None or destination != route[0] or action not in route[1]:
        raise ValueError("unsupported_workflow_route")
    if not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id):
        raise ValueError("invalid delivery occurrence")
    if not _identifier(account_id) or not _identifier(destination_id):
        raise ValueError("invalid account or destination ID")
    if platform not in _SEPARATE_DESTINATIONS and destination_id != account_id:
        raise ValueError("workflow requires the account and destination IDs to match")
    if package["schema"] == SCHEMA:
        validate_standalone_target(
            package_dir, package, platform=platform, account_id=account_id,
            destination_id=destination_id, package_digest=package_digest,
        )
    if not isinstance(options, Mapping) or set(options) != _OPTION_FIELDS.get(platform, set()):
        raise ValueError("options must match the selected workflow")
    options = dict(options)
    if platform == "linkedin":
        _linkedin_identity(account_id, destination_id, occurrence_id)
    elif platform == "telegram":
        _telegram_identity(account_id, destination_id, occurrence_id, package_digest)
    elif platform == "youtube" and not _YOUTUBE_CHANNEL.fullmatch(account_id):
        raise ValueError("invalid YouTube channel ID")
    elif platform == "x" and not _X_ACCOUNT.fullmatch(account_id):
        raise ValueError("invalid X account ID")
    adapter_options_digest = _adapter_options_digest(
        platform, package, account_id, destination_id, occurrence_id, options,
    )
    kind = _KINDS[action]
    attachment = None
    if action == IMAGE_ALBUM_ACTION:
        if platform == "telegram":
            read_telegram_image_album(package_dir, package)
        else:
            read_discord_image_album(package_dir, package)
    else:
        attachment = read_standalone_attachment(package_dir, package, kind)
    if attachment is not None:
        size = len(attachment[1])
        if platform == "x" and kind == "image" and size > _X_MAX_IMAGE:
            raise ValueError("X post image exceeds the media limit")
        if platform == "linkedin":
            preview_initialize(kind=kind, owner=account_id, api_version=options["api_version"],
                               file_size=size if kind == "video" else None)
        if platform == "tiktok":
            preview_inbox_upload(video_size=size, chunk_size=min(size, 16 * 1024 * 1024))
    binding = {
        "schema": "social-v2-dispatch-intent/1",
        "platform": platform,
        "destination": destination,
        "action": action,
        "account_id": account_id,
        "destination_id": destination_id,
        "occurrence_id": occurrence_id,
        "package_digest": package_digest,
        "options": options,
    }
    return {
        "status": "blocked",
        "reason": "production_approval_generation_unavailable",
        "workflow": route[2],
        "binding": binding,
        "binding_digest": canonical_snapshot(binding)[1],
        "adapter_options_digest": adapter_options_digest,
    }


def _adapter_options_digest(
    platform: str, package: dict[str, Any], account_id: str, destination_id: str,
    occurrence_id: str, options: dict[str, Any],
) -> str | None:
    text = package["content"]["text"]
    comment = package["content"].get("first_comment")
    if platform == "facebook":
        _check_page(account_id, options["api_version"])
        validate_facebook_text(text)
        if comment is not None:
            if package["action"] == "post_video":
                raise ValueError("Facebook video delivery does not support a first comment")
            validate_facebook_text(comment)
    elif platform == "telegram":
        limit = _TELEGRAM_METHODS[package["action"]][3]
        if len(text.encode("utf-16-le")) // 2 > limit:
            raise ValueError("Telegram text exceeds the package limit")
    elif platform == "linkedin":
        preview_linkedin_post(author=account_id, text=text, api_version=options["api_version"])
        if comment is not None:
            preview_linkedin_post(author=account_id, text=comment, api_version=options["api_version"])
    elif platform == "x":
        preview_x_post(text=text)
    elif platform == "threads":
        request = preview_container(
            user_id=account_id, api_version=options["api_version"], media_type="TEXT", text=text,
        )["request"]
        if len(request["params"]["text"]) > 500:
            raise ValueError("Threads text exceeds 500 characters")
    elif platform == "youtube":
        metadata = preview_video(description=text, media_id="fixture-video", **options)["request"]["body"]
        return canonical_snapshot(metadata)[1]
    elif platform == "discord":
        preview_discord_message(channel_id=destination_id, text=text)
        return discord_target_digest(bot_id=account_id, channel_id=destination_id, guild_id=options["guild_id"])
    elif platform == "tiktok":
        return tiktok_inbox_options_digest(account_id=account_id, occurrence_id=occurrence_id)
    return None


def main() -> None:
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--package-digest", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--occurrence-id", required=True)
    parser.add_argument("--api-version")
    parser.add_argument("--guild-id")
    parser.add_argument("--title")
    parser.add_argument("--category-id")
    parser.add_argument("--privacy", choices=("private", "unlisted", "public"))
    parser.add_argument("--made-for-kids", action=argparse.BooleanOptionalAction, default=None)
    arguments = vars(parser.parse_args())
    option_names = set().union(*_OPTION_FIELDS.values())
    options = {name: arguments.pop(name) for name in option_names}
    try:
        intent = prepare_dispatch_intent(
            **arguments, options={name: value for name, value in options.items() if value is not None},
        )
    except (OSError, ValueError, RecursionError) as exc:
        reason = str(exc) if str(exc) in _BLOCKED_ROUTES.values() else "invalid_or_unsupported_dispatch_intent"
        parser.exit(2, f"Social V2 dispatch intent rejected ({reason}).\n")
    print(json.dumps(intent, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
