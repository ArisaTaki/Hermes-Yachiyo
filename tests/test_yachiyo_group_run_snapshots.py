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
