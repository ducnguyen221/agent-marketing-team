"""Draft a V2 review preview and check package consistency with V1 source files."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter, _valid_identity
from scripts.lib.delivery_contract import canonical_snapshot
from scripts.lib.delivery_ledger import SCOPE_FIELDS
from scripts.lib.md_io import _moc, read_table
from scripts.lib.studio_paths import channel_of
from scripts.pipeline.approval_gate import check_delivery_local_path
from scripts.social.prepare_package import (
    IMAGE_ALBUM_ACTION,
    _MAX_DOCUMENT,
    _MAX_MEDIA,
    _document,
    _local_file,
    _unique_object,
    prepare_package,
)
from scripts.social.schedule_v2 import _reject_secret_path
from scripts.social.review_snapshot import DRAFT_FIELDS, DRAFT_SCHEMA, SOURCE_STATUS, canonical_review


_PACKAGE_FIELDS = {"schema", "status", "platform", "destination", "action", "source", "content", "media"}
_ACTION_KINDS = {
    "post_text": "text",
    "post_image": "image",
    IMAGE_ALBUM_ACTION: "image",
    "post_video": "video",
    "post_document": "document",
    "upload_video": "video",
}
def verify_stored_package_campaign_source(
    *, package_dir: Path, campaign: Path, scope: dict[str, str], temporary_parent: Path,
    text_file: str | None = None, comment_file: str | None = None,
    media_file: str | None = None,
    media_files: list[str] | None = None, caption_files: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Return the stored manifest and digest after checking it against V1."""
    package_root = _local_directory(package_dir)
    with _checked_package_file(package_root, "package.json") as source:
        package = _read_package_manifest(source)
    digest = verify_package_campaign_source(
        package, package_dir=package_dir, campaign=campaign, scope=scope,
        temporary_parent=temporary_parent, text_file=text_file, comment_file=comment_file,
        media_file=media_file, media_files=media_files, caption_files=caption_files,
    )
    return package, digest


