"""Tests for workflow start projector split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_start import WorkflowRunStartProjector


def test_workflow_run_start_projector_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowRunStartProjector is WorkflowRunStartProjector
