"""Validate a standalone delivery package without deriving publication authority."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Collection
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.capabilities import capabilities
from scripts.social.prepare_package import (
    _DESTINATIONS,
    _IMAGE_TYPES,
    _MAX_DOCUMENT,
    _MAX_MEDIA,
    _PACKAGE_EXTENSIONS,
    _unique_object,
    validate_telegram_album_captions,
)
from scripts.social.prepare_standalone import (
    DISCORD_ALBUM_TOTAL_LIMIT,
    IMAGE_ALBUM_ACTION,
    TELEGRAM_ALBUM_ACTION,
    TELEGRAM_ALBUM_COUNTS,
    TELEGRAM_ALBUM_SUFFIXES,
    _ALBUM_RULES,
    _CAPTIONLESS_ROUTES,
    _check_telegram_photo_dimensions,
    _local_directory,
    _open_input,
    _validate_content,
)

SCHEMA = "social-standalone-package/1"
_KINDS = {
    "post_text": None,
    "post_image": "image",
    IMAGE_ALBUM_ACTION: "image_album",
    "post_video": "video",
    "post_document": "document",
    "upload_video": "video",
}
_SUFFIXES = {"image": _IMAGE_TYPES, "video": {".mp4"}, "document": {".pdf"}}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_LIMIT = _MAX_DOCUMENT * 12 + 8192


def _identifier(value: Any) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 128
        and value.isprintable() and value == value.strip()
    )


def _source_reference(reference: Any, suffixes: Collection[str]) -> bool:
    if not isinstance(reference, str):
        return False
    path = PurePosixPath(reference)
    return (
        bool(path.parts) and not path.is_absolute() and str(path) == reference
        and path.suffix.lower() in suffixes
        and not any(char in reference for char in '\\:<>*"|?#')
        and all(
            not part.startswith(".") and not part.endswith((" ", "."))
            and not PureWindowsPath(part).is_reserved() and all(ord(char) >= 32 for char in part)
            for part in path.parts
        )
    )


def _validate_source(source: dict[str, Any], fields: set[str], kind: str | None, platform: str) -> None:
    expected = fields | {"type"}
    if kind == "image_album":
        expected.add("media_files")
    elif kind is not None:
        expected.add("media_file")
    if source.keys() != expected:
        raise ValueError("standalone provenance fields do not match the content")
    for field in fields:
        entry = source[field]
        if (
            not isinstance(entry, dict) or entry.keys() != {"file", "text_sha256"}
            or not _source_reference(entry["file"], {".txt", ".md"})
            or not isinstance(entry["text_sha256"], str) or not _DIGEST.fullmatch(entry["text_sha256"])
        ):
            raise ValueError("invalid standalone text provenance")
    if kind == "image_album":
        references = source["media_files"]
        if (
            not isinstance(references, list) or len(references) not in TELEGRAM_ALBUM_COUNTS
            or any(not _source_reference(reference, _ALBUM_RULES[platform][0]) for reference in references)
        ):
            raise ValueError("invalid standalone image album provenance")
    elif kind is not None and not _source_reference(source["media_file"], _SUFFIXES[kind]):
        raise ValueError("invalid standalone attachment provenance")


def validate_standalone_target(
    directory: Path,
    package: dict[str, Any],
    *,
    platform: str,
    account_id: str,
    destination_id: str,
    package_digest: str,
) -> None:
    """Bind an exact standalone manifest to the adapter's expected provider target."""
    _local_directory(directory)
    if platform not in _DESTINATIONS or not _identifier(account_id) or not _identifier(destination_id):
        raise ValueError("standalone delivery requires explicit account and destination IDs")
    action = package.get("action")
    if (
        package.get("schema") != SCHEMA
        or package.keys() != {"schema", "status", "platform", "destination", "action", "target",
                              "source", "content", "media"}
        or package.get("status") != "prepared_for_review"
        or package.get("platform") != platform
        or package.get("destination") != _DESTINATIONS[platform]
        or package.get("target") != {"account_id": account_id, "destination_id": destination_id}
        or not isinstance(action, str)
        or action not in _KINDS
        or (action == "upload_video") != (platform == "tiktok")
        or (action == IMAGE_ALBUM_ACTION and platform not in _ALBUM_RULES)
    ):
        raise ValueError("standalone package does not match the delivery route")
    content = package.get("content")
    source = package.get("source")
    if not isinstance(content, dict) or not isinstance(source, dict) or source.get("type") != "standalone_files":
        raise ValueError("invalid standalone content or source")
    expected_content = {"text"}
    if "first_comment" in content and platform in {"facebook", "linkedin"}:
        expected_content.add("first_comment")
    if content.keys() != expected_content:
        raise ValueError("invalid standalone content fields")
    source_fields = expected_content.copy()
    if content["text"] == "" and (platform, action) in _CAPTIONLESS_ROUTES:
        source_fields.remove("text")
    if any(
        not isinstance(content[field], str) or not content[field].strip() or "\x00" in content[field]
        for field in source_fields
    ):
        raise ValueError("invalid standalone caption or first comment")
    attachment_kind = _KINDS[action]
    _validate_content(platform, action, content, destination_id=destination_id)
    _validate_source(source, source_fields, attachment_kind, platform)
    kind = attachment_kind or "text"
    if kind != "image_album" and (platform, kind) not in _PACKAGE_EXTENSIONS:
        capabilities(platform=platform, destination=_DESTINATIONS[platform], action=action)
    if not isinstance(package_digest, str) or not _DIGEST.fullmatch(package_digest):
        raise ValueError("expected a canonical standalone package digest")
    if not hmac.compare_digest(canonical_snapshot(package)[1], package_digest):
        raise ValueError("digest does not match the standalone package")


