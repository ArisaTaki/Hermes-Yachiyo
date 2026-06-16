"""Public Agent runtime boundary exports."""

from __future__ import annotations

from apps.shell.agent import repositories, tools
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    PolicyGate,
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call


def test_repository_package_exports_runtime_persistence_boundaries() -> None:
    assert repositories.AgentDefinitionRepository is AgentDefinitionRepository
    assert repositories.ApprovalRepository is ApprovalRepository
    assert repositories.RunArtifactRepository is RunArtifactRepository
    assert repositories.RunEventRepository is RunEventRepository
    assert repositories.RunGroupRepository is RunGroupRepository
    assert repositories.RunRepository is RunRepository
    assert repositories.TaskRunLinkRepository is TaskRunLinkRepository
    assert repositories.WorkflowRepository is WorkflowRepository
    assert "NativeRunEngine" not in repositories.__all__


def test_tools_package_exports_broker_policy_and_dispatch_boundaries() -> None:
    assert tools.ToolBroker is ToolBroker
    assert tools.PolicyGate is PolicyGate
    assert tools.RuntimePolicyCompiler is RuntimePolicyCompiler
    assert tools.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert tools.TOOL_DISPATCH_REGISTRY is TOOL_DISPATCH_REGISTRY
    assert tools.dispatch_tool_call is dispatch_tool_call
    assert {"terminal.run", "workspace.write_patch"} <= set(HIGH_RISK_AGENT_TOOLS)
    assert PolicyGate.allows_tool("workspace.read", ["workspace.read"]) is True
    assert RuntimePolicyCompiler.default_tool_policy("coding")["approval_required"]["terminal.run"] is True
