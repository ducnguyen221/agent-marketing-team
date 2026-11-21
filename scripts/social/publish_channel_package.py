"""Guarded JSON and multipart dispatch for LinkedIn, Discord and X packages."""
from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.discord import direct as discord
from scripts.social.channels.discord.readonly_auth import _valid_id as _valid_discord_id, check_bot_channel
from scripts.social.channels.linkedin import direct as linkedin
from scripts.social.channels.x import direct as x
from scripts.social.prepare_standalone import IMAGE_ALBUM_ACTION
from scripts.social.publish_facebook_package import _approved_attachment
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.standalone_delivery import (
    SCHEMA, read_delivery_manifest, read_discord_image_album, validate_standalone_target,
)

Transport = Callable[
    [str, Mapping[str, str], Mapping[str, Any], Mapping[str, tuple[str, bytes]]],
    tuple[int, list[tuple[str, str]], Mapping[str, Any]],
]
_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChannelApproval:
    platform: str
    account_id: str
    package_digest: str
    approval_ref: str
    options_digest: str = ""


@dataclass(frozen=True)
class MediaObservation:
    account_id: str
    file_sha256: str
    provider_id: str
    observation_ref: str


@dataclass(frozen=True)
class AccountObservation:
    """Caller-owned readback of an account using the same in-memory credential."""

    platform: str
    account_id: str
    credential_sha256: str
    observation_ref: str


def require_account_observation(
    observation: AccountObservation, platform: str, account_id: str, credential: str,
) -> None:
    if (
        observation.platform != platform or observation.account_id != account_id
        or not observation.observation_ref.strip()
        or not hmac.compare_digest(observation.credential_sha256, hashlib.sha256(credential.encode()).hexdigest())
    ):
        raise ValueError("credential does not match the verified account observation")


@dataclass(frozen=True)
class LinkedInPostObservation:
    author: str
    package_digest: str
    post_urn: str
    observation_ref: str


def approved_package(
    package_dir: Path, *, platform: str, account_id: str, credential: str,
    approval: ChannelApproval, enable_dispatch: bool, destination_id: str | None = None,
) -> dict[str, Any]:
    """Check a caller-owned approval binding before loading the requested package."""
    if enable_dispatch is not True:
        raise ValueError("channel dispatch is disabled")
    require_production_authority()
    if (
        approval.platform != platform or approval.account_id != account_id
        or not approval.approval_ref.strip() or not re.fullmatch(r"[!-~]+", credential)
    ):
        raise ValueError("invalid channel authorization")
    package = read_delivery_manifest(package_dir)
    if package.get("schema") == SCHEMA:
        validate_standalone_target(
            package_dir, package, platform=platform, account_id=account_id,
            destination_id=account_id if destination_id is None else destination_id,
            package_digest=approval.package_digest,
        )
        return package
    _, digest = canonical_snapshot(package)
    if (
        package.get("platform") != platform or package.get("schema") != "social-package/1"
        or package.get("status") != "prepared_for_review"
        or not hmac.compare_digest(digest, approval.package_digest)
    ):
        raise ValueError("approval does not match the channel package")
    return package


def observed_media(
    package_dir: Path, package: dict[str, Any], account_id: str, observation: MediaObservation | None,
) -> tuple[str | None, str | None]:
    """Bind a provider media identifier to the current package through caller readback."""
    kind = package.get("action", "").removeprefix("post_")
    if kind == "text":
        if observation is not None:
            raise ValueError("unexpected media observation")
        _approved_attachment(package_dir, package, None)
        return None, None
    if kind not in {"image", "video"} or observation is None:
        raise ValueError("image or video needs a provider media observation")
    _approved_attachment(package_dir, package, kind)
    if (
        observation.account_id != account_id or not observation.observation_ref.strip()
        or observation.file_sha256 != package["media"]["sha256"]
    ):
        raise ValueError("provider media observation does not match the package")
    return kind, observation.provider_id


