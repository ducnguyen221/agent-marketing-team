"""Guarded orchestration for standalone and campaign LinkedIn V2 packages."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.linkedin import direct
from scripts.social.facebook_package_workflow import _read_journal_json, _store_receipt
from scripts.social.prepare_package import _IMAGE_TYPES, _MAX_MEDIA, _unique_object
from scripts.social.prepare_standalone import _local_directory, _open_input
from scripts.social.publish_channel_package import (
    ChannelApproval,
    LinkedInPostObservation,
    MediaObservation,
    _interpret_linkedin_comment,
    approved_package,
    publish_linkedin_first_comment,
    publish_linkedin_package,
)
from scripts.social.publish_media_package import (
    _linkedin_bearer, _upload_prepared_linkedin_media, prepare_linkedin_package_media,
    upload_linkedin_package_media,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _request
from scripts.social.publish_package_workflow import read_package_account
from scripts.social.standalone_delivery import SCHEMA, read_delivery_manifest, validate_standalone_target

_RECEIPT_LIMIT = 4096
_CAMPAIGN_RECEIPT_LIMIT = 262144
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMMENT_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_ACTIONS = {"post_text", "post_image", "post_video"}
_CREATE_SCHEMA = "linkedin-campaign-create-receipt/1"
_COMMENT_SCHEMA = "linkedin-campaign-comment-receipt/1"


@dataclass(frozen=True)
class LinkedInCampaignContext:
    campaign: Path
    scope: dict[str, str]
    temporary_parent: Path
    approval_directory: Path
    expected_review: str
    timezone: str
    privacy: str
    text_file: str | None = None
    comment_file: str | None = None
    media_file: str | None = None


def _validate_campaign_source(
    source: Any, *, identity: dict[str, str], api_version: str,
    package_digest: str, expected_review: str, approval_ref: str,
) -> dict[str, Any]:
    from scripts.social.target_approval import _validate_snapshot, target_key

    if (
        not all(isinstance(value, str) and _DIGEST.fullmatch(value)
                for value in (package_digest, expected_review, approval_ref))
        or not isinstance(source, dict) or source.keys() != {"snapshot", "approval_ref"}
        or source["approval_ref"] != approval_ref
        or not isinstance(source["snapshot"], dict) or canonical_snapshot(source["snapshot"])[1] != expected_review
    ):
        raise ValueError("LinkedIn campaign receipt review mismatch")
    snapshot = source["snapshot"]
    review = snapshot["review"]
    _validate_snapshot(snapshot, target_key(review))
    if (
        set(snapshot["source_gate_digests"]) != {"g1", "g2"}
        or review["platform"] != "linkedin" or review["destination_kind"] != "account"
        or review["account_id"] != identity["author"] or review["destination_id"] != identity["destination_id"]
        or review["occurrence_key"] != identity["occurrence_id"] or review["package_digest"] != package_digest
        or review["action"] not in _ACTIONS or review["scheduled_at"] is not None
        or review["privacy"] != "public" or review["delivery_options"] != {"api_version": api_version}
    ):
        raise ValueError("LinkedIn campaign receipt target mismatch")
    return review


def _campaign_source(
    package_dir: Path, context: LinkedInCampaignContext, *, identity: dict[str, str],
    api_version: str, approval: ChannelApproval,
) -> dict[str, Any]:
    from scripts.social.check_package_readiness import _check_target

    arguments = {
        "package_dir": package_dir, "campaign": context.campaign, "scope": context.scope,
        "temporary_parent": context.temporary_parent, "account_id": identity["author"],
        "destination_id": identity["destination_id"], "occurrence_id": identity["occurrence_id"],
        "scheduled_at": None, "timezone": context.timezone, "privacy": context.privacy,
        "options": {"api_version": api_version}, "text_file": context.text_file,
        "comment_file": context.comment_file, "media_file": context.media_file,
    }
    checked = _check_target(arguments, context.approval_directory, decision=None)
    if (
        checked["approval_binding"] != "matched" or checked["expected_head"] != approval.approval_ref
        or checked["expected_review"] != context.expected_review
    ):
        raise ValueError("LinkedIn campaign approval is missing, stale, revoked or mismatched")
    source = {"snapshot": checked["snapshot"], "approval_ref": approval.approval_ref}
    _validate_campaign_source(
        source, identity=identity, api_version=api_version, package_digest=approval.package_digest,
        expected_review=context.expected_review, approval_ref=approval.approval_ref,
    )
    return source


def _attempt_identity(author: str, destination_id: str, occurrence_id: str) -> dict[str, str]:
    if (
        not isinstance(author, str) or not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]{1,128}", author)
        or not isinstance(destination_id, str) or destination_id != author
        or not isinstance(occurrence_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", occurrence_id)
    ):
        raise ValueError("invalid LinkedIn member target or occurrence")
    return {
        "platform": "linkedin", "author": author, "destination_id": destination_id,
        "occurrence_id": occurrence_id,
    }


def _create_receipt_fields(identity: dict[str, str], package_digest: str) -> dict[str, str]:
    if not isinstance(package_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", package_digest):
        raise ValueError("invalid LinkedIn package digest")
    operation = {**identity, "operation": "create"}
    return {
        **operation, "attempt_key": canonical_snapshot(operation)[1],
        "package_digest": package_digest, "status": "accepted_by_provider",
    }


def _store_create_receipt(
    directory: Path, *, fields: dict[str, str], post_urn: str,
) -> None:
    """Publish a complete receipt atomically without replacing an existing receipt."""
    if not direct._POST.fullmatch(post_urn):
        raise ValueError("invalid LinkedIn create receipt")
    receipt = {**fields, "post_urn": post_urn}
    destination = directory / f"{fields['attempt_key']}.linkedin-receipt.json"
    with tempfile.NamedTemporaryFile(mode="wb", dir=directory, prefix=".linkedin-receipt-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write((json.dumps(receipt, sort_keys=True) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.link(temporary, destination)
            if os.name == "posix":
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            stream.close()
            temporary.unlink()


def _receipt_bytes(directory: Path, name: str, limit: int) -> bytes:
    with _open_input(directory, name, limit) as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("LinkedIn journal entry exceeds its size limit")
    return data


def read_linkedin_create_receipt(
    journal_directory: Path, *, author: str, destination_id: str, occurrence_id: str, package_digest: str,
) -> dict[str, str]:
    """Read only the derived receipt and claim in a trusted, local journal."""
    identity = _attempt_identity(author, destination_id, occurrence_id)
    expected = _create_receipt_fields(identity, package_digest)
    attempt_key = expected["attempt_key"]
    result = {"attempt_key": attempt_key, "post_status": "unknown", "post_readback": "unverified"}
    claim_data = b"attempt_started\n"
    claim_key = hashlib.sha256(attempt_key.encode("ascii")).hexdigest()
    try:
        directory = _local_directory(journal_directory)
    except (OSError, ValueError):
        return {**result, "receipt_status": "journal_unavailable", "claim_status": "unverified"}
    try:
        claim = _receipt_bytes(directory, f"{claim_key}.attempt", len(claim_data))
        claim_status = "present" if claim == claim_data else "unverified"
    except FileNotFoundError:
        claim_status = "missing"
    except (OSError, ValueError):
        claim_status = "unverified"
    result["claim_status"] = claim_status

    try:
        raw = _receipt_bytes(directory, f"{attempt_key}.linkedin-receipt.json", _RECEIPT_LIMIT)
        receipt = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return {**result, "receipt_status": "missing"}
    except (OSError, ValueError, RecursionError):
        return {**result, "receipt_status": "invalid"}
    if not isinstance(receipt, dict):
        return {**result, "receipt_status": "invalid"}
    post_urn = receipt.pop("post_urn", None)
    if receipt != expected or not isinstance(post_urn, str) or not direct._POST.fullmatch(post_urn):
        return {**result, "receipt_status": "invalid"}
    if claim_status != "present":
        return {**result, "receipt_status": "unbound"}
    return {**result, "receipt_status": "matched", "post_status": "accepted_by_provider", "post_urn": post_urn}


def _operation(identity: dict[str, str], name: str) -> str:
    return canonical_snapshot({**identity, "operation": name})[1]


def _campaign_media(action: str, media: Any) -> dict[str, Any] | None:
    if action == "post_text" and media is None:
        return None
    kind = action.removeprefix("post_")
    if (
        kind not in direct._MEDIA or not isinstance(media, dict)
        or set(media) != {"urn", "status", "attachment"} or media["status"] != "AVAILABLE"
        or not isinstance(media["urn"], str) or not direct._MEDIA[kind].fullmatch(media["urn"])
        or not isinstance(media["attachment"], dict)
    ):
        raise ValueError("invalid LinkedIn receipt media evidence")
    attachment = media["attachment"]
    filename, length, digest = (attachment.get(field) for field in ("file", "bytes", "sha256"))
    suffixes = (".mp4",) if kind == "video" else _IMAGE_TYPES
    if (
        set(attachment) != {"file", "kind", "bytes", "sha256", "width", "height"}
        or attachment.get("kind") != kind or not isinstance(filename, str)
        or filename not in {f"attachment{suffix}" for suffix in suffixes}
        or type(length) is not int or not 0 < length <= _MAX_MEDIA
        or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
        or any(type(attachment[side]) is not int or attachment[side] <= 0 for side in ("width", "height"))
    ):
        raise ValueError("invalid LinkedIn receipt attachment metadata")
    return media


def read_linkedin_campaign_receipt(
    journal_directory: Path, *, author: str, destination_id: str, occurrence_id: str,
    api_version: str, package_digest: str, expected_review: str, approval_ref: str,
) -> dict[str, Any]:
    """Read local historical create and comment evidence without current campaign files."""
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    identity = _attempt_identity(author, destination_id, occurrence_id)
    direct.preview_post(author=author, text="LinkedIn", api_version=api_version)
    transport = GuardedPackageTransport(_local_directory(journal_directory), _operation(identity, "create"))
    return _read_campaign_receipt(
        transport, identity=identity, api_version=api_version, package_digest=package_digest,
        expected_review=expected_review, approval_ref=approval_ref,
    )


def _read_campaign_receipt(
    transport: GuardedPackageTransport, *, identity: dict[str, str], api_version: str,
    package_digest: str, expected_review: str, approval_ref: str,
) -> dict[str, Any]:
    create_key = _operation(identity, "create")
    result = {"attempt_key": create_key, "post_status": "unknown", "post_readback": "unverified",
              "comment_status": "unknown"}
    try:
        receipt = _read_journal_json(
            transport, f"{create_key}.linkedin-campaign-create.json", limit=_CAMPAIGN_RECEIPT_LIMIT,
        )
        review = _validate_campaign_source(
            receipt.get("campaign_source"), identity=identity, api_version=api_version,
            package_digest=package_digest, expected_review=expected_review, approval_ref=approval_ref,
        )
        post_urn = receipt.get("post_urn")
        media = _campaign_media(review["action"], receipt.get("media"))
        package = receipt["package"]
        if (
            canonical_snapshot(package)[1] != review["package_digest"]
            or package.get("schema") != "social-package/1" or package.get("status") != "prepared_for_review"
            or package.get("platform") != "linkedin" or package.get("destination") != "account"
            or package.get("action") != review["action"] or not isinstance(package.get("content"), dict)
            or package["media"] != (media["attachment"] if media is not None else None)
        ):
            raise ValueError("invalid LinkedIn historical package binding")
        comment_requested = package["content"].get("first_comment") is not None
        expected = {
            **_create_receipt_fields(identity, package_digest), "schema": _CREATE_SCHEMA,
            "api_version": api_version, "action": review["action"], "post_urn": post_urn,
            "campaign_source": receipt["campaign_source"], "media": media,
            "package": package, "comment_requested": comment_requested,
        }
        if (
            receipt != expected or not isinstance(post_urn, str) or not direct._POST.fullmatch(post_urn)
            or receipt["comment_requested"] is not comment_requested
        ):
            raise ValueError("invalid LinkedIn campaign create receipt")
    except FileNotFoundError:
        return {**result, "receipt_status": "missing"}
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        return {**result, "receipt_status": "invalid"}
    result.update(post_urn=post_urn, media=media, post_status="accepted_by_provider", receipt_status="matched")
    if not comment_requested:
        return {**result, "comment_status": "not_requested"}

    comment_key = _operation(identity, "comment")
    try:
        comment_transport = _journal_transport(transport, comment_key)
        comment = _read_journal_json(
            comment_transport, f"{comment_key}.linkedin-campaign-comment.json", limit=_CAMPAIGN_RECEIPT_LIMIT,
        )
        comment_id = comment.get("comment_id")
        if (
            comment != _comment_record(receipt, comment_key, comment_id)
            or not isinstance(comment_id, str) or not _COMMENT_ID.fullmatch(comment_id)
        ):
            raise ValueError("invalid LinkedIn campaign comment receipt")
    except FileNotFoundError:
        return {**result, "comment_receipt_status": "missing"}
    except (OSError, TypeError, ValueError, RecursionError):
        return {**result, "comment_receipt_status": "invalid"}
    return {**result, "comment_receipt_status": "matched", "comment_status": "accepted_by_provider",
            "comment_id": comment_id}


def _comment_record(create: dict[str, Any], key: str, provider_id: str) -> dict[str, Any]:
    binding = {name: value for name, value in create.items() if name != "package"}
    return {**binding, "create_receipt_digest": canonical_snapshot(create)[1],
            "schema": _COMMENT_SCHEMA, "operation": "comment", "attempt_key": key,
            "comment_id": provider_id, "post_readback": "provider_reports_published"}


def _store_campaign_receipt(transport: GuardedPackageTransport, name: str, receipt: dict[str, Any]) -> None:
    if len(canonical_snapshot(receipt)[0]) > _CAMPAIGN_RECEIPT_LIMIT:
        raise ValueError("LinkedIn campaign receipt exceeds the size limit")
    _store_receipt(transport, name, receipt)


def _journal_transport(origin: GuardedPackageTransport, key: str) -> GuardedPackageTransport:
    transport = GuardedPackageTransport(origin._journal_directory, key)
    if transport._journal_identity != origin._journal_identity:
        raise ValueError("LinkedIn attempt journal directory changed")
    return transport


def _read_post(
    author: str, post_urn: str, headers: dict[str, str], *, expected_body: dict[str, Any] | None = None,
) -> str:
    try:
        status, _, raw = _request(
            "GET", f"https://api.linkedin.com/rest/posts/{quote(post_urn, safe='')}",
            headers, b"", allowed_hosts={"api.linkedin.com"},
        )
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, RuntimeError, ValueError, RecursionError):
        return "unverified"
    if status != 200 or not isinstance(body, dict) or {"error", "errors", "serviceErrorCode"} & body.keys():
        return "unverified"
    if expected_body is not None:
        expected_media = expected_body.get("content", {}).get("media", {}).get("id")
        content = body.get("content")
        media = content.get("media") if isinstance(content, dict) else None
        if (
            body.get("commentary") != expected_body["commentary"]
            or (expected_media is None and content not in (None, {}))
            or (expected_media is not None and (not isinstance(media, dict) or media.get("id") != expected_media))
        ):
            return "unverified"
    if (
        body.get("id") == post_urn and body.get("author") == author
        and body.get("lifecycleState") == "PUBLISH_REQUESTED" and body.get("visibility") == "PUBLIC"
    ):
        return "provider_reports_pending"
    return direct.observe_post(
        {"state": "accepted", "post_urn": post_urn, "readback": "unverified"},
        status, body, expected_author=author,
    )["readback"]


def reconcile_linkedin_package_workflow(
    package_dir: Path,
    *,
    author: str,
    destination_id: str,
    occurrence_id: str,
    api_version: str,
    credential: str,
    approval: ChannelApproval,
    journal_directory: Path,
    enable_provider_read: bool = False,
) -> dict[str, str]:
    """Reconcile a previously accepted create using provider GETs only."""
    require_production_authority()
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    if enable_provider_read is not True:
        raise ValueError("LinkedIn provider read is disabled")
    if (
        not isinstance(approval, ChannelApproval) or approval.platform != "linkedin"
        or approval.account_id != author or not isinstance(approval.approval_ref, str)
        or not approval.approval_ref.strip()
    ):
        raise ValueError("invalid LinkedIn approval reference")
    result = read_linkedin_create_receipt(
        journal_directory, author=author, destination_id=destination_id,
        occurrence_id=occurrence_id, package_digest=approval.package_digest,
    )
    if result["receipt_status"] != "matched":
        return {**result, "reconciliation": "insufficient_local_evidence"}

    package = read_delivery_manifest(package_dir)
    validate_standalone_target(
        package_dir, package, platform="linkedin", account_id=author,
        destination_id=destination_id, package_digest=approval.package_digest,
    )
    request = direct.preview_post(author=author, text=package["content"]["text"], api_version=api_version)["request"]
    headers = {**request["headers"], "Authorization": _linkedin_bearer(credential)}
    try:
        read_package_account(platform="linkedin", account_id=author, credential=credential, enable_provider_read=True)
    except (OSError, RuntimeError, ValueError):
        return {**result, "reconciliation": "account_unverified"}
    return {
        **result, "reconciliation": "provider_read_attempted",
        "post_readback": _read_post(author, result["post_urn"], headers),
    }


def run_linkedin_package_workflow(
    package_dir: Path,
    *,
    author: str,
    destination_id: str,
    occurrence_id: str,
    api_version: str,
    credential: str,
    approval: ChannelApproval,
    journal_directory: Path,
    enable_dispatch: bool = False,
    campaign_context: LinkedInCampaignContext | None = None,
) -> dict[str, Any]:
    """Run one guarded upload/create/readback/comment sequence without injected evidence."""
    require_production_authority()
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    identity = _attempt_identity(author, destination_id, occurrence_id)
    package = approved_package(
        package_dir, platform="linkedin", account_id=author, destination_id=destination_id,
        credential=credential, approval=approval, enable_dispatch=enable_dispatch,
    )
    if campaign_context is not None:
        if not isinstance(campaign_context, LinkedInCampaignContext) or package.get("schema") != "social-package/1":
            raise ValueError("LinkedIn campaign workflow requires a campaign package and context")
        return _run_campaign(
            package_dir, package, campaign_context, identity=identity, api_version=api_version,
            credential=credential, approval=approval, journal_directory=journal_directory,
        )
    if package.get("schema") != SCHEMA:
        raise ValueError("LinkedIn workflow requires a target-bound standalone package")
    text = package["content"]["text"]
    first_comment = package["content"].get("first_comment")
    request = direct.preview_post(author=author, text=text, api_version=api_version)["request"]
    if first_comment is not None:
        direct.preview_post(author=author, text=first_comment, api_version=api_version)

    headers = {**request["headers"], "Authorization": _linkedin_bearer(credential)}
    receipt_fields = _create_receipt_fields(identity, approval.package_digest)
    create_key = receipt_fields["attempt_key"]
    journal_directory = journal_directory.resolve(strict=True)
    create_transport = GuardedPackageTransport(journal_directory, create_key)
    account = read_package_account(
        platform="linkedin", account_id=author, credential=credential, enable_provider_read=True,
    )

    result = {"post_status": "not_attempted", "comment_status": "not_attempted"}
    media_observation = None
    if package["action"] in {"post_image", "post_video"}:
        upload = upload_linkedin_package_media(
            package_dir, package_digest=approval.package_digest, author=author, destination_id=destination_id,
            occurrence_id=occurrence_id, api_version=api_version, access_token=credential,
            journal_directory=journal_directory,
        )
        result.update(media_status=upload.state, media_stage=upload.stage)
        kind = package["action"].removeprefix("post_")
        if (
            upload.state != "available" or upload.stage != "status" or upload.media_urn is None
            or not direct._MEDIA[kind].fullmatch(upload.media_urn)
        ):
            return result
        media_observation = MediaObservation(
            author, package["media"]["sha256"], upload.media_urn, f"linkedin-upload:{create_key}",
        )

    post = publish_linkedin_package(
        package_dir, author=author, api_version=api_version, credential=credential, approval=approval,
        transport=create_transport.post, account_observation=account, media_observation=media_observation,
        enable_dispatch=enable_dispatch,
    )
    result["post_status"] = post["status"]
    if post["status"] != "accepted_by_provider":
        return result
    post_urn = post["provider_id"]
    result["post_urn"] = post_urn
    result["post_readback"] = "unverified"
    try:
        _store_create_receipt(journal_directory, fields=receipt_fields, post_urn=post_urn)
    except (OSError, ValueError):
        result["receipt_status"] = "unconfirmed"
        return result
    result["receipt_status"] = "stored"
    result["post_readback"] = _read_post(author, post_urn, headers)
    if first_comment is None or result["post_readback"] != "provider_reports_published":
        return result

    comment_key = canonical_snapshot({**identity, "operation": "comment"})[1]
    comment_transport = GuardedPackageTransport(journal_directory, comment_key)
    comment = publish_linkedin_first_comment(
        package_dir, author=author, api_version=api_version, credential=credential, approval=approval,
        observation=LinkedInPostObservation(author, approval.package_digest, post_urn, f"linkedin-readback:{create_key}"),
        transport=comment_transport.post, account_observation=account, enable_dispatch=enable_dispatch,
    )
    result["comment_status"] = comment["status"]
    if comment["status"] == "accepted_by_provider":
        result["comment_id"] = comment["provider_id"]
    return result


def _run_campaign(
    package_dir: Path, package: dict[str, Any], context: LinkedInCampaignContext, *,
    identity: dict[str, str], api_version: str, credential: str, approval: ChannelApproval,
    journal_directory: Path,
) -> dict[str, Any]:
    require_production_authority()
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")
    author = identity["author"]
    action = package.get("action")
    if action not in _ACTIONS or package.get("destination") != "account":
        raise ValueError("invalid LinkedIn campaign delivery action or destination")
    text = package["content"]["text"]
    first_comment = package["content"].get("first_comment")
    preview = direct.preview_post(author=author, text=text, api_version=api_version)["request"]
    if first_comment is not None:
        direct.preview_post(author=author, text=first_comment, api_version=api_version)
    headers = {**preview["headers"], "Authorization": _linkedin_bearer(credential)}
    create_fields = _create_receipt_fields(identity, approval.package_digest)
    create_key = create_fields["attempt_key"]
    create_name = f"{create_key}.linkedin-campaign-create.json"
    journal = _local_directory(journal_directory)
    create_transport = GuardedPackageTransport(journal, create_key)
    no_comment = "not_requested" if first_comment is None else "not_attempted"
    result: dict[str, Any] = {"post_status": "not_attempted", "comment_status": no_comment}
    existing_create = any(os.path.lexists(journal / name) for name in (
        create_transport._claim_name, create_name, f"{create_key}.linkedin-receipt.json",
    ))
    if existing_create:
        result = _read_campaign_receipt(
            create_transport, identity=identity, api_version=api_version, package_digest=approval.package_digest,
            expected_review=context.expected_review, approval_ref=approval.approval_ref,
        )
        if result["receipt_status"] != "matched":
            return result
    comment_pending = first_comment is not None and (
        not existing_create or result.get("comment_receipt_status") == "missing"
    )

    source = _campaign_source(package_dir, context, identity=identity, api_version=api_version, approval=approval)
    if source["snapshot"]["review"]["action"] != action:
        raise ValueError("LinkedIn campaign package action changed")
    receipt_binding = {**create_fields, "schema": _CREATE_SCHEMA, "action": action, "api_version": api_version,
                       "campaign_source": source, "package": package, "comment_requested": first_comment is not None}
    if len(canonical_snapshot(receipt_binding)[0]) > _CAMPAIGN_RECEIPT_LIMIT - 4096:
        raise ValueError("LinkedIn campaign receipt snapshot exceeds the size limit")

    def check_current_approval() -> None:
        if source != _campaign_source(package_dir, context, identity=identity, api_version=api_version,
                                      approval=approval):
            raise ValueError("LinkedIn campaign target approval changed before provider request")

    if not existing_create:
        check_current_approval()
        read_package_account(
            platform="linkedin", account_id=author, credential=credential, enable_provider_read=True,
        )
        media = None
        if action in {"post_image", "post_video"}:
            prepared = prepare_linkedin_package_media(
                package_dir, package_digest=approval.package_digest, author=author, api_version=api_version,
            )
            media_transport = _journal_transport(create_transport, _operation(identity, "media"))
            upload = _upload_prepared_linkedin_media(
                prepared, credential, media_transport, before_send=check_current_approval,
            )
            result.update(media_status=upload.state, media_stage=upload.stage)
            if upload.state != "available" or upload.stage != "status" or upload.media_urn is None:
                return result
            if prepared.file_sha256 != package["media"]["sha256"]:
                raise ValueError("LinkedIn uploaded media does not match the package bytes")
            media = _campaign_media(action, {"urn": upload.media_urn, "status": "AVAILABLE",
                                             "attachment": package["media"]})
        expected_body = _campaign_post_body(author, text, api_version, action, media)
        try:
            check_current_approval()
            status, response_headers, _ = create_transport.post(
                "https://api.linkedin.com" + preview["path"], headers, expected_body, {},
            )
        except (OSError, RuntimeError, ValueError):
            return {**result, "post_status": "unknown"}
        post = direct.interpret_create(status, response_headers)
        if post["state"] != "accepted":
            result["post_status"] = "unknown"
            return result
        post_urn = post["post_urn"]
        result.update(post_status="accepted_by_provider", post_urn=post_urn, media=media, post_readback="unverified")
        receipt = {**receipt_binding, "post_urn": post_urn, "media": media}
        try:
            _store_campaign_receipt(create_transport, create_name, receipt)
        except (OSError, ValueError):
            result["receipt_status"] = "unconfirmed"
            return result
        result["receipt_status"] = "stored"
    else:
        post_urn, media = result["post_urn"], result["media"]
        if (media is None and package["media"] is not None) or (
            media is not None and media["attachment"] != package["media"]
        ):
            raise ValueError("LinkedIn historical media does not match the approved package")
        expected_body = _campaign_post_body(author, text, api_version, action, media)
        receipt = {**receipt_binding, "post_urn": post_urn, "media": media}

    try:
        if existing_create:
            check_current_approval()
            read_package_account(
                platform="linkedin", account_id=author, credential=credential, enable_provider_read=True,
            )
        check_current_approval()
        result["post_readback"] = _read_post(author, post_urn, headers, expected_body=expected_body)
    except (OSError, RuntimeError, ValueError):
        return result
    if not comment_pending or result["post_readback"] != "provider_reports_published":
        return result

    comment_key = _operation(identity, "comment")
    comment_name = f"{comment_key}.linkedin-campaign-comment.json"
    try:
        comment_transport = _journal_transport(create_transport, comment_key)
        if any(os.path.lexists(journal / name) for name in (comment_transport._claim_name, comment_name)):
            return {**result, "comment_status": "unknown", "comment_reason": "existing_comment_attempt"}
        check_current_approval()
        status, _, response = comment_transport.post(
            f"https://api.linkedin.com/rest/socialActions/{quote(post_urn, safe='')}/comments", headers,
            {"actor": author, "object": post_urn, "message": {"text": first_comment}}, {},
        )
    except (OSError, RuntimeError, ValueError):
        return {**result, "comment_status": "unknown"}
    comment = _interpret_linkedin_comment(status, response, author=author, post_urn=post_urn, credential=credential)
    result["comment_status"] = comment["status"]
    if comment["status"] == "accepted_by_provider":
        result["comment_id"] = comment["provider_id"]
        try:
            _store_campaign_receipt(
                comment_transport, comment_name, _comment_record(receipt, comment_key, result["comment_id"]),
            )
        except (OSError, ValueError):
            result["comment_receipt_status"] = "unconfirmed"
        else:
            result["comment_receipt_status"] = "stored"
    return result


def _campaign_post_body(
    author: str, text: str, api_version: str, action: str, media: dict[str, Any] | None,
) -> dict[str, Any]:
    return direct.preview_post(
        author=author, text=text, api_version=api_version,
        media_kind=action.removeprefix("post_") if media is not None else None,
        media_urn=media["urn"] if media is not None else None,
    )["request"]["body"]
