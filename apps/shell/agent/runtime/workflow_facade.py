"""Workflow compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.workflow_outcomes import WorkflowChildOutcomeCoordinator
from apps.shell.agent.runtime.workflow_path import WorkflowPathPlanner


class RuntimeWorkflowFacadeMixin:
    """Keeps legacy Workflow helper methods while delegating to split services."""

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_run_coordinator.create_sync(payload)

    def create_workflow_run_async(
        self,
        payload: dict[str, Any],
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self.workflow_run_async_coordinator.create_async(payload, on_complete=on_complete)

    def _workflow_parent_runs_waiting_for_child(
        self,
        child_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.workflow_parent_locator.parent_runs_waiting_for_child(child_run)

    def _workflow_resume_start_index(
        self,
        workflow: dict[str, Any],
        workflow_run: dict[str, Any],
        child_run_id: str,
    ) -> int | None:
        return self.workflow_resume_planner.resume_start_index(
            workflow,
            workflow_run,
            child_run_id,
        )

    def _workflow_run_is_group_root(self, workflow_run: dict[str, Any]) -> bool:
        return self.workflow_parent_locator.workflow_run_is_group_root(workflow_run)

    @staticmethod
    def _workflow_child_artifact_refs(child_run: dict[str, Any], label: str) -> list[dict[str, Any]]:
        return WorkflowChildOutcomeCoordinator.child_artifact_refs(child_run, label)

    @staticmethod
    def _workflow_child_node_context(
        timeline: list[dict[str, Any]],
        child_run: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        return WorkflowChildOutcomeCoordinator.child_node_context(timeline, child_run)

    def _merge_workflow_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        self.workflow_child_outcomes.merge_child_run_outcome(
            timeline,
            artifacts,
            child_run,
            label,
        )

    @staticmethod
    def _workflow_artifact_path(label: str, artifacts: list[dict[str, Any]], configured_path: str = "") -> str:
        return WorkflowPathPlanner.artifact_path(label, artifacts, configured_path)

    def _resume_parent_workflows_after_child_update(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.resume_after_child_update(child_run)

    def _mark_parent_workflows_child_running(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.mark_child_running(child_run)

    def _resume_parent_workflow_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        return self.workflow_parent_resume.resume_parent_after_child_update(workflow_run, child_run)

    def _continue_workflow_run(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
        start_node_id: str = "",
        runtime_execution_envelope: Any | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        daily_desktop_planning_context: str | None = None,
    ) -> dict[str, Any]:
        return self.workflow_continuation.continue_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
            start_node_id=start_node_id,
            runtime_execution_envelope=runtime_execution_envelope,
            runtime_execution_metadata=runtime_execution_metadata,
            direct_tool_requests=direct_tool_requests,
            daily_desktop_planning_context=daily_desktop_planning_context,
        )

    def _workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return self.workflow_path_planner.workflow_path(workflow)

    def _workflow_nodes_by_id(self, workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return self.workflow_path_planner.nodes_by_id(workflow)

    def _workflow_next_node_id(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any] | str,
        context: str,
    ) -> str:
        return self.workflow_resume_planner.next_node_id(workflow, node, context)

    def _workflow_condition_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.condition_selection(workflow, node, context)

    def _workflow_parallel_plan(self, workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_path_planner.parallel_plan(workflow, node)

    def _workflow_loop_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
        *,
        previous_iterations: int = 0,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )

    def _workflow_loop_step_limit(self, workflow: dict[str, Any]) -> int:
        return self.workflow_path_planner.loop_step_limit(workflow)

    def _workflow_loop_iterations_from_timeline(self, timeline: list[dict[str, Any]]) -> dict[str, int]:
        return self.workflow_path_planner.loop_iterations_from_timeline(timeline)

    @staticmethod
    def _workflow_node_task(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.node_task(node)

    @staticmethod
    def _workflow_approval_criteria(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.approval_criteria(node)

    @staticmethod
    def _workflow_child_goal(workflow_goal: str, step_task: str) -> str:
        return WorkflowPathPlanner.child_goal(workflow_goal, step_task)

    def _workflow_path_snapshot(self, workflow: dict[str, Any]) -> list[dict[str, str]]:
        return self.workflow_path_planner.path_snapshot(workflow)

    @staticmethod
    def _workflow_runtime_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
        return WorkflowPathPlanner.runtime_snapshot(workflow)

    def _workflow_for_run_resume(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_resume_planner.workflow_for_run_resume(workflow_run)
