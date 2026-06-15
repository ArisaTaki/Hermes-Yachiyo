"""Tests for runtime budget and error classes split out of agent_runtime."""

from __future__ import annotations

import time

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudget, RunBudgetLimits, WorkflowRunBudget
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
