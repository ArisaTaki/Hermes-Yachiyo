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
    planner_summary: Any | None = None,
    runtime_execution_envelope: Any | None = None,
    task_core: Any | None = None,
    task_progress: Any | None = None,
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
    effective_task_core = _richer_task_core(
        task_core,
        _field(runtime_execution_envelope, "task_core"),
    )
    effective_task_progress = _richer_task_progress(
        task_progress,
        _field(runtime_execution_envelope, "task_progress"),
    )
    plan_tools = _planner_tools(planner_summary, runtime_execution_envelope)
    plan_capabilities = _planner_capabilities(planner_summary, runtime_execution_envelope)
    runtime_stage_counts = _runtime_stage_counts(runtime_execution_envelope)
    task_totals = _task_totals(effective_task_core, effective_task_progress)

    debug_surfaces = _debug_surfaces(
        event_items=event_items,
        tool_items=tool_items,
        approval_items=approval_items,
        artifact_items=artifact_items,
        memory_items=memory_items,
        skill_items=skill_items,
        child_items=child_items,
        replan_items=replan_items,
        planner_items=[item for item in (planner_summary, runtime_execution_envelope) if item is not None],
        task_items=[item for item in (effective_task_core, effective_task_progress) if item is not None],
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
        planner_decision_id=_optional_text(
            _field(planner_summary, "decision_id")
            or _field(runtime_execution_envelope, "decision_id")
        ),
        planner_plan_id=_optional_text(
            _field(planner_summary, "plan_id")
            or _field(runtime_execution_envelope, "plan_id")
        ),
        intent_kind=_optional_text(
            _field(planner_summary, "intent_kind")
            or _field(runtime_execution_envelope, "intent_kind")
        ),
        intent_title=_optional_text(_field(planner_summary, "intent_title")),
        route_to_studio=_optional_bool(
            _field(planner_summary, "route_to_studio"),
            _field(runtime_execution_envelope, "route_to_studio"),
        ),
        task_status=_optional_text(_field(effective_task_progress, "status")),
        current_step_id=_optional_text(_field(effective_task_progress, "current_step_id")),
        current_step_title=_optional_text(_field(effective_task_progress, "current_step_title")),
        current_tool_name=_optional_text(_field(effective_task_progress, "current_tool_name")),
        total_todos=task_totals["total_todos"],
        completed_todos=task_totals["completed_todos"],
        blocked_todos=task_totals["blocked_todos"],
        total_checkpoints=task_totals["total_checkpoints"],
        completed_checkpoints=task_totals["completed_checkpoints"],
        blocked_checkpoints=task_totals["blocked_checkpoints"],
        runtime_stage_counts=runtime_stage_counts,
        plan_tools=plan_tools,
        plan_capabilities=plan_capabilities,
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
    planner_items: list[Any],
    task_items: list[Any],
) -> list[str]:
    surfaces: list[str] = []
    for name, values in (
        ("planner", planner_items),
        ("task", task_items),
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


def _planner_tools(planner_summary: Any | None, envelope: Any | None) -> list[str]:
    tools = _string_list(_field(planner_summary, "plan_tools"))
    if tools:
        return tools
    selected = _string_list(_field(planner_summary, "selected_tools"))
    if selected:
        return selected
    return _unique_strings(
        _text(_field(request, "tool_name"))
        for request in _items(_field(envelope, "requests"))
    )


def _planner_capabilities(planner_summary: Any | None, envelope: Any | None) -> list[str]:
    capabilities = _string_list(_field(planner_summary, "plan_capabilities"))
    if capabilities:
        return capabilities
    required = _string_list(_field(planner_summary, "required_capabilities"))
    if required:
        return required
    return _unique_strings(
        _text(_field(request, "capability_id"))
        for request in _items(_field(envelope, "requests"))
    )


def _runtime_stage_counts(envelope: Any | None) -> dict[str, int]:
    raw_counts = _field(envelope, "runtime_stage_counts")
    if isinstance(raw_counts, dict):
        counts = {
            _text(key): int(value)
            for key, value in raw_counts.items()
            if _text(key) and isinstance(value, int)
        }
        if counts:
            return counts
    counts: dict[str, int] = {}
    for request in _items(_field(envelope, "requests")):
        stage = _text(_field(request, "runtime_stage"))
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def _task_totals(task_core: Any | None, task_progress: Any | None) -> dict[str, int]:
    total_todos = _int_field(task_progress, "total_todos")
    completed_todos = _int_field(task_progress, "completed_todos")
    blocked_todos = _int_field(task_progress, "blocked_todos")
    total_checkpoints = _int_field(task_progress, "total_checkpoints")
    completed_checkpoints = _int_field(task_progress, "completed_checkpoints")
    blocked_checkpoints = _int_field(task_progress, "blocked_checkpoints")

    if task_core is not None:
        todos = _items(_field(task_core, "todos"))
        checkpoints = _items(_field(task_core, "checkpoints"))
        total_todos = total_todos or len(todos)
        completed_todos = completed_todos or _count_status(todos, "completed")
        blocked_todos = blocked_todos or _count_status(todos, "blocked")
        total_checkpoints = total_checkpoints or len(checkpoints)
        completed_checkpoints = completed_checkpoints or _count_status(checkpoints, "completed")
        blocked_checkpoints = blocked_checkpoints or _count_status(checkpoints, "blocked")

    return {
        "total_todos": total_todos,
        "completed_todos": completed_todos,
        "blocked_todos": blocked_todos,
        "total_checkpoints": total_checkpoints,
        "completed_checkpoints": completed_checkpoints,
        "blocked_checkpoints": blocked_checkpoints,
    }


def _richer_task_progress(primary: Any | None, fallback: Any | None) -> Any | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    primary_total = _int_field(primary, "total_todos") + _int_field(
        primary,
        "total_checkpoints",
    )
    fallback_total = _int_field(fallback, "total_todos") + _int_field(
        fallback,
        "total_checkpoints",
    )
    return fallback if fallback_total > primary_total else primary


def _richer_task_core(primary: Any | None, fallback: Any | None) -> Any | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    primary_total = len(_items(_field(primary, "todos"))) + len(
        _items(_field(primary, "checkpoints"))
    )
    fallback_total = len(_items(_field(fallback, "todos"))) + len(
        _items(_field(fallback, "checkpoints"))
    )
    return fallback if fallback_total > primary_total else primary


def _count_status(items: list[Any], status: str) -> int:
    return sum(1 for item in items if _text(_field(item, "status")) == status)


def _int_field(item: Any, key: str) -> int:
    value = _field(item, key)
    return value if isinstance(value, int) and value > 0 else 0


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, dict)):
        return []
    return _unique_strings(_text(item) for item in values)


def _unique_strings(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _text(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


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
