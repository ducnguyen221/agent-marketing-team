"""Prepare and transfer the approved bytes of a LinkedIn media package."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.linkedin.direct import _MEDIA
from scripts.social.channels.linkedin.media import inspect_media, preview_initialize, video_ranges
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import (
    GuardedPackageTransport, _linkedin_upload_url, _post, _put_linkedin_upload, _request, _response_object,
)
from scripts.social.standalone_delivery import (
    SCHEMA, read_delivery_manifest, read_standalone_attachment, validate_standalone_target,
)

_LINKEDIN_MEDIA_ACTIONS = {"post_image": "image", "post_video": "video"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LINKEDIN_API = "https://api.linkedin.com"
_LINKEDIN_PART_ID = re.compile(r"(?:[A-Za-z0-9_-]{1,128}|/ambry-video(?:ei)?/signedId/[A-Za-z0-9_-]{1,1024}\.bin)")


@dataclass(frozen=True)
class PreparedLinkedInMedia:
    """Package binding and the verified bytes for one future upload attempt."""

    package_digest: str
    file_sha256: str
    kind: str
    filename: str
    data: bytes = field(repr=False)
    initialize_preview: dict[str, Any] = field(repr=False)
    author: str = ""


def prepare_linkedin_package_media(
    package_dir: Path, *, package_digest: str, author: str, api_version: str,
    require_standalone_target: bool = False,
) -> PreparedLinkedInMedia:
    """Check one local media package and build its offline initialize candidate.

    The supplied digest binds the file to a specific package revision. It
    confers no approval or authority. No provider media ID is produced.
    """
    if not isinstance(package_digest, str) or not _SHA256.fullmatch(package_digest):
        raise ValueError("invalid package digest")
    package = read_delivery_manifest(package_dir)
    schema = package.get("schema")
    if require_standalone_target and schema != SCHEMA:
        raise ValueError("LinkedIn media upload requires a target-bound standalone package")
    if schema == SCHEMA:
        validate_standalone_target(
            package_dir, package, platform="linkedin", account_id=author,
            destination_id=author, package_digest=package_digest,
        )
    action = package.get("action")
    if (
        schema not in (SCHEMA, "social-package/1")
        or package.get("status") != "prepared_for_review"
        or package.get("platform") != "linkedin"
        or package.get("destination") != "account"
        or not isinstance(action, str)
        or action not in _LINKEDIN_MEDIA_ACTIONS
    ):
        raise ValueError("invalid LinkedIn media package")

    _, digest = canonical_snapshot(package)
    if not hmac.compare_digest(digest, package_digest):
        raise ValueError("digest does not match the LinkedIn media package")

    kind = _LINKEDIN_MEDIA_ACTIONS[action]
    attachment = read_standalone_attachment(package_dir, package, kind)
    if attachment is None or not attachment[1]:
        raise ValueError("LinkedIn media attachment is empty")
    filename, data = attachment
    initialize_preview = preview_initialize(
        kind=kind, owner=author, api_version=api_version,
        file_size=len(data) if kind == "video" else None,
    )
    return PreparedLinkedInMedia(
        package_digest=digest,
        file_sha256=package["media"]["sha256"],
        kind=kind,
        filename=filename,
        data=data,
        initialize_preview=initialize_preview,
        author=author,
    )


@dataclass(frozen=True, eq=False)
class LinkedInVideoPart:
    """A read-only view of the package bytes for one inclusive provider range."""

    index: int
    start: int
    end: int
    sha256: str
    data: memoryview = field(repr=False)


@dataclass(frozen=True, eq=False)
class LinkedInVideoParts:
    package_digest: str
    owner: str
    video_urn: str
    parts: tuple[LinkedInVideoPart, ...]


def prepare_linkedin_video_parts(
    media: PreparedLinkedInMedia, *, owner: str, video_urn: str, instructions: list[dict[str, int]],
) -> LinkedInVideoParts:
    """Bind sanitized initialization ranges to the exact bytes. No network authority."""
    if (
        media.kind != "video" or not media.author or owner != media.author
        or not isinstance(video_urn, str) or not _MEDIA["video"].fullmatch(video_urn)
        or type(media.data) is not bytes or hashlib.sha256(media.data).hexdigest() != media.file_sha256
    ):
        raise ValueError("invalid LinkedIn video package binding")
    source = memoryview(media.data)
    parts = []
    for item in video_ranges(file_size=len(source), instructions=instructions):
        data = source[item["start"]:item["end"] + 1]
        parts.append(LinkedInVideoPart(item["index"], item["start"], item["end"],
                                       hashlib.sha256(data).hexdigest(), data))
    return LinkedInVideoParts(media.package_digest, owner, video_urn, tuple(parts))


def linkedin_finalize_part_ids(
    upload: LinkedInVideoParts, *, owner: str, video_urn: str,
    completed: list[tuple[LinkedInVideoPart, str]],
) -> list[str]:
    """Order caller-supplied PUT ETags for this in-memory session only."""
    if owner != upload.owner or video_urn != upload.video_urn or not upload.parts or len(completed) != len(upload.parts):
        raise ValueError("incomplete or mismatched LinkedIn video upload")
    identifiers = {}
    for part, etag in completed:
        if (
            not isinstance(part, LinkedInVideoPart) or not 0 <= part.index < len(upload.parts)
            or upload.parts[part.index] is not part or part.index in identifiers
            or not isinstance(etag, str)
        ):
            raise ValueError("invalid LinkedIn video part receipt")
        if len(etag) >= 2 and etag[0] == etag[-1] == '"':
            etag = etag[1:-1]
        if not _LINKEDIN_PART_ID.fullmatch(etag):
            raise ValueError("unsupported LinkedIn part identifier")
        identifiers[part.index] = etag
    return [identifiers[i] for i in range(len(upload.parts))]


@dataclass(frozen=True)
class LinkedInMediaUploadResult:
    """Sanitized upload outcome. This is never a publishing approval."""

    state: Literal["available", "pending", "processing_failed", "unknown", "already_attempted"]
    stage: Literal["initialize", "upload", "finalize", "status"]
    media_urn: str | None = None


def upload_linkedin_package_media(
    package_dir: Path, *, package_digest: str, author: str, destination_id: str,
    occurrence_id: str, api_version: str,
    access_token: str, journal_directory: Path,
) -> LinkedInMediaUploadResult:
    """Upload one local package revision under the production authority gate.

    The caller's journal holds one claim for this package, destination and
    occurrence. A status check is made once per transfer, and only its
    same-owner AVAILABLE result marks readiness.
    """
    require_production_authority()
    if destination_id != author or not isinstance(occurrence_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,128}", occurrence_id,
    ):
        raise ValueError("invalid LinkedIn media upload target or occurrence")
    media = prepare_linkedin_package_media(
        package_dir, package_digest=package_digest, author=author, api_version=api_version,
        require_standalone_target=True,
    )
    attempt_identity = f"linkedin-media\n{package_digest}\n{author}\n{destination_id}\n{occurrence_id}"
    attempt = hashlib.sha256(attempt_identity.encode("ascii")).hexdigest()
    transport = GuardedPackageTransport(journal_directory, attempt)
    return _upload_prepared_linkedin_media(media, access_token, transport)


def _upload_prepared_linkedin_media(
    media: PreparedLinkedInMedia, access_token: str, transport: GuardedPackageTransport,
    *, before_send: Callable[[], None] | None = None,
) -> LinkedInMediaUploadResult:
    require_production_authority()
    authorization = _linkedin_bearer(access_token)
    candidate = media.initialize_preview["request"]
    headers = {**candidate["headers"], "Authorization": authorization}
    media_urn = None
    stage: Literal["initialize", "upload", "finalize", "status"] = "initialize"
    try:
        if before_send is not None:
            before_send()
        status, _, payload = transport.post(_LINKEDIN_API + candidate["path"], headers, candidate["body"], {})
        value = payload.get("value")
        identifier = value.get(media.kind) if isinstance(value, dict) else None
        if status != 200 or not isinstance(identifier, str) or not _MEDIA[media.kind].fullmatch(identifier):
            return LinkedInMediaUploadResult("unknown", stage)
        media_urn = identifier
        stage = "upload"
        if media.kind == "image":
            _check_upload_expiry(value.get("uploadUrlExpiresAt"))
            if before_send is not None:
                before_send()
            status, _ = _put_linkedin_upload(
                value.get("uploadUrl"), kind="image", media_urn=media_urn,
                authorization=authorization, data=media.data,
            )
            if status != 201:
                return LinkedInMediaUploadResult("unknown", stage, media_urn)
        else:
            finalize = _upload_linkedin_video(media, value, media_urn, before_send=before_send)
            stage = "finalize"
            if before_send is not None:
                before_send()
            status, _, _ = _post(
                _LINKEDIN_API + "/rest/videos?action=finalizeUpload", headers,
                {"finalizeUploadRequest": finalize}, {},
            )
            if status != 200:
                return LinkedInMediaUploadResult("unknown", stage, media_urn)

        stage = "status"
        if before_send is not None:
            before_send()
        status, _, raw = _request(
            "GET", f"{_LINKEDIN_API}/rest/{media.kind}s/{quote(media_urn, safe='')}", headers, b"",
            allowed_hosts={"api.linkedin.com"},
        )
        checked = inspect_media(
            status=status, body=_response_object(raw), expected_urn=media_urn, expected_owner=media.author,
        )
        if checked["state"] == "provider_reports_available":
            return LinkedInMediaUploadResult("available", stage, media_urn)
        if checked["state"] in {"provider_reports_waiting_upload", "provider_reports_processing"}:
            return LinkedInMediaUploadResult("pending", stage, media_urn)
        if checked["state"] == "provider_reports_processing_failed":
            return LinkedInMediaUploadResult("processing_failed", stage, media_urn)
    except FileExistsError:
        return LinkedInMediaUploadResult("already_attempted", "initialize")
    except (OSError, RuntimeError, ValueError):
        pass
    return LinkedInMediaUploadResult("unknown", stage, media_urn)


def _linkedin_bearer(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/-]{1,4096}=*", token) or len(token) > 4096:
        raise ValueError("invalid LinkedIn authorization")
    return f"Bearer {token}"


def _check_upload_expiry(expires_at: Any) -> None:
    if type(expires_at) is not int or expires_at <= time.time_ns() // 1_000_000:
        raise ValueError("LinkedIn upload has expired or has no valid expiry")


def _upload_linkedin_video(
    media: PreparedLinkedInMedia, value: dict[str, Any], media_urn: str,
    *, before_send: Callable[[], None] | None = None,
) -> dict[str, Any]:
    expires_at = value.get("uploadUrlsExpireAt")
    _check_upload_expiry(expires_at)
    uploads = value.get("uploadInstructions")
    token = value.get("uploadToken")
    if (not isinstance(uploads, list) or not 1 <= len(uploads) <= 2000
            or not isinstance(token, str) or not re.fullmatch(r"[ -~]{0,8192}", token)):
        raise ValueError("invalid LinkedIn video upload session")
    ranges = []
    urls = []
    for instruction in uploads:
        if not isinstance(instruction, dict):
            raise ValueError("invalid LinkedIn video upload instruction")
        ranges.append({"firstByte": instruction.get("firstByte"), "lastByte": instruction.get("lastByte")})
        urls.append(_linkedin_upload_url(instruction.get("uploadUrl"), kind="video", media_urn=media_urn))
    if len(set(urls)) != len(urls):
        raise ValueError("repeated LinkedIn video upload endpoint")
    session = prepare_linkedin_video_parts(media, owner=media.author, video_urn=media_urn, instructions=ranges)
    completed = []
    for part, url in zip(session.parts, urls, strict=True):
        if before_send is not None:
            before_send()
        _check_upload_expiry(expires_at)
        status, response_headers = _put_linkedin_upload(
            url, kind="video", media_urn=media_urn, authorization="", data=part.data,
        )
        etags = [value for name, value in response_headers if name.lower() == "etag"]
        if status != 200 or len(etags) != 1:
            raise RuntimeError("LinkedIn part upload outcome is unknown")
        completed.append((part, etags[0]))
    part_ids = linkedin_finalize_part_ids(session, owner=media.author, video_urn=media_urn, completed=completed)
    _check_upload_expiry(expires_at)
    return {"video": media_urn, "uploadToken": token, "uploadedPartIds": part_ids}
