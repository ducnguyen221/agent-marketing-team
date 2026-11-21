"""Dispatch one approved V2 Facebook Page package through an injected transport."""
from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.facebook.direct import _check_page, _text
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.standalone_delivery import (
    SCHEMA, read_delivery_manifest, read_standalone_attachment, validate_standalone_target,
)

# Other V2 adapters still import the package attachment reader by this name.
_approved_attachment = read_standalone_attachment

if TYPE_CHECKING:
    from scripts.social.publish_channel_package import AccountObservation


_ACTIONS = {
    "post_text": ("feed", "message", None),
    "post_image": ("photos", "caption", "image"),
    "post_video": ("videos", "description", "video"),
}
_POST_ID = re.compile(r"[1-9][0-9]{0,31}(?:_[1-9][0-9]{0,31}){0,2}\Z")
_Attachment = tuple[str, bytes]
PackageTransport = Callable[
    [str, Mapping[str, str], Mapping[str, str], Mapping[str, _Attachment]],
    tuple[int, Mapping[str, Any]],
]


@dataclass(frozen=True)
class FacebookPackageApproval:
    """A caller-provided approval already recorded by the owning workflow."""

    page_id: str
    api_version: str
    package_digest: str
    approval_ref: str


@dataclass(frozen=True)
class FacebookPostObservation:
    """Caller-owned readback binding verified by the integrated workflow."""

    page_id: str
    package_digest: str
    post_id: str
    observation_ref: str


def _approved_package(package_dir: Path, page_id: str, api_version: str,
                      page_access_token: str, approval: FacebookPackageApproval) -> dict[str, Any]:
    _check_page(page_id, api_version)
    if (
        approval.page_id != page_id
        or approval.api_version != api_version
        or not approval.approval_ref.strip()
        or not page_access_token
        or not page_access_token.isascii()
        or any(ord(char) <= 32 or ord(char) >= 127 for char in page_access_token)
    ):
        raise ValueError("approval or credential is invalid")
    package = read_delivery_manifest(package_dir)
    if package.get("schema") == SCHEMA:
        validate_standalone_target(
            package_dir, package, platform="facebook", account_id=page_id,
            destination_id=page_id, package_digest=approval.package_digest,
        )
        return package
    _, package_digest = canonical_snapshot(package)
    if not hmac.compare_digest(approval.package_digest, package_digest):
        raise ValueError("approval does not match the package")
    action = package.get("action")
    if (
        package.get("schema") != "social-package/1"
        or package.get("status") != "prepared_for_review"
        or package.get("platform") != "facebook"
        or package.get("destination") != "page"
        or not isinstance(action, str)
        or action not in _ACTIONS
        or not isinstance(package.get("content"), dict)
    ):
        raise ValueError("invalid Facebook package")
    return package


