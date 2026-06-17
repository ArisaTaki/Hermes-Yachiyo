"""RunTimeline metadata mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent
from apps.shell.yachiyo_agent.timeline_metadata_snapshots import (
    run_timeline_agent_id_from_payload,
    run_timeline_rerun_provenance_from_payload,
    timeline_child_snapshot_from_payload,
    timeline_child_snapshots_from_payloads,
    workflow_run_id_from_payload,
)


def test_timeline_child_snapshots_preserve_orchestration_context() -> None:
    children = timeline_child_snapshots_from_payloads(
        [
            {
                "run_id": "child-agent",
                "title": "Reviewer",
                "status": "completed",
                "kind": "agent_run",
                "runnable_id": "agent-reviewer",
                "parent_run_id": "parent-run",
                "run_group_id": "group-run-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "review",
                "workflow_node_label": "Review",
                "workflow_id": "workflow-1",
            },
            {
                "run_id": "child-workflow",
                "user_goal": "Nested workflow",
                "status": "running",
                "kind": "workflow_run",
                "runnable_id": "workflow-nested",
            },
            "legacy-child",
        ]
    )

    assert len(children) == 3
    assert children[0].run_id == "child-agent"
    assert children[0].title == "Reviewer"
    assert children[0].parent_run_id == "parent-run"
    assert children[0].group_run_id == "group-run-1"
    assert children[0].run_group_id == "group-run-1"
    assert children[0].workflow_run_id == "workflow-run-1"
    assert children[0].workflow_node_id == "review"
    assert children[0].workflow_node_label == "Review"
    assert children[0].agent_id == "agent-reviewer"
    assert children[0].workflow_id == "workflow-1"
    assert children[1].title == "Nested workflow"
    assert children[1].workflow_id == "workflow-nested"
    assert children[2].run_id == "legacy-child"


def test_timeline_child_snapshot_redacts_sensitive_values() -> None:
    child = timeline_child_snapshot_from_payload(
        {
            "run_id": "child-sk-sensitive-value",
            "title": "token sk-sensitive-value",
            "kind": "agent_run",
            "runnable_id": "agent-sk-sensitive-value",
        }
    )
    rendered = str(child.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "[redacted]" in rendered


def test_rerun_provenance_prefers_direct_payload_values() -> None:
    provenance = run_timeline_rerun_provenance_from_payload(
        {
            "rerun_of_run_id": "original-direct",
            "rerun_of_kind": "agent_run",
            "rerun_of_status": "completed",
            "rerun_of_runnable_id": "agent-direct",
            "rerun_of_runnable_name": "Planner",
            "original_created_at": "2026-06-17T00:00:00Z",
            "original_updated_at": "2026-06-17T00:00:01Z",
        },
        [
            PublicRunEvent(
                run_id="rerun-1",
                event_type="run.rerun.started",
                payload={
                    "rerun_of_run_id": "original-event",
                    "rerun_of_kind": "workflow_run",
                },
            )
        ],
    )

    assert provenance == {
        "rerun_of_run_id": "original-direct",
        "rerun_of_kind": "agent_run",
        "rerun_of_status": "completed",
        "rerun_of_runnable_id": "agent-direct",
        "rerun_of_runnable_name": "Planner",
        "rerun_original_created_at": "2026-06-17T00:00:00Z",
        "rerun_original_updated_at": "2026-06-17T00:00:01Z",
    }


def test_rerun_provenance_falls_back_to_replay_event() -> None:
    provenance = run_timeline_rerun_provenance_from_payload(
        {},
        [
            PublicRunEvent(
                run_id="rerun-1",
                event_type="model.output.completed",
                payload={},
            ),
            PublicRunEvent(
                run_id="rerun-1",
                event_type="run.rerun.started",
                payload={
                    "rerun_of_run_id": "original-run",
                    "rerun_of_kind": "workflow_run",
                    "rerun_of_status": "failed",
                    "rerun_of_runnable_id": "workflow-1",
                    "rerun_of_runnable_name": "Release Workflow",
                    "original_created_at": "2026-06-17T00:00:00Z",
                    "original_updated_at": "2026-06-17T00:00:02Z",
                },
            ),
        ],
    )

    assert provenance["rerun_of_run_id"] == "original-run"
    assert provenance["rerun_of_kind"] == "workflow_run"
    assert provenance["rerun_of_status"] == "failed"
    assert provenance["rerun_of_runnable_id"] == "workflow-1"
    assert provenance["rerun_of_runnable_name"] == "Release Workflow"
    assert provenance["rerun_original_created_at"] == "2026-06-17T00:00:00Z"
    assert provenance["rerun_original_updated_at"] == "2026-06-17T00:00:02Z"


def test_run_timeline_agent_and_workflow_ids_are_derived_from_kind() -> None:
    assert run_timeline_agent_id_from_payload(
        {"kind": "agent_run", "runnable_id": "agent-1"}
    ) == "agent-1"
    assert run_timeline_agent_id_from_payload(
        {"kind": "workflow_run", "runnable_id": "workflow-1"}
    ) == ""
    assert workflow_run_id_from_payload(
        {"kind": "workflow_run"}, "run-workflow"
    ) == "run-workflow"
    assert workflow_run_id_from_payload(
        {"workflow_run_id": "explicit-workflow-run"}, "run-workflow"
    ) == "explicit-workflow-run"
