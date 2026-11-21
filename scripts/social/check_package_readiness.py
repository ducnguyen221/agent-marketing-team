"""Check a prepared social V2 package against its campaign source and approval evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.lib.delivery_ledger import SCOPE_FIELDS
from scripts.pipeline.approval_gate import read_delivery_gate_proof
from scripts.social.approval_package_v2 import _local_directory, verify_stored_package_campaign_source
from scripts.social.schedule_v2 import ScheduleStore
from scripts.social.target_approval import TargetDecisions, read_operator_json, target_key
from scripts.social.verified_dispatch_context import (
    approved_content_columns,
    inspect_campaign_dispatch_evidence,
    prepare_campaign_dispatch_review,
)


_CONTEXT_FIELDS = {
    "account_id", "destination_id", "occurrence_id", "scheduled_at", "timezone", "privacy", "options",
}


def _source_gate_digests(
    campaign: Path, scope: dict[str, str], *, target_platform: str | None = None,
) -> dict[str, str]:
    columns = approved_content_columns(campaign, scope["content_id"])
    gates = ("g1", "g3") if "g3" in columns and target_platform in {"facebook", "youtube"} else ("g1",)
    return {
        **{
            gate: read_delivery_gate_proof(campaign, {**scope, "gate": gate, "post_id": "*"})["source_digest"]
            for gate in gates
        },
        "g2": read_delivery_gate_proof(campaign, scope)["source_digest"],
    }


def _target_review(arguments: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_campaign_dispatch_review(**arguments)
    review = prepared["review"]
    return {
        "review": review,
        "source_gate_digests": _source_gate_digests(
            arguments["campaign"], arguments["scope"], target_platform=review["platform"],
        ),
    }


def _check_target(
    arguments: dict[str, Any], approval_directory: Path, *, decision: dict[str, Any] | None,
) -> dict[str, Any]:
    directory = _local_directory(approval_directory)
    for field in ("campaign", "package_dir"):
        source = _local_directory(arguments[field])
        if source.is_relative_to(directory) or directory.is_relative_to(source):
            raise ValueError("target decision directory must be separate from source and package")
    snapshot = _target_review(arguments)
    digest = canonical_snapshot(snapshot)[1]
    store = TargetDecisions(directory, target_key(snapshot["review"]))
    if decision is not None:
        if decision.get("expected_review") != digest:
            raise ValueError("target review changed")
        latest = store.change(decision, current_snapshot=lambda: _target_review(arguments))
    else:
        entries = store.history()
        latest = entries[-1] if entries else None
    if latest is None:
        local_decision = "missing"
    elif latest["decision"] == "revoked":
        local_decision = "revoked"
    elif latest["snapshot"] != snapshot:
        local_decision = "stale"
    else:
        local_decision = "matched"
    return {
        "status": "blocked",
        "reason": "production_approval_generation_unavailable",
        "source_match": "matched_current_files",
        "approval_binding": local_decision,
        "approval_evidence_scope": "selected_local_journal",
        "target_key": store.key,
        "expected_review": digest,
        "expected_head": latest["id"] if latest else None,
        "snapshot": snapshot,
    }


def _check_schedule(directory: Path, intent_id: str, review_digest: str) -> dict[str, Any]:
    schedule = ScheduleStore(directory, isolated_parent=directory.parent)
    record = schedule.get(intent_id)
    scheduled_digest = record["snapshot"].get("review_digest")
    if scheduled_digest is None:
        return {"reason": "schedule_review_required"}
    if scheduled_digest != review_digest:
        return {"reason": "schedule_review_digest_mismatch"}
    result = {"schedule_review": "matched_current_snapshot", "schedule_status": record["status"]}
    if record["status"] != "pending":
        result["reason"] = "schedule_intent_not_pending"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--temporary-parent", required=True, type=Path)
    for field in SCOPE_FIELDS:
        if field != "gate":
            parser.add_argument(f"--{field.replace('_', '-')}", required=True)
    parser.add_argument("--text-file")
    parser.add_argument("--comment-file")
    media = parser.add_mutually_exclusive_group()
    media.add_argument("--media-file")
    media.add_argument("--media-files", nargs="+")
    parser.add_argument("--caption-files", nargs="+")
    approval_check = parser.add_mutually_exclusive_group()
    approval_check.add_argument(
        "--dispatch-context-stdin", action="store_true",
        help="read the exact reviewed dispatch context as UTF-8 JSON",
    )
    approval_check.add_argument(
        "--check-source-gates", action="store_true",
        help="check local V1 G1 and G2 records for the source item and post",
    )
    approval_check.add_argument(
        "--target-review-stdin", action="store_true",
        help="inspect a V2 target review using an exact JSON dispatch context",
    )
    approval_check.add_argument(
        "--record-target-approval-stdin", action="store_true",
        help="record an operator's verbatim decision for an exact V2 target review",
    )
    parser.add_argument("--approval-directory", type=Path)
    parser.add_argument("--schedule-directory", type=Path)
    parser.add_argument("--schedule-intent-id")
    arguments = vars(parser.parse_args())
    read_dispatch_context = arguments.pop("dispatch_context_stdin")
    check_source_gates = arguments.pop("check_source_gates")
    target_review = arguments.pop("target_review_stdin")
    record_target = arguments.pop("record_target_approval_stdin")
    approval_directory = arguments.pop("approval_directory")
    schedule_directory = arguments.pop("schedule_directory")
    schedule_intent_id = arguments.pop("schedule_intent_id")
    if ((schedule_directory is None) != (schedule_intent_id is None)
            or (schedule_directory is not None and not (read_dispatch_context or target_review))):
        parser.error("provide schedule directory and intent ID together with a read-only context check")
    target_mode = target_review or record_target
    if target_mode != (approval_directory is not None):
        parser.error("--approval-directory is required only for V2 target decisions")
    scope = {field: arguments.pop(field) for field in SCOPE_FIELDS if field != "gate"}
    scope["gate"] = "g2"

    decision = None
    if read_dispatch_context or target_mode:
        try:
            context = read_operator_json()
            if record_target:
                if (not isinstance(context, dict) or set(context) != {"context", "decision"}
                        or not isinstance(context["decision"], dict)):
                    raise ValueError("invalid operator approval envelope")
                decision, context = context["decision"], context["context"]
            if not isinstance(context, dict) or context.keys() != _CONTEXT_FIELDS:
                raise ValueError("invalid dispatch context fields")
        except (OSError, ValueError, RecursionError):
            print(json.dumps({"status": "blocked", "reason": "invalid_dispatch_context"}))
            return 2

    try:
        if target_mode:
            result = _check_target({**arguments, **context, "scope": scope}, approval_directory, decision=decision)
            if schedule_directory is not None:
                review_digest = canonical_snapshot(result["snapshot"]["review"])[1]
                result.update(_check_schedule(schedule_directory, schedule_intent_id, review_digest))
        elif read_dispatch_context:
            evidence = inspect_campaign_dispatch_evidence(scope=scope, **context, **arguments)
            result = {
                "status": "blocked", "reason": evidence["reason"],
                "package_digest": evidence["binding"]["package_digest"],
                "review_digest": evidence["review_digest"],
                "source_match": "matched_current_files", "approval_binding": "matched_local_records",
                "matched_gates": sorted(evidence["campaign_evidence"]),
            }
            if schedule_directory is not None:
                result.update(_check_schedule(schedule_directory, schedule_intent_id, evidence["review_digest"]))
        else:
            _, digest = verify_stored_package_campaign_source(scope=scope, **arguments)
            result = {
                "status": "blocked", "reason": "dispatch_context_required",
                "package_digest": digest, "source_match": "matched_current_files", "approval_binding": "unchecked",
            }
            if check_source_gates:
                result["source_gate_digests"] = _source_gate_digests(arguments["campaign"], scope)
    except (
        OSError, ValueError, TypeError, LookupError, AttributeError, RecursionError,
        subprocess.SubprocessError, yaml.YAMLError, Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        reason = (
            "source_or_approval_check_failed"
            if read_dispatch_context or check_source_gates or target_mode
            else "source_check_failed"
        )
        print(json.dumps({"status": "blocked", "reason": reason}))
        return 2

    print(json.dumps(result, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
