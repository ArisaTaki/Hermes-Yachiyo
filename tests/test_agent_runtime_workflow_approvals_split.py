"""Tests for workflow approval projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)


def test_workflow_approval_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowApprovalTransitionContext is WorkflowApprovalTransitionContext
    assert agent_runtime.WorkflowApprovalResumeContext is WorkflowApprovalResumeContext
    assert agent_runtime.WorkflowApprovalResumeCoordinator is WorkflowApprovalResumeCoordinator
    assert agent_runtime.WorkflowApprovalPauseProjection is WorkflowApprovalPauseProjection
