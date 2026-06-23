"""ToolCall public snapshots derived from replayable RunEvents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent, ToolCallSnapshot
from .tool_call_payload_snapshots import (
    tool_call_snapshot_from_payload,
    tool_call_status_is_terminal,
    tool_result_status,
)

_DAILY_DESKTOP_INTENT_TOOL_EVENTS = {
    "agent.desktop.intent_approval_required",
    "agent.desktop.intent_completed",
    "agent.desktop.intent_unavailable",
}


def tool_call_snapshots_from_events(events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
    calls: list[ToolCallSnapshot] = []
    active_by_key: dict[str, int] = {}
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        if not is_tool_event(event.event_type):
            continue
        payload = tool_call_payload_from_event(event)
        call = tool_call_snapshot_from_payload(payload, run_id=event.run_id)
        key = tool_call_correlation_key(payload, call)
        active_index = active_by_key.get(key) if key else None
        if active_index is None and event.event_type in _DAILY_DESKTOP_INTENT_TOOL_EVENTS:
            active_index = latest_matching_tool_call_index(calls, call)
        if active_index is None:
            active_index = len(calls)
            calls.append(call)
        else:
            calls[active_index] = merge_tool_call_snapshots(calls[active_index], call)
        if key:
            if tool_call_status_is_terminal(call.status):
                active_by_key.pop(key, None)
            else:
                active_by_key[key] = active_index
    return calls


def tool_call_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
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
        "tool_name": tool_name_from_event(event),
        "status": tool_status_from_event_payload(event.event_type, payload),
        "created_at": event.created_at,
    }
    if event.event_type in _DAILY_DESKTOP_INTENT_TOOL_EVENTS:
        output_preview = daily_desktop_intent_output_preview(event.event_type, payload)
        if output_preview:
            normalized.setdefault("output_preview", output_preview)
    if approval_id:
        normalized.setdefault("approval_id", approval_id)
    if risk_level:
        normalized.setdefault("risk_level", risk_level)
    merge_tool_trace_context(normalized, payload)
    merge_tool_trace_into_input_preview(
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


def merge_tool_trace_context(source: dict[str, Any], payload: dict[str, Any]) -> None:
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


def merge_tool_trace_into_input_preview(
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


def merge_tool_call_snapshots(
    current: ToolCallSnapshot,
    next_call: ToolCallSnapshot,
) -> ToolCallSnapshot:
    output_preview = dict(current.output_preview)
    output_preview.update(next_call.output_preview)
    completed_at = next_call.completed_at or current.completed_at
    if tool_call_status_is_terminal(next_call.status) and not completed_at:
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
        foreground_lock_busy=current.foreground_lock_busy or next_call.foreground_lock_busy,
        foreground_lock_holder=current.foreground_lock_holder or next_call.foreground_lock_holder,
        approval_id=current.approval_id or next_call.approval_id,
        started_at=current.started_at or next_call.started_at,
        completed_at=completed_at,
    )


def tool_call_correlation_key(
    payload: Mapping[str, Any],
    call: ToolCallSnapshot,
) -> str:
    explicit_id = _text(payload.get("tool_call_id") or payload.get("id"))
    run_id = call.run_id or _text(payload.get("run_id"))
    if explicit_id:
        return f"{run_id}:id:{explicit_id}"
    preview = _tool_call_correlation_preview(call.input_preview)
    return f"{run_id}:tool:{call.tool_name}:{_stable_json(preview)}"


def latest_matching_tool_call_index(
    calls: list[ToolCallSnapshot],
    call: ToolCallSnapshot,
) -> int | None:
    call_key = tool_call_snapshot_match_key(call)
    for index in range(len(calls) - 1, -1, -1):
        if tool_call_snapshot_match_key(calls[index]) == call_key:
            return index
    return None


def tool_call_snapshot_match_key(call: ToolCallSnapshot) -> str:
    preview = _tool_call_correlation_preview(call.input_preview)
    return f"{call.run_id or ''}:tool:{call.tool_name}:{_stable_json(preview)}"


def is_tool_event(event_type: str) -> bool:
    return event_type in _DAILY_DESKTOP_INTENT_TOOL_EVENTS or event_type in {
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


def tool_name_from_event(event: PublicRunEvent) -> str:
    return _text(
        event.payload.get("tool_name")
        or event.payload.get("tool")
        or event.detail
        or "tool"
    )


def tool_status_from_event_type(event_type: str) -> str:
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


def tool_status_from_event_payload(event_type: str, payload: Mapping[str, Any]) -> str:
    if event_type == "agent.desktop.intent_approval_required":
        return "waiting_approval"
    if event_type == "agent.desktop.intent_unavailable":
        return "blocked"
    if event_type == "agent.desktop.intent_completed":
        result = payload.get("result")
        if isinstance(result, Mapping):
            result_status = tool_result_status(result)
            if result_status:
                return result_status
        return "completed"
    explicit = _text(payload.get("status"))
    if explicit:
        return explicit
    if _payload_foreground_lock_is_busy(payload):
        return "blocked"
    result = payload.get("result")
    if isinstance(result, Mapping):
        result_status = tool_result_status(result)
        if result_status:
            return result_status
    result_status = tool_result_status(payload)
    if result_status:
        return result_status
    return tool_status_from_event_type(event_type)


def daily_desktop_intent_output_preview(
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    if event_type == "agent.desktop.intent_unavailable":
        return {
            key: payload[key]
            for key in (
                "reason",
                "blocked_by",
                "blocked_summary",
                "recovery_actions",
                "allowed_tools",
            )
            if payload.get(key)
        }
    if event_type == "agent.desktop.intent_approval_required":
        return {
            key: payload[key]
            for key in ("reason", "approval_id", "risk_level", "policy_reason")
            if payload.get(key)
        }
    return {}


def _payload_foreground_lock_is_busy(payload: Mapping[str, Any]) -> bool:
    if payload.get("foreground_lock_busy") is True:
        return True
    for key in ("output_preview", "output", "result"):
        value = payload.get(key)
        if isinstance(value, Mapping) and value.get("foreground_lock_busy") is True:
            return True
    return False


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


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