def read_standalone_attachment(
    directory: Path, package: dict[str, Any], kind: str | None,
) -> tuple[str, bytes] | None:
    """Verify and return the actual byte snapshot consumed by a V2 adapter."""
    media = package.get("media")
    if _KINDS[package["action"]] != kind:
        raise ValueError("attachment kind does not match the delivery action")
    if kind is None:
        if media is not None:
            raise ValueError("standalone text package cannot have an attachment")
        return None
    if kind == "image_album":
        raise ValueError("use the ordered album attachment reader")
    return _read_attachment(
        directory, media, kind, filenames={f"attachment{suffix}" for suffix in _SUFFIXES[kind]},
        limit=_MAX_MEDIA,
    )


def _read_attachment(
    directory: Path, media: Any, kind: str, *, filenames: Collection[str], limit: int,
) -> tuple[str, bytes]:
    if not isinstance(media, dict) or media.get("kind") != kind:
        raise ValueError("invalid standalone attachment")
    filename = media.get("file")
    expected_length, expected_hash = media.get("bytes"), media.get("sha256")
    if (
        not isinstance(filename, str) or filename not in filenames
        or type(expected_length) is not int or not 0 < expected_length <= limit
        or not isinstance(expected_hash, str) or not _DIGEST.fullmatch(expected_hash)
    ):
        raise ValueError("invalid standalone attachment metadata")
    with _open_input(_local_directory(directory), filename, expected_length) as reader:
        data = reader.read(expected_length + 1)
    if len(data) != expected_length or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected_hash):
        raise ValueError("standalone attachment bytes do not match the package")
    return filename, data


def read_standalone_image_album(
    directory: Path, package: dict[str, Any],
) -> list[tuple[str, bytes]]:
    if package.get("schema") != SCHEMA or package.get("action") != IMAGE_ALBUM_ACTION:
        raise ValueError("expected a standalone image album")
    platform = package.get("platform")
    if platform == "telegram":
        return read_telegram_image_album(directory, package)[0]
    return read_discord_image_album(directory, package)


def read_discord_image_album(directory: Path, package: dict[str, Any]) -> list[tuple[str, bytes]]:
    """Read a Discord message's images in the order recorded in its manifest."""
    content = package.get("content")
    if (
        package.get("schema") not in (SCHEMA, "social-package/1")
        or package.get("platform") != "discord" or package.get("action") != IMAGE_ALBUM_ACTION
        or not isinstance(content, dict) or content.keys() != {"text"}
        or not isinstance(content["text"], str)
    ):
        raise ValueError("invalid Discord image album")
    return _read_ordered_album(directory, package, "discord")


