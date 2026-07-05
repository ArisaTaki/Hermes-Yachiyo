"""Shared recovery action metadata helper tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent import (
    RECOVERY_ACTION_TASK_METADATA_KEYS,
    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
    recovery_action_metadata_snapshot,
    recovery_retry_context_payload,
)


def test_recovery_retry_context_payload_requires_recovery_metadata() -> None:
    assert recovery_retry_context_payload(None) == {}
    assert recovery_retry_context_payload({}) == {}
    assert recovery_retry_context_payload({"recovery_retry_tool": "screen.capture"}) == {}
    assert recovery_retry_context_payload({"desktop_permission_recovery": True}) == {}


def test_recovery_action_metadata_snapshot_normalizes_task_metadata_contract() -> None:
    snapshot = recovery_action_metadata_snapshot(
        {
            "daily_desktop_intent": True,
            "desktop_permission_recovery": True,
            "recovery_tool": "system.settings_open",
            "recovery_input": {"target": "屏幕录制权限"},
            "recovery_permission_target": "screen_recording",
            "recovery_risk_level": "low",
            "recovery_retry_tool": "screen.capture",
            "recovery_retry_input": {"display_id": "main"},
            "recovery_retry_input_schema": {
                "type": "object",
                "required": ["display_id"],
                "properties": {"display_id": {"type": "string"}},
            },
            "recovery_retry_input_source": "screen_capture_artifact",
            "recovery_retry_artifact_tool": "screen.capture",
            "recovery_retry_artifact_kind": "image",
            "required_retry_fields": ["display_id"],
            "recommended_tools": ["screen.capture"],
            "recovery_followup_tool": "desktop.type_text",
            "recovery_followup_input": {
                "text_source": "original_request",
                "character_count": 5,
            },
            "action_target": {"action": "capture", "target": "main_display"},
            "observation_evidence": {"source_tool": "screen.capture"},
            "observation_retry": {
                "tool": "screen.capture",
                "reason": "permission_recovered",
            },
            "verification_targets": [{"step_id": "verify-screen", "todo_id": "todo-screen"}],
            "task_verification_targets": [
                {"step_id": "verify-screen", "todo_title": "Verify screenshot"}
            ],
            "source_task_id": "task-source-screen",
            "ignored": "value",
        }
    )

    assert RECOVERY_ACTION_TASK_METADATA_KEYS == (
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
        "action_target",
        "observation_evidence",
        "observation_retry",
        "verification_targets",
        "task_verification_targets",
        "recovery_retry_source_event_type",
        "recovery_retry_source_tool_call_id",
        "source_task_id",
        "source_task_title",
    )
    assert snapshot is not None
    assert snapshot.model_dump(mode="json", exclude_none=True) == {
        "daily_desktop_intent": True,
        "desktop_permission_recovery": True,
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "屏幕录制权限"},
        "recovery_permission_target": "screen_recording",
        "recovery_risk_level": "low",
        "recovery_retry_tool": "screen.capture",
        "recovery_retry_input": {"display_id": "main"},
        "recovery_retry_input_schema": {
            "type": "object",
            "required": ["display_id"],
            "properties": {"display_id": {"type": "string"}},
        },
        "recovery_retry_input_source": "screen_capture_artifact",
        "recovery_retry_artifact_tool": "screen.capture",
        "recovery_retry_artifact_kind": "image",
        "required_retry_fields": ["display_id"],
        "recommended_tools": ["screen.capture"],
        "recovery_followup_tool": "desktop.type_text",
        "recovery_followup_input": {
            "text_source": "original_request",
            "character_count": 5,
        },
        "action_target": {"action": "capture", "target": "main_display"},
        "observation_evidence": {"source_tool": "screen.capture"},
        "observation_retry": {
            "tool": "screen.capture",
            "reason": "permission_recovered",
        },
        "verification_targets": [{"step_id": "verify-screen", "todo_id": "todo-screen"}],
        "task_verification_targets": [
            {"step_id": "verify-screen", "todo_title": "Verify screenshot"}
        ],
        "source_task_id": "task-source-screen",
    }


def test_recovery_retry_context_payload_projects_retry_context_for_replay() -> None:
    payload = recovery_retry_context_payload(
        {
            "desktop_permission_recovery": True,
            "desktop_permission_retry": True,
            "recovery_action_kind": "retry_original",
            "recovery_tool": "system.settings_open",
            "recovery_input": {"target": "屏幕录制权限"},
            "recovery_permission_target": "screen_recording",
            "recovery_retry_tool": "screen.capture",
            "recovery_retry_input": {"display_id": "main"},
            "recovery_retry_input_schema": {
                "type": "object",
                "required": ["display_id"],
                "properties": {"display_id": {"type": "string"}},
            },
            "recovery_retry_input_source": "screen_capture_artifact",
            "recovery_retry_artifact_tool": "screen.capture",
            "recovery_retry_artifact_kind": "image",
            "required_retry_fields": ["display_id"],
            "recommended_tools": ["screen.capture"],
            "recovery_retry_prompt": "截图当前屏幕",
            "recovery_followup_tool": "desktop.type_text",
            "recovery_followup_input": {
                "text_source": "original_request",
                "character_count": 5,
            },
            "action_target": {"action": "capture", "target": "main_display"},
            "observation_evidence": {"source_tool": "screen.capture"},
            "observation_retry": {
                "tool": "screen.capture",
                "reason": "permission_recovered",
            },
            "verification_targets": [{"step_id": "verify-screen", "todo_id": "todo-screen"}],
            "task_verification_targets": [
                {"step_id": "verify-screen", "todo_title": "Verify screenshot"}
            ],
            "recovery_retry_source_event_type": "agent.desktop.permission_recovery",
            "recovery_retry_source_tool_call_id": "tool-call-1",
            "source_task_id": "task-source-screen",
            "source_task_title": "截图当前桌面",
        }
    )

    assert RECOVERY_RETRY_CONTEXT_EVENT_TYPE == "agent.desktop.recovery_retry_context"
    assert payload == {
        "source": "desktop_permission_recovery",
        "desktop_permission_retry": True,
        "recovery_action_kind": "retry_original",
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "屏幕录制权限"},
        "recovery_permission_target": "screen_recording",
        "retry_tool": "screen.capture",
        "retry_input": {"display_id": "main"},
        "retry_input_schema": {
            "type": "object",
            "required": ["display_id"],
            "properties": {"display_id": {"type": "string"}},
        },
        "retry_input_source": "screen_capture_artifact",
        "retry_artifact_tool": "screen.capture",
        "retry_artifact_kind": "image",
        "required_retry_fields": ["display_id"],
        "recommended_tools": ["screen.capture"],
        "followup_tool": "desktop.type_text",
        "followup_input": {
            "text_source": "original_request",
            "character_count": 5,
        },
        "action_target": {"action": "capture", "target": "main_display"},
        "observation_evidence": {"source_tool": "screen.capture"},
        "observation_retry": {
            "tool": "screen.capture",
            "reason": "permission_recovered",
        },
        "verification_targets": [{"step_id": "verify-screen", "todo_id": "todo-screen"}],
        "task_verification_targets": [
            {"step_id": "verify-screen", "todo_title": "Verify screenshot"}
        ],
        "retry_prompt": "截图当前屏幕",
        "retry_source_event_type": "agent.desktop.permission_recovery",
        "retry_source_tool_call_id": "tool-call-1",
        "source_task_id": "task-source-screen",
        "source_task_title": "截图当前桌面",
    }


def test_recovery_retry_context_payload_accepts_retry_input_without_retry_tool() -> None:
    assert recovery_retry_context_payload(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.permissions",
            "recovery_input": {},
            "recovery_retry_input": {"reason": "diagnose again"},
        }
    ) == {
        "source": "desktop_permission_recovery",
        "recovery_tool": "desktop.permissions",
        "recovery_input": {},
        "recovery_permission_target": "",
        "retry_tool": "",
        "retry_input": {"reason": "diagnose again"},
    }
