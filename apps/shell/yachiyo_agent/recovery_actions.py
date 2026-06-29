"""Shared recovery action metadata helpers for desktop execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import DesktopRecoveryActionMetadataSnapshot

RECOVERY_RETRY_CONTEXT_EVENT_TYPE = "agent.desktop.recovery_retry_context"
RECOVERY_ACTION_TASK_METADATA_KEYS = (
    "daily_desktop_intent",
    "desktop_permission_recovery",
    "desktop_permission_retry",
    "recovery_action_kind",
    "recovery_tool",
    "recovery_input",
    "recovery_permission_target",
    "recovery_risk_level",
    "recovery_retry_tool",
    "recovery_retry_input",
    "recovery_retry_input_schema",
    "recovery_retry_input_source",
    "recovery_retry_artifact_tool",
    "recovery_retry_artifact_kind",
    "required_retry_fields",
    "recommended_tools",
    "recovery_retry_prompt",
    "recovery_followup_tool",
    "recovery_followup_input",
    "recovery_retry_source_event_type",
    "recovery_retry_source_tool_call_id",
    "source_task_id",
    "source_task_title",
)


def recovery_action_metadata_snapshot(
    metadata: Mapping[str, Any] | None,
) -> DesktopRecoveryActionMetadataSnapshot | None:
    if not isinstance(metadata, Mapping):
        return None
    if metadata.get("desktop_permission_recovery") is not True:
        return None
    recovery_tool = _metadata_text(metadata, "recovery_tool")
    if not recovery_tool:
        return None
    recovery_input = metadata.get("recovery_input")
    retry_input = metadata.get("recovery_retry_input")
    retry_input_schema = metadata.get("recovery_retry_input_schema")
    followup_input = metadata.get("recovery_followup_input")
    payload = {
        "daily_desktop_intent": bool(metadata.get("daily_desktop_intent", True)),
        "desktop_permission_recovery": True,
        "recovery_tool": recovery_tool,
        "recovery_input": dict(recovery_input) if isinstance(recovery_input, Mapping) else {},
        "recovery_permission_target": _metadata_text(metadata, "recovery_permission_target"),
        "recovery_retry_input": dict(retry_input) if isinstance(retry_input, Mapping) else {},
        "recovery_retry_input_schema": (
            dict(retry_input_schema) if isinstance(retry_input_schema, Mapping) else {}
        ),
        "recovery_followup_input": (
            dict(followup_input) if isinstance(followup_input, Mapping) else {}
        ),
        "required_retry_fields": _metadata_text_list(metadata, "required_retry_fields"),
        "recommended_tools": _metadata_text_list(metadata, "recommended_tools"),
    }
    if metadata.get("desktop_permission_retry") is True:
        payload["desktop_permission_retry"] = True
    for key in (
        "recovery_action_kind",
        "recovery_risk_level",
        "recovery_retry_tool",
        "recovery_retry_input_source",
        "recovery_retry_artifact_tool",
        "recovery_retry_artifact_kind",
        "recovery_retry_prompt",
        "recovery_followup_tool",
        "recovery_retry_source_event_type",
        "recovery_retry_source_tool_call_id",
        "source_task_id",
        "source_task_title",
    ):
        value = _metadata_text(metadata, key)
        if value:
            payload[key] = value
    return DesktopRecoveryActionMetadataSnapshot(**payload)


def recovery_retry_context_payload(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata_snapshot = recovery_action_metadata_snapshot(metadata)
    if metadata_snapshot is None:
        return {}
    raw_retry_input = metadata.get("recovery_retry_input") if isinstance(metadata, Mapping) else None
    retry_tool = metadata_snapshot.recovery_retry_tool or ""
    if not retry_tool and not isinstance(raw_retry_input, Mapping):
        return {}
    payload = metadata_snapshot.model_dump(mode="json", exclude_none=True)

    context_payload: dict[str, Any] = {
        "source": "desktop_permission_recovery",
        "recovery_tool": str(payload.get("recovery_tool") or ""),
        "recovery_input": dict(payload.get("recovery_input") or {}),
        "recovery_permission_target": str(payload.get("recovery_permission_target") or ""),
        "retry_tool": retry_tool,
        "retry_input": dict(payload.get("recovery_retry_input") or {}),
    }
    retry_input_schema = payload.get("recovery_retry_input_schema")
    if isinstance(retry_input_schema, dict) and retry_input_schema:
        context_payload["retry_input_schema"] = dict(retry_input_schema)
    for source_key, context_key in (
        ("recovery_retry_input_source", "retry_input_source"),
        ("recovery_retry_artifact_tool", "retry_artifact_tool"),
        ("recovery_retry_artifact_kind", "retry_artifact_kind"),
    ):
        value = payload.get(source_key)
        if value:
            context_payload[context_key] = value
    required_retry_fields = payload.get("required_retry_fields")
    if isinstance(required_retry_fields, list) and required_retry_fields:
        context_payload["required_retry_fields"] = list(required_retry_fields)
    recommended_tools = payload.get("recommended_tools")
    if isinstance(recommended_tools, list) and recommended_tools:
        context_payload["recommended_tools"] = list(recommended_tools)
    followup_tool = payload.get("recovery_followup_tool")
    if followup_tool:
        context_payload["followup_tool"] = str(followup_tool)
    followup_input = payload.get("recovery_followup_input")
    if isinstance(followup_input, dict) and followup_input:
        context_payload["followup_input"] = dict(followup_input)
    for source_key, context_key in (
        ("desktop_permission_retry", "desktop_permission_retry"),
        ("recovery_action_kind", "recovery_action_kind"),
        ("recovery_retry_prompt", "retry_prompt"),
        ("recovery_retry_source_event_type", "retry_source_event_type"),
        ("recovery_retry_source_tool_call_id", "retry_source_tool_call_id"),
        ("source_task_id", "source_task_id"),
        ("source_task_title", "source_task_title"),
    ):
        value = payload.get(source_key)
        if value:
            context_payload[context_key] = value
    return context_payload


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    return str(metadata.get(key) or "").strip()


def _metadata_text_list(metadata: Mapping[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
