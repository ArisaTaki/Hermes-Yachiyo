"""Tests for workflow path planner split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_path import WorkflowDefinitionValidator, WorkflowPathPlanner


def test_workflow_path_planner_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowPathPlanner is WorkflowPathPlanner
    assert agent_runtime.WorkflowDefinitionValidator is WorkflowDefinitionValidator


def test_workflow_definition_validator_rejects_non_loop_cycle() -> None:
    validator = WorkflowDefinitionValidator(node_kind=_node_kind)
    nodes = [
        {"id": "start", "type": "start", "data": {"label": "Start"}},
        {"id": "a", "type": "agent", "data": {"label": "A"}},
        {"id": "b", "type": "agent", "data": {"label": "B"}},
    ]

    with pytest.raises(AgentRuntimeError, match="不能包含非 Loop 控制的环"):
        validator.validate(
            nodes,
            [
                {"source": "start", "target": "a"},
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        )


def test_workflow_definition_validator_allows_loop_continue_cycle() -> None:
    validator = WorkflowDefinitionValidator(node_kind=_node_kind)

    assert validator.validate(
        [
            {"id": "start", "type": "start", "data": {"label": "Start"}},
            {"id": "a", "type": "agent", "data": {"label": "A"}},
            {
                "id": "repeat",
                "type": "loop",
                "data": {"label": "Repeat", "condition": "again", "max_iterations": 2},
            },
            {"id": "done", "type": "artifact", "data": {"label": "Done"}},
        ],
        [
            {"source": "start", "target": "a"},
            {"source": "a", "target": "repeat"},
            {"source": "repeat", "target": "a", "data": {"branch": "continue"}},
            {"source": "repeat", "target": "done", "data": {"branch": "exit"}},
        ],
    ) == {"ok": True}


def _node_kind(node: dict[str, object]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
    node_type = str(node.get("type") or "").strip()
    if data_kind and node_type in {"", "input", "default", "output"}:
        return data_kind
    return node_type or data_kind
