"""Overlay observed execution status onto runtime execution envelopes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import (
    ApprovalCardSnapshot,
    PublicRunEvent,
    ReplanRecoverySnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RuntimeExecutionRequestSnapshot,
    TaskProgressSummarySnapshot,
    ToolCallSnapshot,
)

_TERMINAL_REQUEST_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "completed",
    "denied",
    "expired",
    "failed",
    "rejected",
    "recovered",
    "skipped",
}


def runtime_execution_envelope_with_status_overlay(
    envelope: RuntimeExecutionEnvelopeSnapshot | None,
    *,
    tool_calls: Iterable[ToolCallSnapshot] | None = None,
    approvals: Iterable[ApprovalCardSnapshot] | None = None,
    pending_approval: ApprovalCardSnapshot | None = None,
    replan_recoveries: Iterable[ReplanRecoverySnapshot] | None = None,
    events: Iterable[PublicRunEvent] | None = None,
    task_progress: TaskProgressSummarySnapshot | None = None,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    """Return a copy of the envelope with request statuses reconciled from run facts."""

    if envelope is None or not envelope.requests:
        return envelope

    tool_items = [item for item in tool_calls or [] if item is not None]
    approval_items = [item for item in approvals or [] if item is not None]
    recovery_items = [item for item in replan_recoveries or [] if item is not None]
    event_items = [item for item in events or [] if item is not None]
    if pending_approval is not None and not any(
        _same_approval(item, pending_approval) for item in approval_items
    ):
        approval_items.append(pending_approval)

    current_step_id = _text(getattr(task_progress, "current_step_id", None))
    active_status = _active_task_request_status(task_progress)
    active_step_ids = _active_task_request_step_ids(
        task_progress,
        fallback_step_id=current_step_id,
    )
    requests: list[RuntimeExecutionRequestSnapshot] = []
    for request in envelope.requests:
        status = _observed_request_status(
            request,
            tool_calls=tool_items,
            approvals=approval_items,
            replan_recoveries=recovery_items,
            active_step_ids=active_step_ids,
            active_status=active_status,
        )
        request_update: dict[str, Any] = {}
        if status:
            request_update["status"] = status
        request_update.update(
            _request_replay_evidence_update(
                request,
                events=event_items,
                tool_calls=tool_items,
                approvals=approval_items,
            )
        )
        request_update.update(
            _request_verification_update(
                request,
                events=event_items,
                tool_calls=tool_items,
            )
        )
        requests.append(request.model_copy(update=request_update) if request_update else request)

    updates: dict[str, Any] = {"requests": requests}
    preferred_task_progress = _preferred_task_progress(
        envelope.task_progress,
        task_progress,
    )
    if preferred_task_progress is not envelope.task_progress:
        updates["task_progress"] = preferred_task_progress
    return envelope.model_copy(update=updates)


def _observed_request_status(
    request: RuntimeExecutionRequestSnapshot,
    *,
    tool_calls: list[ToolCallSnapshot],
    approvals: list[ApprovalCardSnapshot],
    replan_recoveries: list[ReplanRecoverySnapshot],
    active_step_ids: set[str],
    active_status: str,
) -> str:
    approval = _matching_approval(request, approvals)
    if approval is not None:
        approval_status = _approval_request_status(approval.status)
        if approval_status:
            return approval_status

    recovery = _matching_completed_recovery(request, replan_recoveries)
    if recovery is not None:
        return "recovered"

    tool_call = _matching_tool_call(request, tool_calls)
    if tool_call is not None and _text(tool_call.status):
        return _tool_request_status(tool_call.status)

    if active_status and _text(request.step_id) in active_step_ids:
        return active_status

    return _text(request.status) or "planned"


def _matching_tool_call(
    request: RuntimeExecutionRequestSnapshot,
    tool_calls: list[ToolCallSnapshot],
) -> ToolCallSnapshot | None:
    request_id = _text(request.request_id)
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    for tool_call in reversed(tool_calls):
        if request_id and _text(tool_call.tool_call_id) == request_id:
            return tool_call
    if request_step_id:
        for tool_call in reversed(tool_calls):
            if request_step_id not in {
                _text(tool_call.step_id),
                _text(tool_call.planner_step_id),
            }:
                continue
            if not request_tool or _text(tool_call.tool_name) == request_tool:
                return tool_call
        if any(_text(item.step_id) or _text(item.planner_step_id) for item in tool_calls):
            return None
    for tool_call in reversed(tool_calls):
        if request_tool and _text(tool_call.tool_name) == request_tool:
            return tool_call
    return None


def _matching_completed_recovery(
    request: RuntimeExecutionRequestSnapshot,
    recoveries: list[ReplanRecoverySnapshot],
) -> ReplanRecoverySnapshot | None:
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    request_capability = _text(request.capability_id)
    for recovery in reversed(recoveries):
        if _recovery_request_status(recovery) not in {"completed", "resolved"}:
            continue
        recovery_step_id = _text(recovery.source_step_id)
        recovery_tool = _text(recovery.source_tool_name)
        recovery_capability = _text(recovery.target_capability_id)
        if request_step_id and recovery_step_id and request_step_id != recovery_step_id:
            continue
        if request_tool and recovery_tool and request_tool != recovery_tool:
            continue
        if request_capability and recovery_capability and request_capability != recovery_capability:
            continue
        if request_step_id and recovery_step_id:
            return recovery
        if request_tool and recovery_tool:
            return recovery
        if request_capability and recovery_capability:
            return recovery
    return None


def _recovery_request_status(recovery: ReplanRecoverySnapshot) -> str:
    status = _text(recovery.status)
    if status:
        return status
    tool_status = _text(recovery.tool_status)
    if tool_status in {"completed", "resolved"}:
        return tool_status
    if _text(recovery.todo_status) == "completed" or _text(recovery.checkpoint_status) == "completed":
        return "completed"
    return ""


def _request_verification_update(
    request: RuntimeExecutionRequestSnapshot,
    *,
    events: list[PublicRunEvent],
    tool_calls: list[ToolCallSnapshot],
) -> dict[str, Any]:
    verification_status = ""
    verification_step_id = ""
    verification_event_ids: list[str] = []
    artifact_paths: list[str] = []

    for event in events:
        payload = _payload(event)
        if not _event_matches_request(event, payload, request):
            continue
        status = _verification_status(payload)
        if status:
            verification_status = status
            verification_step_id = _verification_step_id(payload) or verification_step_id
            _extend_unique(verification_event_ids, [_event_identity(event)])
        _extend_unique(artifact_paths, _artifact_paths_from_payload(payload))

    for tool_call in tool_calls:
        if not _tool_call_matches_request(tool_call, request):
            continue
        _extend_unique(artifact_paths, _artifact_paths_from_payload(tool_call.output_preview))
        _extend_unique(artifact_paths, _artifact_paths_from_payload(tool_call.metadata))

    update: dict[str, Any] = {}
    if verification_status:
        update["verification_status"] = verification_status
    if verification_step_id:
        update["verification_step_id"] = verification_step_id
    if verification_event_ids:
        update["verification_event_ids"] = verification_event_ids
    if artifact_paths:
        update["verification_artifact_paths"] = artifact_paths
    return update


def _request_replay_evidence_update(
    request: RuntimeExecutionRequestSnapshot,
    *,
    events: list[PublicRunEvent],
    tool_calls: list[ToolCallSnapshot],
    approvals: list[ApprovalCardSnapshot],
) -> dict[str, Any]:
    event_ids = _string_list(getattr(request, "event_ids", []))
    tool_call_ids = _string_list(getattr(request, "tool_call_ids", []))
    approval_ids = _string_list(getattr(request, "approval_ids", []))
    artifact_ids = _string_list(getattr(request, "artifact_ids", []))
    artifact_paths = _string_list(getattr(request, "artifact_paths", []))

    for event in events:
        payload = _payload(event)
        if not _event_matches_request(event, payload, request):
            continue
        _extend_unique(event_ids, [_event_identity(event)])
        _extend_unique(tool_call_ids, _tool_call_ids_from_payload(payload))
        _extend_unique(approval_ids, _approval_ids_from_payload(payload))
        _extend_unique(artifact_ids, _artifact_ids_from_payload(payload))
        _extend_unique(artifact_paths, _artifact_paths_from_payload(payload))

    for tool_call in tool_calls:
        if not _tool_call_matches_request(tool_call, request):
            continue
        _extend_unique(tool_call_ids, [tool_call.tool_call_id])
        _extend_unique(approval_ids, [tool_call.approval_id])
        for source in (tool_call.input_preview, tool_call.output_preview, tool_call.metadata):
            _extend_unique(tool_call_ids, _tool_call_ids_from_payload(source))
            _extend_unique(approval_ids, _approval_ids_from_payload(source))
            _extend_unique(artifact_ids, _artifact_ids_from_payload(source))
            _extend_unique(artifact_paths, _artifact_paths_from_payload(source))

    for approval in approvals:
        if not _approval_matches_request(approval, request, approvals=approvals):
            continue
        _extend_unique(approval_ids, [approval.approval_id])
        _extend_unique(tool_call_ids, _tool_call_ids_from_payload(approval.input_preview))
        _extend_unique(artifact_ids, _artifact_ids_from_payload(approval.input_preview))
        _extend_unique(artifact_paths, _artifact_paths_from_payload(approval.input_preview))

    update: dict[str, Any] = {}
    if event_ids:
        update["event_ids"] = event_ids
    if tool_call_ids:
        update["tool_call_ids"] = tool_call_ids
    if approval_ids:
        update["approval_ids"] = approval_ids
    if artifact_ids:
        update["artifact_ids"] = artifact_ids
    if artifact_paths:
        update["artifact_paths"] = artifact_paths
    return update


def _event_matches_request(
    event: PublicRunEvent,
    payload: dict[str, Any],
    request: RuntimeExecutionRequestSnapshot,
) -> bool:
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    request_capability = _text(request.capability_id)
    event_step_ids = _event_step_ids(payload)
    if request_step_id and request_step_id in event_step_ids:
        return True
    event_tool = _text(payload.get("tool_name") or payload.get("tool"))
    if request_tool and event_tool and request_tool == event_tool:
        return True
    event_capability = _text(payload.get("capability_id") or payload.get("target_capability_id"))
    if request_capability and event_capability and request_capability == event_capability:
        return True
    event_type = _text(event.event_type)
    if event_type.endswith(".artifact.created") or "artifact" in event_type:
        return _artifact_event_matches_request(payload, request)
    return False


def _tool_call_matches_request(
    tool_call: ToolCallSnapshot,
    request: RuntimeExecutionRequestSnapshot,
) -> bool:
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    request_capability = _text(request.capability_id)
    if request_step_id and request_step_id in {
        _text(tool_call.step_id),
        _text(tool_call.planner_step_id),
    }:
        return True
    if request_tool and request_tool == _text(tool_call.tool_name):
        return True
    return bool(request_capability and request_capability == _text(tool_call.capability_id))


def _artifact_event_matches_request(
    payload: dict[str, Any],
    request: RuntimeExecutionRequestSnapshot,
) -> bool:
    request_paths = {
        _text(item.get("path") or item.get("artifact_path"))
        for item in request.task_workspace_items
        if isinstance(item, dict)
    }
    request_paths.update(
        _text(item.get("path") or item.get("artifact_path"))
        for item in request.task_verification_targets
        if isinstance(item, dict)
    )
    request_paths = {item for item in request_paths if item}
    if not request_paths:
        return False
    return bool(request_paths.intersection(_artifact_paths_from_payload(payload)))


def _event_step_ids(payload: dict[str, Any]) -> set[str]:
    step_ids = {
        _text(payload.get("step_id")),
        _text(payload.get("planner_step_id")),
        _text(payload.get("source_step_id")),
        _text(payload.get("after_step_id")),
    }
    checkpoint = payload.get("checkpoint")
    if isinstance(checkpoint, dict):
        step_ids.add(_text(checkpoint.get("after_step_id")))
    todo = payload.get("todo")
    if isinstance(todo, dict):
        step_ids.add(_text(todo.get("step_id")))
    return {step_id for step_id in step_ids if step_id}


def _verification_status(payload: dict[str, Any]) -> str:
    status = _text(payload.get("verification_status"))
    if status:
        return status
    checkpoint = payload.get("checkpoint")
    if isinstance(checkpoint, dict):
        checkpoint_payload = checkpoint.get("payload")
        if isinstance(checkpoint_payload, dict):
            return _text(checkpoint_payload.get("verification_status"))
    return ""


def _verification_step_id(payload: dict[str, Any]) -> str:
    return _text(
        payload.get("verified_by_step_id")
        or payload.get("verification_step_id")
        or payload.get("step_id")
        or payload.get("planner_step_id")
    )


def _event_identity(event: PublicRunEvent) -> str:
    return _text(event.event_id) or f"{event.sequence}:{event.event_type}"


def _artifact_paths_from_payload(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    _extend_unique(paths, [payload.get("artifact_path")])
    _extend_unique(paths, _string_list(payload.get("artifact_paths")))
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        _extend_unique(paths, [artifact.get("path"), artifact.get("artifact_path")])
    for key in ("artifacts", "artifact_manifest"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                _extend_unique(paths, [item.get("path"), item.get("artifact_path")])
    for key in ("result", "data", "output", "output_preview"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            _extend_unique(paths, _artifact_paths_from_payload(nested))
    return paths


def _artifact_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    artifact_ids: list[str] = []
    _extend_unique(artifact_ids, [payload.get("artifact_id")])
    _extend_unique(artifact_ids, _string_list(payload.get("artifact_ids")))
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        _extend_unique(artifact_ids, [artifact.get("artifact_id"), artifact.get("id")])
    for key in ("artifacts", "artifact_manifest"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                _extend_unique(artifact_ids, [item.get("artifact_id"), item.get("id")])
    for key in ("result", "data", "output", "output_preview"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            _extend_unique(artifact_ids, _artifact_ids_from_payload(nested))
    return artifact_ids


def _tool_call_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    _extend_unique(values, _string_list(payload.get("tool_call_ids")))
    _extend_unique(values, [payload.get("tool_call_id")])
    return values


def _approval_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    _extend_unique(values, _string_list(payload.get("approval_ids")))
    _extend_unique(values, [payload.get("approval_id")])
    pending = payload.get("pending_approval")
    if isinstance(pending, dict):
        _extend_unique(values, [pending.get("approval_id")])
    approval = payload.get("approval")
    if isinstance(approval, dict):
        _extend_unique(values, [approval.get("approval_id")])
    return values


def _matching_approval(
    request: RuntimeExecutionRequestSnapshot,
    approvals: list[ApprovalCardSnapshot],
) -> ApprovalCardSnapshot | None:
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    for approval in reversed(approvals):
        if request_step_id and request_step_id in {
            _text(approval.step_id),
            _text(approval.planner_step_id),
        }:
            return approval
    if request_step_id and any(
        _text(item.step_id) or _text(item.planner_step_id) for item in approvals
    ):
        return None
    for approval in reversed(approvals):
        if request_tool and _text(approval.tool_name) == request_tool:
            return approval
    return None


def _approval_matches_request(
    approval: ApprovalCardSnapshot,
    request: RuntimeExecutionRequestSnapshot,
    *,
    approvals: list[ApprovalCardSnapshot] | None = None,
) -> bool:
    request_step_id = _text(request.step_id)
    request_tool = _text(request.tool_name)
    request_capability = _text(request.capability_id)
    if request_step_id and request_step_id in {
        _text(approval.step_id),
        _text(approval.planner_step_id),
    }:
        return True
    if request_step_id and any(
        _text(item.step_id) or _text(item.planner_step_id) for item in approvals or []
    ):
        return False
    if request_tool and request_tool == _text(approval.tool_name):
        return True
    return bool(request_capability and request_capability == _text(approval.capability_id))


def _same_approval(
    current: ApprovalCardSnapshot,
    candidate: ApprovalCardSnapshot,
) -> bool:
    current_id = _text(current.approval_id)
    candidate_id = _text(candidate.approval_id)
    return bool(current_id and current_id == candidate_id)


def _approval_request_status(status: str) -> str:
    clean = _text(status)
    if clean == "pending":
        return "waiting_approval"
    if clean == "approved":
        return "approved"
    if clean == "rejected":
        return "denied"
    if clean in {"cancelled", "expired"}:
        return clean
    return ""


def _tool_request_status(status: str) -> str:
    clean = _text(status)
    if clean == "approval_required":
        return "waiting_approval"
    return clean


def _active_task_request_status(
    task_progress: TaskProgressSummarySnapshot | None,
) -> str:
    status = _text(getattr(task_progress, "status", None))
    if not status:
        return ""
    if status in _TERMINAL_REQUEST_STATUSES:
        return status
    if status in {"running", "in_progress"}:
        return "running"
    if status in {"waiting_approval", "approval_required"}:
        return "waiting_approval"
    return ""


def _active_task_request_step_ids(
    task_progress: TaskProgressSummarySnapshot | None,
    *,
    fallback_step_id: str,
) -> set[str]:
    status = _text(getattr(task_progress, "status", None))
    if status in {"waiting_approval", "approval_required"}:
        approval_step_ids = {
            _text(item)
            for item in getattr(task_progress, "approval_step_ids", []) or []
            if _text(item)
        }
        if approval_step_ids:
            return approval_step_ids
    return {_text(fallback_step_id)} if _text(fallback_step_id) else set()


def _preferred_task_progress(
    current: TaskProgressSummarySnapshot | None,
    candidate: TaskProgressSummarySnapshot | None,
) -> TaskProgressSummarySnapshot | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    current_total = _progress_total(current)
    candidate_total = _progress_total(candidate)
    if candidate_total > current_total:
        return candidate
    return current


def _progress_total(progress: TaskProgressSummarySnapshot) -> int:
    return sum(
        value
        for value in (
            progress.total_todos,
            progress.total_checkpoints,
            progress.total_workspace_items,
        )
        if isinstance(value, int) and value > 0
    )


def _payload(event: PublicRunEvent) -> dict[str, Any]:
    return dict(event.payload) if isinstance(event.payload, dict) else {}


def _extend_unique(target: list[str], values: Iterable[Any]) -> None:
    for value in values:
        clean = _text(value)
        if clean and clean not in target:
            target.append(clean)


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [_text(value) for value in values if _text(value)]


def _text(value: Any) -> str:
    return str(value or "").strip()
