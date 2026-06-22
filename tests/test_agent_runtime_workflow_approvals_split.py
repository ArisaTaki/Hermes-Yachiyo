"""Tests for workflow approval projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseCoordinator,
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)


def test_workflow_approval_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowApprovalTransitionContext is WorkflowApprovalTransitionContext
    assert agent_runtime.WorkflowApprovalResumeContext is WorkflowApprovalResumeContext
    assert agent_runtime.WorkflowApprovalResumeCoordinator is WorkflowApprovalResumeCoordinator
    assert agent_runtime.WorkflowApprovalPauseCoordinator is WorkflowApprovalPauseCoordinator
    assert agent_runtime.WorkflowApprovalPauseProjection is WorkflowApprovalPauseProjection


def test_workflow_approval_pause_projection_accepts_prepared_criteria() -> None:
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="  Review output  ",
        context="Draft ready",
        next_index=3,
        next_node_id="report",
    )

    pending = projection.pending_approval()
    assert pending["approval_id"].startswith("approval_")
    assert pending["workflow_node_id"] == "gate"
    assert pending["workflow_node_approval_criteria"] == "Review output"
    assert pending["workflow_next_index"] == 3
    assert pending["workflow_next_node_id"] == "report"
    assert projection.event_payload()["pending_approval"] == projection.public_pending_approval()


def test_workflow_approval_pause_coordinator_applies_projection_side_effects() -> None:
    timeline_events: list[dict[str, object]] = []
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    run_updates: list[tuple[str, dict[str, object]]] = []
    group_updates: list[tuple[str, dict[str, object]]] = []
    get_calls: list[str] = []
    coordinator = WorkflowApprovalPauseCoordinator(
        timeline_factory=lambda event, detail="", **payload: timeline_events.append(
            {"event": event, "detail": detail, **payload}
        )
        or timeline_events[-1],
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=lambda run_id, **fields: run_updates.append((run_id, fields))
        or {"run_id": run_id, "run_group_id": "run_group", **fields},
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda run_id: get_calls.append(run_id)
        or {"run_id": run_id, "refetched": True, **run_updates[-1][1]},
    )
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="Review output",
        context="Draft ready",
        next_index=2,
        next_node_id="report",
    )
    timeline: list[dict[str, object]] = []
    artifacts = [{"kind": "workflow_artifact", "path": "draft.md"}]

    result = coordinator.pause(
        {"run_id": "workflow_run"},
        projection,
        run_group_id="run_group",
        timeline=timeline,
        artifacts=artifacts,
        root_group=True,
    )

    assert result["refetched"] is True
    assert result["status"] == "approval_required"
    assert timeline == timeline_events
    assert appended_events == [
        (
            "workflow_run",
            "workflow.node.approval_required",
            projection.event_payload(),
        )
    ]
    assert run_updates[-1][0] == "workflow_run"
    assert run_updates[-1][1]["status"] == "approval_required"
    assert run_updates[-1][1]["artifacts"] is artifacts
    assert run_updates[-1][1]["pending_approval"]["workflow_context"] == "Draft ready"
    assert group_updates == [
        (
            "run_group",
            {"status": "approval_required", "summary": "等待审批：Human Gate"},
        )
    ]
    assert get_calls == ["workflow_run"]
