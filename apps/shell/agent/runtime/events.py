"""Run event helper functions split from the legacy runtime module."""

from __future__ import annotations

from typing import Any

from packages.security import redact_sensitive_text, sanitize_sensitive_value

RUNTIME_JSON_REDACTION_MAX_ITEMS = 1000


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
