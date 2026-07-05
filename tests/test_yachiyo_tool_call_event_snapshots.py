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
                "source": "runtime_planner",
                "planning_reason": "initial_plan",
                "step_id": "run-tests",
                "capability_id": "terminal.execution",
                "replan_request_id": "replan-1",
                "replan_trigger": "tool_failure",
            },
        )
    )

    assert payload["tool_name"] == "terminal.run"
    assert payload["status"] == "waiting_approval"
    assert payload["approval_id"] == "approval-1"
    assert payload["risk_level"] == "high"
    assert payload["source_runnable_id"] == "agent-1"
    assert payload["source_runnable_name"] == "Planner"
    assert payload["source"] == "runtime_planner"
    assert payload["step_id"] == "run-tests"
    assert payload["capability_id"] == "terminal.execution"
    assert payload["replan_request_id"] == "replan-1"
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
        "source": "runtime_planner",
        "planning_reason": "initial_plan",
        "step_id": "run-tests",
        "capability_id": "terminal.execution",
        "replan_request_id": "replan-1",
        "replan_trigger": "tool_failure",
    }


def test_tool_call_payload_from_event_uses_top_level_run_context() -> None:
    payload = tool_call_payload_from_event(
        PublicRunEvent(
            run_id="run-tool-context",
            sequence=8,
            event_type="tool.requested",
            detail="workspace.read",
            source_run_id="child-run-1",
            source_runnable_id="agent-1",
            source_runnable_name="Planner",
            workflow_id="workflow-1",
            workflow_run_id="workflow-run-1",
            workflow_node_id="read",
            workflow_node_label="Read Files",
            group_id="group-1",
            group_run_id="group-run-1",
            core_id="core-1",
            workspace_id="workspace-1",
            task_id="task-1",
            payload={
                "tool_call_id": "call-2",
                "input_preview": {"path": "README.md"},
            },
        )
    )

    assert payload["source_run_id"] == "child-run-1"
    assert payload["source_runnable_id"] == "agent-1"
    assert payload["source_runnable_name"] == "Planner"
    assert payload["workflow_id"] == "workflow-1"
    assert payload["workflow_run_id"] == "workflow-run-1"
    assert payload["workflow_node_id"] == "read"
    assert payload["workflow_node_label"] == "Read Files"
    assert payload["group_id"] == "group-1"
    assert payload["group_run_id"] == "group-run-1"
    assert payload["core_id"] == "core-1"
    assert payload["workspace_id"] == "workspace-1"
    assert payload["task_id"] == "task-1"
    assert payload["input_preview"]["workflow_run_id"] == "workflow-run-1"
    assert payload["input_preview"]["group_run_id"] == "group-run-1"
    assert payload["input_preview"]["core_id"] == "core-1"
    assert payload["input_preview"]["workspace_id"] == "workspace-1"
    assert payload["input_preview"]["task_id"] == "task-1"


def test_daily_desktop_intent_step_payloads_preserve_top_level_task_core_context() -> None:
    calls = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-desktop-steps",
                sequence=1,
                event_type="agent.desktop.intent_completed",
                detail="open_browser",
                core_id="core-desktop",
                workspace_id="workspace-desktop",
                task_id="task-desktop",
                payload={
                    "steps": [
                        {
                            "tool": "app.open",
                            "input_preview": {"app_name": "Safari"},
                            "result": {"ok": True},
                        }
                    ],
                },
            )
        ]
    )

    assert len(calls) == 1
    assert calls[0].core_id == "core-desktop"
    assert calls[0].workspace_id == "workspace-desktop"
    assert calls[0].task_id == "task-desktop"
    assert calls[0].input_preview["core_id"] == "core-desktop"
    assert calls[0].input_preview["workspace_id"] == "workspace-desktop"
    assert calls[0].input_preview["task_id"] == "task-desktop"


