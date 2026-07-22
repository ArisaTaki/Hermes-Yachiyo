"""Process-private authority for attaching child Runs to an existing RunGroup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


RUN_GROUP_ATTACHMENT_PAYLOAD_KEY = "_run_group_attachment_authority"
_INTERNAL_AUTHORITY = object()
_MAX_CHILD_IDENTITY_LENGTH = 128
_ACTIVE_GROUP_STATUSES = frozenset(
    {
        "created",
        "pending",
        "queued",
        "running",
        "processing",
        "approval_required",
        "waiting_approval",
    }
)


@dataclass(frozen=True, slots=True)
class RunGroupChildAttachment:
    run_group_id: str
    parent_run_id: str
    workflow_run_id: str
    child_kind: str
    child_runnable_id: str
    child_identity: str
    _authority: object = field(repr=False, compare=False)


def normalize_run_group_child_identity(value: Any) -> str:
    """Keep lineage and the persisted idempotency key on the same boundary."""

    identity = str(value or "").strip()
    if len(identity) <= _MAX_CHILD_IDENTITY_LENGTH:
        return identity
    digest = sha256(identity.encode("utf-8")).hexdigest()
    return f"run-group-child:{digest}"


def issue_run_group_child_attachment(
    *,
    run_group_id: str,
    parent_run_id: str,
    workflow_run_id: str = "",
    child_kind: str,
    child_runnable_id: str,
    child_identity: str,
) -> RunGroupChildAttachment:
    """Issue an in-process marker that cannot be reconstructed from JSON metadata."""

    return RunGroupChildAttachment(
        run_group_id=str(run_group_id or "").strip(),
        parent_run_id=str(parent_run_id or "").strip(),
        workflow_run_id=str(workflow_run_id or "").strip(),
        child_kind=str(child_kind or "").strip(),
        child_runnable_id=str(child_runnable_id or "").strip(),
        child_identity=normalize_run_group_child_identity(child_identity),
        _authority=_INTERNAL_AUTHORITY,
    )


def require_internal_run_group_attachment(
    value: Any,
    *,
    error_type: type[Exception] = RuntimeError,
) -> RunGroupChildAttachment:
    if (
        not isinstance(value, RunGroupChildAttachment)
        or value._authority is not _INTERNAL_AUTHORITY
    ):
        raise error_type("run_group_attachment_authority_required")
    return value


def validate_run_group_child_attachment(
    value: Any,
    *,
    group: dict[str, Any],
    run_group_id: str,
    child_kind: str,
    child_runnable_id: str,
    expected_child_identity: str,
    get_run: Callable[[str], dict[str, Any]],
    error_type: type[Exception] = RuntimeError,
) -> RunGroupChildAttachment:
    attachment = require_internal_run_group_attachment(value, error_type=error_type)
    clean_group_id = str(run_group_id or "").strip()
    if (
        attachment.run_group_id != clean_group_id
        or str(group.get("run_group_id") or "").strip() != clean_group_id
    ):
        raise error_type("run_group_attachment_group_mismatch")
    if str(group.get("status") or "").strip().lower() not in _ACTIVE_GROUP_STATUSES:
        raise error_type("run_group_attachment_group_not_active")
    clean_child_identity = str(expected_child_identity or "").strip()
    if (
        attachment.child_kind != str(child_kind or "").strip()
        or attachment.child_runnable_id != str(child_runnable_id or "").strip()
        or not clean_child_identity
        or attachment.child_identity != clean_child_identity
    ):
        raise error_type("run_group_attachment_child_identity_mismatch")
    member_run_ids = {
        str(run_id or "").strip()
        for run_id in group.get("child_run_ids") or []
        if str(run_id or "").strip()
    }
    if not attachment.parent_run_id or attachment.parent_run_id not in member_run_ids:
        raise error_type("run_group_attachment_parent_not_member")
    if (
        attachment.workflow_run_id
        and attachment.workflow_run_id not in member_run_ids
    ):
        raise error_type("run_group_attachment_workflow_parent_not_member")
    try:
        parent = get_run(attachment.parent_run_id)
    except (KeyError, RuntimeError) as exc:
        raise error_type("run_group_attachment_parent_missing") from exc
    if (
        str(parent.get("run_id") or "").strip() != attachment.parent_run_id
        or str(parent.get("run_group_id") or "").strip() != clean_group_id
    ):
        raise error_type("run_group_attachment_parent_group_mismatch")
    if attachment.workflow_run_id:
        try:
            workflow_parent = (
                parent
                if attachment.workflow_run_id == attachment.parent_run_id
                else get_run(attachment.workflow_run_id)
            )
        except (KeyError, RuntimeError) as exc:
            raise error_type("run_group_attachment_workflow_parent_missing") from exc
        if (
            str(workflow_parent.get("run_id") or "").strip()
            != attachment.workflow_run_id
            or str(workflow_parent.get("run_group_id") or "").strip()
            != clean_group_id
            or str(workflow_parent.get("kind") or "").strip() != "workflow_run"
        ):
            raise error_type("run_group_attachment_workflow_parent_invalid")
    return attachment


def validate_existing_run_group_child_attachment(
    value: Any,
    *,
    group: dict[str, Any],
    run_group_id: str,
    existing_child: dict[str, Any],
    child_kind: str,
    child_runnable_id: str,
    expected_child_identity: str,
    get_run: Callable[[str], dict[str, Any]],
    error_type: type[Exception] = RuntimeError,
) -> RunGroupChildAttachment:
    """Revalidate authority before an idempotent existing-child return.

    The insert path validates the process-private marker, but an idempotency
    hit bypasses that path.  Bind the persisted child row to the same group,
    member set, kind, runnable and idempotency identity before returning it.
    """

    attachment = validate_run_group_child_attachment(
        value,
        group=group,
        run_group_id=run_group_id,
        child_kind=child_kind,
        child_runnable_id=child_runnable_id,
        expected_child_identity=expected_child_identity,
        get_run=get_run,
        error_type=error_type,
    )
    clean_group_id = str(run_group_id or "").strip()
    clean_child_id = str(existing_child.get("run_id") or "").strip()
    ordered_member_run_ids = [
        str(run_id or "").strip()
        for run_id in group.get("child_run_ids") or []
        if str(run_id or "").strip()
    ]
    member_run_ids = set(ordered_member_run_ids)
    if not clean_child_id or clean_child_id not in member_run_ids:
        raise error_type("run_group_attachment_existing_child_not_member")
    canonical_root_parent_id = (
        ordered_member_run_ids[0] if ordered_member_run_ids else ""
    )
    marker_root_parent_id = (
        attachment.workflow_run_id or attachment.parent_run_id
    )
    if (
        not canonical_root_parent_id
        or marker_root_parent_id != canonical_root_parent_id
    ):
        raise error_type("run_group_attachment_existing_parent_mismatch")
    if (
        str(existing_child.get("run_group_id") or "").strip() != clean_group_id
        or str(existing_child.get("kind") or "").strip()
        != str(child_kind or "").strip()
        or str(existing_child.get("runnable_id") or "").strip()
        != str(child_runnable_id or "").strip()
        or str(existing_child.get("client_request_id") or "").strip()
        != str(expected_child_identity or "").strip()
    ):
        raise error_type("run_group_attachment_existing_child_mismatch")
    return attachment


__all__ = [
    "RUN_GROUP_ATTACHMENT_PAYLOAD_KEY",
    "RunGroupChildAttachment",
    "issue_run_group_child_attachment",
    "normalize_run_group_child_identity",
    "require_internal_run_group_attachment",
    "validate_existing_run_group_child_attachment",
    "validate_run_group_child_attachment",
]
