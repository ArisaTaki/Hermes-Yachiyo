"""GroupRun public snapshot projector regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import GroupRunSnapshot
from apps.shell.yachiyo_agent.group_run_snapshots import (
    group_run_events_with_lifecycle,
    group_run_snapshot_from_payload,
)


def test_group_run_snapshot_module_projects_lifecycle_events() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-direct",
            "group_id": "group-1",
            "title": "Team review",
            "status": "completed",
            "objective": "Compare options",
            "members": [{"agent_id": "agent-1", "name": "Planner"}],
            "child_run_ids": ["run-1"],
            "events": [
                {
                    "event_type": "group.member.completed",
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
        }
    )

    assert group_run.group_run_id == "group-run-direct"
    assert group_run.participants[0].agent_id == "agent-1"
    assert [event.event_type for event in group_run.events] == [
        "group.run.started",
        "group.member.completed",
        "group.run.completed",
    ]
    assert group_run.events[0].payload["participant_count"] == 1
    assert group_run.events[-1].payload["child_run_ids"] == ["run-1"]


def test_group_run_snapshot_returns_existing_public_snapshot() -> None:
    existing = GroupRunSnapshot(
        group_run_id="group-run-existing",
        group_id="group-1",
        title="Existing",
        status="completed",
        objective="Already projected",
    )

    assert group_run_snapshot_from_payload(existing) is existing


def test_group_run_events_with_lifecycle_keeps_source_run_sequence_for_replay() -> None:
    events = group_run_events_with_lifecycle(
        {
            "group_run_id": "group-run-1",
            "status": "running",
            "events": [
                {
                    "event_type": "group.member.completed",
                    "run_id": "child-run-1",
                    "sequence": 9,
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
        },
        group_run_id="group-run-1",
        group_id="group-1",
        objective="Review",
        child_run_ids=[],
    )

    assert events[1]["payload"]["source_run_id"] == "child-run-1"
    assert events[1]["payload"]["source_sequence"] == 9
    assert "sequence" not in events[1]


def test_group_run_snapshot_projects_task_core_progress_from_group_events() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-task-core",
            "group_id": "group-1",
            "title": "Group analysis",
            "status": "completed",
            "objective": "Analyze shared report",
            "events": _completed_task_core_events(),
        }
    )

    event_types = [event.event_type for event in group_run.events]
    assert "group.run.task_core.created" in event_types
    assert "group.run.task.todo.updated" in event_types
    assert "group.run.task.checkpoint.updated" in event_types
    assert group_run.task_core is not None
    assert group_run.task_core.workspace.workspace_id == "task-workspace-1"
    assert group_run.task_core.todos[0].status == "completed"
    assert group_run.task_core.checkpoints[0].status == "completed"
    assert group_run.task_progress is not None
    assert group_run.task_progress.status == "completed"
    assert group_run.task_progress.completed_todos == 1
    assert group_run.task_progress.completed_checkpoints == 1
    assert group_run.runtime_debug is not None
    assert group_run.runtime_debug.needs_replan is False


def test_group_run_snapshot_rolls_up_blocked_foreground_tool_calls() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-lock",
            "group_id": "group-1",
            "title": "Desktop handoff",
            "status": "running",
            "objective": "Coordinate foreground input",
            "members": [
                {"agent_id": "agent-1", "name": "Planner"},
                {"agent_id": "agent-2", "name": "Operator"},
            ],
            "runs": [
                {
                    "run_id": "run-operator",
                    "agent_id": "agent-2",
                    "status": "running",
                    "events": [
                        {
                            "event_type": "agent.tool.call",
                            "detail": "desktop.type_text",
                            "payload": {
                                "tool_call_id": "call-foreground-lock",
                                "member_agent_id": "agent-2",
                                "member_agent_name": "Operator",
                                "result": {
                                    "ok": False,
                                    "action": "foreground_lock",
                                    "foreground_lock_busy": True,
                                    "locked_by": "group-run-lock:run-planner",
                                    "summary": "Foreground control is already held by Planner.",
                                },
                            },
                            "created_at": "2026-06-22T00:00:01Z",
                        }
                    ],
                }
            ],
        }
    )

    assert len(group_run.tool_calls) == 1
    tool_call = group_run.tool_calls[0]
    assert tool_call.run_id == "run-operator"
    assert tool_call.group_run_id == "group-run-lock"
    assert tool_call.source_runnable_id == "agent-2"
    assert tool_call.status == "blocked"
    assert tool_call.output_preview["foreground_lock_busy"] is True
    assert tool_call.output_preview["locked_by"] == "group-run-lock:run-planner"

    operator = next(participant for participant in group_run.participants if participant.agent_id == "agent-2")
    assert len(operator.tool_calls) == 1
    assert operator.tool_calls[0].tool_call_id == "call-foreground-lock"
    assert operator.tool_calls[0].status == "blocked"


def test_group_run_snapshot_rolls_up_child_runtime_provider_and_deferred_events() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-runtime-rollup",
            "group_id": "group-runtime",
            "title": "Desktop group task",
            "status": "running",
            "objective": "Type into an app",
            "members": [{"agent_id": "agent-operator", "name": "Operator"}],
            "runs": [
                {
                    "run_id": "run-operator-runtime",
                    "agent_id": "agent-operator",
                    "status": "running",
                    "runtime_execution_envelope": {
                        "envelope_id": "envelope-child-runtime",
                        "requests": [
                            {
                                "request_id": "request-type",
                                "tool_name": "desktop.safe_type_text",
                            }
                        ],
                        "desktop_provider_session": {
                            "ok": False,
                            "status": "start_failed",
                            "needed": True,
                            "running": False,
                            "provider_id": "isolated-vnc",
                            "reason": "sandbox_desktop_provider_required",
                            "tool_names": ["desktop.safe_type_text"],
                        },
                    },
                    "events": [
                        {
                            "event_type": "agent.deferred_continuation.enqueued",
                            "sequence": 7,
                            "payload": {
                                "deferred_continuation_count": 1,
                                "deferred_tools": ["desktop.safe_type_text"],
                            },
                        }
                    ],
                }
            ],
        }
    )

    provider_event = next(
        event
        for event in group_run.events
        if event.event_type == "desktop.provider_session.failed"
    )
    deferred_event = next(
        event
        for event in group_run.events
        if event.event_type == "group.run.deferred_continuation.enqueued"
    )

    assert provider_event.group_run_id == "group-run-runtime-rollup"
    assert provider_event.payload["source_run_id"] == "run-operator-runtime"
    assert provider_event.payload["desktop_provider_session"]["provider_id"] == "isolated-vnc"
    assert deferred_event.payload["source_sequence"] == 7
    assert deferred_event.payload["group_run_id"] == "group-run-runtime-rollup"
    assert group_run.runtime_debug is not None
    assert group_run.runtime_debug.desktop_provider_session_status == "start_failed"
    assert group_run.runtime_debug.desktop_provider_session_provider_id == "isolated-vnc"
    assert group_run.runtime_debug.deferred_continuation_count == 1
    assert (
        group_run.runtime_debug.latest_deferred_continuation_tool
        == "desktop.safe_type_text"
    )


def _completed_task_core_events() -> list[dict]:
    return [
        {
            "event_type": "agent.task_core.created",
            "payload": {
                "core_id": "task-core-1",
                "task_core": {
                    "core_id": "task-core-1",
                    "workspace": {
                        "workspace_id": "task-workspace-1",
                        "title": "Analysis Workspace",
                    },
                    "todos": [
                        {
                            "todo_id": "todo-analyze",
                            "title": "Analyze data",
                            "step_id": "analyze-data",
                            "tool_name": "data.analyze",
                            "status": "pending",
                        }
                    ],
                    "checkpoints": [
                        {
                            "checkpoint_id": "checkpoint-analyze",
                            "title": "Verify analysis",
                            "after_step_id": "analyze-data",
                            "status": "planned",
                        }
                    ],
                    "replan_signals": [],
                },
            },
        },
        {
            "event_type": "agent.task.todo.updated",
            "payload": {
                "todo_id": "todo-analyze",
                "status": "completed",
                "todo": {
                    "todo_id": "todo-analyze",
                    "title": "Analyze data",
                    "step_id": "analyze-data",
                    "tool_name": "data.analyze",
                    "status": "completed",
                },
            },
        },
        {
            "event_type": "agent.task.checkpoint.updated",
            "payload": {
                "checkpoint_id": "checkpoint-analyze",
                "status": "completed",
                "checkpoint": {
                    "checkpoint_id": "checkpoint-analyze",
                    "title": "Verify analysis",
                    "after_step_id": "analyze-data",
                    "status": "completed",
                },
            },
        },
    ]
