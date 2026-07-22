"""Chat-facing AgentTask snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import AgentTaskSnapshot, PlannerTraceSummarySnapshot
from apps.shell.yachiyo_agent.task_snapshots import (
    agent_task_snapshot_from_payload,
    agent_task_snapshots_from_payloads,
    run_events_from_payload,
    task_status_from_value,
)


def _desktop_click_approval_payload(
    *,
    approval_id: str,
    requested_at: str,
    events: list[dict],
) -> dict:
    return {
        "run_id": "run-approval-alias",
        "task_id": "task-approval-alias",
        "status": "approval_required",
        "pending_approvals": [
            {
                "approval_id": approval_id,
                "run_id": "run-approval-alias",
                "status": "pending",
                "tool": "app.focus_and_click_ui_element",
                "plan_id": "plan-approval-alias",
                "step_id": "operate-foreground-ui",
                "requested_at": requested_at,
                "input_preview": {
                    "app_name": "WeChat",
                    "target": "搜索",
                    "role_filter": "text",
                    "click_count": 1,
                    "limit": 80,
                    "approval_required": True,
                    "depends_on": ["inspect-app"],
                    "desktop_execution_policy": {"mode": "provider_required"},
                    "desktop_loop": {"stage": "operate", "role": "click_ui"},
                    "action_target": {
                        "kind": "desktop_app",
                        "action": "click_ui",
                        "app_name": "微信",
                    },
                    "observation_evidence": {"source_tool": "desktop.list_apps"},
                    "observation_retry": {"tool": "desktop.list_apps"},
                    "followup_target": {"kind": "desktop_observed_action"},
                    "target_app_name": "WeChat",
                },
            }
        ],
        "events": events,
    }


def _desktop_click_approval_required_event(*, sequence: int, created_at: str) -> dict:
    return {
        "event_id": f"event-approval-required-{sequence}",
        "sequence": sequence,
        "event_type": "agent.desktop.intent_approval_required",
        "created_at": created_at,
        "payload": {
            "tool": "app.focus_and_click_ui_element",
            "status": "approval_required",
            "summary": "需要批准在 WeChat 中点击搜索。",
            "plan_id": "plan-approval-alias",
            "decision_id": "decision-approval-alias",
            "core_id": "core-approval-alias",
            "workspace_id": "workspace-approval-alias",
            "step_id": "operate-foreground-ui",
            "depends_on": ["inspect-app"],
            "desktop_loop": {"stage": "operate", "role": "click_ui"},
            "input_preview": {
                "app_name": "WeChat",
                "target": "搜索",
                "role_filter": "text",
                "click_count": 1,
                "limit": 80,
                "action_target": {
                    "kind": "desktop_observed_action",
                    "action": "click",
                    "app_name": "WeChat",
                },
                "observation_evidence": {"source_tool": "desktop.ui_elements"},
            },
            "result": {
                "ok": False,
                "approval_required": True,
                "internal_reason": "policy gate",
            },
        },
    }


def _desktop_click_approval_approved_event(*, sequence: int, created_at: str) -> dict:
    return {
        "event_id": f"event-approval-approved-{sequence}",
        "sequence": sequence,
        "event_type": "agent.tool.approval_approved",
        "created_at": created_at,
        "payload": {
            "tool": "app.focus_and_click_ui_element",
            "plan_id": "plan-approval-alias",
            "step_id": "operate-foreground-ui",
            "input_preview": {
                "app_name": "WeChat",
                "target": "搜索",
                "role_filter": "text",
                "click_count": 1,
                "limit": 80,
            },
        },
    }


def test_agent_task_snapshot_merges_real_approval_with_event_alias() -> None:
    task = agent_task_snapshot_from_payload(
        _desktop_click_approval_payload(
            approval_id="approval-real-click",
            requested_at="2026-07-12T00:00:00Z",
            events=[
                _desktop_click_approval_required_event(
                    sequence=1,
                    created_at="2026-07-12T00:00:00Z",
                )
            ],
        )
    )

    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].approval_id == "approval-real-click"
    assert task.pending_approvals[0].input_preview == {
        "app_name": "WeChat",
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }


def test_agent_task_snapshot_sanitizes_private_pending_approval_input() -> None:
    task = agent_task_snapshot_from_payload(
        _desktop_click_approval_payload(
            approval_id="approval-private-click",
            requested_at="2026-07-12T00:00:00Z",
            events=[],
        )
    )

    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].input_preview == {
        "app_name": "WeChat",
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }


def test_agent_task_snapshot_sanitizes_event_alias_approval_input() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "run_id": "run-event-alias",
            "status": "approval_required",
            "events": [
                _desktop_click_approval_required_event(
                    sequence=1,
                    created_at="2026-07-12T00:00:00Z",
                )
            ],
        }
    )

    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].input_preview == {
        "app_name": "WeChat",
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }


def test_agent_task_snapshot_projects_approval_recent_event_through_public_schema() -> None:
    task = agent_task_snapshot_from_payload(
        _desktop_click_approval_payload(
            approval_id="approval-public-click",
            requested_at="2026-07-12T00:00:00Z",
            events=[
                _desktop_click_approval_required_event(
                    sequence=1,
                    created_at="2026-07-12T00:00:00Z",
                )
            ],
        )
    )

    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].input_preview == {
        "app_name": "WeChat",
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }
    assert len(task.recent_events) == 1
    event = task.recent_events[0]
    assert event.event_type == "agent.desktop.intent_approval_required"
    assert event.detail == "需要批准在 WeChat 中点击搜索。"
    assert event.core_id is None
    assert event.workspace_id is None
    assert event.payload == {
        "tool": "app.focus_and_click_ui_element",
        "status": "approval_required",
        "summary": "需要批准在 WeChat 中点击搜索。",
        "input_preview": {
            "app_name": "WeChat",
            "target": "搜索",
            "role_filter": "text",
            "click_count": 1,
            "limit": 80,
        },
    }


def test_agent_task_snapshot_projects_terminal_desktop_event_without_trace() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-open-public",
            "run_id": "run-open-public",
            "status": "completed",
            "events": [
                {
                    "event_id": "event-open-completed",
                    "sequence": 4,
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "app.open",
                    "core_id": "core-open-public",
                    "workspace_id": "workspace-open-public",
                    "payload": {
                        "tool": "app.open",
                        "status": "completed",
                        "summary": "已打开 Calendar。",
                        "plan_id": "plan-open-public",
                        "decision_id": "decision-open-public",
                        "step_id": "open-app",
                        "source": "runtime_planner",
                        "input_preview": {
                            "app_name": "Calendar",
                            "action_target": {"kind": "desktop_app"},
                        },
                        "result": {
                            "ok": True,
                            "data": {
                                "app_name": "Calendar",
                                "bundle_path": "/Applications/Calendar.app",
                            },
                        },
                        "steps": [
                            {
                                "tool": "app.open",
                                "input_preview": {"app_name": "Calendar"},
                                "result": {"ok": True},
                            }
                        ],
                    },
                }
            ],
        }
    )

    assert [tool_call.tool_name for tool_call in task.tool_calls] == ["app.open"]
    assert len(task.recent_events) == 1
    event = task.recent_events[0]
    assert event.event_type == "agent.desktop.intent_completed"
    assert event.detail == "已打开 Calendar。"
    assert event.core_id is None
    assert event.workspace_id is None
    assert event.payload == {
        "tool": "app.open",
        "status": "completed",
        "summary": "已打开 Calendar。",
        "input_preview": {"app_name": "Calendar"},
    }


def test_agent_task_snapshot_hides_unknown_high_risk_recent_event() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-unknown-tool-event",
            "run_id": "run-unknown-tool-event",
            "status": "running",
            "events": [
                {
                    "event_id": "event-unknown-tool-event",
                    "sequence": 1,
                    "event_type": "agent.tool.experimental_observation",
                    "visibility": "user",
                    "sensitivity": "public",
                    "payload": {
                        "tool": "desktop.experimental",
                        "prompt": "private planner prompt",
                        "raw_result": {"screen_text": "private UI content"},
                    },
                }
            ],
        }
    )

    assert task.recent_events == []


def test_agent_task_snapshot_hides_approved_event_alias() -> None:
    task = agent_task_snapshot_from_payload(
        _desktop_click_approval_payload(
            approval_id="approval-real-click",
            requested_at="2026-07-12T00:00:00Z",
            events=[
                _desktop_click_approval_required_event(
                    sequence=1,
                    created_at="2026-07-12T00:00:00Z",
                ),
                _desktop_click_approval_approved_event(
                    sequence=2,
                    created_at="2026-07-12T00:00:01Z",
                ),
            ],
        )
    )

    assert task.pending_approvals == []


def test_agent_task_snapshot_keeps_next_real_approval_after_old_resolution() -> None:
    task = agent_task_snapshot_from_payload(
        _desktop_click_approval_payload(
            approval_id="approval-next-click",
            requested_at="2026-07-12T00:00:02Z",
            events=[
                _desktop_click_approval_required_event(
                    sequence=1,
                    created_at="2026-07-12T00:00:00Z",
                ),
                _desktop_click_approval_approved_event(
                    sequence=2,
                    created_at="2026-07-12T00:00:01Z",
                ),
            ],
        )
    )

    assert len(task.pending_approvals) == 1
    assert task.pending_approvals[0].approval_id == "approval-next-click"


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


def test_agent_task_snapshot_hides_raw_tool_noise_and_internal_runtime_events() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-legacy-internal",
            "run_id": "run-legacy-internal",
            "status": "running",
            "events": [
                {
                    "event_id": "evt-action",
                    "event_type": "agent.tool.call",
                    "payload": {
                        "tool": "app.open",
                        "source": "runtime_planner",
                        "result": {"ok": True},
                    },
                },
                {
                    "event_id": "evt-model-followup",
                    "event_type": "agent.model.followup_context",
                    "payload": {
                        "source": "runtime_planner",
                        "replan_prompt": "INTERNAL MODEL INSTRUCTION",
                    },
                },
                {
                    "event_id": "evt-verifier-satisfied",
                    "event_type": "agent.post_action_verification.satisfied",
                    "payload": {
                        "source": "runtime_native_postcondition_receipt",
                        "tool": "desktop.active_window",
                    },
                },
                {
                    "event_id": "evt-verifier-call",
                    "event_type": "agent.tool.call",
                    "payload": {
                        "source": "runtime_post_action_auto_verify",
                        "runtime_stage": "verify",
                        "tool": "desktop.active_window",
                        "result": {"ok": True},
                    },
                },
                {
                    "event_id": "evt-recovery-observation",
                    "event_type": "agent.tool.call",
                    "payload": {
                        "source": "runtime_replan_recovery",
                        "tool": "desktop.read_ui",
                        "result": {"ok": True, "text": "private foreground text"},
                    },
                },
                {
                    "event_id": "evt-intent",
                    "event_type": "agent.desktop.intent_completed",
                    "payload": {
                        "tool": "app.open",
                        "status": "completed",
                        "summary": "已打开 Notes。",
                    },
                },
            ],
        }
    )

    assert [event.event_id for event in task.recent_events] == ["evt-intent"]
    assert task.recent_events[0].event_type == "agent.desktop.intent_completed"
    assert "INTERNAL MODEL INSTRUCTION" not in task.model_dump_json()
    assert "private foreground text" not in task.model_dump_json()


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
                        "followup_target": {
                            "kind": "desktop_discovered_app_action",
                            "app_query": "messaging",
                            "target_action": "safe_shortcut",
                            "safe_shortcut_action": "new_message",
                            "communication_compose": {
                                "channel": "message",
                                "recipient": "Alice",
                                "send_action": "send",
                            },
                        },
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
        followup_target={
            "kind": "desktop_discovered_app_action",
            "app_query": "messaging",
            "target_action": "safe_shortcut",
            "safe_shortcut_action": "new_message",
            "communication_compose": {
                "channel": "message",
                "recipient": "Alice",
                "send_action": "send",
            },
        },
        step_count=2,
        event_count=2,
    )
    assert task.planner_summary.followup_target["communication_compose"]["recipient"] == "Alice"


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


def test_agent_task_snapshot_derives_progress_from_unverified_desktop_intent() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "running",
            "current_step": "",
            "progress_text": "",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_unverified",
                    "detail": "media.system_control",
                    "payload": {
                        "tool": "media.system_control",
                        "status": "failed",
                        "reason": "desktop_verification_missing",
                        "error": "已发送媒体控制请求，但无法确认播放状态。",
                    },
                }
            ],
        }
    )

    assert task.current_step == "操作效果未能验证 · 控制当前媒体"
    assert task.progress_text == "操作效果未能验证 · 控制当前媒体"
    assert len(task.tool_calls) == 1
    assert task.tool_calls[0].status == "failed"


def test_agent_task_snapshot_preserves_distinct_cross_status_tool_calls() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music",
            "run_id": "run-music",
            "status": "failed",
            "tool_calls": [
                {
                    "tool_call_id": "call-music",
                    "tool_name": "media.music_app_open_and_play",
                    "status": "completed",
                    "input_preview": {"app_name": "Spotify"},
                    "output_preview": {"ok": True},
                },
                {
                    "tool_call_id": "intent-unverified",
                    "tool_name": "media.music_app_open_and_play",
                    "status": "failed",
                    "input_preview": {"app_name": "Spotify"},
                    "output_preview": {
                        "reason": "desktop_verification_missing",
                        "error": "无法确认播放状态",
                    },
                },
            ],
        }
    )

    assert len(task.tool_calls) == 2
    assert [call.tool_name for call in task.tool_calls] == [
        "media.music_app_open_and_play",
        "media.music_app_open_and_play",
    ]
    assert [call.status for call in task.tool_calls] == ["completed", "failed"]
    assert task.tool_calls[0].output_preview["ok"] is True
    assert task.tool_calls[1].output_preview["reason"] == "desktop_verification_missing"


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
                    "detail": "browser.open_url",
                    "payload": {
                        "tool_call_id": "call-direct",
                        "tool": "browser.open_url",
                        "input_preview": {"url": "https://example.com"},
                        "result": {"ok": True, "from_event": True},
                    },
                },
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
    assert task.tool_calls[0].output_preview["from_event"] is True


def test_agent_task_snapshot_keeps_chat_tool_inputs_free_of_trace_context() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-open",
            "run_id": "run-open",
            "status": "completed",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "app.open",
                    "core_id": "core-open",
                    "task_id": "task-open",
                    "payload": {
                        "decision_id": "decision-open",
                        "planner_step_id": "open-or-focus-app",
                        "steps": [
                            {
                                "tool": "app.open",
                                "input_preview": {"app_name": "WeChat"},
                                "result": {"ok": True},
                            }
                        ],
                    },
                }
            ],
        }
    )

    assert len(task.tool_calls) == 1
    assert task.tool_calls[0].tool_name == "app.open"
    assert task.tool_calls[0].core_id == "core-open"
    assert task.tool_calls[0].task_id == "task-open"
    assert task.tool_calls[0].decision_id == "decision-open"
    assert task.tool_calls[0].planner_step_id == "open-or-focus-app"
    assert task.tool_calls[0].input_preview == {"app_name": "WeChat"}


def test_agent_task_snapshot_hides_trailing_verify_from_primary_tool_calls() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-calendar",
            "run_id": "run-calendar",
            "status": "completed",
            "recent_events": [
                {
                    "event_type": "agent.tool.call",
                    "sequence": 1,
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "input_preview": {"app_name": "Calendar"},
                        "result": {"ok": True},
                    },
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 2,
                    "detail": "desktop.verify",
                    "payload": {
                        "tool": "desktop.verify",
                        "input_preview": {"app_name": "Calendar"},
                        "result": {"ok": True},
                    },
                },
                {
                    "event_type": "agent.desktop.intent_completed",
                    "sequence": 3,
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "result": {"ok": True},
                        "steps": [
                            {
                                "tool": "app.open",
                                "input_preview": {
                                    "app_name": "Calendar",
                                    "app_resolution_matched_name": "Calendar",
                                    "app_resolution_matched_name_source": "bundle_name",
                                },
                                "result": {"ok": True},
                            },
                            {
                                "tool": "desktop.verify",
                                "input_preview": {"app_name": "Calendar"},
                                "result": {"ok": True},
                            },
                        ],
                    },
                },
            ],
        }
    )

    assert [tool_call.tool_name for tool_call in task.tool_calls] == ["app.open"]
    assert task.tool_calls[0].input_preview == {"app_name": "Calendar"}
    assert all(
        not (
            event.event_type == "agent.tool.call"
            and event.payload.get("tool") == "desktop.verify"
        )
        for event in task.recent_events
    )


def test_agent_task_snapshot_hides_internal_verify_without_completion_aggregate() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-open-fallback",
            "run_id": "run-open-fallback",
            "status": "completed",
            "recent_events": [
                {
                    "event_type": "agent.tool.call",
                    "sequence": 1,
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "runtime_stage": "operate",
                        "input_preview": {"app_name": "Calendar"},
                        "result": {"ok": True},
                    },
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 2,
                    "detail": "desktop.verify",
                    "payload": {
                        "tool": "desktop.verify",
                        "runtime_stage": "verify",
                        "runtime_role": "verify_result",
                        "input_preview": {"app_name": "Calendar"},
                        "result": {"ok": True},
                    },
                },
            ],
        }
    )

    assert [tool_call.tool_name for tool_call in task.tool_calls] == ["app.open"]


def test_agent_task_snapshot_hides_internal_runtime_recovery_observation() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-music-permission",
            "run_id": "run-music-permission",
            "status": "failed",
            "tool_calls": [
                {
                    "tool_call_id": "call-play",
                    "tool": "media.apple_music_play",
                    "source": "runtime_planner",
                    "status": "failed",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "output_preview": {
                        "ok": False,
                        "permission_error": True,
                        "permission_targets": ["music_app", "automation"],
                    },
                },
                {
                    "tool_call_id": "call-observe-window",
                    "tool": "desktop.active_window",
                    "source": "runtime_replan_recovery",
                    "status": "completed",
                    "input_preview": {"permission_target": "runtime_observation"},
                    "output_preview": {
                        "ok": True,
                        "data": {"app_name": "Music"},
                    },
                },
            ],
            "recent_events": [
                {
                    "event_type": "agent.desktop.permission_recovery",
                    "sequence": 3,
                    "detail": "media.apple_music_play",
                    "payload": {
                        "tool": "media.apple_music_play",
                        "permission_targets": ["music_app", "automation"],
                        "recovery_actions": [
                            {
                                "label": "打开 Apple Music",
                                "tool": "app.open",
                                "input": {"app_name": "Music"},
                                "permission_target": "music_app",
                                "risk_level": "low",
                            }
                        ],
                    },
                }
            ],
        }
    )

    assert [tool_call.tool_name for tool_call in task.tool_calls] == [
        "media.apple_music_play"
    ]
    assert task.tool_calls[0].status == "failed"
    assert task.needs_user_action is True
    assert any(
        event.event_type == "agent.desktop.permission_recovery"
        for event in task.recent_events
    )


def test_failed_approval_resume_permission_event_remains_user_action_without_approval() -> None:
    secret = "sk-task-snapshot-permission-secret-123456789"
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-approval-resume-permission",
            "run_id": "run-approval-resume-permission",
            "status": "failed",
            "pending_approvals": [
                {
                    "approval_id": "stale-consumed-approval",
                    "run_id": "run-approval-resume-permission",
                    "status": "pending",
                    "tool": "terminal.run",
                }
            ],
            "recent_events": [
                {
                    "event_type": "agent.desktop.permission_recovery",
                    "sequence": 4,
                    "detail": "terminal.run",
                    "payload": {
                        "tool": "terminal.run",
                        "tool_call_id": "approved-terminal-permission",
                        "source": "approval_resume",
                        "status": "permission_recovery_available",
                        "permission_error": True,
                        "permission_targets": ["accessibility"],
                        "affected_tools": ["terminal.run"],
                        "recovery_hints": [
                            "Open System Settings",
                            f"api_key={secret}",
                        ],
                        "input_preview": {
                            "command": "printf permission",
                            "api_key": secret,
                        },
                    },
                }
            ],
        }
    )

    assert task.status == "failed"
    assert task.pending_approvals == []
    assert task.needs_user_action is True
    recovery_event = next(
        event
        for event in task.recent_events
        if event.event_type == "agent.desktop.permission_recovery"
    )
    assert recovery_event.payload["status"] == "permission_required"
    assert recovery_event.payload["permission_error"] is True
    assert recovery_event.payload["tool_call_id"] == "approved-terminal-permission"
    assert recovery_event.payload["permission_targets"] == ["accessibility"]
    assert recovery_event.payload["affected_tools"] == ["terminal.run"]
    assert recovery_event.payload["recovery_hints"] == [
        "Open System Settings",
        "api_key=[redacted]",
    ]
    assert "recovery_actions" not in recovery_event.payload
    assert secret not in repr(recovery_event.payload)


def test_non_permission_desktop_event_does_not_expose_permission_fields() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-non-permission-event",
            "run_id": "run-non-permission-event",
            "status": "failed",
            "recent_events": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "sequence": 2,
                    "detail": "app.open",
                    "payload": {
                        "tool": "app.open",
                        "status": "failed",
                        "permission_error": True,
                        "permission_targets": ["must-not-pass"],
                        "affected_tools": ["terminal.run"],
                        "recovery_hints": ["secret diagnostic"],
                        "tool_call_id": "must-not-pass-call",
                        "input_preview": {"app_name": "Music"},
                    },
                }
            ],
        }
    )

    event = next(
        event
        for event in task.recent_events
        if event.event_type == "agent.desktop.intent_completed"
    )
    assert event.payload == {
        "tool": "app.open",
        "status": "failed",
        "input_preview": {"app_name": "Music"},
    }


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
