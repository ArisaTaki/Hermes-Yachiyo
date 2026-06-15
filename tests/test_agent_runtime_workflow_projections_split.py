"""Tests for workflow timeline projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)


def test_workflow_timeline_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowStartNodeProjection is WorkflowStartNodeProjection
    assert agent_runtime.WorkflowConditionNodeProjection is WorkflowConditionNodeProjection
    assert agent_runtime.WorkflowParallelNodeProjection is WorkflowParallelNodeProjection
    assert agent_runtime.WorkflowLoopNodeProjection is WorkflowLoopNodeProjection
    assert agent_runtime.WorkflowRunCompletionProjection is WorkflowRunCompletionProjection
    assert (
        agent_runtime.WorkflowContinuationFailureProjection
        is WorkflowContinuationFailureProjection
    )
