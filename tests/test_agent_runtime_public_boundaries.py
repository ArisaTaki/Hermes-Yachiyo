"""Public Agent runtime boundary exports."""

from __future__ import annotations

from apps.shell.agent import repositories, tools
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.repositories.row_projections import RuntimeRowProjector
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    MEMORY_TOOL_NAMES,
    PolicyGate,
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
)
from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPlugin,
    register_restricted_tool_plugin,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call


def test_repository_package_exports_runtime_persistence_boundaries() -> None:
    assert repositories.AgentDefinitionRepository is AgentDefinitionRepository
    assert repositories.AgentFutureTaskStore is AgentFutureTaskStore
    assert repositories.AgentMemoryStore is AgentMemoryStore
    assert repositories.ApprovalRepository is ApprovalRepository
    assert repositories.RunArtifactRepository is RunArtifactRepository
    assert repositories.RunEventRepository is RunEventRepository
    assert repositories.RunGroupRepository is RunGroupRepository
    assert repositories.RunRepository is RunRepository
    assert repositories.RuntimeRowProjector is RuntimeRowProjector
    assert repositories.SkillFolderRepository is SkillFolderRepository
    assert repositories.SkillRepository is SkillRepository
    assert repositories.StudioDeletionRepository is StudioDeletionRepository
    assert repositories.TaskRunLinkRepository is TaskRunLinkRepository
    assert repositories.TrustedWorkspaceRepository is TrustedWorkspaceRepository
    assert repositories.WorkflowRepository is WorkflowRepository
    assert "NativeRunEngine" not in repositories.__all__


def test_tools_package_exports_broker_policy_and_dispatch_boundaries() -> None:
    assert tools.ToolBroker is ToolBroker
    assert tools.PolicyGate is PolicyGate
    assert tools.RuntimePolicyCompiler is RuntimePolicyCompiler
    assert tools.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert tools.RestrictedPluginTool is RestrictedPluginTool
    assert tools.RestrictedToolPlugin is RestrictedToolPlugin
    assert tools.register_restricted_tool_plugin is register_restricted_tool_plugin
    assert tools.TOOL_DISPATCH_REGISTRY is TOOL_DISPATCH_REGISTRY
    assert tools.dispatch_tool_call is dispatch_tool_call
    assert {"terminal.run", "workspace.write_patch"} <= set(HIGH_RISK_AGENT_TOOLS)
    assert {"memory.add", "memory.replace", "memory.remove"} <= set(MEMORY_TOOL_NAMES)
    assert {"future_task.schedule", "future_task.list"} <= set(FUTURE_TASK_TOOL_NAMES)
    assert PolicyGate.allows_tool("workspace.read", ["workspace.read"]) is True
    assert RuntimePolicyCompiler.default_tool_policy("coding")["approval_required"]["terminal.run"] is True
