"""Tests for workflow node handoffs split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowSubworkflowNodeExecution,
)


def test_workflow_node_handoffs_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowAgentNodeHandoff is WorkflowAgentNodeHandoff
    assert agent_runtime.WorkflowAgentNodeExecution is WorkflowAgentNodeExecution
    assert agent_runtime.WorkflowSubworkflowNodeExecution is WorkflowSubworkflowNodeExecution
    assert agent_runtime.WorkflowArtifactNodeWrite is WorkflowArtifactNodeWrite
