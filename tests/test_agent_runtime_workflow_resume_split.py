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
