"""Prepare a batch of offline review packages from a local JSON manifest."""
from __future__ import annotations

import argparse
import json
import stat
import subprocess
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml
from PIL import Image

from scripts.social.prepare_package import _DESTINATIONS, _unique_object, prepare_package


_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_ITEMS = 9
_REQUIRED_FIELDS = {"post_id", "platform", "kind"}
_OPTIONAL_FIELDS = {"text_file", "comment_file", "media_file"}
_ORDERED_FIELDS = {"media_files", "caption_files"}
_PACKAGE_ERRORS = (
    OSError, ValueError, RecursionError, subprocess.SubprocessError, yaml.YAMLError,
    Image.DecompressionBombError, Image.DecompressionBombWarning,
)


class _ManifestError(ValueError):
    """Manifest validation error whose message is safe to print."""


def _invalid_component(part: str) -> bool:
    name = part.casefold()
    return (
        name in {"..", ".secret", "auth.json", "oauth_creds.json"}
        or name.startswith(".env")
        or name.endswith((".credentials.json", ".key", ".pem", " ", "."))
        or any(char in part for char in '\\:<>*"|?')
        or any(ord(char) < 32 for char in part)
        or PureWindowsPath(part).is_reserved()
    )


def _local_path(path: Path, *, directory: bool) -> Path:
    path = path.absolute()
    if path.anchor.startswith(("\\\\", "//")) or any(map(_invalid_component, path.parts[1:])):
        raise ValueError("unsafe local path")
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x441400:
            raise ValueError("linked or cloud-placeholder input paths are forbidden")
        expected_directory = component != path or directory
        if expected_directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError("expected a local directory")
        if not expected_directory and not stat.S_ISREG(info.st_mode):
            raise ValueError("expected a local regular file")
    return path


def _read_manifest(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    if path.suffix.lower() != ".json":
        raise ValueError("manifest must be a JSON file")
    path = _local_path(path, directory=False)
    with path.open("rb") as source:
        data = source.read(_MAX_MANIFEST_BYTES + 1)
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    manifest = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or manifest.keys() != {"schema", "source_dir", "items"}:
        raise ValueError("invalid manifest fields")
    if manifest["schema"] != "social-batch/1":
        raise ValueError("unsupported manifest schema")
    source_dir = manifest["source_dir"]
    items = manifest["items"]
    if not isinstance(source_dir, str) or not source_dir.strip() or not isinstance(items, list) or not items:
        raise ValueError("manifest requires a source directory and at least one item")
    if len(items) > _MAX_ITEMS:
        raise _ManifestError("too_many_manifest_items")
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if (
            not isinstance(item, dict)
            or not _REQUIRED_FIELDS <= item.keys() <= (_REQUIRED_FIELDS | _OPTIONAL_FIELDS | _ORDERED_FIELDS)
            or any(not isinstance(value, str) or not value.strip()
                   for key, value in item.items() if key not in _ORDERED_FIELDS)
            or any(not isinstance(item[key], list) or not item[key]
                   or any(not isinstance(value, str) or not value.strip() for value in item[key])
                   for key in _ORDERED_FIELDS & item.keys())
            or item["platform"] not in _DESTINATIONS
            or item["kind"] not in {"text", "image", "video", "document"}
        ):
            raise _ManifestError(f"invalid_manifest_item_{index}")
        identity = json.dumps(item, sort_keys=True)
        if identity in seen:
            raise _ManifestError(f"duplicate_manifest_item_{index}")
        seen.add(identity)
    source_path = Path(source_dir)
    if source_path.drive or source_path.root:
        raise ValueError("source_dir must be relative to the manifest")
    return _local_path(path.parent / source_path, directory=True), items


def prepare_batch(*, manifest: Path, output_dir: Path) -> list[dict[str, Any]]:
    """Create a fresh batch directory and return the outcome of each item in order."""
    source_dir, items = _read_manifest(manifest)
    if not output_dir.name or _invalid_component(output_dir.name):
        raise ValueError("a named, new batch directory is required")
    output_dir = _local_path(output_dir.parent, directory=True) / output_dir.name
    if any(parent.samefile(source_dir) for parent in output_dir.parents):
        raise ValueError("the output must be outside the source directory")
    output_dir.mkdir()

    results: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        name = f"{index:02d}-{item['platform']}"
        result = {"item": index, "platform": item["platform"], "kind": item["kind"]}
        try:
            prepare_package(source_dir=source_dir, output_dir=output_dir / name, **item)
        except _PACKAGE_ERRORS:
            result.update(status="failed", error="package_preparation_failed")
        else:
            result.update(status="prepared_for_review", review=f"{name}/review.html")
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        results = prepare_batch(manifest=args.manifest, output_dir=args.output_dir)
    except _ManifestError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 2
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "failed", "error": "check_manifest_source_and_new_output_directory"}))
        return 2
    failed = any(item["status"] == "failed" for item in results)
    if failed:
        status = "partial" if any(item["status"] == "prepared_for_review" for item in results) else "failed"
    else:
        status = "prepared_for_review"
    print(json.dumps({"status": status, "items": results}, indent=2))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
