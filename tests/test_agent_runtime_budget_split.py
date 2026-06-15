"""Tests for runtime budget and error classes split out of agent_runtime."""

from __future__ import annotations

import time

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import (
    RunBudget,
    RunBudgetLimits,
    WorkflowRunBudget,
    check_context_budget,
    json_chars,
    limit_json_strings,
    limit_model_output,
    limit_tool_result,
    run_budget_from_timeline,
    tool_result_limiter,
    truncate_text,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError


def test_runtime_error_types_remain_exported_from_legacy_module() -> None:
    pending = {"tool": "terminal.run"}
    approval = agent_runtime.AgentApprovalRequired(pending)

    assert agent_runtime.AgentRuntimeError is AgentRuntimeError
    assert agent_runtime.AgentApprovalRequired is AgentApprovalRequired
    assert isinstance(approval, AgentRuntimeError)
    assert approval.pending_approval == pending


def test_runtime_budget_classes_remain_exported_as_legacy_aliases() -> None:
    assert agent_runtime._RunBudgetLimits is RunBudgetLimits
    assert agent_runtime._RunBudget is RunBudget
    assert agent_runtime._WorkflowRunBudget is WorkflowRunBudget
    assert agent_runtime._json_chars is json_chars
    assert agent_runtime._truncate_text is truncate_text
    assert agent_runtime._limit_json_strings is limit_json_strings


def test_run_budget_claims_model_tool_and_terminal_limits() -> None:
    limits = RunBudgetLimits(max_model_calls=1, max_tool_calls=2, max_terminal_calls=1)
    budget = RunBudget(limits=limits, started_at_epoch=time.time())

    budget.claim_model_call()
    with pytest.raises(AgentRuntimeError, match="max_model_calls=1"):
        budget.claim_model_call()

    budget.claim_tool_call("workspace.read")
    budget.claim_tool_call("terminal.run", terminal_execution=True)
    with pytest.raises(AgentRuntimeError, match="max_tool_calls=2"):
        budget.claim_tool_call("workspace.read")

    terminal_budget = RunBudget(
        limits=RunBudgetLimits(max_tool_calls=3, max_terminal_calls=1),
        started_at_epoch=time.time(),
    )
    terminal_budget.claim_tool_call("terminal.run", terminal_execution=True)
    with pytest.raises(AgentRuntimeError, match="max_terminal_calls=1"):
        terminal_budget.claim_tool_call("terminal.run", terminal_execution=True)


def test_workflow_budget_claims_step_and_context_limits() -> None:
    limits = RunBudgetLimits(max_workflow_steps=1, max_context_chars=5)
    budget = WorkflowRunBudget(limits=limits, started_at_epoch=time.time())

    budget.claim_step()
    with pytest.raises(AgentRuntimeError, match="max_workflow_steps=1"):
        budget.claim_step()

    context_budget = WorkflowRunBudget(limits=limits, started_at_epoch=time.time())
    with pytest.raises(AgentRuntimeError, match="max_context_chars=5"):
        context_budget.check_context(6)


def test_budget_helpers_limit_runtime_context_and_outputs() -> None:
    limits = RunBudgetLimits(max_context_chars=12, max_model_output_chars=8, max_tool_output_chars=6)
    budget = RunBudget(limits=limits, started_at_epoch=time.time())

    assert json_chars({"text": "八千代"}) >= len('"八千代"')
    with pytest.raises(AgentRuntimeError, match="max_context_chars=12"):
        check_context_budget(
            budget,
            [{"role": "user", "content": "This context is too long"}],
            redact_json_value=lambda value: value,
        )

    text, truncated = limit_model_output("1234567890", limits=limits, redact_text=str)
    assert truncated is True
    assert text == "12345678"

    limited = limit_tool_result(
        {"ok": True, "nested": {"content": "abcdefghi"}},
        limits=limits,
        redact_json_value=lambda value: value,
    )
    assert limited["truncated"] is True
    assert limited["nested"]["content"] == "abcdef"


def test_tool_result_limiter_closes_over_current_runtime_limits() -> None:
    limits = RunBudgetLimits(max_tool_output_chars=4)
    limiter = tool_result_limiter(limits=lambda: limits, redact_json_value=lambda value: value)

    limited = limiter({"ok": True, "content": "abcdef"})

    assert limited["truncated"] is True
    assert limited["content"] == "abcd"


def test_run_budget_reconstructs_usage_from_timeline() -> None:
    budget = run_budget_from_timeline(
        RunBudgetLimits(),
        started_at_epoch=time.time(),
        timeline=[
            {"event": "agent.model.response"},
            {"event": "model.output.completed"},
            {"event": "agent.tool.skipped"},
            {"event": "agent.tool.call", "detail": "terminal.run", "result": {"ok": True}},
            {"event": "agent.tool.call", "detail": "terminal.run", "result": {"approval_required": True}},
        ],
    )

    assert budget.model_calls_used == 2
    assert budget.tool_calls_used == 3
    assert budget.terminal_calls_used == 1
