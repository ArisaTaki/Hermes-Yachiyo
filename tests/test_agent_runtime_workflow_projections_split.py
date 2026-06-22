"""Tests for workflow timeline projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelBranchProjection,
    WorkflowParallelNodeProjection,
    WorkflowProjectionPortBundle,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)


def test_workflow_timeline_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowStartNodeProjection is WorkflowStartNodeProjection
    assert agent_runtime.WorkflowEdgeFollowedProjection is WorkflowEdgeFollowedProjection
    assert agent_runtime.WorkflowConditionNodeProjection is WorkflowConditionNodeProjection
    assert agent_runtime.WorkflowParallelBranchProjection is WorkflowParallelBranchProjection
    assert agent_runtime.WorkflowParallelNodeProjection is WorkflowParallelNodeProjection
    assert agent_runtime.WorkflowLoopNodeProjection is WorkflowLoopNodeProjection
    assert agent_runtime.WorkflowRunCompletionProjection is WorkflowRunCompletionProjection
    assert agent_runtime.WorkflowProjectionPortBundle is WorkflowProjectionPortBundle
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


def test_workflow_condition_projection_legacy_helper_accepts_port_bundle() -> None:
    calls: list[tuple[str, str]] = []
    ports = WorkflowProjectionPortBundle(
        workflow_condition_selection=lambda _workflow, node, context: calls.append(
            (str(node["id"]), context)
        )
        or {
            "condition": "ship",
            "operator": "contains",
            "matched": False,
            "branch": "false",
            "target_node_id": "skip",
        }
    )

    projection = WorkflowConditionNodeProjection.from_node(
        object(),
        {"nodes": []},
        {"id": "route", "type": "condition"},
        label="Route",
        kind="condition",
        context="skip",
        ports=ports,
    )

    assert calls == [("route", "skip")]
    assert projection.branch == "false"
    assert projection.target_node_id == "skip"
    assert projection.timeline_event(
        lambda event, detail, **payload: {"event": event, "detail": detail, **payload}
    )["event"] == "workflow.node.condition"


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


def test_workflow_loop_projection_legacy_helper_accepts_port_bundle() -> None:
    calls: list[tuple[str, str, int]] = []
    ports = WorkflowProjectionPortBundle(
        workflow_loop_selection=lambda _workflow, node, context, *, previous_iterations: calls.append(
            (str(node["id"]), context, previous_iterations)
        )
        or {
            "condition": "again",
            "operator": "contains",
            "matched": True,
            "branch": "continue",
            "target_node_id": "worker",
            "previous_iterations": previous_iterations,
            "iteration": previous_iterations + 1,
            "max_iterations": 3,
            "limit_reached": False,
        }
    )

    projection = WorkflowLoopNodeProjection.from_node(
        object(),
        {"nodes": []},
        {"id": "repeat", "type": "loop"},
        label="Repeat",
        kind="loop",
        context="again",
        previous_iterations=1,
        ports=ports,
    )

    assert calls == [("repeat", "again", 1)]
    assert projection.branch == "continue"
    assert projection.iteration == 2
    timeline_event = projection.timeline_event(
        lambda event, detail, **payload: {"event": event, "detail": detail, **payload}
    )
    assert timeline_event["event"] == "workflow.node.loop"
    assert timeline_event["workflow_node_loop_iteration"] == 2


def test_workflow_parallel_projection_accepts_plan_payload() -> None:
    projection = WorkflowParallelNodeProjection.from_plan(
        {"id": "fanout", "type": "parallel"},
        {
            "join_node_id": "report",
            "branches": [
                {"entry_node_id": "design", "label": "Design"},
                {"entry_node_id": "code", "label": "Code"},
            ],
        },
        [
            {"entry_node_id": "design", "label": "Design", "result": "Design ready"},
        ],
        label="Parallel Work",
        kind="parallel",
    )

    assert projection.event_payload() == {
        "workflow_node_id": "fanout",
        "workflow_node_kind": "parallel",
        "workflow_node_label": "Parallel Work",
        "workflow_node_branch_count": 2,
        "workflow_node_completed_branch_count": 1,
        "workflow_node_join_target": "report",
        "workflow_node_branch_results": [
            {"entry_node_id": "design", "label": "Design", "result": "Design ready"},
        ],
        "status": "completed",
    }


def test_workflow_parallel_branch_projection_builds_child_metadata_and_aggregate_context() -> None:
    projection = WorkflowParallelBranchProjection.from_branch(
        {"id": "fanout", "type": "parallel"},
        {"entry_node_id": "design", "label": "Design"},
        label="Parallel Work",
        kind="parallel",
        context="Parent context",
    )

    assert projection.child_node_info() == {
        "workflow_parent_node_id": "fanout",
        "workflow_parent_node_kind": "parallel",
        "workflow_parent_node_label": "Parallel Work",
        "workflow_parallel_branch_entry_node_id": "design",
        "workflow_parallel_branch_label": "Design",
        "workflow_parent_node_context": "Parent context",
    }
    assert projection.result_payload("Design ready") == {
        "entry_node_id": "design",
        "label": "Design",
        "result": "Design ready",
    }
    assert WorkflowParallelBranchProjection.aggregate_context(
        "Parallel Work",
        [projection.result_payload("Design ready")],
        fallback="Parent context",
    ) == "Parallel Parallel Work results:\n- Design: Design ready"
    assert (
        WorkflowParallelBranchProjection.aggregate_context(
            "Parallel Work",
            [],
            fallback="Parent context",
        )
        == "Parent context"
    )