def publish_linkedin_package(
    package_dir: Path, *, author: str, api_version: str, credential: str, approval: ChannelApproval,
    transport: Transport, account_observation: AccountObservation,
    media_observation: MediaObservation | None = None, enable_dispatch: bool = False,
) -> dict[str, str]:
    package = approved_package(package_dir, platform="linkedin", account_id=author, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    if package.get("schema") != SCHEMA:
        raise ValueError("LinkedIn adapter requires a target-bound standalone package")
    if not author.startswith("urn:li:person:"):
        raise ValueError("LinkedIn dispatch requires a verified member author")
    require_account_observation(account_observation, "linkedin", author, credential)
    kind, media_urn = observed_media(package_dir, package, author, media_observation)
    request = linkedin.preview_post(author=author, text=package["content"]["text"], api_version=api_version,
                                    media_kind=kind, media_urn=media_urn)["request"]
    headers = {**request["headers"], "Authorization": f"Bearer {credential}"}
    try:
        status, response_headers, _ = transport("https://api.linkedin.com" + request["path"], headers,
                                                request["body"], {})
        receipt = linkedin.interpret_create(status, response_headers)
        if receipt["state"] == "accepted":
            return {"status": "accepted_by_provider", "provider_id": receipt["post_urn"]}
    except Exception:
        return {"status": _UNKNOWN}
    return {"status": _UNKNOWN}


def publish_linkedin_first_comment(
    package_dir: Path, *, author: str, api_version: str, credential: str, approval: ChannelApproval,
    observation: LinkedInPostObservation, transport: Transport, account_observation: AccountObservation,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    package = approved_package(package_dir, platform="linkedin", account_id=author, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    if package.get("schema") != SCHEMA:
        raise ValueError("LinkedIn comment adapter requires a target-bound standalone package")
    if not author.startswith("urn:li:person:"):
        raise ValueError("LinkedIn dispatch requires a verified member author")
    require_account_observation(account_observation, "linkedin", author, credential)
    if (
        observation.author != author or observation.package_digest != approval.package_digest
        or not observation.observation_ref.strip() or not linkedin._POST.fullmatch(observation.post_urn)
    ):
        raise ValueError("verified LinkedIn post binding is required")
    comment = package["content"].get("first_comment")
    headers = linkedin.preview_post(author=author, text=comment, api_version=api_version)["request"]["headers"]
    headers["Authorization"] = f"Bearer {credential}"
    urn = observation.post_urn
    body = {"actor": author, "object": urn, "message": {"text": comment}}
    try:
        status, _, response = transport(
            f"https://api.linkedin.com/rest/socialActions/{quote(urn, safe='')}/comments", headers, body, {},
        )
        return _interpret_linkedin_comment(status, response, author=author, post_urn=urn, credential=credential)
    except Exception:
        return {"status": _UNKNOWN}


def _interpret_linkedin_comment(
    status: int, response: Mapping[str, Any], *, author: str, post_urn: str, credential: str,
) -> dict[str, str]:
    if (
        status == 201 and not {"error", "errors", "serviceErrorCode"} & response.keys()
        and response.get("actor") == author and response.get("object") == post_urn
    ):
        comment_id = response.get("id")
        if isinstance(comment_id, str) and _ID.fullmatch(comment_id) and comment_id != credential:
            return {"status": "accepted_by_provider", "provider_id": comment_id}
    return {"status": _UNKNOWN}


def publish_x_package(
    package_dir: Path, *, account_id: str, credential: str, approval: ChannelApproval,
    transport: Transport, account_observation: AccountObservation,
    media_observation: MediaObservation | None = None, enable_dispatch: bool = False,
) -> dict[str, str]:
    if not _ID.fullmatch(account_id):
        raise ValueError("invalid X account ID")
    package = approved_package(package_dir, platform="x", account_id=account_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    if package.get("schema") != SCHEMA:
        raise ValueError("X campaign dispatch requires the campaign workflow")
    path, body = _prepare_x_create(
        package_dir, package=package, account_id=account_id, credential=credential,
        account_observation=account_observation, media_observation=media_observation,
    )
    try:
        status, _, response = transport("https://api.x.com" + path,
                                        {"Authorization": f"Bearer {credential}"}, body, {})
        return _interpret_x_create(status, response, credential)
    except Exception:
        return {"status": _UNKNOWN}


def _prepare_x_create(
    package_dir: Path, *, package: dict[str, Any], account_id: str, credential: str,
    account_observation: AccountObservation, media_observation: MediaObservation | None,
) -> tuple[str, dict[str, Any]]:
    require_account_observation(account_observation, "x", account_id, credential)
    _, media_id = observed_media(package_dir, package, account_id, media_observation)
    request = x.preview_post(text=package["content"]["text"])["request"]
    body = request["body"]
    if media_id is not None:
        if not _ID.fullmatch(media_id):
            raise ValueError("invalid X media ID")
        body["media"] = {"media_ids": [media_id]}
    return request["path"], body


def _interpret_x_create(status: int, response: Mapping[str, Any], credential: str) -> dict[str, str]:
    post = response.get("data")
    if status == 201 and isinstance(post, Mapping) and not response.get("errors"):
        provider_id = post.get("id")
        if isinstance(provider_id, str) and _ID.fullmatch(provider_id) and provider_id != credential:
            return {"status": "accepted_by_provider", "provider_id": provider_id}
    return {"status": _UNKNOWN}


def discord_target_digest(*, bot_id: str, channel_id: str, guild_id: str) -> str:
    """Fingerprint the target to be included in a Discord package approval."""
    if not all(_valid_discord_id(value) for value in (bot_id, channel_id, guild_id)):
        raise ValueError("invalid Discord target")
    return canonical_snapshot({"platform": "discord", "bot_id": bot_id,
                               "channel_id": channel_id, "guild_id": guild_id})[1]


def publish_discord_package(
    package_dir: Path, *, channel_id: str, credential: str, approval: ChannelApproval,
    transport: Transport, enable_dispatch: bool = False, guild_id: str = "",
) -> dict[str, str]:
    return _publish_discord_package(
        package_dir, channel_id=channel_id, credential=credential, approval=approval,
        transport=transport, enable_dispatch=enable_dispatch, guild_id=guild_id,
    )


def _publish_discord_package(
    package_dir: Path, *, channel_id: str, credential: str, approval: ChannelApproval,
    transport: Transport, enable_dispatch: bool, guild_id: str,
    before_campaign_send: Callable[[], None] | None = None,
) -> dict[str, str]:
    bot_id = approval.account_id
    package = approved_package(package_dir, platform="discord", account_id=bot_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch, destination_id=channel_id)
    if (package["schema"] == SCHEMA) != (before_campaign_send is None):
        raise ValueError("Discord campaign dispatch requires the campaign workflow")
    target_digest = discord_target_digest(bot_id=bot_id, channel_id=channel_id, guild_id=guild_id)
    if not hmac.compare_digest(approval.options_digest, target_digest):
        raise ValueError("approval does not match the Discord bot and guild channel")
    is_album = package["action"] == IMAGE_ALBUM_ACTION
    if is_album:
        attachments = read_discord_image_album(package_dir, package)
    else:
        kind = package.get("action", "").removeprefix("post_")
        if kind not in {"text", "image", "video", "document"}:
            raise ValueError("unsupported Discord package type")
        attachment = _approved_attachment(package_dir, package, None if kind == "text" else kind)
        attachments = [] if attachment is None else [attachment]
    request = discord.preview_message(channel_id=channel_id, text=package["content"]["text"])["request"]
    body = request["body"]
    files = {f"files[{index}]": attachment for index, attachment in enumerate(attachments)}
    if attachments:
        body["attachments"] = [
            {"id": index, "filename": filename} for index, (filename, _) in enumerate(attachments)
        ]
    observation = check_bot_channel(credential, expected_bot_id=bot_id, channel_id=channel_id, guild_id=guild_id)
    if observation["identity"] != "match" or observation["channel_access_verified"] is not True:
        raise ValueError("Discord dispatch requires a verified bot and channel binding")
    if before_campaign_send is not None:
        before_campaign_send()
    try:
        status, _, message = transport("https://discord.com" + request["path"],
                                       {"Authorization": f"Bot {credential}"}, body, files)
        response_attachments = message.get("attachments")
        if (
            status in {200, 201} and message["channel_id"] == channel_id and _valid_discord_id(message["id"])
            and message["author"]["id"] == bot_id and message["author"].get("bot") is True
            and message["content"] == body["content"]
            and isinstance(response_attachments, list)
            and [item["filename"] for item in response_attachments] == [name for name, _ in attachments]
            and (not is_album or (
                all(
                    _valid_discord_id(item.get("id")) and type(item.get("size")) is int
                    and item["size"] == len(binary)
                    for item, (_, binary) in zip(response_attachments, attachments)
                )
                and len({item["id"] for item in response_attachments}) == len(attachments)
            ))
        ):
            return {"status": "accepted_by_provider", "provider_id": message["id"]}
    except Exception:
        return {"status": _UNKNOWN}
    return {"status": _UNKNOWN}
