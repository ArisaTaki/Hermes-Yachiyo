"""Tests for workflow approval projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)


def test_workflow_approval_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowApprovalTransitionContext is WorkflowApprovalTransitionContext
    assert agent_runtime.WorkflowApprovalResumeContext is WorkflowApprovalResumeContext
    assert agent_runtime.WorkflowApprovalResumeCoordinator is WorkflowApprovalResumeCoordinator
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
