"""Tests for tool approval resume projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalClaimProjection,
    ToolApprovalContinuationHandoff,
    ToolApprovalContinuationOutcome,
    ToolApprovalCustomApiContinuationRequest,
    ToolApprovalExecutionFailureProjection,
    ToolApprovalExecutionFollowup,
    ToolApprovalExecutionRequest,
    ToolApprovalResumeContext,
    ToolApprovalTransitionContext,
)


def test_tool_approval_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.ToolApprovalResumeContext is ToolApprovalResumeContext
    assert agent_runtime.ToolApprovalClaimProjection is ToolApprovalClaimProjection
    assert agent_runtime.ToolApprovalExecutionRequest is ToolApprovalExecutionRequest
    assert agent_runtime.ToolApprovalContinuationHandoff is ToolApprovalContinuationHandoff
    assert (
        agent_runtime.ToolApprovalCustomApiContinuationRequest
        is ToolApprovalCustomApiContinuationRequest
    )
    assert agent_runtime.ToolApprovalContinuationOutcome is ToolApprovalContinuationOutcome
    assert (
        agent_runtime.ToolApprovalExecutionFailureProjection
        is ToolApprovalExecutionFailureProjection
    )
    assert agent_runtime.ToolApprovalExecutionFollowup is ToolApprovalExecutionFollowup
    assert agent_runtime.ToolApprovalTransitionContext is ToolApprovalTransitionContext
