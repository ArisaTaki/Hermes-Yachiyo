"""Shared recovery action metadata helper tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent import (
    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
    recovery_retry_context_payload,
)


def test_recovery_retry_context_payload_requires_recovery_metadata() -> None:
    assert recovery_retry_context_payload(None) == {}
    assert recovery_retry_context_payload({}) == {}
    assert recovery_retry_context_payload({"recovery_retry_tool": "screen.capture"}) == {}
    assert recovery_retry_context_payload({"desktop_permission_recovery": True}) == {}


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
            "recovery_retry_prompt": "截图当前屏幕",
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