def verify_package_campaign_source(
    package: dict[str, Any], *, package_dir: Path, campaign: Path, scope: dict[str, str],
    temporary_parent: Path,
    text_file: str | None = None, comment_file: str | None = None,
    media_file: str | None = None,
    media_files: list[str] | None = None, caption_files: list[str] | None = None,
) -> str:
    """Verify the stored manifest and attachment against the selected V1 source."""
    if (
        not isinstance(scope, dict) or set(scope) != set(SCOPE_FIELDS)
        or scope["gate"] != "g2" or not all(map(_valid_identity, scope.values()))
    ):
        raise ValueError("package source check requires one exact G2 scope")
    if (
        not isinstance(package, dict) or set(package) != _PACKAGE_FIELDS
        or package["schema"] != "social-package/1" or package["status"] != "prepared_for_review"
    ):
        raise ValueError("expected a prepared social package")

    package_dir = _local_directory(package_dir)
    package_directory_info = package_dir.lstat()
    campaign = _local_directory(campaign)
    frontmatter, body = _split_frontmatter(_document(campaign, "campaign.md"))
    metadata = _source_metadata(frontmatter)
    start, end = _moc("CONTENT")
    if body.count(start) != 1 or body.count(end) != 1 or body.index(start) > body.index(end):
        raise ValueError("V1 campaign must contain exactly one ordered Content marker pair")
    columns, rows = read_table(body, "CONTENT")
    if (
        metadata.get("id") != scope["campaign_id"] or metadata.get("channel") != scope["channel_id"]
        or len(columns) != len(set(columns))
    ):
        raise ValueError("V1 campaign metadata or Content table does not match the scope")
    try:
        (campaign / "channel.yml").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("V1 channel metadata must be outside the campaign")
    channel = channel_of(campaign.parent)
    channel_config = _source_metadata(_document(channel, "channel.yml"))
    if channel_config.get("id") != scope["channel_id"]:
        raise ValueError("V1 channel does not match the scope")

    matching = [row for row in rows if row.get("content_id") == scope["content_id"]]
    if len(matching) != 1:
        raise ValueError("V1 Content row is missing or ambiguous")
    folder = matching[0].get("folder", "")
    relative = PurePosixPath(folder)
    if (
        not relative.parts or relative.is_absolute()
        or "\\" in folder or ":" in folder or ".." in relative.parts
        or any(part.startswith(".") or part.endswith((" ", ".")) or PureWindowsPath(part).is_reserved()
               for part in relative.parts)
    ):
        raise ValueError("V1 Content row requires a local post folder")
    source_dir = _local_directory(campaign.joinpath(*relative.parts))
    if source_dir == campaign or not source_dir.is_relative_to(campaign):
        raise ValueError("V1 post folder is outside the campaign")
    folder_key = os.path.normcase(str(relative))
    if sum(os.path.normcase(str(PurePosixPath(row.get("folder", "")))) == folder_key for row in rows) != 1:
        raise ValueError("V1 post folder is shared by multiple Content rows")
    publication = json.loads(_document(source_dir, "publish.json"), object_pairs_hook=_unique_object)
    if (
        not isinstance(publication, dict)
        or publication.get("campaign_id") != scope["campaign_id"]
        or publication.get("channel_id") != scope["channel_id"]
        or publication.get("post_id") != scope["content_id"]
    ):
        raise ValueError("V1 publication metadata does not match the scope")

    platform, action = package["platform"], package["action"]
    if not isinstance(platform, str):
        raise ValueError("unsupported package platform")
    if not isinstance(action, str) or action not in _ACTION_KINDS:
        raise ValueError("unsupported package action")
    snapshot, digest = canonical_snapshot(package)
    temp_root = _local_directory(temporary_parent)
    if temp_root.is_relative_to(campaign) or temp_root.is_relative_to(package_dir):
        raise ValueError("temporary package storage must be outside the campaign and package")
    with tempfile.TemporaryDirectory(dir=temp_root, prefix="social-source-check-") as staging:
        rebuilt_dir = prepare_package(
            source_dir=source_dir, output_dir=Path(staging) / "package", post_id=scope["post_id"],
            platform=platform, kind=_ACTION_KINDS[action], text_file=text_file,
            comment_file=comment_file, media_file=media_file, media_files=media_files, caption_files=caption_files,
        )
        rebuilt = json.loads(_document(rebuilt_dir, "package.json"), object_pairs_hook=_unique_object)
    if canonical_snapshot(rebuilt)[0] != snapshot:
        raise ValueError("package does not match the selected V1 source")
    with _checked_package_file(package_dir, "package.json") as source:
        stored = _read_package_manifest(source)
        if canonical_snapshot(stored)[0] != snapshot:
            raise ValueError("stored package manifest does not match the selected V1 source")
        media = rebuilt["media"]
        if action == IMAGE_ALBUM_ACTION:
            for photo in media:
                _verify_attachment(package_dir, photo)
        elif media is not None:
            _verify_attachment(package_dir, media)
    check_delivery_local_path(package_dir)
    if not os.path.samestat(package_directory_info, package_dir.lstat()):
        raise ValueError("package directory changed during verification")
    return digest


def _read_package_manifest(source: BinaryIO) -> dict[str, Any]:
    data = source.read(_MAX_DOCUMENT + 1)
    if len(data) > _MAX_DOCUMENT:
        raise ValueError("package manifest too large")
    package = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(package, dict) or set(package) != _PACKAGE_FIELDS:
        raise ValueError("expected a prepared social package")
    return package


def _verify_attachment(package_dir: Path, media: dict[str, Any]) -> None:
    digest = hashlib.sha256()
    length = 0
    with _checked_package_file(package_dir, media["file"]) as source:
        while chunk := source.read(1024 * 1024):
            length += len(chunk)
            if length > min(_MAX_MEDIA, media["bytes"]):
                raise ValueError("package attachment length does not match the selected V1 source")
            digest.update(chunk)
        if length != media["bytes"] or digest.hexdigest() != media["sha256"]:
            raise ValueError("package attachment does not match the selected V1 source")


@contextmanager
def _checked_package_file(root: Path, reference: str) -> Iterator[BinaryIO]:
    path = _local_file(root, reference)
    check_delivery_local_path(path, file=True)
    before = path.lstat()
    if before.st_nlink != 1:
        raise ValueError("package file must have exactly one hard link")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not _same_package_file(before, opened):
            raise ValueError("package file changed before verification")
        check_delivery_local_path(path, file=True)
        if not _same_package_file(opened, path.lstat()):
            raise ValueError("package file changed before verification")
        yield stream
        check_delivery_local_path(path, file=True)
        if not (
            _same_package_file(opened, os.fstat(stream.fileno()))
            and _same_package_file(opened, path.lstat())
        ):
            raise ValueError("package file changed during verification")


