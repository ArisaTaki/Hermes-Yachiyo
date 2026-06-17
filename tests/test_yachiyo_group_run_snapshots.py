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
