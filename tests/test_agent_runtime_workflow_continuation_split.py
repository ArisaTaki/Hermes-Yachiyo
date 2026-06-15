"""Tests for workflow continuation coordinator split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator


def test_workflow_continuation_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowContinuationCoordinator is WorkflowContinuationCoordinator
