"""Task progress event projections for the shared Yachiyo runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from apps.shell.agent.runtime.task_progress import (
    append_task_progress_events_for_tool_result as _append_task_progress_events,
)

from .contracts import PublicRunEvent
from .events import public_run_event_from_payload

ProgressEventScope = Literal["agent", "group.run", "workflow.run"]

_SCOPED_PROGRESS_EVENT_TYPES: dict[ProgressEventScope, dict[str, str]] = {
    "agent": {},
    "group.run": {
        "agent.task.workspace_item.updated": "group.run.task.workspace_item.updated",
        "agent.task.todo.updated": "group.run.task.todo.updated",
        "agent.task.checkpoint.updated": "group.run.task.checkpoint.updated",
        "agent.replan.recovery.updated": "group.run.replan.recovery.updated",
    },
    "workflow.run": {
        "agent.task.workspace_item.updated": "workflow.run.task.workspace_item.updated",
        "agent.task.todo.updated": "workflow.run.task.todo.updated",
        "agent.task.checkpoint.updated": "workflow.run.task.checkpoint.updated",
        "agent.replan.recovery.updated": "workflow.run.replan.recovery.updated",
    },
}


def task_progress_event_payloads_for_tool_result(
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    event_scope: ProgressEventScope = "agent",
    existing_timeline: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return task workspace/todo/checkpoint progress events for a tool result."""
    timeline = [dict(item) for item in existing_timeline or []]
    start_index = len(timeline)
    _append_task_progress_events(
        tool_request=tool_request,
        tool_event=tool_event,
        timeline=timeline,
        timeline_factory=_timeline_event,
    )
    return [
        _scoped_progress_event(event, event_scope)
        for event in timeline[start_index:]
    ]


def public_task_progress_events_for_tool_result(
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    event_scope: ProgressEventScope = "agent",
    run_id: str = "",
    after_sequence: int = 0,
    existing_timeline: list[Mapping[str, Any]] | None = None,
) -> list[PublicRunEvent]:
    """Return redacted PublicRunEvent task progress updates for Chat and Studio."""
    payloads = task_progress_event_payloads_for_tool_result(
        tool_request=tool_request,
        tool_event=tool_event,
        event_scope=event_scope,
        existing_timeline=existing_timeline,
    )
    return [
        public_run_event_from_payload(
            payload,
            run_id=run_id,
            sequence=after_sequence + index,
        )
        for index, payload in enumerate(payloads, start=1)
    ]


def _timeline_event(event_type: str, detail: str = "", **payload: Any) -> dict[str, Any]:
    return {"event": event_type, "detail": detail, **payload}


def _scoped_progress_event(
    event: Mapping[str, Any],
    event_scope: ProgressEventScope,
) -> dict[str, Any]:
    scoped = dict(event)
    event_type = str(scoped.get("event_type") or scoped.get("event") or "").strip()
    scoped_type = _SCOPED_PROGRESS_EVENT_TYPES.get(event_scope, {}).get(event_type)
    if not scoped_type:
        return scoped
    if "event_type" in scoped:
        scoped["event_type"] = scoped_type
    else:
        scoped["event"] = scoped_type
    scoped.setdefault("planner_event_type", event_type)
    return scoped
