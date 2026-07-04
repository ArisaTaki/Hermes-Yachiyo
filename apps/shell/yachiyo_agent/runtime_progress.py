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

ProgressEventScope = Literal["agent", "group.run", "workflow.run", "auto"]

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
    effective_scope = _effective_progress_event_scope(event_scope, tool_request)
    timeline = [dict(item) for item in existing_timeline or []]
    start_index = len(timeline)
    _append_task_progress_events(
        tool_request=tool_request,
        tool_event=tool_event,
        timeline=timeline,
        timeline_factory=_timeline_event,
    )
    return [
        _scoped_progress_event(event, effective_scope)
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
    effective_scope = _effective_progress_event_scope(event_scope, tool_request)
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
        metadata=_replan_failure_metadata(tool_request, failure),
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
            effective_scope,
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


def _effective_progress_event_scope(
    event_scope: ProgressEventScope,
    tool_request: Mapping[str, Any],
) -> Literal["agent", "group.run", "workflow.run"]:
    if event_scope != "auto":
        return event_scope
    if _text(tool_request.get("workflow_run_id")):
        return "workflow.run"
    if _text(tool_request.get("group_run_id") or tool_request.get("run_group_id")):
        return "group.run"
    return "agent"


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
    request_input = tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    failure = {
        **dict(tool_event),
        "event_type": _text(tool_event.get("event_type") or tool_event.get("event")),
        "step_id": _text(tool_request.get("step_id") or tool_request.get("planner_step_id")),
        "tool_name": _text(tool_request.get("tool") or tool_request.get("tool_name")),
        "tool_input": dict(request_input),
        "result": dict(result),
    }
    for key in (
        "replan_request_id",
        "replan_recovery_action_id",
        "action_id",
        "replan_trigger",
        "source_step_id",
        "source_tool_name",
        "target_capability_id",
        "capability_id",
    ):
        value = tool_request.get(key)
        if value not in (None, "", [], {}):
            failure[key] = value
    for key in (
        "desktop_loop",
        "action_target",
        "observation_evidence",
        "observation_retry",
    ):
        value = _mapping(tool_request.get(key))
        if value:
            failure[key] = value
    for key in ("replan_triggers", "replan_signal_ids"):
        values = _string_list(tool_request.get(key))
        if values:
            failure[key] = values
    return failure


def _replan_failure_metadata(
    tool_request: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    replan_signal_ids = _string_list(tool_request.get("replan_signal_ids"))
    if replan_signal_ids:
        metadata["replan_signal_ids"] = replan_signal_ids
    replan_triggers = _string_list(tool_request.get("replan_triggers"))
    if replan_triggers:
        metadata["replan_triggers"] = replan_triggers
    desktop_loop = _mapping(tool_request.get("desktop_loop") or failure.get("desktop_loop"))
    if desktop_loop:
        metadata["desktop_loop"] = desktop_loop
    parent_replan_request_id = _text(tool_request.get("replan_request_id"))
    if not parent_replan_request_id:
        return metadata

    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    request_input = tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    action_id = _text(
        tool_request.get("replan_recovery_action_id") or tool_request.get("action_id")
    )
    metadata.update(
        {
            "replan_recovery_failed": True,
            "parent_replan_request_id": parent_replan_request_id,
            "failed_recovery_tool": _text(
                tool_request.get("tool") or tool_request.get("tool_name")
            ),
            "failed_recovery_input": dict(request_input),
        }
    )
    for key, value in (
        ("parent_replan_trigger", tool_request.get("replan_trigger")),
        ("failed_recovery_action_id", action_id),
        ("failed_recovery_action_label", tool_request.get("recovery_action_label")),
        (
            "failed_recovery_step_id",
            tool_request.get("step_id") or tool_request.get("planner_step_id"),
        ),
        ("failed_recovery_source", tool_request.get("source")),
        (
            "failed_recovery_target_capability_id",
            tool_request.get("target_capability_id") or tool_request.get("capability_id"),
        ),
        ("original_source_step_id", tool_request.get("source_step_id")),
        ("original_source_tool_name", tool_request.get("source_tool_name")),
    ):
        clean = _text(value)
        if clean:
            metadata[key] = clean
    verification_targets = _mapping_list(
        tool_request.get("verification_targets")
        or tool_request.get("task_verification_targets")
    )
    if verification_targets:
        metadata["failed_recovery_verification_targets"] = verification_targets
    result_preview = _failure_result_preview(result)
    if result_preview:
        metadata["failed_recovery_result_preview"] = result_preview
    return {key: value for key, value in metadata.items() if value not in ("", [], {})}


def _failure_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "status",
        "error",
        "hint",
        "summary",
        "returncode",
        "exit_code",
        "verification_failed",
    ):
        if key in result:
            preview[key] = result.get(key)
    return preview


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
