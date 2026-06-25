"""Shared recovery action metadata helpers for desktop execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RECOVERY_RETRY_CONTEXT_EVENT_TYPE = "agent.desktop.recovery_retry_context"


def recovery_retry_context_payload(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    if metadata.get("desktop_permission_recovery") is not True:
        return {}
    retry_tool = _metadata_text(metadata, "recovery_retry_tool")
    retry_input = metadata.get("recovery_retry_input")
    if not retry_tool and not isinstance(retry_input, Mapping):
        return {}

    recovery_input = metadata.get("recovery_input")
    payload: dict[str, Any] = {
        "source": "desktop_permission_recovery",
        "recovery_tool": _metadata_text(metadata, "recovery_tool"),
        "recovery_input": dict(recovery_input) if isinstance(recovery_input, Mapping) else {},
        "recovery_permission_target": _metadata_text(metadata, "recovery_permission_target"),
        "retry_tool": retry_tool,
        "retry_input": dict(retry_input) if isinstance(retry_input, Mapping) else {},
    }
    if metadata.get("desktop_permission_retry") is True:
        payload["desktop_permission_retry"] = True
    action_kind = _metadata_text(metadata, "recovery_action_kind")
    if action_kind:
        payload["recovery_action_kind"] = action_kind
    for source_key, payload_key in (
        ("recovery_retry_prompt", "retry_prompt"),
        ("recovery_retry_source_event_type", "retry_source_event_type"),
        ("recovery_retry_source_tool_call_id", "retry_source_tool_call_id"),
        ("source_task_id", "source_task_id"),
        ("source_task_title", "source_task_title"),
    ):
        value = _metadata_text(metadata, source_key)
        if value:
            payload[payload_key] = value
    return payload


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    return str(metadata.get(key) or "").strip()
