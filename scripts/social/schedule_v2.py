"""Destination-aware schedule storage. This module has no publishing entry point."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.social.review_snapshot import canonical_review

SCHEMA = "social-schedule/2"
_SCOPE_FIELDS = ("station_id", "channel_id", "campaign_id", "content_id", "post_id")
IDENTITY_FIELDS = (
    *_SCOPE_FIELDS,
    "platform", "account_id", "destination_id", "occurrence_key",
)
_SNAPSHOT_FIELDS = {"identity", "action", "package_sha256", "scheduled_at", "timezone", "scheduled_utc"}
_REVIEW_FIELDS = {"destination_kind", "privacy", "delivery_options", "review_digest"}
MAX_BYTES = 8_000_000
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:[0-5]\d)")
SHA256 = re.compile(r"[0-9a-f]{64}")
LEDGER_ID = re.compile(r"[0-9a-f]{32}")
_OUTCOMES = frozenset({"published", "failed", "unknown"})
_STATES = _OUTCOMES | {"pending", "revoked", "submitting"}
_RECEIPT_PROVIDERS = frozenset({
    "discord", "facebook", "instagram", "linkedin", "postiz", "telegram", "threads",
    "tiktok", "x", "youtube",
})
_UNSAFE_FILE_ATTRIBUTES = 0x400 | 0x1000 | 0x40000 | 0x400000
ApprovalLookup = Callable[[str], str | None]


class ScheduleError(ValueError):
    """A schedule operation could not safely proceed."""


@dataclass(frozen=True)
class ProviderEvidence:
    """A receipt reference and reported outcome supplied by the caller."""

    intent_id: str
    binding: str
    attempt_id: str
    provider_id: str
    receipt_ref: str
    reported_outcome: str


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ScheduleError("duplicate_json_field")
        result[name] = value
    return result


def _json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _label(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 512 and value == value.strip() and value.isprintable()


def _parse_schedule_time(value: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value) or value.endswith("-00:00"):
        raise ScheduleError("schedule_requires_explicit_offset")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise ScheduleError("invalid_schedule_time") from exc


def _schedule_time(value: str, zone: str | None = None) -> str:
    local = _parse_schedule_time(value)
    try:
        utc = local.astimezone(timezone.utc)
        if zone is None:
            return utc.isoformat()
        roundtrip = utc.astimezone(ZoneInfo(zone))
    except (ValueError, OverflowError, KeyError) as exc:
        raise ScheduleError("invalid_schedule_or_iana_zone") from exc
    if (local.utcoffset() != roundtrip.utcoffset()
            or local.replace(tzinfo=None) != roundtrip.replace(tzinfo=None)):
        raise ScheduleError("offset_or_wall_time_does_not_match_zone")
    return utc.isoformat()


def _file_info(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _UNSAFE_FILE_ATTRIBUTES
            or (not directory and info.st_nlink != 1)):
        raise ScheduleError("unsafe_schedule_path")
    return info


def _reject_secret_path(path: Path) -> None:
    if any(part.rstrip(" .").casefold() == ".secret" for part in path.parts):
        raise ScheduleError("unsafe_schedule_path")


def _snapshot_review(snapshot: dict[str, Any]) -> tuple[dict[str, Any], str]:
    identity = snapshot["identity"]
    options = snapshot["delivery_options"]
    privacy = snapshot["privacy"]
    if (identity["post_id"] == "*" or not _label(snapshot["destination_kind"])
            or not _label(privacy) or not isinstance(options, dict)
            or ("privacy" in options and options["privacy"] != privacy)):
        raise ScheduleError("invalid_schedule_review")
    try:
        return canonical_review(
            claimed_scope={**{key: identity[key] for key in _SCOPE_FIELDS}, "gate": "g2"},
            platform=identity["platform"], destination_kind=snapshot["destination_kind"],
            action=snapshot["action"], account_id=identity["account_id"],
            destination_id=identity["destination_id"], occurrence_key=identity["occurrence_key"],
            scheduled_at=snapshot["scheduled_at"], timezone=snapshot["timezone"], privacy=privacy,
            delivery_options=options, package_digest=snapshot["package_sha256"],
        )
    except ValueError as exc:
        raise ScheduleError("invalid_schedule_review") from exc


class ScheduleStore:
    """Keep one isolated schedule on a trusted, single-host local filesystem."""

    def __init__(self, directory: Path, *, isolated_parent: Path) -> None:
        root = Path(isolated_parent)
        candidate = Path(directory)
        _reject_secret_path(root)
        _reject_secret_path(candidate)
        if (not root.is_absolute() or root == Path(root.anchor)
                or root.anchor.startswith(("//", "\\\\"))
                or ".." in root.parts or candidate.parent != root
                or not candidate.name.startswith("social-schedule-v2-")):
            raise ScheduleError("dedicated_local_temporary_directory_required")
        for ancestor in reversed(root.parents):
            _file_info(ancestor, directory=True)
            _reject_secret_path(ancestor.resolve(strict=True))
        self._parent_id = _file_info(root, directory=True)
        _reject_secret_path(root.resolve(strict=True))
        self._directory = candidate
        self._directory_id = _file_info(candidate, directory=True)
        _reject_secret_path(candidate.resolve(strict=True))
        self._path = candidate / "schedule.json"
        self._lock_path = candidate / "schedule.lock"

    def _check_directory(self) -> None:
        if not os.path.samestat(self._directory_id, _file_info(self._directory, directory=True)):
            raise ScheduleError("schedule_directory_changed")

    @contextmanager
    def _locked(self, *, new: bool = False) -> Iterator[None]:
        self._check_directory()
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if new:
            if any(self._directory.iterdir()):
                raise ScheduleError("schedule_directory_not_empty")
            flags |= os.O_CREAT | os.O_EXCL
        else:
            _file_info(self._lock_path)
        fd = os.open(self._lock_path, flags, 0o600)
        try:
            if not os.path.samestat(os.fstat(fd), _file_info(self._lock_path)):
                raise ScheduleError("schedule_lock_changed")
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                elif os.name == "posix":
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    raise ScheduleError("schedule_lock_unavailable")
            except OSError as exc:
                raise ScheduleError("schedule_lock_unavailable") from exc
            self._check_directory()
            yield
        finally:
            os.close(fd)

    def _load(self, *, new: bool = False) -> tuple[str, dict[str, dict[str, Any]]]:
        try:
            expected = _file_info(self._path)
        except FileNotFoundError:
            if new:
                return uuid.uuid4().hex, {}
            raise ScheduleError("schedule_missing") from None
        if new:
            raise ScheduleError("schedule_already_initialized")
        with self._path.open("rb") as stream:
            if not os.path.samestat(expected, os.fstat(stream.fileno())):
                raise ScheduleError("schedule_file_changed")
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ScheduleError("schedule_too_large")
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
        if (not isinstance(data, dict)
                or set(data) != {"schema", "ledger_id", "items", "checksum"}
                or data["schema"] != SCHEMA or not isinstance(data["items"], dict)
                or not isinstance(data["ledger_id"], str) or not LEDGER_ID.fullmatch(data["ledger_id"])
                or _digest({"ledger_id": data["ledger_id"], "items": data["items"]})
                != data["checksum"]):
            raise ScheduleError("invalid_schedule_file")
        return data["ledger_id"], data["items"]

    @contextmanager
    def _directory_sync(self, *, required: bool) -> Iterator[int | None]:
        if os.name != "posix":
            if required:
                raise ScheduleError("durable_claim_unavailable_on_this_platform")
            yield None
            return
        fd = os.open(self._directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            if not os.path.samestat(self._directory_id, os.fstat(fd)):
                raise ScheduleError("schedule_directory_changed")
            # Probe directory durability before a send-capable transition.
            os.fsync(fd)
            yield fd
        finally:
            os.close(fd)

    def _save(
        self, ledger_id: str, items: dict[str, dict[str, Any]], *, durable: bool = False,
    ) -> None:
        content = {"ledger_id": ledger_id, "items": items}
        data = _json({"schema": SCHEMA, **content, "checksum": _digest(content)}) + b"\n"
        if len(data) > MAX_BYTES:
            raise ScheduleError("schedule_too_large")
        with self._directory_sync(required=durable) as dir_fd:
            temp_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=self._directory, delete=False) as stream:
                    temp_name = stream.name
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._check_directory()
                os.replace(temp_name, self._path)
                if dir_fd is not None:
                    os.fsync(dir_fd)
            finally:
                if temp_name is not None:
                    Path(temp_name).unlink(missing_ok=True)

    def initialize(self) -> None:
        """Explicitly create an empty ledger in a newly allocated directory."""
        with self._locked(new=True):
            if os.name == "posix":
                parent_fd = os.open(self._directory.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    if not os.path.samestat(self._parent_id, os.fstat(parent_fd)):
                        raise ScheduleError("schedule_parent_changed")
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            self._save(*self._load(new=True))

    @staticmethod
    def _binding(ledger_id: str, snapshot: dict[str, Any], revision: int) -> str:
        return _digest({
            "schema": SCHEMA, "ledger_id": ledger_id, "snapshot": snapshot, "revision": revision,
        })

    @staticmethod
    def _intent_id(identity: dict[str, str]) -> str:
        # Account changes must never re-arm the same occurrence at this destination.
        return _digest({name: identity[name] for name in IDENTITY_FIELDS if name != "account_id"})

    def put(
        self, identity: dict[str, str], *, scheduled_at: str, timezone_name: str,
        package_sha256: str, action: str, destination_kind: str, privacy: str,
        delivery_options: dict[str, Any],
    ) -> str:
        """Store a destination intent or revise its pending snapshot."""
        if (set(identity) != set(IDENTITY_FIELDS)
                or not all(_label(value) for value in identity.values())
                or not all(_label(value) for value in (action, timezone_name))
                or not isinstance(package_sha256, str) or not SHA256.fullmatch(package_sha256)):
            raise ScheduleError("invalid_schedule_intent")
        scheduled_utc = _schedule_time(scheduled_at, timezone_name)
        intent_id = self._intent_id(identity)
        snapshot = {
            "identity": dict(identity), "action": action, "package_sha256": package_sha256,
            "scheduled_at": scheduled_at, "timezone": timezone_name, "scheduled_utc": scheduled_utc,
            "destination_kind": destination_kind, "privacy": privacy, "delivery_options": delivery_options,
        }
        review, review_digest = _snapshot_review(snapshot)
        snapshot.update(delivery_options=review["delivery_options"], review_digest=review_digest)
        with self._locked():
            ledger_id, items = self._load()
            previous = self._item(ledger_id, items, intent_id) if intent_id in items else None
            if previous is not None:
                if previous["snapshot"]["identity"] != identity:
                    raise ScheduleError("conflicting_destination_account")
                if previous["snapshot"] == snapshot:
                    # The original replacement may have succeeded before directory sync failed.
                    with self._directory_sync(required=False):
                        pass
                    return intent_id
                if previous["status"] != "pending":
                    raise ScheduleError("schedule_intent_already_closed_or_claimed")
            revision = 1 if previous is None else previous["revision"] + 1
            items[intent_id] = {
                "snapshot": snapshot, "revision": revision, "status": "pending",
                "binding": self._binding(ledger_id, snapshot, revision),
                "attempt_id": None, "approval_ref": None, "result_ref": None,
            }
            self._save(ledger_id, items)
        return intent_id

    def get(self, intent_id: str) -> dict[str, Any]:
        """Read the current record, including its binding and destination state."""
        with self._locked():
            ledger_id, items = self._load()
            return self._item(ledger_id, items, intent_id)

    def due(self) -> tuple[str, ...]:
        """Return pending IDs due now. Claim still checks the current record and approval."""
        _, records = self.due_records()
        return tuple(records)

    def due_records(self) -> tuple[datetime, dict[str, dict[str, Any]]]:
        """Capture the UTC cutoff and validated due records under one lock."""
        with self._locked():
            ledger_id, items = self._load()
            now = datetime.now(timezone.utc)
            due_records = {}
            for intent_id in items:
                item = self._item(ledger_id, items, intent_id)
                if (item["status"] == "pending"
                        and datetime.fromisoformat(item["snapshot"]["scheduled_utc"]) <= now):
                    due_records[intent_id] = item
            return now, due_records

    @staticmethod
    def _item(
        ledger_id: str, items: dict[str, dict[str, Any]], intent_id: str,
    ) -> dict[str, Any]:
        try:
            item = items[intent_id]
        except KeyError:
            raise ScheduleError("schedule_intent_missing") from None
        fields = {"snapshot", "revision", "status", "binding", "attempt_id", "approval_ref", "result_ref"}
        if not isinstance(item, dict) or set(item) not in (fields, fields | {"provider_evidence"}):
            raise ScheduleError("invalid_schedule_intent_record")
        snapshot = item["snapshot"]
        revision = item["revision"]
        state = item["status"]
        if (not isinstance(snapshot, dict) or set(snapshot) not in (
                _SNAPSHOT_FIELDS, _SNAPSHOT_FIELDS | _REVIEW_FIELDS)
                or type(revision) is not int or revision < 1
                or not isinstance(state, str) or state not in _STATES):
            raise ScheduleError("invalid_schedule_intent_record")
        identity = snapshot["identity"]
        package_sha256 = snapshot["package_sha256"]
        if (not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS)
                or not all(_label(value) for value in identity.values())
                or ScheduleStore._intent_id(identity) != intent_id
                or not all(_label(snapshot[name]) for name in ("action", "timezone"))
                or not isinstance(package_sha256, str) or not SHA256.fullmatch(package_sha256)
                or _schedule_time(snapshot["scheduled_at"]) != snapshot["scheduled_utc"]
                or ScheduleStore._binding(ledger_id, snapshot, revision) != item["binding"]):
            raise ScheduleError("invalid_schedule_intent_record")
        if "review_digest" in snapshot and _snapshot_review(snapshot)[1] != snapshot["review_digest"]:
            raise ScheduleError("schedule_review_digest_mismatch")
        attempt, approval, result = (item[name] for name in ("attempt_id", "approval_ref", "result_ref"))
        if state in {"pending", "revoked"}:
            valid = attempt is None and approval is None and result is None
        else:
            valid = (isinstance(attempt, str) and bool(LEDGER_ID.fullmatch(attempt))
                     and _label(approval) and (_label(result) if state in _OUTCOMES else result is None))
        if not valid:
            raise ScheduleError("invalid_schedule_intent_record")
        if "provider_evidence" in item:
            receipts = item["provider_evidence"]
            if (state != "unknown" or not isinstance(receipts, list) or not receipts
                    or not all(ScheduleStore._matches_evidence(intent_id, item, receipt)
                               for receipt in receipts)
                    or len({(receipt["provider_id"], receipt["receipt_ref"]) for receipt in receipts})
                    != len(receipts)):
                raise ScheduleError("invalid_schedule_provider_evidence")
        return item

    @staticmethod
    def _matches_evidence(intent_id: str, item: dict[str, Any], evidence: Any) -> bool:
        return (isinstance(evidence, dict)
                and evidence.keys() == ProviderEvidence.__annotations__.keys()
                and all(type(value) is str for value in evidence.values())
                and evidence["intent_id"] == intent_id
                and evidence["binding"] == item["binding"]
                and evidence["attempt_id"] == item["attempt_id"]
                and evidence["provider_id"] in _RECEIPT_PROVIDERS
                and evidence["provider_id"] in (item["snapshot"]["identity"]["platform"], "postiz")
                and bool(SHA256.fullmatch(evidence["receipt_ref"]))
                and evidence["reported_outcome"] in _OUTCOMES)

    def claim_due(
        self, intent_id: str, *, expected_binding: str, approval_lookup: ApprovalLookup,
    ) -> str:
        """Commit one claim after a trusted approval lookup for that exact binding."""
        if os.name != "posix":
            raise ScheduleError("durable_claim_unavailable_on_this_platform")
        with self._locked():
            ledger_id, items = self._load()
            item = self._item(ledger_id, items, intent_id)
            if item["status"] != "pending" or item["binding"] != expected_binding:
                raise ScheduleError("schedule_intent_not_claimable")
            if "review_digest" not in item["snapshot"]:
                raise ScheduleError("schedule_review_required")
            due = datetime.fromisoformat(item["snapshot"]["scheduled_utc"])
            if due > datetime.now(timezone.utc):
                raise ScheduleError("schedule_intent_not_due")
            # The caller must adapt a trusted authority. This store cannot authenticate approval.
            approval_ref = approval_lookup(item["binding"])
            if not _label(approval_ref):
                raise ScheduleError("schedule_approval_unavailable")
            attempt_id = uuid.uuid4().hex
            item.update(status="submitting", attempt_id=attempt_id, approval_ref=approval_ref)
            self._save(ledger_id, items, durable=True)
            return attempt_id

    def revoke(self, intent_id: str, *, expected_binding: str) -> None:
        """Close a pending intent. A committed claim has already won the race."""
        with self._locked():
            ledger_id, items = self._load()
            item = self._item(ledger_id, items, intent_id)
            if item["binding"] != expected_binding or item["status"] not in {"pending", "revoked"}:
                raise ScheduleError("schedule_intent_not_revocable")
            item["status"] = "revoked"
            self._save(ledger_id, items)

    def finish(
        self, intent_id: str, *, attempt_id: str, outcome: str, result_ref: str,
    ) -> None:
        """Record a terminal result for the matching attempt and destination."""
        if outcome not in _OUTCOMES or not _label(result_ref) or not _label(attempt_id):
            raise ScheduleError("invalid_schedule_outcome")
        with self._locked():
            ledger_id, items = self._load()
            item = self._item(ledger_id, items, intent_id)
            if attempt_id != item["attempt_id"]:
                raise ScheduleError("schedule_attempt_mismatch")
            if (item["status"], item["result_ref"]) == (outcome, result_ref):
                with self._directory_sync(required=True):
                    pass
                return
            if item["status"] != "submitting":
                raise ScheduleError("schedule_attempt_already_closed")
            item.update(status=outcome, result_ref=result_ref)
            self._save(ledger_id, items, durable=True)

    def record_unknown_evidence(self, intent_id: str, *, evidence: ProviderEvidence) -> None:
        """Save a receipt reference for reconciliation while keeping the attempt unknown."""
        if type(evidence) is not ProviderEvidence:
            raise ScheduleError("invalid_schedule_provider_evidence")
        receipt = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
        with self._locked():
            ledger_id, items = self._load()
            item = self._item(ledger_id, items, intent_id)
            if not self._matches_evidence(intent_id, item, receipt):
                raise ScheduleError("invalid_schedule_provider_evidence")
            if item["status"] != "unknown":
                raise ScheduleError("schedule_attempt_not_unknown")
            receipts = item.setdefault("provider_evidence", [])
            receipt_key = (evidence.provider_id, evidence.receipt_ref)
            for previous in receipts:
                if (previous["provider_id"], previous["receipt_ref"]) != receipt_key:
                    continue
                if previous != receipt:
                    raise ScheduleError("schedule_provider_evidence_conflict")
                with self._directory_sync(required=True):
                    pass
                return
            receipts.append(receipt)
            self._save(ledger_id, items, durable=True)
