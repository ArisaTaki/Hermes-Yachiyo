"""Overlay observed execution status onto runtime execution envelopes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import (
    ApprovalCardSnapshot,
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
    "skipped",
}


def runtime_execution_envelope_with_status_overlay(
    envelope: RuntimeExecutionEnvelopeSnapshot | None,
    *,
    tool_calls: Iterable[ToolCallSnapshot] | None = None,
    approvals: Iterable[ApprovalCardSnapshot] | None = None,
    pending_approval: ApprovalCardSnapshot | None = None,
    task_progress: TaskProgressSummarySnapshot | None = None,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    """Return a copy of the envelope with request statuses reconciled from run facts."""

    if envelope is None or not envelope.requests:
        return envelope

    tool_items = [item for item in tool_calls or [] if item is not None]
    approval_items = [item for item in approvals or [] if item is not None]
    if pending_approval is not None and not any(
        _same_approval(item, pending_approval) for item in approval_items
    ):
        approval_items.append(pending_approval)

    current_step_id = _text(getattr(task_progress, "current_step_id", None))
    active_status = _active_task_request_status(task_progress)
    requests: list[RuntimeExecutionRequestSnapshot] = []
    for request in envelope.requests:
        status = _observed_request_status(
            request,
            tool_calls=tool_items,
            approvals=approval_items,
            current_step_id=current_step_id,
            active_status=active_status,
        )
        requests.append(request.model_copy(update={"status": status}) if status else request)

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
    current_step_id: str,
    active_status: str,
) -> str:
    approval = _matching_approval(request, approvals)
    if approval is not None:
        approval_status = _approval_request_status(approval.status)
        if approval_status:
            return approval_status

    tool_call = _matching_tool_call(request, tool_calls)
    if tool_call is not None and _text(tool_call.status):
        return _tool_request_status(tool_call.status)

    if active_status and current_step_id and _text(request.step_id) == current_step_id:
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


def _text(value: Any) -> str:
    return str(value or "").strip()
