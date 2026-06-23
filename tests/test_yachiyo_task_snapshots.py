"""Chat-facing AgentTask snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import AgentTaskSnapshot
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

    assert task.current_step == "无法执行 · 播放 Apple Music"
    assert task.progress_text == "无法执行 · 播放 Apple Music"


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

    assert task.current_step == "需要权限 · 播放 Apple Music"
    assert task.progress_text == "需要权限 · 播放 Apple Music"


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
