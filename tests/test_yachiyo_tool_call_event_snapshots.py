"""ToolCall RunEvent replay helper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent
from apps.shell.yachiyo_agent.tool_call_event_snapshots import (
    tool_call_snapshots_from_events,
    tool_call_payload_from_event,
    tool_status_from_event_type,
)


def test_tool_call_payload_from_event_preserves_approval_trace_context() -> None:
    payload = tool_call_payload_from_event(
        PublicRunEvent(
            run_id="run-tool-context",
            sequence=7,
            event_type="tool.approval_required",
            detail="terminal.run",
            created_at="2026-06-17T00:00:00Z",
            payload={
                "tool_call_id": "call-1",
                "input_preview": {"command": "npm test"},
                "pending_approval": {
                    "approval_id": "approval-1",
                    "risk_level": "high",
                    "policy_reason": "terminal command requires approval",
                },
                "group_id": "group-1",
                "group_run_id": "group-run-1",
                "member_agent_id": "agent-1",
                "member_agent_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "test",
                "workflow_node_label": "Run Tests",
            },
        )
    )

    assert payload["tool_name"] == "terminal.run"
    assert payload["status"] == "waiting_approval"
    assert payload["approval_id"] == "approval-1"
    assert payload["risk_level"] == "high"
    assert payload["source_runnable_id"] == "agent-1"
    assert payload["source_runnable_name"] == "Planner"
    assert payload["input_preview"] == {
        "command": "npm test",
        "approval_id": "approval-1",
        "risk_level": "high",
        "policy_reason": "terminal command requires approval",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "test",
        "workflow_node_label": "Run Tests",
    }


def test_tool_call_payload_from_event_projects_desktop_result_status() -> None:
    failed = tool_call_payload_from_event(
        PublicRunEvent(
            run_id="run-tool-status",
            sequence=1,
            event_type="agent.tool.call",
            detail="media.apple_music_play",
            created_at="2026-06-22T00:00:00Z",
            payload={
                "tool_call_id": "call-music",
                "result": {
                    "ok": False,
                    "permission_error": True,
                    "permission_targets": ["music_app", "automation"],
                    "fallback_used": True,
                },
            },
        )
    )
    waiting = tool_call_payload_from_event(
        PublicRunEvent(
            run_id="run-tool-status",
            sequence=2,
            event_type="agent.tool.call",
            detail="terminal.run",
            created_at="2026-06-22T00:00:01Z",
            payload={
                "tool_call_id": "call-terminal",
                "result": {
                    "ok": False,
                    "approval_required": True,
                    "tool": "terminal.run",
                },
            },
        )
    )

    assert failed["status"] == "failed"
    assert failed["tool_name"] == "media.apple_music_play"
    assert waiting["status"] == "waiting_approval"
    assert waiting["tool_name"] == "terminal.run"


def test_tool_call_status_from_event_type_covers_terminal_approval_aliases() -> None:
    assert tool_status_from_event_type("tool.approval_timeout") == "expired"
    assert tool_status_from_event_type("agent.tool.approval_cancelled") == "cancelled"
    assert tool_status_from_event_type("agent.tool.denied") == "denied"
    assert tool_status_from_event_type("agent.tool.completed") == "completed"


def test_tool_call_snapshots_merge_input_resolution_with_followup_call() -> None:
    calls = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-app-resolution",
                sequence=1,
                event_type="agent.tool.input_resolved",
                detail="app.open",
                created_at="2026-06-27T00:00:00Z",
                payload={
                    "tool": "app.open",
                    "field": "app_name",
                    "requested_app_name": "Apple Music",
                    "resolved_app_name": "Music",
                    "source_tool": "desktop.list_apps",
                },
            ),
            PublicRunEvent(
                run_id="run-app-resolution",
                sequence=2,
                event_type="agent.tool.call",
                detail="app.open",
                created_at="2026-06-27T00:00:01Z",
                payload={
                    "tool": "app.open",
                    "input_preview": {"app_name": "Music"},
                    "result": {"ok": True, "opened": True},
                },
            ),
        ]
    )

    assert len(calls) == 1
    call = calls[0]
    assert call.tool_name == "app.open"
    assert call.status == "completed"
    assert call.input_preview == {
        "app_name": "Music",
        "requested_app_name": "Apple Music",
        "resolved_app_name": "Music",
        "app_resolution_source": "desktop.list_apps",
    }
    assert call.output_preview == {"ok": True, "opened": True}


def test_tool_call_snapshots_merge_resolved_app_with_completed_desktop_steps() -> None:
    calls = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-app-resolution-steps",
                sequence=1,
                event_type="agent.tool.input_resolved",
                detail="app.focus",
                created_at="2026-06-27T00:00:00Z",
                payload={
                    "tool": "app.focus",
                    "field": "app_name",
                    "requested_app_name": "Chrome",
                    "resolved_app_name": "Google Chrome",
                    "source_tool": "desktop.list_apps",
                },
            ),
            PublicRunEvent(
                run_id="run-app-resolution-steps",
                sequence=2,
                event_type="agent.tool.call",
                detail="app.focus",
                created_at="2026-06-27T00:00:01Z",
                payload={
                    "tool": "app.focus",
                    "input_preview": {"app_name": "Google Chrome"},
                    "result": {"ok": True, "data": {"app_name": "Google Chrome"}},
                },
            ),
            PublicRunEvent(
                run_id="run-app-resolution-steps",
                sequence=3,
                event_type="agent.tool.call",
                detail="desktop.ui_elements",
                created_at="2026-06-27T00:00:02Z",
                payload={
                    "tool": "desktop.ui_elements",
                    "input_preview": {"role_filter": "button", "limit": 80},
                    "result": {"ok": True},
                },
            ),
            PublicRunEvent(
                run_id="run-app-resolution-steps",
                sequence=4,
                event_type="agent.desktop.intent_completed",
                detail="desktop.ui_elements",
                created_at="2026-06-27T00:00:03Z",
                payload={
                    "tool": "desktop.ui_elements",
                    "steps": [
                        {
                            "tool": "app.focus",
                            "input_preview": {"app_name": "Google Chrome"},
                            "result": {"ok": True, "data": {"app_name": "Google Chrome"}},
                        },
                        {
                            "tool": "desktop.ui_elements",
                            "input_preview": {"role_filter": "button", "limit": 80},
                            "result": {"ok": True},
                        },
                    ],
                    "result": {"ok": True},
                },
            ),
        ]
    )

    assert [call.tool_name for call in calls] == ["app.focus", "desktop.ui_elements"]
    assert calls[0].input_preview["app_name"] == "Google Chrome"
    assert calls[0].input_preview["requested_app_name"] == "Chrome"
