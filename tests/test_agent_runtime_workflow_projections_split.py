"""Tests for workflow timeline projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)


def test_workflow_timeline_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowStartNodeProjection is WorkflowStartNodeProjection
    assert agent_runtime.WorkflowEdgeFollowedProjection is WorkflowEdgeFollowedProjection
    assert agent_runtime.WorkflowConditionNodeProjection is WorkflowConditionNodeProjection
    assert agent_runtime.WorkflowParallelNodeProjection is WorkflowParallelNodeProjection
    assert agent_runtime.WorkflowLoopNodeProjection is WorkflowLoopNodeProjection
    assert agent_runtime.WorkflowRunCompletionProjection is WorkflowRunCompletionProjection
    assert (
        agent_runtime.WorkflowContinuationFailureProjection
        is WorkflowContinuationFailureProjection
    )


def test_workflow_edge_followed_projection_builds_replay_payload() -> None:
    projection = WorkflowEdgeFollowedProjection.from_node(
        {"id": "condition", "type": "condition"},
        label="Decision",
        kind="condition",
        target_node_id="ship",
        branch="true",
    )

    assert projection.event_payload() == {
        "workflow_node_id": "condition",
        "workflow_node_kind": "condition",
        "workflow_node_label": "Decision",
        "workflow_edge_source_node_id": "condition",
        "workflow_edge_source_node_kind": "condition",
        "workflow_edge_source_node_label": "Decision",
        "workflow_edge_target_node_id": "ship",
        "workflow_edge_branch": "true",
        "status": "completed",
    }