def _same_package_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        os.path.samestat(left, right)
        and left.st_nlink == right.st_nlink == 1
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def _source_metadata(data: str | None) -> dict[str, str]:
    node = yaml.compose(data or "", Loader=yaml.SafeLoader)
    yaml_tag = "tag:yaml.org,2002:"
    if not isinstance(node, yaml.MappingNode) or node.tag != yaml_tag + "map":
        raise ValueError("source metadata must be a mapping")
    keys = set()
    identity = {}
    for key, value in node.value:
        if key.tag != yaml_tag + "str" or key.value in keys:
            raise ValueError("source metadata keys must be unique strings")
        keys.add(key.value)
        if key.value in {"id", "channel"}:
            if value.tag != yaml_tag + "str":
                raise ValueError("source identity fields must be strings")
            identity[key.value] = value.value
    return identity


def _local_directory(path: Path) -> Path:
    path = Path(path)
    _reject_secret_path(path)
    path = Path(os.path.abspath(path))
    _reject_secret_path(path)
    if path.drive.startswith(("\\\\", "//")):
        raise ValueError("expected a local public-intent directory")
    check_delivery_local_path(path)
    resolved = path.resolve(strict=True)
    _reject_secret_path(resolved)
    if not resolved.is_dir():
        raise ValueError("expected a local directory")
    return resolved


def prepare_review_draft(
    package: dict[str, Any], *, claimed_scope: dict[str, str], account_id: str,
    destination_id: str, occurrence_key: str, scheduled_at: str | None,
    timezone: str, privacy: str, delivery_options: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return an unverified draft and digest for one explicit destination occurrence."""
    if set(claimed_scope) != set(SCOPE_FIELDS) or claimed_scope.get("gate") != "g2":
        raise ValueError("package review draft requires a proposed G2 scope")
    source = package.get("source")
    if (
        set(package) != _PACKAGE_FIELDS
        or package.get("schema") != "social-package/1"
        or package.get("status") != "prepared_for_review"
        or not isinstance(source, dict)
        or source.get("post_id") != claimed_scope.get("post_id")
        or claimed_scope["post_id"] == "*"
    ):
        raise ValueError("prepared package post ID does not match the proposed scope")
    required = (
        *claimed_scope.values(), package.get("platform"), package.get("destination"),
        package.get("action"), account_id, destination_id, occurrence_key, timezone, privacy,
    )
    if any(not isinstance(value, str) or not value.strip() for value in required):
        raise ValueError("package review identity or delivery settings are incomplete")
    if scheduled_at is not None and (not isinstance(scheduled_at, str) or not scheduled_at.strip()):
        raise ValueError("invalid review schedule")
    if not isinstance(delivery_options, dict):
        raise ValueError("delivery options must be an object")

    return canonical_review(
        claimed_scope=claimed_scope, platform=package["platform"],
        destination_kind=package["destination"], action=package["action"],
        account_id=account_id, destination_id=destination_id,
        occurrence_key=occurrence_key, scheduled_at=scheduled_at, timezone=timezone,
        privacy=privacy, delivery_options=delivery_options,
        package_digest=canonical_snapshot(package)[1],
    )


def compare_draft_record(
    preview: dict[str, Any], *, recorded_digest: str, recorded_by: str,
    recorded_quote: str, reviewer: str, verbatim_decision: str,
) -> None:
    """Compare the unverified draft digest and witness text with a separate record."""
    if (
        set(preview) != DRAFT_FIELDS or preview.get("schema") != DRAFT_SCHEMA
        or preview.get("source_status") != SOURCE_STATUS
    ):
        raise ValueError("incompatible package review draft")
    digest = canonical_snapshot(preview)[1]
    if recorded_digest != digest:
        raise ValueError("recorded review does not match the package preview")
    if any(not isinstance(value, str) or not value.strip() for value in (reviewer, verbatim_decision)):
        raise ValueError("package review requires the reviewer and verbatim decision")
    if recorded_by != reviewer or recorded_quote != verbatim_decision:
        raise ValueError("recorded review does not match the original decision")
