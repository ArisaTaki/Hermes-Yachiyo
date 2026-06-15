"""Workflow public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import WorkflowSnapshot


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
