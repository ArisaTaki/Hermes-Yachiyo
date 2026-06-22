"""Tests for pure Workflow continuation state helpers."""

from __future__ import annotations

from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator
from apps.shell.agent.runtime.workflow_state import (
    parallel_completed_agent_context,
    parallel_completed_artifact_exists,
    parallel_node_resume_context,
    workflow_context_chars,
    workflow_path_index,
    workflow_steps_used,
)


def test_workflow_state_counts_executable_node_steps_without_rejected_approvals() -> None:
    timeline = [
        {"event": "workflow.node.start"},
        {"event": "workflow.edge.followed"},
        {"event": "workflow.node.approval_rejected"},
        {"event": "workflow.node.approval_timeout"},
        {"event": "workflow.node.agent"},
    ]

    assert workflow_steps_used(timeline) == 2
    assert WorkflowContinuationCoordinator._workflow_steps_used(timeline) == 2


def test_workflow_state_preserves_context_budget_and_path_index_compatibility() -> None:
    path = [{"id": "start"}, {"id": "review"}]

    assert workflow_context_chars("hello") == WorkflowContinuationCoordinator._workflow_context_chars(
        "hello"
    )
    assert workflow_path_index(path, "review") == 1
    assert WorkflowContinuationCoordinator._path_index(path, "missing") == 2


def test_workflow_state_recovers_parallel_resume_context_and_completed_children() -> None:
    timeline = [
        {
            "event": "workflow.node.agent",
            "workflow_parent_node_id": "parallel-1",
            "workflow_parent_node_context": "original context",
            "workflow_node_id": "branch-agent",
            "workflow_node_context": "agent result",
            "status": "completed",
        },
        {
            "event": "workflow.node.artifact",
            "workflow_parent_node_id": "parallel-1",
            "workflow_node_id": "branch-artifact",
            "status": "completed",
        },
    ]

    assert parallel_node_resume_context(
        timeline,
        parallel_node_id="parallel-1",
        fallback="fallback",
    ) == "original context"
    assert WorkflowContinuationCoordinator._parallel_node_resume_context(
        timeline,
        parallel_node_id="parallel-unknown",
        fallback="fallback",
    ) == "fallback"
    assert parallel_completed_agent_context(
        timeline,
        parallel_node_id="parallel-1",
        branch_node_id="branch-agent",
    ) == "agent result"
    assert WorkflowContinuationCoordinator._parallel_completed_agent_context(
        timeline,
        parallel_node_id="parallel-1",
        branch_node_id="missing",
    ) is None
    assert parallel_completed_artifact_exists(
        timeline,
        parallel_node_id="parallel-1",
        branch_node_id="branch-artifact",
    ) is True
    assert WorkflowContinuationCoordinator._parallel_completed_artifact_exists(
        timeline,
        parallel_node_id="parallel-1",
        branch_node_id="missing",
    ) is False
