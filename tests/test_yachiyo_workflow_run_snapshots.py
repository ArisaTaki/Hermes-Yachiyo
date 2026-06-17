"""WorkflowRun public snapshot projector regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import WorkflowRunSnapshot
from apps.shell.yachiyo_agent.workflow_run_snapshots import (
    workflow_run_payload_with_lifecycle,
    workflow_run_snapshot_from_payload,
)


def test_workflow_run_snapshot_module_projects_lifecycle_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-direct",
            "kind": "workflow_run",
            "status": "completed",
            "workflow_id": "workflow-1",
            "objective": "Review docs",
            "current_node_id": "done",
            "current_node_label": "Done",
            "created_at": "2026-06-17T00:00:00Z",
            "updated_at": "2026-06-17T00:00:03Z",
        }
    )

    assert workflow_run.workflow_id == "workflow-1"
    assert workflow_run.workflow_run_id == "workflow-run-direct"
    assert workflow_run.current_node_id == "done"
    assert workflow_run.current_node_label == "Done"
    assert [event.event_type for event in workflow_run.events] == [
        "workflow.run.started",
        "workflow.run.completed",
    ]
    assert workflow_run.events[-1].payload["status"] == "completed"


def test_workflow_run_snapshot_returns_existing_public_snapshot() -> None:
    existing = WorkflowRunSnapshot(
        run_id="workflow-run-existing",
        workflow_run_id="workflow-run-existing",
        workflow_id="workflow-1",
        status="completed",
        objective="Already projected",
    )

    assert workflow_run_snapshot_from_payload(existing) is existing


def test_workflow_run_payload_with_lifecycle_does_not_duplicate_aliases() -> None:
    payload = workflow_run_payload_with_lifecycle(
        {
            "run_id": "workflow-run-alias",
            "kind": "workflow_run",
            "status": "succeeded",
            "events": [
                {"event_type": "workflow.started"},
                {"event_type": "workflow.completed"},
            ],
        }
    )

    assert [event["event_type"] for event in payload["events"]] == [
        "workflow.started",
        "workflow.completed",
    ]
