"""Tests for workflow path planner split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_path import (
    WorkflowDefinitionValidator,
    WorkflowPathPlanner,
    workflow_node_kind,
)


def test_workflow_path_planner_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowPathPlanner is WorkflowPathPlanner
    assert agent_runtime.WorkflowDefinitionValidator is WorkflowDefinitionValidator
    assert agent_runtime._workflow_node_kind is workflow_node_kind


def test_workflow_node_kind_normalizes_legacy_node_shapes() -> None:
    assert workflow_node_kind({"id": "start", "type": "start"}) == "start"
    assert workflow_node_kind({"id": "agent", "type": "input", "data": {"kind": "agent"}}) == "agent"
    assert workflow_node_kind({"id": "workflow", "type": "", "data": {"node_type": "workflow"}}) == "workflow"


def test_workflow_definition_validator_rejects_non_loop_cycle() -> None:
    validator = WorkflowDefinitionValidator(node_kind=workflow_node_kind)
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
    validator = WorkflowDefinitionValidator(node_kind=workflow_node_kind)

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
