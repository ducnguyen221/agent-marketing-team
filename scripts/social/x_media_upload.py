"""Upload the exact attachment of an approved standalone X package."""
from __future__ import annotations

import base64
import json
import math
import os
import re
import stat
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.linkedin.readonly_auth import _reject_constant, _unique
from scripts.social.publish_channel_package import ChannelApproval, approved_package
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _json, _request
from scripts.social.publish_package_workflow import read_package_account
from scripts.social.standalone_delivery import SCHEMA, read_standalone_attachment

_UPLOAD = "https://api.x.com/2/media/upload"
_MEDIA_ID = re.compile(r"[1-9][0-9]{0,18}\Z")
_ACCOUNT_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MAX_IMAGE_BYTES = 5_000_000
_SEGMENT_BYTES = 4 * 1024 * 1024
_MAX_STATUS_CALLS = 5
_POLL_BUDGET_SECONDS = 30

UploadState = Literal["available", "pending", "processing_failed", "expired", "unknown", "already_attempted"]
UploadStage = Literal["upload", "initialize", "append", "finalize", "status"]


@dataclass(frozen=True)
class XMediaUploadResult:
    """Sanitized outcome tied to a local upload attempt."""

    state: UploadState
    stage: UploadStage
    account_id: str
    package_digest: str
    file_sha256: str
    occurrence_id: str
    attempt_key: str
    provider_id: str | None = None
    expires_at: float | None = None
    reconciliation_id: str | None = None


def _data(status: int, raw: bytes) -> dict[str, Any]:
    response = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(response, dict):
        raise ValueError("unexpected X media response")
    data = response.get("data")
    if (
        status != 200 or not isinstance(data, dict) or response.get("errors") not in (None, [])
        or any(key in response for key in ("error", "code", "status", "title", "detail", "type"))
    ):
        raise ValueError("unexpected X media response")
    return data


def _post_json(url: str, headers: Mapping[str, str], fields: Mapping[str, Any]) -> tuple[int, bytes]:
    status, _, raw = _request(
        "POST", url, {**headers, "Content-Type": "application/json"}, _json(fields),
        allowed_hosts={"api.x.com"},
    )
    return status, raw


def _identity(data: dict[str, Any], *, expected_id: str | None = None) -> str:
    media_id = data.get("id")
    if (
        not isinstance(media_id, str) or not _MEDIA_ID.fullmatch(media_id)
        or (expected_id is not None and media_id != expected_id)
    ):
        raise ValueError("unexpected X media identifier")
    return media_id


def _deadline(data: dict[str, Any], request_started: float) -> float:
    seconds = data.get("expires_after_secs")
    if type(seconds) is not int or not 0 < seconds <= 2**31 - 1:
        raise ValueError("missing or invalid X media expiry")
    return request_started + seconds


def _processing(data: dict[str, Any], *, synchronous_allowed: bool) -> tuple[UploadState, int]:
    if "processing_info" not in data and synchronous_allowed:
        return "available", 0
    info = data.get("processing_info")
    if not isinstance(info, dict):
        raise ValueError("missing X media processing information")
    state = info.get("state")
    if state == "succeeded":
        return "available", 0
    if state == "failed":
        return "processing_failed", 0
    if state in ("pending", "in_progress"):
        delay = info.get("check_after_secs", 1)
        if type(delay) is not int or delay < 0:
            raise ValueError("invalid X media poll delay")
        return "pending", max(1, delay)
    raise ValueError("unexpected X media processing state")


def _x_upload_attempt_key(account_id: str, occurrence_id: str) -> str:
    return canonical_snapshot({
        "platform": "x", "operation": "media_upload", "account_id": account_id,
        "destination_id": account_id, "occurrence_id": occurrence_id,
    })[1]


@contextmanager
def _open_x_journal(transport: GuardedPackageTransport):
    if os.name != "posix":
        raise OSError("X attempt journal unavailable on this platform")
    directory_fd = os.open(
        transport._journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        info = os.fstat(directory_fd)
        if (info.st_dev, info.st_ino) != transport._journal_identity:
            raise OSError("attempt journal directory changed")
        yield directory_fd
    finally:
        os.close(directory_fd)


def _read_x_journal_file(directory_fd: int, name: str, limit: int) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ValueError("unsafe X journal record")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("oversized X journal record")
    return raw


def _read_x_record(directory_fd: int, name: str) -> dict[str, Any]:
    raw = _read_x_journal_file(directory_fd, name, 4096)
    record = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(record, dict):
        raise ValueError("invalid X journal record")
    return record


def _write_x_record(directory_fd: int, name: str, record: dict[str, Any], *, exclusive: bool = False) -> None:
    temporary = f".x-{uuid.uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json(record))
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory_fd)
        else:
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


