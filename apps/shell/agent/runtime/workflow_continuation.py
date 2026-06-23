"""Workflow continuation orchestration for Workflow Runs."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.budget import RunBudgetLimits, WorkflowRunBudget
from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.clock import iso_epoch as _iso_epoch
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_brokers import write_artifact_with_tool_broker
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseCoordinator,
    WorkflowApprovalPauseProjection,
)
from apps.shell.agent.runtime.workflow_child_approvals import (
    WorkflowChildPendingApprovalProjection,
)
from apps.shell.agent.runtime.workflow_outcomes import WorkflowChildExecutionStatusProjection
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowNodePortBundle,
    WorkflowSubworkflowNodeExecution,
)
from apps.shell.agent.runtime.workflow_parallel import (
    WorkflowParallelExecutionPortBundle,
    WorkflowParallelNodeExecution,
)
from apps.shell.agent.runtime.workflow_ports import WorkflowContinuationPortBundle
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedCoordinator,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowProjectionPortBundle,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeCoordinator,
)
from apps.shell.agent.runtime.workflow_run_outcomes import WorkflowRunOutcomeProjector
from apps.shell.agent.runtime.workflow_state import (
    parallel_completed_agent_context,
    parallel_completed_artifact_exists,
    parallel_node_resume_context,
    workflow_context_chars,
    workflow_initial_cursor,
    workflow_path_index,
    workflow_steps_used,
)


class WorkflowContinuationCoordinator:
    """Executes Workflow nodes for a Workflow Run."""

    def __init__(
        self,
        engine: Any,
        *,
        ports: WorkflowContinuationPortBundle | None = None,
        iso_epoch: Any | None = None,
        workflow_path: Any | None = None,
        workflow_nodes_by_id: Any | None = None,
        workflow_next_node_id: Any | None = None,
        workflow_parallel_plan: Any | None = None,
        workflow_condition_selection: Any | None = None,
        workflow_loop_selection: Any | None = None,
        workflow_approval_criteria: Any | None = None,
        default_workspace_policy: Any | None = None,
        workflow_artifacts_dir: Any | None = None,
        workflow_artifact_path: Any | None = None,
        workflow_artifact_write: Any | None = None,
        workflow_agent_for_node: Any | None = None,
        workflow_node_task: Any | None = None,
        workflow_child_goal: Any | None = None,
        insert_run: Any | None = None,
        execute_agent_run: Any | None = None,
        workflow_child_artifact_refs: Any | None = None,
        merge_workflow_child_run_outcome: Any | None = None,
        workflow_for_node: Any | None = None,
        workflow_run_started_projection: Any | None = None,
        continue_workflow_run: Any | None = None,
        timeline_factory: Any | None = None,
        append_run_event: Any | None = None,
        update_run: Any | None = None,
        update_run_group: Any | None = None,
        get_run: Any | None = None,
        pending_approval_private: Any | None = None,
        approve_workflow_node: Any | None = None,
        runtime_limits: Any | None = None,
        workflow_loop_iterations_from_timeline: Any | None = None,
        workflow_loop_step_limit: Any | None = None,
        node_kind: Any | None = None,
    ) -> None:
        def port_value(value: Any | None, name: str) -> Any | None:
            if value is not None:
                return value
            if ports is None:
                return None
            return getattr(ports, name)

        self._engine = engine
        self._iso_epoch = port_value(iso_epoch, "iso_epoch") or _iso_epoch
        self._workflow_path_callback = port_value(workflow_path, "workflow_path")
        self._workflow_nodes_by_id_callback = port_value(
            workflow_nodes_by_id,
            "workflow_nodes_by_id",
        )
        self._workflow_next_node_id_callback = port_value(
            workflow_next_node_id,
            "workflow_next_node_id",
        )
        self._workflow_parallel_plan_callback = port_value(
            workflow_parallel_plan,
            "workflow_parallel_plan",
        )
        self._workflow_condition_selection_callback = port_value(
            workflow_condition_selection,
            "workflow_condition_selection",
        )
        self._workflow_loop_selection_callback = port_value(
            workflow_loop_selection,
            "workflow_loop_selection",
        )
        self._workflow_approval_criteria_callback = port_value(
            workflow_approval_criteria,
            "workflow_approval_criteria",
        )
        self._default_workspace_policy_callback = port_value(
            default_workspace_policy,
            "default_workspace_policy",
        )
        self._workflow_artifacts_dir_source = port_value(
            workflow_artifacts_dir,
            "workflow_artifacts_dir",
        )
        self._workflow_artifact_path_callback = port_value(
            workflow_artifact_path,
            "workflow_artifact_path",
        )
        self._workflow_artifact_write_callback = port_value(
            workflow_artifact_write,
            "workflow_artifact_write",
        )
        self._workflow_agent_for_node_callback = port_value(
            workflow_agent_for_node,
            "workflow_agent_for_node",
        )
        self._workflow_node_task_callback = port_value(workflow_node_task, "workflow_node_task")
        self._workflow_child_goal_callback = port_value(
            workflow_child_goal,
            "workflow_child_goal",
        )
        self._insert_run_callback = port_value(insert_run, "insert_run")
        self._execute_agent_run_callback = port_value(execute_agent_run, "execute_agent_run")
        self._workflow_child_artifact_refs_callback = port_value(
            workflow_child_artifact_refs,
            "workflow_child_artifact_refs",
        )
        self._merge_workflow_child_run_outcome_callback = port_value(
            merge_workflow_child_run_outcome,
            "merge_workflow_child_run_outcome",
        )
        self._workflow_for_node_callback = port_value(workflow_for_node, "workflow_for_node")
        self._workflow_run_started_projection_callback = port_value(
            workflow_run_started_projection,
            "workflow_run_started_projection",
        )
        self._continue_workflow_run_callback = port_value(
            continue_workflow_run,
            "continue_workflow_run",
        )
        self._timeline_callback = port_value(timeline_factory, "timeline_factory")
        self._append_run_event_callback = port_value(append_run_event, "append_run_event")
        self._update_run_callback = port_value(update_run, "update_run")
        self._update_run_group_callback = port_value(update_run_group, "update_run_group")
        self._get_run_callback = port_value(get_run, "get_run")
        self._pending_approval_private_callback = port_value(
            pending_approval_private,
            "pending_approval_private",
        )
        self._approve_workflow_node_callback = port_value(
            approve_workflow_node,
            "approve_workflow_node",
        )
        self._runtime_limits_source = port_value(runtime_limits, "runtime_limits")
        self._workflow_loop_iterations_from_timeline_callback = port_value(
            workflow_loop_iterations_from_timeline,
            "workflow_loop_iterations_from_timeline",
        )
        self._workflow_loop_step_limit_callback = port_value(
            workflow_loop_step_limit,
            "workflow_loop_step_limit",
        )
        self._node_kind_callback = port_value(node_kind, "node_kind")
        self._outcomes = WorkflowRunOutcomeProjector(
            engine,
            timeline_factory=self._timeline,
            append_run_event=self._append_run_event,
            update_run=self._update_run,
            update_run_group=self._update_run_group,
            get_run=self._get_run,
        )
        self._approval_pause = WorkflowApprovalPauseCoordinator(
            timeline_factory=self._timeline,
            append_run_event=self._append_run_event,
            update_run=self._update_run,
            update_run_group=self._update_run_group,
            get_run=self._get_run,
        )
        self._edge_followed = WorkflowEdgeFollowedCoordinator(
            node_kind=self._node_kind,
            append_run_event=self._append_run_event,
        )
        self._start_node = WorkflowStartNodeCoordinator(
            timeline_factory=self._timeline,
            append_run_event=self._append_run_event,
        )

    def _workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        if self._workflow_path_callback is not None:
            return self._workflow_path_callback(workflow)
        return self._engine._workflow_path(workflow)

    def _workflow_nodes_by_id(
        self,
        workflow: dict[str, Any],
        path: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if self._workflow_nodes_by_id_callback is not None:
            return self._workflow_nodes_by_id_callback(workflow)
        try:
            return self._engine._workflow_nodes_by_id(workflow)
        except AttributeError:
            return {
                str(node.get("id") or index): node
                for index, node in enumerate(path)
            }

    def _workflow_next_node_id(
        self,
        workflow: dict[str, Any],
        current_node: dict[str, Any],
        current_context: str,
        path: list[dict[str, Any]],
    ) -> str:
        if self._workflow_next_node_id_callback is not None:
            return str(
                self._workflow_next_node_id_callback(
                    workflow,
                    current_node,
                    current_context,
                )
                or ""
            )
        try:
            return str(
                self._engine._workflow_next_node_id(
                    workflow,
                    current_node,
                    current_context,
                )
                or ""
            )
        except AttributeError:
            try:
                current_index = path.index(current_node)
            except ValueError:
                return ""
            if current_index + 1 >= len(path):
                return ""
            return str(path[current_index + 1].get("id") or "")

    def _workflow_parallel_plan(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
    ) -> dict[str, Any]:
        if self._workflow_parallel_plan_callback is not None:
            return self._workflow_parallel_plan_callback(workflow, node)
        return self._engine._workflow_parallel_plan(workflow, node)

    def _workflow_condition_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        if self._workflow_condition_selection_callback is not None:
            return self._workflow_condition_selection_callback(workflow, node, context)
        return self._engine._workflow_condition_selection(workflow, node, context)

    def _workflow_loop_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
        *,
        previous_iterations: int,
    ) -> dict[str, Any]:
        if self._workflow_loop_selection_callback is not None:
            return self._workflow_loop_selection_callback(
                workflow,
                node,
                context,
                previous_iterations=previous_iterations,
            )
        return self._engine._workflow_loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )

    def _workflow_approval_criteria(self, node: dict[str, Any]) -> str:
        if self._workflow_approval_criteria_callback is not None:
            return str(self._workflow_approval_criteria_callback(node) or "").strip()
        return self._engine._workflow_approval_criteria(node)

    def _default_workspace_policy(self) -> dict[str, Any]:
        if self._default_workspace_policy_callback is not None:
            return self._default_workspace_policy_callback()
        return self._engine._default_workspace_policy()

    def _workflow_artifacts_dir(self) -> Any:
        source = self._workflow_artifacts_dir_source
        if source is not None:
            return source() if callable(source) else source
        return self._engine.workflow_artifacts_dir

    def _workflow_artifact_path(
        self,
        label: str,
        artifacts: list[dict[str, Any]],
        configured_path: str = "",
    ) -> str:
        if self._workflow_artifact_path_callback is not None:
            return str(
                self._workflow_artifact_path_callback(
                    label,
                    artifacts,
                    configured_path,
                )
                or ""
            )
        return self._engine._workflow_artifact_path(label, artifacts, configured_path)

    def _workflow_artifact_write(
        self,
        run: dict[str, Any],
        artifact_path: str,
        context: str,
    ) -> dict[str, Any]:
        if self._workflow_artifact_write_callback is not None:
            return self._workflow_artifact_write_callback(run, artifact_path, context)
        return write_artifact_with_tool_broker(
            tool_brokers=getattr(self._engine, "tool_brokers", None),
            run_id=str(run.get("run_id") or ""),
            workspace_policy=self._default_workspace_policy(),
            artifacts_dir=self._workflow_artifacts_dir(),
            artifact_path=artifact_path,
            content=context,
        )

    def _workflow_agent_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        if self._workflow_agent_for_node_callback is not None:
            return self._workflow_agent_for_node_callback(node)
        return self._engine._workflow_agent_for_node(node)

    def _workflow_node_task(self, node: dict[str, Any]) -> str:
        if self._workflow_node_task_callback is not None:
            return str(self._workflow_node_task_callback(node) or "")
        return self._engine._workflow_node_task(node)

    def _workflow_child_goal(self, workflow_goal: str, step_task: str) -> str:
        if self._workflow_child_goal_callback is not None:
            return str(self._workflow_child_goal_callback(workflow_goal, step_task) or "")
        return self._engine._workflow_child_goal(workflow_goal, step_task)

    def _insert_run(self, **fields: Any) -> dict[str, Any]:
        if self._insert_run_callback is not None:
            return self._insert_run_callback(**fields)
        return self._engine._insert_run(**fields)

    def _execute_agent_run(
        self,
        run_id: str,
        agent: dict[str, Any],
        user_goal: str,
        *,
        upstream: str,
        run_group_id: str = "",
        workflow_run_id: str = "",
    ) -> dict[str, Any]:
        if self._execute_agent_run_callback is not None:
            kwargs: dict[str, str] = {"upstream": upstream}
            if supports_keyword(self._execute_agent_run_callback, "run_group_id"):
                kwargs["run_group_id"] = run_group_id
            if workflow_run_id and supports_keyword(
                self._execute_agent_run_callback,
                "workflow_run_id",
            ):
                kwargs["workflow_run_id"] = workflow_run_id
            return self._execute_agent_run_callback(
                run_id,
                agent,
                user_goal,
                **kwargs,
            )
        return self._engine._execute_agent_run(
            run_id,
            agent,
            user_goal,
            upstream=upstream,
            run_group_id=run_group_id,
            workflow_run_id=workflow_run_id,
        )

    def _workflow_child_artifact_refs(
        self,
        child_run: dict[str, Any],
        label: str,
    ) -> list[dict[str, Any]]:
        if self._workflow_child_artifact_refs_callback is not None:
            return self._workflow_child_artifact_refs_callback(child_run, label)
        return self._engine._workflow_child_artifact_refs(child_run, label)

    def _merge_workflow_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        if self._merge_workflow_child_run_outcome_callback is not None:
            self._merge_workflow_child_run_outcome_callback(
                timeline,
                artifacts,
                child_run,
                label,
            )
            return
        self._engine._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)

    def _workflow_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        if self._workflow_for_node_callback is not None:
            return self._workflow_for_node_callback(node)
        return self._engine._workflow_for_node(node)

    def _workflow_run_started_projection(
        self,
        workflow_id: str,
        workflow: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if self._workflow_run_started_projection_callback is not None:
            return self._workflow_run_started_projection_callback(workflow_id, workflow)
        return self._engine.workflow_run_start_projector.started_projection(
            workflow_id,
            workflow,
        )

    def _continue_workflow_run(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._continue_workflow_run_callback is not None:
            return self._continue_workflow_run_callback(run, workflow, **kwargs)
        return self._engine._continue_workflow_run(run, workflow, **kwargs)

    def _timeline(self, event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
        if self._timeline_callback is not None:
            return self._timeline_callback(event, detail, **payload)
        return self._engine._timeline(event, detail, **payload)

    def _append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> Any:
        if self._append_run_event_callback is not None:
            return self._append_run_event_callback(run_id, event_type, payload)
        return self._engine.append_run_event(run_id, event_type, payload)

    def _update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        if self._update_run_callback is not None:
            return self._update_run_callback(run_id, **fields)
        return self._engine._update_run(run_id, **fields)

    def _update_run_group(self, run_group_id: str, **fields: Any) -> Any:
        if self._update_run_group_callback is not None:
            return self._update_run_group_callback(run_group_id, **fields)
        return self._engine._update_run_group(run_group_id, **fields)

    def _get_run(self, run_id: str) -> dict[str, Any]:
        if self._get_run_callback is not None:
            return self._get_run_callback(run_id)
        return self._engine.get_run(run_id)

    def _approve_workflow_node(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._approve_workflow_node_callback is not None:
            return self._approve_workflow_node_callback(run_id, **kwargs)
        return self._engine.approvals.approve_workflow_node(run_id, **kwargs)

    def _runtime_limits(self) -> RunBudgetLimits:
        source = self._runtime_limits_source
        if source is not None:
            return source() if callable(source) else source
        return getattr(self._engine, "runtime_limits", RunBudgetLimits())

    def _workflow_loop_iterations_from_timeline(
        self,
        timeline: list[dict[str, Any]],
    ) -> dict[str, int]:
        if self._workflow_loop_iterations_from_timeline_callback is not None:
            return self._workflow_loop_iterations_from_timeline_callback(timeline)
        try:
            return self._engine._workflow_loop_iterations_from_timeline(timeline)
        except AttributeError:
            return {}

    def _workflow_loop_step_limit(
        self,
        workflow: dict[str, Any],
        nodes_by_id: dict[str, dict[str, Any]],
    ) -> int:
        if self._workflow_loop_step_limit_callback is not None:
            return int(self._workflow_loop_step_limit_callback(workflow))
        try:
            return int(self._engine._workflow_loop_step_limit(workflow))
        except AttributeError:
            return len(nodes_by_id) + 1

    def _node_kind(self, node: dict[str, Any]) -> str:
        if self._node_kind_callback is not None:
            return self._node_kind_callback(node)
        return self._engine._node_kind(node)

    @staticmethod
    def _workflow_steps_used(timeline: list[dict[str, Any]]) -> int:
        return workflow_steps_used(timeline)

    @staticmethod
    def _workflow_context_chars(context: str) -> int:
        return workflow_context_chars(context)

    def _workflow_budget(
        self,
        run: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> WorkflowRunBudget:
        return WorkflowRunBudget(
            limits=self._runtime_limits(),
            started_at_epoch=self._iso_epoch(run.get("created_at")),
            steps_used=self._workflow_steps_used(timeline),
        )

    def continue_run(
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
    ) -> dict[str, Any]:
        engine = self._engine
        run_group_id = str(run.get("run_group_id") or "")
        current_node_info: dict[str, str] = {}
        try:
            workflow_goal = str(run.get("user_goal") or context)
            path = self._workflow_path(workflow)
            nodes_by_id = self._workflow_nodes_by_id(workflow, path)

            def next_node_id_for(current_node: dict[str, Any], current_context: str) -> str:
                return self._workflow_next_node_id(
                    workflow,
                    current_node,
                    current_context,
                    path,
                )

            cursor = workflow_initial_cursor(
                path,
                nodes_by_id,
                start_index=start_index,
                start_node_id=start_node_id,
            )
            node = cursor.node
            current_node_id = cursor.current_node_id
            has_agent_upstream = cursor.has_agent_upstream
            loop_iterations = self._workflow_loop_iterations_from_timeline(timeline)
            max_step_count = self._workflow_loop_step_limit(workflow, nodes_by_id)
            budget = self._workflow_budget(run, timeline)
            step_count = 0
            while node is not None:
                step_count += 1
                if step_count > max_step_count:
                    raise AgentRuntimeError("Workflow 执行步骤超过 Loop 上限")
                kind = self._node_kind(node)
                label = str((node.get("data") or {}).get("label") or node.get("id"))
                current_node_info = {
                    "workflow_node_id": str(node.get("id") or ""),
                    "workflow_node_kind": kind,
                    "workflow_node_label": label,
                }
                budget.check_context(self._workflow_context_chars(context))
                budget.claim_step()
                if kind == "start":
                    self._start_node.append(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        timeline=timeline,
                    )
                    next_id = next_node_id_for(node, context)
                    self._edge_followed.append(run, node, next_id)
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "agent":
                    result = self._run_agent_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        workflow_goal=workflow_goal,
                        context=context,
                        has_agent_upstream=has_agent_upstream,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                    )
                    if result.get("done"):
                        return result["run"]
                    context = str(result.get("context") or "")
                    has_agent_upstream = True
                    next_id = next_node_id_for(node, context)
                    self._edge_followed.append(run, node, next_id)
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "condition":
                    result = self._run_condition_node(
                        run,
                        workflow,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        timeline=timeline,
                    )
                    next_id = str(result.get("next_node_id") or "")
                    self._edge_followed.append(run, node, next_id, branch=str(result.get("branch") or ""))
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "loop":
                    result = self._run_loop_node(
                        run,
                        workflow,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        previous_iterations=loop_iterations.get(current_node_id, 0),
                        timeline=timeline,
                    )
                    loop_iterations[current_node_id] = int(result.get("iteration") or 0)
                    next_id = str(result.get("next_node_id") or "")
                    self._edge_followed.append(run, node, next_id, branch=str(result.get("branch") or ""))
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "parallel":
                    result = self._run_parallel_node(
                        run,
                        workflow,
                        node,
                        label=label,
                        kind=kind,
                        workflow_goal=workflow_goal,
                        context=context,
                        has_agent_upstream=has_agent_upstream,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                    )
                    if result.get("done"):
                        return result["run"]
                    context = str(result.get("context") or "")
                    has_agent_upstream = True
                    next_id = str(result.get("next_node_id") or "")
                    self._edge_followed.append(run, node, next_id, branch="join")
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "workflow":
                    result = self._run_workflow_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        workflow_goal=workflow_goal,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                    )
                    if result.get("done"):
                        return result["run"]
                    context = str(result.get("context") or "")
                    has_agent_upstream = True
                    next_id = next_node_id_for(node, context)
                    self._edge_followed.append(run, node, next_id)
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                if kind == "approval":
                    next_id = next_node_id_for(node, context)
                    return self._pause_for_approval_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                        node_index=self._path_index(path, str(node.get("id") or "")),
                        next_node_id=next_id,
                    )
                if kind == "artifact":
                    self._write_artifact_node(
                        run,
                        node,
                        label=label,
                        kind=kind,
                        context=context,
                        artifacts=artifacts,
                        timeline=timeline,
                    )
                    next_id = next_node_id_for(node, context)
                    self._edge_followed.append(run, node, next_id)
                    node = nodes_by_id.get(next_id) if next_id else None
                    current_node_id = next_id
                    continue
                raise AgentRuntimeError(f"未知 Workflow 节点类型：{kind}")
            return self._outcomes.completed(
                run,
                WorkflowRunCompletionProjection(context),
                timeline=timeline,
                artifacts=artifacts,
                root_group=root_group,
            )
        except Exception as exc:
            return self._outcomes.failed(
                run,
                WorkflowContinuationFailureProjection.from_error(exc, current_node_info),
                timeline=timeline,
                artifacts=artifacts,
                root_group=root_group,
            )

    @staticmethod
    def _path_index(path: list[dict[str, Any]], node_id: str) -> int:
        return workflow_path_index(path, node_id)

    def resume_after_approval_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
        start_node_id: str = "",
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        running = self._approve_workflow_node(
            run_id,
            timeline=timeline,
            artifacts=artifacts,
            result_context=context,
            workflow_node_id=workflow_node_id,
            label=label,
            criteria=criteria,
            input_preview=input_preview,
        )
        if root_group:
            self._update_run_group(
                str(run.get("run_group_id") or ""),
                status="running",
                summary=context,
            )
            running = self._get_run(run_id)
        return self.continue_run(
            running,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            start_node_id=start_node_id,
            root_group=root_group,
        )

    def project_background_failure(
        self,
        run: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        error: Any,
        root_group: bool,
    ) -> dict[str, Any]:
        return self._outcomes.background_failed(
            run,
            timeline=timeline,
            error=error,
            root_group=root_group,
        )

    @staticmethod
    def _parallel_node_resume_context(
        timeline: list[dict[str, Any]],
        *,
        parallel_node_id: str,
        fallback: str,
    ) -> str:
        return parallel_node_resume_context(
            timeline,
            parallel_node_id=parallel_node_id,
            fallback=fallback,
        )

    @staticmethod
    def _parallel_completed_agent_context(
        timeline: list[dict[str, Any]],
        *,
        parallel_node_id: str,
        branch_node_id: str,
    ) -> str | None:
        return parallel_completed_agent_context(
            timeline,
            parallel_node_id=parallel_node_id,
            branch_node_id=branch_node_id,
        )

    @staticmethod
    def _parallel_completed_artifact_exists(
        timeline: list[dict[str, Any]],
        *,
        parallel_node_id: str,
        branch_node_id: str,
    ) -> bool:
        return parallel_completed_artifact_exists(
            timeline,
            parallel_node_id=parallel_node_id,
            branch_node_id=branch_node_id,
        )

    def _run_agent_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        context: str,
        has_agent_upstream: bool,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
        node_info_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        agent = self._workflow_agent_for_node(node)
        step_task = self._workflow_node_task(node)
        handoff = WorkflowAgentNodeHandoff.from_agent(
            node,
            agent=agent,
            label=label,
            kind=kind,
            step_task=step_task,
            child_goal=self._workflow_child_goal(workflow_goal, step_task),
            context=context,
            has_agent_upstream=has_agent_upstream,
            node_info_extra=node_info_extra,
        )
        execution = WorkflowAgentNodeExecution.from_handoff(
            object(),
            handoff,
            run_group_id=run_group_id,
            workflow_run_id=str(run["run_id"]),
            prepare_child_run=lambda child: self._project_workflow_child_pending_context(
                child,
                run,
                handoff,
                run_group_id=run_group_id,
            ),
            ports=WorkflowNodePortBundle(
                insert_run=self._insert_run,
                execute_agent_run=self._execute_agent_run,
                workflow_child_artifact_refs=self._workflow_child_artifact_refs,
            ),
        )
        next_context = execution.next_context
        agent_payload = execution.agent_event_payload()
        if node_info_extra and str(node_info_extra.get("workflow_parent_node_id") or ""):
            agent_payload["workflow_node_context"] = next_context
        timeline.append(
            self._timeline(
                "workflow.node.agent",
                label,
                **agent_payload,
            )
        )
        self._append_run_event(str(run["run_id"]), "workflow.node.agent", agent_payload)
        self._merge_workflow_child_run_outcome(timeline, artifacts, execution.child_run, label)
        return self._apply_child_execution_status(
            run,
            execution,
            label=label,
            run_group_id=run_group_id,
            timeline=timeline,
            artifacts=artifacts,
            root_group=root_group,
        )

    def _project_workflow_child_pending_context(
        self,
        child: dict[str, Any],
        run: dict[str, Any],
        handoff: WorkflowAgentNodeHandoff,
        *,
        run_group_id: str,
    ) -> dict[str, Any]:
        private_pending = None
        child_run_id = str(child.get("run_id") or "").strip()
        if child_run_id and callable(self._pending_approval_private_callback):
            private_pending = self._pending_approval_private_callback(child_run_id)
        projection = WorkflowChildPendingApprovalProjection.from_child_run(
            child,
            workflow_run_id=str(run.get("run_id") or ""),
            node_info=handoff.node_info(),
            run_group_id=run_group_id,
            private_pending_approval=private_pending,
        )
        if projection is None:
            return child
        updated = projection.project(self._update_run)
        return {**child, **updated}

    def _apply_child_execution_status(
        self,
        run: dict[str, Any],
        execution: Any,
        *,
        label: str,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        projection = WorkflowChildExecutionStatusProjection.from_execution(
            execution,
            label=label,
        )
        if projection is None:
            return {"done": False, "context": str(getattr(execution, "next_context") or "")}
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(
            str(run["run_id"]),
            projection.event_type,
            projection.run_event_payload(),
        )
        result = self._update_run(
            str(run["run_id"]),
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            self._update_run_group(run_group_id, **projection.run_group_update_fields())
            result = self._get_run(result["run_id"])
        return {"done": True, "run": result}

    def _run_workflow_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        execution = WorkflowSubworkflowNodeExecution.from_node(
            object(),
            run,
            node,
            label=label,
            kind=kind,
            workflow_goal=workflow_goal,
            run_group_id=run_group_id,
            ports=WorkflowNodePortBundle(
                workflow_for_node=self._workflow_for_node,
                workflow_node_task=self._workflow_node_task,
                workflow_child_goal=self._workflow_child_goal,
                insert_run=self._insert_run,
                workflow_run_started_projection=self._workflow_run_started_projection,
                append_run_event=self._append_run_event,
                continue_workflow_run=self._continue_workflow_run,
                workflow_child_artifact_refs=self._workflow_child_artifact_refs,
            ),
        )
        payload = execution.event_payload()
        timeline.append(self._timeline("workflow.node.workflow", label, **payload))
        self._append_run_event(str(run["run_id"]), "workflow.node.workflow", payload)
        self._merge_workflow_child_run_outcome(timeline, artifacts, execution.child_run, label)
        return self._apply_child_execution_status(
            run,
            execution,
            label=label,
            run_group_id=run_group_id,
            timeline=timeline,
            artifacts=artifacts,
            root_group=root_group,
        )

    def _pause_for_approval_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
        node_index: int,
        next_node_id: str,
    ) -> dict[str, Any]:
        projection = WorkflowApprovalPauseProjection.from_criteria(
            node,
            label=label,
            kind=kind,
            criteria=self._workflow_approval_criteria(node),
            context=context,
            next_index=node_index + 1,
            next_node_id=next_node_id,
        )
        return self._approval_pause.pause(
            run,
            projection,
            run_group_id=run_group_id,
            timeline=timeline,
            artifacts=artifacts,
            root_group=root_group,
        )

    def _run_parallel_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        context: str,
        has_agent_upstream: bool,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        plan = self._workflow_parallel_plan(workflow, node)
        nodes_by_id = self._workflow_nodes_by_id(workflow, self._workflow_path(workflow))
        parallel_context = self._parallel_node_resume_context(
            timeline,
            parallel_node_id=str(node.get("id") or ""),
            fallback=context,
        )
        execution = WorkflowParallelNodeExecution.from_plan(
            run=run,
            node=node,
            plan=plan,
            nodes_by_id=nodes_by_id,
            label=label,
            kind=kind,
            workflow_goal=workflow_goal,
            context=context,
            parallel_context=parallel_context,
            has_agent_upstream=has_agent_upstream,
            run_group_id=run_group_id,
            timeline=timeline,
            artifacts=artifacts,
            root_group=root_group,
            ports=WorkflowParallelExecutionPortBundle(
                node_kind=self._node_kind,
                run_agent_node=self._run_agent_node,
                write_artifact_node=self._write_artifact_node,
                completed_agent_context=self._parallel_completed_agent_context,
                completed_artifact_exists=self._parallel_completed_artifact_exists,
            ),
        )
        if execution.done:
            return execution.early_result or {"done": True}
        projection = WorkflowParallelNodeProjection.from_plan(
            node,
            plan,
            execution.branch_results,
            label=label,
            kind=kind,
        )
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.parallel", projection.event_payload())
        return {
            "done": False,
            "context": execution.aggregate_context,
            "next_node_id": str(plan.get("join_node_id") or ""),
        }

    def _run_condition_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projection = WorkflowConditionNodeProjection.from_node(
            object(),
            workflow,
            node,
            label=label,
            kind=kind,
            context=context,
            ports=WorkflowProjectionPortBundle(
                workflow_condition_selection=self._workflow_condition_selection,
            ),
        )
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.condition", projection.event_payload())
        return {
            "branch": projection.branch,
            "next_node_id": projection.target_node_id,
        }

    def _run_loop_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        previous_iterations: int,
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projection = WorkflowLoopNodeProjection.from_node(
            object(),
            workflow,
            node,
            label=label,
            kind=kind,
            context=context,
            previous_iterations=previous_iterations,
            ports=WorkflowProjectionPortBundle(
                workflow_loop_selection=self._workflow_loop_selection,
            ),
        )
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.loop", projection.event_payload())
        return {
            "branch": projection.branch,
            "next_node_id": projection.target_node_id,
            "iteration": projection.iteration,
        }

    def _write_artifact_node(
        self,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        artifacts: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        node_info_extra: dict[str, str] | None = None,
    ) -> None:
        write = WorkflowArtifactNodeWrite.from_node(
            object(),
            run,
            node,
            label=label,
            kind=kind,
            context=context,
            artifacts=artifacts,
            node_info_extra=node_info_extra,
            ports=WorkflowNodePortBundle(
                workflow_artifact_path=self._workflow_artifact_path,
                workflow_artifact_write=self._workflow_artifact_write,
            ),
        )
        artifacts.append(write.artifact_record())
        timeline.append(write.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.artifact", write.event_payload())
