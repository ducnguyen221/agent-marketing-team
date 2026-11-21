"""Two-phase Threads and Instagram dispatch using caller-owned media bindings."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.social.channels.instagram import direct as instagram
from scripts.social.channels.threads import direct as threads
from scripts.social.publish_channel_package import (
    AccountObservation, ChannelApproval, MediaObservation, Transport, approved_package, observed_media,
    require_account_observation,
)
from scripts.social.standalone_delivery import SCHEMA

_PROVIDERS = {
    "instagram": (instagram, "graph.facebook.com"),
    "threads": (threads, "graph.threads.com"),
}
_ID = re.compile(r"[1-9][0-9]{0,31}\Z")


@dataclass(frozen=True)
class MetaContainerObservation:
    platform: str
    account_id: str
    package_digest: str
    container_id: str
    readiness: str
    observation_ref: str


def _send(transport: Transport, host: str, credential: str, request: dict[str, Any],
          result_field: str) -> dict[str, str]:
    try:
        status, _, body = transport(
            f"https://{host}" + request["path"], {"Authorization": f"Bearer {credential}"},
            request["params"], {},
        )
        identifier = body.get("id")
        if (
            200 <= status < 300 and isinstance(identifier, str) and _ID.fullmatch(identifier)
            and "error" not in body and "errors" not in body
        ):
            return {"status": result_field, "provider_id": identifier}
    except Exception:
        return {"status": "unknown"}
    return {"status": "unknown"}


def _require_supported_standalone(package: dict[str, Any]) -> None:
    if package.get("schema") != SCHEMA:
        return
    if package.get("action") in {"post_image", "post_video"}:
        raise ValueError("standalone Meta media requires verified immutable hosting")
    if package.get("platform") != "threads" or package.get("action") != "post_text":
        raise ValueError("unsupported standalone Meta action")


def create_meta_package_container(
    package_dir: Path, *, platform: str, account_id: str, api_version: str, credential: str,
    approval: ChannelApproval, transport: Transport, account_observation: AccountObservation,
    media: MediaObservation | None = None,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Create a container only. For media, the observation's provider ID is a hosted URL."""
    if platform not in _PROVIDERS:
        raise ValueError("unsupported Meta platform")
    provider, host = _PROVIDERS[platform]
    package = approved_package(package_dir, platform=platform, account_id=account_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    _require_supported_standalone(package)
    require_account_observation(account_observation, platform, account_id, credential)
    kind, media_url = observed_media(package_dir, package, account_id, media)
    text = package["content"]["text"]
    if platform == "threads":
        request = provider.preview_container(user_id=account_id, api_version=api_version,
                                             media_type=(kind or "text").upper(), text=text, media_url=media_url)
    else:
        if kind not in {"image", "video"}:
            raise ValueError("Instagram requires an image or Reel")
        request = provider.preview_container(user_id=account_id, api_version=api_version,
                                             media_type="IMAGE" if kind == "image" else "REELS",
                                             caption=text, media_url=media_url)
    return _send(transport, host, credential, request["request"], "container_accepted_by_provider")


def publish_meta_package_container(
    package_dir: Path, *, platform: str, account_id: str, api_version: str, credential: str,
    approval: ChannelApproval, transport: Transport, observation: MetaContainerObservation,
    account_observation: AccountObservation,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Publish a container independently read back as ready for this package."""
    if platform not in _PROVIDERS:
        raise ValueError("unsupported Meta platform")
    provider, host = _PROVIDERS[platform]
    package = approved_package(package_dir, platform=platform, account_id=account_id, credential=credential,
                               approval=approval, enable_dispatch=enable_dispatch)
    _require_supported_standalone(package)
    require_account_observation(account_observation, platform, account_id, credential)
    if (
        observation.platform != platform or observation.account_id != account_id
        or observation.package_digest != approval.package_digest or observation.readiness != "FINISHED"
        or not observation.observation_ref.strip()
    ):
        raise ValueError("verified Meta container readiness is required")
    request = provider.preview_publish(user_id=account_id, api_version=api_version,
                                       creation_id=observation.container_id)["request"]
    return _send(transport, host, credential, request, "accepted_by_provider")
