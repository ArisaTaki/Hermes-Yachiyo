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
from apps.shell.agent.tools.foreground_lock import ForegroundActionLock
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    MEMORY_TOOL_NAMES,
    PolicyGate,
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
)
from apps.shell.agent.tools.plugins import (
    RestrictedPluginInstallState,
    RestrictedPluginTool,
    RestrictedToolPlugin,
    RestrictedToolPluginManager,
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
    assert tools.ForegroundActionLock is ForegroundActionLock
    assert tools.PolicyGate is PolicyGate
    assert tools.RuntimePolicyCompiler is RuntimePolicyCompiler
    assert tools.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert tools.RestrictedPluginInstallState is RestrictedPluginInstallState
    assert tools.RestrictedPluginTool is RestrictedPluginTool
    assert tools.RestrictedToolPlugin is RestrictedToolPlugin
    assert tools.RestrictedToolPluginManager is RestrictedToolPluginManager
    assert tools.register_restricted_tool_plugin is register_restricted_tool_plugin
    assert tools.TOOL_DISPATCH_REGISTRY is TOOL_DISPATCH_REGISTRY
    assert tools.dispatch_tool_call is dispatch_tool_call
    assert {"terminal.run", "workspace.write_patch"} <= set(HIGH_RISK_AGENT_TOOLS)
    assert {"memory.add", "memory.replace", "memory.remove"} <= set(MEMORY_TOOL_NAMES)
    assert {"future_task.schedule", "future_task.list"} <= set(FUTURE_TASK_TOOL_NAMES)
    assert PolicyGate.allows_tool("workspace.read", ["workspace.read"]) is True
    assert RuntimePolicyCompiler.default_tool_policy("coding")["approval_required"]["terminal.run"] is True


def test_planner_core_tools_are_registered_for_dispatch() -> None:
    planner_core_tools = {
        "workspace.list",
        "workspace.read",
        "data.analyze",
        "artifact.write",
        "terminal.run",
        "python.run",
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
        "desktop.ui_elements",
        "app.open_and_safe_shortcut",
        "app.open_and_safe_type_text",
        "app.open_and_click_ui_element",
    }

    assert planner_core_tools <= set(TOOL_DISPATCH_REGISTRY)


def test_desktop_operation_aliases_dispatch_to_stable_runtime_tools() -> None:
    class FakeBroker:
        def __init__(self) -> None:
            self.calls = []

        def app_open(self, app_name):
            self.calls.append(("app_open", app_name))
            return {"ok": True, "action": "app.open"}

        def app_focus(self, app_name):
            self.calls.append(("app_focus", app_name))
            return {"ok": True, "action": "app.focus"}

        def desktop_windows(self, app_name):
            self.calls.append(("desktop_windows", app_name))
            return {"ok": True, "action": "desktop.windows"}

        def desktop_ui_elements(self, *, role_filter="", limit=80, app_name=""):
            self.calls.append(("desktop_ui_elements", app_name, role_filter, limit))
            return {"ok": True, "action": "desktop.ui_elements"}

        def desktop_hotkey(self, key, *, modifiers=None):
            self.calls.append(("desktop_hotkey", key, modifiers or []))
            return {"ok": True, "action": "desktop.hotkey"}

        def desktop_type_text(self, text):
            self.calls.append(("desktop_type_text", text))
            return {"ok": True, "action": "desktop.type_text"}

        def app_open_and_click_ui_element(
            self,
            app_name,
            target,
            *,
            role_filter="",
            limit=80,
            click_count=1,
        ):
            self.calls.append(
                (
                    "app_open_and_click_ui_element",
                    app_name,
                    target,
                    role_filter,
                    limit,
                    click_count,
                )
            )
            return {"ok": True, "action": "app.open_and_click_ui_element"}

        def desktop_inspect_app(
            self,
            app_name,
            *,
            open_if_needed=True,
            focus=True,
            role_filter="",
            limit=80,
        ):
            self.calls.append(
                (
                    "desktop_inspect_app",
                    app_name,
                    open_if_needed,
                    focus,
                    role_filter,
                    limit,
                )
            )
            return {"ok": True, "action": "desktop.inspect_app"}

        def desktop_active_window(self):
            self.calls.append(("desktop_active_window",))
            return {"ok": True, "action": "desktop.active_window"}

    broker = FakeBroker()

    assert dispatch_tool_call(broker, "desktop.open_app", {"app_name": "Music"})["ok"] is True
    assert dispatch_tool_call(broker, "desktop.focus_app", {"app_name": "Music"})["ok"] is True
    assert dispatch_tool_call(broker, "desktop.list_windows", {"app_name": "Music"})["ok"] is True
    assert dispatch_tool_call(
        broker,
        "desktop.read_ui",
        {"app_name": "Music", "role_filter": "button", "limit": 10},
    )["ok"] is True
    assert dispatch_tool_call(
        broker,
        "desktop.shortcut",
        {"key": "l", "modifiers": ["command"]},
    )["ok"] is True
    assert dispatch_tool_call(
        broker,
        "desktop.shortcut",
        {"key": "return", "modifiers": []},
    )["ok"] is True
    assert dispatch_tool_call(broker, "desktop.type", {"text": "hello"})["ok"] is True
    assert dispatch_tool_call(
        broker,
        "app.open_and_click_ui_element",
        {
            "app_name": "Music",
            "target": "first result",
            "role_filter": "",
            "limit": 80,
            "click_count": 1,
        },
    )["ok"] is True
    verify = dispatch_tool_call(
        broker,
        "desktop.verify",
        {"app_name": "Music", "role_filter": "button", "limit": 5},
    )

    assert verify["action"] == "desktop.verify"
    assert broker.calls == [
        ("app_open", "Music"),
        ("app_focus", "Music"),
        ("desktop_windows", "Music"),
        ("desktop_ui_elements", "Music", "button", 10),
        ("desktop_hotkey", "l", ["command"]),
        ("desktop_hotkey", "return", []),
        ("desktop_type_text", "hello"),
        ("app_open_and_click_ui_element", "Music", "first result", "", 80, 1),
        ("desktop_inspect_app", "Music", False, False, "button", 5),
    ]
