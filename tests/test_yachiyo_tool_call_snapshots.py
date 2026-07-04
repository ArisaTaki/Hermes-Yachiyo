"""ToolCall public snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent, ToolCallSnapshot
from apps.shell.yachiyo_agent.tool_call_snapshots import (
    tool_call_snapshot_from_payload,
    tool_call_snapshots_from_events,
    tool_call_snapshots_from_payloads,
)


def test_tool_call_snapshots_from_events_merge_lifecycle_and_trace_context() -> None:
    events = [
        PublicRunEvent(
            event_id="evt-1",
            run_id="run-tools",
            sequence=1,
            event_type="tool.requested",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "input_preview": {"path": "README.md"},
                "source_runnable_id": "agent-1",
                "source_runnable_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "write",
                "workflow_node_label": "Write README",
                "group_id": "group-1",
                "group_run_id": "group-run-1",
                "task_workspace_items": [
                    {"item_id": "workspace-report", "title": "Analysis report", "path": "analysis.md"}
                ],
                "task_verification_targets": [
                    {
                        "todo_id": "todo-report",
                        "todo_title": "Write report",
                        "workspace_items": [
                            {"item_id": "workspace-report", "path": "analysis.md"}
                        ],
                    }
                ],
                "checkpoint_policy": {
                    "checkpoint_ids": ["checkpoint-write-report"],
                    "replan_on_failure": True,
                    "replan_triggers": ["verification_failed"],
                    "fallback_tools": ["artifact.write"],
                },
                "desktop_loop": {
                    "stage": "operate",
                    "action": "read_ui",
                    "retry_tool": "desktop.ui_elements",
                    "can_auto_retry": True,
                },
            },
            created_at="2026-06-17T00:00:00Z",
        ),
        PublicRunEvent(
            event_id="evt-secret",
            run_id="run-tools",
            sequence=2,
            event_type="tool.completed",
            sensitivity="secret",
            payload={
                "tool_call_id": "call-secret",
                "tool_name": "terminal.run",
                "result": {"content": "secret"},
            },
        ),
        PublicRunEvent(
            event_id="evt-3",
            run_id="run-tools",
            sequence=3,
            event_type="tool.approval_required",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "pending_approval": {
                    "approval_id": "approval-write",
                    "risk_level": "high",
                    "policy_reason": "writes workspace files",
                },
                "input_preview": {"path": "README.md"},
                "group_id": "group-1",
                "group_run_id": "group-run-1",
                "member_agent_id": "agent-1",
                "member_agent_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "write",
                "workflow_node_label": "Write README",
            },
            created_at="2026-06-17T00:00:01Z",
        ),
        PublicRunEvent(
            event_id="evt-4",
            run_id="run-tools",
            sequence=4,
            event_type="tool.completed",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "result": {"ok": True},
            },
            created_at="2026-06-17T00:00:02Z",
        ),
    ]

    snapshots = tool_call_snapshots_from_events(events)

    assert len(snapshots) == 1
    call = snapshots[0]
    assert call.tool_call_id == "call-write"
    assert call.run_id == "run-tools"
    assert call.tool_name == "workspace.write"
    assert call.status == "completed"
    assert call.approval_id == "approval-write"
    assert call.risk_level == "high"
    assert call.source_runnable_id == "agent-1"
    assert call.source_runnable_name == "Planner"
    assert call.workflow_id == "workflow-1"
    assert call.workflow_run_id == "workflow-run-1"
    assert call.workflow_node_id == "write"
    assert call.workflow_node_label == "Write README"
    assert call.group_id == "group-1"
    assert call.group_run_id == "group-run-1"
    assert call.task_workspace_items == [
        {"item_id": "workspace-report", "title": "Analysis report", "path": "analysis.md"}
    ]
    assert call.task_verification_targets == [
        {
            "todo_id": "todo-report",
            "todo_title": "Write report",
            "workspace_items": [
                {"item_id": "workspace-report", "path": "analysis.md"}
            ],
        }
    ]
    assert call.metadata["checkpoint_policy"] == {
        "checkpoint_ids": ["checkpoint-write-report"],
        "replan_on_failure": True,
        "replan_triggers": ["verification_failed"],
        "fallback_tools": ["artifact.write"],
    }
    assert call.metadata["desktop_loop"] == {
        "stage": "operate",
        "action": "read_ui",
        "retry_tool": "desktop.ui_elements",
        "can_auto_retry": True,
    }
    assert call.input_preview == {
        "path": "README.md",
        "approval_id": "approval-write",
        "risk_level": "high",
        "policy_reason": "writes workspace files",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "write",
        "workflow_node_label": "Write README",
    }
    assert call.output_preview == {"ok": True}
    assert call.completed_at == "2026-06-17T00:00:02Z"


def test_tool_call_snapshot_from_payload_redacts_sensitive_previews() -> None:
    direct = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-sk-sensitive-value",
            "run_id": "run-1",
            "tool_name": "terminal.run",
            "input_preview": {
                "command": "printf sk-sensitive-value",
                "api_key": "secret-api-key-value",
                "api_key_configured": True,
            },
            "error": "bearer sensitive-token-value",
        }
    )
    existing = tool_call_snapshot_from_payload(
        ToolCallSnapshot(
            tool_call_id="call-2",
            run_id="run-1",
            tool_name="workspace.read",
            status="completed",
            input_preview={"path": "sk-sensitive-value.md"},
            output_preview={"content": "token sk-sensitive-value"},
        )
    )

    rendered = str({
        "direct": direct.model_dump(mode="json"),
        "existing": existing.model_dump(mode="json"),
    })

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert direct.input_preview["api_key"] == "[redacted]"
    assert direct.input_preview["api_key_configured"] is True
    assert "[redacted]" in rendered


def test_tool_call_snapshot_from_payload_marks_foreground_lock_busy_as_blocked() -> None:
    snapshot = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-foreground-lock",
            "run_id": "run-desktop",
            "tool_name": "desktop.type_text",
            "result": {
                "ok": False,
                "action": "foreground_lock",
                "foreground_lock_busy": True,
                "locked_by": "group-run-1:run-planner",
                "summary": "Foreground control is already held by Planner.",
            },
            "created_at": "2026-06-22T00:00:00Z",
        }
    )

    assert snapshot.status == "blocked"
    assert snapshot.completed_at == "2026-06-22T00:00:00Z"
    assert snapshot.foreground_lock_busy is True
    assert snapshot.foreground_lock_holder == "group-run-1:run-planner"
    assert snapshot.output_preview["foreground_lock_busy"] is True
    assert snapshot.output_preview["locked_by"] == "group-run-1:run-planner"


def test_tool_call_snapshot_from_payload_marks_failed_desktop_result() -> None:
    snapshot = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-music",
            "run_id": "run-desktop",
            "tool_name": "media.apple_music_play",
            "result": {
                "ok": False,
                "action": "media.apple_music_play",
                "permission_error": True,
                "permission_targets": ["music_app", "automation"],
                "recovery_hints": ["Open Music.app and allow Automation."],
                "recovery_actions": [
                    {
                        "label": "打开自动化权限",
                        "tool": "app.open",
                        "input": {"app_name": "自动化权限"},
                        "permission_target": "automation",
                        "risk_level": "low",
                    }
                ],
                "fallback_used": True,
            },
            "created_at": "2026-06-22T00:00:00Z",
        }
    )

    assert snapshot.status == "failed"
    assert snapshot.completed_at == "2026-06-22T00:00:00Z"
    assert snapshot.output_preview["permission_error"] is True
    assert snapshot.output_preview["fallback_used"] is True
    assert snapshot.output_preview["recovery_hints"] == [
        "Open Music.app and allow Automation."
    ]
    assert snapshot.output_preview["recovery_actions"] == [
        {
            "label": "打开自动化权限",
            "tool": "app.open",
            "input": {"app_name": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        }
    ]


def test_tool_call_snapshot_from_payload_marks_approval_result_waiting() -> None:
    snapshot = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-terminal",
            "run_id": "run-approval",
            "tool_name": "terminal.run",
            "result": {
                "ok": False,
                "approval_required": True,
                "tool": "terminal.run",
            },
            "created_at": "2026-06-22T00:00:00Z",
        }
    )

    assert snapshot.status == "waiting_approval"
    assert snapshot.completed_at is None
    assert snapshot.output_preview["approval_required"] is True


def test_tool_call_snapshots_from_events_marks_foreground_lock_busy_as_blocked() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-lock",
                run_id="run-desktop",
                sequence=1,
                event_type="agent.tool.call",
                detail="desktop.type_text",
                payload={
                    "tool_call_id": "call-foreground-lock",
                    "result": {
                        "ok": False,
                        "action": "foreground_lock",
                        "foreground_lock_busy": True,
                        "locked_by": "group-run-1:run-planner",
                        "summary": "Foreground control is already held by Planner.",
                    },
                },
                created_at="2026-06-22T00:00:01Z",
            )
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "desktop.type_text"
    assert snapshots[0].status == "blocked"
    assert snapshots[0].completed_at == "2026-06-22T00:00:01Z"
    assert snapshots[0].foreground_lock_busy is True
    assert snapshots[0].foreground_lock_holder == "group-run-1:run-planner"
    assert snapshots[0].output_preview["foreground_lock_busy"] is True


def test_tool_call_snapshots_from_events_marks_failed_desktop_result() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-music-failed",
                run_id="run-desktop",
                sequence=1,
                event_type="agent.tool.call",
                detail="media.apple_music_play",
                payload={
                    "tool_call_id": "call-music",
                    "result": {
                        "ok": False,
                        "action": "media.apple_music_play",
                        "permission_error": True,
                        "permission_targets": ["music_app", "automation"],
                        "fallback_used": True,
                    },
                },
                created_at="2026-06-22T00:00:01Z",
            )
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "media.apple_music_play"
    assert snapshots[0].status == "failed"
    assert snapshots[0].completed_at == "2026-06-22T00:00:01Z"
    assert snapshots[0].output_preview["permission_error"] is True


def test_tool_call_snapshots_from_events_projects_daily_desktop_intent_completion() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-tool-call",
                run_id="run-daily-desktop",
                sequence=1,
                event_type="agent.tool.call",
                detail="desktop.windows",
                payload={
                    "tool": "desktop.windows",
                    "input_preview": {"app_name": "Google Chrome"},
                    "result": {
                        "ok": True,
                        "action": "desktop.windows",
                        "data": {
                            "count": 1,
                            "windows": [
                                {
                                    "app_name": "Google Chrome",
                                    "title": "ChatGPT",
                                    "frontmost": True,
                                }
                            ],
                        },
                    },
                },
                created_at="2026-06-22T00:00:01Z",
            ),
            PublicRunEvent(
                event_id="evt-intent-completed",
                run_id="run-daily-desktop",
                sequence=2,
                event_type="agent.desktop.intent_completed",
                detail="desktop.windows",
                payload={
                    "tool": "desktop.windows",
                    "source": "daily_desktop_intent",
                    "input_preview": {"app_name": "Google Chrome"},
                    "result": {
                        "ok": True,
                        "action": "desktop.windows",
                        "data": {
                            "count": 1,
                            "windows": [
                                {
                                    "app_name": "Google Chrome",
                                    "title": "ChatGPT",
                                    "frontmost": True,
                                }
                            ],
                        },
                    },
                    "summary": "当前窗口：Google Chrome: ChatGPT。",
                },
                created_at="2026-06-22T00:00:02Z",
            ),
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "desktop.windows"
    assert snapshots[0].status == "completed"
    assert snapshots[0].input_preview == {"app_name": "Google Chrome"}
    assert snapshots[0].output_preview["action"] == "desktop.windows"
    assert snapshots[0].output_preview["data"]["count"] == 1
    assert snapshots[0].completed_at == "2026-06-22T00:00:02Z"


def test_tool_call_snapshots_preserve_observed_desktop_action_metadata() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-observed-click",
                run_id="run-observed-desktop",
                sequence=1,
                event_type="agent.desktop.intent_completed",
                detail="desktop.click",
                payload={
                    "tool": "desktop.click",
                    "source": "runtime_planner",
                    "planning_reason": "planner_followup_desktop_observed_action",
                    "capability_id": "desktop.ui_operation",
                    "input_preview": {"x": 120, "y": 240, "click_count": 1},
                    "result": {"ok": True, "summary": "Clicked observed target"},
                    "followup_target": {
                        "kind": "desktop_observed_action",
                        "target_action": "click",
                        "target": "登录",
                    },
                    "action_target": {
                        "kind": "desktop_observed_action",
                        "action": "click",
                        "target": "登录",
                        "role_filter": "button",
                    },
                    "observation_evidence": {
                        "source_tool": "desktop.read_ui",
                        "strategy": "observed_center",
                        "center": {"x": 120, "y": 240},
                    },
                },
                created_at="2026-06-22T00:00:03Z",
            )
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "desktop.click"
    assert snapshots[0].capability_id == "desktop.ui_operation"
    assert snapshots[0].metadata["action_target"] == {
        "kind": "desktop_observed_action",
        "action": "click",
        "target": "登录",
        "role_filter": "button",
    }
    assert snapshots[0].metadata["observation_evidence"] == {
        "source_tool": "desktop.read_ui",
        "strategy": "observed_center",
        "center": {"x": 120, "y": 240},
    }


def test_tool_call_snapshots_from_events_projects_daily_desktop_intent_sequence_steps() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-intent-completed",
                run_id="run-daily-sequence",
                sequence=5,
                event_type="agent.desktop.intent_completed",
                detail="desktop.ui_elements",
                payload={
                    "tool": "desktop.ui_elements",
                    "tools": ["app.open", "desktop.ui_elements"],
                    "source": "daily_desktop_intent",
                    "input_preview": {"role_filter": "button", "limit": 80},
                    "result": {
                        "ok": True,
                        "action": "desktop.ui_elements",
                        "data": {"count": 2},
                    },
                    "steps": [
                        {
                            "tool": "app.open",
                            "input_preview": {"app_name": "WeChat"},
                            "result": {
                                "ok": True,
                                "action": "app.open",
                                "summary": "已打开 WeChat。",
                            },
                            "summary": "已打开 WeChat。",
                        },
                        {
                            "tool": "desktop.ui_elements",
                            "input_preview": {"role_filter": "button", "limit": 80},
                            "result": {
                                "ok": True,
                                "action": "desktop.ui_elements",
                                "data": {"count": 2},
                            },
                            "summary": "当前 WeChat 界面控件：2 个。",
                        },
                    ],
                    "summary": "已打开 WeChat。 当前 WeChat 界面控件：2 个。",
                },
                created_at="2026-06-22T00:00:05Z",
            ),
        ]
    )

    assert [snapshot.tool_name for snapshot in snapshots] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert [snapshot.status for snapshot in snapshots] == ["completed", "completed"]
    assert snapshots[0].input_preview == {"app_name": "WeChat"}
    assert snapshots[0].output_preview["action"] == "app.open"
    assert snapshots[1].input_preview == {"role_filter": "button", "limit": 80}
    assert snapshots[1].output_preview["data"]["count"] == 2
    assert snapshots[1].completed_at == "2026-06-22T00:00:05Z"


def test_tool_call_snapshots_from_events_merges_redacted_daily_desktop_step_inputs() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-tool-call",
                run_id="run-daily-sequence",
                sequence=1,
                event_type="agent.tool.call",
                detail="desktop.ui_elements",
                payload={
                    "tool": "desktop.ui_elements",
                    "input_preview": {"role_filter": "button", "limit": 80},
                    "result": {
                        "ok": True,
                        "action": "desktop.ui_elements",
                        "data": {"count": 2},
                    },
                },
                created_at="2026-06-22T00:00:04Z",
            ),
            PublicRunEvent(
                event_id="evt-intent-completed",
                run_id="run-daily-sequence",
                sequence=2,
                event_type="agent.desktop.intent_completed",
                detail="desktop.ui_elements",
                payload={
                    "tool": "desktop.ui_elements",
                    "tools": ["desktop.ui_elements"],
                    "source": "daily_desktop_intent",
                    "steps": [
                        {
                            "tool": "desktop.ui_elements",
                            "input_preview": {"role_filter": "button", "limit": "80"},
                            "result": {
                                "ok": "True",
                                "action": "desktop.ui_elements",
                                "data": "{'count': 2}",
                            },
                        },
                    ],
                },
                created_at="2026-06-22T00:00:05Z",
            ),
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "desktop.ui_elements"
    assert snapshots[0].input_preview == {"role_filter": "button", "limit": 80}
    assert snapshots[0].completed_at == "2026-06-22T00:00:05Z"


def test_tool_call_snapshots_from_events_projects_daily_desktop_intent_boundaries() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-intent-approval",
                run_id="run-daily-desktop",
                sequence=1,
                event_type="agent.desktop.intent_approval_required",
                detail="desktop.hotkey",
                payload={
                    "tool": "desktop.hotkey",
                    "status": "approval_required",
                    "source": "daily_desktop_intent",
                    "reason": "tool_policy_requires_approval",
                    "approval_id": "approval-hotkey",
                    "risk_level": "medium",
                    "policy_reason": "前台快捷键需要确认。",
                    "input_preview": {"key": "l", "modifiers": ["command"]},
                },
                created_at="2026-06-22T00:00:01Z",
            ),
            PublicRunEvent(
                event_id="evt-intent-unavailable",
                run_id="run-daily-desktop",
                sequence=2,
                event_type="agent.desktop.intent_unavailable",
                detail="media.apple_music_play",
                payload={
                    "tool": "media.apple_music_play",
                    "status": "unavailable",
                    "source": "daily_desktop_intent",
                    "reason": "tool_not_allowed",
                    "blocked_by": "agent_tool_policy",
                    "blocked_summary": "这个 Agent 当前没有开启 media.apple_music_play。",
                    "input_preview": {"query": "超时空辉夜姬"},
                },
                created_at="2026-06-22T00:00:02Z",
            ),
        ]
    )

    assert len(snapshots) == 2
    assert snapshots[0].tool_name == "desktop.hotkey"
    assert snapshots[0].status == "waiting_approval"
    assert snapshots[0].approval_id == "approval-hotkey"
    assert snapshots[0].risk_level == "medium"
    assert snapshots[0].completed_at is None
    assert snapshots[1].tool_name == "media.apple_music_play"
    assert snapshots[1].status == "blocked"
    assert snapshots[1].completed_at == "2026-06-22T00:00:02Z"
    assert snapshots[1].output_preview["blocked_by"] == "agent_tool_policy"


def test_tool_call_snapshots_from_payloads_prefers_payload_list_over_event_fallback() -> None:
    snapshots = tool_call_snapshots_from_payloads(
        [
            {
                "id": "payload-call",
                "tool": "workspace.read",
                "input": {"path": "README.md"},
                "output": {"ok": True},
            }
        ],
        run_id="run-payload",
        events=[
            PublicRunEvent(
                run_id="run-events",
                sequence=1,
                event_type="tool.completed",
                payload={"tool_call_id": "event-call", "tool_name": "terminal.run"},
            )
        ],
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_call_id == "payload-call"
    assert snapshots[0].run_id == "run-payload"
    assert snapshots[0].tool_name == "workspace.read"
    assert snapshots[0].input_preview == {"path": "README.md"}
    assert snapshots[0].output_preview == {"ok": True}