@contextmanager
def _lock_x_attempt(directory_fd: int, name: str):
    import fcntl

    fd = os.open(
        name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ValueError("unsafe X attempt lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _media_binding(
    account_id: str, package_digest: str, file_sha256: str, occurrence_id: str, kind: str,
) -> dict[str, str]:
    return {
        "account_id": account_id, "destination_id": account_id,
        "package_digest": package_digest, "file_sha256": file_sha256,
        "occurrence_id": occurrence_id, "kind": kind,
        "attempt_key": _x_upload_attempt_key(account_id, occurrence_id),
    }


def _media_status(
    headers: Mapping[str, str], media_id: str, size: int, expires_at: float,
) -> tuple[UploadState, int, float]:
    started = time.time()
    if started >= expires_at:
        return "expired", 0, expires_at
    query = urlencode({"command": "STATUS", "media_id": media_id})
    status, _, raw = _request("GET", f"{_UPLOAD}?{query}", headers, b"", allowed_hosts={"api.x.com"})
    data = _data(status, raw)
    _identity(data, expected_id=media_id)
    if "size" in data and (type(data["size"]) is not int or data["size"] != size):
        raise ValueError("unexpected X media size")
    if "expires_after_secs" in data:
        expires_at = min(expires_at, _deadline(data, started))
    state, delay = _processing(data, synchronous_allowed=False)
    return state, delay, expires_at


def upload_x_package_media(
    package_dir: Path, *, account_id: str, occurrence_id: str, credential: str,
    approval: ChannelApproval, journal_directory: Path, enable_dispatch: bool = False,
) -> XMediaUploadResult:
    """Claim and run one attempt using the same OAuth credential throughout."""
    return _upload_x_package_media(
        package_dir, account_id=account_id, occurrence_id=occurrence_id, credential=credential,
        approval=approval, journal_directory=journal_directory, enable_dispatch=enable_dispatch,
    )


def _upload_x_package_media(
    package_dir: Path, *, account_id: str, occurrence_id: str, credential: str,
    approval: ChannelApproval, journal_directory: Path, enable_dispatch: bool,
    resume: bool = False,
) -> XMediaUploadResult:
    require_production_authority()
    if (
        not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id)
        or not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id)
    ):
        raise ValueError("invalid X media upload target or occurrence")
    package = approved_package(
        package_dir, platform="x", account_id=account_id, credential=credential,
        approval=approval, enable_dispatch=enable_dispatch,
    )
    if package.get("schema") != SCHEMA:
        raise ValueError("X upload requires a target-bound standalone image or video package")
    return _upload_checked_x_media(
        package_dir, package=package, account_id=account_id, occurrence_id=occurrence_id,
        credential=credential, package_digest=approval.package_digest, journal_directory=journal_directory,
        resume=resume,
    )


