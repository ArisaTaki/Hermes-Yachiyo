"""Task progress event projections for the shared Yachiyo runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from apps.shell.agent.runtime.task_progress import (
    append_task_progress_events_for_tool_result as _append_task_progress_events,
)

from .contracts import PlannerDecisionSnapshot, PublicRunEvent
from .events import public_run_event_from_payload
from .replans import (
    task_replan_request_from_failure,
    task_replan_run_event_payload,
)

ProgressEventScope = Literal["agent", "group.run", "workflow.run"]

_SCOPED_PROGRESS_EVENT_TYPES: dict[ProgressEventScope, dict[str, str]] = {
    "agent": {},
    "group.run": {
        "agent.replan.requested": "group.run.replan.requested",
        "agent.task.workspace_item.updated": "group.run.task.workspace_item.updated",
        "agent.task.todo.updated": "group.run.task.todo.updated",
        "agent.task.checkpoint.updated": "group.run.task.checkpoint.updated",
        "agent.replan.recovery.updated": "group.run.replan.recovery.updated",
    },
    "workflow.run": {
        "agent.replan.requested": "workflow.run.replan.requested",
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


def public_runtime_tool_result_events(
    decision: PlannerDecisionSnapshot,
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    event_scope: ProgressEventScope = "agent",
    run_id: str = "",
    task_id: str = "",
    after_sequence: int = 0,
    existing_timeline: list[Mapping[str, Any]] | None = None,
) -> list[PublicRunEvent]:
    """Return shared task progress and replan events for a completed tool step."""
    progress_events = public_task_progress_events_for_tool_result(
        tool_request=tool_request,
        tool_event=tool_event,
        event_scope=event_scope,
        run_id=run_id,
        after_sequence=after_sequence,
        existing_timeline=existing_timeline,
    )
    replan_events = public_task_replan_events_for_tool_result(
        decision,
        tool_request=tool_request,
        tool_event=tool_event,
        event_scope=event_scope,
        run_id=run_id,
        task_id=task_id,
        after_sequence=after_sequence + len(progress_events),
    )
    return [*progress_events, *replan_events]


def task_replan_event_payloads_for_tool_result(
    decision: PlannerDecisionSnapshot,
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    event_scope: ProgressEventScope = "agent",
    run_id: str = "",
    task_id: str = "",
) -> list[dict[str, Any]]:
    """Return a replayable replan request event for a failed tool result."""
    if not _tool_event_requests_replan(tool_event):
        return []
    failure = _failure_payload_from_tool_result(tool_request, tool_event)
    request = task_replan_request_from_failure(
        decision,
        failure,
        trigger=_failure_trigger(failure),
        run_id=run_id or _text(tool_request.get("run_id")),
        task_id=task_id or _text(tool_request.get("task_id")),
        source_step_id=_text(
            tool_request.get("step_id")
            or tool_request.get("planner_step_id")
            or failure.get("step_id")
        ),
        tool_name=_text(
            tool_request.get("tool")
            or tool_request.get("tool_name")
            or failure.get("tool_name")
            or failure.get("tool")
        ),
    )
    if request is None:
        return []
    event_type, payload = task_replan_run_event_payload(request)
    return [
        _scoped_progress_event(
            {
                "event": event_type,
                "detail": payload.get("reason")
                or payload.get("failure_detail")
                or payload.get("trigger")
                or "replan requested",
                "status": payload.get("status") or "requested",
                "source": payload.get("source") or "runtime_planner",
                "decision_id": payload.get("decision_id") or "",
                "plan_id": payload.get("plan_id") or "",
                "payload": payload,
            },
            event_scope,
        )
    ]


def public_task_replan_events_for_tool_result(
    decision: PlannerDecisionSnapshot,
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    event_scope: ProgressEventScope = "agent",
    run_id: str = "",
    task_id: str = "",
    after_sequence: int = 0,
) -> list[PublicRunEvent]:
    """Return redacted PublicRunEvent replan request updates for Chat and Studio."""
    payloads = task_replan_event_payloads_for_tool_result(
        decision,
        tool_request=tool_request,
        tool_event=tool_event,
        event_scope=event_scope,
        run_id=run_id,
        task_id=task_id,
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
    scoped.setdefault("planner_scope", event_scope)
    payload = scoped.get("payload")
    if isinstance(payload, Mapping):
        scoped["payload"] = {
            **dict(payload),
            "planner_event_type": str(payload.get("planner_event_type") or event_type),
            "planner_scope": str(payload.get("planner_scope") or event_scope),
        }
    return scoped


def _tool_event_requests_replan(tool_event: Mapping[str, Any]) -> bool:
    result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
    if result.get("approval_required") or tool_event.get("approval_required"):
        return False
    if result.get("verification_failed") is True or tool_event.get("verification_failed") is True:
        return True
    if result.get("ok") is False:
        return True
    status = _text(tool_event.get("status") or result.get("status")).lower()
    if status in {"failed", "failure", "error", "unavailable", "rejected", "cancelled"}:
        return True
    event_type = _text(tool_event.get("event") or tool_event.get("event_type")).lower()
    return event_type.endswith(".failed") or event_type.endswith("_failed")


def _failure_payload_from_tool_result(
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
) -> dict[str, Any]:
    result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
    return {
        **dict(tool_event),
        "event_type": _text(tool_event.get("event_type") or tool_event.get("event")),
        "step_id": _text(tool_request.get("step_id") or tool_request.get("planner_step_id")),
        "tool_name": _text(tool_request.get("tool") or tool_request.get("tool_name")),
        "result": dict(result),
    }


def _failure_trigger(failure: Mapping[str, Any]) -> str:
    status = _text(failure.get("status") or failure.get("event_type")).lower()
    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    if result.get("verification_failed") is True or failure.get("verification_failed") is True:
        return "verification_failed"
    detail = " ".join(
        item
        for item in (
            _text(failure.get("detail")).lower(),
            _text(failure.get("error")).lower(),
            _text(result.get("error")).lower(),
            _text(result.get("hint")).lower(),
        )
        if item
    )
    if "unavailable" in status or "missing" in detail or "unavailable" in detail:
        return "tool_unavailable"
    if "verify" in status or "verification" in status or "verify" in detail:
        return "verification_failed"
    return "tool_failure"


def _text(value: Any) -> str:
    return str(value or "").strip()
