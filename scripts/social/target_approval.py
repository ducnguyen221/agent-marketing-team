"""Record and inspect local operator decisions for a single Social V2 target."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.lib.delivery_ledger import SCOPE_FIELDS
from scripts.social.approval_package_v2 import _checked_package_file, _local_directory
from scripts.social.prepare_package import _MAX_DOCUMENT, _unique_object
from scripts.social.review_snapshot import DRAFT_FIELDS, DRAFT_SCHEMA, SOURCE_STATUS, canonical_review
from scripts.social.schedule_v2 import SHA256, _file_info, _parse_schedule_time, _schedule_time

_SCHEMA = "social-target-decisions/2"


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def read_operator_json() -> Any:
    data = sys.stdin.buffer.read(_MAX_DOCUMENT + 1)
    if len(data) > _MAX_DOCUMENT:
        raise ValueError("operator input too large")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)


def target_key(review: dict[str, Any]) -> str:
    """Keep history together when a reviewed package or schedule changes."""
    return canonical_snapshot({
        "schema": _SCHEMA,
        "scope": review["claimed_scope"],
        **{field: review[field] for field in (
            "platform", "account_id", "destination_id", "occurrence_key",
        )},
    })[1]


def _validate_snapshot(snapshot: Any, key: str) -> None:
    if not isinstance(snapshot, dict) or set(snapshot) != {"review", "source_gate_digests"}:
        raise ValueError("invalid target decision snapshot")
    gates = snapshot["source_gate_digests"]
    if (not isinstance(gates, dict) or set(gates) not in ({"g1", "g2"}, {"g1", "g2", "g3"})
            or not all(map(_is_digest, gates.values()))):
        raise ValueError("invalid target decision snapshot")
    review = snapshot["review"]
    if (not isinstance(review, dict) or review.keys() != DRAFT_FIELDS
            or review["schema"] != DRAFT_SCHEMA or review["source_status"] != SOURCE_STATUS):
        raise ValueError("invalid target review schema")
    scope = review["claimed_scope"]
    options = review["delivery_options"]
    if (not isinstance(scope, dict) or scope.keys() != set(SCOPE_FIELDS)
            or scope["gate"] != "g2" or scope["post_id"] == "*"
            or not isinstance(options, dict) or options.get("privacy", review["privacy"]) != review["privacy"]
            or not _is_digest(review["package_digest"])):
        raise ValueError("invalid target review scope or settings")
    required = (*scope.values(), *(review[field] for field in (
        "platform", "destination_kind", "action", "account_id", "destination_id", "occurrence_key", "timezone", "privacy",
    )))
    if any(not isinstance(value, str) or not value.strip() for value in required):
        raise ValueError("incomplete target review scope or settings")
    if review["scheduled_at"] is not None:
        _parse_schedule_time(review["scheduled_at"])
    canonical, _ = canonical_review(**{
        field: review[field] for field in DRAFT_FIELDS - {"schema", "source_status"}
    })
    if canonical != review or target_key(review) != key:
        raise ValueError("invalid target decision snapshot")


def _operator_fields(request: Any, *, approve: bool) -> tuple[str, str, str | None]:
    expected = {"decision", "by", "quote", "expected_head"}
    if approve:
        expected.add("expected_review")
    if (not isinstance(request, dict) or set(request) != expected
            or request["decision"] != ("approve" if approve else "revoke")):
        raise ValueError("invalid operator decision fields")
    by, quote, head = (request[key] for key in ("by", "quote", "expected_head"))
    _validate_operator_quote(by, quote)
    if (head is not None and not _is_digest(head)) or (approve and not _is_digest(request["expected_review"])):
        raise ValueError("invalid operator decision reference")
    return by, quote, head


def _validate_operator_quote(by: Any, quote: Any) -> None:
    if (not isinstance(by, str) or not by.isprintable() or not by.strip() or len(by) > 128
            or not isinstance(quote, str) or not quote.strip() or len(quote) > 4096
            or any(not (char.isprintable() or char in "\r\n\t") for char in quote)):
        raise ValueError("invalid operator decision evidence")


class TargetDecisions:
    """Serialize updates and retain prior decisions in an atomically replaced journal."""

    def __init__(self, directory: Path, key: str) -> None:
        if not _is_digest(key):
            raise ValueError("invalid target key")
        self.directory = _local_directory(directory)
        self.directory_info = self.directory.stat()
        self.key = key
        self.path = self.directory / f"{key}.json"
        self.marker = self.directory / f"{key}.initialized"

    def _check_directory(self) -> None:
        if not os.path.samestat(self.directory_info, _file_info(self.directory, directory=True)):
            raise ValueError("target decision directory changed")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._check_directory()
        lock_path = self.directory / f"{self.key}.lock"
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(lock_path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            _file_info(lock_path)
            fd = os.open(lock_path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not os.path.samestat(info, _file_info(lock_path)):
                raise ValueError("target decision lock changed")
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            elif os.name == "posix":
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                raise ValueError("target decision locking unavailable")
            self._check_directory()
            yield
        finally:
            os.close(fd)

    def history(self) -> list[dict[str, Any]]:
        self._check_directory()
        try:
            _file_info(self.marker)
        except FileNotFoundError:
            try:
                self.path.lstat()
            except FileNotFoundError:
                return []
            raise ValueError("target decision initialization marker missing") from None
        try:
            self.path.lstat()
        except FileNotFoundError:
            raise ValueError("initialized target decision journal is missing") from None
        with _checked_package_file(self.directory, self.path.name) as stream:
            raw = stream.read(_MAX_DOCUMENT + 1)
        if len(raw) > _MAX_DOCUMENT:
            raise ValueError("target decision history too large")
        journal = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(journal, dict) or set(journal) != {"schema", "target_key", "decisions"}
                or journal["schema"] != _SCHEMA or journal["target_key"] != self.key
                or not isinstance(journal["decisions"], list) or not journal["decisions"]):
            raise ValueError("invalid target decision history")
        head = None
        previous = None
        for entry in journal["decisions"]:
            if not isinstance(entry, dict) or set(entry) != {
                "id", "previous", "decision", "snapshot", "by", "quote", "at",
            }:
                raise ValueError("invalid target decision")
            payload = {key: value for key, value in entry.items() if key != "id"}
            snapshot = entry["snapshot"]
            _validate_snapshot(snapshot, self.key)
            _validate_operator_quote(entry["by"], entry["quote"])
            at = entry["at"]
            if not isinstance(at, str) or not at.endswith("+00:00") or datetime.fromisoformat(at).isoformat() != at:
                raise ValueError("invalid target decision timestamp")
            if (entry["previous"] != head or canonical_snapshot(payload)[1] != entry["id"]
                    or entry["decision"] not in ("approved", "revoked")
                    or (entry["decision"] == "revoked" and (
                        previous is None or previous["decision"] != "approved"
                        or previous["snapshot"] != snapshot
                    ))):
                raise ValueError("target decision history is inconsistent")
            head, previous = entry["id"], entry
        return journal["decisions"]

    def _save(self, entries: list[dict[str, Any]]) -> None:
        document, _ = canonical_snapshot({
            "schema": _SCHEMA, "target_key": self.key, "decisions": entries,
        })
        available = _MAX_DOCUMENT - len(document) - 1
        if available < 0:
            raise ValueError("target decision history too large")
        if entries[-1]["decision"] == "approved":
            # A full-length UTF-8 revocation must still fit, including the repeated snapshot.
            snapshot_size = len(canonical_snapshot(entries[-1]["snapshot"])[0])
            if available < snapshot_size + 20_000:
                raise ValueError("target decision history requires room for revocation")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(document + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._check_directory()
            if len(entries) == 1:
                # A crash before replace must leave an initialized-but-missing journal fail closed.
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            os.replace(temporary, self.path)
            if os.name == "posix":
                fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    if not os.path.samestat(self.directory_info, os.fstat(fd)):
                        raise ValueError("target decision directory changed")
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def change(
        self, request: Any, *, current_snapshot: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist the supplied human quote if the reviewed snapshot and head match."""
        approve = current_snapshot is not None
        by, quote, head = _operator_fields(request, approve=approve)
        with self._locked():
            entries = self.history()
            latest = entries[-1] if entries else None
            if head != (latest["id"] if latest else None):
                raise ValueError("target decision changed since review")
            if current_snapshot is not None:
                snapshot = current_snapshot()
                _validate_snapshot(snapshot, self.key)
                review = snapshot["review"]
                zone = review["timezone"]
                if len(zone) > 128:
                    raise ValueError("invalid_review_timezone")
                if review["scheduled_at"] is not None:
                    _schedule_time(review["scheduled_at"], zone)
                else:
                    try:
                        ZoneInfo(zone)
                    except (ValueError, ZoneInfoNotFoundError) as exc:
                        raise ValueError("invalid_review_timezone") from exc
                if canonical_snapshot(snapshot)[1] != request["expected_review"]:
                    raise ValueError("target review changed")
            else:
                if latest is None or latest["decision"] != "approved":
                    raise ValueError("there is no active target decision to revoke")
                snapshot = latest["snapshot"]
            payload = {
                "previous": head, "decision": "approved" if approve else "revoked",
                "snapshot": snapshot, "by": by, "quote": quote,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            entry = {"id": canonical_snapshot(payload)[1], **payload}
            self._save([*entries, entry])
            return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("operation", choices=("history", "revoke"))
    parser.add_argument("--approval-directory", required=True, type=Path)
    parser.add_argument("--target-key", required=True)
    args = parser.parse_args()
    try:
        decisions = TargetDecisions(args.approval_directory, args.target_key)
        if args.operation == "history":
            result = {"target_key": decisions.key, "decisions": decisions.history()}
        else:
            entry = decisions.change(read_operator_json())
            result = {"target_key": decisions.key, "decision_id": entry["id"], "decision": "revoked"}
    except (OSError, ValueError, TypeError, LookupError, RecursionError):
        print(json.dumps({"status": "blocked", "reason": "target_decision_operation_failed"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
