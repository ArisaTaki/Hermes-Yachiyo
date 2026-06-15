"""Tests for Workflow execution service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.cancellation import WorkflowCancellationProjectionCoordinator
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalResumeCoordinator
from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator
from apps.shell.agent.runtime.workflow_outcomes import WorkflowChildOutcomeCoordinator
from apps.shell.agent.runtime.workflow_services import (
    RuntimeWorkflowExecutionServiceBundle,
    build_runtime_workflow_execution_services,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_workflow_execution_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeWorkflowExecutionServiceBundle is RuntimeWorkflowExecutionServiceBundle


def test_build_runtime_workflow_execution_services_wires_continuation_approval_and_cancellation() -> None:
    engine = object()

    def iso_epoch(_value: Any) -> float:
        return 0.0

    def timeline_factory(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **extra}

    def workflow_artifact_write(
        _run: dict[str, Any],
        artifact_path: str,
        context: str,
    ) -> dict[str, Any]:
        return {"path": artifact_path, "content": context}

    bundle = build_runtime_workflow_execution_services(
        engine=engine,
        iso_epoch=iso_epoch,
        claim_pending_approval=lambda *_args, **_kwargs: True,
        get_current_run=lambda run_id: {"run_id": run_id},
        pending_approval_private=lambda _run_id: None,
        get_run=lambda run_id: {"run_id": run_id},
        merge_workflow_child_run_outcome=lambda *_args, **_kwargs: None,
        timeline_factory=timeline_factory,
        append_run_event=lambda _run_id, _event_type, _payload: None,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        update_run_group=lambda run_group_id, **kwargs: {"run_group_id": run_group_id, **kwargs},
        approve_workflow_node=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        workflow_artifact_write=workflow_artifact_write,
    )

    assert isinstance(bundle, RuntimeWorkflowExecutionServiceBundle)
    assert isinstance(bundle.workflow_continuation, WorkflowContinuationCoordinator)
    assert isinstance(bundle.workflow_approval_resume, WorkflowApprovalResumeCoordinator)
    assert isinstance(bundle.workflow_cancellation, WorkflowCancellationProjectionCoordinator)
    assert isinstance(bundle.workflow_child_outcomes, WorkflowChildOutcomeCoordinator)
    assert bundle.workflow_continuation._engine is engine
    assert bundle.workflow_continuation._iso_epoch is iso_epoch
    assert callable(bundle.workflow_continuation._workflow_path_callback)
    assert callable(bundle.workflow_continuation._workflow_nodes_by_id_callback)
    assert callable(bundle.workflow_continuation._workflow_next_node_id_callback)
    assert callable(bundle.workflow_continuation._workflow_parallel_plan_callback)
    assert callable(bundle.workflow_continuation._workflow_condition_selection_callback)
    assert callable(bundle.workflow_continuation._workflow_loop_selection_callback)
    assert callable(bundle.workflow_continuation._workflow_approval_criteria_callback)
    assert callable(bundle.workflow_continuation._default_workspace_policy_callback)
    assert callable(bundle.workflow_continuation._workflow_artifacts_dir_source)
    assert callable(bundle.workflow_continuation._workflow_artifact_path_callback)
    assert bundle.workflow_continuation._workflow_artifact_write_callback is workflow_artifact_write
    assert callable(bundle.workflow_continuation._workflow_agent_for_node_callback)
    assert callable(bundle.workflow_continuation._workflow_node_task_callback)
    assert callable(bundle.workflow_continuation._workflow_child_goal_callback)
    assert callable(bundle.workflow_continuation._insert_run_callback)
    assert callable(bundle.workflow_continuation._execute_agent_run_callback)
    assert callable(bundle.workflow_continuation._workflow_child_artifact_refs_callback)
    assert callable(bundle.workflow_continuation._merge_workflow_child_run_outcome_callback)
    assert callable(bundle.workflow_continuation._workflow_for_node_callback)
    assert callable(bundle.workflow_continuation._workflow_run_started_projection_callback)
    assert callable(bundle.workflow_continuation._continue_workflow_run_callback)
    assert bundle.workflow_continuation._timeline_callback is timeline_factory
    assert callable(bundle.workflow_continuation._append_run_event_callback)
    assert callable(bundle.workflow_continuation._update_run_callback)
    assert callable(bundle.workflow_continuation._update_run_group_callback)
    assert callable(bundle.workflow_continuation._get_run_callback)
    assert callable(bundle.workflow_continuation._approve_workflow_node_callback)
    assert callable(bundle.workflow_continuation._runtime_limits_source)
    assert callable(bundle.workflow_continuation._workflow_loop_iterations_from_timeline_callback)
    assert callable(bundle.workflow_continuation._workflow_loop_step_limit_callback)
    assert callable(bundle.workflow_continuation._node_kind_callback)
    assert bundle.workflow_approval_resume._resume_after_approval_node.__self__ is bundle.workflow_continuation
    assert bundle.workflow_cancellation._timeline is timeline_factory


def test_build_runtime_workflow_execution_services_prefers_explicit_planning_ports() -> None:
    engine = object()

    def iso_epoch(_value: Any) -> float:
        return 0.0

    def workflow_path(_workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def workflow_nodes_by_id(_workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {}

    def workflow_next_node_id(
        _workflow: dict[str, Any],
        _node: dict[str, Any],
        _context: str,
    ) -> str:
        return ""

    def workflow_parallel_plan(
        _workflow: dict[str, Any],
        _node: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def workflow_condition_selection(
        _workflow: dict[str, Any],
        _node: dict[str, Any],
        _context: str,
    ) -> dict[str, Any]:
        return {}

    def workflow_loop_selection(
        _workflow: dict[str, Any],
        _node: dict[str, Any],
        _context: str,
        *,
        previous_iterations: int,
    ) -> dict[str, Any]:
        return {"previous_iterations": previous_iterations}

    def workflow_loop_iterations_from_timeline(
        _timeline: list[dict[str, Any]],
    ) -> dict[str, int]:
        return {}

    def workflow_loop_step_limit(_workflow: dict[str, Any]) -> int:
        return 1

    def workflow_run_started_projection(
        workflow_id: str,
        _workflow: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return [], {"workflow_id": workflow_id}

    bundle = build_runtime_workflow_execution_services(
        engine=engine,
        iso_epoch=iso_epoch,
        workflow_path=workflow_path,
        workflow_nodes_by_id=workflow_nodes_by_id,
        workflow_next_node_id=workflow_next_node_id,
        workflow_parallel_plan=workflow_parallel_plan,
        workflow_condition_selection=workflow_condition_selection,
        workflow_loop_selection=workflow_loop_selection,
        workflow_loop_iterations_from_timeline=workflow_loop_iterations_from_timeline,
        workflow_loop_step_limit=workflow_loop_step_limit,
        workflow_run_started_projection=workflow_run_started_projection,
        claim_pending_approval=lambda *_args, **_kwargs: True,
        get_current_run=lambda run_id: {"run_id": run_id},
        pending_approval_private=lambda _run_id: None,
        get_run=lambda run_id: {"run_id": run_id},
        merge_workflow_child_run_outcome=lambda *_args, **_kwargs: None,
        timeline_factory=lambda event, detail="", **extra: {"event": event, "detail": detail, **extra},
        append_run_event=lambda _run_id, _event_type, _payload: None,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        update_run_group=lambda run_group_id, **kwargs: {"run_group_id": run_group_id, **kwargs},
        approve_workflow_node=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
    )

    continuation = bundle.workflow_continuation
    assert continuation._workflow_path_callback is workflow_path
    assert continuation._workflow_nodes_by_id_callback is workflow_nodes_by_id
    assert continuation._workflow_next_node_id_callback is workflow_next_node_id
    assert continuation._workflow_parallel_plan_callback is workflow_parallel_plan
    assert continuation._workflow_condition_selection_callback is workflow_condition_selection
    assert continuation._workflow_loop_selection_callback is workflow_loop_selection
    assert (
        continuation._workflow_loop_iterations_from_timeline_callback
        is workflow_loop_iterations_from_timeline
    )
    assert continuation._workflow_loop_step_limit_callback is workflow_loop_step_limit
    assert continuation._workflow_run_started_projection_callback is workflow_run_started_projection


def test_native_runtime_installs_workflow_execution_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.workflow_continuation, WorkflowContinuationCoordinator)
        assert isinstance(service.workflow_approval_resume, WorkflowApprovalResumeCoordinator)
        assert isinstance(service.workflow_cancellation, WorkflowCancellationProjectionCoordinator)
        assert isinstance(service.workflow_child_outcomes, WorkflowChildOutcomeCoordinator)
        assert service.workflow_continuation._engine is service
        assert callable(service.workflow_continuation._workflow_path_callback)
        assert (
            service.workflow_continuation._workflow_path_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._workflow_nodes_by_id_callback)
        sample_workflow = {"nodes": [{"id": "start", "type": "start"}], "edges": []}
        assert service.workflow_continuation._workflow_nodes_by_id_callback(sample_workflow) == {
            "start": sample_workflow["nodes"][0]
        }
        assert callable(service.workflow_continuation._workflow_next_node_id_callback)
        assert (
            service.workflow_continuation._workflow_next_node_id_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._workflow_parallel_plan_callback)
        assert (
            service.workflow_continuation._workflow_parallel_plan_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._workflow_condition_selection_callback)
        assert (
            service.workflow_continuation._workflow_condition_selection_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._workflow_loop_selection_callback)
        assert (
            service.workflow_continuation._workflow_loop_selection_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._workflow_approval_criteria_callback)
        assert callable(service.workflow_continuation._default_workspace_policy_callback)
        assert callable(service.workflow_continuation._workflow_artifacts_dir_source)
        assert callable(service.workflow_continuation._workflow_artifact_path_callback)
        assert callable(service.workflow_continuation._workflow_artifact_write_callback)
        artifact = service.workflow_continuation._workflow_artifact_write_callback(
            {"run_id": "workflow-run-1"},
            "notes/result.md",
            "workflow result",
        )
        assert artifact["ok"] is True
        assert artifact["path"] == "notes/result.md"
        assert (
            service.workflow_artifacts_dir / "workflow-run-1" / "notes" / "result.md"
        ).read_text(encoding="utf-8") == "workflow result"
        assert not (
            service.agent_artifacts_dir / "workflow-run-1" / "notes" / "result.md"
        ).exists()
        assert callable(service.workflow_continuation._workflow_agent_for_node_callback)
        assert callable(service.workflow_continuation._workflow_node_task_callback)
        assert callable(service.workflow_continuation._workflow_child_goal_callback)
        assert callable(service.workflow_continuation._insert_run_callback)
        assert callable(service.workflow_continuation._execute_agent_run_callback)
        assert callable(service.workflow_continuation._workflow_child_artifact_refs_callback)
        assert callable(service.workflow_continuation._merge_workflow_child_run_outcome_callback)
        assert callable(service.workflow_continuation._workflow_for_node_callback)
        assert callable(service.workflow_continuation._workflow_run_started_projection_callback)
        assert (
            service.workflow_continuation._workflow_run_started_projection_callback.__self__
            is service.workflow_run_start_projector
        )
        assert callable(service.workflow_continuation._continue_workflow_run_callback)
        assert callable(service.workflow_continuation._timeline_callback)
        assert callable(service.workflow_continuation._append_run_event_callback)
        assert callable(service.workflow_continuation._update_run_callback)
        assert callable(service.workflow_continuation._update_run_group_callback)
        assert callable(service.workflow_continuation._get_run_callback)
        assert callable(service.workflow_continuation._approve_workflow_node_callback)
        assert callable(service.workflow_continuation._runtime_limits_source)
        assert callable(service.workflow_continuation._workflow_loop_iterations_from_timeline_callback)
        assert service.workflow_continuation._workflow_loop_iterations_from_timeline_callback(
            [
                {
                    "event": "workflow.node.loop",
                    "workflow_node_id": "repeat",
                    "workflow_node_loop_iteration": 2,
                }
            ]
        ) == {"repeat": 2}
        assert callable(service.workflow_continuation._workflow_loop_step_limit_callback)
        assert (
            service.workflow_continuation._workflow_loop_step_limit_callback.__self__
            is service.workflow_path_planner
        )
        assert callable(service.workflow_continuation._node_kind_callback)
        assert service.workflow_approval_resume._resume_after_approval_node.__self__ is service.workflow_continuation
        assert service.workflow_approval_resume._claim_pending_approval.__self__ is service.run_approvals
        assert callable(service.workflow_cancellation._pending_approval_private)
        assert callable(service.workflow_cancellation._merge_workflow_child_run_outcome)
    finally:
        service.close()
