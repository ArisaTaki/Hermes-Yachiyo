"""WorkflowRun public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent, WorkflowRunSnapshot
from .run_snapshots import run_timeline_snapshot_from_payload


def workflow_run_snapshot_from_payload(
    payload: Mapping[str, Any] | WorkflowRunSnapshot,
) -> WorkflowRunSnapshot:
    if isinstance(payload, WorkflowRunSnapshot):
        return payload

    timeline = run_timeline_snapshot_from_payload(workflow_run_payload_with_lifecycle(payload))
    workflow_event_context = workflow_event_context_from_events(timeline.events)
    return WorkflowRunSnapshot(
        **timeline.model_dump(mode="python"),
        workflow_id=_optional_text(
            payload.get("workflow_id")
            or workflow_event_context.get("workflow_id")
            or payload.get("runnable_id")
        ),
        objective=_text(payload.get("objective") or payload.get("user_goal") or timeline.title),
        current_node_id=_optional_text(
            payload.get("current_node_id")
            or payload.get("workflow_node_id")
            or workflow_event_context.get("workflow_node_id")
        ),
        current_node_label=_optional_text(
            payload.get("current_node_label")
            or payload.get("workflow_node_label")
            or workflow_event_context.get("workflow_node_label")
        ),
        final_answer=_optional_text(payload.get("final_answer") or payload.get("result")),
    )


def is_workflow_run_payload(payload: Any) -> bool:
    if isinstance(payload, WorkflowRunSnapshot):
        return True
    if not isinstance(payload, Mapping):
        return False
    run_id = _text(payload.get("run_id"))
    workflow_run_id = _text(payload.get("workflow_run_id"))
    return (
        _text(payload.get("kind")) == "workflow_run"
        or bool(_text(payload.get("workflow_id")))
        or bool(workflow_run_id and workflow_run_id == run_id)
    )


def workflow_run_payload_with_lifecycle(payload: Mapping[str, Any]) -> dict[str, Any]:
    run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
    if not run_id:
        return dict(payload)

    lifecycle_context = _workflow_lifecycle_context(payload, run_id)
    raw_events = _workflow_stream_events(
        _raw_events_from_payload(
            payload,
            ("events", "run_events", "recent_events", "timeline"),
        ),
        lifecycle_context,
    )
    raw_events = _workflow_scoped_planner_events(raw_events)
    existing_types = {_event_type(event) for event in raw_events}
    events: list[dict[str, Any]] = []
    if not existing_types.intersection({"workflow.run.started", "workflow.started"}):
        events.append(
            _workflow_lifecycle_event(
                "workflow.run.started",
                payload,
                lifecycle_context,
                created_at=_text(payload.get("created_at")),
            )
        )
    events.extend(raw_events)

    terminal_event_type = _workflow_terminal_event_type(payload.get("status"))
    if (
        terminal_event_type
        and not existing_types.intersection(_workflow_terminal_event_aliases(terminal_event_type))
    ):
        events.append(
            _workflow_lifecycle_event(
                terminal_event_type,
                payload,
                {**lifecycle_context, "status": _text(payload.get("status"))},
                created_at=_text(payload.get("updated_at") or payload.get("created_at")),
            )
        )

    projected = dict(payload)
    projected["events"] = events
    return projected


def workflow_event_context_from_events(events: list[PublicRunEvent]) -> dict[str, str]:
    context: dict[str, str] = {}
    for event in events:
        workflow_id = _text(event.payload.get("workflow_id"))
        if workflow_id:
            context["workflow_id"] = workflow_id
        workflow_node_id = _text(event.payload.get("workflow_node_id"))
        if workflow_node_id:
            context["workflow_node_id"] = workflow_node_id
            context["workflow_node_label"] = _text(event.payload.get("workflow_node_label"))
    return context


def _raw_events_from_payload(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


_WORKFLOW_PLANNER_EVENT_TYPES = {
    "agent.intent.selected": "workflow.run.intent.selected",
    "agent.plan.created": "workflow.run.plan.created",
    "agent.task_core.created": "workflow.run.task_core.created",
    "agent.plan.step": "workflow.run.plan.step",
    "agent.plan.selection": "workflow.run.plan.selection",
    "agent.replan.requested": "workflow.run.replan.requested",
    "agent.replan.recovery.updated": "workflow.run.replan.recovery.updated",
    "agent.desktop.intent_planned": "workflow.run.desktop.intent_planned",
    "agent.tool.approval_required": "workflow.run.tool.approval_required",
    "agent.desktop.intent_approval_required": "workflow.run.desktop.intent_approval_required",
    "agent.desktop.intent_completed": "workflow.run.desktop.intent_completed",
    "agent.desktop.intent_unavailable": "workflow.run.desktop.intent_unavailable",
    "agent.desktop.permission_recovery": "workflow.run.desktop.permission_recovery",
    "agent.desktop.readiness_recovered": "workflow.run.desktop.readiness_recovered",
    "agent.task.workspace_item.updated": "workflow.run.task.workspace_item.updated",
    "agent.task.todo.updated": "workflow.run.task.todo.updated",
    "agent.task.checkpoint.updated": "workflow.run.task.checkpoint.updated",
}


def _workflow_scoped_planner_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoped_events: list[dict[str, Any]] = []
    for event in events:
        event_type = _event_type(event)
        workflow_type = _WORKFLOW_PLANNER_EVENT_TYPES.get(event_type)
        if not workflow_type:
            scoped_events.append(event)
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        scoped_events.append(
            {
                **event,
                "event_type": workflow_type,
                "payload": {
                    **dict(payload),
                    "planner_event_type": str(
                        payload.get("planner_event_type") or event_type
                    ),
                    "planner_scope": str(payload.get("planner_scope") or "workflow_run"),
                },
            }
        )
    return scoped_events


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("event"))


def _workflow_lifecycle_context(payload: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "workflow_id": _text(payload.get("workflow_id") or payload.get("runnable_id")),
        "workflow_run_id": _text(payload.get("workflow_run_id") or run_id),
        "objective": _text(payload.get("objective") or payload.get("user_goal")),
        "status": _text(payload.get("status") or "unknown"),
        "workflow_node_id": _text(payload.get("current_node_id") or payload.get("workflow_node_id")),
        "workflow_node_label": _text(
            payload.get("current_node_label") or payload.get("workflow_node_label")
        ),
    }


def _workflow_lifecycle_event(
    event_type: str,
    payload: Mapping[str, Any],
    lifecycle_context: dict[str, Any],
    *,
    created_at: str = "",
) -> dict[str, Any]:
    label = _text(
        payload.get("title")
        or payload.get("objective")
        or payload.get("user_goal")
        or "Workflow run"
    )
    event = {
        "event_type": event_type,
        "detail": label,
        "payload": {
            key: value
            for key, value in lifecycle_context.items()
            if value or key in {"status"}
        },
    }
    if created_at:
        event["created_at"] = created_at
    return event


def _workflow_stream_events(
    events: list[dict[str, Any]],
    lifecycle_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        _workflow_stream_event(event, lifecycle_context)
        for event in events
    ]


def _workflow_stream_event(
    event: dict[str, Any],
    lifecycle_context: Mapping[str, Any],
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    for key in (
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        value = lifecycle_context.get(key)
        if value:
            payload.setdefault(key, value)
    if payload:
        item["payload"] = payload
    return item


def _workflow_terminal_event_type(value: Any) -> str:
    status = _text(value)
    if status in {"completed", "success", "succeeded", "done"}:
        return "workflow.run.completed"
    if status in {"failed", "error"}:
        return "workflow.run.failed"
    if status in {"cancelled", "canceled"}:
        return "workflow.run.cancelled"
    return ""


def _workflow_terminal_event_aliases(event_type: str) -> set[str]:
    aliases = {
        "workflow.run.completed": {"workflow.run.completed", "workflow.completed"},
        "workflow.run.failed": {"workflow.run.failed", "workflow.failed"},
        "workflow.run.cancelled": {"workflow.run.cancelled", "workflow.cancelled"},
    }
    return aliases.get(event_type, {event_type})


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
