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


def test_workflow_condition_projection_accepts_selection_payload() -> None:
    projection = WorkflowConditionNodeProjection.from_selection(
        {"id": "route", "type": "condition"},
        {
            "condition": "ship",
            "operator": "contains",
            "matched": True,
            "branch": "true",
            "target_node_id": "ship",
        },
        label="Route",
        kind="condition",
    )

    assert projection.event_payload() == {
        "workflow_node_id": "route",
        "workflow_node_kind": "condition",
        "workflow_node_label": "Route",
        "workflow_node_condition": "ship",
        "workflow_node_condition_operator": "contains",
        "workflow_node_condition_matched": True,
        "workflow_node_selected_branch": "true",
        "workflow_node_selected_target": "ship",
        "status": "completed",
    }


def test_workflow_loop_projection_accepts_selection_payload() -> None:
    projection = WorkflowLoopNodeProjection.from_selection(
        {"id": "repeat", "type": "loop"},
        {
            "condition": "again",
            "operator": "contains",
            "matched": True,
            "branch": "continue",
            "target_node_id": "worker",
            "previous_iterations": 1,
            "iteration": 2,
            "max_iterations": 3,
            "limit_reached": False,
        },
        label="Repeat",
        kind="loop",
    )

    assert projection.event_payload() == {
        "workflow_node_id": "repeat",
        "workflow_node_kind": "loop",
        "workflow_node_label": "Repeat",
        "workflow_node_condition": "again",
        "workflow_node_condition_operator": "contains",
        "workflow_node_condition_matched": True,
        "workflow_node_selected_branch": "continue",
        "workflow_node_selected_target": "worker",
        "workflow_node_loop_previous_iterations": 1,
        "workflow_node_loop_iteration": 2,
        "workflow_node_loop_max_iterations": 3,
        "workflow_node_loop_limit_reached": False,
        "status": "completed",
    }
