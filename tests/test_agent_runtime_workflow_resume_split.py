"""Tests for workflow resume coordinators split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_resume import (
    RunTransitionProjectionCoordinator,
    WorkflowParentRunLocator,
    WorkflowResumePlanner,
)


def test_workflow_resume_coordinators_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RunTransitionProjectionCoordinator is RunTransitionProjectionCoordinator
    assert agent_runtime.WorkflowParentRunLocator is WorkflowParentRunLocator
    assert agent_runtime.WorkflowResumePlanner is WorkflowResumePlanner


def test_workflow_resume_planner_resolves_next_node_from_node_or_id() -> None:
    workflow = {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "agent-a", "type": "agent"},
            {"id": "artifact", "type": "artifact"},
        ]
    }
    next_node_calls: list[dict[str, object]] = []
    planner = WorkflowResumePlanner(
        get_workflow=lambda workflow_id: {"workflow_id": workflow_id},
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        node_kind=lambda node: str(node.get("type") or ""),
        next_node_id=lambda _workflow, node, context: next_node_calls.append(
            {"node_id": node.get("id"), "context": context}
        )
        or {
            "start": "agent-a",
            "agent-a": "artifact",
        }.get(str(node.get("id") or ""), ""),
    )

    assert planner.next_node_id(workflow, "start", "first context") == "agent-a"
    assert planner.next_node_id(workflow, {"id": "agent-a", "type": "agent"}, "second") == "artifact"
    assert planner.next_node_id(workflow, "missing", "third") == ""
    assert next_node_calls == [
        {"node_id": "start", "context": "first context"},
        {"node_id": "agent-a", "context": "second"},
    ]
