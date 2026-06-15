"""Workflow RunEvent observability tests."""

from __future__ import annotations

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_workflow_run_emits_edge_followed_events(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    workflow = service.create_workflow(
        {
            "name": "Edge Observability",
            "nodes": [
                {"id": "start", "type": "input", "data": {"kind": "start", "label": "Start"}},
                {
                    "id": "artifact",
                    "type": "output",
                    "data": {
                        "kind": "artifact",
                        "label": "Report",
                        "artifact_path": "report.md",
                    },
                },
            ],
            "edges": [{"id": "edge-start-report", "source": "start", "target": "artifact"}],
        }
    )

    run = service.create_workflow_run(
        {
            "workflow_id": workflow["workflow_id"],
            "user_goal": "Write a short report",
        }
    )
    events = service.list_run_events(run["run_id"], limit=50)["events"]
    event_types = [event["event_type"] for event in events]
    edge_events = [
        event
        for event in events
        if event["event_type"] == "workflow.edge.followed"
    ]
    started_events = [
        event for event in events if event["event_type"] == "workflow.node.started"
    ]
    completed_events = [
        event for event in events if event["event_type"] == "workflow.node.completed"
    ]

    assert run["status"] == "completed"
    assert "workflow.completed" in event_types
    assert [event["payload"]["workflow_node_id"] for event in started_events] == [
        "start",
        "artifact",
    ]
    assert [event["payload"]["workflow_node_id"] for event in completed_events] == [
        "start",
        "artifact",
    ]
    assert len(edge_events) == 1
    assert edge_events[0]["payload"]["workflow_edge_source_node_id"] == "start"
    assert edge_events[0]["payload"]["workflow_edge_target_node_id"] == "artifact"
    assert edge_events[0]["payload"]["status"] == "completed"
