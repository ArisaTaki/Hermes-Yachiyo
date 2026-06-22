"""Pure Workflow continuation state helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.budget import json_chars
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value

_STEP_COUNTER_EXCLUDED_EVENTS = {
    "workflow.node.approval_rejected",
    "workflow.node.approval_timeout",
}


def workflow_steps_used(timeline: list[dict[str, Any]]) -> int:
    return sum(
        1
        for event in timeline
        if isinstance(event, dict)
        and str(event.get("event") or "").startswith("workflow.node.")
        and str(event.get("event") or "") not in _STEP_COUNTER_EXCLUDED_EVENTS
    )


def workflow_context_chars(context: str) -> int:
    return json_chars(redact_json_value({"context": context}))


def workflow_path_index(path: list[dict[str, Any]], node_id: str) -> int:
    for index, node in enumerate(path):
        if str(node.get("id") or "") == node_id:
            return index
    return len(path)


@dataclass(frozen=True)
class WorkflowContinuationCursor:
    """Initial cursor for continuing a Workflow run."""

    node: dict[str, Any] | None
    current_node_id: str
    has_agent_upstream: bool


def workflow_initial_cursor(
    path: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    *,
    start_index: int,
    start_node_id: str = "",
) -> WorkflowContinuationCursor:
    if start_index < 0 or start_index > len(path):
        raise AgentRuntimeError("Workflow Run 待审批恢复位置无效")
    if start_node_id:
        node = nodes_by_id.get(start_node_id)
        if node is None:
            raise AgentRuntimeError("Workflow Run 待审批恢复节点不存在")
        return WorkflowContinuationCursor(
            node=node,
            current_node_id=start_node_id,
            has_agent_upstream=True,
        )
    if start_index < len(path):
        node = path[start_index]
        return WorkflowContinuationCursor(
            node=node,
            current_node_id=str(node.get("id") or ""),
            has_agent_upstream=start_index > 0,
        )
    return WorkflowContinuationCursor(
        node=None,
        current_node_id="",
        has_agent_upstream=start_index > 0,
    )


def parallel_node_resume_context(
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


def parallel_completed_agent_context(
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


def parallel_completed_artifact_exists(
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


__all__ = [
    "parallel_completed_agent_context",
    "parallel_completed_artifact_exists",
    "parallel_node_resume_context",
    "WorkflowContinuationCursor",
    "workflow_context_chars",
    "workflow_initial_cursor",
    "workflow_path_index",
    "workflow_steps_used",
]