def test_tool_call_snapshots_from_events_preserve_planner_trace_context() -> None:
    calls = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-planner-trace",
                sequence=1,
                event_type="tool.requested",
                detail="workspace.read",
                created_at="2026-06-17T00:00:00Z",
                payload={
                    "tool_call_id": "call-1",
                    "tool": "workspace.read",
                    "input_preview": {"path": "report.csv"},
                    "source": "runtime_planner",
                    "intent_kind": "data_analysis",
                    "step_id": "inspect-data-source",
                    "capability_id": "file.workspace_read",
                    "core_id": "core-1",
                    "workspace_id": "workspace-1",
                    "task_id": "task-1",
                    "replan_request_id": "replan-1",
                    "action_target": {"action": "read", "path": "report.csv"},
                    "observation_evidence": {"source_tool": "workspace.read"},
                    "observation_retry": {
                        "from_tool": "workspace.read",
                        "reason": "content_missing",
                    },
                },
            ),
            PublicRunEvent(
                run_id="run-planner-trace",
                sequence=2,
                event_type="tool.completed",
                detail="workspace.read",
                created_at="2026-06-17T00:00:01Z",
                payload={
                    "tool_call_id": "call-1",
                    "tool": "workspace.read",
                    "input_preview": {"path": "report.csv"},
                    "result": {"ok": True, "content": "date,value"},
                },
            ),
        ]
    )

    assert len(calls) == 1
    assert calls[0].status == "completed"
    assert calls[0].source == "runtime_planner"
    assert calls[0].intent_kind == "data_analysis"
    assert calls[0].step_id == "inspect-data-source"
    assert calls[0].capability_id == "file.workspace_read"
    assert calls[0].core_id == "core-1"
    assert calls[0].workspace_id == "workspace-1"
    assert calls[0].task_id == "task-1"
    assert calls[0].replan_request_id == "replan-1"
    assert calls[0].action_target == {"action": "read", "path": "report.csv"}
    assert calls[0].observation_evidence == {"source_tool": "workspace.read"}
    assert calls[0].observation_retry == {
        "from_tool": "workspace.read",
        "reason": "content_missing",
    }
    assert calls[0].input_preview["path"] == "report.csv"
    assert calls[0].input_preview["core_id"] == "core-1"
    assert calls[0].input_preview["workspace_id"] == "workspace-1"
    assert calls[0].input_preview["task_id"] == "task-1"


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


def test_tool_call_snapshots_project_scoped_desktop_intent_events() -> None:
    calls = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="group-run-desktop",
                sequence=1,
                event_type="group.run.desktop.intent_approval_required",
                detail="desktop.hotkey",
                created_at="2026-06-27T00:00:00Z",
                payload={
                    "tool": "desktop.hotkey",
                    "approval_id": "approval-hotkey",
                    "risk_level": "medium",
                    "policy_reason": "前台快捷键需要确认。",
                    "group_run_id": "group-run-1",
                    "input_preview": {"key": "l", "modifiers": ["command"]},
                },
            ),
            PublicRunEvent(
                run_id="workflow-run-desktop",
                sequence=2,
                event_type="workflow.run.desktop.intent_completed",
                detail="desktop.ui_elements",
                created_at="2026-06-27T00:00:01Z",
                payload={
                    "tool": "desktop.ui_elements",
                    "workflow_run_id": "workflow-run-1",
                    "steps": [
                        {
                            "tool": "app.focus",
                            "input_preview": {"app_name": "Music"},
                            "result": {"ok": True},
                        },
                        {
                            "tool": "desktop.ui_elements",
                            "input_preview": {"limit": 80},
                            "result": {"ok": True, "count": 4},
                        },
                    ],
                    "result": {"ok": True},
                },
            ),
            PublicRunEvent(
                run_id="workflow-run-desktop",
                sequence=3,
                event_type="workflow.run.desktop.intent_unavailable",
                detail="media.apple_music_play",
                created_at="2026-06-27T00:00:02Z",
                payload={
                    "tool": "media.apple_music_play",
                    "workflow_run_id": "workflow-run-1",
                    "reason": "tool_not_allowed",
                    "blocked_by": "agent_tool_policy",
                    "blocked_summary": "这个 Agent 当前没有开启 media.apple_music_play。",
                },
            ),
        ]
    )

    assert [call.tool_name for call in calls] == [
        "desktop.hotkey",
        "app.focus",
        "desktop.ui_elements",
        "media.apple_music_play",
    ]
    assert calls[0].status == "waiting_approval"
    assert calls[0].approval_id == "approval-hotkey"
    assert calls[0].group_run_id == "group-run-1"
    assert calls[1].status == "completed"
    assert calls[1].workflow_run_id == "workflow-run-1"
    assert calls[2].status == "completed"
    assert calls[2].workflow_run_id == "workflow-run-1"
    assert calls[2].output_preview["count"] == 4
    assert calls[3].status == "blocked"
    assert calls[3].output_preview["blocked_by"] == "agent_tool_policy"
