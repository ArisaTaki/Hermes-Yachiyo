"""ToolCall public snapshots derived from direct runtime payloads."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import ToolCallSnapshot

_LEGACY_APPLE_MUSIC_AFFECTED_TOOLS = [
    "media.apple_music_play",
    "media.apple_music_open_and_play",
    "media.apple_music_control",
]
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
_TOOL_METADATA_KEYS = (
    "followup_target",
    "action_target",
    "observation_evidence",
)


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
    foreground_lock_busy = tool_foreground_lock_is_busy(payload, output_preview)
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
        **{
            key: _optional_text(payload.get(key) or input_preview.get(key))
            for key in _PLANNER_TRACE_KEYS
        },
        tool_name=tool_name,
        status=status,
        risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
        input_preview=input_preview,
        output_preview=output_preview,
        metadata=tool_call_metadata(payload),
        foreground_lock_busy=foreground_lock_busy,
        foreground_lock_holder=tool_foreground_lock_holder(payload, output_preview),
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
    result_status = tool_result_status(output_preview) or tool_result_status(payload)
    if result_status:
        return result_status
    return "completed"


def tool_result_status(value: Mapping[str, Any]) -> str:
    if _foreground_lock_is_busy(value):
        return "blocked"
    if _value_is_true(value.get("approval_required")):
        return "waiting_approval"
    if _value_is_false(value.get("ok")):
        return "failed"
    return ""


def tool_output_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _mapping(
        payload.get("output_preview")
        or payload.get("output")
        or payload.get("result")
    )
    if explicit:
        return _legacy_desktop_permissions_output_preview(payload, explicit)
    error = payload.get("error")
    return _mapping({"error": error}) if error is not None else {}


def _legacy_desktop_permissions_output_preview(
    payload: Mapping[str, Any],
    output_preview: dict[str, Any],
) -> dict[str, Any]:
    tool_name = _text(payload.get("tool_name") or payload.get("tool"))
    if tool_name != "desktop.permissions":
        return output_preview
    permission_targets = output_preview.get("permission_targets")
    affected_tools = output_preview.get("affected_tools")
    if not isinstance(permission_targets, list) or not isinstance(affected_tools, list):
        return output_preview
    target_set = {_text(item) for item in permission_targets}
    affected_set = {_text(item) for item in affected_tools}
    if not {"music_app", "automation"}.issubset(target_set):
        return output_preview
    if not set(_LEGACY_APPLE_MUSIC_AFFECTED_TOOLS).issubset(affected_set):
        return output_preview
    return {
        **output_preview,
        "affected_tools": list(_LEGACY_APPLE_MUSIC_AFFECTED_TOOLS),
    }


def tool_foreground_lock_is_busy(
    payload: Mapping[str, Any],
    output_preview: Mapping[str, Any],
) -> bool:
    if _foreground_lock_is_busy(output_preview) or _foreground_lock_is_busy(payload):
        return True
    foreground_lock = output_preview.get("foreground_lock")
    if not isinstance(foreground_lock, Mapping):
        foreground_lock = payload.get("foreground_lock")
    return isinstance(foreground_lock, Mapping) and bool(foreground_lock.get("busy"))


def tool_foreground_lock_holder(
    payload: Mapping[str, Any],
    output_preview: Mapping[str, Any],
) -> str | None:
    holder = _text(output_preview.get("locked_by") or payload.get("locked_by"))
    if holder:
        return holder
    for source in (output_preview, payload):
        foreground_lock = source.get("foreground_lock")
        if isinstance(foreground_lock, Mapping):
            holder = _text(foreground_lock.get("holder") or foreground_lock.get("locked_by"))
            if holder:
                return holder
    return None


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
            **{
                key: _optional_text(getattr(snapshot, key))
                for key in _PLANNER_TRACE_KEYS
            },
            "tool_name": _text(snapshot.tool_name),
            "status": _text(snapshot.status),
            "risk_level": _optional_text(snapshot.risk_level),
            "input_preview": _mapping(snapshot.input_preview),
            "output_preview": _mapping(snapshot.output_preview),
            "metadata": _mapping(snapshot.metadata),
            "foreground_lock_busy": bool(snapshot.foreground_lock_busy),
            "foreground_lock_holder": _optional_text(snapshot.foreground_lock_holder),
            "approval_id": _optional_text(snapshot.approval_id),
            "started_at": _text(snapshot.started_at),
            "completed_at": _optional_text(snapshot.completed_at),
        }
    )


def tool_call_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(payload.get("metadata"))
    for key in _TOOL_METADATA_KEYS:
        value = payload.get(key)
        if isinstance(value, Mapping) and value:
            metadata[key] = _mapping(value)
    return metadata


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    result = dict(redacted) if isinstance(redacted, Mapping) else {}
    return _restore_known_preview_types(_restore_stable_scalar_types(value, result))


def _restore_stable_scalar_types(source: Any, target: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        return dict(target) if isinstance(target, Mapping) else {}
    result = dict(target)
    for key, item in source.items():
        key_text = _text(key)
        target_item = result.get(key_text)
        if isinstance(item, (bool, int, float)):
            result[key_text] = item
        elif isinstance(item, Mapping) and isinstance(target_item, Mapping):
            result[key_text] = _restore_stable_scalar_types(item, target_item)
        elif isinstance(item, list) and isinstance(target_item, list):
            result[key_text] = [
                _restore_stable_scalar_types(source_item, redacted_item)
                if isinstance(source_item, Mapping) and isinstance(redacted_item, Mapping)
                else redacted_item
                for source_item, redacted_item in zip(item, target_item, strict=False)
            ]
    return result


def _restore_known_preview_types(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for key in ("limit", "click_count", "repeat_count", "level", "pages", "x", "y"):
        item = result.get(key)
        if isinstance(item, str) and item.isdigit():
            result[key] = int(item)
    for key in ("ok", "approval_required", "permission_error", "fallback_used"):
        item = result.get(key)
        if _value_is_true(item):
            result[key] = True
        elif _value_is_false(item):
            result[key] = False
    for key in (
        "permission_targets",
        "missing_permissions",
        "affected_tools",
        "recovery_actions",
        "recovery_hints",
    ):
        item = result.get(key)
        if isinstance(item, str):
            parsed = _literal_preview_value(item)
            if isinstance(parsed, list):
                result[key] = parsed
    data = result.get("data")
    if isinstance(data, str):
        parsed_data = _literal_preview_value(data)
        if isinstance(parsed_data, (dict, list)):
            result["data"] = parsed_data
    return result


def _literal_preview_value(value: str) -> Any:
    text = value.strip()
    if not (
        (text.startswith("[") and text.endswith("]"))
        or (text.startswith("{") and text.endswith("}"))
    ):
        return value
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return value


def _value_is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _value_is_false(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
