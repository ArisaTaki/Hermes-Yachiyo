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
