"""Workflow public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import (
    redact_json_value,
    redact_run_event_payload,
    redact_secrets,
)

from .contracts import WorkflowSnapshot
from .workflow_run_snapshots import is_workflow_run_payload, workflow_run_snapshot_from_payload


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


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
