"""Tests for Workflow facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_facade import RuntimeWorkflowFacadeMixin
from apps.shell.agent.runtime.workflow_outcomes import WorkflowChildOutcomeCoordinator
from apps.shell.agent.runtime.workflow_path import WorkflowPathPlanner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_workflow_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeWorkflowFacadeMixin is RuntimeWorkflowFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeWorkflowFacadeMixin)
    for method_name in (
        "create_workflow_run",
        "create_workflow_run_async",
        "_workflow_parent_runs_waiting_for_child",
        "_workflow_resume_start_index",
        "_workflow_run_is_group_root",
        "_workflow_child_artifact_refs",
        "_workflow_child_node_context",
        "_merge_workflow_child_run_outcome",
        "_workflow_artifact_path",
        "_resume_parent_workflows_after_child_update",
        "_mark_parent_workflows_child_running",
        "_resume_parent_workflow_after_child_update",
        "_continue_workflow_run",
        "_workflow_path",
        "_workflow_nodes_by_id",
        "_workflow_next_node_id",
        "_workflow_condition_selection",
        "_workflow_parallel_plan",
        "_workflow_loop_selection",
        "_workflow_loop_step_limit",
        "_workflow_loop_iterations_from_timeline",
        "_workflow_node_task",
        "_workflow_approval_criteria",
        "_workflow_child_goal",
        "_workflow_path_snapshot",
        "_workflow_runtime_snapshot",
        "_workflow_for_run_resume",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_workflow_static_helpers_available_after_split() -> None:
    child_run = {
        "run_id": "child-1",
        "artifacts": [{"artifact_id": "artifact-1", "kind": "workflow_child_artifact"}],
        "timeline": [{"event": "agent.run.completed", "detail": "done"}],
    }
    timeline = [{"workflow_node_id": "node-1", "workflow_node_context": "child context"}]
    node = {"label": "Review", "task": "Review the patch.", "approval_criteria": "Approved"}
    workflow = {"workflow_id": "workflow-1", "nodes": [node]}
    artifacts = [{"kind": "workflow_artifact", "path": "review.md"}]

    assert agent_runtime.NativeRunEngine._workflow_child_artifact_refs(
        child_run,
        "Review",
    ) == WorkflowChildOutcomeCoordinator.child_artifact_refs(child_run, "Review")
    assert agent_runtime.NativeRunEngine._workflow_child_node_context(
        timeline,
        child_run,
    ) == WorkflowChildOutcomeCoordinator.child_node_context(timeline, child_run)
    assert agent_runtime.NativeRunEngine._workflow_artifact_path(
        "Review",
        artifacts,
    ) == WorkflowPathPlanner.artifact_path("Review", artifacts)
    assert agent_runtime.NativeRunEngine._workflow_node_task(node) == WorkflowPathPlanner.node_task(node)
    assert agent_runtime.NativeRunEngine._workflow_approval_criteria(
        node,
    ) == WorkflowPathPlanner.approval_criteria(node)
    assert agent_runtime.NativeRunEngine._workflow_child_goal(
        "Ship the feature.",
        "Review the patch.",
    ) == WorkflowPathPlanner.child_goal("Ship the feature.", "Review the patch.")
    assert agent_runtime.NativeRunEngine._workflow_runtime_snapshot(
        workflow,
    ) == WorkflowPathPlanner.runtime_snapshot(workflow)


def test_native_runtime_keeps_workflow_facade_methods_available_after_split(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class _WorkflowRunCoordinator:
        @staticmethod
        def create_sync(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("create-sync", payload))
            return {"run_id": "workflow-run"}

    class _AsyncWorkflowRunCoordinator:
        @staticmethod
        def create_async(payload: dict[str, Any], *, on_complete: Any = None) -> dict[str, Any]:
            calls.append(("create-async", payload, on_complete))
            return {"run_id": "workflow-run-async"}

    class _WorkflowParentLocator:
        @staticmethod
        def parent_runs_waiting_for_child(child_run: dict[str, Any]) -> list[dict[str, Any]]:
            calls.append(("parents", child_run))
            return [{"run_id": "parent-1"}]

        @staticmethod
        def workflow_run_is_group_root(workflow_run: dict[str, Any]) -> bool:
            calls.append(("group-root", workflow_run))
            return True

    class _WorkflowResumePlanner:
        @staticmethod
        def resume_start_index(
            workflow: dict[str, Any],
            workflow_run: dict[str, Any],
            child_run_id: str,
        ) -> int:
            calls.append(("resume-index", workflow, workflow_run, child_run_id))
            return 3

        @staticmethod
        def next_node_id(workflow: dict[str, Any], node: dict[str, Any] | str, context: str) -> str:
            calls.append(("next-node", workflow, node, context))
            return "node-next"

        @staticmethod
        def workflow_for_run_resume(workflow_run: dict[str, Any]) -> dict[str, Any]:
            calls.append(("workflow-for-resume", workflow_run))
            return {"workflow_id": "workflow-1"}

    class _WorkflowChildOutcomes:
        @staticmethod
        def merge_child_run_outcome(
            timeline: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
            child_run: dict[str, Any],
            label: str,
        ) -> None:
            calls.append(("merge-child", timeline, artifacts, child_run, label))

    class _WorkflowParentResume:
        @staticmethod
        def resume_after_child_update(child_run: dict[str, Any]) -> None:
            calls.append(("resume-after-child", child_run))

        @staticmethod
        def mark_child_running(child_run: dict[str, Any]) -> None:
            calls.append(("mark-child-running", child_run))

        @staticmethod
        def resume_parent_after_child_update(
            workflow_run: dict[str, Any],
            child_run: dict[str, Any],
        ) -> dict[str, Any]:
            calls.append(("resume-parent", workflow_run, child_run))
            return {"run_id": workflow_run["run_id"], "status": "completed"}

    class _WorkflowContinuation:
        @staticmethod
        def continue_run(
            run: dict[str, Any],
            workflow: dict[str, Any],
            **kwargs: Any,
        ) -> dict[str, Any]:
            calls.append(("continue", run, workflow, kwargs))
            return {"run_id": run["run_id"], "status": "completed"}

    class _WorkflowPathPlanner:
        @staticmethod
        def workflow_path(workflow: dict[str, Any]) -> list[dict[str, Any]]:
            calls.append(("path", workflow))
            return [{"id": "start"}]

        @staticmethod
        def nodes_by_id(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
            calls.append(("nodes", workflow))
            return {"start": {"id": "start"}}

        @staticmethod
        def condition_selection(workflow: dict[str, Any], node: dict[str, Any], context: str) -> dict[str, Any]:
            calls.append(("condition", workflow, node, context))
            return {"matched": True, "target": "node-next"}

        @staticmethod
        def parallel_plan(workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
            calls.append(("parallel", workflow, node))
            return {"branches": ["a", "b"]}

        @staticmethod
        def loop_selection(
            workflow: dict[str, Any],
            node: dict[str, Any],
            context: str,
            *,
            previous_iterations: int = 0,
        ) -> dict[str, Any]:
            calls.append(("loop", workflow, node, context, previous_iterations))
            return {"iteration": previous_iterations + 1}

        @staticmethod
        def loop_step_limit(workflow: dict[str, Any]) -> int:
            calls.append(("loop-limit", workflow))
            return 4

        @staticmethod
        def loop_iterations_from_timeline(timeline: list[dict[str, Any]]) -> dict[str, int]:
            calls.append(("loop-iterations", timeline))
            return {"loop-1": 2}

        @staticmethod
        def path_snapshot(workflow: dict[str, Any]) -> list[dict[str, str]]:
            calls.append(("path-snapshot", workflow))
            return [{"id": "start", "label": "Start"}]

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service.workflow_run_coordinator = _WorkflowRunCoordinator()
        service.workflow_run_async_coordinator = _AsyncWorkflowRunCoordinator()
        service.workflow_parent_locator = _WorkflowParentLocator()
        service.workflow_resume_planner = _WorkflowResumePlanner()
        service.workflow_child_outcomes = _WorkflowChildOutcomes()
        service.workflow_parent_resume = _WorkflowParentResume()
        service.workflow_continuation = _WorkflowContinuation()
        service.workflow_path_planner = _WorkflowPathPlanner()

        workflow = {"workflow_id": "workflow-1"}
        workflow_run = {"run_id": "workflow-run", "runnable_id": "workflow-1"}
        child_run = {"run_id": "child-run", "kind": "agent_run"}
        timeline: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        on_complete = object()

        assert service.create_workflow_run({"workflow_id": "workflow-1"}) == {"run_id": "workflow-run"}
        assert service.create_workflow_run_async(
            {"workflow_id": "workflow-1"},
            on_complete=on_complete,
        ) == {"run_id": "workflow-run-async"}
        assert service._workflow_parent_runs_waiting_for_child(child_run) == [{"run_id": "parent-1"}]
        assert service._workflow_resume_start_index(workflow, workflow_run, "child-run") == 3
        assert service._workflow_run_is_group_root(workflow_run) is True
        service._merge_workflow_child_run_outcome(timeline, artifacts, child_run, "Review")
        service._resume_parent_workflows_after_child_update(child_run)
        service._mark_parent_workflows_child_running(child_run)
        assert service._resume_parent_workflow_after_child_update(
            workflow_run,
            child_run,
        ) == {"run_id": "workflow-run", "status": "completed"}
        assert service._continue_workflow_run(
            workflow_run,
            workflow,
            context="context",
            timeline=timeline,
            artifacts=artifacts,
            start_index=1,
            root_group=True,
            start_node_id="node-1",
        ) == {"run_id": "workflow-run", "status": "completed"}
        assert service._workflow_path(workflow) == [{"id": "start"}]
        assert service._workflow_nodes_by_id(workflow) == {"start": {"id": "start"}}
        assert service._workflow_next_node_id(workflow, {"id": "start"}, "context") == "node-next"
        assert service._workflow_condition_selection(
            workflow,
            {"id": "condition"},
            "context",
        ) == {"matched": True, "target": "node-next"}
        assert service._workflow_parallel_plan(workflow, {"id": "parallel"}) == {"branches": ["a", "b"]}
        assert service._workflow_loop_selection(
            workflow,
            {"id": "loop"},
            "context",
            previous_iterations=2,
        ) == {"iteration": 3}
        assert service._workflow_loop_step_limit(workflow) == 4
        assert service._workflow_loop_iterations_from_timeline(timeline) == {"loop-1": 2}
        assert service._workflow_path_snapshot(workflow) == [{"id": "start", "label": "Start"}]
        assert service._workflow_for_run_resume(workflow_run) == {"workflow_id": "workflow-1"}

        assert ("create-sync", {"workflow_id": "workflow-1"}) in calls
        assert ("create-async", {"workflow_id": "workflow-1"}, on_complete) in calls
        assert ("merge-child", timeline, artifacts, child_run, "Review") in calls
        assert (
            "continue",
            workflow_run,
            workflow,
            {
                "context": "context",
                "timeline": timeline,
                "artifacts": artifacts,
                "start_index": 1,
                "root_group": True,
                "start_node_id": "node-1",
                "runtime_execution_envelope": None,
                "runtime_execution_metadata": None,
                "direct_tool_requests": None,
                "daily_desktop_planning_context": None,
            },
        ) in calls
        assert ("workflow-for-resume", workflow_run) in calls
    finally:
        service.close()
