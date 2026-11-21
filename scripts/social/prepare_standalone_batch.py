"""Prepare independent social review packages from one local JSON manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.social.prepare_batch import (
    _MAX_ITEMS,
    _MAX_MANIFEST_BYTES,
    _PACKAGE_ERRORS,
    _ManifestError,
    _invalid_component,
    _local_path,
)
from scripts.social.prepare_package import _DESTINATIONS, _unique_object
from scripts.social.prepare_standalone import _KINDS, _open_input, prepare_standalone


_REQUIRED_FIELDS = {"platform", "kind"}
_OPTIONAL_FIELDS = {"text_file", "media_file", "media_files", "comment_file", "account_id", "destination_id"}


class _SafeParser(argparse.ArgumentParser):
    """Report argument errors without repeating supplied values."""

    def error(self, message: str) -> None:
        self.exit(2, "Invalid arguments. Use --help for the supported options.\n")


def _read_manifest(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    if (
        (path.drive and not path.is_absolute())
        or path.suffix.lower() != ".json"
        or _invalid_component(path.name)
    ):
        raise ValueError("expected a local JSON manifest")
    parent = _local_path(path.parent, directory=True)
    with _open_input(parent, path.name, _MAX_MANIFEST_BYTES) as reader:
        data = reader.read(_MAX_MANIFEST_BYTES + 1)
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("manifest too large")
    manifest = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if (
        not isinstance(manifest, dict)
        or manifest.keys() != {"schema", "source_dir", "items"}
        or manifest["schema"] != "social-standalone-batch/1"
    ):
        raise ValueError("invalid manifest schema or fields")
    source_dir = manifest["source_dir"]
    items = manifest["items"]
    if not isinstance(source_dir, str) or not source_dir.strip() or not isinstance(items, list) or not items:
        raise ValueError("manifest requires a source directory and at least one item")
    if len(items) > _MAX_ITEMS:
        raise _ManifestError("too_many_manifest_items")
    source_path = Path(source_dir)
    if source_path.drive or source_path.root:
        raise ValueError("source_dir must be relative to the manifest")

    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if (
            not isinstance(item, dict)
            or not _REQUIRED_FIELDS <= item.keys() <= (_REQUIRED_FIELDS | _OPTIONAL_FIELDS)
            or any(not isinstance(value, str) or not value.strip()
                   for key, value in item.items() if key != "media_files")
            or item["platform"] not in _DESTINATIONS
            or item["kind"] not in _KINDS
        ):
            raise _ManifestError(f"invalid_manifest_item_{index}")
        if "media_files" in item and (
            not isinstance(item["media_files"], list)
            or any(not isinstance(value, str) or not value.strip() for value in item["media_files"])
        ):
            raise _ManifestError(f"invalid_manifest_item_{index}")
        identity = json.dumps(item, sort_keys=True)
        if identity in seen:
            raise _ManifestError(f"duplicate_manifest_item_{index}")
        seen.add(identity)
    return _local_path(parent / source_path, directory=True), items


def prepare_standalone_batch(*, manifest: Path, output_dir: Path) -> dict[str, Any]:
    """Prepare one package per manifest item and return the ordered results."""
    source_dir, items = _read_manifest(manifest)
    if (
        (output_dir.drive and not output_dir.is_absolute())
        or not output_dir.name
        or _invalid_component(output_dir.name)
    ):
        raise ValueError("a named, new batch directory is required")
    output_dir = _local_path(output_dir.parent, directory=True) / output_dir.name
    if any(parent.samefile(source_dir) for parent in output_dir.parents):
        raise ValueError("the output must be outside the source directory")
    output_dir.mkdir()

    results: list[dict[str, Any]] = []
    prepared = 0
    for index, item in enumerate(items, start=1):
        name = f"{index:02d}-{item['platform']}"
        result = {"item": index, "platform": item["platform"], "kind": item["kind"]}
        try:
            prepare_standalone(source_dir=source_dir, output_dir=output_dir / name, **item)
        except _PACKAGE_ERRORS:
            result.update(status="failed", error="package_preparation_failed")
        else:
            prepared += 1
            result.update(status="prepared_for_review", review=f"{name}/review.html")
        results.append(result)

    if prepared == len(items):
        status = "prepared_for_review"
    elif prepared:
        status = "partial"
    else:
        status = "failed"
    return {"status": status, "items": results}


def main() -> int:
    """Run local preparation and report success or failure as JSON."""
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    try:
        result = prepare_standalone_batch(**vars(parser.parse_args()))
    except _ManifestError as exc:
        result = {"status": "failed", "error": str(exc)}
    except (OSError, ValueError, RecursionError):
        result = {"status": "failed", "error": "check_manifest_source_and_new_output_directory"}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "prepared_for_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
