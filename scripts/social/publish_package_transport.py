"""Explicit HTTPS transports for V2 adapters, with no retry or redirect."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from scripts.social.channels.linkedin.readonly_auth import _reject_constant, _unique
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.prepare_standalone import TELEGRAM_ALBUM_COUNTS

_META_HOSTS = {"graph.facebook.com", "graph-video.facebook.com", "graph.threads.com"}
_JSON_HOSTS = {"api.linkedin.com", "api.x.com", "discord.com", "open.tiktokapis.com"}
_FORM_HOSTS = _META_HOSTS | {"api.telegram.org"}
_UPLOAD_HOSTS = {"www.googleapis.com"}
_LINKEDIN_UPLOAD_HOST = "www.linkedin.com"
_MAX_RESPONSE = 2 * 1024 * 1024
_SAFE_FILE = re.compile(r"attachment\.(?:png|jpe?g|webp|mp4|pdf)\Z")
_SAFE_FIELD = re.compile(r"(?:source|photo|video|document|files\[0\])\Z")
_ALBUM_FILES = re.compile(r"attachment-([1-9]|10)\.(?:png|jpe?g)\Z")
_DISCORD_ALBUM_FILE = re.compile(r"attachment-([1-9]|10)\.(?:png|jpe?g|webp)\Z")
_DISCORD_MESSAGE_PATH = re.compile(r"/api/v10/channels/[1-9][0-9]{0,31}/messages\Z")
_DISCORD_MESSAGE_LIMIT = 25 * 1024 * 1024


def _request(method: str, url: str, headers: Mapping[str, str], body: bytes | memoryview, *,
             allowed_hosts: set[str]) -> tuple[int, list[tuple[str, str]], bytes]:
    require_production_authority()
    connection = None
    try:
        target = urlsplit(url)
        if (
            target.scheme != "https" or target.hostname not in allowed_hosts or target.port not in {None, 443}
            or target.username is not None or target.password is not None or target.fragment
        ):
            raise ValueError("invalid provider endpoint")
        path = (target.path or "/") + ("?" + target.query if target.query else "")
        connection = http.client.HTTPSConnection(target.hostname, timeout=120)
        connection.request(method, path, body=body, headers=dict(headers))
        result = connection.getresponse()
        payload = result.read(_MAX_RESPONSE + 1)
        if len(payload) > _MAX_RESPONSE:
            raise ValueError("provider response too large")
        return result.status, result.getheaders(), payload
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise RuntimeError("provider transport failed") from None
    finally:
        if connection is not None:
            connection.close()


def _json(data: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(data), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _response_object(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant) if raw else {}
    except (UnicodeError, ValueError, RecursionError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _multipart(boundary: str, parts: list[tuple[bytes, bytes]]) -> bytes:
    marker = boundary.encode("ascii")
    fragments: list[bytes] = []
    for headers, data in parts:
        fragments.extend((b"--", marker, b"\r\n", headers, b"\r\n\r\n", data, b"\r\n"))
    fragments.extend((b"--", marker, b"--\r\n"))
    return b"".join(fragments)


def _post(
    url: str, headers: Mapping[str, str], fields: Mapping[str, Any],
    files: Mapping[str, tuple[str, bytes]],
) -> tuple[int, list[tuple[str, str]], Mapping[str, Any]]:
    """Send one fixed-host POST after the caller has claimed the attempt."""
    endpoint = urlsplit(url)
    host = endpoint.hostname
    telegram_album = (
        host == "api.telegram.org"
        and re.fullmatch(r"/bot[0-9]{1,20}:[A-Za-z0-9_-]{20,128}/sendMediaGroup", endpoint.path)
    )
    discord_album = host == "discord.com" and len(files) > 1
    boundary = uuid.uuid4().hex
    if telegram_album and (
        len(files) not in TELEGRAM_ALBUM_COUNTS or fields.keys() != {"chat_id", "media"}
        or set(files) != {f"photo_{index}" for index in range(1, len(files) + 1)}
    ):
        raise ValueError("invalid Telegram album multipart fields")
    if discord_album:
        if (
            not _DISCORD_MESSAGE_PATH.fullmatch(endpoint.path) or endpoint.query
            or len(files) not in TELEGRAM_ALBUM_COUNTS
            or list(files) != [f"files[{index}]" for index in range(len(files))]
            or fields.get("attachments") != [
                {"id": index, "filename": filename}
                for index, (filename, _) in enumerate(files.values())
            ]
        ):
            raise ValueError("invalid Discord album multipart fields")
    if files:
        if not (telegram_album or discord_album) and len(files) != 1:
            raise ValueError("expected one attachment")
        if host in _UPLOAD_HOSTS:
            field, (filename, binary) = next(iter(files.items()))
            if not _SAFE_FIELD.fullmatch(field) or not _SAFE_FILE.fullmatch(filename):
                raise ValueError("invalid attachment metadata")
            content_type = f'multipart/related; boundary="{boundary}"'
            parts = [(b"Content-Type: application/json; charset=UTF-8", _json(fields)),
                     (b"Content-Type: video/mp4", binary)]
        else:
            content_type = f"multipart/form-data; boundary={boundary}"
            if host == "discord.com":
                parts = [(b'Content-Disposition: form-data; name="payload_json"\r\n'
                          b"Content-Type: application/json", _json(fields))]
            else:
                if not all(re.fullmatch(r"[a-z_]+", key) and isinstance(value, str)
                           for key, value in fields.items()):
                    raise ValueError("invalid form fields")
                parts = [(f'Content-Disposition: form-data; name="{key}"'.encode("ascii"), value.encode("utf-8"))
                         for key, value in fields.items()]
            for index, (field, (filename, binary)) in enumerate(files.items(), start=1):
                if telegram_album:
                    match = _ALBUM_FILES.fullmatch(filename)
                    if match is None or field != f"photo_{match[1]}":
                        raise ValueError("invalid Telegram album attachment metadata")
                elif discord_album:
                    match = _DISCORD_ALBUM_FILE.fullmatch(filename)
                    if match is None or match[1] != str(index):
                        raise ValueError("invalid Discord album attachment metadata")
                elif not _SAFE_FIELD.fullmatch(field) or not _SAFE_FILE.fullmatch(filename):
                    raise ValueError("invalid attachment metadata")
                file_header = (f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                               "Content-Type: application/octet-stream")
                parts.append((file_header.encode("ascii"), binary))
        body = _multipart(boundary, parts)
        if discord_album and len(body) > _DISCORD_MESSAGE_LIMIT:
            raise ValueError("Discord album request exceeds the multipart limit")
    elif host in _FORM_HOSTS:
        content_type, body = "application/x-www-form-urlencoded", urlencode(fields).encode("ascii")
    else:
        content_type, body = "application/json", _json(fields)
    status, response_headers, raw = _request(
        "POST", url, {**headers, "Content-Type": content_type}, body,
        allowed_hosts=_JSON_HOSTS | _FORM_HOSTS | _UPLOAD_HOSTS,
    )
    return status, response_headers, _response_object(raw)


def _linkedin_upload_url(url: Any, *, kind: str, media_urn: str) -> str:
    if not isinstance(url, str) or not re.fullmatch(r"[!-~]{1,8192}", url) or "\\" in url or "#" in url:
        raise ValueError("invalid LinkedIn upload endpoint")
    target = urlsplit(url)
    suffix = "uploaded-image/0" if kind == "image" else "uploadedVideo"
    asset_id = media_urn.rsplit(":", 1)[-1]
    if (target.scheme != "https" or target.netloc != _LINKEDIN_UPLOAD_HOST
            or target.path != f"/dms-uploads/{asset_id}/{suffix}" or not target.query):
        raise ValueError("invalid LinkedIn upload endpoint")
    return url


def _put_linkedin_upload(
    url: str, *, kind: str, media_urn: str, authorization: str, data: bytes | memoryview,
) -> tuple[int, list[tuple[str, str]]]:
    url = _linkedin_upload_url(url, kind=kind, media_urn=media_urn)
    headers = {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}
    if kind == "image":
        headers["Authorization"] = authorization
    status, response_headers, _ = _request("PUT", url, headers, data, allowed_hosts={_LINKEDIN_UPLOAD_HOST})
    return status, response_headers


class GuardedPackageTransport:
    """One stable attempt key per approved package, destination, and operation."""

    def __init__(self, journal_directory: Path, attempt_key: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", attempt_key):
            raise ValueError("invalid workflow attempt key")
        journal_directory = journal_directory.resolve(strict=True)
        if any(part.casefold() == ".secret" for part in journal_directory.parts):
            raise ValueError("invalid attempt journal directory")
        journal_stat = journal_directory.stat()
        if not stat.S_ISDIR(journal_stat.st_mode):
            raise ValueError("invalid attempt journal directory")
        key_digest = hashlib.sha256(attempt_key.encode("ascii")).hexdigest()
        self._journal_directory = journal_directory
        self._journal_identity = (journal_stat.st_dev, journal_stat.st_ino)
        self._claim_name = f"{key_digest}.attempt"
        self._tiktok_upload_url: str | None = None

    def _claim_attempt(self) -> None:
        if os.name != "posix":
            raise OSError("durable attempt journal unavailable on this platform")
        directory_fd = os.open(self._journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            journal_stat = os.fstat(directory_fd)
            if (journal_stat.st_dev, journal_stat.st_ino) != self._journal_identity:
                raise OSError("attempt journal directory changed")
            claim_fd = os.open(
                self._claim_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd,
            )
            with os.fdopen(claim_fd, "wb") as journal:
                journal.write(b"attempt_started\n")
                journal.flush()
                os.fsync(journal.fileno())
            # The file sync does not persist its directory entry.
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def post(
        self, url: str, headers: Mapping[str, str], fields: Mapping[str, Any],
        files: Mapping[str, tuple[str, bytes]],
    ) -> tuple[int, list[tuple[str, str]], Mapping[str, Any]]:
        """Claim before opening HTTPS. Retain the claim after every outcome."""
        require_production_authority()
        self._claim_attempt()
        result = _post(url, headers, fields, files)
        endpoint = urlsplit(url)
        if endpoint.hostname == "open.tiktokapis.com" and endpoint.path == "/v2/post/publish/inbox/video/init/":
            data = result[2].get("data")
            upload_url = data.get("upload_url") if isinstance(data, dict) else None
            if result[0] == 200 and isinstance(upload_url, str):
                self._tiktok_upload_url = upload_url
        return result

    def post_form(
        self, url: str, headers: Mapping[str, str], fields: Mapping[str, str],
        files: Mapping[str, tuple[str, bytes]],
    ) -> tuple[int, Mapping[str, Any]]:
        """Two-result version for the Facebook and Telegram package adapters."""
        status, _, payload = self.post(url, headers, fields, files)
        return status, payload

    def put_tiktok_chunk(self, url: str, headers: Mapping[str, str], data: bytes) -> int:
        """Transfer a chunk to the endpoint returned for this same claimed attempt."""
        host = urlsplit(url).hostname
        if (
            not host or not host.endswith(".tiktokapis.com") or url != self._tiktok_upload_url
            or any(key.lower() == "authorization" for key in headers)
        ):
            raise ValueError("invalid TikTok transfer endpoint")
        status, _, _ = _request("PUT", url, headers, data, allowed_hosts={host})
        return status
