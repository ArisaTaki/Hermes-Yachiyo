"""Shared Runtime debug summary projection for Chat and Agent Studio."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import RuntimeDebugSummarySnapshot


def runtime_debug_summary_from_runtime_objects(
    *,
    run_id: str = "",
    task_id: str = "",
    group_id: str = "",
    group_run_id: str = "",
    workflow_id: str = "",
    workflow_run_id: str = "",
    events: Iterable[Any] | None = None,
    tool_calls: Iterable[Any] | None = None,
    approvals: Iterable[Any] | None = None,
    pending_approval: Any | None = None,
    artifacts: Iterable[Any] | None = None,
    memory_traces: Iterable[Any] | None = None,
    skill_traces: Iterable[Any] | None = None,
    children: Iterable[Any] | None = None,
    replan_recoveries: Iterable[Any] | None = None,
    needs_user_action: bool = False,
    needs_replan: bool = False,
) -> RuntimeDebugSummarySnapshot:
    event_items = _items(events)
    tool_items = _items(tool_calls)
    approval_items = _approval_items(approvals, pending_approval)
    artifact_items = _items(artifacts)
    memory_items = _items(memory_traces)
    skill_items = _items(skill_traces)
    child_items = _items(children)
    replan_items = _items(replan_recoveries)

    tool_statuses = [_text(_field(item, "status")) for item in tool_items]
    pending_approvals = [
        item for item in approval_items if _text(_field(item, "status")) == "pending"
    ]
    latest_event = event_items[-1] if event_items else None
    latest_tool = tool_items[-1] if tool_items else None
    latest_approval = pending_approvals[-1] if pending_approvals else (
        approval_items[-1] if approval_items else None
    )
    latest_artifact = artifact_items[-1] if artifact_items else None

    debug_surfaces = _debug_surfaces(
        event_items=event_items,
        tool_items=tool_items,
        approval_items=approval_items,
        artifact_items=artifact_items,
        memory_items=memory_items,
        skill_items=skill_items,
        child_items=child_items,
        replan_items=replan_items,
    )
    replan_needed = needs_replan or bool(replan_items) or any(
        "replan" in _text(_field(event, "event_type")) for event in event_items
    )

    return RuntimeDebugSummarySnapshot(
        run_id=_optional_text(run_id),
        task_id=_optional_text(task_id),
        group_id=_optional_text(group_id),
        group_run_id=_optional_text(group_run_id),
        workflow_id=_optional_text(workflow_id),
        workflow_run_id=_optional_text(workflow_run_id),
        event_count=len(event_items),
        tool_call_count=len(tool_items),
        completed_tool_call_count=sum(status == "completed" for status in tool_statuses),
        failed_tool_call_count=sum(status == "failed" for status in tool_statuses),
        blocked_tool_call_count=sum(status == "blocked" for status in tool_statuses),
        waiting_tool_call_count=sum(
            status in {"approval_required", "waiting_approval"}
            for status in tool_statuses
        ),
        approval_count=len(approval_items),
        pending_approval_count=len(pending_approvals),
        artifact_count=len(artifact_items),
        memory_trace_count=len(memory_items),
        skill_trace_count=len(skill_items),
        child_run_count=len(child_items),
        replan_recovery_count=len(replan_items),
        needs_user_action=bool(needs_user_action or pending_approvals),
        needs_replan=bool(replan_needed),
        latest_event_type=_optional_text(_field(latest_event, "event_type")),
        latest_tool_name=_optional_text(_field(latest_tool, "tool_name")),
        latest_tool_status=_optional_text(_field(latest_tool, "status")),
        latest_approval_id=_optional_text(_field(latest_approval, "approval_id")),
        latest_artifact_path=_optional_text(
            _field(latest_artifact, "path") or _field(latest_artifact, "title")
        ),
        debug_surfaces=debug_surfaces,
    )


def _approval_items(approvals: Iterable[Any] | None, pending_approval: Any | None) -> list[Any]:
    items = _items(approvals)
    if pending_approval is None:
        return items
    pending_id = _text(_field(pending_approval, "approval_id"))
    if pending_id and any(_text(_field(item, "approval_id")) == pending_id for item in items):
        return items
    return [*items, pending_approval]


def _debug_surfaces(
    *,
    event_items: list[Any],
    tool_items: list[Any],
    approval_items: list[Any],
    artifact_items: list[Any],
    memory_items: list[Any],
    skill_items: list[Any],
    child_items: list[Any],
    replan_items: list[Any],
) -> list[str]:
    surfaces: list[str] = []
    for name, values in (
        ("timeline", event_items),
        ("tools", tool_items),
        ("approvals", approval_items),
        ("artifacts", artifact_items),
        ("memory", memory_items),
        ("skills", skill_items),
        ("children", child_items),
        ("replan", replan_items),
    ):
        if values:
            surfaces.append(name)
    return surfaces


def _items(values: Iterable[Any] | None) -> list[Any]:
    if values is None:
        return []
    return [item for item in values if item is not None]


def _field(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return str(value or "").strip()
