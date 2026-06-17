"""Workflow public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import (
    redact_json_value,
    redact_run_event_payload,
    redact_secrets,
)

from .contracts import PublicRunEvent, WorkflowRunSnapshot, WorkflowSnapshot
from .run_snapshots import run_timeline_snapshot_from_payload


def workflow_snapshot_from_payload(
    payload: Mapping[str, Any] | WorkflowSnapshot,
) -> WorkflowSnapshot:
    if isinstance(payload, WorkflowSnapshot):
        return payload
    return WorkflowSnapshot(
        workflow_id=_text(payload.get("workflow_id")),
        name=_text(payload.get("name") or "Workflow"),
        description=_optional_text(payload.get("description")),
        nodes=_list_of_mappings(payload.get("nodes")),
        edges=_list_of_mappings(payload.get("edges")),
        default_input_schema=_schema_mapping(payload.get("default_input_schema")),
        enabled=bool(payload.get("enabled", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def workflow_run_snapshot_from_payload(
    payload: Mapping[str, Any] | WorkflowRunSnapshot,
) -> WorkflowRunSnapshot:
    if isinstance(payload, WorkflowRunSnapshot):
        return payload

    timeline = run_timeline_snapshot_from_payload(_workflow_run_payload_with_lifecycle(payload))
    workflow_event_context = _workflow_event_context(timeline.events)
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


def _workflow_run_payload_with_lifecycle(payload: Mapping[str, Any]) -> dict[str, Any]:
    run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
    if not run_id:
        return dict(payload)

    raw_events = _raw_events_from_payload(
        payload,
        ("events", "run_events", "recent_events", "timeline"),
    )
    existing_types = {_event_type(event) for event in raw_events}
    lifecycle_context = _workflow_lifecycle_context(payload, run_id)
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


def _raw_events_from_payload(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


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


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    result = dict(redacted) if isinstance(redacted, Mapping) else {}
    return _restore_configured_flags(value, result)


def _restore_configured_flags(source: Any, target: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        return dict(target) if isinstance(target, Mapping) else {}
    result = dict(target)
    for key, item in source.items():
        key_text = _text(key)
        target_item = result.get(key_text)
        if key_text.endswith("_configured") and isinstance(item, bool):
            result[key_text] = item
        elif isinstance(item, Mapping) and isinstance(target_item, Mapping):
            result[key_text] = _restore_configured_flags(item, target_item)
        elif isinstance(item, list) and isinstance(target_item, list):
            result[key_text] = [
                _restore_configured_flags(source_item, redacted_item)
                if isinstance(source_item, Mapping) and isinstance(redacted_item, Mapping)
                else redacted_item
                for source_item, redacted_item in zip(item, target_item, strict=False)
            ]
    return result


def _schema_mapping(value: Any) -> dict[str, Any]:
    redacted = redact_json_value(dict(value)) if isinstance(value, Mapping) else {}
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _workflow_event_context(events: list[PublicRunEvent]) -> dict[str, str]:
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


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
