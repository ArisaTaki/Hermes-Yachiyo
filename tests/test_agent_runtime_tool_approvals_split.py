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
    ToolPendingApprovalBuilder,
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
    assert agent_runtime.ToolPendingApprovalBuilder is ToolPendingApprovalBuilder
    assert agent_runtime.ToolApprovalTransitionContext is ToolApprovalTransitionContext


def test_tool_pending_approval_builder_snapshots_private_payloads() -> None:
    builder = ToolPendingApprovalBuilder(
        approval_id_factory=lambda: "approval_fixed",
        now=lambda: "2026-06-15T10:00:00Z",
    )
    messages = [{"role": "user", "content": "run", "meta": {"turn": 1}}]
    tool_request = {
        "tool": "terminal_run",
        "input": {"command": "printf ok", "options": {"timeout": 3}},
    }
    remaining = [{"tool": "artifact.write", "input": {"path": "report.md", "content": "ok"}}]

    pending = builder.build(
        tool_request,
        messages=messages,
        next_iteration=999,
        remaining_tool_requests=remaining,
    )

    assert pending["approval_id"] == "approval_fixed"
    assert pending["tool"] == "terminal.run"
    assert pending["requested_at"] == "2026-06-15T10:00:00Z"
    assert pending["input"] == {"command": "printf ok", "options": {"timeout": 3}}
    assert pending["input_preview"] == {"command": "printf ok", "options": {"timeout": 3}}
    assert pending["messages"] == messages
    assert pending["tool_request"] == {
        "tool": "terminal_run",
        "input": {"command": "printf ok", "options": {"timeout": 3}},
    }
    assert pending["remaining_tool_requests"] == remaining
    assert pending["next_iteration"] == 50

    messages[0]["meta"]["turn"] = 2
    tool_request["input"]["command"] = "changed"
    remaining[0]["input"]["content"] = "changed"

    assert pending["messages"][0]["meta"]["turn"] == 1
    assert pending["tool_request"]["input"]["command"] == "printf ok"
    assert pending["remaining_tool_requests"][0]["input"]["content"] == "ok"