def _read_ordered_album(
    directory: Path, package: dict[str, Any], platform: str,
) -> list[tuple[str, bytes]]:
    suffixes, photo_limit = _ALBUM_RULES[platform]
    source = package.get("source")
    references = source.get("media_files") if isinstance(source, dict) else None
    media = package.get("media")
    if (
        not isinstance(media, list) or len(media) not in TELEGRAM_ALBUM_COUNTS
        or not isinstance(references, list) or len(media) != len(references)
        or any(not _source_reference(reference, suffixes) for reference in references)
    ):
        raise ValueError("invalid ordered image album")
    total = 0
    photos = []
    for index, (entry, reference) in enumerate(zip(media, references), start=1):
        if not isinstance(entry, dict) or entry.keys() != {"file", "kind", "bytes", "sha256", "width", "height"}:
            raise ValueError("invalid image album metadata")
        width, height = entry["width"], entry["height"]
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            raise ValueError("invalid image album dimensions")
        if platform == "telegram":
            _check_telegram_photo_dimensions(width, height)
        photo = _read_attachment(
            directory, entry, "image",
            filenames={f"attachment-{index}{PurePosixPath(reference).suffix.lower()}"},
            limit=photo_limit,
        )
        total += len(photo[1])
        if platform == "discord" and total > DISCORD_ALBUM_TOTAL_LIMIT:
            raise ValueError("Discord album images exceed the combined package size limit")
        photos.append(photo)
    return photos


def read_telegram_image_album(
    directory: Path, package: dict[str, Any],
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Read every approved Telegram photo in its reviewed order."""
    schema = package.get("schema")
    media = package.get("media")
    source = package.get("source")
    content = package.get("content")
    references = source.get("media_files") if isinstance(source, dict) else None
    if (
        schema not in (SCHEMA, "social-package/1") or package.get("platform") != "telegram"
        or package.get("action") != TELEGRAM_ALBUM_ACTION
        or not isinstance(media, list) or len(media) not in TELEGRAM_ALBUM_COUNTS
        or not isinstance(references, list) or len(media) != len(references)
        or any(not _source_reference(reference, TELEGRAM_ALBUM_SUFFIXES) for reference in references)
        or not isinstance(content, dict)
    ):
        raise ValueError("invalid Telegram image album")
    if schema == SCHEMA:
        captions = [content.get("text"), *([""] * (len(media) - 1))]
    else:
        captions = content.get("captions")
        if (
            content.keys() != {"text", "captions"} or not isinstance(captions, list)
            or len(captions) != len(media) or captions[0] != content["text"]
        ):
            raise ValueError("invalid ordered Telegram captions")
    validate_telegram_album_captions(captions)
    return _read_ordered_album(directory, package, "telegram"), captions


def read_delivery_manifest(directory: Path) -> dict[str, Any]:
    """Load a stable local manifest before determining its source schema."""
    root = _local_directory(directory)
    with _open_input(root, "package.json", _MANIFEST_LIMIT) as reader:
        data = reader.read(_MANIFEST_LIMIT + 1)
    if len(data) > _MANIFEST_LIMIT:
        raise ValueError("delivery manifest exceeds the size limit")
    package = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(package, dict):
        raise ValueError("invalid delivery manifest")
    if package.get("schema") != SCHEMA and len(data) > _MAX_DOCUMENT:
        raise ValueError("delivery manifest exceeds the size limit")
    return package


def inspect_standalone_package(
    directory: Path, *, platform: str, account_id: str, destination_id: str, package_digest: str,
) -> dict[str, Any]:
    """Check target and reviewed bytes offline and return a non-authorizing result."""
    package = read_delivery_manifest(directory)
    validate_standalone_target(
        directory, package, platform=platform, account_id=account_id,
        destination_id=destination_id, package_digest=package_digest,
    )
    if package["action"] == IMAGE_ALBUM_ACTION:
        read_standalone_image_album(directory, package)
    else:
        read_standalone_attachment(directory, package, _KINDS[package["action"]])
    return {
        "status": "integrity_checked",
        "platform": platform,
        "account_id": account_id,
        "destination_id": destination_id,
        "action": package["action"],
        "package_digest": package_digest,
    }
