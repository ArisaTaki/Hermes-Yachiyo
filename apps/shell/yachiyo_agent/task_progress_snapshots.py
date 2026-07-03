"""Shared task progress summaries for Chat and Agent Studio."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    PublicRunEvent,
    TaskCoreSnapshot,
    TaskProgressSummarySnapshot,
    TaskTodoItemSnapshot,
)


def task_progress_summary_from_task_core(
    task_core: TaskCoreSnapshot | None,
    *,
    events: Iterable[PublicRunEvent] | None = None,
    needs_user_action: bool = False,
) -> TaskProgressSummarySnapshot | None:
    if task_core is None:
        return None

    event_list = list(events or [])
    todos = list(task_core.todos or [])
    checkpoints = list(task_core.checkpoints or [])
    workspace_items = list(task_core.workspace.items or [])
    latest_replan = _latest_unresolved_replan_event(event_list)
    blocked_step_ids = _blocked_step_ids(todos)
    approval_step_ids = _approval_step_ids(todos, checkpoints, event_list)
    status = _summary_status(
        todos,
        checkpoints,
        replan_requested=latest_replan is not None,
        needs_user_action=bool(needs_user_action or approval_step_ids),
    )
    current = _current_todo(todos)
    completed_todos = _count_status(todos, "completed")
    total_todos = len(todos)
    blocked_todos = _count_status(todos, "blocked")
    active_todos = _count_status(todos, "in_progress")
    skipped_todos = _count_status(todos, "skipped")
    completed_checkpoints = _count_status(checkpoints, "completed")
    blocked_checkpoints = _count_status(checkpoints, "blocked")
    waiting_approval_checkpoints = _count_status(checkpoints, "waiting_approval")
    completed_workspace_items = _count_status(workspace_items, "completed")
    blocked_workspace_items = _count_status(workspace_items, "blocked")
    verification_counts = _verification_counts(checkpoints, todos, workspace_items)
    latest_verification = _latest_verification_status(event_list)
    latest_payload = latest_replan.payload if latest_replan is not None else {}

    return TaskProgressSummarySnapshot(
        core_id=task_core.core_id,
        workspace_id=task_core.workspace.workspace_id,
        status=status,
        current_step_id=current.step_id if current is not None else None,
        current_step_title=current.title if current is not None else None,
        current_tool_name=current.tool_name if current is not None else None,
        total_todos=total_todos,
        completed_todos=completed_todos,
        active_todos=active_todos,
        blocked_todos=blocked_todos,
        skipped_todos=skipped_todos,
        total_checkpoints=len(checkpoints),
        completed_checkpoints=completed_checkpoints,
        blocked_checkpoints=blocked_checkpoints,
        waiting_approval_checkpoints=waiting_approval_checkpoints,
        total_workspace_items=len(workspace_items),
        completed_workspace_items=completed_workspace_items,
        blocked_workspace_items=blocked_workspace_items,
        pending_verification_count=verification_counts["pending"],
        failed_verification_count=verification_counts["failed"],
        verified_verification_count=verification_counts["verified"],
        latest_verification_status=latest_verification.get("status"),
        latest_verification_step_id=latest_verification.get("step_id"),
        replan_request_count=_replan_request_count(event_list),
        latest_replan_request_id=_optional_text(latest_payload.get("request_id")),
        latest_replan_trigger=_optional_text(latest_payload.get("trigger")),
        latest_replan_step_id=_optional_text(latest_payload.get("source_step_id")),
        needs_replan=latest_replan is not None,
        needs_user_action=bool(needs_user_action or approval_step_ids),
        blocked_step_ids=blocked_step_ids,
        approval_step_ids=approval_step_ids,
        progress_text=_progress_text(
            total=total_todos,
            completed=completed_todos,
            blocked=blocked_todos,
            waiting_approval=waiting_approval_checkpoints,
            pending_verifications=verification_counts["pending"],
            failed_verifications=verification_counts["failed"],
            replan_requested=latest_replan is not None,
        ),
    )


def _current_todo(todos: list[TaskTodoItemSnapshot]) -> TaskTodoItemSnapshot | None:
    for status in ("in_progress", "blocked", "pending", "skipped"):
        for todo in todos:
            if _status(todo) == status:
                return todo
    return todos[-1] if todos else None


def _summary_status(
    todos: list[TaskTodoItemSnapshot],
    checkpoints: list[Any],
    *,
    replan_requested: bool,
    needs_user_action: bool,
) -> str:
    if needs_user_action or any(_status(checkpoint) == "waiting_approval" for checkpoint in checkpoints):
        return "waiting_approval"
    if replan_requested:
        return "replan_requested"
    if any(_status(todo) == "blocked" for todo in todos) or any(
        _status(checkpoint) == "blocked" for checkpoint in checkpoints
    ):
        return "blocked"
    if any(_status(todo) == "in_progress" for todo in todos):
        return "running"
    if todos and all(_status(todo) in {"completed", "skipped"} for todo in todos):
        return "completed"
    if todos:
        return "planned"
    return "unknown"


def _blocked_step_ids(todos: list[TaskTodoItemSnapshot]) -> list[str]:
    return _dedupe(
        str(todo.step_id or "").strip()
        for todo in todos
        if _status(todo) == "blocked"
    )


def _approval_step_ids(
    todos: list[TaskTodoItemSnapshot],
    checkpoints: list[Any],
    events: list[PublicRunEvent],
) -> list[str]:
    step_ids: list[str] = []
    step_ids.extend(
        str(todo.step_id or "").strip()
        for todo in todos
        if bool(todo.approval_required) and _status(todo) not in {"completed", "skipped"}
    )
    step_ids.extend(
        str(getattr(checkpoint, "after_step_id", "") or "").strip()
        for checkpoint in checkpoints
        if _status(checkpoint) == "waiting_approval"
    )
    for event in events:
        if not _event_is_approval(event):
            continue
        step_id = _text(event.payload.get("step_id") or event.payload.get("planner_step_id"))
        if step_id:
            step_ids.append(step_id)
    return _dedupe(step_ids)


def _latest_unresolved_replan_event(events: list[PublicRunEvent]) -> PublicRunEvent | None:
    resolved_request_ids: set[str] = set()
    for event in reversed(events):
        request_id = _replan_request_id(event)
        if request_id and not _event_is_replan(event) and _event_resolves_replan(event):
            resolved_request_ids.add(request_id)
            continue
        if not _event_is_replan(event):
            continue
        if request_id and request_id in resolved_request_ids:
            continue
        return event
    return None


def _replan_request_count(events: list[PublicRunEvent]) -> int:
    return sum(1 for event in events if _event_is_replan(event))


def _event_is_replan(event: PublicRunEvent) -> bool:
    event_type = _base_event_type(event)
    return event_type == "agent.replan.requested" or event_type.endswith(".replan.requested")


def _event_resolves_replan(event: PublicRunEvent) -> bool:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("status") or payload.get("tool_status")).lower() in {
        "completed",
        "resolved",
    }


def _replan_request_id(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("request_id") or payload.get("replan_request_id"))


def _event_is_approval(event: PublicRunEvent) -> bool:
    event_type = _base_event_type(event)
    return (
        event_type.endswith(".approval_required")
        or event_type.endswith("_approval_required")
        or event_type == "tool.approval_required"
        or event_type == "agent.tool.approval_required"
    )


def _base_event_type(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("planner_event_type") or event.event_type)


def _count_status(items: Iterable[Any], status: str) -> int:
    return sum(1 for item in items if _status(item) == status)


def _verification_counts(
    checkpoints: list[Any],
    todos: list[TaskTodoItemSnapshot],
    workspace_items: list[Any],
) -> dict[str, int]:
    statuses = _verification_statuses(checkpoints, source_kind="checkpoint")
    if not statuses:
        statuses = _verification_statuses(todos, source_kind="todo")
    if not statuses:
        statuses = _verification_statuses(workspace_items, source_kind="workspace_item")
    return {
        "pending": sum(1 for status in statuses if status == "pending_verification"),
        "failed": sum(1 for status in statuses if status == "verification_failed"),
        "verified": sum(1 for status in statuses if status == "verified"),
    }


def _verification_statuses(items: Iterable[Any], *, source_kind: str) -> list[str]:
    statuses: list[str] = []
    for item in items:
        status = _verification_status(item, source_kind=source_kind)
        if status:
            statuses.append(status)
    return statuses


def _verification_status(item: Any, *, source_kind: str) -> str:
    source = {}
    if source_kind == "checkpoint":
        source = getattr(item, "payload", {}) or {}
    elif source_kind in {"todo", "workspace_item"}:
        source = getattr(item, "metadata", {}) or {}
    if not isinstance(source, Mapping):
        return ""
    return _text(source.get("verification_status"))


def _latest_verification_status(events: list[PublicRunEvent]) -> dict[str, str | None]:
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        status = _text(payload.get("verification_status"))
        if not status:
            continue
        return {
            "status": status,
            "step_id": _optional_text(
                payload.get("step_id")
                or payload.get("verified_by_step_id")
                or payload.get("planner_step_id")
            ),
        }
    return {"status": None, "step_id": None}


def _status(item: Any) -> str:
    return _text(getattr(item, "status", ""))


def _progress_text(
    *,
    total: int,
    completed: int,
    blocked: int,
    waiting_approval: int,
    pending_verifications: int,
    failed_verifications: int,
    replan_requested: bool,
) -> str:
    if not total:
        return "No task steps"
    parts = [f"{completed}/{total} todos completed"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if waiting_approval:
        parts.append(f"{waiting_approval} waiting approval")
    if pending_verifications:
        parts.append(f"{pending_verifications} verification pending")
    if failed_verifications:
        parts.append(f"{failed_verifications} verification failed")
    if replan_requested:
        parts.append("replan requested")
    return " | ".join(parts)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
