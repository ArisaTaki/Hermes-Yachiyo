"""Chat-facing AgentTask snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import AgentTaskSnapshot, PlannerTraceSummarySnapshot
from apps.shell.yachiyo_agent.task_snapshots import (
    agent_task_snapshot_from_payload,
    agent_task_snapshots_from_payloads,
    run_events_from_payload,
    task_status_from_value,
)


def test_agent_task_snapshot_uses_chat_visible_events_and_public_cards() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "run_id": "run-task",
            "session_id": "session-1",
            "title": "Write report",
            "status": "approval_required",
            "current_step": "Waiting for approval",
            "run_group_id": "group-run-1",
            "events": [
                {
                    "event_id": "evt-approval",
                    "event_type": "tool.approval_required",
                    "payload": {
                        "approval_id": "approval-1",
                        "tool": "workspace.write",
                        "input_preview": {"path": "report.md"},
                    },
                    "created_at": "2026-06-17T00:00:00Z",
                },
                {
                    "event_id": "evt-artifact",
                    "event_type": "artifact.created",
                    "payload": {
                        "path": "report.md",
                        "kind": "markdown",
                        "source_tool": "artifact.write",
                    },
                    "created_at": "2026-06-17T00:00:01Z",
                },
                {
                    "event_id": "evt-internal",
                    "event_type": "tool.completed",
                    "visibility": "internal",
                    "payload": {"tool": "workspace.read"},
                },
                {
                    "event_id": "evt-secret",
                    "event_type": "artifact.created",
                    "sensitivity": "secret",
                    "payload": {"path": "secret.md"},
                },
            ],
        }
    )

    assert task.task_id == "run-task"
    assert task.conversation_id == "session-1"
    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.open_in_studio_url == "#/agents?run_id=run-task&group_run=group-run-1"
    assert [event.event_id for event in task.recent_events] == ["evt-approval", "evt-artifact"]
    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].approval_id == "approval-1"
    assert task.pending_approvals[0].tool_name == "workspace.write"
    assert len(task.artifacts) == 1
    assert task.artifacts[0].path == "report.md"
    assert task.artifacts[0].source_tool == "artifact.write"


def test_agent_task_snapshot_prefers_explicit_open_in_studio_url() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "completed",
            "open_in_studio_url": "#/agents?run_id=custom",
        }
    )

    assert task.open_in_studio_url == "#/agents?run_id=custom"


def test_agent_task_snapshot_projects_planner_summary_from_visible_events() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-report",
            "run_id": "run-report",
            "status": "running",
            "events": [
                {
                    "event_type": "agent.plan.created",
                    "payload": {
                        "source": "runtime_planner",
                        "decision_id": "decision-report",
                        "plan": {
                            "plan_id": "plan-report",
                            "intent": {
                                "intent_id": "intent-report",
                                "kind": "data_analysis",
                                "title": "Analyze data",
                                "required_capabilities": ["data.analysis"],
                            },
                            "capabilities": [
                                {"capability_id": "file.read"},
                                {"capability_id": "artifact.output"},
                            ],
                            "tool_plan": {
                                "steps": [
                                    {
                                        "step_id": "read-data",
                                        "capability_id": "file.read",
                                        "tool_name": "workspace.read",
                                    },
                                    {
                                        "step_id": "analyze-data",
                                        "capability_id": "data.analysis",
                                        "tool_name": "python.pandas",
                                    },
                                ],
                                "artifacts_expected": ["markdown_report", "chart"],
                            },
                        },
                    },
                },
                {
                    "event_type": "agent.plan.selection",
                    "payload": {
                        "source": "runtime_planner",
                        "selection_source": "runtime_planner",
                        "selection_role": "runtime_planner_primary",
                        "selection_reason": "capability_plan",
                        "planner_entrypoint": "bubble_default",
                        "entrypoint_source": "bubble",
                        "plan_tools": ["workspace.read", "python.pandas"],
                        "plan_capabilities": [
                            "file.read",
                            "artifact.output",
                            "data.analysis",
                        ],
                        "required_capabilities": ["data.analysis"],
                        "artifacts_expected": ["markdown_report", "chart"],
                        "selected_tools": ["workspace.read", "python.pandas"],
                        "plan_step_count": 2,
                    },
                },
            ],
        }
    )

    assert task.planner_summary == PlannerTraceSummarySnapshot(
        source="runtime_planner",
        decision_id="decision-report",
        plan_id="plan-report",
        intent_kind="data_analysis",
        intent_title="Analyze data",
        selection_source="runtime_planner",
        selection_role="runtime_planner_primary",
        selection_reason="capability_plan",
        planner_entrypoint="bubble_default",
        entrypoint_source="bubble",
        plan_tools=["workspace.read", "python.pandas"],
        selected_tools=["workspace.read", "python.pandas"],
        plan_capabilities=["file.read", "artifact.output", "data.analysis"],
        required_capabilities=["data.analysis"],
        artifacts_expected=["markdown_report", "chart"],
        step_count=2,
        event_count=2,
    )


def test_agent_task_snapshot_derives_progress_from_planned_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_planned",
                    "detail": "media.apple_music_play",
                    "payload": {"tool": "media.apple_music_play"},
                }
            ],
        }
    )

    assert task.current_step == "准备执行 · 播放 Apple Music"
    assert task.progress_text == "准备执行 · 播放 Apple Music"


def test_agent_task_snapshot_derives_progress_from_unavailable_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_unavailable",
                    "detail": "media.apple_music_play",
                    "payload": {
                        "tool": "media.apple_music_play",
                        "reason": "tool_not_allowed",
                    },
                }
            ],
        }
    )

    assert task.current_step == "无法执行 · 播放 Apple Music · 工具未开启"
    assert task.progress_text == "无法执行 · 播放 Apple Music · 工具未开启"


def test_agent_task_snapshot_derives_progress_from_approval_required_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-hotkey",
            "run_id": "run-hotkey",
            "status": "approval_required",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_approval_required",
                    "detail": "desktop.hotkey",
                    "payload": {
                        "tool": "desktop.hotkey",
                        "status": "approval_required",
                        "input_preview": {"key": "l", "modifiers": ["command"]},
                    },
                }
            ],
        }
    )

    assert task.current_step == "等待批准 · 发送快捷键"
    assert task.progress_text == "等待批准 · 发送快捷键"


def test_agent_task_snapshot_derives_progress_from_completed_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "media.apple_music_play",
                    "payload": {
                        "tool": "media.apple_music_play",
                        "result": {"ok": True},
                    },
                }
            ],
        }
    )

    assert task.current_step == "已执行 · 播放 Apple Music"
    assert task.progress_text == "已执行 · 播放 Apple Music"
    assert len(task.tool_calls) == 1
    assert task.tool_calls[0].tool_name == "media.apple_music_play"
    assert task.tool_calls[0].status == "completed"
    assert task.tool_calls[0].output_preview == {"ok": True}


def test_agent_task_snapshot_prefers_direct_tool_calls_over_event_fallback() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-browser",
            "run_id": "run-browser",
            "status": "running",
            "tool_calls": [
                {
                    "tool_call_id": "call-direct",
                    "tool_name": "browser.open_url",
                    "status": "completed",
                    "input_preview": {"url": "https://example.com"},
                    "output_preview": {"ok": True},
                }
            ],
            "timeline": [
                {
                    "event_type": "agent.tool.call",
                    "detail": "desktop.windows",
                    "payload": {"tool": "desktop.windows", "result": {"ok": True}},
                }
            ],
        }
    )

    assert len(task.tool_calls) == 1
    assert task.tool_calls[0].tool_call_id == "call-direct"
    assert task.tool_calls[0].tool_name == "browser.open_url"
    assert task.tool_calls[0].input_preview == {"url": "https://example.com"}


def test_agent_task_snapshot_derives_progress_from_permission_blocked_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "media.apple_music_play",
                    "payload": {
                        "tool": "media.apple_music_play",
                        "result": {
                            "ok": False,
                            "permission_error": True,
                            "permission_targets": ["music_app", "automation"],
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "需要权限 · 播放 Apple Music · music_app, automation"
    assert task.progress_text == "需要权限 · 播放 Apple Music · music_app, automation"
    assert task.needs_user_action is True


def test_agent_task_snapshot_marks_recovery_actions_as_user_action() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-app-not-found",
            "run_id": "run-app-not-found",
            "status": "completed",
            "timeline": [
                {
                    "event_type": "agent.desktop.permission_recovery",
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "permission_targets": [],
                        "recovery_actions": [
                            {
                                "label": "打开应用程序文件夹",
                                "tool": "desktop.open_path",
                                "input": {"path": "/Applications"},
                                "permission_target": "app_not_found",
                                "risk_level": "low",
                            }
                        ],
                    },
                }
            ],
        }
    )

    assert task.status == "completed"
    assert task.needs_user_action is True


def test_agent_task_snapshot_derives_progress_from_app_not_found_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-app",
            "run_id": "run-app",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "result": {
                            "ok": False,
                            "error": "Application not found.",
                            "error_code": "app_not_found",
                            "recovery_hints": ["确认应用已安装，或换用精确应用名。"],
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "应用未找到 · 打开应用"
    assert task.progress_text == "应用未找到 · 打开应用"


def test_agent_task_snapshot_derives_progress_from_browser_open_fallback() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-browser",
            "run_id": "run-browser",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "browser.open_url",
                    "payload": {
                        "tool": "browser.open_url",
                        "result": {
                            "ok": True,
                            "fallback_used": True,
                            "fallback": "system_browser",
                            "data": {"url": "https://example.com"},
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "已回退执行 · 打开网页 · 系统浏览器"
    assert task.progress_text == "已回退执行 · 打开网页 · 系统浏览器"


def test_agent_task_snapshot_derives_progress_from_approved_desktop_tool_call() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-hotkey",
            "run_id": "run-hotkey",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.tool.call",
                    "detail": "desktop.hotkey",
                    "payload": {
                        "tool": "desktop.hotkey",
                        "approved": True,
                        "result": {
                            "ok": True,
                            "action": "desktop.hotkey",
                            "data": {"key": "l", "modifiers": ["command"]},
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "已执行 · 发送快捷键"
    assert task.progress_text == "已执行 · 发送快捷键"


def test_agent_task_snapshot_derives_permission_progress_from_desktop_tool_call() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-type",
            "run_id": "run-type",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.tool.call",
                    "detail": "desktop.type_text",
                    "payload": {
                        "tool": "desktop.type_text",
                        "result": {
                            "ok": False,
                            "permission_error": True,
                            "permission_targets": ["accessibility"],
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "需要权限 · 输入前台文字 · accessibility"
    assert task.progress_text == "需要权限 · 输入前台文字 · accessibility"


def test_agent_task_snapshot_derives_foreground_lock_progress_from_desktop_tool_call() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-click",
            "run_id": "run-click",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.tool.call",
                    "detail": "desktop.click",
                    "payload": {
                        "tool": "desktop.click",
                        "result": {
                            "ok": False,
                            "foreground_lock_busy": True,
                            "locked_by": "run-other",
                        },
                    },
                }
            ],
        }
    )

    assert task.current_step == "前台被占用 · 点击前台界面 · run-other"
    assert task.progress_text == "前台被占用 · 点击前台界面 · run-other"


def test_agent_task_snapshot_preserves_explicit_progress_over_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "Reading workspace",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_planned",
                    "detail": "media.apple_music_play",
                    "payload": {"tool": "media.apple_music_play"},
                }
            ],
        }
    )

    assert task.current_step == "Reading workspace"
    assert task.progress_text is None


def test_agent_task_snapshot_does_not_derive_desktop_progress_for_completed_task() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "completed",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_planned",
                    "detail": "media.apple_music_play",
                    "payload": {"tool": "media.apple_music_play"},
                }
            ],
        }
    )

    assert task.current_step is None
    assert task.progress_text is None


def test_agent_task_snapshot_passthrough_and_payload_list_guard() -> None:
    existing = AgentTaskSnapshot(
        task_id="task-existing",
        title="Existing",
        status="completed",
    )

    assert agent_task_snapshot_from_payload(existing) is existing
    assert agent_task_snapshots_from_payloads("not-a-list") == []
    assert [task.task_id for task in agent_task_snapshots_from_payloads([existing])] == [
        "task-existing"
    ]


def test_run_events_from_payload_uses_first_non_empty_event_key() -> None:
    events = run_events_from_payload(
        {
            "recent_events": [],
            "events": [
                {
                    "event_type": "task.started",
                    "payload": {"ok": True},
                }
            ],
            "timeline": [{"event": "task.completed"}],
        },
        run_id="run-events",
        keys=("recent_events", "events", "timeline"),
    )

    assert len(events) == 1
    assert events[0].run_id == "run-events"
    assert events[0].sequence == 1
    assert events[0].event_type == "task.started"


def test_task_status_from_value_normalizes_legacy_statuses() -> None:
    assert task_status_from_value("approval_required") == "waiting_approval"
    assert task_status_from_value("pending_approval") == "waiting_approval"
    assert task_status_from_value("processing") == "running"
    assert task_status_from_value("success") == "completed"
    assert task_status_from_value("succeeded") == "completed"
    assert task_status_from_value("done") == "completed"
    assert task_status_from_value("error") == "failed"
    assert task_status_from_value("canceled") == "cancelled"
    assert task_status_from_value("unknown") == "running"
