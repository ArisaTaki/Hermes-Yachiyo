"""Tests for Workflow child approval context projection split out of continuation."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_child_approvals import (
    WorkflowChildPendingApprovalProjection,
)


def test_workflow_child_pending_approval_projection_remains_exported() -> None:
    assert (
        agent_runtime.WorkflowChildPendingApprovalProjection
        is WorkflowChildPendingApprovalProjection
    )


def test_workflow_child_pending_approval_projection_adds_missing_trace_context() -> None:
    child = {
        "run_id": "child-run-1",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-1",
            "tool": "desktop.type_text",
            "input": {"text": "hello"},
        },
    }

    projection = WorkflowChildPendingApprovalProjection.from_child_run(
        child,
        workflow_run_id="workflow-run-1",
        node_info={
            "workflow_node_id": "node-1",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Type in app",
        },
        run_group_id="group-run-1",
    )

    assert projection is not None
    assert projection.child_run_id == "child-run-1"
    assert projection.pending_approval == {
        "approval_id": "approval-1",
        "tool": "desktop.type_text",
        "input": {"text": "hello"},
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "node-1",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Type in app",
        "group_run_id": "group-run-1",
        "run_group_id": "group-run-1",
    }


def test_workflow_child_pending_approval_projection_preserves_existing_context() -> None:
    child = {
        "run_id": "child-run-1",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-1",
            "tool": "desktop.type_text",
            "workflow_run_id": "existing-workflow",
            "workflow_node_id": "existing-node",
        },
    }

    projection = WorkflowChildPendingApprovalProjection.from_child_run(
        child,
        workflow_run_id="workflow-run-1",
        node_info={
            "workflow_node_id": "node-1",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Type in app",
        },
    )

    assert projection is not None
    assert projection.pending_approval["workflow_run_id"] == "existing-workflow"
    assert projection.pending_approval["workflow_node_id"] == "existing-node"
    assert projection.pending_approval["workflow_node_kind"] == "agent"
    assert projection.pending_approval["workflow_node_label"] == "Type in app"


def test_workflow_child_pending_approval_projection_noops_without_pending_approval() -> None:
    assert (
        WorkflowChildPendingApprovalProjection.from_child_run(
            {"run_id": "child-run-1", "status": "completed"},
            workflow_run_id="workflow-run-1",
            node_info={"workflow_node_id": "node-1"},
        )
        is None
    )


def test_workflow_child_pending_approval_projection_project_calls_update_run() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    projection = WorkflowChildPendingApprovalProjection(
        child_run_id="child-run-1",
        pending_approval={"approval_id": "approval-1"},
    )

    result = projection.project(
        lambda run_id, **fields: calls.append((run_id, fields)) or {"run_id": run_id, **fields}
    )

    assert result == {
        "run_id": "child-run-1",
        "pending_approval": {"approval_id": "approval-1"},
    }
    assert calls == [
        ("child-run-1", {"pending_approval": {"approval_id": "approval-1"}})
    ]
