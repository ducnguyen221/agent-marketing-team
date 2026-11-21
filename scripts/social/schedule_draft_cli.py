"""Store and inspect local schedule drafts for prepared Social V2 packages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.approval_package_v2 import (
    _checked_package_file,
    _local_directory,
    _read_package_manifest,
)
from scripts.social.dispatch_package_v2 import _prepare_bound_route
from scripts.social.prepare_package import _MAX_DOCUMENT, _unique_object
from scripts.social.schedule_v2 import ScheduleError, ScheduleStore, _reject_secret_path


def _read_package(path: Path, expected_digest: str | None) -> tuple[Path, dict[str, Any], str]:
    _reject_secret_path(path)
    _reject_secret_path(Path(os.path.abspath(path)))
    root = _local_directory(path)
    _reject_secret_path(root)
    with _checked_package_file(root, "package.json") as source:
        package = _read_package_manifest(source)
        if package["schema"] != "social-package/1" or package["status"] != "prepared_for_review":
            raise ValueError("expected a prepared V2 package")
        origin = package["source"]
        if not isinstance(origin, dict) or not isinstance(origin.get("post_id"), str):
            raise ValueError("invalid V2 post ID")
        _, digest = canonical_snapshot(package)
        if expected_digest is not None and expected_digest != digest:
            raise ScheduleError("schedule_package_digest_mismatch")
    return root, package, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--directory", required=True, type=Path)
    operations = parser.add_subparsers(dest="command", required=True)
    operations.add_parser("init", allow_abbrev=False)
    put = operations.add_parser("put", allow_abbrev=False)
    put.add_argument("--package-dir", required=True, type=Path)
    put.add_argument("--expected-package-sha256")
    scope_fields = ("station_id", "channel_id", "campaign_id", "content_id")
    dest_fields = ("account_id", "destination_id", "occurrence_key")
    for field in (*scope_fields, *dest_fields, "scheduled_at", "timezone"):
        put.add_argument(f"--{field.replace('_', '-')}", required=True)
    put.add_argument("--privacy", required=True)
    put.add_argument("--options-stdin", required=True, action="store_true", help="read delivery options as a JSON object")
    get = operations.add_parser("get", allow_abbrev=False)
    get.add_argument("intent_id")
    operations.add_parser("due", allow_abbrev=False)
    readiness = operations.add_parser("readiness", allow_abbrev=False)
    readiness.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    try:
        directory = args.directory
        store = ScheduleStore(directory, isolated_parent=directory.parent)
        if args.command == "init":
            store.initialize()
            result = {"status": "initialized"}
        elif args.command == "put":
            raw_options = sys.stdin.buffer.read(_MAX_DOCUMENT + 1)
            if len(raw_options) > _MAX_DOCUMENT:
                raise ScheduleError("invalid_schedule_review_options")
            options = json.loads(raw_options.decode("utf-8-sig"), object_pairs_hook=_unique_object)
            package_root, package, digest = _read_package(
                args.package_dir, args.expected_package_sha256,
            )
            route = _prepare_bound_route(
                package_root, package, package_digest=digest, account_id=args.account_id,
                destination_id=args.destination_id, occurrence_id=args.occurrence_key, options=options,
            )["binding"]
            identity = {field: getattr(args, field) for field in (*scope_fields, *dest_fields)}
            identity.update(platform=route["platform"], post_id=package["source"]["post_id"])
            intent_id = store.put(
                identity, scheduled_at=args.scheduled_at, timezone_name=args.timezone,
                package_sha256=digest, action=route["action"], destination_kind=route["destination"],
                privacy=args.privacy, delivery_options=route["options"],
            )
            result = {
                "status": "intent_returned", "intent_id": intent_id, "package_sha256": digest,
                "source_status": "unverified",
            }
        elif args.command == "get":
            record = store.get(args.intent_id)
            result = {
                "intent_id": args.intent_id, "snapshot": record["snapshot"], "binding": record["binding"],
                "revision": record["revision"], "status": record["status"], "source_status": "unverified",
            }
        elif args.command == "due":
            result = {"due_intent_ids": store.due()}
        else:
            from scripts.social.schedule_readiness import check_due_readiness

            result = check_due_readiness(store, directory, args.manifest)
            print(json.dumps(result, sort_keys=True))
            return 3
    except ScheduleError as exc:
        result = {"status": "blocked", "reason": str(exc)}
    except (OSError, ValueError, TypeError, LookupError, AttributeError, RecursionError):
        result = {"status": "blocked", "reason": "invalid_local_schedule_or_package"}

    print(json.dumps(result, sort_keys=True))
    return 2 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
