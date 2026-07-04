"""Shared event scoping helpers for runtime planner timelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_RUNTIME_SCOPE_KEYS = (
    "task_id",
    "run_group_id",
    "group_run_id",
    "group_id",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
)

_RUNTIME_PROGRESS_GROUP_EVENT_TYPES = {
    "agent.task.workspace_item.updated": "group.run.task.workspace_item.updated",
    "agent.task.todo.updated": "group.run.task.todo.updated",
    "agent.task.checkpoint.updated": "group.run.task.checkpoint.updated",
    "agent.replan.recovery.updated": "group.run.replan.recovery.updated",
}

_RUNTIME_PROGRESS_WORKFLOW_EVENT_TYPES = {
    "agent.task.workspace_item.updated": "workflow.run.task.workspace_item.updated",
    "agent.task.todo.updated": "workflow.run.task.todo.updated",
    "agent.task.checkpoint.updated": "workflow.run.task.checkpoint.updated",
    "agent.replan.recovery.updated": "workflow.run.replan.recovery.updated",
}

_RUNTIME_PROGRESS_BASE_EVENT_TYPES = {
    **{value: key for key, value in _RUNTIME_PROGRESS_GROUP_EVENT_TYPES.items()},
    **{value: key for key, value in _RUNTIME_PROGRESS_WORKFLOW_EVENT_TYPES.items()},
    "workflow.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "workflow.task.todo.updated": "agent.task.todo.updated",
    "workflow.task.checkpoint.updated": "agent.task.checkpoint.updated",
    "workflow.replan.recovery.updated": "agent.replan.recovery.updated",
}

_RUNTIME_PLANNER_GROUP_EVENT_TYPES = {
    "agent.intent.selected": "group.run.intent.selected",
    "agent.plan.created": "group.run.plan.created",
    "agent.plan.step": "group.run.plan.step",
    "agent.task_core.created": "group.run.task_core.created",
    "agent.plan.selection": "group.run.plan.selection",
}

_RUNTIME_PLANNER_WORKFLOW_EVENT_TYPES = {
    "agent.intent.selected": "workflow.run.intent.selected",
    "agent.plan.created": "workflow.run.plan.created",
    "agent.plan.step": "workflow.run.plan.step",
    "agent.task_core.created": "workflow.run.task_core.created",
    "agent.plan.selection": "workflow.run.plan.selection",
}

_RUNTIME_PLANNER_BASE_EVENT_TYPES = {
    **{value: key for key, value in _RUNTIME_PLANNER_GROUP_EVENT_TYPES.items()},
    **{value: key for key, value in _RUNTIME_PLANNER_WORKFLOW_EVENT_TYPES.items()},
    "workflow.intent.selected": "agent.intent.selected",
    "workflow.plan.created": "agent.plan.created",
    "workflow.plan.step": "agent.plan.step",
    "workflow.task_core.created": "agent.task_core.created",
    "workflow.plan.selection": "agent.plan.selection",
}


def runtime_event_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = value.get("payload") if isinstance(value.get("payload"), Mapping) else {}
    return {**dict(value), **dict(payload)}


def runtime_scope_context(
    *sources: Any,
    timeline: list[dict[str, Any]] | None = None,
    include_input: bool = True,
) -> dict[str, str]:
    for source in sources:
        context = runtime_scope_context_from_source(source, include_input=include_input)
        if context:
            return context
    for event in reversed(timeline or []):
        if not isinstance(event, Mapping):
            continue
        context = runtime_scope_context_from_mapping(event, include_input=include_input)
        if context:
            return context
    return {}


def runtime_scope_context_from_source(
    source: Any,
    *,
    include_input: bool = True,
) -> dict[str, str]:
    if isinstance(source, Mapping):
        return runtime_scope_context_from_mapping(source, include_input=include_input)
    if isinstance(source, Iterable) and not isinstance(source, (str, bytes)):
        for item in source:
            context = runtime_scope_context_from_source(item, include_input=include_input)
            if context:
                return context
    return {}


def runtime_scope_context_from_mapping(
    source: Mapping[str, Any],
    *,
    include_input: bool = True,
) -> dict[str, str]:
    payload = runtime_event_payload(source)
    input_payload = payload.get("input") if isinstance(payload.get("input"), Mapping) else {}
    context: dict[str, str] = {}
    for key in _RUNTIME_SCOPE_KEYS:
        raw_value = payload.get(key)
        if include_input and raw_value in (None, ""):
            raw_value = input_payload.get(key)
        clean_value = str(raw_value or "").strip()
        if clean_value:
            context[key] = clean_value
    return context


def runtime_progress_event_type(event_type: str, payload: Mapping[str, Any]) -> str:
    return _scoped_runtime_event_type(
        event_type,
        payload,
        group_event_types=_RUNTIME_PROGRESS_GROUP_EVENT_TYPES,
        workflow_event_types=_RUNTIME_PROGRESS_WORKFLOW_EVENT_TYPES,
        include_input=False,
    )


def runtime_progress_event_payload(
    payload: Mapping[str, Any],
    base_event_type: str,
    scoped_event_type: str,
) -> dict[str, Any]:
    return _scoped_runtime_event_payload(payload, base_event_type, scoped_event_type)


def runtime_progress_base_event_type(event_type: str) -> str:
    clean_event_type = str(event_type or "").strip()
    return _RUNTIME_PROGRESS_BASE_EVENT_TYPES.get(clean_event_type, clean_event_type)


def runtime_planner_timeline_event(
    event: Mapping[str, Any],
    scope_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    event_type = str(event.get("event") or event.get("event_type") or "").strip()
    scoped_event_type = runtime_planner_event_type(event_type, scope_context)
    event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    scoped_payload = runtime_planner_event_payload(
        event_payload,
        event_type,
        scoped_event_type,
        scope_context,
    )
    result = dict(event)
    result["event"] = scoped_event_type
    result.update({key: value for key, value in dict(scope_context or {}).items() if value})
    result["payload"] = scoped_payload
    return result


def runtime_planner_event_type(
    event_type: str,
    scope_context: Mapping[str, Any] | None,
) -> str:
    return _scoped_runtime_event_type(
        event_type,
        scope_context or {},
        group_event_types=_RUNTIME_PLANNER_GROUP_EVENT_TYPES,
        workflow_event_types=_RUNTIME_PLANNER_WORKFLOW_EVENT_TYPES,
    )


def runtime_planner_event_payload(
    payload: Mapping[str, Any],
    base_event_type: str,
    scoped_event_type: str,
    scope_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return _scoped_runtime_event_payload(
        payload,
        base_event_type,
        scoped_event_type,
        scope_context=scope_context,
    )


def runtime_planner_base_event_type(event_type: str) -> str:
    clean_event_type = str(event_type or "").strip()
    return _RUNTIME_PLANNER_BASE_EVENT_TYPES.get(clean_event_type, clean_event_type)


def runtime_replan_request_event_type(payload: Mapping[str, Any]) -> str:
    context = runtime_scope_context_from_mapping(payload, include_input=False)
    if str(context.get("workflow_run_id") or "").strip():
        return "workflow.run.replan.requested"
    if str(context.get("group_run_id") or context.get("run_group_id") or "").strip():
        return "group.run.replan.requested"
    return "agent.replan.requested"


def runtime_replan_request_event_payload(
    payload: Mapping[str, Any],
    event_type: str,
) -> dict[str, Any]:
    return _scoped_runtime_event_payload(
        payload,
        "agent.replan.requested",
        event_type,
    )


def runtime_replan_base_event_type(event_type: str) -> str:
    clean_event_type = str(event_type or "").strip()
    if clean_event_type in {
        "group.run.replan.requested",
        "workflow.replan.requested",
        "workflow.run.replan.requested",
    }:
        return "agent.replan.requested"
    return clean_event_type


def runtime_event_scope(event_type: str) -> str:
    clean_event_type = str(event_type or "").strip()
    if clean_event_type.startswith("workflow.run."):
        return "workflow.run"
    if clean_event_type.startswith("group.run."):
        return "group.run"
    return "agent"


def _scoped_runtime_event_type(
    event_type: str,
    scope_context: Mapping[str, Any],
    *,
    group_event_types: Mapping[str, str],
    workflow_event_types: Mapping[str, str],
    include_input: bool = True,
) -> str:
    clean_event_type = str(event_type or "").strip()
    context = runtime_scope_context_from_mapping(scope_context, include_input=include_input)
    if str(context.get("workflow_run_id") or "").strip():
        return workflow_event_types.get(clean_event_type, clean_event_type)
    if str(context.get("group_run_id") or context.get("run_group_id") or "").strip():
        return group_event_types.get(clean_event_type, clean_event_type)
    return clean_event_type


def _scoped_runtime_event_payload(
    payload: Mapping[str, Any],
    base_event_type: str,
    scoped_event_type: str,
    *,
    scope_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event_payload = {**dict(scope_context or {}), **dict(payload)}
    if scoped_event_type == base_event_type:
        return event_payload
    event_payload.setdefault("planner_event_type", base_event_type)
    event_payload.setdefault("planner_scope", runtime_event_scope(scoped_event_type))
    return event_payload
