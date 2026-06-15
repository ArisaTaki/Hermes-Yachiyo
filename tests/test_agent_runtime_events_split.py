"""Tests for helpers split out of the legacy agent runtime module."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import redact_json_value, redact_run_event_payload


def test_runtime_event_redaction_helpers_match_runtime_json_alias() -> None:
    payload = {
        "command": "echo ok",
        "api_key": "sk-runtime-event-secret123456",
        "nested": ["token=sk-runtime-event-nested123456"],
    }

    split_payload = redact_run_event_payload(payload)
    split_json = redact_json_value(payload)
    legacy_json = agent_runtime._redact_json_value(payload)

    serialized = json.dumps(
        {
            "split_payload": split_payload,
            "split_json": split_json,
            "legacy_json": legacy_json,
        },
        ensure_ascii=False,
    )
    assert "sk-runtime-event-secret123456" not in serialized
    assert "sk-runtime-event-nested123456" not in serialized
    assert split_json == legacy_json
