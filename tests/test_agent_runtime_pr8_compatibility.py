"""PR8 compatibility guards for the split runtime modules."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.runtime.budget import (
    RunBudget,
    RunBudgetLimits,
    WorkflowRunBudget,
    context_budget_checker,
    run_budget_from_timeline,
)
from apps.shell.agent.runtime.events import (
    RuntimeRunEventRecorder,
    RuntimeToolCallEventRecorder,
    canonical_tool_event_payload,
    redact_json_value,
)
from apps.shell.agent.runtime.native_engine import NativeRunEngine
from apps.shell.agent.runtime.tool_brokers import RuntimeToolBrokerFactory
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import PolicyGate, RuntimePolicyCompiler


def test_pr8_runtime_split_keeps_legacy_agent_runtime_import_surface() -> None:
    assert agent_runtime.NativeRunEngine is NativeRunEngine
    assert agent_runtime.AgentRuntimeService is NativeRunEngine

    assert agent_runtime.RunRepository is RunRepository
    assert agent_runtime.RunEventRepository is RunEventRepository
    assert agent_runtime.ApprovalRepository is ApprovalRepository
    assert agent_runtime.RunArtifactRepository is RunArtifactRepository
    assert agent_runtime.RunGroupRepository is RunGroupRepository
    assert agent_runtime.WorkflowRepository is WorkflowRepository

    assert agent_runtime.ToolBroker is ToolBroker
    assert agent_runtime.RuntimeToolBrokerFactory is RuntimeToolBrokerFactory
    assert agent_runtime.PolicyGate is PolicyGate
    assert agent_runtime.RuntimePolicyCompiler is RuntimePolicyCompiler

    assert agent_runtime.RuntimeRunEventRecorder is RuntimeRunEventRecorder
    assert agent_runtime.RuntimeToolCallEventRecorder is RuntimeToolCallEventRecorder
    assert agent_runtime._canonical_tool_event_payload is canonical_tool_event_payload
    assert agent_runtime._redact_json_value is redact_json_value

    assert agent_runtime._RunBudgetLimits is RunBudgetLimits
    assert agent_runtime._RunBudget is RunBudget
    assert agent_runtime._WorkflowRunBudget is WorkflowRunBudget
    assert agent_runtime._runtime_context_budget_checker is context_budget_checker
    assert agent_runtime._runtime_run_budget_from_timeline is run_budget_from_timeline
