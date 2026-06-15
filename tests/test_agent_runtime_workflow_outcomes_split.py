"""Tests for workflow outcome projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_outcomes import (
    WorkflowChildOutcomeCoordinator,
    WorkflowChildRunProjection,
    WorkflowChildStatusProjection,
    WorkflowParentResumeFailureProjection,
)


def test_workflow_outcome_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowChildOutcomeCoordinator is WorkflowChildOutcomeCoordinator
    assert agent_runtime.WorkflowChildRunProjection is WorkflowChildRunProjection
    assert agent_runtime.WorkflowChildStatusProjection is WorkflowChildStatusProjection
    assert (
        agent_runtime.WorkflowParentResumeFailureProjection
        is WorkflowParentResumeFailureProjection
    )
