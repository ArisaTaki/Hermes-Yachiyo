"""ToolCall public snapshots derived from payloads and replayable RunEvents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import PublicRunEvent, ToolCallSnapshot


def tool_call_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
    events: list[PublicRunEvent] | None = None,
) -> list[ToolCallSnapshot]:
    if isinstance(payloads, list):
        return [tool_call_snapshot_from_payload(item, run_id=run_id) for item in payloads]
    return tool_call_snapshots_from_events(events or [])


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
    status = _text(payload.get("status") or "completed")
    completed_at = _optional_text(payload.get("completed_at"))
    if not completed_at and _tool_call_status_is_terminal(status):
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
        output_preview=_tool_output_preview(payload),
        approval_id=_optional_text(payload.get("approval_id")),
        started_at=_text(payload.get("started_at") or payload.get("created_at")),
        completed_at=completed_at,
    )


def tool_call_snapshots_from_events(events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
    calls: list[ToolCallSnapshot] = []
    active_by_key: dict[str, int] = {}
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        if not _is_tool_event(event.event_type):
            continue
        payload = _tool_call_payload_from_event(event)
        call = tool_call_snapshot_from_payload(payload, run_id=event.run_id)
        key = _tool_call_correlation_key(payload, call)
        active_index = active_by_key.get(key) if key else None
        if active_index is None:
            active_index = len(calls)
            calls.append(call)
        else:
            calls[active_index] = _merge_tool_call_snapshots(calls[active_index], call)
        if key:
            if _tool_call_status_is_terminal(call.status):
                active_by_key.pop(key, None)
            else:
                active_by_key[key] = active_index
    return calls


def _tool_call_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    approval = _nested_mapping(payload, "pending_approval") or _nested_mapping(payload, "approval")
    approval_id = (
        _text(payload.get("approval_id"))
        or _text(approval.get("approval_id"))
        or _text(approval.get("id"))
    )
    risk_level = (
        _text(payload.get("risk_level"))
        or _text(payload.get("risk"))
        or _text(approval.get("risk_level"))
        or _text(approval.get("risk"))
    )
    policy_reason = (
        _text(payload.get("policy_reason"))
        or _text(approval.get("policy_reason"))
        or _text(approval.get("reason"))
    )
    normalized = {
        **payload,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "tool_name": _tool_name_from_event(event),
        "status": payload.get("status") or _tool_status_from_event_type(event.event_type),
        "created_at": event.created_at,
    }
    if approval_id:
        normalized.setdefault("approval_id", approval_id)
    if risk_level:
        normalized.setdefault("risk_level", risk_level)
    _merge_tool_trace_context(normalized, payload)
    _merge_tool_trace_into_input_preview(
        normalized,
        {
            "approval_id": approval_id,
            "risk_level": risk_level,
            "policy_reason": policy_reason,
            "group_id": payload.get("group_id"),
            "group_run_id": payload.get("group_run_id") or payload.get("run_group_id"),
            "member_agent_id": payload.get("member_agent_id"),
            "member_agent_name": payload.get("member_agent_name"),
            "workflow_id": payload.get("workflow_id"),
            "workflow_run_id": payload.get("workflow_run_id"),
            "workflow_node_id": payload.get("workflow_node_id"),
            "workflow_node_label": payload.get("workflow_node_label"),
        },
    )
    return normalized


def _merge_tool_trace_context(source: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in (
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
    ):
        if payload.get(key):
            source.setdefault(key, payload.get(key))
    if payload.get("run_group_id"):
        source.setdefault("group_run_id", payload.get("run_group_id"))
    if payload.get("member_agent_id"):
        source.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        source.setdefault("source_runnable_name", payload.get("member_agent_name"))
    if payload.get("agent_id"):
        source.setdefault("source_runnable_id", payload.get("agent_id"))
    if payload.get("agent_name"):
        source.setdefault("source_runnable_name", payload.get("agent_name"))


def _merge_tool_trace_into_input_preview(
    source: dict[str, Any],
    context: dict[str, Any],
) -> None:
    clean_context = {key: value for key, value in context.items() if value}
    if not clean_context:
        return
    input_preview = (
        source.get("input_preview")
        or source.get("input")
        or source.get("arguments")
        or source.get("args")
    )
    preview = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    for key, value in clean_context.items():
        preview.setdefault(key, value)
    source["input_preview"] = preview


def _merge_tool_call_snapshots(
    current: ToolCallSnapshot,
    next_call: ToolCallSnapshot,
) -> ToolCallSnapshot:
    output_preview = dict(current.output_preview)
    output_preview.update(next_call.output_preview)
    completed_at = next_call.completed_at or current.completed_at
    if _tool_call_status_is_terminal(next_call.status) and not completed_at:
        completed_at = next_call.started_at or current.completed_at
    return ToolCallSnapshot(
        tool_call_id=current.tool_call_id or next_call.tool_call_id,
        run_id=current.run_id or next_call.run_id,
        source_run_id=current.source_run_id or next_call.source_run_id,
        source_runnable_id=current.source_runnable_id or next_call.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_call.source_runnable_name,
        workflow_id=current.workflow_id or next_call.workflow_id,
        workflow_run_id=current.workflow_run_id or next_call.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_call.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_call.workflow_node_label,
        group_id=current.group_id or next_call.group_id,
        group_run_id=current.group_run_id or next_call.group_run_id,
        tool_name=current.tool_name or next_call.tool_name,
        status=next_call.status or current.status,
        risk_level=current.risk_level or next_call.risk_level,
        input_preview={**current.input_preview, **next_call.input_preview},
        output_preview=output_preview,
        approval_id=current.approval_id or next_call.approval_id,
        started_at=current.started_at or next_call.started_at,
        completed_at=completed_at,
    )


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


def _tool_call_correlation_key(
    payload: Mapping[str, Any],
    call: ToolCallSnapshot,
) -> str:
    explicit_id = _text(payload.get("tool_call_id") or payload.get("id"))
    run_id = call.run_id or _text(payload.get("run_id"))
    if explicit_id:
        return f"{run_id}:id:{explicit_id}"
    preview = _tool_call_correlation_preview(call.input_preview)
    return f"{run_id}:tool:{call.tool_name}:{_stable_json(preview)}"


def _tool_call_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "agent_id",
        "agent_name",
        "approval_id",
        "group_id",
        "group_run_id",
        "member_agent_id",
        "member_agent_name",
        "policy_reason",
        "risk_level",
        "run_id",
        "run_group_id",
        "source_agent_id",
        "source_agent_name",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "source_tool",
        "tool_call_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_kind",
        "workflow_node_label",
        "workflow_run_id",
        "workflow_step_label",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _tool_call_status_is_terminal(status: str) -> bool:
    return status in {"completed", "failed", "denied", "skipped", "expired", "cancelled"}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


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


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _tool_output_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _mapping(
        payload.get("output_preview")
        or payload.get("output")
        or payload.get("result")
    )
    if explicit:
        return explicit
    error = payload.get("error")
    return _mapping({"error": error}) if error is not None else {}


def _is_tool_event(event_type: str) -> bool:
    return event_type in {
        "agent.tool.call",
        "agent.tool.denied",
        "agent.tool.started",
        "agent.tool.failed",
        "agent.tool.skipped",
        "agent.tool.approval_required",
        "agent.tool.approval_approved",
        "agent.tool.approval_rejected",
        "agent.tool.approval_timeout",
        "agent.tool.approval_cancelled",
        "agent.tool.completed",
        "approval.cancelled",
        "approval.timeout",
        "tool.approved",
        "tool.approval_approved",
        "tool.approval_cancelled",
        "tool.approval_rejected",
        "tool.requested",
        "tool.started",
        "tool.approval_required",
        "tool.approval_timeout",
        "tool.denied",
        "tool.rejected",
        "tool.skipped",
        "tool.completed",
        "tool.failed",
        "tool.cancelled",
    }


def _tool_name_from_event(event: PublicRunEvent) -> str:
    return _text(
        event.payload.get("tool_name")
        or event.payload.get("tool")
        or event.detail
        or "tool"
    )


def _tool_status_from_event_type(event_type: str) -> str:
    if event_type in {"tool.requested"}:
        return "requested"
    if event_type in {"tool.started", "agent.tool.started"}:
        return "running"
    if event_type in {"tool.approval_required", "agent.tool.approval_required"}:
        return "waiting_approval"
    if event_type in {"agent.tool.approval_approved", "tool.approved", "tool.approval_approved"}:
        return "approved"
    if event_type in {
        "agent.tool.approval_rejected",
        "agent.tool.denied",
        "tool.approval_rejected",
        "tool.denied",
        "tool.rejected",
    }:
        return "denied"
    if event_type in {"agent.tool.approval_timeout", "approval.timeout", "tool.approval_timeout"}:
        return "expired"
    if event_type in {
        "agent.tool.approval_cancelled",
        "approval.cancelled",
        "tool.approval_cancelled",
    }:
        return "cancelled"
    if event_type in {"tool.completed", "agent.tool.call", "agent.tool.completed"}:
        return "completed"
    if event_type in {"tool.failed", "agent.tool.failed"}:
        return "failed"
    if event_type in {"agent.tool.skipped", "tool.skipped"}:
        return "skipped"
    if event_type in {"tool.cancelled"}:
        return "cancelled"
    return "completed"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
