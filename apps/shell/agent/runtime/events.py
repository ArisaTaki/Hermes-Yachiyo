"""Run event helper functions split from the legacy runtime module."""

from __future__ import annotations

import json
import re
from typing import Any

from packages.security import (
    contains_sensitive_text,
    redact_api_error_text,
    redact_sensitive_text,
    sanitize_sensitive_value,
)

RUNTIME_JSON_REDACTION_MAX_ITEMS = 1000
_MEMORY_TOOL_NAMES = {"memory.add", "memory.replace", "memory.remove"}
_SENSITIVE_PREVALIDATION_PREVIEW_RE = re.compile(
    r"(?i)\b(?:authorization|bearer|[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD))\b"
)


def redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def redact_run_event_payload(value: Any) -> Any:
    return sanitize_sensitive_value(
        value,
        text_limit=0,
        max_items=RUNTIME_JSON_REDACTION_MAX_ITEMS,
        collapse_whitespace=False,
        trim=False,
    )


def tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def runtime_trace_input_preview(tool_name: str, input_preview: Any) -> Any:
    if not isinstance(input_preview, dict):
        return input_preview
    if tool_name == "artifact.write":
        return {
            key: value
            for key, value in input_preview.items()
            if str(key) != "content"
        }
    if tool_name not in _MEMORY_TOOL_NAMES:
        return input_preview
    return {
        key: value
        for key, value in input_preview.items()
        if str(key) not in {"content", "old_content"}
    }


def canonical_tool_input_preview(
    tool_name: str,
    input_preview: Any,
    *,
    pre_validation: bool = False,
) -> Any:
    preview = runtime_trace_input_preview(tool_name, input_preview)
    if not pre_validation:
        return preview
    try:
        serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        serialized = str(preview)
    if (
        contains_sensitive_text(serialized)
        or redact_secrets(serialized) != serialized
        or _SENSITIVE_PREVALIDATION_PREVIEW_RE.search(serialized)
    ):
        return {"redacted": True, "reason": "sensitive_input"}
    return preview


def canonical_tool_event_payload(
    tool_name: str,
    input_preview: Any,
    *,
    approved: bool = False,
    pre_validation: bool = False,
    result: dict[str, Any] | None = None,
    error: Any = None,
    status: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": tool_name,
        "input_preview": canonical_tool_input_preview(
            tool_name,
            input_preview,
            pre_validation=pre_validation,
        ),
        "approved": bool(approved),
    }
    if status:
        payload["status"] = status
    if result is not None:
        payload["output_preview"] = tool_input_preview(result)
    if error is not None:
        payload["error"] = redact_api_error_text(error)
    return payload


class ToolEventPayloadBuilder:
    """Builds canonical ToolCall RunEvent payloads."""

    def payload(
        self,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
        pre_validation: bool = False,
        result: dict[str, Any] | None = None,
        error: Any = None,
        status: str = "",
    ) -> dict[str, Any]:
        return canonical_tool_event_payload(
            tool_name,
            input_preview,
            approved=approved,
            pre_validation=pre_validation,
            result=result,
            error=error,
            status=status,
        )


def canonical_run_event_aliases(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    clean_event_type = str(event_type or "")
    direct_alias = {
        "model.request.started": "model.requested",
        "model.output.completed": "model.completed",
        "workflow.run.approval_required": "workflow.paused_for_approval",
        "workflow.run.resumed": "workflow.resumed",
        "workflow.run.completed": "workflow.completed",
        "workflow.run.failed": "workflow.failed",
        "skill.dispatch.read": "skill.selected",
    }.get(clean_event_type)
    if direct_alias:
        return [direct_alias]

    if clean_event_type in {
        "workflow.node.start",
        "workflow.node.agent",
        "workflow.node.workflow",
        "workflow.node.artifact",
        "workflow.node.condition",
        "workflow.node.parallel",
        "workflow.node.loop",
    }:
        status = str((payload or {}).get("status") or "").strip()
        aliases = ["workflow.node.started"]
        if status == "completed":
            aliases.append("workflow.node.completed")
        elif status in {"failed", "cancelled"}:
            aliases.append("workflow.node.failed")
        elif status == "approval_required":
            aliases.append("workflow.paused_for_approval")
        return aliases
    return []


class RuntimeRunEventRecorder:
    """Writes replayable RunEvents and their public compatibility aliases."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        event = self._repository.append(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )
        for alias in canonical_run_event_aliases(event_type, payload):
            self._repository.append(
                run_id,
                alias,
                payload,
                actor=actor,
                visibility=visibility,
                sensitivity=sensitivity,
            )
        return event

    def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self._repository.list(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )
