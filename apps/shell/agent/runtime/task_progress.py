"""Task-core progress projections for runtime tool execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def append_task_progress_events_for_tool_result(
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None = None,
    run_id: str = "",
) -> None:
    step_id = str(tool_request.get("step_id") or tool_request.get("planner_step_id") or "").strip()
    tool_name = str(tool_request.get("tool") or tool_request.get("tool_name") or "").strip()
    if not step_id or not tool_name:
        return

    todo = tool_request.get("task_todo") if isinstance(tool_request.get("task_todo"), Mapping) else {}
    checkpoints = _mapping_items(tool_request.get("task_checkpoints"))
    workspace_items = _mapping_items(tool_request.get("task_workspace_items"))
    replan_request_id = str(tool_request.get("replan_request_id") or "").strip()
    if not todo and not checkpoints and not workspace_items and not replan_request_id:
        return

    result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
    todo_status = _task_todo_status_for_tool_result(str(tool_event.get("event") or ""), result)
    checkpoint_status = _task_checkpoint_status_for_todo_status(todo_status, result)
    skip_statuses = {todo_status}
    if todo_status != "completed":
        skip_statuses.add("completed")
    task_update_already_recorded = _runtime_planner_step_has_status(
        timeline,
        decision_id=str(tool_request.get("decision_id") or ""),
        step_id=step_id,
        statuses=skip_statuses,
    )

    source_event = {
        "event": str(tool_event.get("event") or ""),
        "detail": str(tool_event.get("detail") or tool_name),
    }
    base_payload = {
        "source": str(tool_request.get("source") or "runtime_planner"),
        "core_id": str(tool_request.get("core_id") or ""),
        "workspace_id": str(tool_request.get("workspace_id") or ""),
        "decision_id": str(tool_request.get("decision_id") or ""),
        "plan_id": str(tool_request.get("plan_id") or ""),
        "step_id": step_id,
        "tool": tool_name,
        "source_event": source_event,
        "result_preview": _task_progress_result_preview(result),
    }
    for key in (
        "task_id",
        "run_group_id",
        "group_run_id",
        "group_id",
        "workflow_run_id",
        "workflow_id",
        "workflow_node_id",
    ):
        value = str(tool_request.get(key) or "").strip()
        if value:
            base_payload[key] = value

    if not task_update_already_recorded:
        for workspace_item in workspace_items:
            item_payload = dict(workspace_item)
            item_payload["status"] = todo_status
            payload = {
                **base_payload,
                "workspace_item_id": str(workspace_item.get("item_id") or "").strip(),
                "status": todo_status,
                "previous_status": str(workspace_item.get("status") or "planned"),
                "workspace_item": item_payload,
            }
            _append_task_progress_event(
                "agent.task.workspace_item.updated",
                str(workspace_item.get("title") or step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )

    if todo and not task_update_already_recorded:
        todo_payload = dict(todo)
        todo_payload["status"] = todo_status
        payload = {
            **base_payload,
            "todo_id": str(todo.get("todo_id") or "").strip(),
            "status": todo_status,
            "previous_status": str(todo.get("status") or "pending"),
            "todo": todo_payload,
        }
        _append_task_progress_event(
            "agent.task.todo.updated",
            str(todo.get("title") or step_id),
            payload,
            timeline=timeline,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            run_id=run_id,
        )

    if not task_update_already_recorded:
        for checkpoint in checkpoints:
            checkpoint_payload = dict(checkpoint)
            checkpoint_payload["status"] = checkpoint_status
            payload = {
                **base_payload,
                "checkpoint_id": str(checkpoint.get("checkpoint_id") or "").strip(),
                "status": checkpoint_status,
                "previous_status": str(checkpoint.get("status") or "planned"),
                "checkpoint": checkpoint_payload,
            }
            _append_task_progress_event(
                "agent.task.checkpoint.updated",
                str(checkpoint.get("title") or step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )

    if replan_request_id:
        _append_replan_recovery_update_event(
            tool_request,
            base_payload,
            status=checkpoint_status,
            todo_status=todo_status,
            checkpoint_status=checkpoint_status,
            timeline=timeline,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            run_id=run_id,
        )


def _append_replan_recovery_update_event(
    tool_request: Mapping[str, Any],
    base_payload: Mapping[str, Any],
    *,
    status: str,
    todo_status: str,
    checkpoint_status: str,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    request_id = str(tool_request.get("replan_request_id") or "").strip()
    if not request_id:
        return
    task_todo = (
        tool_request.get("task_todo")
        if isinstance(tool_request.get("task_todo"), Mapping)
        else {}
    )
    payload: dict[str, Any] = {
        **dict(base_payload),
        "request_id": request_id,
        "replan_request_id": request_id,
        "trigger": str(tool_request.get("replan_trigger") or "tool_failure").strip(),
        "replan_trigger": str(tool_request.get("replan_trigger") or "tool_failure").strip(),
        "status": status,
        "source_step_id": str(
            tool_request.get("source_step_id")
            or tool_request.get("planner_step_id")
            or tool_request.get("step_id")
            or ""
        ).strip(),
        "source_tool_name": _first_text(
            tool_request.get("source_tool_name"),
            task_todo.get("tool_name") if isinstance(task_todo, Mapping) else "",
        ),
        "selected_step_id": str(
            tool_request.get("step_id") or tool_request.get("planner_step_id") or ""
        ).strip(),
        "selected_tool_name": str(
            tool_request.get("tool") or tool_request.get("tool_name") or ""
        ).strip(),
        "target_capability_id": str(
            tool_request.get("capability_id")
            or tool_request.get("target_capability_id")
            or ""
        ).strip(),
        "planning_reason": str(tool_request.get("planning_reason") or "").strip(),
        "tool_status": status,
        "todo_status": todo_status,
        "checkpoint_status": checkpoint_status,
    }
    for key in ("task_id", "group_run_id", "workflow_run_id"):
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in ("recovery_action_label", "permission_target", "risk_level"):
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    fallback_tools = _string_list(tool_request.get("fallback_tools"))
    selected_tool = str(payload.get("selected_tool_name") or "").strip()
    if selected_tool and selected_tool not in fallback_tools:
        fallback_tools.append(selected_tool)
    if fallback_tools:
        payload["fallback_tools"] = fallback_tools
    for key in ("action_target", "observation_evidence"):
        value = tool_request.get(key)
        if isinstance(value, Mapping) and value:
            payload[key] = dict(value)
    _append_replan_progress_event(
        "agent.replan.recovery.updated",
        str(payload.get("recovery_action_label") or selected_tool or request_id),
        payload,
        timeline=timeline,
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        run_id=run_id,
    )


def _append_replan_progress_event(
    event_type: str,
    detail: str,
    payload: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if _runtime_replan_recovery_update_exists(timeline, event_type, payload):
        return
    timeline.append(timeline_factory(event_type, detail, **payload))
    if run_id and append_run_event is not None:
        append_run_event(run_id, event_type, payload)


def _runtime_replan_recovery_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    request_id = str(payload.get("request_id") or payload.get("replan_request_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    selected_tool = str(payload.get("selected_tool_name") or payload.get("tool") or "").strip()
    return any(
        isinstance(event, Mapping)
        and str(event.get("event") or "").strip() == event_type
        and _first_text(
            event.get("request_id"),
            event.get("replan_request_id"),
            _event_payload(event).get("request_id"),
            _event_payload(event).get("replan_request_id"),
        )
        == request_id
        and (
            not status
            or str(event.get("status") or _event_payload(event).get("status") or "").strip()
            == status
        )
        and (
            not selected_tool
            or _first_text(
                event.get("selected_tool_name"),
                event.get("tool"),
                _event_payload(event).get("selected_tool_name"),
                _event_payload(event).get("tool"),
            )
            == selected_tool
        )
        for event in timeline
    )


def _first_text(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _append_task_progress_event(
    event_type: str,
    detail: str,
    payload: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if _runtime_task_update_exists(timeline, event_type, payload):
        return
    timeline.append(timeline_factory(event_type, detail, **payload))
    if run_id and append_run_event is not None:
        append_run_event(run_id, event_type, payload)


def _task_todo_status_for_tool_result(event_type: str, result: Mapping[str, Any]) -> str:
    if not isinstance(result, Mapping):
        return "blocked"
    if result.get("approval_required"):
        return "blocked"
    if str(event_type or "").strip() == "agent.tool.skipped":
        return "skipped" if result.get("blocked_by_user_goal") else "blocked"
    return "blocked" if _tool_result_requests_replan(result) else "completed"


def _task_checkpoint_status_for_todo_status(
    todo_status: str,
    result: Mapping[str, Any],
) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if todo_status == "completed":
        return "completed"
    return "blocked"


def _tool_result_requests_replan(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return True
    if result.get("ok") is True and not result.get("approval_required"):
        return False
    return True


def _task_progress_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "action",
        "summary",
        "error",
        "hint",
        "returncode",
        "exit_code",
        "blocked_by_user_goal",
        "approval_required",
    ):
        if key in result:
            preview[key] = result.get(key)
    stderr = str(result.get("stderr") or "").strip()
    if stderr:
        preview["stderr"] = stderr[:500]
    return preview


def _runtime_task_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    identity_key = (
        "todo_id"
        if event_type == "agent.task.todo.updated"
        else "workspace_item_id"
        if event_type == "agent.task.workspace_item.updated"
        else "checkpoint_id"
        if event_type == "agent.task.checkpoint.updated"
        else ""
    )
    identity = str(payload.get(identity_key) or "").strip() if identity_key else ""
    status = str(payload.get("status") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    return any(
        isinstance(event, Mapping)
        and str(event.get("event") or "").strip() == event_type
        and (
            not decision_id
            or str(event.get("decision_id") or "").strip() == decision_id
            or str(_event_payload(event).get("decision_id") or "").strip() == decision_id
        )
        and (
            not identity
            or str(event.get(identity_key) or "").strip() == identity
            or str(_event_payload(event).get(identity_key) or "").strip() == identity
        )
        and (
            not status
            or str(event.get("status") or "").strip() == status
            or str(_event_payload(event).get("status") or "").strip() == status
        )
        for event in timeline
    )


def _runtime_planner_step_has_status(
    timeline: list[dict[str, Any]],
    *,
    decision_id: str,
    step_id: str,
    statuses: set[str],
) -> bool:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id:
        return False
    clean_decision_id = str(decision_id or "").strip()
    expected_statuses = {
        str(status or "").strip()
        for status in statuses
        if str(status or "").strip()
    }
    if not expected_statuses:
        return False
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        payload = _event_payload(event)
        if str(event.get("event") or "").strip() != "agent.task.todo.updated":
            continue
        event_step_id = str(event.get("step_id") or payload.get("step_id") or "").strip()
        if event_step_id != clean_step_id:
            continue
        event_decision_id = str(
            event.get("decision_id") or payload.get("decision_id") or ""
        ).strip()
        if clean_decision_id and event_decision_id != clean_decision_id:
            continue
        event_status = str(event.get("status") or payload.get("status") or "").strip()
        if event_status in expected_statuses:
            return True
    return False


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}
