"""Build an offline social review package from local text or media files."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO

from PIL import Image

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.capabilities import capabilities
from scripts.social.channels.discord.direct import preview_message as preview_discord_message
from scripts.social.channels.discord.readonly_auth import _valid_id as valid_discord_id
from scripts.social.channels.facebook.direct import _text as validate_facebook_text
from scripts.social.channels.linkedin.direct import preview_post as preview_linkedin_post
from scripts.social.prepare_package import (
    _DESTINATIONS,
    _IMAGE_TYPES,
    _MAX_DOCUMENT,
    _MAX_MEDIA,
    _PACKAGE_EXTENSIONS,
    TELEGRAM_ALBUM_ACTION,
    _local_file,
    _media_metadata,
    _review_html,
)


_KINDS = ("text", "image", "video", "document")
IMAGE_ALBUM_ACTION = TELEGRAM_ALBUM_ACTION
TELEGRAM_ALBUM_COUNTS = range(2, 11)
TELEGRAM_ALBUM_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
TELEGRAM_PHOTO_LIMIT = 10_000_000
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096
DISCORD_ALBUM_TOTAL_LIMIT = 24 * 1024 * 1024
_ALBUM_RULES = {
    "telegram": (TELEGRAM_ALBUM_SUFFIXES, TELEGRAM_PHOTO_LIMIT),
    "discord": (frozenset(_IMAGE_TYPES), 20 * 1024 * 1024),
}
_CAPTIONLESS_ROUTES = frozenset({
    ("telegram", "post_image"),
    ("telegram", TELEGRAM_ALBUM_ACTION),
    ("telegram", "post_video"),
    ("telegram", "post_document"),
    ("youtube", "post_video"),
    ("tiktok", "upload_video"),
})


def _local_directory(path: Path) -> Path:
    if path.drive and not path.is_absolute():
        raise ValueError("drive-relative directories are forbidden")
    path = path.absolute()
    if path.drive.startswith(("\\\\", "//")) or any(
        part.casefold() == ".secret" or part.endswith((" ", ".")) for part in path.parts
    ):
        raise ValueError("expected a local, public-intent directory")
    for directory in reversed((path, *path.parents)):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x441400:
            raise ValueError("linked or cloud-placeholder directories are forbidden")
    resolved = path.resolve(strict=True)
    if resolved.drive.startswith(("\\\\", "//")) or any(
        part.casefold() == ".secret" for part in resolved.parts
    ):
        raise ValueError("expected a local, public-intent directory")
    return resolved


@contextmanager
def _open_input(root: Path, reference: str, limit: int) -> Iterator[BinaryIO]:
    path = _local_file(root, reference)
    before = path.lstat()
    # Where available, reject a substituted symlink and avoid blocking on a pipe.
    flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with open(path, "rb", opener=lambda name, mode: os.open(name, mode | flags)) as reader:
        opened = os.fstat(reader.fileno())
        if (
            not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
            or opened.st_size > limit or not os.path.samestat(before, opened)
            or not os.path.samestat(_local_file(root, reference).lstat(), opened)
        ):
            raise ValueError("input must be a stable, singly linked local file within the size limit")
        yield reader
        after = os.fstat(reader.fileno())
        if (
            after.st_nlink != 1 or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns or after.st_ctime_ns != opened.st_ctime_ns
            or not os.path.samestat(_local_file(root, reference).lstat(), after)
        ):
            raise ValueError("input changed while it was being read")


def _read_text(root: Path, reference: str) -> tuple[str, dict[str, str]]:
    if PurePosixPath(reference).suffix.lower() not in {".md", ".txt"}:
        raise ValueError("caption and comment must be UTF-8 .txt or .md files")
    with _open_input(root, reference, _MAX_DOCUMENT) as reader:
        data = reader.read(_MAX_DOCUMENT + 1)
    if len(data) > _MAX_DOCUMENT:
        raise ValueError("source document too large")
    original = data.decode("utf-8-sig")
    caption = original.strip()
    if not caption or "\x00" in caption:
        raise ValueError("expected nonempty plain text")
    return caption, {
        "file": reference,
        "text_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
    }


def _validate_content(
    platform: str, action: str, content: dict[str, str], *, destination_id: str | None = None,
) -> None:
    text = content["text"]
    comment = content.get("first_comment")
    if platform == "telegram":
        limit = TELEGRAM_MESSAGE_LIMIT if action == "post_text" else TELEGRAM_CAPTION_LIMIT
        if len(text.encode("utf-16-le")) // 2 > limit:
            raise ValueError("Telegram text exceeds the package limit")
    elif platform == "discord":
        if destination_id is not None and not valid_discord_id(destination_id):
            raise ValueError("invalid Discord destination ID")
        preview_discord_message(channel_id=destination_id or "1", text=text)
    elif platform == "facebook":
        validate_facebook_text(text)
        if comment is not None:
            if action == "post_video":
                raise ValueError("standalone Facebook video does not support a first comment")
            validate_facebook_text(comment)
    elif platform == "linkedin":
        preview_linkedin_post(author="urn:li:person:preview", api_version="202601", text=text)
        if comment is not None:
            preview_linkedin_post(author="urn:li:person:preview", api_version="202601", text=comment)


def _check_telegram_photo_dimensions(width: Any, height: Any) -> None:
    if (
        type(width) is not int or type(height) is not int or min(width, height) <= 0
        or width + height > 10_000 or max(width, height) > 20 * min(width, height)
    ):
        raise ValueError("Telegram album photo dimensions exceed the supported limits")


def _stage_media(
    root: Path, reference: str, staged: Path, kind: str, *, index: int | None = None,
    album_platform: str = "telegram",
) -> dict[str, Any]:
    suffix = PurePosixPath(reference).suffix.lower()
    allowed = {"image": _IMAGE_TYPES, "document": {".pdf"}, "video": {".mp4"}}
    suffixes, limit = _ALBUM_RULES[album_platform] if index is not None else (allowed[kind], _MAX_MEDIA)
    if suffix not in suffixes:
        raise ValueError("unsupported local attachment extension")
    prefix = "attachment" if index is None else f"attachment-{index}"
    attachment = staged / f"{prefix}{suffix}"
    digest = hashlib.sha256()
    length = 0
    with _open_input(root, reference, limit) as reader, attachment.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            length += len(chunk)
            if length > limit:
                raise ValueError("local attachment too large")
            digest.update(chunk)
            writer.write(chunk)
    metadata = _media_metadata(attachment, kind)
    if index is not None and album_platform == "telegram":
        _check_telegram_photo_dimensions(metadata["width"], metadata["height"])
    return {
        "file": attachment.name,
        "kind": kind,
        "bytes": length,
        "sha256": digest.hexdigest(),
        **metadata,
    }


def _review_standalone(package: dict[str, Any]) -> str:
    target = package["target"]
    account = html.escape(target["account_id"] or "Chưa chỉ định")
    destination = html.escape(target["destination_id"] or "Chưa chỉ định")
    context = f"<dl><dt>Tài khoản</dt><dd>{account}</dd><dt>ID đích</dt><dd>{destination}</dd></dl>"
    album = package["media"] if package["action"] == IMAGE_ALBUM_ACTION else None
    preview_package = {**package, "media": None} if album is not None else package
    review, end = _review_html(preview_package).rsplit("</html>", 1)
    if "text" not in package["source"]:
        review = review.replace("<pre></pre>", "<p>Không có caption hoặc mô tả.</p>", 1)
    if album is not None:
        context += "<ol>" + "".join(
            f'<li><img src="{html.escape(entry["file"])}" alt="Ảnh {index}"></li>'
            for index, entry in enumerate(album, start=1)
        ) + "</ol>"
    return f"{review}{context}</html>{end}"


def prepare_standalone(
    *,
    source_dir: Path,
    output_dir: Path,
    platform: str,
    kind: str,
    text_file: str | None = None,
    media_file: str | None = None,
    media_files: list[str] | None = None,
    comment_file: str | None = None,
    account_id: str | None = None,
    destination_id: str | None = None,
) -> Path:
    """Prepare one review-only package without a campaign or publication row."""
    if platform not in _DESTINATIONS or kind not in _KINDS:
        raise ValueError("unsupported platform or media kind")
    if media_files is not None:
        if (
            platform not in _ALBUM_RULES or kind != "image" or media_file is not None
            or not isinstance(media_files, list) or len(media_files) not in TELEGRAM_ALBUM_COUNTS
            or any(not isinstance(reference, str) or not reference for reference in media_files)
        ):
            raise ValueError("only Telegram and Discord standalone image albums accept 2–10 image files")
    elif (kind == "text") != (media_file is None) or media_file == "":
        raise ValueError("an attachment kind requires one media file")
    if comment_file is not None and platform not in {"facebook", "linkedin"}:
        raise ValueError("first comment preview is supported for Facebook and LinkedIn")
    if any(
        value is not None and (not value or len(value) > 128 or not value.isprintable() or value != value.strip())
        for value in (account_id, destination_id)
    ):
        raise ValueError("expected printable account and destination identifiers")

    destination = _DESTINATIONS[platform]
    action = "upload_video" if (platform, kind) == ("tiktok", "video") else f"post_{kind}"
    if media_files is not None:
        action = IMAGE_ALBUM_ACTION
    if text_file is None and (platform, action) not in _CAPTIONLESS_ROUTES:
        raise ValueError("this platform and action require a caption file")
    if media_files is None and (platform, kind) not in _PACKAGE_EXTENSIONS:
        capabilities(platform=platform, destination=destination, action=action)

    source_dir = _local_directory(source_dir)
    output_name = output_dir.name
    if (
        not output_name or output_name.casefold() == ".secret" or output_name.endswith((" ", "."))
        or PureWindowsPath(output_name).is_reserved()
        or any(char in output_name for char in '\\:<>*"|?')
    ):
        raise ValueError("expected a new output directory")
    output_dir = _local_directory(output_dir.parent) / output_name
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("output directory already exists")

    source: dict[str, Any] = {"type": "standalone_files"}
    content = {"text": ""}
    if text_file is not None:
        content["text"], source["text"] = _read_text(source_dir, text_file)
        content["text"] = content["text"].replace("\r\n", "\n")
    if comment_file is not None:
        content["first_comment"], source["first_comment"] = _read_text(source_dir, comment_file)
        content["first_comment"] = content["first_comment"].replace("\r\n", "\n")
    _validate_content(platform, action, content, destination_id=destination_id)
    package = {
        "schema": "social-standalone-package/1",
        "status": "prepared_for_review",
        "platform": platform,
        "destination": destination,
        "action": action,
        "target": {"account_id": account_id, "destination_id": destination_id},
        "source": source,
        "content": content,
        "media": None,
    }

    with tempfile.TemporaryDirectory(dir=output_dir.parent, prefix="social-standalone-") as staging_root:
        staged = Path(staging_root)
        if media_file is not None:
            source["media_file"] = media_file
            package["media"] = _stage_media(source_dir, media_file, staged, kind)
        elif media_files is not None:
            source["media_files"] = media_files.copy()
            package["media"] = [
                _stage_media(source_dir, reference, staged, "image", index=index, album_platform=platform)
                for index, reference in enumerate(source["media_files"], start=1)
            ]
            if (
                platform == "discord"
                and sum(item["bytes"] for item in package["media"]) > DISCORD_ALBUM_TOTAL_LIMIT
            ):
                raise ValueError("Discord album images exceed the combined package size limit")
        canonical_snapshot(package)
        (staged / "review.html").write_text(_review_standalone(package), encoding="utf-8")
        manifest = staged / "package.json"
        manifest.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_dir.mkdir()
        moved = []
        try:
            for path in sorted(staged.iterdir(), key=lambda item: item == manifest):
                moved.append(path.rename(output_dir / path.name))
        except OSError:
            for path in moved:
                path.unlink()
            output_dir.rmdir()
            raise
    return output_dir


def main() -> None:
    """Run the local packager and print the review path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--text-file", help="caption relative to --source-dir (optional on supported media routes)")
    parser.add_argument("--platform", choices=sorted(_DESTINATIONS), required=True)
    parser.add_argument("--kind", choices=_KINDS, required=True)
    media = parser.add_mutually_exclusive_group()
    media.add_argument("--media-file", help="attachment relative to --source-dir")
    media.add_argument("--media-files", nargs="+", help="ordered Telegram or Discord images relative to --source-dir")
    parser.add_argument("--comment-file", help="first comment relative to --source-dir")
    parser.add_argument("--account-id")
    parser.add_argument("--destination-id")
    try:
        output = prepare_standalone(**vars(parser.parse_args()))
    except (OSError, ValueError, subprocess.SubprocessError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        parser.exit(2, "Social package failed: check the channel, local inputs and new output directory.\n")
    print(output / "review.html")


if __name__ == "__main__":
    main()
