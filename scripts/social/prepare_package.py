"""Prepare an offline, reviewable social package from local V1 files."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import stat
import subprocess
import tempfile
import warnings
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from PIL import Image

import yaml

from scripts.lib.delivery_anchors import _split_frontmatter, _valid_identity, extract_delivery_anchor, preview_facebook_post
from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.capabilities import capabilities
from scripts.social.channels.facebook.direct import _text as validate_facebook_text
from scripts.social.channels.facebook.direct import preview_reel_anchor
from scripts.social.channels.youtube.direct import preview_marketing_anchor as preview_youtube_anchor


_MAX_DOCUMENT = 2 * 1024 * 1024
_MAX_MEDIA = 256 * 1024 * 1024
_IMAGE_TYPES = {".png": "PNG", ".jpeg": "JPEG", ".jpg": "JPEG", ".webp": "WEBP"}
IMAGE_ALBUM_ACTION = "post_image_album"
TELEGRAM_ALBUM_ACTION = IMAGE_ALBUM_ACTION
_DESTINATIONS = {
    "facebook": "page", "telegram": "channel", "linkedin": "account",
    "threads": "account", "x": "account", "discord": "channel",
    "instagram": "account", "youtube": "channel", "tiktok": "profile",
}
_PACKAGE_EXTENSIONS = {
    ("x", "image"), ("x", "video"),
    ("discord", "image"), ("discord", "video"),
    ("telegram", "document"), ("discord", "document"),
}


def _local_file(root: Path, reference: str) -> Path:
    path = PurePosixPath(reference)
    if (
        not path.parts
        or path.is_absolute()
        or str(path) != reference
        or any(char in reference for char in "\\:<>*\"|?#")
        or any(
            part in {".", ".."}
            or part.startswith(".")
            or part.endswith((" ", "."))
            or PureWindowsPath(part).is_reserved()
            or any(ord(char) < 32 for char in part)
            for part in path.parts
        )
    ):
        raise ValueError("invalid local file reference")
    candidate = root
    for part in path.parts:
        candidate /= part
        info = candidate.lstat()
        # Reject reparse points and Windows cloud placeholders without hydrating them.
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x441400:
            raise ValueError("linked or cloud-placeholder input paths are forbidden")
    if not stat.S_ISREG(info.st_mode) or candidate.resolve(strict=True) != candidate:
        raise ValueError("expected a local regular file")
    return candidate


def _document(root: Path, name: str) -> str:
    with _local_file(root, name).open("rb") as source:
        data = source.read(_MAX_DOCUMENT + 1)
    if len(data) > _MAX_DOCUMENT:
        raise ValueError("source document too large")
    return data.decode("utf-8-sig")


def _unique_object(entries: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in entries:
        if key in result:
            raise ValueError("duplicate publication field")
        result[key] = value
    return result


def _structured_source(content: str, publication: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    header, _ = _split_frontmatter(content)
    if header is None:
        raise ValueError("source content identity missing")
    metadata = yaml.compose(header, Loader=yaml.SafeLoader)
    values: dict[str, str] = {}
    if not isinstance(metadata, yaml.MappingNode):
        raise ValueError("source content identity invalid")
    string_tag = "tag:yaml.org,2002:str"
    if metadata.tag != "tag:yaml.org,2002:map":
        raise ValueError("unsupported source metadata mapping")
    for key, value in metadata.value:
        if not isinstance(key, yaml.ScalarNode) or key.tag != string_tag or key.value in values:
            raise ValueError("source metadata keys must be unique")
        if key.value in {"schema", "content_id", "campaign_id"} and (
            not isinstance(value, yaml.ScalarNode) or value.tag != string_tag
        ):
            raise ValueError("source identity fields must be strings")
        values[key.value] = value.value if isinstance(value, yaml.ScalarNode) else ""
    anchor = row.get("post_content")
    channel, post_format = row.get("channel"), row.get("post_format")
    if not isinstance(channel, str) or not isinstance(post_format, str):
        raise ValueError("unknown V1 source format")
    allowed = {
        ("youtube", "youtube_video"): {"post:youtube_desc", "post:youtube_video"},
        ("youtube", "youtube_short"): {"post:youtube_short"},
        ("facebook", "reel"): {"post:reel"},
        ("facebook", "carousel"): {"post:carousel"},
        ("facebook", "infographic"): {"post:infographic"},
    }.get((channel, post_format), set())
    if (
        values.get("schema") != "content/1" or publication.get("schema") != "publish/2"
        or not _valid_identity(publication.get("post_id")) or not _valid_identity(publication.get("campaign_id"))
        or values.get("content_id") != publication.get("post_id")
        or values.get("campaign_id") != publication.get("campaign_id")
        or row.get("content_id") != publication.get("post_id")
        or not isinstance(anchor, str) or re.sub(r"#[1-9][0-9]*$", "", anchor) not in allowed
        or sum(item.get("post_content") == anchor for item in publication["posts"]) != 1
    ):
        raise ValueError("V1 source identity or anchor mismatch")
    if post_format == "reel":
        body = preview_reel_anchor(source=content, anchor=anchor, page_id="1", api_version="v23.0",
                                   media_id="fixture-video")["caption"]
    else:
        # Bind the real heading first. Feed only its block to the existing
        # description or single-Caption parser, preserving the original anchor below.
        block = extract_delivery_anchor(content, anchor)
        parser_anchor = "post:youtube_desc" if post_format == "youtube_video" else "post:youtube_short"
        preview = preview_youtube_anchor(source=f"## {parser_anchor}\n{block}", anchor=parser_anchor,
                                         title="Preview", category_id="1", privacy="private",
                                         made_for_kids=False, media_id="fixture-video")
        body = preview["request"]["body"]["snippet"]["description"]
    return {"post_id": row["post_id"], "anchor": anchor,
            "body_raw": body, "first_comment_raw": None}


def _media_metadata(staged_file: Path, kind: str) -> dict[str, int]:
    if kind == "image":
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(staged_file, formats=list(_IMAGE_TYPES.values())) as image:
                if image.format != _IMAGE_TYPES[staged_file.suffix] or image.n_frames != 1:
                    raise ValueError("image format mismatch or animation")
                size = image.size
                image.verify()
            with Image.open(staged_file, formats=list(_IMAGE_TYPES.values())) as image:
                image.load()
    elif kind == "document":
        with staged_file.open("rb") as source:
            if not source.read(8).startswith(b"%PDF-"):
                raise ValueError("invalid PDF signature")
        return {}
    else:
        probe = shutil.which("ffprobe")
        if probe is None:
            raise ValueError("ffprobe is required for MP4")
        result = subprocess.run(
            [
                probe, "-v", "error", "-protocol_whitelist", "file",
                "-f", "mov", "-enable_drefs", "0", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_name", "-of", "json",
                str(staged_file),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=True,
        )
        streams = json.loads(result.stdout).get("streams")
        if not streams or not streams[0].get("codec_name"):
            raise ValueError("MP4 video stream is missing")
        size = (streams[0].get("width"), streams[0].get("height"))
    if any(not isinstance(value, int) or value <= 0 for value in size):
        raise ValueError("invalid media dimensions")
    return {"width": size[0], "height": size[1]}


def _copy_media(root: Path, reference: str, staged: Path, kind: str) -> dict[str, Any]:
    source = _local_file(root, reference)
    suffix = source.suffix.lower()
    allowed = _IMAGE_TYPES if kind == "image" else {".pdf"} if kind == "document" else {".mp4"}
    if suffix not in allowed:
        raise ValueError("unsupported local attachment extension")
    name = f"attachment{suffix}"
    digest = hashlib.sha256()
    length = 0
    with source.open("rb") as reader, (staged / name).open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            length += len(chunk)
            if length > _MAX_MEDIA:
                raise ValueError("local attachment too large")
            digest.update(chunk)
            writer.write(chunk)
    metadata = _media_metadata(staged / name, kind)
    return {"file": name, "kind": kind, "bytes": length, "sha256": digest.hexdigest(), **metadata}


def _review_html(package: dict[str, Any]) -> str:
    caption = html.escape(package["content"]["text"])
    text_preview = f"<pre>{caption}</pre>"
    first_comment = package["content"].get("first_comment")
    comment = f"<h2>Bình luận đầu tiên</h2><pre>{html.escape(first_comment)}</pre>" if first_comment else ""
    media = package["media"]
    preview = ""
    if isinstance(media, list):
        captions = package["content"].get("captions")
        if captions is not None:
            text_preview = ""
        entries = []
        for index, entry in enumerate(media, start=1):
            photo = f'<img src="{html.escape(entry["file"])}" alt="Ảnh {index}">'
            caption_preview = f'<pre>{html.escape(captions[index - 1])}</pre>' if captions is not None else ""
            entries.append(f"<li>{photo}{caption_preview}</li>")
        preview = "<ol>" + "".join(entries) + "</ol>"
    elif media:
        name = media["file"]
        if media["kind"] == "image":
            preview = f'<img src="{name}" alt="Ảnh đính kèm">'
        elif media["kind"] == "video":
            preview = f'<video src="{name}" controls preload="metadata"></video>'
        else:
            preview = f'<a href="{name}" download>Tải PDF đính kèm</a>'
    title = f'{package["platform"]} / {package["destination"]} / {package["action"]}'
    return f"""<!doctype html>
