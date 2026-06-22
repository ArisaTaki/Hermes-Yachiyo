"""ToolCall public snapshots derived from direct runtime payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import ToolCallSnapshot


def tool_call_snapshot_from_payload(
    payload: Mapping[str, Any] | ToolCallSnapshot,
    *,
    run_id: str = "",
) -> ToolCallSnapshot:
    if isinstance(payload, ToolCallSnapshot):
        return _redacted_tool_call_snapshot(payload)
    tool_name = _text(payload.get("tool_name") or payload.get("tool") or "tool")
    tool_call_id = _text(payload.get("tool_call_id") or payload.get("id"))
    if not tool_call_id:
        tool_call_id = f"{run_id or 'run'}:{tool_name}:{payload.get('sequence') or 0}"
    input_preview = _mapping(
        payload.get("input_preview")
        or payload.get("input")
        or payload.get("arguments")
        or payload.get("args")
    )
    output_preview = tool_output_preview(payload)
    status = tool_status_from_payload(payload, output_preview=output_preview)
    completed_at = _optional_text(payload.get("completed_at"))
    if not completed_at and tool_call_status_is_terminal(status):
        completed_at = _optional_text(payload.get("created_at") or payload.get("started_at"))
    return ToolCallSnapshot(
        tool_call_id=tool_call_id,
        run_id=_optional_text(payload.get("run_id") or run_id),
        source_run_id=_optional_text(
            payload.get("source_run_id") or input_preview.get("source_run_id")
        ),
        source_runnable_id=_optional_text(
            payload.get("source_runnable_id")
            or payload.get("source_agent_id")
            or payload.get("member_agent_id")
            or payload.get("agent_id")
            or input_preview.get("source_runnable_id")
            or input_preview.get("member_agent_id")
            or input_preview.get("agent_id")
        ),
        source_runnable_name=_optional_text(
            payload.get("source_runnable_name")
            or payload.get("source_agent_name")
            or payload.get("member_agent_name")
            or payload.get("agent_name")
            or input_preview.get("source_runnable_name")
            or input_preview.get("member_agent_name")
            or input_preview.get("agent_name")
        ),
        workflow_id=_optional_text(payload.get("workflow_id") or input_preview.get("workflow_id")),
        workflow_run_id=_optional_text(
            payload.get("workflow_run_id") or input_preview.get("workflow_run_id")
        ),
        workflow_node_id=_optional_text(
            payload.get("workflow_node_id") or input_preview.get("workflow_node_id")
        ),
        workflow_node_label=_optional_text(
            payload.get("workflow_node_label") or input_preview.get("workflow_node_label")
        ),
        group_id=_optional_text(payload.get("group_id") or input_preview.get("group_id")),
        group_run_id=_optional_text(
            payload.get("group_run_id")
            or payload.get("run_group_id")
            or input_preview.get("group_run_id")
            or input_preview.get("run_group_id")
        ),
        tool_name=tool_name,
        status=status,
        risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
        input_preview=input_preview,
        output_preview=output_preview,
        approval_id=_optional_text(payload.get("approval_id")),
        started_at=_text(payload.get("started_at") or payload.get("created_at")),
        completed_at=completed_at,
    )


def tool_call_status_is_terminal(status: str) -> bool:
    return status in {"completed", "failed", "denied", "skipped", "expired", "cancelled", "blocked"}


def tool_status_from_payload(
    payload: Mapping[str, Any],
    *,
    output_preview: Mapping[str, Any],
) -> str:
    explicit = _text(payload.get("status"))
    if explicit:
        return explicit
    if _foreground_lock_is_busy(payload) or _foreground_lock_is_busy(output_preview):
        return "blocked"
    return "completed"


def tool_output_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _mapping(
        payload.get("output_preview")
        or payload.get("output")
        or payload.get("result")
    )
    if explicit:
        return explicit
    error = payload.get("error")
    return _mapping({"error": error}) if error is not None else {}


def _foreground_lock_is_busy(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("foreground_lock_busy") is True


def _redacted_tool_call_snapshot(snapshot: ToolCallSnapshot) -> ToolCallSnapshot:
    return snapshot.model_copy(
        update={
            "tool_call_id": _text(snapshot.tool_call_id),
            "run_id": _optional_text(snapshot.run_id),
            "source_run_id": _optional_text(snapshot.source_run_id),
            "source_runnable_id": _optional_text(snapshot.source_runnable_id),
            "source_runnable_name": _optional_text(snapshot.source_runnable_name),
            "workflow_id": _optional_text(snapshot.workflow_id),
            "workflow_run_id": _optional_text(snapshot.workflow_run_id),
            "workflow_node_id": _optional_text(snapshot.workflow_node_id),
            "workflow_node_label": _optional_text(snapshot.workflow_node_label),
            "group_id": _optional_text(snapshot.group_id),
            "group_run_id": _optional_text(snapshot.group_run_id),
            "tool_name": _text(snapshot.tool_name),
            "status": _text(snapshot.status),
            "risk_level": _optional_text(snapshot.risk_level),
            "input_preview": _mapping(snapshot.input_preview),
            "output_preview": _mapping(snapshot.output_preview),
            "approval_id": _optional_text(snapshot.approval_id),
            "started_at": _text(snapshot.started_at),
            "completed_at": _optional_text(snapshot.completed_at),
        }
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


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
