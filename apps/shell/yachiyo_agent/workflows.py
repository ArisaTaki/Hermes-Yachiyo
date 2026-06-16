"""Workflow public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
        default_input_schema=_mapping(payload.get("default_input_schema")),
        enabled=bool(payload.get("enabled", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def workflow_run_snapshot_from_payload(
    payload: Mapping[str, Any] | WorkflowRunSnapshot,
) -> WorkflowRunSnapshot:
    if isinstance(payload, WorkflowRunSnapshot):
        return payload

    timeline = run_timeline_snapshot_from_payload(payload)
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


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
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
