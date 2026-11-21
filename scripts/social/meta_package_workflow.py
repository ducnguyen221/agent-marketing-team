"""Run a guarded standalone Meta container workflow once per delivery occurrence."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.lib.delivery_contract import canonical_snapshot
from scripts.social.channels.threads import direct as threads
from scripts.social.channels.threads.readonly_auth import interpret_identity
from scripts.social.publish_channel_package import AccountObservation, ChannelApproval, approved_package
from scripts.social.publish_meta_package import (
    _ID,
    MetaContainerObservation,
    create_meta_package_container,
    publish_meta_package_container,
)
from scripts.social.publish_package_authority import require_production_authority
from scripts.social.publish_package_transport import GuardedPackageTransport, _request, _response_object
from scripts.social.standalone_delivery import SCHEMA

_OCCURRENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_RECEIPT_SCHEMA = "meta-package-attempt-receipt/1"
_MAX_RECEIPT = 4096
_THREADS_HOST = "graph.threads.com"


class _ThreadsTransport(GuardedPackageTransport):
    def post(
        self, url: str, headers: Mapping[str, str], fields: Mapping[str, Any],
        files: Mapping[str, tuple[str, bytes]],
    ) -> tuple[int, list[tuple[str, str]], Mapping[str, Any]]:
        # The Meta adapter uses a common bearer interface. Threads documents a form parameter.
        authorization = headers.get("Authorization", "")
        if not url.startswith(f"https://{_THREADS_HOST}/") or not authorization.startswith("Bearer ") or files:
            raise ValueError("invalid Threads form request")
        form = {**fields, "access_token": authorization.removeprefix("Bearer ")}
        return super().post(url, {}, form, {})


@contextmanager
def _open_journal(transport: GuardedPackageTransport) -> Iterator[int]:
    descriptor = os.open(transport._journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != transport._journal_identity:
            raise OSError("attempt journal directory changed")
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise OSError("Meta attempt journal directory must be private to its owner")
        yield descriptor
    finally:
        os.close(descriptor)


def _read_attempt(transport: GuardedPackageTransport, binding: dict[str, str]) -> tuple[bool, str | None]:
    with _open_journal(transport) as directory:
        name = transport._claim_name
        try:
            claim = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return False, None
        if not stat.S_ISREG(claim.st_mode):
            raise OSError("invalid Meta attempt claim")
        try:
            fd = os.open(f"{name}.receipt.json", os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW,
                         dir_fd=directory)
        except FileNotFoundError:
            return True, None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_RECEIPT:
                raise OSError("invalid Meta attempt receipt")
            raw = stream.read(_MAX_RECEIPT + 1)
            payload = _response_object(raw)
            identifier = payload.get("provider_id")
            if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
                return True, None
            expected, _ = canonical_snapshot({"schema": _RECEIPT_SCHEMA, **binding, "provider_id": identifier})
            if raw != expected:
                return True, None
            os.fsync(stream.fileno())
            os.fsync(directory)
            return True, identifier


def _save_receipt(transport: GuardedPackageTransport, binding: dict[str, str], identifier: str) -> None:
    payload, _ = canonical_snapshot({"schema": _RECEIPT_SCHEMA, **binding, "provider_id": identifier})
    with _open_journal(transport) as directory:
        fd = os.open(f"{transport._claim_name}.receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)


def _threads_get(path: str, *, fields: str, credential: str) -> tuple[int, dict[str, Any]]:
    query = urlencode({"fields": fields})
    url = f"https://{_THREADS_HOST}{path}?{query}"
    try:
        status, _, raw = _request("GET", url, {"Accept": "application/json",
                                              "Authorization": f"Bearer {credential}"}, b"",
                                  allowed_hosts={_THREADS_HOST})
    except RuntimeError:
        return 0, {}
    return status, _response_object(raw)


def _threads_container_status(*, container_id: str, credential: str, api_version: str) -> str | None:
    status, payload = _threads_get(f"/{api_version}/{container_id}", fields="status,error_message",
                                   credential=credential)
    if status != 200 or payload.get("id") != container_id or "error" in payload or "errors" in payload:
        return None
    observed = payload.get("status")
    if observed == "FINISHED" and payload.get("error_message"):
        return None
    return observed if observed in ("FINISHED", "IN_PROGRESS", "ERROR", "EXPIRED", "PUBLISHED") else None


def _threads_account(*, account_id: str, credential: str, credential_digest: str,
                     api_version: str) -> AccountObservation:
    status, payload = _threads_get(f"/{api_version}/me", fields="id", credential=credential)
    if interpret_identity(status, payload, expected_user_id=account_id)["identity"] != "match":
        raise ValueError("Threads credential could not be matched to the package account")
    return AccountObservation("threads", account_id, credential_digest, "threads:provider-identity-read")


def run_meta_package_workflow(
    package_dir: Path,
    *,
    platform: str,
    account_id: str,
    api_version: str,
    credential: str,
    occurrence_id: str,
    approval: ChannelApproval,
    journal_directory: Path,
    enable_dispatch: bool = False,
) -> dict[str, str]:
    """Bind a standalone package to a verified account and publish only a ready container."""
    if enable_dispatch is not True:
        raise ValueError("Meta workflow dispatch is disabled")
    require_production_authority()
    if platform not in {"instagram", "threads"} or not isinstance(account_id, str) or not _ID.fullmatch(account_id):
        raise ValueError("unsupported Meta platform or account ID")
    if not isinstance(occurrence_id, str) or not _OCCURRENCE.fullmatch(occurrence_id):
        raise ValueError("invalid Meta delivery occurrence")
    package = approved_package(package_dir, platform=platform, account_id=account_id, credential=credential,
                               approval=approval, enable_dispatch=True)
    if package["schema"] != SCHEMA:
        raise ValueError("Meta workflow requires a standalone package")
    if package["action"] in {"post_image", "post_video"}:
        return {"status": "blocked", "reason": "verified_immutable_hosted_media_unavailable"}
    if platform != "threads" or package["action"] != "post_text":
        return {"status": "blocked", "reason": "unsupported_meta_package_action"}
    preview = threads.preview_container(user_id=account_id, api_version=api_version, media_type="TEXT",
                                        text=package["content"]["text"])
    if len(preview["request"]["params"]["text"]) > 500:
        raise ValueError("Threads text exceeds 500 characters")
    if os.name != "posix":
        raise ValueError("durable attempt journal unavailable on this platform")

    occurrence = {"platform": platform, "account_id": account_id, "occurrence_id": occurrence_id}
    create_key = canonical_snapshot({**occurrence, "operation": "container"})[1]
    publish_key = canonical_snapshot({**occurrence, "operation": "publish_container"})[1]
    create = _ThreadsTransport(journal_directory, create_key)
    publish = _ThreadsTransport(journal_directory, publish_key)
    if (create._journal_directory, create._journal_identity) != (publish._journal_directory, publish._journal_identity):
        raise ValueError("Meta attempt journal directory changed")
    credential_digest = hashlib.sha256(credential.encode()).hexdigest()
    binding_digest = canonical_snapshot({**occurrence, "api_version": api_version,
                                         "credential_sha256": credential_digest,
                                         "package_digest": approval.package_digest})[1]
    create_binding = {"operation": "container", "binding_digest": binding_digest}
    attempted, container_id = _read_attempt(create, create_binding)
    if attempted and container_id is None:
        return {"status": "unknown", "stage": "container"}

    account = None
    if container_id is None:
        account = _threads_account(account_id=account_id, credential=credential,
                                   credential_digest=credential_digest, api_version=api_version)
        receipt = create_meta_package_container(
            package_dir, platform=platform, account_id=account_id, api_version=api_version,
            credential=credential, approval=approval, account_observation=account, transport=create.post,
            enable_dispatch=True,
        )
        if receipt["status"] != "container_accepted_by_provider":
            return {"status": "unknown", "stage": "container"}
        container_id = receipt["provider_id"]
        try:
            _save_receipt(create, create_binding, container_id)
        except OSError:
            return {"status": "unknown", "stage": "container_receipt",
                    "container_id": container_id, "receipt_status": "unconfirmed"}

    publish_binding = {"operation": "publish_container", "binding_digest": binding_digest,
                       "container_id": container_id}
    attempted, post_id = _read_attempt(publish, publish_binding)
    if attempted:
        if post_id is None:
            return {"status": "unknown", "stage": "publish", "container_id": container_id}
        return {"status": "accepted_by_provider", "provider_id": post_id, "container_id": container_id}

    if account is None:
        account = _threads_account(account_id=account_id, credential=credential,
                                   credential_digest=credential_digest, api_version=api_version)
    readiness = _threads_container_status(container_id=container_id, credential=credential, api_version=api_version)
    if readiness is None:
        return {"status": "unknown", "stage": "container_status", "container_id": container_id}
    if readiness == "IN_PROGRESS":
        return {"status": "container_pending", "container_status": readiness, "container_id": container_id}
    if readiness != "FINISHED":
        return {"status": "blocked", "reason": "container_terminal", "container_status": readiness,
                "container_id": container_id}

    observation = MetaContainerObservation(platform, account_id, approval.package_digest, container_id,
                                           readiness, f"threads:container-status:{create_key}")
    receipt = publish_meta_package_container(
        package_dir, platform=platform, account_id=account_id, api_version=api_version, credential=credential,
        approval=approval, observation=observation, account_observation=account, transport=publish.post,
        enable_dispatch=True,
    )
    if receipt["status"] != "accepted_by_provider" or receipt["provider_id"] == container_id:
        return {"status": "unknown", "stage": "publish", "container_id": container_id}
    try:
        _save_receipt(publish, publish_binding, receipt["provider_id"])
    except OSError:
        return {"status": "unknown", "stage": "publish_receipt", "container_id": container_id,
                "provider_id": receipt["provider_id"], "receipt_status": "unconfirmed"}
    return {**receipt, "container_id": container_id}
