"""Workflow continuation orchestration for Workflow Runs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.budget import RunBudgetLimits, WorkflowRunBudget
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value, redact_secrets
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalPauseProjection
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowSubworkflowNodeExecution,
)
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)
from apps.shell.agent.runtime.workflow_run_outcomes import WorkflowRunOutcomeProjector
from apps.shell.agent.tools.broker import ToolBroker


def _iso_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


def _json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


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
    approve_workflow_node: Any | None = None
    runtime_limits: Any | None = None
    workflow_loop_iterations_from_timeline: Any | None = None
    workflow_loop_step_limit: Any | None = None
    node_kind: Any | None = None


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
        broker = ToolBroker(
            self._default_workspace_policy(),
            Path(self._workflow_artifacts_dir()) / str(run["run_id"]),
        )
        return broker.artifact_write(artifact_path, context)

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
    ) -> dict[str, Any]:
        if self._execute_agent_run_callback is not None:
            return self._execute_agent_run_callback(
                run_id,
                agent,
                user_goal,
                upstream=upstream,
            )
        return self._engine._execute_agent_run(
            run_id,
            agent,
            user_goal,
            upstream=upstream,
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
        return sum(
            1
            for event in timeline
            if isinstance(event, dict)
            and str(event.get("event") or "").startswith("workflow.node.")
            and str(event.get("event") or "") not in {
                "workflow.node.approval_rejected",
                "workflow.node.approval_timeout",
            }
        )

    @staticmethod
    def _workflow_context_chars(context: str) -> int:
        return _json_chars(redact_json_value({"context": context}))

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
            if start_index < 0 or start_index > len(path):
                raise AgentRuntimeError("Workflow Run 待审批恢复位置无效")
            nodes_by_id = self._workflow_nodes_by_id(workflow, path)

            def next_node_id_for(current_node: dict[str, Any], current_context: str) -> str:
                return self._workflow_next_node_id(
                    workflow,
                    current_node,
                    current_context,
                    path,
                )

            def append_edge_followed(current_node: dict[str, Any], next_node_id: str, branch: str = "") -> None:
                source_node_id = str(current_node.get("id") or "")
                if not source_node_id or not next_node_id:
                    return
                source_kind = self._node_kind(current_node)
                source_label = str((current_node.get("data") or {}).get("label") or source_node_id)
                projection = WorkflowEdgeFollowedProjection.from_node(
                    current_node,
                    label=source_label,
                    kind=source_kind,
                    target_node_id=next_node_id,
                    branch=branch,
                )
                self._append_run_event(
                    str(run["run_id"]),
                    "workflow.edge.followed",
                    projection.event_payload(),
                )

            if start_node_id:
                node = nodes_by_id.get(start_node_id)
                if node is None:
                    raise AgentRuntimeError("Workflow Run 待审批恢复节点不存在")
                current_node_id = start_node_id
                has_agent_upstream = True
            elif start_index < len(path):
                node = path[start_index]
                current_node_id = str(node.get("id") or "")
                has_agent_upstream = start_index > 0
            else:
                node = None
                current_node_id = ""
                has_agent_upstream = start_index > 0
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
                    projection = WorkflowStartNodeProjection.from_node(node, label=label, kind=kind)
                    timeline.append(projection.timeline_event(self._timeline))
                    self._append_run_event(
                        str(run["run_id"]),
                        "workflow.node.start",
                        projection.event_payload(),
                    )
                    next_id = next_node_id_for(node, context)
                    append_edge_followed(node, next_id)
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
                    append_edge_followed(node, next_id)
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
                    append_edge_followed(node, next_id, str(result.get("branch") or ""))
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
                    append_edge_followed(node, next_id, str(result.get("branch") or ""))
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
                    append_edge_followed(node, next_id, "join")
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
                    append_edge_followed(node, next_id)
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
                    append_edge_followed(node, next_id)
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
        for index, node in enumerate(path):
            if str(node.get("id") or "") == node_id:
                return index
        return len(path)

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
        if not parallel_node_id:
            return fallback
        for event in reversed(timeline):
            if not isinstance(event, dict):
                continue
            if str(event.get("workflow_parent_node_id") or "") != parallel_node_id:
                continue
            context = str(event.get("workflow_parent_node_context") or "")
            if context:
                return context
        return fallback

    @staticmethod
    def _parallel_completed_agent_context(
        timeline: list[dict[str, Any]],
        *,
        parallel_node_id: str,
        branch_node_id: str,
    ) -> str | None:
        if not parallel_node_id or not branch_node_id:
            return None
        for event in reversed(timeline):
            if not isinstance(event, dict):
                continue
            if event.get("event") != "workflow.node.agent":
                continue
            if str(event.get("workflow_parent_node_id") or "") != parallel_node_id:
                continue
            if str(event.get("workflow_node_id") or "") != branch_node_id:
                continue
            if str(event.get("status") or "") != "completed":
                continue
            return str(event.get("workflow_node_context") or event.get("result") or "")
        return None

    @staticmethod
    def _parallel_completed_artifact_exists(
        timeline: list[dict[str, Any]],
        *,
        parallel_node_id: str,
        branch_node_id: str,
    ) -> bool:
        if not parallel_node_id or not branch_node_id:
            return False
        return any(
            isinstance(event, dict)
            and event.get("event") == "workflow.node.artifact"
            and str(event.get("workflow_parent_node_id") or "") == parallel_node_id
            and str(event.get("workflow_node_id") or "") == branch_node_id
            and str(event.get("status") or "") == "completed"
            for event in timeline
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
        child = self._insert_run(
            kind="agent_run",
            runnable_id=handoff.agent_id,
            user_goal=handoff.child_goal,
            run_group_id=run_group_id,
        )
        child = self._execute_agent_run(
            child["run_id"],
            handoff.agent,
            handoff.child_goal,
            upstream=handoff.upstream,
        )
        execution = WorkflowAgentNodeExecution.from_child_run(
            handoff,
            child,
            artifact_count=len(self._workflow_child_artifact_refs(child, handoff.node_label)),
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
        if execution.status == "approval_required":
            event_payload = execution.status_event_payload()
            timeline.append(
                self._timeline(
                    "workflow.run.approval_required",
                    label,
                    **event_payload,
                )
            )
            self._append_run_event(
                str(run["run_id"]),
                "workflow.run.approval_required",
                event_payload,
            )
            result = self._update_run(
                str(run["run_id"]),
                status="approval_required",
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(
                    run_group_id,
                    status="approval_required",
                    summary=next_context,
                )
                result = self._get_run(result["run_id"])
            return {"done": True, "run": result}
        if execution.status != "completed":
            status = "cancelled" if execution.status == "cancelled" else "failed"
            detail = f"{label}: {next_context or execution.status}"
            timeline.append(
                self._timeline(
                    f"workflow.run.{status}",
                    detail,
                    **execution.status_event_payload(),
                )
            )
            self._append_run_event(
                str(run["run_id"]),
                f"workflow.run.{status}",
                {
                    **execution.status_event_payload(),
                    "result": _tool_input_preview(next_context or execution.status, limit=1800),
                },
            )
            result = self._update_run(
                str(run["run_id"]),
                status=status,
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status=status, summary=next_context)
                result = self._get_run(result["run_id"])
            return {"done": True, "run": result}
        return {"done": False, "context": next_context}

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
        child_workflow = self._workflow_for_node(node)
        workflow_id = str(child_workflow.get("workflow_id") or "")
        step_task = self._workflow_node_task(node)
        child_goal = self._workflow_child_goal(workflow_goal, step_task)
        child = self._insert_run(
            kind="workflow_run",
            runnable_id=workflow_id,
            user_goal=child_goal,
            run_group_id=run_group_id,
        )
        child_timeline, started_payload = self._workflow_run_started_projection(
            workflow_id,
            child_workflow,
        )
        self._append_run_event(child["run_id"], "workflow.run.started", started_payload)
        child = self._continue_workflow_run(
            child,
            child_workflow,
            context=child_goal,
            timeline=child_timeline,
            artifacts=[],
            start_index=0,
            root_group=False,
        )
        execution = WorkflowSubworkflowNodeExecution.from_child_run(
            node,
            child_workflow=child_workflow,
            child_run=child,
            label=label,
            kind=kind,
            step_task=step_task,
            child_goal=child_goal,
            artifact_count=len(self._workflow_child_artifact_refs(child, label)),
        )
        next_context = execution.next_context
        payload = execution.event_payload()
        timeline.append(self._timeline("workflow.node.workflow", label, **payload))
        self._append_run_event(str(run["run_id"]), "workflow.node.workflow", payload)
        self._merge_workflow_child_run_outcome(timeline, artifacts, execution.child_run, label)
        if execution.status == "approval_required":
            event_payload = execution.status_event_payload()
            timeline.append(
                self._timeline(
                    "workflow.run.approval_required",
                    label,
                    **event_payload,
                )
            )
            self._append_run_event(str(run["run_id"]), "workflow.run.approval_required", event_payload)
            result = self._update_run(
                str(run["run_id"]),
                status="approval_required",
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status="approval_required", summary=next_context)
                result = self._get_run(result["run_id"])
            return {"done": True, "run": result}
        if execution.status != "completed":
            status = "cancelled" if execution.status == "cancelled" else "failed"
            detail = f"{label}: {next_context or execution.status}"
            timeline.append(
                self._timeline(
                    f"workflow.run.{status}",
                    detail,
                    **execution.status_event_payload(),
                )
            )
            self._append_run_event(
                str(run["run_id"]),
                f"workflow.run.{status}",
                {
                    **execution.status_event_payload(),
                    "result": _tool_input_preview(next_context or execution.status, limit=1800),
                },
            )
            result = self._update_run(
                str(run["run_id"]),
                status=status,
                result=next_context,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status=status, summary=next_context)
                result = self._get_run(result["run_id"])
            return {"done": True, "run": result}
        return {"done": False, "context": next_context}

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
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(
            str(run["run_id"]),
            "workflow.node.approval_required",
            projection.event_payload(),
        )
        result = self._update_run(
            str(run["run_id"]),
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            self._update_run_group(
                run_group_id,
                status="approval_required",
                summary=projection.result_text(),
            )
            result = self._get_run(result["run_id"])
        return result

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
        parallel_node_id = str(node.get("id") or "")
        parallel_context = self._parallel_node_resume_context(
            timeline,
            parallel_node_id=parallel_node_id,
            fallback=context,
        )
        branch_results: list[dict[str, str]] = []
        for branch in plan.get("branches") or []:
            branch_context = parallel_context
            branch_entry_node_id = str(branch.get("entry_node_id") or "")
            branch_label = str(branch.get("label") or branch.get("entry_node_id") or "Branch")
            for branch_node_id in branch.get("node_ids") or []:
                branch_node_id_text = str(branch_node_id)
                branch_node = nodes_by_id.get(branch_node_id_text)
                if branch_node is None:
                    raise AgentRuntimeError(f"Parallel 分支引用了不存在的节点：{branch_node_id}")
                branch_kind = self._node_kind(branch_node)
                branch_node_label = str((branch_node.get("data") or {}).get("label") or branch_node.get("id"))
                node_info_extra = {
                    "workflow_parent_node_id": parallel_node_id,
                    "workflow_parent_node_kind": kind,
                    "workflow_parent_node_label": label,
                    "workflow_parallel_branch_entry_node_id": branch_entry_node_id,
                    "workflow_parallel_branch_label": branch_label,
                    "workflow_parent_node_context": parallel_context,
                }
                if branch_kind == "agent":
                    completed_context = self._parallel_completed_agent_context(
                        timeline,
                        parallel_node_id=parallel_node_id,
                        branch_node_id=branch_node_id_text,
                    )
                    if completed_context is not None:
                        branch_context = completed_context
                        continue
                    result = self._run_agent_node(
                        run,
                        branch_node,
                        label=branch_node_label,
                        kind=branch_kind,
                        workflow_goal=workflow_goal,
                        context=branch_context,
                        has_agent_upstream=has_agent_upstream,
                        run_group_id=run_group_id,
                        timeline=timeline,
                        artifacts=artifacts,
                        root_group=root_group,
                        node_info_extra=node_info_extra,
                    )
                    if result.get("done"):
                        return result
                    branch_context = str(result.get("context") or "")
                    continue
                if branch_kind == "artifact":
                    if self._parallel_completed_artifact_exists(
                        timeline,
                        parallel_node_id=parallel_node_id,
                        branch_node_id=branch_node_id_text,
                    ):
                        continue
                    self._write_artifact_node(
                        run,
                        branch_node,
                        label=branch_node_label,
                        kind=branch_kind,
                        context=branch_context,
                        artifacts=artifacts,
                        timeline=timeline,
                        node_info_extra=node_info_extra,
                    )
                    continue
                raise AgentRuntimeError(
                    f"Parallel 分支暂不支持 {branch_kind or 'unknown'} 节点：{branch_node_label}"
                )
            branch_results.append(
                {
                    "entry_node_id": str(branch.get("entry_node_id") or ""),
                    "label": branch_label,
                    "result": _tool_input_preview(branch_context, limit=1800),
                }
            )
        aggregate_context = "\n".join(
            f"- {item['label']}: {item['result']}"
            for item in branch_results
        ).strip()
        if aggregate_context:
            aggregate_context = f"Parallel {label} results:\n{aggregate_context}"
        else:
            aggregate_context = context
        projection = WorkflowParallelNodeProjection.from_plan(
            node,
            plan,
            branch_results,
            label=label,
            kind=kind,
        )
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.parallel", projection.event_payload())
        return {
            "done": False,
            "context": aggregate_context,
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
        selection = self._workflow_condition_selection(workflow, node, context)
        projection = WorkflowConditionNodeProjection.from_selection(
            node,
            selection,
            label=label,
            kind=kind,
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
        selection = self._workflow_loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )
        projection = WorkflowLoopNodeProjection.from_selection(
            node,
            selection,
            label=label,
            kind=kind,
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
        artifact_path = self._workflow_artifact_path(
            label,
            artifacts,
            WorkflowArtifactNodeWrite.configured_path(node),
        )
        write = WorkflowArtifactNodeWrite.from_artifact(
            node,
            self._workflow_artifact_write(run, artifact_path, context),
            label=label,
            kind=kind,
            node_info_extra=node_info_extra,
        )
        artifacts.append(write.artifact_record())
        timeline.append(write.timeline_event(self._timeline))
        self._append_run_event(str(run["run_id"]), "workflow.node.artifact", write.event_payload())
