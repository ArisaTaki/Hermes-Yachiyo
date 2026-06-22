"""Workflow parallel branch execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_projections import WorkflowParallelBranchProjection


@dataclass(frozen=True)
class WorkflowParallelExecutionPortBundle:
    """Callbacks used to execute Workflow parallel branch nodes."""

    node_kind: Any
    run_agent_node: Any
    write_artifact_node: Any
    completed_agent_context: Any
    completed_artifact_exists: Any


@dataclass(frozen=True)
class WorkflowParallelNodeExecution:
    """Execution result for a Workflow parallel node."""

    branch_results: list[dict[str, str]]
    aggregate_context: str
    early_result: dict[str, Any] | None = None

    @property
    def done(self) -> bool:
        return self.early_result is not None

    @classmethod
    def from_plan(
        cls,
        *,
        run: dict[str, Any],
        node: dict[str, Any],
        plan: dict[str, Any],
        nodes_by_id: dict[str, dict[str, Any]],
        label: str,
        kind: str,
        workflow_goal: str,
        context: str,
        parallel_context: str,
        has_agent_upstream: bool,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
        ports: WorkflowParallelExecutionPortBundle,
    ) -> "WorkflowParallelNodeExecution":
        parallel_node_id = str(node.get("id") or "")
        branch_results: list[dict[str, str]] = []
        for branch in plan.get("branches") or []:
            branch_context = parallel_context
            branch_projection = WorkflowParallelBranchProjection.from_branch(
                node,
                branch,
                label=label,
                kind=kind,
                context=parallel_context,
            )
            for branch_node_id in branch.get("node_ids") or []:
                branch_node_id_text = str(branch_node_id)
                branch_node = nodes_by_id.get(branch_node_id_text)
                if branch_node is None:
                    raise AgentRuntimeError(f"Parallel 分支引用了不存在的节点：{branch_node_id}")
                branch_kind = ports.node_kind(branch_node)
                branch_node_label = str(
                    (branch_node.get("data") or {}).get("label") or branch_node.get("id")
                )
                node_info_extra = branch_projection.child_node_info()
                if branch_kind == "agent":
                    completed_context = ports.completed_agent_context(
                        timeline,
                        parallel_node_id=parallel_node_id,
                        branch_node_id=branch_node_id_text,
                    )
                    if completed_context is not None:
                        branch_context = completed_context
                        continue
                    result = ports.run_agent_node(
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
                        return cls(
                            branch_results=branch_results,
                            aggregate_context=context,
                            early_result=result,
                        )
                    branch_context = str(result.get("context") or "")
                    continue
                if branch_kind == "artifact":
                    if ports.completed_artifact_exists(
                        timeline,
                        parallel_node_id=parallel_node_id,
                        branch_node_id=branch_node_id_text,
                    ):
                        continue
                    ports.write_artifact_node(
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
            branch_results.append(branch_projection.result_payload(branch_context))
        return cls(
            branch_results=branch_results,
            aggregate_context=WorkflowParallelBranchProjection.aggregate_context(
                label,
                branch_results,
                fallback=context,
            ),
        )

