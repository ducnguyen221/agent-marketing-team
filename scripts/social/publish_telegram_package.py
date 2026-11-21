"""Dispatch one approved V2 Telegram channel package through an injected transport."""
from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.prepare_standalone import TELEGRAM_ALBUM_ACTION, TELEGRAM_CAPTION_LIMIT
from scripts.social.publish_channel_package import AccountObservation, require_account_observation
from scripts.social.publish_facebook_package import PackageTransport, _approved_attachment
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.standalone_delivery import (
    SCHEMA, read_delivery_manifest, read_telegram_image_album, validate_standalone_target,
)

_CHANNEL = re.compile(r"-100[0-9]{5,20}\Z")
_TOKEN = re.compile(r"[0-9]{1,20}:[A-Za-z0-9_-]{20,128}\Z")
_ERROR_FIELDS = {"error", "errors", "error_code", "description", "parameters"}
_MESSAGE_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_METHODS = {
    "post_text": ("sendMessage", "text", None, 4096),
    "post_image": ("sendPhoto", "caption", "image", 1024),
    TELEGRAM_ALBUM_ACTION: ("sendMediaGroup", "caption", "image_album", TELEGRAM_CAPTION_LIMIT),
    "post_video": ("sendVideo", "caption", "video", 1024),
    "post_document": ("sendDocument", "caption", "document", 1024),
}


@dataclass(frozen=True)
class TelegramPackageApproval:
    """A caller-provided approval bound to a bot, channel, and package."""

    channel_id: str
    bot_id: str
    package_digest: str
    approval_ref: str


def _has_file_id(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    file_id = value.get("file_id")
    return isinstance(file_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", file_id))


def _matches_media(field: str | None, value: Any) -> bool:
    if field is None:
        return True
    if field == "photo":
        return isinstance(value, list) and bool(value) and all(_has_file_id(item) for item in value)
    return _has_file_id(value)


def _album_result(
    result: Any, *, channel_id: str, captions: list[str],
) -> dict[str, Any]:
    if not isinstance(result, list) or len(result) != len(captions):
        return {"status": "unknown"}
    message_ids = []
    group_id = None
    for index, message in enumerate(result):
        if not isinstance(message, dict):
            return {"status": "unknown"}
        chat, message_id = message.get("chat"), message.get("message_id")
        album_id = message.get("media_group_id")
        if (
            not isinstance(chat, dict) or chat.get("type") != "channel"
            or type(chat.get("id")) is not int or str(chat["id"]) != channel_id
            or type(message_id) is not int or not _MESSAGE_ID.fullmatch(str(message_id))
            or not isinstance(album_id, str) or not re.fullmatch(r"[!-~]{1,128}", album_id)
            or (group_id is not None and album_id != group_id)
            or message.get("caption", "") != captions[index]
            or not _matches_media("photo", message.get("photo"))
        ):
            return {"status": "unknown"}
        group_id = album_id
        message_ids.append(str(message_id))
    if len(set(message_ids)) != len(captions):
        return {"status": "unknown"}
    return {"status": "accepted_by_provider", "provider_id": message_ids[0],
            "media_group_id": group_id, "message_ids": message_ids}


def publish_telegram_package(
    package_dir: Path, *, channel_id: str, bot_token: str, approval: TelegramPackageApproval,
    transport: PackageTransport, account_observation: AccountObservation, enable_dispatch: bool = False,
) -> dict[str, Any]:
    """Post a V2 package once through a transport that redacts the credential URL."""
    return _publish_telegram_package(
        package_dir, channel_id=channel_id, bot_token=bot_token, approval=approval,
        transport=transport, account_observation=account_observation, enable_dispatch=enable_dispatch,
    )


def _publish_telegram_package(
    package_dir: Path, *, channel_id: str, bot_token: str, approval: TelegramPackageApproval,
    transport: PackageTransport, account_observation: AccountObservation, enable_dispatch: bool,
    before_campaign_send: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if enable_dispatch is not True:
        raise ValueError("Telegram package dispatch is disabled")
    require_production_authority()
    if (
        not _CHANNEL.fullmatch(channel_id)
        or not _TOKEN.fullmatch(bot_token)
        or approval.channel_id != channel_id
        or approval.bot_id != bot_token.partition(":")[0]
        or not approval.approval_ref.strip()
    ):
        raise ValueError("approval or credential is invalid")
    require_account_observation(account_observation, "telegram", approval.bot_id, bot_token)
    package = read_delivery_manifest(package_dir)
    schema = package.get("schema")
    if schema == SCHEMA:
        if before_campaign_send is not None:
            raise ValueError("Telegram campaign package changed before dispatch")
        validate_standalone_target(
            package_dir, package, platform="telegram", account_id=approval.bot_id,
            destination_id=channel_id, package_digest=approval.package_digest,
        )
    elif (
        schema != "social-package/1" or before_campaign_send is None
        or not hmac.compare_digest(approval.package_digest, canonical_snapshot(package)[1])
    ):
        raise ValueError("invalid Telegram package or approval")
    action = package.get("action")
    if (
        package.get("status") != "prepared_for_review"
        or package.get("platform") != "telegram"
        or package.get("destination") != "channel"
        or not isinstance(action, str)
        or action not in _METHODS
        or not isinstance(package.get("content"), dict)
    ):
        raise ValueError("invalid Telegram package or approval")
    method, text_field, kind, limit = _METHODS[action]
    text = package["content"].get("text")
    captionless = (schema == SCHEMA and kind is not None or action == TELEGRAM_ALBUM_ACTION) and text == ""
    if (
        not isinstance(text, str) or (not captionless and not text.strip())
        or len(text.encode("utf-16-le")) // 2 > limit
    ):
        raise ValueError("Telegram text is missing or exceeds the package limit")
    fields = {"chat_id": channel_id}
    if action == TELEGRAM_ALBUM_ACTION:
        photos, captions = read_telegram_image_album(package_dir, package)
        files = {f"photo_{index}": photo for index, photo in enumerate(photos, start=1)}
        media = [
            {"type": "photo", "media": f"attach://{field}", **({"caption": caption} if caption else {})}
            for field, caption in zip(files, captions)
        ]
        fields["media"] = json.dumps(media, ensure_ascii=False)
    else:
        if not captionless:
            fields[text_field] = text
        attachment = _approved_attachment(package_dir, package, kind)
        file_field = "photo" if kind == "image" else kind
        files = {file_field: attachment} if file_field and attachment is not None else {}
    if before_campaign_send is not None:
        before_campaign_send()
    try:
        code, response = transport(f"https://api.telegram.org/bot{bot_token}/{method}", {}, fields, files)
        if 200 <= code < 300 and response.get("ok") is True and not _ERROR_FIELDS & response.keys():
            result = response["result"]
            if action == TELEGRAM_ALBUM_ACTION:
                return _album_result(result, channel_id=channel_id, captions=captions)
            message_id = result["message_id"]
            chat = result["chat"]
            if (
                type(message_id) is int and _MESSAGE_ID.fullmatch(str(message_id))
                and chat["type"] == "channel" and type(chat["id"]) is int and str(chat["id"]) == channel_id
                and result.get(text_field, "") == text
                and _matches_media(file_field, result.get(file_field) if file_field else None)
            ):
                return {"status": "accepted_by_provider", "provider_id": str(message_id)}
    except Exception:
        # The transport may have sent the request, and exceptions can contain its credential URL.
        return {"status": "unknown"}
    return {"status": "unknown"}
