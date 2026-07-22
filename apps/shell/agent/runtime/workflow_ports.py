"""Workflow execution port contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowContinuationPortBundle:
    """Injected continuation ports for decoupling Workflow execution from the engine."""

    iso_epoch: Any | None = None
    workflow_path: Any | None = None
    workflow_nodes_by_id: Any | None = None
    workflow_next_node_id: Any | None = None
    workflow_parallel_plan: Any | None = None
    workflow_condition_selection: Any | None = None
    workflow_loop_selection: Any | None = None
    workflow_approval_criteria: Any | None = None
    default_workspace_policy: Any | None = None
    workflow_artifacts_dir: Any | None = None
    workflow_artifact_path: Any | None = None
    workflow_artifact_write: Any | None = None
    workflow_agent_for_node: Any | None = None
    workflow_node_task: Any | None = None
    workflow_child_goal: Any | None = None
    insert_run: Any | None = None
    execute_agent_run: Any | None = None
    workflow_child_artifact_refs: Any | None = None
    merge_workflow_child_run_outcome: Any | None = None
    workflow_for_node: Any | None = None
    workflow_run_started_projection: Any | None = None
    continue_workflow_run: Any | None = None
    timeline_factory: Any | None = None
    append_run_event: Any | None = None
    update_run: Any | None = None
    update_run_group: Any | None = None
    get_run: Any | None = None
    get_run_group: Any | None = None
    transaction_scope: Any | None = None
    pending_approval_private: Any | None = None
    approve_workflow_node: Any | None = None
    runtime_limits: Any | None = None
    workflow_loop_iterations_from_timeline: Any | None = None
    workflow_loop_step_limit: Any | None = None
    node_kind: Any | None = None


__all__ = ["WorkflowContinuationPortBundle"]
