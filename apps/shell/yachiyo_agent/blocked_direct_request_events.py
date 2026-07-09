"""Project blocked direct runtime requests into public progress events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent
from .events import public_run_event_from_payload


def run_events_with_blocked_direct_request_progress_events(
    events: list[PublicRunEvent],
    payload: Mapping[str, Any],
    *,
    run_id: str,
    task_id: str = "",
    group_run_id: str = "",
    workflow_run_id: str = "",
    created_at: str = "",
) -> list[PublicRunEvent]:
    blocked_requests = _blocked_direct_requests_from_payload(payload)
    if not blocked_requests:
        return events
    existing_keys = _existing_blocked_direct_event_keys(events)
    next_sequence = max([int(event.sequence or 0) for event in events] or [0]) + 1
    projected: list[PublicRunEvent] = []
    for request in blocked_requests:
        event_key = _blocked_direct_event_key(request)
        if event_key and event_key in existing_keys:
            continue
        if event_key:
            existing_keys.add(event_key)
        for event_type, event_payload in _blocked_direct_progress_payloads(
            request,
            run_id=run_id,
            task_id=task_id,
            group_run_id=group_run_id,
            workflow_run_id=workflow_run_id,
        ):
            projected.append(
                public_run_event_from_payload(
                    {
                        "run_id": run_id,
                        "sequence": next_sequence,
                        "event_type": event_type,
                        "title": _blocked_direct_event_title(event_type),
                        "detail": _blocked_direct_request_detail(request),
                        "payload": event_payload,
                        "created_at": created_at,
                    },
                    run_id=run_id,
                    sequence=next_sequence,
                )
            )
            next_sequence += 1
    return [*events, *projected]


def _blocked_direct_requests_from_payload(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    requests: list[Mapping[str, Any]] = []
    _extend_blocked_direct_requests(requests, payload)
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        _extend_blocked_direct_requests(requests, metadata)
    unique: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for request in requests:
        key = (
            _text(request.get("request_id")),
            _blocked_direct_step_id(request),
            _blocked_direct_tool_name(request),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)
    return unique


def _extend_blocked_direct_requests(
    requests: list[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> None:
    for key in ("yachiyo_blocked_direct_tool_requests", "blocked_direct_tool_requests"):
        raw_requests = payload.get(key)
        if not isinstance(raw_requests, list):
            continue
        for request in raw_requests:
            if isinstance(request, Mapping):
                requests.append(request)


def _blocked_direct_progress_payloads(
    request: Mapping[str, Any],
    *,
    run_id: str,
    task_id: str,
    group_run_id: str,
    workflow_run_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    step_id = _blocked_direct_step_id(request)
    tool_name = _blocked_direct_tool_name(request)
    if not step_id and not tool_name:
        return []
    metadata = _blocked_direct_runtime_metadata(request)
    base = {
        "source": "runtime_blocked_direct_request",
        "runtime_blocked_request_id": _text(request.get("request_id")),
        "step_id": step_id,
        "planner_step_id": step_id,
        "tool": tool_name,
        "tool_name": tool_name,
        "status": "blocked",
        "reason": _blocked_direct_request_detail(request),
        "blocking_conditions": _blocked_direct_blocking_conditions(request),
        "workflow_run_id": workflow_run_id,
        "group_run_id": group_run_id,
    }
    base = {key: value for key, value in base.items() if value not in ("", [], None)}
    return [
        (
            _blocked_direct_event_type(
                "agent.task.todo.updated",
                group_run_id=group_run_id,
                workflow_run_id=workflow_run_id,
            ),
            {
                **base,
                "todo": {
                    "step_id": step_id,
                    "tool_name": tool_name,
                    "status": "blocked",
                    "metadata": metadata,
                },
            },
        ),
        (
            _blocked_direct_event_type(
                "agent.task.checkpoint.updated",
                group_run_id=group_run_id,
                workflow_run_id=workflow_run_id,
            ),
            {
                **base,
                "checkpoint": {
                    "after_step_id": step_id,
                    "status": "blocked",
                    "payload": metadata,
                },
            },
        ),
        (
            _blocked_direct_event_type(
                "agent.replan.requested",
                group_run_id=group_run_id,
                workflow_run_id=workflow_run_id,
            ),
            {
                **base,
                "request_id": _blocked_direct_replan_request_id(request),
                "trigger": "runtime_blocked",
                "run_id": run_id or None,
                "task_id": task_id or None,
                "group_run_id": group_run_id or None,
                "workflow_run_id": workflow_run_id or None,
                "source_step_id": step_id or None,
                "source_tool_name": tool_name or None,
                "condition": _blocked_direct_request_detail(request),
                "failure_event_type": "runtime.blocked_direct_request",
                "failure_detail": _blocked_direct_request_detail(request),
                "metadata": metadata,
            },
        ),
    ]


def _blocked_direct_event_type(
    event_type: str,
    *,
    group_run_id: str,
    workflow_run_id: str,
) -> str:
    if workflow_run_id:
        if event_type == "agent.task.todo.updated":
            return "workflow.run.task.todo.updated"
        if event_type == "agent.task.checkpoint.updated":
            return "workflow.run.task.checkpoint.updated"
        if event_type == "agent.replan.requested":
            return "workflow.run.replan.requested"
    if group_run_id:
        if event_type == "agent.task.todo.updated":
            return "group.run.task.todo.updated"
        if event_type == "agent.task.checkpoint.updated":
            return "group.run.task.checkpoint.updated"
        if event_type == "agent.replan.requested":
            return "group.run.replan.requested"
    return event_type


def _blocked_direct_event_title(event_type: str) -> str:
    if event_type.endswith(".task.todo.updated"):
        return "Runtime task blocked"
    if event_type.endswith(".task.checkpoint.updated"):
        return "Runtime checkpoint blocked"
    if event_type.endswith(".replan.requested"):
        return "Runtime replan requested"
    return "Runtime progress"


def _existing_blocked_direct_event_keys(events: list[PublicRunEvent]) -> set[str]:
    keys: set[str] = set()
    for event in events:
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        key = _text(
            payload.get("runtime_blocked_request_id")
            or metadata.get("runtime_blocked_request_id")
        )
        if key:
            keys.add(key)
    return keys


def _blocked_direct_event_key(request: Mapping[str, Any]) -> str:
    return _text(
        request.get("request_id")
        or _blocked_direct_step_id(request)
        or _blocked_direct_tool_name(request)
    )


def _blocked_direct_replan_request_id(request: Mapping[str, Any]) -> str:
    return "runtime-blocked:" + _blocked_direct_event_key(request)


def _blocked_direct_step_id(request: Mapping[str, Any]) -> str:
    todo = request.get("task_todo")
    todo_step_id = todo.get("step_id") if isinstance(todo, Mapping) else ""
    return _text(
        request.get("step_id")
        or request.get("planner_step_id")
        or request.get("source_step_id")
        or todo_step_id
    )


def _blocked_direct_tool_name(request: Mapping[str, Any]) -> str:
    todo = request.get("task_todo")
    todo_tool_name = todo.get("tool_name") if isinstance(todo, Mapping) else ""
    return _text(
        request.get("tool_name")
        or request.get("tool")
        or request.get("name")
        or todo_tool_name
    )


def _blocked_direct_request_status(request: Mapping[str, Any]) -> str:
    route = request.get("desktop_execution_route")
    route_status = route.get("status") if isinstance(route, Mapping) else ""
    return _text(request.get("blocked_by") or route_status or request.get("status"))


def _blocked_direct_request_detail(request: Mapping[str, Any]) -> str:
    route = request.get("desktop_execution_route")
    route_reason = route.get("reason") if isinstance(route, Mapping) else ""
    return _text(
        request.get("policy_reason")
        or route_reason
        or request.get("reason")
        or request.get("blocked_by")
        or request.get("status")
    )


def _blocked_direct_blocking_conditions(request: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in request.get("blocking_conditions") or []:
        clean = _text(item)
        if clean and clean not in values:
            values.append(clean)
    route = request.get("desktop_execution_route")
    if isinstance(route, Mapping):
        for item in route.get("blocking_conditions") or []:
            clean = _text(item)
            if clean and clean not in values:
                values.append(clean)
    return values


def _blocked_direct_runtime_metadata(request: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {
        "runtime_status": _blocked_direct_request_status(request),
        "runtime_event_type": "runtime.blocked_direct_request",
        "runtime_blocked": True,
        "runtime_blocked_request_id": _text(request.get("request_id")),
        "runtime_blocked_tool_name": _blocked_direct_tool_name(request),
        "runtime_blocked_reason": _blocked_direct_request_detail(request),
        "runtime_blocking_conditions": _blocked_direct_blocking_conditions(request),
    }
    return {key: value for key, value in metadata.items() if value not in ("", [], None)}


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
