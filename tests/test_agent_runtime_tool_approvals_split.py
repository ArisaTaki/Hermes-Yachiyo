"""Tests for tool approval resume projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.runtime.tool_approvals import (
    _tool_input_preview,
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
    assert _tool_input_preview is tool_input_preview


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


def test_tool_pending_approval_builder_preserves_runtime_context() -> None:
    builder = ToolPendingApprovalBuilder(
        approval_id_factory=lambda: "approval_context",
        now=lambda: "2026-06-15T10:00:00Z",
    )
    tool_request = {
        "tool": "desktop.click_ui_element",
        "input": {"label": "Save"},
        "source": "runtime_planner",
        "planning_reason": "planner_selected_foreground_operation",
        "decision_id": "decision-1",
        "plan_id": "runtime-plan-1",
        "tool_plan_id": "tool-plan-1",
        "intent_kind": "desktop_operation",
        "step_id": "save-file",
        "capability_id": "desktop.ui_operation",
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Save",
        "runtime_stage": "operate",
        "runtime_role": "click_ui",
        "requires_post_action_verification": True,
        "replan_triggers": ["ui_not_found"],
    }

    pending = builder.build(
        tool_request,
        messages=[{"role": "user", "content": "save"}],
        next_iteration=2,
        remaining_tool_requests=[],
    )

    for key in (
        "source",
        "planning_reason",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "step_id",
        "capability_id",
        "core_id",
        "workspace_id",
        "task_id",
        "group_id",
        "group_run_id",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "runtime_stage",
        "runtime_role",
    ):
        assert pending[key] == tool_request[key]
        assert pending["input_preview"][key] == tool_request[key]
    assert pending["requires_post_action_verification"] is True
    assert pending["input_preview"]["requires_post_action_verification"] is True
    assert pending["replan_triggers"] == ["ui_not_found"]
    assert pending["input_preview"]["replan_triggers"] == ["ui_not_found"]


def test_tool_approval_resume_context_preserves_pending_input_preview_context() -> None:
    pending = {
        "approval_id": "approval-context",
        "tool": "desktop.click_ui_element",
        "messages": [{"role": "user", "content": "save"}],
        "tool_request": {
            "tool": "desktop.click_ui_element",
            "input": {"label": "Save"},
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "step_id": "save-file",
            "capability_id": "desktop.ui_operation",
            "group_run_id": "group-run-1",
            "workflow_run_id": "workflow-run-1",
        },
        "input_preview": {
            "label": "Save",
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "step_id": "save-file",
            "capability_id": "desktop.ui_operation",
            "group_run_id": "group-run-1",
            "workflow_run_id": "workflow-run-1",
        },
        "remaining_tool_requests": [],
        "next_iteration": 3,
    }

    context = ToolApprovalResumeContext.from_run(
        {"run_id": "run-1", "timeline": [], "artifacts": []},
        pending,
        broker=object(),
        allowed_tools=["desktop.click_ui_element"],
        budget=object(),
    )

    assert context.input_preview == pending["input_preview"]


def test_tool_approval_resume_context_backfills_context_from_tool_request() -> None:
    pending = {
        "approval_id": "approval-context",
        "tool": "desktop.click_ui_element",
        "messages": [{"role": "user", "content": "save"}],
        "tool_request": {
            "tool": "desktop.click_ui_element",
            "input": {"label": "Save"},
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "step_id": "save-file",
            "capability_id": "desktop.ui_operation",
        },
        "remaining_tool_requests": [],
        "next_iteration": 3,
    }

    context = ToolApprovalResumeContext.from_run(
        {"run_id": "run-1", "timeline": [], "artifacts": []},
        pending,
        broker=object(),
        allowed_tools=["desktop.click_ui_element"],
        budget=object(),
    )

    assert context.input_preview["label"] == "Save"
    assert context.input_preview["core_id"] == "core-1"
    assert context.input_preview["workspace_id"] == "workspace-1"
    assert context.input_preview["task_id"] == "task-1"
    assert context.input_preview["step_id"] == "save-file"
    assert context.input_preview["capability_id"] == "desktop.ui_operation"
