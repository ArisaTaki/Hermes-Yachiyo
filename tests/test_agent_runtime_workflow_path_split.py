"""Tests for workflow path planner split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_path import WorkflowPathPlanner


def test_workflow_path_planner_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowPathPlanner is WorkflowPathPlanner