def _submit(transport: PackageTransport, url: str, access_token: str, fields: dict[str, str],
            files: dict[str, _Attachment], *, operation: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        status, response = transport(url, headers, fields, files)
        post_id = response.get("id")
        if (
            200 <= status < 300
            and not {"error", "errors"} & response.keys()
            and isinstance(post_id, str)
            and _POST_ID.fullmatch(post_id)
            and post_id != access_token
        ):
            receipt = {"status": "accepted_by_provider", "provider_id": post_id}
            if operation == "photos":
                receipt["photo_id"] = post_id
                page_post_id = response.get("post_id")
                if page_post_id == access_token:
                    return {"status": "unknown"}
                if isinstance(page_post_id, str) and _POST_ID.fullmatch(page_post_id):
                    receipt["post_id"] = page_post_id
            return receipt
    except Exception:
        # The injected transport may fail after acceptance. Its exception can
        # carry credentials, and replay could create another post.
        return {"status": "unknown"}
    return {"status": "unknown"}


def publish_facebook_package(
    package_dir: Path,
    *,
    page_id: str,
    api_version: str,
    page_access_token: str,
    approval: FacebookPackageApproval,
    transport: PackageTransport,
    account_observation: AccountObservation,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Submit a standalone package with approval and account verification."""
    return _publish_facebook_package(
        package_dir, page_id=page_id, api_version=api_version, page_access_token=page_access_token,
        approval=approval, transport=transport, account_observation=account_observation,
        enable_dispatch=enable_dispatch,
    )


def _publish_facebook_package(
    package_dir: Path, *, page_id: str, api_version: str, page_access_token: str,
    approval: FacebookPackageApproval, transport: PackageTransport,
    account_observation: AccountObservation, enable_dispatch: bool,
    before_campaign_send: Callable[[], None] | None = None,
) -> dict[str, str]:
    """Submit once with no redirects or transport retries.

    Transport must send a POST to the supplied URL, infer multipart for files,
    and disable retries and redirects. The transport owns token redaction.
    Reconcile any unknown result before making another request.
    """
    if enable_dispatch is not True:
        raise ValueError("Facebook package dispatch is disabled")
    require_production_authority()
    from scripts.social.publish_channel_package import require_account_observation

    require_account_observation(account_observation, "facebook", page_id, page_access_token)
    package = _approved_package(package_dir, page_id, api_version, page_access_token, approval)
    operation, text_field, kind = _ACTIONS[package["action"]]
    fields = {text_field: _text(package["content"].get("text"))}
    attachment = read_standalone_attachment(package_dir, package, kind)
    files = {"source": attachment} if attachment is not None else {}

    host = "graph-video.facebook.com" if kind == "video" else "graph.facebook.com"
    url = f"https://{host}/{api_version}/{page_id}/{operation}"
    _check_campaign_dispatch(package, before_campaign_send)
    return _submit(transport, url, page_access_token, fields, files, operation=operation)


def _check_campaign_dispatch(package: dict[str, Any], before_send: Callable[[], None] | None) -> None:
    if package["schema"] == SCHEMA:
        if before_send is not None:
            raise ValueError("Facebook campaign context requires a campaign package")
    elif before_send is None:
        raise ValueError("Facebook campaign dispatch requires the campaign workflow")
    else:
        before_send()


def publish_facebook_first_comment(
    package_dir: Path, *, page_id: str, api_version: str, page_access_token: str,
    approval: FacebookPackageApproval, transport: PackageTransport,
    observation: FacebookPostObservation, account_observation: AccountObservation,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Submit the approved standalone comment for a verified Page post."""
    return _publish_facebook_first_comment(
        package_dir, page_id=page_id, api_version=api_version, page_access_token=page_access_token,
        approval=approval, transport=transport, observation=observation, account_observation=account_observation,
        enable_dispatch=enable_dispatch,
    )


def _publish_facebook_first_comment(
    package_dir: Path, *, page_id: str, api_version: str, page_access_token: str,
    approval: FacebookPackageApproval, transport: PackageTransport,
    observation: FacebookPostObservation, account_observation: AccountObservation, enable_dispatch: bool,
    before_campaign_send: Callable[[], None] | None = None,
) -> dict[str, str]:
    if enable_dispatch is not True:
        raise ValueError("Facebook comment dispatch is disabled")
    require_production_authority()
    from scripts.social.publish_channel_package import require_account_observation

    require_account_observation(account_observation, "facebook", page_id, page_access_token)
    package = _approved_package(package_dir, page_id, api_version, page_access_token, approval)
    if (
        observation.page_id != page_id or observation.package_digest != approval.package_digest
        or not observation.observation_ref.strip()
        or not re.fullmatch(re.escape(page_id) + r"_[1-9][0-9]{0,31}", observation.post_id)
    ):
        raise ValueError("a verified Page post ID is required")
    fields = {"message": _text(package["content"].get("first_comment"))}
    url = f"https://graph.facebook.com/{api_version}/{observation.post_id}/comments"
    _check_campaign_dispatch(package, before_campaign_send)
    return _submit(transport, url, page_access_token, fields, {}, operation="comments")
