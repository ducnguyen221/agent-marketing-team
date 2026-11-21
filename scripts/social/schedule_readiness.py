"""Inspect campaign source and local approval evidence for pending due schedules."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from PIL import Image

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.lib.delivery_ledger import SCOPE_FIELDS
from scripts.social.approval_package_v2 import _checked_package_file, _local_directory
from scripts.social.check_package_readiness import _check_target
from scripts.social.prepare_package import _MAX_DOCUMENT, _unique_object
from scripts.social.schedule_v2 import SHA256, ScheduleError, ScheduleStore, _reject_secret_path
from scripts.social.target_approval import TargetDecisions


_DIRECTORIES = {"campaign", "package_dir", "approval_directory", "temporary_parent"}
_FILE_SELECTORS = {"text_file", "comment_file", "media_file"}
_LIST_SELECTORS = {"media_files", "caption_files"}
_READ_ERRORS = (OSError, ValueError, TypeError, LookupError, AttributeError, RecursionError)
_CHECK_ERRORS = (
    *_READ_ERRORS, subprocess.SubprocessError, yaml.YAMLError,
    Image.DecompressionBombError, Image.DecompressionBombWarning,
)


def _absolute_local(path: Path) -> Path:
    _reject_secret_path(path)
    if not path.is_absolute() or path.anchor.startswith(("//", "\\\\")) or ".." in path.parts:
        raise ValueError("absolute local path required")
    _reject_credential_names(path.parts[1:])
    return path


def _reject_credential_names(parts: tuple[str, ...]) -> None:
    for part in parts:
        name = part.rstrip(" .").casefold()
        if (name in {".secret", "auth.json", "oauth_creds.json"} or name.startswith(".env")
                or name.endswith((".credentials.json", ".pem", ".key")) or ":" in name):
            raise ValueError("unsafe readiness path")


def _manifest(path: Path) -> dict[str, Any]:
    path = _absolute_local(path)
    if path.suffix.casefold() != ".json":
        raise ValueError("readiness manifest must be a JSON file")
    with _checked_package_file(_local_directory(path.parent), path.name) as source:
        data = source.read(_MAX_DOCUMENT + 1)
    if len(data) > _MAX_DOCUMENT:
        raise ValueError("readiness manifest too large")
    entries = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(entries, dict) or not all(SHA256.fullmatch(key) for key in entries):
        raise ValueError("readiness manifest must map intent IDs to source entries")
    return entries


def _sources(entry: Any, schedule_directory: Path) -> dict[str, Any]:
    if (not isinstance(entry, dict) or not _DIRECTORIES <= entry.keys()
            or entry.keys() - _DIRECTORIES - _FILE_SELECTORS - _LIST_SELECTORS
            or ("media_file" in entry and "media_files" in entry)):
        raise ValueError("invalid readiness source fields")
    for key in entry.keys() - _LIST_SELECTORS:
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise ValueError("invalid readiness source value")
    for key in entry.keys() & _LIST_SELECTORS:
        if (not isinstance(entry[key], list) or not entry[key]
                or any(not isinstance(value, str) or not value.strip() for value in entry[key])):
            raise ValueError("invalid readiness selector list")
        for value in entry[key]:
            _reject_credential_names(PurePosixPath(value).parts)
    for key in entry.keys() & _FILE_SELECTORS:
        _reject_credential_names(PurePosixPath(entry[key]).parts)
    directories = {key: _local_directory(_absolute_local(Path(entry[key]))) for key in _DIRECTORIES}
    temporary_parent = directories["temporary_parent"]
    if any(temporary_parent.is_relative_to(root) for root in (
        schedule_directory, directories["approval_directory"],
    )):
        raise ValueError("temporary package storage must be outside schedule and approval directories")
    return {**entry, **directories}


def _due(record: dict[str, Any], cutoff: datetime) -> bool:
    return (record["status"] == "pending"
            and datetime.fromisoformat(record["snapshot"]["scheduled_utc"]) <= cutoff)


def _review(intent: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    identity = intent["identity"]
    scope = {field: identity[field] for field in SCOPE_FIELDS if field != "gate"}
    approval_directory = arguments.pop("approval_directory")
    result = _check_target({
        **arguments,
        "scope": {**scope, "gate": "g2"},
        "account_id": identity["account_id"],
        "destination_id": identity["destination_id"],
        "occurrence_id": identity["occurrence_key"],
        "scheduled_at": intent["scheduled_at"],
        "timezone": intent["timezone"],
        "privacy": intent["privacy"],
        "options": intent["delivery_options"],
    }, approval_directory, decision=None)
    digest = canonical_snapshot(result["snapshot"]["review"])[1]
    if digest != intent["review_digest"]:
        return {"reason": "schedule_review_digest_mismatch"}
    entries = TargetDecisions(approval_directory, result["target_key"]).history()
    current_head = entries[-1]["id"] if entries else None
    if current_head != result["expected_head"]:
        return {"reason": "target_decision_changed_during_check"}
    return {
        "reason": result["reason"],
        "source_match": result["source_match"],
        "approval_binding": result["approval_binding"],
        "approval_evidence_scope": result["approval_evidence_scope"],
        "review_digest": digest,
        "target_key": result["target_key"],
        "expected_review": result["expected_review"],
        "expected_head": result["expected_head"],
        "schedule_review": "matched_current_snapshot",
    }


def _check_item(
    store: ScheduleStore, directory: Path, intent_id: str, initial: dict[str, Any],
    entries: dict[str, Any], cutoff: datetime,
) -> dict[str, Any]:
    try:
        current = store.get(intent_id)
    except _READ_ERRORS:
        return {"reason": "schedule_intent_unavailable"}
    if (current["binding"] != initial["binding"] or current["revision"] != initial["revision"]
            or not _due(current, cutoff)):
        return {"reason": "schedule_intent_changed_since_due_scan"}
    if intent_id not in entries:
        return {"reason": "readiness_source_mapping_missing"}
    intent = initial["snapshot"]
    if "review_digest" not in intent:
        return {"reason": "schedule_review_required"}
    try:
        arguments = _sources(entries[intent_id], directory)
    except _READ_ERRORS:
        return {"reason": "invalid_or_unavailable_readiness_source"}
    try:
        result = _review(intent, arguments)
    except _CHECK_ERRORS:
        result = {"reason": "source_or_approval_check_failed"}
    try:
        current = store.get(intent_id)
    except _READ_ERRORS:
        return {"reason": "schedule_recheck_failed"}
    if (current["binding"] != initial["binding"] or current["revision"] != initial["revision"]
            or not _due(current, cutoff)):
        return {"reason": "schedule_intent_changed_during_check"}
    return {**result, "binding": current["binding"], "revision": current["revision"]}


def check_due_readiness(store: ScheduleStore, directory: Path, manifest: Path) -> dict[str, Any]:
    """Report local observations for each due intent without changing either ledger."""
    try:
        entries = _manifest(manifest)
    except _READ_ERRORS:
        raise ScheduleError("invalid_or_unavailable_readiness_manifest") from None
    directory = _local_directory(_absolute_local(directory))
    cutoff, due_records = store.due_records()
    return {
        "status": "blocked",
        "reason": "production_approval_generation_unavailable",
        "items": [
            {
                **_check_item(store, directory, intent_id, record, entries, cutoff),
                "intent_id": intent_id, "status": "blocked",
            }
            for intent_id, record in due_records.items()
        ],
    }
