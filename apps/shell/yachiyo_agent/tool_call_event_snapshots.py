"""ToolCall public snapshots derived from replayable RunEvents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent, ToolCallSnapshot
from .event_context import run_event_context_payload
from .tool_call_payload_snapshots import (
    tool_call_snapshot_from_payload,
    tool_call_status_is_terminal,
    tool_result_status,
)

_DAILY_DESKTOP_INTENT_TOOL_EVENTS = {
    "agent.desktop.intent_approval_required",
    "agent.desktop.intent_completed",
    "agent.desktop.permission_recovery",
    "agent.desktop.intent_unavailable",
}
_TOOL_INPUT_RESOLUTION_EVENT_TYPE = "agent.tool.input_resolved"
_PLANNER_TRACE_KEYS = (
    "source",
    "planning_reason",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "replan_request_id",
    "replan_trigger",
)


def tool_call_snapshots_from_events(events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
    calls: list[ToolCallSnapshot] = []
    active_by_key: dict[str, int] = {}
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        if not is_tool_event(event.event_type):
            continue
        for payload in tool_call_payloads_from_event(event):
            call = tool_call_snapshot_from_payload(payload, run_id=event.run_id)
            key = tool_call_correlation_key(payload, call)
            active_index = active_by_key.get(key) if key else None
            if active_index is None and is_daily_desktop_intent_tool_event(
                event.event_type
            ):
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


def tool_call_payloads_from_event(event: PublicRunEvent) -> list[dict[str, Any]]:
    if is_desktop_intent_event(event.event_type, "completed"):
        step_payloads = daily_desktop_intent_step_payloads(event)
        if step_payloads:
            return [
                tool_call_payload_from_event(
                    event.model_copy(
                        update={
                            "detail": _text(step_payload.get("tool") or event.detail),
                            "payload": step_payload,
                        }
                    )
                )
                for step_payload in step_payloads
            ]
    return [tool_call_payload_from_event(event)]


def tool_call_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = run_event_context_payload(event)
    if event.event_type == _TOOL_INPUT_RESOLUTION_EVENT_TYPE:
        payload = tool_input_resolution_payload(payload)
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
    if is_daily_desktop_intent_tool_event(event.event_type):
        output_preview = daily_desktop_intent_output_preview(event.event_type, payload)
        if output_preview:
            normalized.setdefault("output_preview", output_preview)
    if approval_id:
        normalized.setdefault("approval_id", approval_id)
    if risk_level:
        normalized.setdefault("risk_level", risk_level)
    merge_tool_trace_context(normalized, payload)
    trace_context = {
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
        "core_id": payload.get("core_id"),
        "workspace_id": payload.get("workspace_id"),
        "task_id": payload.get("task_id"),
    }
    for key in _PLANNER_TRACE_KEYS:
        if key == "source" and is_daily_desktop_intent_tool_event(event.event_type):
            continue
        trace_context[key] = payload.get(key)
    merge_tool_trace_into_input_preview(
        normalized,
        trace_context,
    )
    return normalized


def daily_desktop_intent_step_payloads(event: PublicRunEvent) -> list[dict[str, Any]]:
    payload = run_event_context_payload(event)
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []

    step_payloads: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, Mapping):
            continue
        tool_name = _text(step.get("tool") or step.get("tool_name"))
        if not tool_name:
            continue
        input_preview = _mapping_from_first(
            step,
            "input_preview",
            "input",
            "arguments",
            "args",
        )
        result = _mapping_from_first(step, "result", "output_preview", "output")
        step_payload = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "source",
                "source_run_id",
                "source_runnable_id",
                "source_runnable_name",
                "workflow_id",
                "workflow_run_id",
                "workflow_node_id",
                "workflow_node_label",
                "group_id",
                "group_run_id",
                "run_group_id",
                "core_id",
                "workspace_id",
                "task_id",
                "task_workspace_items",
                "task_verification_targets",
                "workspace_items",
                "verification_targets",
                "member_agent_id",
                "member_agent_name",
                "agent_id",
                "agent_name",
                "risk_level",
                "risk",
                *_PLANNER_TRACE_KEYS,
            }
        }
        step_payload.update(
            {
                "tool_call_id": _text(
                    step.get("tool_call_id")
                    or step.get("id")
                    or f"{event.run_id or 'run'}:desktop-intent-step:{event.sequence}:{index}"
                ),
                "tool": tool_name,
                "tool_name": tool_name,
                "input_preview": input_preview,
                "result": result,
            }
        )
        if step.get("status"):
            step_payload["status"] = step.get("status")
        if step.get("summary"):
            step_payload["summary"] = step.get("summary")
        step_payloads.append(step_payload)
    return step_payloads


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
        "core_id",
        "workspace_id",
        "task_id",
        "task_workspace_items",
        "task_verification_targets",
        "workspace_items",
        "verification_targets",
        *_PLANNER_TRACE_KEYS,
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
    metadata = dict(current.metadata)
    metadata.update(next_call.metadata)
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
        core_id=current.core_id or next_call.core_id,
        workspace_id=current.workspace_id or next_call.workspace_id,
        task_id=current.task_id or next_call.task_id,
        source=current.source or next_call.source,
        planning_reason=current.planning_reason or next_call.planning_reason,
        decision_id=current.decision_id or next_call.decision_id,
        plan_id=current.plan_id or next_call.plan_id,
        tool_plan_id=current.tool_plan_id or next_call.tool_plan_id,
        intent_kind=current.intent_kind or next_call.intent_kind,
        step_id=current.step_id or next_call.step_id,
        planner_step_id=current.planner_step_id or next_call.planner_step_id,
        capability_id=current.capability_id or next_call.capability_id,
        replan_request_id=current.replan_request_id or next_call.replan_request_id,
        replan_trigger=current.replan_trigger or next_call.replan_trigger,
        task_workspace_items=_merge_record_lists(
            current.task_workspace_items,
            next_call.task_workspace_items,
        ),
        task_verification_targets=_merge_record_lists(
            current.task_verification_targets,
            next_call.task_verification_targets,
        ),
        tool_name=current.tool_name or next_call.tool_name,
        status=next_call.status or current.status,
        risk_level=current.risk_level or next_call.risk_level,
        input_preview=_merge_input_previews(current.input_preview, next_call.input_preview),
        output_preview=output_preview,
        metadata=metadata,
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
    return is_daily_desktop_intent_tool_event(event_type) or event_type in {
        "agent.tool.call",
        "agent.tool.denied",
        _TOOL_INPUT_RESOLUTION_EVENT_TYPE,
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
    if event_type == _TOOL_INPUT_RESOLUTION_EVENT_TYPE:
        return "resolved"
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
    if is_desktop_intent_event(event_type, "approval_required"):
        return "waiting_approval"
    if is_desktop_intent_event(event_type, "unavailable"):
        return "blocked"
    if is_desktop_permission_recovery_event(event_type):
        return _text(payload.get("status")) or "blocked"
    if is_desktop_intent_event(event_type, "completed"):
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


def tool_input_resolution_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    resolved_app_name = _text(payload.get("resolved_app_name"))
    requested_app_name = _text(payload.get("requested_app_name"))
    source_tool = _text(payload.get("source_tool"))
    input_preview = _nested_mapping(payload, "input_preview")
    if resolved_app_name:
        input_preview.setdefault("app_name", resolved_app_name)
        input_preview.setdefault("resolved_app_name", resolved_app_name)
    if requested_app_name:
        input_preview.setdefault("requested_app_name", requested_app_name)
    if source_tool:
        input_preview.setdefault("app_resolution_source", source_tool)
    for key in (
        "app_resolution_score",
        "app_resolution_confidence",
        "app_resolution_reason",
        "resolved_app_path",
    ):
        value = _text(payload.get(key))
        if value:
            input_preview.setdefault(key, value)
    normalized = dict(payload)
    if input_preview:
        normalized["input_preview"] = input_preview
    normalized.setdefault("status", "resolved")
    return normalized


def daily_desktop_intent_output_preview(
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    if is_desktop_intent_event(event_type, "unavailable"):
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
    if is_desktop_intent_event(event_type, "approval_required"):
        return {
            key: payload[key]
            for key in ("reason", "approval_id", "risk_level", "policy_reason")
            if payload.get(key)
        }
    if is_desktop_permission_recovery_event(event_type):
        return {
            key: payload[key]
            for key in (
                "permission_targets",
                "affected_tools",
                "recovery_hints",
                "recovery_actions",
                "status",
            )
            if payload.get(key)
        }
    return {}


def is_daily_desktop_intent_tool_event(event_type: str) -> bool:
    return (
        event_type in _DAILY_DESKTOP_INTENT_TOOL_EVENTS
        or is_desktop_permission_recovery_event(event_type)
        or any(
            is_desktop_intent_event(event_type, suffix)
            for suffix in ("approval_required", "completed", "unavailable")
        )
    )


def is_desktop_intent_event(event_type: str, suffix: str) -> bool:
    return event_type in {
        f"agent.desktop.intent_{suffix}",
        f"group.run.desktop.intent_{suffix}",
        f"workflow.desktop.intent_{suffix}",
        f"workflow.run.desktop.intent_{suffix}",
    }


def is_desktop_permission_recovery_event(event_type: str) -> bool:
    return event_type in {
        "agent.desktop.permission_recovery",
        "group.run.desktop.permission_recovery",
        "workflow.desktop.permission_recovery",
        "workflow.run.desktop.permission_recovery",
    }


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
        "app_resolution_source",
        "app_resolution_score",
        "app_resolution_confidence",
        "app_resolution_reason",
        "requested_app_name",
        "resolved_app_name",
        "resolved_app_path",
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
        *_PLANNER_TRACE_KEYS,
    }
    return {
        key: _canonical_preview_value(value)
        for key, value in preview.items()
        if key not in trace_keys
    }


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_from_first(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _merge_input_previews(
    current: Mapping[str, Any],
    next_preview: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(current)
    for key, value in next_preview.items():
        merged.setdefault(key, value)
    return merged


def _merge_record_lists(
    current: list[dict[str, Any]],
    next_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*current, *next_items]:
        if not isinstance(item, Mapping):
            continue
        record = dict(item)
        key = _stable_json(record)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def _canonical_preview_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _canonical_preview_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_preview_value(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text and text.lstrip("-").isdigit():
            try:
                return int(text)
            except ValueError:
                return value
    return value


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