<html lang="vi"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gói social để xem trước</title>
<style>body{{font:1rem system-ui;max-width:760px;margin:3rem auto;padding:0 1rem}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}} img,video{{max-width:100%;height:auto}}</style>
<h1>{title}</h1><p>Bản chuẩn bị để xem trước.</p>{text_preview}{preview}{comment}
</html>
"""


def prepare_package(
    *, source_dir: Path, output_dir: Path, post_id: str, platform: str, kind: str,
    text_file: str | None = None, comment_file: str | None = None, media_file: str | None = None,
    media_files: list[str] | None = None, caption_files: list[str] | None = None,
) -> Path:
    """Prepare one destination package. The source directory must contain public-intent inputs."""
    if platform not in _DESTINATIONS or kind not in {"text", "image", "video", "document"}:
        raise ValueError("unsupported destination or media kind")
    if media_file is not None and (kind == "text" or not media_file):
        raise ValueError("media file requires an attachment kind")
    if media_files is not None:
        from scripts.social.prepare_standalone import TELEGRAM_ALBUM_COUNTS, _local_directory

        if (
            platform not in {"telegram", "discord"} or kind != "image" or media_file is not None
            or not isinstance(media_files, list) or len(media_files) not in TELEGRAM_ALBUM_COUNTS
            or any(not isinstance(reference, str) or not reference for reference in media_files)
        ):
            raise ValueError("only Telegram and Discord image albums accept 2–10 ordered media files")
        if platform == "discord" and (text_file is None or caption_files is not None):
            raise ValueError("Discord image albums require one message text file for all images")
        source_dir = _local_directory(source_dir)
    if caption_files is not None and (
        media_files is None or text_file is not None or not isinstance(caption_files, list)
        or len(caption_files) != len(media_files)
        or any(not isinstance(reference, str) or not reference for reference in caption_files)
    ):
        raise ValueError("album caption files must correspond to the images and replace the text file")
    if platform == "facebook" and text_file is not None:
        raise ValueError("Facebook text is read from the source anchor")
    if text_file is not None and PurePosixPath(text_file).suffix.lower() != ".txt":
        raise ValueError("channel text must be a dedicated .txt file")
    if comment_file is not None:
        if platform not in {"facebook", "linkedin"} or PurePosixPath(comment_file).suffix.lower() != ".txt":
            raise ValueError("a dedicated .txt comment file is supported for Facebook Page and LinkedIn")
        if platform == "facebook" and kind not in {"text", "image"}:
            raise ValueError("a dedicated Facebook Page comment requires a text or image package")
    if any(part.casefold() == ".secret" for part in source_dir.absolute().parts):
        raise ValueError("secret store paths are forbidden")
    source_dir = source_dir.resolve(strict=True)
    output_dir = output_dir.parent.resolve(strict=True) / output_dir.name
    if any(
        directory.drive.startswith(("\\\\", "//"))
        or any(part.casefold() == ".secret" for part in directory.parts)
        for directory in (source_dir, output_dir)
    ):
        raise ValueError("only local, public-intent directories are supported")
    if output_dir.is_relative_to(source_dir) or output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output must be a new directory outside the V1 source")

    destination = _DESTINATIONS[platform]
    action = "upload_video" if (platform, kind) == ("tiktok", "video") else f"post_{kind}"
    if media_files is not None:
        action = IMAGE_ALBUM_ACTION
    elif (platform, kind) not in _PACKAGE_EXTENSIONS:
        capabilities(platform=platform, destination=destination, action=action)
    publication = json.loads(_document(source_dir, "publish.json"), object_pairs_hook=_unique_object)
    rows = publication.get("posts") if isinstance(publication, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or not _valid_identity(post_id):
        raise ValueError("invalid V1 publication")
    matches = [row for row in rows if row.get("post_id") == post_id]
    if len(matches) != 1:
        raise ValueError("V1 post is missing or ambiguous")
    row = matches[0]
    raw_content = _document(source_dir, "content.md")
    native_video = platform in {"youtube", "tiktok"} and row.get("channel") == "youtube"
    if row.get("post_format") == "facebook_post":
        source = preview_facebook_post(raw_content, publication, post_id=post_id)
    else:
        source = _structured_source(raw_content, publication, row)
    if platform == "facebook" and row.get("channel") != "facebook":
        raise ValueError("Facebook requires a Facebook source")
    if platform == "facebook" and row.get("post_format") == "reel":
        raise ValueError("native Facebook Reel delivery is unsupported")
    if platform == "facebook" and row.get("post_format") == "carousel":
        raise ValueError("native Facebook multi-image carousel is unsupported")
    if platform == "facebook" and row.get("post_format") == "infographic" and kind != "image":
        raise ValueError("Facebook infographic source requires an image")
    if platform != "facebook" and text_file is None and not native_video and media_files is None:
        raise ValueError("a separate channel text file is required for cross-channel reuse")
    if media_files is not None:
        from scripts.social.prepare_standalone import _read_text

        if platform == "discord":
            from scripts.social.channels.discord.direct import preview_message

            text = _read_text(source_dir, text_file)[0]
            preview_message(channel_id="1", text=text)
        else:
            captions = [""] * len(media_files)
            if caption_files is not None:
                captions = ["" if path == "-" else _read_text(source_dir, path)[0] for path in caption_files]
            elif text_file is not None:
                captions[0] = _read_text(source_dir, text_file)[0]
            validate_telegram_album_captions(captions)
            text = captions[0]
    else:
        text = source["body_raw"].strip() if text_file is None else _document(source_dir, text_file).strip()
    if not text and platform not in {"youtube", "tiktok"} and media_files is None:
        raise ValueError("channel text is missing")
    content = {"text": text}
    comment = None
    if comment_file is not None:
        comment = _document(source_dir, comment_file).strip()
        if not comment:
            raise ValueError("comment text is missing")
    elif platform == "facebook" and source["first_comment_raw"]:
        comment = source["first_comment_raw"].strip()
    if comment is not None:
        if platform == "facebook":
            if kind == "video":
                raise ValueError("Facebook video delivery does not support a first comment")
            comment = validate_facebook_text(comment)
        content["first_comment"] = comment
    package = {
        "schema": "social-package/1",
        "status": "prepared_for_review",
        "platform": platform,
        "destination": destination,
        "action": action,
        "source": {"post_id": source["post_id"], "anchor": source["anchor"]},
        "content": content,
        "media": None,
    }
    canonical_snapshot(package)
    with tempfile.TemporaryDirectory(dir=output_dir.parent, prefix="social-package-") as staging_root:
        staged = Path(staging_root) / "package"
        staged.mkdir()
        if media_files is not None:
            from scripts.social.prepare_standalone import DISCORD_ALBUM_TOTAL_LIMIT, _stage_media

            package["source"]["media_files"] = media_files.copy()
            if caption_files is not None:
                package["source"]["caption_files"] = caption_files.copy()
            if text_file is not None:
                package["source"]["text_file"] = text_file
            if platform == "telegram":
                content["captions"] = captions
            package["media"] = [
                _stage_media(source_dir, reference, staged, "image", index=index, album_platform=platform)
                for index, reference in enumerate(media_files, start=1)
            ]
            if platform == "discord" and sum(item["bytes"] for item in package["media"]) > DISCORD_ALBUM_TOTAL_LIMIT:
                raise ValueError("Discord album images exceed the combined package size limit")
        elif kind != "text":
            reference = media_file if media_file is not None else row.get("asset_ref", "")
            if kind == "image" and reference == "" and row.get("post_format") not in {"carousel", "infographic"}:
                reference = "thumbnail.png"
            if kind == "video" and native_video and reference == "":
                reference = "short.mp4" if row["post_format"] == "youtube_short" else "video.mp4"
            if kind == "video" and row.get("post_format") == "reel" and reference == "":
                reference = "short.mp4"
            if not isinstance(reference, str) or not reference:
                raise ValueError("media requires an explicit V1 asset_ref")
            package["media"] = _copy_media(source_dir, reference, staged, kind)
        canonical_snapshot(package)
        (staged / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staged / "review.html").write_text(_review_html(package), encoding="utf-8")
        staged.rename(output_dir)
    return output_dir


def validate_telegram_album_captions(captions: list[str]) -> None:
    from scripts.social.prepare_standalone import TELEGRAM_CAPTION_LIMIT

    if any(
        not isinstance(caption, str) or "\x00" in caption
        or len(caption.encode("utf-16-le")) // 2 > TELEGRAM_CAPTION_LIMIT
        for caption in captions
    ):
        raise ValueError("Telegram album caption exceeds the package limit or is invalid")


def main() -> None:
    """Parse CLI arguments and report only sanitized input errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--platform", choices=sorted(_DESTINATIONS), default="facebook")
    parser.add_argument("--kind", choices=("text", "image", "video", "document"), required=True)
    parser.add_argument("--text-file")
    parser.add_argument("--comment-file")
    media = parser.add_mutually_exclusive_group()
    media.add_argument("--media-file", help="attachment path relative to the source directory")
    media.add_argument("--media-files", nargs="+", help="ordered Telegram or Discord album images relative to the source directory")
    parser.add_argument("--caption-files", nargs="+", help="Telegram album caption files in image order; use - to omit a caption")
    try:
        output = prepare_package(**vars(parser.parse_args()))
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError, yaml.YAMLError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        parser.exit(2, "Social package failed: check the V1 binding, local input files and output directory.\n")
    print(output / "review.html")


if __name__ == "__main__":
    main()
