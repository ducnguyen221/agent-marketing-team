"""Guarded YouTube upload and TikTok Inbox upload using injected transports."""
from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.tiktok import direct as tiktok
from scripts.social.channels.youtube import direct as youtube
from scripts.social.publish_channel_package import (
    AccountObservation, ChannelApproval, Transport, approved_package, require_account_observation,
)
from scripts.social.publish_facebook_package import _approved_attachment
from scripts.social.standalone_delivery import SCHEMA

ChunkTransport = Callable[[str, Mapping[str, str], bytes], int]
# TikTok Inbox initialization response limits the identifier to 64 characters.
_MAX_TIKTOK_PUBLISH_ID_LENGTH = 64


def _valid_tiktok_publish_id(value: Any) -> bool:
    return (
        isinstance(value, str) and 1 <= len(value) <= _MAX_TIKTOK_PUBLISH_ID_LENGTH
        and bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))
    )


def publish_youtube_package(
    package_dir: Path, *, channel_id: str, credential: str, approval: ChannelApproval,
    title: str, category_id: str, privacy: str, made_for_kids: bool, transport: Transport,
    account_observation: AccountObservation,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Send videos.insert using a transport that encodes a multipart/related body."""
    request = _prepare_youtube_upload(
        package_dir, channel_id=channel_id, credential=credential, approval=approval,
        title=title, category_id=category_id, privacy=privacy, made_for_kids=made_for_kids,
        account_observation=account_observation, enable_dispatch=enable_dispatch, expected_schema=SCHEMA,
    )
    try:
        status, _, response = transport(*request)
    except Exception:
        return {"status": "unknown"}
    return _youtube_upload_result(status, response, channel_id=channel_id, credential=credential)


def _prepare_youtube_upload(
    package_dir: Path, *, channel_id: str, credential: str, approval: ChannelApproval,
    title: str, category_id: str, privacy: str, made_for_kids: bool,
    account_observation: AccountObservation, enable_dispatch: bool, expected_schema: str,
) -> tuple[str, dict[str, str], dict[str, Any], dict[str, tuple[str, bytes]]]:
    """Build the guarded request and load its approved bytes without sending it."""
    if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
        raise ValueError("invalid YouTube channel ID")
    package = approved_package(package_dir, platform="youtube", account_id=channel_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    if package["schema"] != expected_schema:
        raise ValueError("YouTube campaign dispatch requires the campaign workflow")
    require_account_observation(account_observation, "youtube", channel_id, credential)
    if package.get("action") != "post_video":
        raise ValueError("YouTube requires a video package")
    attachment = _approved_attachment(package_dir, package, "video")
    request = youtube.preview_video(title=title, description=package["content"]["text"], category_id=category_id,
                                    privacy=privacy, made_for_kids=made_for_kids, media_id="fixture-video")["request"]
    if not hmac.compare_digest(approval.options_digest, canonical_snapshot(request["body"])[1]):
        raise ValueError("approval does not match YouTube metadata")
    params = {**request["params"], "uploadType": "multipart", "notifySubscribers": "false"}
    url = f'https://{request["host"]}{request["path"]}?{urlencode(params)}'
    return url, {"Authorization": f"Bearer {credential}"}, request["body"], {"video": attachment}


def _youtube_upload_result(
    status: int, response: Mapping[str, Any], *, channel_id: str, credential: str,
) -> dict[str, str]:
    try:
        video_id = response.get("id")
        if (
            status in {200, 201} and isinstance(video_id, str) and video_id != credential
            and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
            and response["snippet"]["channelId"] == channel_id
        ):
            return {"status": "accepted_by_provider", "provider_id": video_id}
    except Exception:
        return {"status": "unknown"}
    return {"status": "unknown"}


def upload_tiktok_inbox_package(
    package_dir: Path, *, account_id: str, credential: str, approval: ChannelApproval,
    upload_host: str, transport: Transport, put_chunk: ChunkTransport,
    account_observation: AccountObservation, enable_dispatch: bool = False,
) -> dict[str, str]:
    """Transfer approved standalone bytes to TikTok Inbox using injected transports."""
    package = approved_package(package_dir, platform="tiktok", account_id=account_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    if package["schema"] != SCHEMA:
        raise ValueError("TikTok campaign dispatch requires the campaign workflow")
    require_account_observation(account_observation, "tiktok", account_id, credential)
    data, plan = _prepare_tiktok_attachment(package_dir, package)
    request = plan["request"]
    publish_id = None
    try:
        status, _, response = transport(
            "https://open.tiktokapis.com" + request["path"], {"Authorization": f"Bearer {credential}"},
            request["body"], {},
        )
        if status != 200 or "errors" in response or response["error"]["code"] != "ok":
            return {"status": "unknown"}
        candidate_id = response["data"]["publish_id"]
        upload_url = response["data"]["upload_url"]
        if not _valid_tiktok_publish_id(candidate_id) or candidate_id in (credential, upload_url):
            return {"status": "unknown"}
        publish_id = candidate_id
        endpoint = urlsplit(upload_url)
        if (
            endpoint.scheme != "https" or endpoint.hostname != upload_host or endpoint.port not in {None, 443}
            or endpoint.username is not None or endpoint.password is not None or endpoint.fragment
            or not upload_host.endswith(".tiktokapis.com")
        ):
            return {"status": "unknown", "provider_id": publish_id}
        for headers, chunk, expected in _tiktok_chunks(data, plan):
            if put_chunk(upload_url, headers, chunk) != expected:
                return {"status": "unknown", "provider_id": publish_id}
        return {"status": "upload_accepted_by_provider", "provider_id": publish_id}
    except Exception:
        return {"status": "unknown", **({"provider_id": publish_id} if publish_id is not None else {})}


def _prepare_tiktok_attachment(
    package_dir: Path, package: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Load and verify exact upload bytes and build their request without sending."""
    if package.get("action") != "upload_video":
        raise ValueError("TikTok Inbox requires an upload package")
    _, data = _approved_attachment(package_dir, package, "video")
    plan = tiktok.preview_inbox_upload(video_size=len(data), chunk_size=min(len(data), 16 * 1024 * 1024))
    return data, plan


def _tiktok_chunks(data: bytes, plan: Mapping[str, Any]) -> Iterator[tuple[dict[str, str], bytes, int]]:
    for index, chunk in enumerate(plan["chunks"]):
        start, end = chunk["start"], chunk["end"]
        headers = {"Content-Type": "video/mp4", "Content-Length": str(chunk["length"]),
                   "Content-Range": f"bytes {start}-{end}/{len(data)}"}
        expected = 201 if index + 1 == len(plan["chunks"]) else 206
        yield headers, data[start:end + 1], expected
