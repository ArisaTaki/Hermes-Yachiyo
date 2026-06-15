"""Workflow planning and start service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.cancellation import WorkflowCancellationProjectionCoordinator
from apps.shell.agent.runtime.run_projections import ApprovalResumeProjectionCoordinator
from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalResumeCoordinator
from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator
from apps.shell.agent.runtime.workflow_outcomes import WorkflowChildOutcomeCoordinator
from apps.shell.agent.runtime.workflow_parent_resume import WorkflowParentResumeCoordinator
from apps.shell.agent.runtime.workflow_path import WorkflowDefinitionValidator, WorkflowPathPlanner
from apps.shell.agent.runtime.workflow_resume import (
    RunTransitionProjectionCoordinator,
    WorkflowParentRunLocator,
    WorkflowResumePlanner,
)
from apps.shell.agent.runtime.workflow_runs import RuntimeWorkflowRunStarter
from apps.shell.agent.runtime.workflow_start import WorkflowRunStartProjector


@dataclass(frozen=True)
class RuntimeWorkflowPlanningServiceBundle:
    workflow_parent_locator: WorkflowParentRunLocator
    workflow_path_planner: WorkflowPathPlanner
    workflow_definition_validator: WorkflowDefinitionValidator
    run_readiness_validator: RuntimeRunReadinessValidator
    workflow_run_start_projector: WorkflowRunStartProjector
    workflow_run_starter: RuntimeWorkflowRunStarter
    workflow_resume_planner: WorkflowResumePlanner


@dataclass(frozen=True)
class RuntimeWorkflowExecutionServiceBundle:
    workflow_continuation: WorkflowContinuationCoordinator
    workflow_approval_resume: WorkflowApprovalResumeCoordinator
    workflow_cancellation: WorkflowCancellationProjectionCoordinator
    workflow_child_outcomes: WorkflowChildOutcomeCoordinator


@dataclass(frozen=True)
class RuntimeWorkflowTransitionServiceBundle:
    workflow_parent_resume: WorkflowParentResumeCoordinator
    approval_resume_projection: ApprovalResumeProjectionCoordinator
    run_transition_projection: RunTransitionProjectionCoordinator


def build_runtime_workflow_planning_services(
    *,
    get_run_group: Callable[[str], dict[str, Any]],
    get_run: Callable[[str], dict[str, Any]],
    node_kind: Callable[[dict[str, Any]], str],
    node_types: set[str],
    get_agent_private: Callable[[str], dict[str, Any]],
    get_workflow: Callable[[str], dict[str, Any]],
    load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
    agent_model_config_private: Callable[[dict[str, Any]], dict[str, Any]],
    default_agent_ids: set[str],
    timeline_factory: Callable[..., dict[str, Any]],
    workflow_path_snapshot: Callable[[dict[str, Any]], list[dict[str, Any]]],
    workflow_runtime_snapshot: Callable[[dict[str, Any]], dict[str, Any]],
    insert_run_group: Callable[..., dict[str, Any]],
    insert_run: Callable[..., dict[str, Any]],
    run_by_client_request_id: Callable[[str], dict[str, Any] | None],
    client_request_id_from_payload: Callable[[dict[str, Any]], str],
    workflow_path: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> RuntimeWorkflowPlanningServiceBundle:
    workflow_path_planner = WorkflowPathPlanner(node_kind=node_kind)
    return RuntimeWorkflowPlanningServiceBundle(
        workflow_parent_locator=WorkflowParentRunLocator(
            get_run_group=get_run_group,
            get_run=get_run,
        ),
        workflow_path_planner=workflow_path_planner,
        workflow_definition_validator=WorkflowDefinitionValidator(
            node_kind=node_kind,
            node_types=node_types,
        ),
        run_readiness_validator=RuntimeRunReadinessValidator(
            node_kind=node_kind,
            get_agent_private=get_agent_private,
            get_workflow=get_workflow,
            load_agent_skills=load_agent_skills,
            agent_model_config_private=agent_model_config_private,
            default_agent_ids=default_agent_ids,
        ),
        workflow_run_start_projector=WorkflowRunStartProjector(
            timeline_factory=timeline_factory,
            path_snapshot=workflow_path_snapshot,
            runtime_snapshot=workflow_runtime_snapshot,
        ),
        workflow_run_starter=RuntimeWorkflowRunStarter(
            get_run_group=get_run_group,
            insert_run_group=insert_run_group,
            insert_run=insert_run,
            run_by_client_request_id=run_by_client_request_id,
            client_request_id_from_payload=client_request_id_from_payload,
        ),
        workflow_resume_planner=WorkflowResumePlanner(
            get_workflow=get_workflow,
            workflow_path=workflow_path,
            node_kind=node_kind,
            nodes_by_id=workflow_path_planner.nodes_by_id,
            next_node_id=workflow_path_planner.next_node_id,
        ),
    )


def build_runtime_workflow_execution_services(
    *,
    engine: Any,
    iso_epoch: Callable[[Any], float],
    claim_pending_approval: Callable[..., bool],
    get_current_run: Callable[[str], dict[str, Any]],
    pending_approval_private: Callable[[str], dict[str, Any] | None],
    get_run: Callable[[str], dict[str, Any]],
    merge_workflow_child_run_outcome: Callable[..., None],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    update_run: Callable[..., dict[str, Any]],
) -> RuntimeWorkflowExecutionServiceBundle:
    workflow_continuation = WorkflowContinuationCoordinator(
        engine,
        iso_epoch=iso_epoch,
        workflow_path=lambda workflow: engine._workflow_path(workflow),
        workflow_nodes_by_id=lambda workflow: engine._workflow_nodes_by_id(workflow),
        workflow_next_node_id=lambda workflow, node, context: (
            engine._workflow_next_node_id(workflow, node, context)
        ),
        workflow_parallel_plan=lambda workflow, node: engine._workflow_parallel_plan(
            workflow,
            node,
        ),
        workflow_condition_selection=lambda workflow, node, context: (
            engine._workflow_condition_selection(workflow, node, context)
        ),
        workflow_loop_selection=lambda workflow, node, context, *, previous_iterations: (
            engine._workflow_loop_selection(
                workflow,
                node,
                context,
                previous_iterations=previous_iterations,
            )
        ),
        workflow_approval_criteria=lambda node: engine._workflow_approval_criteria(node),
        default_workspace_policy=lambda: engine._default_workspace_policy(),
        workflow_artifacts_dir=lambda: engine.workflow_artifacts_dir,
        workflow_artifact_path=lambda label, artifacts, requested: (
            engine._workflow_artifact_path(label, artifacts, requested)
        ),
        workflow_agent_for_node=lambda node: engine._workflow_agent_for_node(node),
        workflow_node_task=lambda node: engine._workflow_node_task(node),
        workflow_child_goal=lambda workflow_goal, step_task: (
            engine._workflow_child_goal(workflow_goal, step_task)
        ),
        insert_run=lambda **kwargs: engine._insert_run(**kwargs),
        execute_agent_run=lambda run_id, agent, user_goal, *, upstream: (
            engine._execute_agent_run(run_id, agent, user_goal, upstream=upstream)
        ),
        workflow_child_artifact_refs=lambda child_run, label: (
            engine._workflow_child_artifact_refs(child_run, label)
        ),
        merge_workflow_child_run_outcome=merge_workflow_child_run_outcome,
        workflow_for_node=lambda node: engine._workflow_for_node(node),
        workflow_run_started_projection=lambda workflow_id, workflow: (
            engine.workflow_run_start_projector.started_projection(workflow_id, workflow)
        ),
        continue_workflow_run=lambda run, workflow, **kwargs: (
            engine._continue_workflow_run(run, workflow, **kwargs)
        ),
        node_kind=lambda node: engine._node_kind(node),
    )
    return RuntimeWorkflowExecutionServiceBundle(
        workflow_continuation=workflow_continuation,
        workflow_approval_resume=WorkflowApprovalResumeCoordinator(
            claim_pending_approval=claim_pending_approval,
            get_current_run=get_current_run,
            resume_after_approval_node=workflow_continuation.resume_after_approval_node,
        ),
        workflow_cancellation=WorkflowCancellationProjectionCoordinator(
            pending_approval_private=pending_approval_private,
            get_run=get_run,
            merge_workflow_child_run_outcome=merge_workflow_child_run_outcome,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            update_run=update_run,
        ),
        workflow_child_outcomes=WorkflowChildOutcomeCoordinator(),
    )


def build_runtime_workflow_transition_services(
    *,
    parent_runs_waiting_for_child: Callable[[dict[str, Any]], list[dict[str, Any]]],
    workflow_run_is_group_root: Callable[[dict[str, Any]], bool],
    workflow_child_node_context: Callable[..., tuple[str, dict[str, str]]],
    merge_workflow_child_run_outcome: Callable[..., None],
    workflow_for_run_resume: Callable[[dict[str, Any]], dict[str, Any]],
    workflow_resume_start_index: Callable[..., int | None],
    workflow_next_node_id: Callable[..., str],
    continue_workflow_run: Callable[..., dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    update_run: Callable[..., dict[str, Any]],
    update_run_group: Callable[..., dict[str, Any]],
    update_agent_run_group_if_root: Callable[[dict[str, Any]], None],
    mark_parent_workflows_child_running: Callable[[dict[str, Any]], None],
    resume_parent_workflows_after_child_update: Callable[[dict[str, Any]], None],
    get_run: Callable[[str], dict[str, Any]],
) -> RuntimeWorkflowTransitionServiceBundle:
    workflow_parent_resume = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=parent_runs_waiting_for_child,
        workflow_run_is_group_root=workflow_run_is_group_root,
        workflow_child_node_context=workflow_child_node_context,
        merge_workflow_child_run_outcome=merge_workflow_child_run_outcome,
        workflow_for_run_resume=workflow_for_run_resume,
        workflow_resume_start_index=workflow_resume_start_index,
        workflow_next_node_id=workflow_next_node_id,
        continue_workflow_run=continue_workflow_run,
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        update_run=update_run,
        update_run_group=update_run_group,
    )
    return RuntimeWorkflowTransitionServiceBundle(
        workflow_parent_resume=workflow_parent_resume,
        approval_resume_projection=ApprovalResumeProjectionCoordinator(
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            update_run=update_run,
            update_agent_run_group_if_root=update_agent_run_group_if_root,
            mark_parent_workflows_child_running=mark_parent_workflows_child_running,
        ),
        run_transition_projection=RunTransitionProjectionCoordinator(
            update_agent_run_group_if_root=update_agent_run_group_if_root,
            resume_parent_workflows_after_child_update=resume_parent_workflows_after_child_update,
            workflow_run_is_group_root=workflow_run_is_group_root,
            update_run_group=update_run_group,
            get_run=get_run,
        ),
    )