def _upload_checked_x_media(
    package_dir: Path, *, package: dict[str, Any], account_id: str, occurrence_id: str,
    credential: str, package_digest: str, journal_directory: Path, resume: bool,
    before_upload: Callable[[], None] | None = None,
) -> XMediaUploadResult:
    if os.name != "posix":
        raise ValueError("X attempt journal unavailable on this platform")
    if package.get("action") not in ("post_image", "post_video"):
        raise ValueError("X upload requires a single image or video package")
    kind = package["action"].removeprefix("post_")
    attachment = read_standalone_attachment(package_dir, package, kind)
    if attachment is None or not attachment[1]:
        raise ValueError("X media attachment is empty")
    _, binary = attachment
    if kind == "image" and len(binary) > _MAX_IMAGE_BYTES:
        raise ValueError("X post image exceeds the media limit")

    attempt = _x_upload_attempt_key(account_id, occurrence_id)
    transport = GuardedPackageTransport(journal_directory, attempt)
    read_package_account(platform="x", account_id=account_id, credential=credential, enable_provider_read=True)
    headers = {"Authorization": f"Bearer {credential}", "Accept": "application/json"}
    stage: UploadStage = "upload" if kind == "image" else "initialize"
    media_id: str | None = None
    expires_at: float | None = None
    binding = _media_binding(account_id, package_digest, package["media"]["sha256"], occurrence_id, kind)
    record_name = f"{transport._claim_name}.media"

    def outcome(state: UploadState) -> XMediaUploadResult:
        return XMediaUploadResult(
            state=state, stage=stage, account_id=account_id, package_digest=package_digest,
            file_sha256=package["media"]["sha256"], occurrence_id=occurrence_id, attempt_key=attempt,
            provider_id=media_id if state == "available" else None,
            expires_at=expires_at,
            reconciliation_id=media_id if state != "available" else None,
        )

    if kind == "image":
        url = _UPLOAD
        fields = {"media_category": "tweet_image", "media": base64.b64encode(binary).decode("ascii")}
    else:
        url = f"{_UPLOAD}/initialize"
        fields = {"media_category": "tweet_video", "media_type": "video/mp4", "total_bytes": len(binary)}

    def save(directory_fd: int, state: str, *, delay: int = 0) -> None:
        _write_x_record(directory_fd, record_name, {
            **binding, "version": 1, "media_id": media_id, "expires_at": expires_at,
            "state": state, "next_poll_at": min(time.time() + delay, expires_at) if expires_at else None,
        })

    def poll(directory_fd: int, delay: float) -> XMediaUploadResult:
        nonlocal stage, expires_at
        stage = "status"
        poll_until = time.monotonic() + _POLL_BUDGET_SECONDS
        for _ in range(_MAX_STATUS_CALLS):
            if time.time() >= expires_at:
                return outcome("expired")
            if time.time() + delay >= expires_at or time.monotonic() + delay >= poll_until:
                break
            if delay > 0:
                time.sleep(delay)
            if before_upload is not None:
                before_upload()
            state, delay, expires_at = _media_status(headers, media_id, len(binary), expires_at)
            if state != "pending":
                save(directory_fd, state)
                return outcome("expired" if state == "available" and time.time() >= expires_at else state)
            save(directory_fd, state, delay=delay)
        return outcome("pending")

    def reconcile(directory_fd: int) -> XMediaUploadResult:
        nonlocal stage, media_id, expires_at
        try:
            if _read_x_journal_file(directory_fd, transport._claim_name, 16) != b"attempt_started\n":
                return outcome("unknown")
            record = _read_x_record(directory_fd, record_name)
        except FileNotFoundError:
            return outcome("already_attempted")
        expected_fields = binding.keys() | {"version", "media_id", "expires_at", "state", "next_poll_at"}
        if (
            record.keys() != expected_fields or type(record["version"]) is not int or record["version"] != 1
            or any(record[key] != value for key, value in binding.items())
        ):
            return outcome("unknown")
        if record["state"] not in ("pending", "available"):
            return outcome("already_attempted")
        recorded_id, deadline, next_poll = record["media_id"], record["expires_at"], record["next_poll_at"]
        if (
            not isinstance(recorded_id, str) or not _MEDIA_ID.fullmatch(recorded_id) or recorded_id == credential
            or type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0
            or type(next_poll) not in (int, float) or not math.isfinite(next_poll) or not 0 < next_poll <= deadline
        ):
            return outcome("unknown")
        media_id, expires_at = recorded_id, deadline
        stage = "status"
        return poll(directory_fd, max(0.0, next_poll - time.time()))

    def upload(directory_fd: int) -> XMediaUploadResult:
        nonlocal stage, media_id, expires_at
        started = time.time()
        status, raw = _post_json(url, headers, fields)
        data = _data(status, raw)
        observed_id = _identity(data)
        if observed_id == credential:
            raise ValueError("invalid X media identifier")
        media_id = observed_id
        save(directory_fd, "identified")
        expires_at = _deadline(data, started)
        save(directory_fd, "identified")
        if kind == "video":
            stage = "append"
            for index, offset in enumerate(range(0, len(binary), _SEGMENT_BYTES)):
                if before_upload is not None:
                    before_upload()
                if time.time() >= expires_at:
                    return outcome("expired")
                chunk = binary[offset:offset + _SEGMENT_BYTES]
                status, raw = _post_json(
                    f"{_UPLOAD}/{media_id}/append", headers,
                    {"media": base64.b64encode(chunk).decode("ascii"), "segment_index": index},
                )
                _data(status, raw)

            stage = "finalize"
            if before_upload is not None:
                before_upload()
            started = time.time()
            if started >= expires_at:
                return outcome("expired")
            status, _, raw = _request(
                "POST", f"{_UPLOAD}/{media_id}/finalize", headers, b"", allowed_hosts={"api.x.com"},
            )
            data = _data(status, raw)
            _identity(data, expected_id=media_id)
            expires_at = min(expires_at, _deadline(data, started))

        if "size" in data and (type(data["size"]) is not int or data["size"] != len(binary)):
            return outcome("unknown")
        state, delay = _processing(data, synchronous_allowed=True)
        save(directory_fd, state, delay=delay)
        if state == "pending":
            return poll(directory_fd, delay)
        if state == "processing_failed":
            return outcome(state)
        if time.time() >= expires_at:
            return outcome("expired")
        return outcome(state)

    try:
        with _open_x_journal(transport) as directory_fd:
            with _lock_x_attempt(directory_fd, f"{transport._claim_name}.lock"):
                try:
                    os.stat(transport._claim_name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    return reconcile(directory_fd) if resume and kind == "video" else outcome("already_attempted")
                try:
                    os.stat(record_name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    return outcome("unknown")
                try:
                    transport._claim_attempt()
                except FileExistsError:
                    return outcome("already_attempted")
                if before_upload is not None:
                    before_upload()
                return upload(directory_fd)
    except (OSError, RuntimeError, ValueError, RecursionError, OverflowError):
        return outcome("unknown")
