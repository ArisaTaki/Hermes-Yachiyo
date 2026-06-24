"""Tests for the split ToolBroker dispatch registry."""

from __future__ import annotations

import os
import subprocess

import pytest

from apps.shell.agent.tools import browser as browser_mod
from apps.shell.agent.tools import desktop as desktop_mod
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import (
    DAILY_DESKTOP_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    KNOWN_AGENT_TOOLS,
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
)
from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPlugin,
    RestrictedToolPluginManager,
    clear_restricted_tool_plugins,
    list_restricted_plugin_tools,
    register_restricted_tool_plugin,
    restricted_plugin_tool_risk,
    unregister_restricted_tool_plugin,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call


@pytest.fixture(autouse=True)
def _clear_plugin_tools():
    clear_restricted_tool_plugins()
    yield
    clear_restricted_tool_plugins()


def _broker(tmp_path):
    return ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": ["."]},
        tmp_path / "artifacts",
    )


def test_tool_dispatch_registry_covers_known_agent_tools() -> None:
    assert set(TOOL_DISPATCH_REGISTRY) == KNOWN_AGENT_TOOLS


def test_tool_broker_call_uses_split_registry_for_workspace_read(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    broker = _broker(tmp_path)

    assert broker.call("workspace.read", {"path": "note.txt"}) == {
        "ok": True,
        "path": "note.txt",
        "content": "hello",
    }


def test_tool_dispatch_registry_keeps_terminal_approval_gate(tmp_path) -> None:
    broker = _broker(tmp_path)

    result = broker.call("terminal.run", {"command": "printf blocked", "approved": True})

    assert result["ok"] is False
    assert result["approval_required"] is True
    assert result["tool"] == "terminal.run"
    assert result["input_preview"] == {"command": "printf blocked", "shell": False}


def test_tool_dispatch_registry_rejects_unknown_tool(tmp_path) -> None:
    with pytest.raises(AgentRuntimeError, match="未知工具"):
        dispatch_tool_call(_broker(tmp_path), "unknown.tool", {})


def test_restricted_plugin_tool_registers_schema_policy_and_dispatch(tmp_path) -> None:
    def echo_tool(payload, context):
        return {
            "ok": True,
            "echo": payload["text"],
            "tool": "plugin.spoof.echo",
            "plugin_id": "spoof",
            "risk_level": "high",
            "context": {
                "tool_name": context.tool_name,
                "plugin_id": context.plugin_id,
                "risk_level": context.risk_level,
                "workdir": str(context.workdir),
            },
        }

    registered = register_restricted_tool_plugin(
        RestrictedToolPlugin(
            plugin_id="notes",
            tools=(
                RestrictedPluginTool(
                    tool_id="echo",
                    description="Echo text through a restricted test plugin.",
                    properties={"text": {"type": "string"}},
                    required=("text",),
                    risk_level="low",
                    execute=echo_tool,
                ),
            ),
            skill_docs="Use echo for tests only.",
        )
    )
    tool_name = "plugin.notes.echo"

    assert registered[0].name == tool_name
    assert registered[0].function_name == "plugin_notes_echo"
    assert registered[0].skill_docs == "Use echo for tests only."
    assert list_restricted_plugin_tools()[0].name == tool_name
    assert restricted_plugin_tool_risk(tool_name) == "low"
    assert tool_name in KNOWN_AGENT_TOOLS
    assert tool_name in TOOL_DISPATCH_REGISTRY

    schemas = ToolDescriptorRegistry.model_tool_schemas([tool_name])
    assert schemas[0]["function"]["name"] == "plugin_notes_echo"
    assert schemas[0]["function"]["parameters"]["additionalProperties"] is False
    ToolDescriptorRegistry.validate_payload(tool_name, {"text": "hello"})
    with pytest.raises(AgentRuntimeError, match="未声明"):
        ToolDescriptorRegistry.validate_payload(tool_name, {"text": "hello", "extra": True})

    policy = RuntimePolicyCompiler().compile_tool_policy(
        "custom",
        {"allowed_tools": [tool_name, "unknown.tool"]},
    )
    assert policy == {"allowed_tools": [tool_name], "approval_required": {}}
    result = dispatch_tool_call(_broker(tmp_path), tool_name, {"text": "hello"})
    assert result["ok"] is True
    assert result["echo"] == "hello"
    assert result["tool"] == tool_name
    assert result["plugin_id"] == "notes"
    assert result["risk_level"] == "low"
    assert result["context"]["tool_name"] == tool_name

    unregister_restricted_tool_plugin("notes")

    assert tool_name not in KNOWN_AGENT_TOOLS
    assert tool_name not in TOOL_DISPATCH_REGISTRY
    assert restricted_plugin_tool_risk(tool_name) is None
    with pytest.raises(AgentRuntimeError, match="未知工具"):
        dispatch_tool_call(_broker(tmp_path), tool_name, {"text": "hello"})


def test_restricted_plugin_manager_installs_disables_enables_and_uninstalls(
    tmp_path,
) -> None:
    def echo_tool(payload, context):
        return {"ok": True, "text": payload["text"], "plugin_id": context.plugin_id}

    tool_name = "plugin.notes.echo"
    manager = RestrictedToolPluginManager()
    plugin = RestrictedToolPlugin(
        plugin_id="notes",
        tools=(
            RestrictedPluginTool(
                tool_id="echo",
                description="Echo text through a managed test plugin.",
                properties={"text": {"type": "string"}},
                required=("text",),
                risk_level="medium",
                execute=echo_tool,
            ),
        ),
        skill_docs="Use echo for managed plugin tests.",
    )

    installed = manager.install(plugin, enabled=False)
    assert installed.plugin_id == "notes"
    assert installed.enabled is False
    assert installed.tool_names == (tool_name,)
    assert installed.skill_docs == "Use echo for managed plugin tests."
    assert list_restricted_plugin_tools() == []
    assert tool_name not in TOOL_DISPATCH_REGISTRY

    enabled = manager.enable("notes")
    assert enabled.enabled is True
    assert list_restricted_plugin_tools()[0].name == tool_name
    assert restricted_plugin_tool_risk(tool_name) == "medium"
    assert dispatch_tool_call(_broker(tmp_path), tool_name, {"text": "hello"}) == {
        "ok": True,
        "text": "hello",
        "plugin_id": "notes",
        "tool": tool_name,
        "risk_level": "medium",
    }

    disabled = manager.disable("notes")
    assert disabled.enabled is False
    assert manager.list_installed()[0].enabled is False
    assert list_restricted_plugin_tools() == []
    assert tool_name not in TOOL_DISPATCH_REGISTRY
    with pytest.raises(AgentRuntimeError, match="未知工具"):
        dispatch_tool_call(_broker(tmp_path), tool_name, {"text": "hello"})

    assert manager.enable("notes").enabled is True
    uninstalled = manager.uninstall("notes")
    assert uninstalled.enabled is False
    assert manager.list_installed() == []
    assert tool_name not in TOOL_DISPATCH_REGISTRY
    with pytest.raises(AgentRuntimeError, match="插件未安装"):
        manager.enable("notes")


def test_high_risk_restricted_plugin_tool_uses_existing_approval_gate(tmp_path) -> None:
    def delete_like_tool(payload, context):
        return {
            "ok": True,
            "approved": context.approved,
            "target": payload["target"],
        }

    register_restricted_tool_plugin(
        RestrictedToolPlugin(
            plugin_id="ops",
            tools=(
                RestrictedPluginTool(
                    tool_id="delete_file",
                    description="High-risk mock plugin tool.",
                    properties={"target": {"type": "string"}},
                    required=("target",),
                    risk_level="high",
                    execute=delete_like_tool,
                ),
            ),
        )
    )
    tool_name = "plugin.ops.delete_file"

    policy = RuntimePolicyCompiler().compile_tool_policy(
        "custom",
        {"allowed_tools": [tool_name]},
    )
    assert policy == {"allowed_tools": [tool_name], "approval_required": {tool_name: True}}
    assert tool_name in HIGH_RISK_AGENT_TOOLS

    approval = dispatch_tool_call(_broker(tmp_path), tool_name, {"target": "notes.md"})
    assert approval == {
        "ok": False,
        "approval_required": True,
        "tool": tool_name,
        "risk_level": "high",
        "plugin_id": "ops",
    }

    result = dispatch_tool_call(
        _broker(tmp_path),
        tool_name,
        {"target": "notes.md"},
        approved=True,
    )
    assert result["ok"] is True
    assert result["approved"] is True
    assert result["plugin_id"] == "ops"
    assert result["risk_level"] == "high"


def test_desktop_tools_have_schemas_and_do_not_relax_terminal_approval() -> None:
    schemas = {
        schema["function"]["name"]: schema
        for schema in ToolDescriptorRegistry.model_tool_schemas(list(DAILY_DESKTOP_TOOL_NAMES))
    }

    assert {
        "screen_capture",
        "desktop_permissions",
        "desktop_active_window",
        "desktop_running_apps",
        "desktop_windows",
        "app_status",
        "app_open",
        "app_focus",
        "app_focus_window",
        "app_open_and_safe_type_text",
        "app_focus_and_safe_type_text",
        "app_open_and_safe_shortcut",
        "app_focus_and_safe_shortcut",
        "app_open_and_safe_key",
        "app_focus_and_safe_key",
        "app_open_and_hotkey",
        "app_focus_and_hotkey",
        "app_open_and_safe_scroll",
        "app_focus_and_safe_scroll",
        "app_open_and_safe_click",
        "app_focus_and_safe_click",
        "app_open_and_click_ui_element",
        "app_focus_and_click_ui_element",
        "app_open_and_type_into_ui_element",
        "app_focus_and_type_into_ui_element",
        "app_show",
        "app_hide",
        "app_minimize",
        "app_quit",
        "desktop_reveal_path",
        "desktop_open_path",
        "media_apple_music_play",
        "media_apple_music_open_and_play",
        "media_apple_music_control",
        "system_volume",
        "clipboard_write",
        "clipboard_read",
        "notes_create",
        "reminders_create",
        "calendar_create_event",
        "desktop_safe_shortcut",
        "desktop_safe_key",
        "desktop_safe_type_text",
        "desktop_safe_click",
        "desktop_safe_scroll",
        "desktop_click_ui_element",
        "desktop_type_into_ui_element",
        "desktop_hide_app",
        "desktop_minimize_window",
        "desktop_close_window",
        "desktop_hotkey",
        "desktop_submit_foreground",
        "desktop_type_text",
        "desktop_click",
        "browser_open_url",
        "browser_current_page",
        "browser_click",
        "browser_type_text",
        "browser_extract_text",
        "browser_screenshot",
    }.issubset(schemas)
    assert "terminal.run" in HIGH_RISK_AGENT_TOOLS
    assert "workspace.write_patch" in HIGH_RISK_AGENT_TOOLS


def test_desktop_running_apps_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.running_apps", {})


def test_desktop_permissions_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.permissions", {})


def test_desktop_windows_schema_accepts_optional_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.windows", {})
    ToolDescriptorRegistry.validate_payload("desktop.windows", {"app_name": "Google Chrome"})

    with pytest.raises(AgentRuntimeError, match="desktop.windows 参数 app_name 必须是字符串"):
        ToolDescriptorRegistry.validate_payload("desktop.windows", {"app_name": 123})


def test_desktop_ui_elements_schema_accepts_optional_filter_and_limit() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.ui_elements", {})
    ToolDescriptorRegistry.validate_payload("desktop.ui_elements", {"role_filter": "button", "limit": 20})

    with pytest.raises(AgentRuntimeError, match="desktop.ui_elements 参数 role_filter 必须是字符串"):
        ToolDescriptorRegistry.validate_payload("desktop.ui_elements", {"role_filter": 123})
    with pytest.raises(AgentRuntimeError, match="desktop.ui_elements 参数 limit 必须是 1-200 的整数"):
        ToolDescriptorRegistry.validate_payload("desktop.ui_elements", {"limit": 0})


def test_desktop_click_ui_element_schema_requires_target_and_valid_options() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.click_ui_element",
        {"target": "Send", "role_filter": "button", "limit": 20, "click_count": 2},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_click_ui_element",
        {
            "app_name": "Google Chrome",
            "target": "Send",
            "role_filter": "button",
            "limit": 20,
            "click_count": 2,
        },
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_click_ui_element",
        {"app_name": "Slack", "target": "Send"},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.click_ui_element 参数 target 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.click_ui_element", {"target": ""})
    with pytest.raises(AgentRuntimeError, match="app.open_and_click_ui_element 参数 app_name 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_click_ui_element",
            {"app_name": "", "target": "Send"},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_click_ui_element 参数 target 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_click_ui_element",
            {"app_name": "Slack", "target": ""},
        )
    with pytest.raises(AgentRuntimeError, match="desktop.click_ui_element 参数 role_filter 必须是字符串"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.click_ui_element",
            {"target": "Send", "role_filter": 123},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_click_ui_element 参数 role_filter 必须是字符串"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_click_ui_element",
            {"app_name": "Google Chrome", "target": "Send", "role_filter": 123},
        )
    with pytest.raises(AgentRuntimeError, match="desktop.click_ui_element 参数 limit 必须是 1-200"):
        ToolDescriptorRegistry.validate_payload("desktop.click_ui_element", {"target": "Send", "limit": 0})
    with pytest.raises(AgentRuntimeError, match="app.focus_and_click_ui_element 参数 limit 必须是 1-200"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_click_ui_element",
            {"app_name": "Slack", "target": "Send", "limit": 0},
        )
    with pytest.raises(AgentRuntimeError, match="desktop.click_ui_element 参数 click_count 必须是 1-3"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.click_ui_element",
            {"target": "Send", "click_count": 4},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_click_ui_element 参数 click_count 必须是 1-3"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_click_ui_element",
            {"app_name": "Google Chrome", "target": "Send", "click_count": 4},
        )


def test_desktop_type_into_ui_element_schema_requires_target_text_and_valid_options() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.type_into_ui_element",
        {"target": "Search", "text": "hello", "role_filter": "text", "limit": 20},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_type_into_ui_element",
        {
            "app_name": "Google Chrome",
            "target": "Search",
            "text": "hello",
            "role_filter": "text",
            "limit": 20,
        },
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_type_into_ui_element",
        {"app_name": "Slack", "target": "Message", "text": "hello"},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.type_into_ui_element 参数 target 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.type_into_ui_element", {"target": "", "text": "hello"})
    with pytest.raises(AgentRuntimeError, match="desktop.type_into_ui_element 参数 text 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.type_into_ui_element", {"target": "Search", "text": ""})
    with pytest.raises(AgentRuntimeError, match="app.open_and_type_into_ui_element 参数 app_name 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_type_into_ui_element",
            {"app_name": "", "target": "Search", "text": "hello"},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_type_into_ui_element 参数 text 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_type_into_ui_element",
            {"app_name": "Slack", "target": "Message", "text": ""},
        )
    with pytest.raises(AgentRuntimeError, match="desktop.type_into_ui_element 参数 role_filter 必须是字符串"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.type_into_ui_element",
            {"target": "Search", "text": "hello", "role_filter": 123},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_type_into_ui_element 参数 role_filter 必须是字符串"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_type_into_ui_element",
            {"app_name": "Google Chrome", "target": "Search", "text": "hello", "role_filter": 123},
        )
    with pytest.raises(AgentRuntimeError, match="desktop.type_into_ui_element 参数 limit 必须是 1-200"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.type_into_ui_element",
            {"target": "Search", "text": "hello", "limit": 0},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_type_into_ui_element 参数 limit 必须是 1-200"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_type_into_ui_element",
            {"app_name": "Slack", "target": "Message", "text": "hello", "limit": 0},
        )


def test_app_status_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.status", {"app_name": "Google Chrome"})

    with pytest.raises(AgentRuntimeError, match="app.status 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.status", {"app_name": ""})


def test_app_quit_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.quit", {"app_name": "Slack"})

    with pytest.raises(AgentRuntimeError, match="app.quit 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.quit", {"app_name": ""})


def test_app_show_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.show", {"app_name": "Slack"})

    with pytest.raises(AgentRuntimeError, match="app.show 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.show", {"app_name": ""})


def test_app_focus_window_schema_requires_app_name_and_title() -> None:
    ToolDescriptorRegistry.validate_payload(
        "app.focus_window",
        {"app_name": "Slack", "title_contains": "general"},
    )

    with pytest.raises(AgentRuntimeError, match="app.focus_window 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_window",
            {"app_name": "", "title_contains": "general"},
        )
    with pytest.raises(
        AgentRuntimeError,
        match="app.focus_window 参数 title_contains 必须是非空字符串",
    ):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_window",
            {"app_name": "Slack", "title_contains": ""},
        )


def test_app_foreground_action_schemas_require_app_and_explicit_action() -> None:
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_safe_shortcut",
        {"app_name": "Google Chrome", "action": "new_tab"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_safe_shortcut",
        {"app_name": "Slack", "action": "paste"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_safe_key",
        {"app_name": "Google Chrome", "action": "tab"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_safe_key",
        {"app_name": "Slack", "action": "arrow_down", "repeat_count": 3},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_hotkey",
        {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_hotkey",
        {"app_name": "Slack", "key": "k", "modifiers": ["command"]},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_safe_scroll",
        {"app_name": "Google Chrome", "direction": "down"},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_safe_scroll",
        {"app_name": "Slack", "direction": "up", "pages": 3},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.open_and_safe_click",
        {"app_name": "Google Chrome", "x": 120, "y": 240},
    )
    ToolDescriptorRegistry.validate_payload(
        "app.focus_and_safe_click",
        {"app_name": "Slack", "x": "120", "y": "240"},
    )

    with pytest.raises(AgentRuntimeError, match="app.open_and_safe_type_text 参数 text 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_safe_type_text",
            {"app_name": "Notes", "text": ""},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_safe_shortcut 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_shortcut",
            {"app_name": "Slack", "action": "close_tab"},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_safe_key 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_safe_key",
            {"app_name": "Slack", "action": "return"},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_safe_key 参数 repeat_count 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_key",
            {"app_name": "Slack", "action": "tab", "repeat_count": 0},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_hotkey 参数 modifiers 只能包含"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_hotkey",
            {"app_name": "Slack", "key": "l", "modifiers": ["meta"]},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_safe_scroll 参数 direction 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_safe_scroll",
            {"app_name": "Slack", "direction": "left"},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_safe_scroll 参数 pages 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_scroll",
            {"app_name": "Slack", "direction": "down", "pages": 0},
        )
    with pytest.raises(AgentRuntimeError, match="app.open_and_safe_click 参数 x 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.open_and_safe_click",
            {"app_name": "Slack", "x": -1, "y": 240},
        )
    with pytest.raises(AgentRuntimeError, match="app.focus_and_safe_click 参数 y 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_click",
            {"app_name": "Slack", "x": 120, "y": True},
        )


def test_app_hide_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.hide", {"app_name": "Slack"})

    with pytest.raises(AgentRuntimeError, match="app.hide 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.hide", {"app_name": ""})


def test_desktop_safe_shortcut_schema_accepts_only_whitelisted_actions() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "copy"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_tab"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_window"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_document"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_note"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_reminder"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_event"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "browser_back"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "browser_forward"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "reopen_closed_tab"})

    with pytest.raises(AgentRuntimeError, match="desktop.safe_shortcut 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "close_tab"})


def test_desktop_safe_key_schema_accepts_only_whitelisted_navigation_keys() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_key", {"action": "tab"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_key", {"action": "shift_tab"})
    ToolDescriptorRegistry.validate_payload(
        "desktop.safe_key",
        {"action": "arrow_down", "repeat_count": 3},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.safe_key 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_key", {"action": "return"})
    with pytest.raises(AgentRuntimeError, match="desktop.safe_key 参数 repeat_count 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_key", {"action": "tab", "repeat_count": 0})
    with pytest.raises(AgentRuntimeError, match="desktop.safe_key 参数 repeat_count 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_key", {"action": "tab", "repeat_count": True})


def test_desktop_safe_type_text_schema_requires_user_text() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_type_text", {"text": "hello"})

    with pytest.raises(AgentRuntimeError, match="desktop.safe_type_text 参数 text 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_type_text", {"text": ""})


def test_desktop_safe_click_schema_accepts_only_coordinates() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_click", {"x": 12, "y": 34.5})

    with pytest.raises(AgentRuntimeError, match="desktop.safe_click 参数 x 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_click", {"x": -1, "y": 34})
    with pytest.raises(AgentRuntimeError, match="desktop.safe_click 参数 y 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_click", {"x": 12, "y": True})


def test_desktop_safe_scroll_schema_accepts_direction_and_pages() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_scroll", {"direction": "down"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_scroll", {"direction": "up", "pages": 3})

    with pytest.raises(AgentRuntimeError, match="desktop.safe_scroll 参数 direction 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_scroll", {"direction": "left"})
    with pytest.raises(AgentRuntimeError, match="desktop.safe_scroll 参数 pages 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_scroll", {"direction": "down", "pages": 0})
    with pytest.raises(AgentRuntimeError, match="desktop.safe_scroll 参数 pages 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_scroll", {"direction": "down", "pages": True})


def test_desktop_submit_foreground_schema_requires_known_action() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.submit_foreground", {"action": "send"})
    ToolDescriptorRegistry.validate_payload("desktop.submit_foreground", {"action": "submit"})
    ToolDescriptorRegistry.validate_payload("desktop.submit_foreground", {"action": "confirm"})

    with pytest.raises(AgentRuntimeError, match="desktop.submit_foreground 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.submit_foreground", {"action": "return"})


def test_app_minimize_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.minimize", {"app_name": "Slack"})

    with pytest.raises(AgentRuntimeError, match="app.minimize 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.minimize", {"app_name": ""})


def test_desktop_reveal_path_schema_accepts_local_path() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.reveal_path",
        {"path": "~/Downloads/report.pdf"},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.reveal_path 参数 path 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("desktop.reveal_path", {"path": ""})


def test_desktop_open_path_schema_accepts_local_path() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.open_path",
        {"path": "~/Downloads/report.pdf"},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.open_path 参数 path 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("desktop.open_path", {"path": ""})


def test_system_volume_schema_accepts_safe_volume_actions() -> None:
    ToolDescriptorRegistry.validate_payload("system.volume", {"action": "status"})
    ToolDescriptorRegistry.validate_payload("system.volume", {"action": "set", "level": 35})
    ToolDescriptorRegistry.validate_payload("system.volume", {"action": "up", "step": 5})
    ToolDescriptorRegistry.validate_payload("system.volume", {"action": "mute"})

    with pytest.raises(AgentRuntimeError, match="system.volume 参数 action"):
        ToolDescriptorRegistry.validate_payload("system.volume", {"action": "shutdown"})
    with pytest.raises(AgentRuntimeError, match="system.volume 参数 level"):
        ToolDescriptorRegistry.validate_payload("system.volume", {"action": "set"})
    with pytest.raises(AgentRuntimeError, match="system.volume 参数 level"):
        ToolDescriptorRegistry.validate_payload("system.volume", {"action": "set", "level": 150})


def test_clipboard_write_schema_requires_text() -> None:
    ToolDescriptorRegistry.validate_payload("clipboard.write", {"text": "hello"})

    with pytest.raises(AgentRuntimeError, match="clipboard.write 参数 text 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("clipboard.write", {"text": ""})


def test_clipboard_read_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("clipboard.read", {})
    ToolDescriptorRegistry.validate_payload("clipboard.read", {"max_chars": 120})


def test_notes_create_schema_requires_body() -> None:
    ToolDescriptorRegistry.validate_payload("notes.create", {"body": "hello"})
    ToolDescriptorRegistry.validate_payload(
        "notes.create",
        {"body": "hello", "title": "Greeting", "folder_name": "Notes"},
    )

    with pytest.raises(AgentRuntimeError, match="notes.create 参数 body 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("notes.create", {"body": ""})


def test_native_schedule_creation_schemas_validate_titles_and_times() -> None:
    ToolDescriptorRegistry.validate_payload("reminders.create", {"title": "开会"})
    ToolDescriptorRegistry.validate_payload(
        "reminders.create",
        {"title": "开会", "due_at": "2026-06-25T15:00"},
    )
    ToolDescriptorRegistry.validate_payload(
        "calendar.create_event",
        {"title": "开会", "start_at": "2026-06-25T15:00"},
    )
    ToolDescriptorRegistry.validate_payload(
        "calendar.create_event",
        {
            "title": "开会",
            "start_at": "2026-06-25T15:00",
            "end_at": "2026-06-25T16:00",
        },
    )

    with pytest.raises(AgentRuntimeError, match="reminders.create 参数 title 必须是"):
        ToolDescriptorRegistry.validate_payload("reminders.create", {"title": ""})
    with pytest.raises(AgentRuntimeError, match="reminders.create 参数 due_at 必须是"):
        ToolDescriptorRegistry.validate_payload("reminders.create", {"title": "开会", "due_at": "tomorrow"})
    with pytest.raises(AgentRuntimeError, match="reminders.create 参数 due_at 必须是"):
        ToolDescriptorRegistry.validate_payload("reminders.create", {"title": "开会", "due_at": "2026-06-25"})
    with pytest.raises(AgentRuntimeError, match="calendar.create_event 参数 start_at 必须是"):
        ToolDescriptorRegistry.validate_payload("calendar.create_event", {"title": "开会"})
    with pytest.raises(AgentRuntimeError, match="calendar.create_event 参数 end_at 必须是"):
        ToolDescriptorRegistry.validate_payload(
            "calendar.create_event",
            {"title": "开会", "start_at": "2026-06-25T15:00", "end_at": "tomorrow"},
        )


def test_desktop_close_window_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.close_window", {})


def test_desktop_minimize_window_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.minimize_window", {})


def test_desktop_hide_app_schema_accepts_empty_payload() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.hide_app", {})


def test_compile_tool_policy_accepts_desktop_tools_with_foreground_approval() -> None:
    compiler = RuntimePolicyCompiler()

    policy = compiler.compile_tool_policy(
        "custom",
        {
            "allowed_tools": [
                "screen.capture",
                "app.focus_window",
                "app.show",
                "app.hide",
                "app.minimize",
                "desktop.hide_app",
                "desktop.minimize_window",
                "desktop.safe_key",
                "desktop.safe_scroll",
                "app.quit",
                "app.open_and_click_ui_element",
                "app.focus_and_click_ui_element",
                "app.open_and_type_into_ui_element",
                "app.focus_and_type_into_ui_element",
                "app.open_and_hotkey",
                "app.focus_and_hotkey",
                "desktop.close_window",
                "desktop.click",
                "desktop.click_ui_element",
                "desktop.type_into_ui_element",
                "desktop.type_text",
                "terminal.run",
            ]
        },
    )

    assert policy["allowed_tools"] == [
        "screen.capture",
        "app.focus_window",
        "app.show",
        "app.hide",
        "app.minimize",
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.safe_key",
        "desktop.safe_scroll",
        "app.quit",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "desktop.close_window",
        "desktop.click",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.type_text",
        "terminal.run",
    ]
    assert policy["approval_required"] == {
        "app.quit": True,
        "app.open_and_click_ui_element": True,
        "app.focus_and_click_ui_element": True,
        "app.open_and_type_into_ui_element": True,
        "app.focus_and_type_into_ui_element": True,
        "app.open_and_hotkey": True,
        "app.focus_and_hotkey": True,
        "desktop.close_window": True,
        "desktop.click": True,
        "desktop.click_ui_element": True,
        "desktop.type_into_ui_element": True,
        "desktop.type_text": True,
        "terminal.run": True,
    }


def test_desktop_click_schema_accepts_coordinates_and_rejects_bad_payload() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.click",
        {"x": 12, "y": 34.5, "click_count": 2},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.click 参数 x 必须是非负坐标数字"):
        ToolDescriptorRegistry.validate_payload("desktop.click", {"x": -1, "y": 34})
    with pytest.raises(AgentRuntimeError, match="desktop.click 参数 click_count 必须是 1-3"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.click",
            {"x": 12, "y": 34, "click_count": 4},
        )


def test_apple_music_control_schema_accepts_safe_playback_actions() -> None:
    ToolDescriptorRegistry.validate_payload(
        "media.apple_music_control",
        {"action": "pause"},
    )
    ToolDescriptorRegistry.validate_payload(
        "media.apple_music_control",
        {"action": "next"},
    )

    with pytest.raises(
        AgentRuntimeError,
        match="media.apple_music_control 参数 action 必须是",
    ):
        ToolDescriptorRegistry.validate_payload(
            "media.apple_music_control",
            {"action": "volume_up"},
        )


def test_browser_click_schema_accepts_optional_fallback_coordinates() -> None:
    ToolDescriptorRegistry.validate_payload(
        "browser.open_url_and_extract_text",
        {"url": "https://example.com/docs", "selector": "main"},
    )
    ToolDescriptorRegistry.validate_payload(
        "browser.open_url_and_screenshot",
        {"url": "https://example.com/docs", "reason": "capture docs"},
    )
    ToolDescriptorRegistry.validate_payload(
        "browser.click",
        {"selector": "#submit", "fallback_x": 12, "fallback_y": 34.5, "click_count": 2},
    )

    with pytest.raises(AgentRuntimeError, match="browser.click 参数 fallback_x 必须是非负坐标数字"):
        ToolDescriptorRegistry.validate_payload(
            "browser.click",
            {"selector": "#submit", "fallback_x": -1, "fallback_y": 34},
        )


def test_browser_type_text_schema_accepts_optional_fallback_coordinates() -> None:
    ToolDescriptorRegistry.validate_payload(
        "browser.type_text",
        {"selector": "point=12,34", "text": "hello", "fallback_x": 12, "fallback_y": 34.5},
    )

    with pytest.raises(AgentRuntimeError, match="browser.type_text 参数 fallback_y 必须是非负坐标数字"):
        ToolDescriptorRegistry.validate_payload(
            "browser.type_text",
            {"selector": "point=12,34", "text": "hello", "fallback_x": 12, "fallback_y": -1},
        )


def test_compile_tool_policy_accepts_browser_tools_with_interaction_approval() -> None:
    compiler = RuntimePolicyCompiler()

    policy = compiler.compile_tool_policy(
        "custom",
        {"allowed_tools": ["browser.open_url", "browser.click", "workspace.write_patch"]},
    )

    assert policy["allowed_tools"] == ["browser.open_url", "browser.click", "workspace.write_patch"]
    assert policy["approval_required"] == {"browser.click": True, "workspace.write_patch": True}


def test_tool_dispatch_registry_routes_desktop_tools(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    calls = []

    monkeypatch.setattr(
        broker,
        "media_apple_music_play",
        lambda query: calls.append(("music", query)) or {"ok": True, "query": query},
    )
    monkeypatch.setattr(
        broker,
        "media_apple_music_control",
        lambda action: calls.append(("music_control", action)) or {"ok": True, "action": action},
    )
    monkeypatch.setattr(
        broker,
        "media_apple_music_open_and_play",
        lambda: calls.append(("music_open_and_play",)) or {"ok": True, "action": "open_and_play"},
    )
    monkeypatch.setattr(
        broker,
        "notes_create",
        lambda body, *, title="", folder_name="": calls.append(("note", body, title, folder_name))
        or {"ok": True, "body": body},
    )
    monkeypatch.setattr(
        broker,
        "desktop_safe_shortcut",
        lambda action: calls.append(("safe_shortcut", action)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_safe_key",
        lambda action, *, repeat_count=1: calls.append(("safe_key", action, repeat_count))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_safe_type_text",
        lambda text: calls.append(("safe_type_text", text)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_safe_click",
        lambda x, y: calls.append(("safe_click", x, y)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_safe_scroll",
        lambda direction, *, pages=1: calls.append(("safe_scroll", direction, pages))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_click_ui_element",
        lambda target, *, role_filter="", limit=80, click_count=1: calls.append(
            ("click_ui_element", target, role_filter, limit, click_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_type_into_ui_element",
        lambda target, text, *, role_filter="", limit=80: calls.append(
            ("type_into_ui_element", target, text, role_filter, limit)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_hotkey",
        lambda key, *, modifiers=None: calls.append(("hotkey", key, modifiers))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_submit_foreground",
        lambda action="submit": calls.append(("submit_foreground", action))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_click",
        lambda x, y, *, click_count=1: calls.append(("click", x, y, click_count))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_hide_app",
        lambda: calls.append(("hide_app",)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_minimize_window",
        lambda: calls.append(("minimize_window",)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_close_window",
        lambda: calls.append(("close_window",)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "desktop_reveal_path",
        lambda path: calls.append(("reveal", path)) or {"ok": True, "path": path},
    )
    monkeypatch.setattr(
        broker,
        "desktop_permissions",
        lambda: calls.append(("permissions",)) or {"ok": True, "action": "desktop.permissions"},
    )
    monkeypatch.setattr(
        broker,
        "desktop_running_apps",
        lambda: calls.append(("running",)) or {"ok": True, "apps": ["Finder"]},
    )
    monkeypatch.setattr(
        broker,
        "desktop_windows",
        lambda app_name="": calls.append(("windows", app_name)) or {"ok": True, "app_name": app_name},
    )
    monkeypatch.setattr(
        broker,
        "desktop_ui_elements",
        lambda role_filter="", limit=80: calls.append(("ui_elements", role_filter, limit))
        or {"ok": True, "role_filter": role_filter, "limit": limit},
    )
    monkeypatch.setattr(
        broker,
        "app_status",
        lambda app_name: calls.append(("status", app_name)) or {"ok": True, "app_name": app_name},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_window",
        lambda app_name, title_contains: calls.append(("focus_window", app_name, title_contains))
        or {"ok": True, "app_name": app_name, "title_contains": title_contains},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_safe_type_text",
        lambda app_name, text: calls.append(("open_type", app_name, text)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_safe_type_text",
        lambda app_name, text: calls.append(("focus_type", app_name, text)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_safe_shortcut",
        lambda app_name, action: calls.append(("open_shortcut", app_name, action)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_safe_shortcut",
        lambda app_name, action: calls.append(("focus_shortcut", app_name, action)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_safe_key",
        lambda app_name, action, *, repeat_count=1: calls.append(
            ("open_key", app_name, action, repeat_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_safe_key",
        lambda app_name, action, *, repeat_count=1: calls.append(
            ("focus_key", app_name, action, repeat_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_hotkey",
        lambda app_name, key, *, modifiers=None: calls.append(
            ("open_hotkey", app_name, key, list(modifiers or []))
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_hotkey",
        lambda app_name, key, *, modifiers=None: calls.append(
            ("focus_hotkey", app_name, key, list(modifiers or []))
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_safe_scroll",
        lambda app_name, direction, *, pages=1: calls.append(
            ("open_scroll", app_name, direction, pages)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_safe_scroll",
        lambda app_name, direction, *, pages=1: calls.append(
            ("focus_scroll", app_name, direction, pages)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_safe_click",
        lambda app_name, x, y: calls.append(("open_click", app_name, x, y))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_safe_click",
        lambda app_name, x, y: calls.append(("focus_click", app_name, x, y))
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_click_ui_element",
        lambda app_name, target, *, role_filter="", limit=80, click_count=1: calls.append(
            ("open_click_ui", app_name, target, role_filter, limit, click_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_click_ui_element",
        lambda app_name, target, *, role_filter="", limit=80, click_count=1: calls.append(
            ("focus_click_ui", app_name, target, role_filter, limit, click_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_open_and_type_into_ui_element",
        lambda app_name, target, text, *, role_filter="", limit=80: calls.append(
            ("open_type_into_ui", app_name, target, text, role_filter, limit)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_focus_and_type_into_ui_element",
        lambda app_name, target, text, *, role_filter="", limit=80: calls.append(
            ("focus_type_into_ui", app_name, target, text, role_filter, limit)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "app_show",
        lambda app_name: calls.append(("show_named_app", app_name))
        or {"ok": True, "app_name": app_name},
    )
    monkeypatch.setattr(
        broker,
        "app_hide",
        lambda app_name: calls.append(("hide_named_app", app_name))
        or {"ok": True, "app_name": app_name},
    )
    monkeypatch.setattr(
        broker,
        "app_minimize",
        lambda app_name: calls.append(("minimize_named_app", app_name))
        or {"ok": True, "app_name": app_name},
    )

    assert dispatch_tool_call(
        broker,
        "media.apple_music_play",
        {"query": "超时空辉夜姬"},
    ) == {"ok": True, "query": "超时空辉夜姬"}
    assert dispatch_tool_call(
        broker,
        "media.apple_music_control",
        {"action": "pause"},
    ) == {"ok": True, "action": "pause"}
    assert dispatch_tool_call(
        broker,
        "media.apple_music_open_and_play",
        {},
    ) == {"ok": True, "action": "open_and_play"}
    assert dispatch_tool_call(
        broker,
        "notes.create",
        {"body": "hello", "title": "Greeting", "folder_name": "Notes"},
    ) == {"ok": True, "body": "hello"}
    assert dispatch_tool_call(
        broker,
        "desktop.safe_shortcut",
        {"action": "copy"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.safe_key",
        {"action": "arrow_down", "repeat_count": 3},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.safe_type_text",
        {"text": "hello"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.safe_click",
        {"x": 12, "y": 34},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.safe_scroll",
        {"direction": "down", "pages": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.click_ui_element",
        {"target": "Send", "role_filter": "button", "limit": 20, "click_count": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.type_into_ui_element",
        {"target": "Search", "text": "hello", "role_filter": "text", "limit": 20},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.hotkey",
        {"key": "l", "modifiers": ["command"]},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.submit_foreground",
        {"action": "send"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.click",
        {"x": 12, "y": 34, "click_count": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(broker, "desktop.hide_app", {}) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_window",
        {"app_name": "Slack", "title_contains": "general"},
    ) == {
        "ok": True,
        "app_name": "Slack",
        "title_contains": "general",
    }
    assert dispatch_tool_call(
        broker,
        "app.open_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_safe_shortcut",
        {"app_name": "Google Chrome", "action": "new_tab"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_safe_shortcut",
        {"app_name": "Slack", "action": "paste"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_safe_key",
        {"app_name": "Google Chrome", "action": "tab"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_safe_key",
        {"app_name": "Slack", "action": "arrow_down", "repeat_count": 3},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_hotkey",
        {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_hotkey",
        {"app_name": "Slack", "key": "k", "modifiers": ["command"]},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_safe_scroll",
        {"app_name": "Google Chrome", "direction": "down"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_safe_scroll",
        {"app_name": "Slack", "direction": "up", "pages": 3},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_safe_click",
        {"app_name": "Google Chrome", "x": 120, "y": 240},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_safe_click",
        {"app_name": "Slack", "x": 320, "y": 180},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_click_ui_element",
        {
            "app_name": "Google Chrome",
            "target": "Sign in",
            "role_filter": "button",
            "limit": 20,
            "click_count": 2,
        },
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_click_ui_element",
        {"app_name": "Slack", "target": "Send"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.open_and_type_into_ui_element",
        {
            "app_name": "Google Chrome",
            "target": "Address",
            "text": "github.com",
            "role_filter": "text",
            "limit": 20,
        },
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "app.focus_and_type_into_ui_element",
        {"app_name": "Slack", "target": "Message", "text": "hello"},
    ) == {"ok": True}
    assert dispatch_tool_call(broker, "app.show", {"app_name": "Slack"}) == {
        "ok": True,
        "app_name": "Slack",
    }
    assert dispatch_tool_call(broker, "app.hide", {"app_name": "Slack"}) == {
        "ok": True,
        "app_name": "Slack",
    }
    assert dispatch_tool_call(broker, "app.minimize", {"app_name": "Slack"}) == {
        "ok": True,
        "app_name": "Slack",
    }
    assert dispatch_tool_call(broker, "desktop.minimize_window", {}) == {"ok": True}
    assert dispatch_tool_call(broker, "desktop.close_window", {}) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.reveal_path",
        {"path": "~/Downloads/report.pdf"},
    ) == {"ok": True, "path": "~/Downloads/report.pdf"}
    assert dispatch_tool_call(broker, "desktop.permissions", {}) == {
        "ok": True,
        "action": "desktop.permissions",
    }
    assert dispatch_tool_call(broker, "desktop.running_apps", {}) == {
        "ok": True,
        "apps": ["Finder"],
    }
    assert dispatch_tool_call(broker, "desktop.windows", {"app_name": "Google Chrome"}) == {
        "ok": True,
        "app_name": "Google Chrome",
    }
    assert dispatch_tool_call(
        broker,
        "desktop.ui_elements",
        {"role_filter": "button", "limit": 20},
    ) == {"ok": True, "role_filter": "button", "limit": 20}
    assert dispatch_tool_call(
        broker,
        "app.status",
        {"app_name": "Google Chrome"},
    ) == {"ok": True, "app_name": "Google Chrome"}
    assert calls == [
        ("music", "超时空辉夜姬"),
        ("music_control", "pause"),
        ("music_open_and_play",),
        ("note", "hello", "Greeting", "Notes"),
        ("safe_shortcut", "copy"),
        ("safe_key", "arrow_down", 3),
        ("safe_type_text", "hello"),
        ("safe_click", 12, 34),
        ("safe_scroll", "down", 2),
        ("click_ui_element", "Send", "button", 20, 2),
        ("type_into_ui_element", "Search", "hello", "text", 20),
        ("hotkey", "l", ["command"]),
        ("submit_foreground", "send"),
        ("click", 12, 34, 2),
        ("hide_app",),
        ("focus_window", "Slack", "general"),
        ("open_type", "Notes", "hello"),
        ("focus_type", "Notes", "hello"),
        ("open_shortcut", "Google Chrome", "new_tab"),
        ("focus_shortcut", "Slack", "paste"),
        ("open_key", "Google Chrome", "tab", 1),
        ("focus_key", "Slack", "arrow_down", 3),
        ("open_hotkey", "Google Chrome", "l", ["command"]),
        ("focus_hotkey", "Slack", "k", ["command"]),
        ("open_scroll", "Google Chrome", "down", 1),
        ("focus_scroll", "Slack", "up", 3),
        ("open_click", "Google Chrome", 120, 240),
        ("focus_click", "Slack", 320, 180),
        ("open_click_ui", "Google Chrome", "Sign in", "button", 20, 2),
        ("focus_click_ui", "Slack", "Send", "", 80, 1),
        ("open_type_into_ui", "Google Chrome", "Address", "github.com", "text", 20),
        ("focus_type_into_ui", "Slack", "Message", "hello", "", 80),
        ("show_named_app", "Slack"),
        ("hide_named_app", "Slack"),
        ("minimize_named_app", "Slack"),
        ("minimize_window",),
        ("close_window",),
        ("reveal", "~/Downloads/report.pdf"),
        ("permissions",),
        ("running",),
        ("windows", "Google Chrome"),
        ("ui_elements", "button", 20),
        ("status", "Google Chrome"),
    ]


def test_tool_broker_app_open_and_safe_type_text_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_safe_type_text",
        lambda text: calls.append(("type", text))
        or {
            "ok": True,
            "action": "desktop.safe_type_text",
            "data": {"character_count": len(text), "explicit_user_text": True},
        },
    )

    result = broker.app_open_and_safe_type_text("Notes", "hello")

    assert calls == [("open", "Notes"), ("focus", "Notes"), ("type", "hello")]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_safe_type_text"
    assert result["data"] == {
        "app_name": "Notes",
        "foreground_action": "safe_type_text",
        "character_count": 5,
        "explicit_user_text": True,
    }
    assert list(result["fallback_result"]) == ["open", "focus", "safe_type_text"]


def test_tool_broker_app_open_and_safe_key_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_safe_key",
        lambda action, *, repeat_count=1: calls.append(("key", action))
        or {
            "ok": True,
            "action": "desktop.safe_key",
            "data": {
                "key_action": action,
                "key_label": "Tab",
                "key_code": 48,
                "repeat_count": repeat_count,
                "explicit_user_key": True,
            },
        },
    )

    result = broker.app_open_and_safe_key("Google Chrome", "tab", repeat_count=2)

    assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("key", "tab")]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_safe_key"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "safe_key",
        "key_action": "tab",
        "key_label": "Tab",
        "key_code": 48,
        "repeat_count": 2,
        "explicit_user_key": True,
    }
    assert list(result["fallback_result"]) == ["open", "focus", "safe_key"]


def test_tool_broker_app_open_and_hotkey_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_hotkey",
        lambda key, *, modifiers=None: calls.append(("hotkey", key))
        or {
            "ok": True,
            "action": "desktop.hotkey",
            "data": {"key": key, "modifiers": list(modifiers or [])},
        },
    )

    result = broker.app_open_and_hotkey("Google Chrome", "l", modifiers=["command"])

    assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("hotkey", "l")]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_hotkey"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "hotkey",
        "key": "l",
        "modifiers": ["command"],
    }
    assert list(result["fallback_result"]) == ["open", "focus", "hotkey"]


def test_tool_broker_app_open_and_safe_scroll_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_safe_scroll",
        lambda direction, *, pages=1: calls.append(("scroll", direction))
        or {
            "ok": True,
            "action": "desktop.safe_scroll",
            "data": {
                "direction": direction,
                "pages": pages,
                "explicit_user_scroll": True,
            },
        },
    )

    result = broker.app_open_and_safe_scroll("Google Chrome", "down", pages=2)

    assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("scroll", "down")]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_safe_scroll"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "safe_scroll",
        "direction": "down",
        "pages": 2,
        "explicit_user_scroll": True,
    }
    assert list(result["fallback_result"]) == ["open", "focus", "safe_scroll"]


def test_tool_broker_app_open_and_safe_click_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_safe_click",
        lambda x, y: calls.append(("click", x, y))
        or {
            "ok": True,
            "action": "desktop.safe_click",
            "data": {
                "x": int(x),
                "y": int(y),
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        },
    )

    result = broker.app_open_and_safe_click("Google Chrome", 120, 240)

    assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("click", 120, 240)]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_safe_click"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "safe_click",
        "x": 120,
        "y": 240,
        "click_count": 1,
        "explicit_user_coordinates": True,
    }
    assert list(result["fallback_result"]) == ["open", "focus", "safe_click"]


def test_tool_broker_app_open_and_click_ui_element_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "click_ui_element",
        lambda target, *, role_filter="", limit=80, click_count=1: calls.append(
            ("click_ui", target, role_filter, limit, click_count)
        )
        or {
            "ok": True,
            "action": "desktop.click_ui_element",
            "data": {
                "target": target,
                "matched_label": "Sign in",
                "x": 120,
                "y": 240,
                "click_count": click_count,
                "role_filter": role_filter,
            },
        },
    )

    result = broker.app_open_and_click_ui_element(
        "Google Chrome",
        "Sign in",
        role_filter="button",
        limit=20,
        click_count=2,
    )

    assert calls == [
        ("open", "Google Chrome"),
        ("focus", "Google Chrome"),
        ("click_ui", "Sign in", "button", 20, 2),
    ]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_click_ui_element"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "click_ui_element",
        "target": "Sign in",
        "matched_label": "Sign in",
        "x": 120,
        "y": 240,
        "click_count": 2,
        "role_filter": "button",
    }
    assert list(result["fallback_result"]) == ["open", "focus", "click_ui_element"]


def test_tool_broker_app_open_and_type_into_ui_element_sequences_foreground_action(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: calls.append(("open", app_name))
        or {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "type_into_ui_element",
        lambda target, text, *, role_filter="", limit=80: calls.append(
            ("type_into_ui", target, text, role_filter, limit)
        )
        or {
            "ok": True,
            "action": "desktop.type_into_ui_element",
            "data": {
                "target": target,
                "matched_label": "Address",
                "character_count": len(text),
                "role_filter": role_filter,
            },
        },
    )

    result = broker.app_open_and_type_into_ui_element(
        "Google Chrome",
        "Address",
        "github.com",
        role_filter="text",
        limit=20,
    )

    assert calls == [
        ("open", "Google Chrome"),
        ("focus", "Google Chrome"),
        ("type_into_ui", "Address", "github.com", "text", 20),
    ]
    assert result["ok"] is True
    assert result["action"] == "app.open_and_type_into_ui_element"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "foreground_action": "type_into_ui_element",
        "target": "Address",
        "matched_label": "Address",
        "character_count": 10,
        "role_filter": "text",
    }
    assert list(result["fallback_result"]) == ["open", "focus", "type_into_ui_element"]


def test_tool_broker_app_focus_and_safe_shortcut_reports_action_failure(
    tmp_path,
    monkeypatch,
) -> None:
    broker = _broker(tmp_path)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        desktop_mod,
        "app_focus",
        lambda app_name: calls.append(("focus", app_name))
        or {"ok": True, "action": "app.focus", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "desktop_safe_shortcut",
        lambda action: calls.append(("shortcut", action))
        or {
            "ok": False,
            "action": "desktop.safe_shortcut",
            "permission_error": True,
            "permission_targets": ["accessibility"],
            "data": {"shortcut_action": action},
        },
    )

    result = broker.app_focus_and_safe_shortcut("Slack", "paste")

    assert calls == [("focus", "Slack"), ("shortcut", "paste")]
    assert result["ok"] is False
    assert result["action"] == "app.focus_and_safe_shortcut"
    assert result["permission_targets"] == ["accessibility"]
    assert result["data"] == {
        "app_name": "Slack",
        "foreground_action": "safe_shortcut",
        "shortcut_action": "paste",
    }
    assert list(result["fallback_result"]) == ["focus", "safe_shortcut"]


def test_tool_dispatch_registry_routes_browser_tools(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    calls = []

    monkeypatch.setattr(
        broker,
        "browser_open_url",
        lambda url: calls.append(("open", url)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "browser_open_url_and_extract_text",
        lambda url, *, selector="": calls.append(("open_extract", url, selector)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "browser_open_url_and_screenshot",
        lambda url, *, reason="": calls.append(("open_screenshot", url, reason)) or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "browser_click",
        lambda selector, *, fallback_x=None, fallback_y=None, click_count=1: calls.append(
            ("click", selector, fallback_x, fallback_y, click_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "browser_type_text",
        lambda selector, text, **kwargs: calls.append(("type", selector, text, kwargs))
        or {"ok": True},
    )

    assert dispatch_tool_call(
        broker,
        "browser.open_url",
        {"url": "https://example.com"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.open_url_and_extract_text",
        {"url": "https://example.com/docs", "selector": "main"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.open_url_and_screenshot",
        {"url": "https://example.com/docs", "reason": "capture docs"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.click",
        {"selector": "#go", "fallback_x": 12, "fallback_y": 34, "click_count": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.type_text",
        {"selector": "point=12,34", "text": "八千代", "fallback_x": 12, "fallback_y": 34},
    ) == {"ok": True}
    assert calls == [
        ("open", "https://example.com"),
        ("open_extract", "https://example.com/docs", "main"),
        ("open_screenshot", "https://example.com/docs", "capture docs"),
        ("click", "#go", 12, 34, 2),
        ("type", "point=12,34", "八千代", {"fallback_x": 12, "fallback_y": 34}),
    ]


def test_browser_current_page_cdp_failure_returns_recovery_action(monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_configured_browser_cdp_url", lambda: "")

    result = browser_mod.current_page()

    assert result["ok"] is False
    assert result["action"] == "browser.current_page"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["chrome_cdp"]
    assert result["permission_targets"] == ["chrome_cdp"]
    assert result["recovery_actions"] == [
        {
            "label": "打开 Google Chrome",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
            "permission_target": "chrome_cdp",
            "risk_level": "low",
        }
    ]


def test_screen_capture_tool_writes_artifact_metadata(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)

    def fake_capture(target):
        target.write_bytes(b"png")
        return {
            "path": str(target),
            "mime_type": "image/png",
            "format": "png",
            "width": 320,
            "height": 200,
            "size": 3,
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")
    monkeypatch.setattr("apps.locald.screenshot.capture_screenshot_to_file", fake_capture)

    result = broker.call("screen.capture", {"reason": "check desktop"})

    assert result["ok"] is True
    assert result["reason"] == "check desktop"
    assert result["artifact"] == {
        "path": "screenshots/current-screen.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": 3,
        "width": 320,
        "height": 200,
    }
    assert (tmp_path / "artifacts" / "screenshots" / "current-screen.png").read_bytes() == b"png"


def test_screen_capture_permission_failure_returns_recovery_targets(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)

    class ScreenCapturePermissionError(RuntimeError):
        pass

    def fake_capture(_target):
        raise ScreenCapturePermissionError("screen recording permission denied")

    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")
    monkeypatch.setattr("apps.locald.screenshot.capture_screenshot_to_file", fake_capture)

    result = broker.call("screen.capture", {"reason": "check desktop"})

    assert result["ok"] is False
    assert result["action"] == "screen.capture"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["screen_recording"]
    assert result["permission_targets"] == ["screen_recording"]
    assert result["recovery_hints"] == [
        (
            "Grant Screen Recording permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Screen Recording."
        )
    ]
    assert result["recovery_actions"] == [
        {
            "label": "打开屏幕录制权限",
            "tool": "app.open",
            "input": {"app_name": "屏幕录制权限"},
            "permission_target": "screen_recording",
            "risk_level": "low",
        }
    ]


def test_app_open_failure_returns_unified_desktop_result(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Application not found.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.app_open("Missing App")

    assert result["ok"] is False
    assert result["action"] == "app.open"
    assert result["summary"] == "app.open failed"
    assert result["data"] == {"app_name": "Missing App"}
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["error_code"] == "app_not_found"
    assert "确认应用已安装" in result["recovery_hints"][0]
    assert result["recovery_actions"] == [
        {
            "label": "打开应用程序文件夹",
            "tool": "desktop.open_path",
            "input": {"path": "/Applications"},
            "permission_target": "app_not_found",
            "risk_level": "low",
        },
        {
            "label": "打开 App Store",
            "tool": "app.open",
            "input": {"app_name": "App Store"},
            "permission_target": "app_not_found",
            "risk_level": "low",
        },
    ]


def test_app_open_success_records_launch_verification(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {"ok": True, "stdout": "running", "stderr": ""},
    )

    result = desktop_mod.app_open("Google Chrome")

    assert result["ok"] is True
    assert result["action"] == "app.open"
    assert result["data"] == {
        "app_name": "Google Chrome",
        "launch_verified": True,
        "launch_status": "running",
    }
    assert calls[0][0] == ["open", "-a", "Google Chrome"]


def test_app_open_handles_common_finder_folder_aliases(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.app_open("下载文件夹")

    assert result["ok"] is True
    assert result["action"] == "app.open"
    assert result["summary"] == "Opened Downloads"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "app_name": "下载文件夹",
        "path": str(desktop_mod.Path.home() / "Downloads"),
        "open_target": "folder",
    }
    assert calls[0][0] == ["open", str(desktop_mod.Path.home() / "Downloads")]


def test_app_open_handles_system_settings_permission_aliases(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.app_open("屏幕录制权限")

    assert result["ok"] is True
    assert result["action"] == "app.open"
    assert result["summary"] == "Opened System Settings: Screen Recording Permission"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "app_name": "屏幕录制权限",
        "open_target": "system_settings",
        "settings_label": "Screen Recording Permission",
        "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "fallback_used": False,
    }
    assert calls[0][0] == [
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    ]

    result = desktop_mod.app_open("桌面权限")

    assert result["ok"] is True
    assert result["summary"] == "Opened System Settings: Privacy & Security"
    assert result["data"]["settings_label"] == "Privacy & Security"
    assert calls[1][0] == [
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy",
    ]

    result = desktop_mod.app_open("蓝牙设置")

    assert result["ok"] is True
    assert result["summary"] == "Opened System Settings: Bluetooth"
    assert result["data"]["settings_label"] == "Bluetooth"
    assert calls[2][0] == [
        "open",
        "x-apple.systempreferences:com.apple.BluetoothSettings",
    ]

    result = desktop_mod.app_open("Wi-Fi 设置")

    assert result["ok"] is True
    assert result["summary"] == "Opened System Settings: Wi-Fi"
    assert result["data"]["settings_label"] == "Wi-Fi"
    assert calls[3][0] == [
        "open",
        "x-apple.systempreferences:com.apple.wifi-settings-extension",
    ]

    result = desktop_mod.app_open("系统设置里的辅助功能")

    assert result["ok"] is True
    assert result["summary"] == "Opened System Settings: Accessibility Permission"
    assert result["data"]["settings_label"] == "Accessibility Permission"
    assert calls[4][0] == [
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ]


def test_app_open_system_settings_tries_fallback_url(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            1 if len(calls) == 1 else 0,
            stdout="",
            stderr="unsupported URL" if len(calls) == 1 else "",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.app_open("设置的隐私与安全性")

    assert result["ok"] is True
    assert result["action"] == "app.open"
    assert result["summary"] == "Opened System Settings: Privacy & Security"
    assert result["fallback_used"] is True
    assert result["data"] == {
        "app_name": "设置的隐私与安全性",
        "open_target": "system_settings",
        "settings_label": "Privacy & Security",
        "settings_url": "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
        "fallback_used": True,
    }
    assert calls[0][0] == [
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy",
    ]
    assert calls[1][0] == [
        "open",
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
    ]


def test_desktop_reveal_path_reveals_existing_path(monkeypatch, tmp_path) -> None:
    target = tmp_path / "report.md"
    target.write_text("hello", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.reveal_path(str(target))
    expanded = str(target.resolve(strict=False))

    assert result["ok"] is True
    assert result["action"] == "desktop.reveal_path"
    assert result["summary"] == "Revealed report.md in Finder"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "path": str(target),
        "expanded_path": expanded,
        "open_target": "finder_reveal",
        "exists": True,
        "is_dir": False,
    }
    assert calls[0][0] == ["open", "-R", expanded]


def test_desktop_reveal_path_reports_missing_path(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.md"
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")

    result = desktop_mod.reveal_path(str(missing))
    expanded = str(missing.resolve(strict=False))

    assert result["ok"] is False
    assert result["action"] == "desktop.reveal_path"
    assert result["summary"] == "desktop.reveal_path failed"
    assert result["error_code"] == "path_not_found"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "path": str(missing),
        "expanded_path": expanded,
        "open_target": "finder_reveal",
        "exists": False,
    }


def test_desktop_open_path_opens_safe_existing_file(monkeypatch, tmp_path) -> None:
    target = tmp_path / "report.pdf"
    target.write_text("pdf", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path(str(target))
    expanded = str(target.resolve(strict=False))

    assert result["ok"] is True
    assert result["action"] == "desktop.open_path"
    assert result["summary"] == "Opened report.pdf"
    assert result["data"] == {
        "path": str(target),
        "expanded_path": expanded,
        "open_target": "system_open",
        "exists": True,
        "is_dir": False,
        "suffix": ".pdf",
    }
    assert calls[0][0] == ["open", expanded]


def test_desktop_open_path_resolves_latest_download_alias(monkeypatch, tmp_path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    older = downloads / "older.pdf"
    newer = downloads / "newer.pdf"
    partial = downloads / "still-downloading.crdownload"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    partial.write_text("partial", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    os.utime(partial, (300, 300))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path("latest_download")

    assert result["ok"] is True
    assert result["action"] == "desktop.open_path"
    assert result["summary"] == "Opened newer.pdf"
    assert result["data"] == {
        "path": "latest_download",
        "open_target": "system_open",
        "desktop_object": "latest_download",
        "source_folder": str(downloads),
        "expanded_path": str(newer),
        "resolved_path": str(newer),
        "display_path": str(newer),
        "source_exists": True,
        "exists": True,
        "is_dir": False,
        "suffix": ".pdf",
    }
    assert calls[0][0] == ["open", str(newer)]


def test_desktop_reveal_path_resolves_latest_download_alias(monkeypatch, tmp_path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    target = downloads / "latest.txt"
    target.write_text("latest", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.reveal_path("latest_download")

    assert result["ok"] is True
    assert result["action"] == "desktop.reveal_path"
    assert result["summary"] == "Revealed latest.txt in Finder"
    assert result["data"]["desktop_object"] == "latest_download"
    assert result["data"]["resolved_path"] == str(target)
    assert result["data"]["is_dir"] is False
    assert calls[0][0] == ["open", "-R", str(target)]


def test_desktop_open_path_resolves_finder_selection_alias(monkeypatch, tmp_path) -> None:
    target = tmp_path / "selected.pdf"
    target.write_text("pdf", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "osascript":
            return subprocess.CompletedProcess(command, 0, stdout=f"{target}\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path("finder_selection")

    assert result["ok"] is True
    assert result["action"] == "desktop.open_path"
    assert result["summary"] == "Opened selected.pdf"
    assert result["data"] == {
        "path": "finder_selection",
        "open_target": "system_open",
        "desktop_object": "finder_selection",
        "source_app": "Finder",
        "expanded_path": str(target),
        "resolved_path": str(target),
        "display_path": str(target),
        "source_exists": True,
        "exists": True,
        "is_dir": False,
        "suffix": ".pdf",
    }
    assert calls[0][0][0] == "osascript"
    assert calls[1][0] == ["open", str(target)]


def test_desktop_reveal_path_resolves_finder_selection_alias(monkeypatch, tmp_path) -> None:
    target = tmp_path / "selected.txt"
    target.write_text("selected", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "osascript":
            return subprocess.CompletedProcess(command, 0, stdout=f"{target}\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.reveal_path("finder_selection")

    assert result["ok"] is True
    assert result["action"] == "desktop.reveal_path"
    assert result["summary"] == "Revealed selected.txt in Finder"
    assert result["data"]["desktop_object"] == "finder_selection"
    assert result["data"]["resolved_path"] == str(target)
    assert result["data"]["source_app"] == "Finder"
    assert calls[0][0][0] == "osascript"
    assert calls[1][0] == ["open", "-R", str(target)]


def test_desktop_open_path_reports_empty_finder_selection(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path("finder_selection")

    assert result["ok"] is False
    assert result["action"] == "desktop.open_path"
    assert result["error_code"] == "finder_selection_not_found"
    assert result["data"]["desktop_object"] == "finder_selection"
    assert calls[0][0][0] == "osascript"
    assert len(calls) == 1


def test_desktop_open_path_resolves_latest_screenshot_alias(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    downloads = tmp_path / "Downloads"
    pictures = tmp_path / "Pictures"
    desktop.mkdir()
    downloads.mkdir()
    pictures.mkdir()
    older = desktop / "Screenshot 2026-06-01 at 10.00.00.png"
    newer = downloads / "Screen Shot 2026-06-01 at 11.00.00.png"
    not_screenshot = pictures / "vacation.png"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    not_screenshot.write_text("image", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    os.utime(not_screenshot, (300, 300))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path("latest_screenshot")

    assert result["ok"] is True
    assert result["action"] == "desktop.open_path"
    assert result["summary"] == "Opened Screen Shot 2026-06-01 at 11.00.00.png"
    assert result["data"] == {
        "path": "latest_screenshot",
        "open_target": "system_open",
        "desktop_object": "latest_screenshot",
        "source_folders": [str(desktop), str(downloads), str(pictures)],
        "source_folder": str(downloads),
        "expanded_path": str(newer),
        "resolved_path": str(newer),
        "display_path": str(newer),
        "source_exists": True,
        "exists": True,
        "is_dir": False,
        "suffix": ".png",
    }
    assert calls[0][0] == ["open", str(newer)]


def test_desktop_reveal_path_resolves_latest_desktop_item_alias(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    older = desktop / "older.txt"
    newer = desktop / "newer.txt"
    partial = desktop / "still-downloading.part"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    partial.write_text("partial", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    os.utime(partial, (300, 300))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.reveal_path("latest_desktop_item")

    assert result["ok"] is True
    assert result["action"] == "desktop.reveal_path"
    assert result["summary"] == "Revealed newer.txt in Finder"
    assert result["data"]["desktop_object"] == "latest_desktop_item"
    assert result["data"]["source_folder"] == str(desktop)
    assert result["data"]["resolved_path"] == str(newer)
    assert calls[0][0] == ["open", "-R", str(newer)]


def test_desktop_open_path_keeps_safety_for_latest_desktop_item_alias(monkeypatch, tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    target = desktop / "run.sh"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.open_path("latest_desktop_item")

    assert result["ok"] is False
    assert result["action"] == "desktop.open_path"
    assert result["error_code"] == "unsafe_path_type"
    assert result["data"]["desktop_object"] == "latest_desktop_item"
    assert result["data"]["resolved_path"] == str(target)
    assert result["data"]["suffix"] == ".sh"
    assert calls == []


def test_desktop_open_path_blocks_unsafe_file_types(monkeypatch, tmp_path) -> None:
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: calls.append((_args, _kwargs)),
    )

    result = desktop_mod.open_path(str(target))

    assert result["ok"] is False
    assert result["action"] == "desktop.open_path"
    assert result["summary"] == "desktop.open_path blocked"
    assert result["error_code"] == "unsafe_path_type"
    assert ".sh" in result["error"]
    assert result["data"]["suffix"] == ".sh"
    assert calls == []


def test_app_focus_falls_back_to_open_when_automation_is_blocked(monkeypatch) -> None:
    open_calls = []

    def fake_run(command, **kwargs):
        open_calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    osascript_calls = []

    def fake_osascript(script, args=None):
        osascript_calls.append(args)
        if len(osascript_calls) == 1:
            return {
                "ok": False,
                "action": "osascript",
                "summary": "osascript failed",
                "error": "Not authorized to send Apple events to Slack.",
                "permission_error": True,
                "fallback_used": False,
            }
        return {"ok": True, "stdout": "running", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_focus("Slack")

    assert result["ok"] is True
    assert result["action"] == "app.focus"
    assert result["permission_error"] is False
    assert result["fallback_used"] is True
    assert result["fallback_result"]["action"] == "app.open"
    assert result["data"] == {
        "app_name": "Slack",
        "launch_verified": True,
        "launch_status": "running",
        "focus_fallback": "app.open",
    }
    assert open_calls[0][0] == ["open", "-a", "Slack"]
    assert osascript_calls == [["Slack"], ["Slack"]]


def test_app_quit_uses_osascript_and_verifies_running_state(monkeypatch) -> None:
    osascript_calls = []

    def fake_osascript(script, args=None):
        osascript_calls.append(args)
        if len(osascript_calls) == 1:
            return {"ok": True, "stdout": "quit|Slack", "stderr": ""}
        return {"ok": True, "stdout": "not_running", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_quit("Slack")

    assert result["ok"] is True
    assert result["action"] == "app.quit"
    assert result["summary"] == "Quit Slack"
    assert result["data"] == {
        "app_name": "Slack",
        "quit_status": "quit",
        "quit_verified": True,
        "running": False,
        "launch_verified": False,
        "launch_status": "not_running",
    }
    assert result["fallback_used"] is False
    assert osascript_calls == [["Slack"], ["Slack"]]


def test_app_focus_window_raises_matching_window(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "focused|Slack|2|general", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_focus_window("Slack", "general")

    assert result == {
        "ok": True,
        "action": "app.focus_window",
        "summary": "Focused Slack window: general",
        "data": {
            "app_name": "Slack",
            "title_contains": "general",
            "focus_status": "focused",
            "window_index": 2,
            "window_title": "general",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert 'perform action "AXRaise"' in calls[0][0]
    assert 'attribute "AXMinimized"' in calls[0][0]
    assert calls[0][1] == ["Slack", "general"]


def test_app_focus_window_reports_window_not_found(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, args=None: {"ok": True, "stdout": "not_found|Slack|general", "stderr": ""},
    )

    result = desktop_mod.app_focus_window("Slack", "general")

    assert result["ok"] is False
    assert result["action"] == "app.focus_window"
    assert result["summary"] == "No Slack window matched general"
    assert result["error_code"] == "window_not_found"
    assert result["data"] == {
        "app_name": "Slack",
        "title_contains": "general",
        "focus_status": "not_found",
    }


def test_app_show_unhides_restores_and_activates_app(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "shown|Slack|2", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_show("Slack")

    assert result == {
        "ok": True,
        "action": "app.show",
        "summary": "Showed Slack",
        "data": {
            "app_name": "Slack",
            "show_status": "shown",
            "restored_window_count": 2,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert "set visible of application process appName to true" in calls[0][0]
    assert 'attribute "AXMinimized"' in calls[0][0]
    assert "tell application appName to activate" in calls[0][0]
    assert calls[0][1] == ["Slack"]


def test_app_show_reports_launch_when_app_was_not_running(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, args=None: {"ok": True, "stdout": "launched|Slack|0", "stderr": ""},
    )

    result = desktop_mod.app_show("Slack")

    assert result["ok"] is True
    assert result["action"] == "app.show"
    assert result["summary"] == "Launched and showed Slack"
    assert result["data"] == {
        "app_name": "Slack",
        "show_status": "launched",
        "restored_window_count": 0,
    }


def test_app_hide_uses_system_events_process_visibility(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "hidden|Slack", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_hide("Slack")

    assert result == {
        "ok": True,
        "action": "app.hide",
        "summary": "Hid Slack",
        "data": {"app_name": "Slack", "hide_status": "hidden"},
        "permission_error": False,
        "fallback_used": False,
    }
    assert "set visible of application process appName to false" in calls[0][0]
    assert calls[0][1] == ["Slack"]


def test_app_hide_reports_not_running(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, args=None: {"ok": True, "stdout": "not_running|Slack", "stderr": ""},
    )

    result = desktop_mod.app_hide("Slack")

    assert result["ok"] is False
    assert result["action"] == "app.hide"
    assert result["summary"] == "Slack is not running"
    assert result["error_code"] == "app_not_running"
    assert result["data"] == {"app_name": "Slack", "hide_status": "not_running"}


def test_app_minimize_uses_system_events_window_minimize(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "minimized|Slack|2", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.app_minimize("Slack")

    assert result == {
        "ok": True,
        "action": "app.minimize",
        "summary": "Minimized Slack",
        "data": {
            "app_name": "Slack",
            "minimize_status": "minimized",
            "window_count": 2,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert 'attribute "AXMinimized"' in calls[0][0]
    assert calls[0][1] == ["Slack"]


def test_app_minimize_reports_no_windows(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, args=None: {"ok": True, "stdout": "no_windows|Slack|0", "stderr": ""},
    )

    result = desktop_mod.app_minimize("Slack")

    assert result["ok"] is False
    assert result["action"] == "app.minimize"
    assert result["summary"] == "Slack has no windows to minimize"
    assert result["error_code"] == "app_no_windows"
    assert result["data"] == {
        "app_name": "Slack",
        "minimize_status": "no_windows",
        "window_count": 0,
    }


def test_desktop_active_window_permission_failure_returns_recovery_targets(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Not authorized to send Apple events to System Events.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.active_window()

    assert result["ok"] is False
    assert result["action"] == "desktop.active_window"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]
    assert result["recovery_hints"] == [
        (
            "Grant Automation permission so Oha-Yachiyo can control System Events "
            "or the target app in macOS System Settings > Privacy & Security > Automation."
        ),
        (
            "Grant Accessibility permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Accessibility."
        ),
    ]


def test_desktop_permissions_reports_ready_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.desktop_permissions.desktop_permission_missing_by_capability",
        lambda use_cache=True: {
            "desktop_execution": [],
            "screen_capture": [],
            "active_window": [],
        },
    )

    result = desktop_mod.permissions()

    assert result["ok"] is True
    assert result["action"] == "desktop.permissions"
    assert result["summary"] == "Desktop execution permissions are ready."
    assert result["permission_error"] is False
    assert result["permission_targets"] == []
    assert result["affected_tools"] == []
    assert result["data"]["diagnostic_route"] == "/yachiyo/readiness"


def test_desktop_permissions_reports_missing_targets_and_affected_tools(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.desktop_permissions.desktop_permission_missing_by_capability",
        lambda use_cache=True: {
            "screen_capture": ["screen_recording"],
            "active_window": ["automation_or_accessibility"],
            "media_control": ["music_app", "automation"],
        },
    )

    result = desktop_mod.permissions()

    assert result["ok"] is True
    assert result["action"] == "desktop.permissions"
    assert result["permission_error"] is True
    assert result["permission_targets"] == [
        "screen_recording",
        "automation_or_accessibility",
        "music_app",
        "automation",
    ]
    assert result["affected_tools"] == [
        "screen.capture",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    ]
    assert result["data"]["missing_permissions"] == {
        "screen_capture": ["screen_recording"],
        "active_window": ["automation_or_accessibility"],
        "media_control": ["music_app", "automation"],
    }
    assert result["recovery_actions"] == [
        {
            "label": "打开屏幕录制权限",
            "tool": "app.open",
            "input": {"app_name": "屏幕录制权限"},
            "permission_target": "screen_recording",
            "risk_level": "low",
        },
        {
            "label": "打开自动化权限",
            "tool": "app.open",
            "input": {"app_name": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        },
        {
            "label": "打开辅助功能权限",
            "tool": "app.open",
            "input": {"app_name": "辅助功能权限"},
            "permission_target": "accessibility",
            "risk_level": "low",
        },
        {
            "label": "打开 Apple Music",
            "tool": "app.open",
            "input": {"app_name": "Music"},
            "permission_target": "music_app",
            "risk_level": "low",
        },
    ]
    assert result["data"]["recovery_actions"] == result["recovery_actions"]
    assert any("Screen Recording permission" in hint for hint in result["recovery_hints"])


def test_desktop_permission_preflight_reports_cached_missing_targets(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.desktop_permissions.cached_desktop_permission_missing_by_capability",
        lambda: {
            "foreground_input": ["accessibility"],
        },
    )

    result = desktop_mod.permission_preflight()

    assert result["ok"] is True
    assert result["action"] == "desktop.permission_preflight"
    assert result["permission_error"] is True
    assert result["permission_targets"] == ["accessibility"]
    assert "desktop.safe_type_text" in result["affected_tools"]
    assert result["recovery_actions"] == [
        {
            "label": "打开辅助功能权限",
            "tool": "app.open",
            "input": {"app_name": "辅助功能权限"},
            "permission_target": "accessibility",
            "risk_level": "low",
        }
    ]
    assert result["data"]["recovery_actions"] == result["recovery_actions"]


def test_desktop_running_apps_returns_foreground_app_list(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {
            "ok": True,
            "stdout": "Finder|101|false\nGoogle Chrome|202|true\nMusic|303|false",
            "stderr": "",
        },
    )

    result = desktop_mod.running_apps()

    assert result["ok"] is True
    assert result["action"] == "desktop.running_apps"
    assert result["summary"] == "Running apps: Finder, Google Chrome, Music"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "apps": [
            {"name": "Finder", "pid": 101, "frontmost": False},
            {"name": "Google Chrome", "pid": 202, "frontmost": True},
            {"name": "Music", "pid": 303, "frontmost": False},
        ],
        "count": 3,
        "frontmost": "Google Chrome",
    }


def test_desktop_running_apps_permission_failure_returns_recovery_targets(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Not authorized to send Apple events to System Events.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.running_apps()

    assert result["ok"] is False
    assert result["action"] == "desktop.running_apps"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]


def test_desktop_windows_returns_window_titles(monkeypatch) -> None:
    osascript_args = []

    def fake_osascript(_script, args=None):
        osascript_args.append(args)
        return {
            "ok": True,
            "stdout": "Finder\t101\t1\tfalse\tDownloads\nGoogle Chrome\t202\t1\ttrue\tChatGPT",
            "stderr": "",
        }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.windows()

    assert result["ok"] is True
    assert result["action"] == "desktop.windows"
    assert result["summary"] == "Open windows: Finder: Downloads, Google Chrome: ChatGPT"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "app_name": "",
        "windows": [
            {
                "app_name": "Finder",
                "pid": 101,
                "index": 1,
                "frontmost": False,
                "title": "Downloads",
            },
            {
                "app_name": "Google Chrome",
                "pid": 202,
                "index": 1,
                "frontmost": True,
                "title": "ChatGPT",
            },
        ],
        "count": 2,
    }
    assert osascript_args == [[""]]


def test_desktop_windows_permission_failure_returns_recovery_targets(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Not authorized to send Apple events to System Events.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.windows()

    assert result["ok"] is False
    assert result["action"] == "desktop.windows"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]


def test_desktop_ui_elements_returns_foreground_accessibility_controls(monkeypatch) -> None:
    osascript_args = []

    def fake_osascript(_script, args=None):
        osascript_args.append(args)
        return {
            "ok": True,
            "stdout": (
                "META\tGoogle Chrome\t202\tChatGPT\n"
                "0\tAXButton\t\tSend\tSend message\t\ttrue\t100\t220\t40\t40\n"
                "1\tAXTextField\t\t\tMessage\tDraft\ttrue\t20\t200\t300\t40"
            ),
            "stderr": "",
        }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.ui_elements(role_filter="button", limit=20)

    assert result["ok"] is True
    assert result["action"] == "desktop.ui_elements"
    assert result["summary"] == "Google Chrome UI elements: AXButton: Send"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "app_name": "Google Chrome",
        "pid": 202,
        "title": "ChatGPT",
        "elements": [
            {
                "depth": 0,
                "role": "AXButton",
                "subrole": "",
                "name": "Send",
                "description": "Send message",
                "value": "",
                "enabled": True,
                "frame": {"x": 100, "y": 220, "width": 40, "height": 40},
                "center": {"x": 120, "y": 240},
            },
        ],
        "count": 1,
        "truncated": False,
        "role_filter": "button",
        "limit": 20,
    }
    assert osascript_args == [["20", "2"]]


def test_desktop_ui_elements_permission_failure_returns_recovery_targets(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Not authorized to send Apple events to System Events.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.ui_elements()

    assert result["ok"] is False
    assert result["action"] == "desktop.ui_elements"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]


def test_desktop_click_ui_element_matches_foreground_control_and_clicks_center(
    monkeypatch,
) -> None:
    clicks: list[tuple[str, int, int, int]] = []
    observed = {
        "ok": True,
        "action": "desktop.ui_elements",
        "summary": "Google Chrome UI elements: AXButton: Send",
        "data": {
            "app_name": "Google Chrome",
            "title": "ChatGPT",
            "elements": [
                {
                    "depth": 0,
                    "role": "AXTextField",
                    "name": "",
                    "description": "Message",
                    "value": "",
                    "enabled": True,
                    "center": {"x": 80, "y": 240},
                },
                {
                    "depth": 0,
                    "role": "AXButton",
                    "name": "Send",
                    "description": "Send message",
                    "value": "",
                    "enabled": True,
                    "center": {"x": 120, "y": 240},
                },
            ],
        },
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "ui_elements",
        lambda role_filter="", limit=80: observed,
    )

    def fake_click(action_name, x, y, *, click_count=1):
        clicks.append((action_name, x, y, click_count))
        return {
            "ok": True,
            "action": action_name,
            "summary": f"Clicked foreground desktop at ({x}, {y})",
            "data": {"x": x, "y": y, "click_count": click_count},
            "permission_error": False,
            "fallback_used": False,
        }

    monkeypatch.setattr(desktop_mod, "_send_desktop_click", fake_click)

    result = desktop_mod.click_ui_element(
        "Send",
        role_filter="button",
        limit=20,
        click_count=2,
    )

    assert clicks == [("desktop.click_ui_element", 120, 240, 2)]
    assert result["ok"] is True
    assert result["action"] == "desktop.click_ui_element"
    assert result["summary"] == "Clicked foreground UI element: Send"
    assert result["data"]["target"] == "Send"
    assert result["data"]["matched_label"] == "Send"
    assert result["data"]["role_filter"] == "button"
    assert result["data"]["match_count"] == 1
    assert result["data"]["element"]["role"] == "AXButton"
    assert result["fallback_result"] == {"observe": observed}


def test_desktop_click_ui_element_returns_candidates_without_blind_click(
    monkeypatch,
) -> None:
    observed = {
        "ok": True,
        "action": "desktop.ui_elements",
        "summary": "Notes UI elements",
        "data": {
            "app_name": "Notes",
            "title": "Draft",
            "elements": [
                {
                    "depth": 0,
                    "role": "AXButton",
                    "name": "Cancel",
                    "enabled": True,
                    "center": {"x": 44, "y": 55},
                }
            ],
        },
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "ui_elements", lambda role_filter="", limit=80: observed)
    monkeypatch.setattr(
        desktop_mod,
        "_send_desktop_click",
        lambda *args, **kwargs: pytest.fail("should not click without a UI element match"),
    )

    result = desktop_mod.click_ui_element("Send", role_filter="button")

    assert result["ok"] is False
    assert result["action"] == "desktop.click_ui_element"
    assert result["error"] == "ui_element_not_found"
    assert result["data"]["target"] == "Send"
    assert result["data"]["candidates"] == [
        {
            "role": "AXButton",
            "label": "Cancel",
            "enabled": True,
            "center": {"x": 44, "y": 55},
        }
    ]


def test_desktop_click_ui_element_permission_failure_returns_recovery_targets(
    monkeypatch,
) -> None:
    observed = {
        "ok": False,
        "action": "desktop.ui_elements",
        "summary": "desktop.ui_elements failed",
        "error": "Not authorized to send Apple events to System Events.",
        "data": {},
        "permission_error": True,
        "fallback_used": False,
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "ui_elements", lambda role_filter="", limit=80: observed)

    result = desktop_mod.click_ui_element("Send")

    assert result["ok"] is False
    assert result["action"] == "desktop.click_ui_element"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]
    assert result["data"]["target"] == "Send"
    assert result["fallback_result"] == {"observe": observed}


def test_desktop_type_into_ui_element_matches_input_focuses_and_types(
    monkeypatch,
) -> None:
    clicks: list[tuple[str, int, int, int]] = []
    typed: list[tuple[str, str, str]] = []
    observed = {
        "ok": True,
        "action": "desktop.ui_elements",
        "summary": "Google Chrome UI elements: AXTextField: Search",
        "data": {
            "app_name": "Google Chrome",
            "title": "Search",
            "elements": [
                {
                    "depth": 0,
                    "role": "AXTextField",
                    "name": "Search",
                    "description": "Search field",
                    "value": "",
                    "enabled": True,
                    "center": {"x": 120, "y": 240},
                }
            ],
        },
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "ui_elements", lambda role_filter="", limit=80: observed)

    def fake_click(action_name, x, y, *, click_count=1):
        clicks.append((action_name, x, y, click_count))
        return {
            "ok": True,
            "action": action_name,
            "summary": f"Clicked foreground desktop at ({x}, {y})",
            "data": {"x": x, "y": y, "click_count": click_count},
            "permission_error": False,
            "fallback_used": False,
        }

    def fake_type(action_name, text, *, summary):
        typed.append((action_name, text, summary))
        return {
            "ok": True,
            "action": action_name,
            "summary": summary,
            "data": {"character_count": len(text)},
            "permission_error": False,
            "fallback_used": False,
        }

    monkeypatch.setattr(desktop_mod, "_send_desktop_click", fake_click)
    monkeypatch.setattr(desktop_mod, "_send_desktop_text", fake_type)

    result = desktop_mod.type_into_ui_element("Search", "yachiyo", role_filter="text", limit=20)

    assert clicks == [("desktop.type_into_ui_element", 120, 240, 1)]
    assert typed == [
        (
            "desktop.type_into_ui_element",
            "yachiyo",
            "Typed into foreground UI element: Search",
        )
    ]
    assert result["ok"] is True
    assert result["action"] == "desktop.type_into_ui_element"
    assert result["summary"] == "Typed into foreground UI element: Search"
    assert result["data"]["target"] == "Search"
    assert result["data"]["matched_label"] == "Search"
    assert result["data"]["role_filter"] == "text"
    assert result["data"]["character_count"] == 7
    assert result["data"]["match_count"] == 1
    assert result["data"]["element"]["role"] == "AXTextField"
    assert "text" not in result["data"]
    assert list(result["fallback_result"]) == ["observe", "focus", "type_text"]


def test_desktop_type_into_ui_element_returns_candidates_without_blind_typing(
    monkeypatch,
) -> None:
    observed = {
        "ok": True,
        "action": "desktop.ui_elements",
        "summary": "Notes UI elements",
        "data": {
            "app_name": "Notes",
            "title": "Draft",
            "elements": [
                {
                    "depth": 0,
                    "role": "AXTextField",
                    "name": "Title",
                    "enabled": True,
                    "center": {"x": 44, "y": 55},
                }
            ],
        },
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "ui_elements", lambda role_filter="", limit=80: observed)
    monkeypatch.setattr(
        desktop_mod,
        "_send_desktop_click",
        lambda *args, **kwargs: pytest.fail("should not focus without a UI element match"),
    )
    monkeypatch.setattr(
        desktop_mod,
        "_send_desktop_text",
        lambda *args, **kwargs: pytest.fail("should not type without a UI element match"),
    )

    result = desktop_mod.type_into_ui_element("Search", "hello")

    assert result["ok"] is False
    assert result["action"] == "desktop.type_into_ui_element"
    assert result["error"] == "ui_element_not_found"
    assert result["data"]["target"] == "Search"
    assert result["data"]["character_count"] == 5
    assert result["data"]["candidates"] == [
        {
            "role": "AXTextField",
            "label": "Title",
            "enabled": True,
            "center": {"x": 44, "y": 55},
        }
    ]


def test_desktop_type_into_ui_element_permission_failure_returns_recovery_targets(
    monkeypatch,
) -> None:
    observed = {
        "ok": False,
        "action": "desktop.ui_elements",
        "summary": "desktop.ui_elements failed",
        "error": "Not authorized to send Apple events to System Events.",
        "data": {},
        "permission_error": True,
        "fallback_used": False,
    }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "ui_elements", lambda role_filter="", limit=80: observed)

    result = desktop_mod.type_into_ui_element("Search", "hello")

    assert result["ok"] is False
    assert result["action"] == "desktop.type_into_ui_element"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["automation_or_accessibility"]
    assert result["permission_targets"] == ["automation", "accessibility"]
    assert result["data"]["target"] == "Search"
    assert result["data"]["character_count"] == 5
    assert result["fallback_result"] == {"observe": observed}


def test_app_status_reports_running_state(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {"ok": True, "stdout": "running", "stderr": ""},
    )

    result = desktop_mod.app_status("Google Chrome")

    assert result["ok"] is True
    assert result["action"] == "app.status"
    assert result["summary"] == "Google Chrome is running"
    assert result["permission_error"] is False
    assert result["fallback_used"] is False
    assert result["data"] == {
        "app_name": "Google Chrome",
        "running": True,
        "status": "running",
    }


def test_app_status_reports_not_running_state(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {"ok": True, "stdout": "not_running", "stderr": ""},
    )

    result = desktop_mod.app_status("Slack")

    assert result["ok"] is True
    assert result["action"] == "app.status"
    assert result["summary"] == "Slack is not running"
    assert result["data"] == {
        "app_name": "Slack",
        "running": False,
        "status": "not_running",
    }


def test_desktop_close_window_uses_standard_foreground_shortcut(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "closed_window", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.desktop_close_window()

    assert result == {
        "ok": True,
        "action": "desktop.close_window",
        "summary": "Closed the foreground window",
        "data": {"key": "w", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }
    assert "keystroke \"w\" using {command down}" in calls[0][0]
    assert calls[0][1] is None


def test_desktop_minimize_window_uses_standard_foreground_shortcut(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "minimized_window", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.desktop_minimize_window()

    assert result == {
        "ok": True,
        "action": "desktop.minimize_window",
        "summary": "Minimized the foreground window",
        "data": {"key": "m", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }
    assert "keystroke \"m\" using {command down}" in calls[0][0]
    assert calls[0][1] is None


def test_desktop_hide_app_uses_standard_foreground_shortcut(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {"ok": True, "stdout": "hidden_app", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.desktop_hide_app()

    assert result == {
        "ok": True,
        "action": "desktop.hide_app",
        "summary": "Hid the foreground app",
        "data": {"key": "h", "modifiers": ["command"]},
        "permission_error": False,
        "fallback_used": False,
    }
    assert "keystroke \"h\" using {command down}" in calls[0][0]
    assert calls[0][1] is None


def test_desktop_type_text_permission_failure_returns_accessibility_target(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="System Events got an error: osascript is not allowed assistive access.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_type_text("hello")

    assert result["ok"] is False
    assert result["action"] == "desktop.type_text"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["accessibility"]
    assert result["permission_targets"] == ["accessibility"]
    assert result["recovery_hints"] == [
        (
            "Grant Accessibility permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Accessibility."
        )
    ]


def test_desktop_safe_type_text_uses_system_events_with_explicit_text(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="typed\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_type_text("hello")

    assert result == {
        "ok": True,
        "action": "desktop.safe_type_text",
        "summary": "Typed user-provided text into the foreground app",
        "data": {"character_count": 5, "explicit_user_text": True},
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert calls[0][0][-1] == "hello"
    assert "keystroke textToType" in calls[0][0][2]


def test_desktop_click_uses_system_events_with_coordinates(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="clicked\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_click(12.2, "34.6", click_count=2)

    assert result == {
        "ok": True,
        "action": "desktop.click",
        "summary": "Clicked foreground desktop at (12, 35)",
        "data": {"x": 12, "y": 35, "click_count": 2},
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert calls[0][0][-3:] == ["12", "35", "2"]


def test_desktop_safe_click_uses_single_system_events_click(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="clicked\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_click(12.2, "34.6")

    assert result == {
        "ok": True,
        "action": "desktop.safe_click",
        "summary": "Clicked explicit foreground coordinate at (12, 35)",
        "data": {
            "x": 12,
            "y": 35,
            "click_count": 1,
            "explicit_user_coordinates": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert calls[0][0][-3:] == ["12", "35", "1"]


def test_desktop_safe_scroll_uses_system_events_page_keys(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="scrolled\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    down = desktop_mod.desktop_safe_scroll("down", pages=2)
    up = desktop_mod.desktop_safe_scroll("up")

    assert down == {
        "ok": True,
        "action": "desktop.safe_scroll",
        "summary": "Scrolled foreground desktop down 2 pages",
        "data": {
            "direction": "down",
            "pages": 2,
            "key_code": 121,
            "explicit_user_scroll": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert up["ok"] is True
    assert up["data"] == {
        "direction": "up",
        "pages": 1,
        "key_code": 116,
        "explicit_user_scroll": True,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert calls[0][0][-2:] == ["121", "2"]
    assert calls[1][0][-2:] == ["116", "1"]


def test_desktop_safe_shortcut_uses_whitelisted_system_events_keystroke(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="hotkey\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_shortcut("browser_forward")

    assert result == {
        "ok": True,
        "action": "desktop.safe_shortcut",
        "summary": "Executed safe shortcut: browser forward",
        "data": {
            "key": "]",
            "modifiers": ["command"],
            "shortcut_action": "browser_forward",
            "shortcut_label": "browser forward",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert 'keystroke keyName using {command down}' in calls[0][0][2]
    assert calls[0][0][-1] == "]"


def test_desktop_safe_shortcut_reopen_closed_tab_uses_command_shift_t(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="hotkey\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_shortcut("reopen_closed_tab")

    assert result == {
        "ok": True,
        "action": "desktop.safe_shortcut",
        "summary": "Executed safe shortcut: reopen closed tab",
        "data": {
            "key": "t",
            "modifiers": ["command", "shift"],
            "shortcut_action": "reopen_closed_tab",
            "shortcut_label": "reopen closed tab",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert "keystroke keyName using {command down, shift down}" in calls[0][0][2]
    assert calls[0][0][-1] == "t"


def test_desktop_safe_shortcut_new_document_uses_command_n(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="new document\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_shortcut("new_document")

    assert result["ok"] is True
    assert result["summary"] == "Executed safe shortcut: new document"
    assert result["data"]["key"] == "n"
    assert result["data"]["modifiers"] == ["command"]
    assert result["data"]["shortcut_action"] == "new_document"
    assert result["data"]["shortcut_label"] == "new document"
    assert calls[0][0][-1] == "n"


def test_desktop_safe_shortcut_new_event_uses_command_n(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="new event\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_shortcut("new_event")

    assert result["ok"] is True
    assert result["summary"] == "Executed safe shortcut: new calendar event"
    assert result["data"]["key"] == "n"
    assert result["data"]["modifiers"] == ["command"]
    assert result["data"]["shortcut_action"] == "new_event"
    assert result["data"]["shortcut_label"] == "new calendar event"
    assert calls[0][0][-1] == "n"


def test_desktop_notes_create_uses_macos_notes_automation(monkeypatch) -> None:
    calls = []

    def fake_run_osascript(script, args=None):
        calls.append((script, args or []))
        return {"ok": True, "stdout": "note-id", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_run_osascript)

    result = desktop_mod.notes_create("hello world")

    assert result["ok"] is True
    assert result["action"] == "notes.create"
    assert result["data"] == {
        "title": "hello world",
        "body_length": 11,
        "folder_name": "",
        "note_id": "note-id",
    }
    assert "tell application \"Notes\"" in calls[0][0]
    assert calls[0][1] == ["hello world", "hello world", ""]


def test_desktop_reminders_create_uses_macos_reminders_automation(monkeypatch) -> None:
    calls = []

    def fake_run_osascript(script, args=None):
        calls.append((script, args or []))
        return {"ok": True, "stdout": "reminder-id", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_run_osascript)

    result = desktop_mod.reminders_create("开会", due_at="2026-06-25T15:00")

    assert result["ok"] is True
    assert result["action"] == "reminders.create"
    assert result["data"] == {
        "title": "开会",
        "due_at": "2026-06-25T15:00",
        "list_name": "",
        "reminder_id": "reminder-id",
    }
    assert "tell application \"Reminders\"" in calls[0][0]
    assert calls[0][1] == ["开会", "", "true", "2026", "6", "25", "15", "0"]


def test_desktop_calendar_create_event_defaults_to_one_hour(monkeypatch) -> None:
    calls = []

    def fake_run_osascript(script, args=None):
        calls.append((script, args or []))
        return {"ok": True, "stdout": "event-id", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_run_osascript)

    result = desktop_mod.calendar_create_event("开会", start_at="2026-06-25T15:00")

    assert result["ok"] is True
    assert result["action"] == "calendar.create_event"
    assert result["data"] == {
        "title": "开会",
        "start_at": "2026-06-25T15:00",
        "end_at": "2026-06-25T16:00",
        "calendar_name": "",
        "event_id": "event-id",
    }
    assert "tell application \"Calendar\"" in calls[0][0]
    assert calls[0][1] == [
        "开会",
        "",
        "true",
        "2026",
        "6",
        "25",
        "15",
        "0",
        "true",
        "2026",
        "6",
        "25",
        "16",
        "0",
    ]


def test_native_note_and_schedule_permission_failures_return_automation_targets(monkeypatch) -> None:
    def fake_run_osascript(_script, _args=None):
        return {
            "ok": False,
            "action": "osascript",
            "summary": "osascript failed",
            "permission_error": True,
            "fallback_used": False,
        }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_run_osascript)

    note = desktop_mod.notes_create("hello")
    reminder = desktop_mod.reminders_create("开会", due_at="2026-06-25T15:00")
    calendar_event = desktop_mod.calendar_create_event("开会", start_at="2026-06-25T15:00")

    assert note["ok"] is False
    assert note["action"] == "notes.create"
    assert note["missing_permissions"] == ["automation"]
    assert note["permission_targets"] == ["automation"]
    assert note["recovery_actions"][0]["permission_target"] == "automation"
    assert reminder["ok"] is False
    assert reminder["action"] == "reminders.create"
    assert reminder["missing_permissions"] == ["automation"]
    assert reminder["permission_targets"] == ["automation"]
    assert reminder["recovery_actions"][0]["permission_target"] == "automation"
    assert calendar_event["ok"] is False
    assert calendar_event["action"] == "calendar.create_event"
    assert calendar_event["missing_permissions"] == ["automation"]
    assert calendar_event["permission_targets"] == ["automation"]
    assert calendar_event["recovery_actions"][0]["permission_target"] == "automation"


def test_desktop_safe_key_uses_whitelisted_system_events_key_code(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="pressed\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_key("arrow_down", repeat_count=3)

    assert result == {
        "ok": True,
        "action": "desktop.safe_key",
        "summary": "Pressed safe foreground key: Down Arrow x3",
        "data": {
            "key_action": "arrow_down",
            "key_label": "Down Arrow",
            "key_code": 125,
            "repeat_count": 3,
            "explicit_user_key": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][0][0:2] == ["osascript", "-e"]
    assert calls[0][0][-2:] == ["125", "3"]


def test_desktop_safe_key_accepts_directional_chinese_aliases(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="pressed\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_key("向下箭头", repeat_count=2)

    assert result["ok"] is True
    assert result["data"]["key_action"] == "arrow_down"
    assert result["data"]["key_label"] == "Down Arrow"
    assert result["data"]["repeat_count"] == 2
    assert calls[0][0][-2:] == ["125", "2"]


def test_desktop_safe_key_uses_shift_modifier_for_shift_tab(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="pressed\n", stderr="")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_key("shift_tab")

    assert result["ok"] is True
    assert result["data"]["key_action"] == "shift_tab"
    assert result["data"]["key_label"] == "Shift+Tab"
    assert result["data"]["key_code"] == 48
    assert result["data"]["repeat_count"] == 1
    assert any("using {shift down}" in str(part) for part in calls[0][0])
    assert calls[0][0][-2:] == ["48", "1"]


def test_desktop_click_permission_failure_returns_accessibility_target(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="System Events got an error: not allowed assistive access.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_click(12, 34)

    assert result["ok"] is False
    assert result["action"] == "desktop.click"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["accessibility"]
    assert result["permission_targets"] == ["accessibility"]
    assert result["recovery_hints"] == [
        (
            "Grant Accessibility permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Accessibility."
        )
    ]


def test_desktop_safe_scroll_permission_failure_returns_accessibility_target(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="System Events got an error: not allowed assistive access.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_scroll("down")

    assert result["ok"] is False
    assert result["action"] == "desktop.safe_scroll"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["accessibility"]
    assert result["permission_targets"] == ["accessibility"]


def test_desktop_safe_key_permission_failure_returns_accessibility_target(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="System Events got an error: not allowed assistive access.",
        )

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.desktop_safe_key("tab")

    assert result["ok"] is False
    assert result["action"] == "desktop.safe_key"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["accessibility"]
    assert result["permission_targets"] == ["accessibility"]


def test_apple_music_permission_failure_returns_music_and_automation_targets(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {
            "ok": False,
            "action": "osascript",
            "summary": "osascript failed",
            "error": "Not authorized to send Apple events to Music.",
            "permission_error": True,
            "fallback_used": False,
        },
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )

    result = desktop_mod.apple_music_play("超时空辉夜姬")

    assert result["ok"] is False
    assert result["action"] == "media.apple_music_play"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["music_app", "automation"]
    assert result["permission_targets"] == ["music_app", "automation"]
    assert result["recovery_hints"] == [
        (
            "Open Music.app once, confirm the track exists in the local library, "
            "and allow Automation when macOS asks for Music control."
        ),
        (
            "Grant Automation permission so Oha-Yachiyo can control System Events "
            "or the target app in macOS System Settings > Privacy & Security > Automation."
        ),
    ]
    assert result["recovery_actions"] == [
        {
            "label": "打开 Apple Music",
            "tool": "app.open",
            "input": {"app_name": "Music"},
            "permission_target": "music_app",
            "risk_level": "low",
        },
        {
            "label": "打开自动化权限",
            "tool": "app.open",
            "input": {"app_name": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        },
    ]
    assert result["fallback_used"] is True


def test_apple_music_play_opens_search_when_track_is_not_in_library(monkeypatch) -> None:
    subprocess_calls = []

    def fake_run(command, *, capture_output=None, text=None, timeout=None, check=None):
        subprocess_calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "check": check,
            }
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {
            "ok": True,
            "stdout": "not_found|超时空辉夜姬|",
            "stderr": "",
        },
    )
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.apple_music_play("超时空辉夜姬")

    search_url = "https://music.apple.com/search?term=%E8%B6%85%E6%97%B6%E7%A9%BA%E8%BE%89%E5%A4%9C%E5%A7%AC"
    assert result["ok"] is False
    assert result["action"] == "media.apple_music_play"
    assert result["summary"] == "Could not directly play 超时空辉夜姬; opened Apple Music search."
    assert result["data"] == {
        "query": "超时空辉夜姬",
        "status": "not_found",
        "search_url": search_url,
        "search_opened": True,
    }
    assert result["permission_error"] is False
    assert result["fallback_used"] is True
    assert result["fallback"] == "apple_music_search"
    assert result["fallback_result"] == {
        "ok": True,
        "action": "media.apple_music.search",
        "summary": "Opened Apple Music search for 超时空辉夜姬",
        "data": {
            "query": "超时空辉夜姬",
            "url": search_url,
            "open_target": "apple_music_search",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert subprocess_calls == [
        {
            "command": ["open", "-a", "Music", search_url],
            "capture_output": True,
            "text": True,
            "timeout": 10,
            "check": False,
        }
    ]


def test_apple_music_control_executes_low_risk_playback_action(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        return {
            "ok": True,
            "stdout": "controlled|pause|paused|超时空辉夜姬|Yachiyo",
            "stderr": "",
        }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.apple_music_control("pause")

    assert result == {
        "ok": True,
        "action": "media.apple_music_control",
        "summary": "Apple Music pause executed",
        "data": {
            "control": "pause",
            "player_state": "paused",
            "track": "超时空辉夜姬",
            "artist": "Yachiyo",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][1] == ["pause"]


def test_apple_music_open_and_play_opens_music_then_starts_playback(monkeypatch) -> None:
    calls = []

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": "Opened Music",
            "data": {"app_name": app_name},
        }

    def fake_music_control(action: str) -> dict[str, Any]:
        calls.append(("control", action))
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": "Apple Music play executed",
            "data": {
                "control": action,
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
            "permission_error": False,
            "fallback_used": False,
        }

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "app_open", fake_app_open)
    monkeypatch.setattr(desktop_mod, "apple_music_control", fake_music_control)

    result = desktop_mod.apple_music_open_and_play()

    assert result == {
        "ok": True,
        "action": "media.apple_music_open_and_play",
        "summary": "Opened Music and started playback",
        "data": {
            "app_name": "Music",
            "open_ok": True,
            "open_summary": "Opened Music",
            "playback_ok": True,
            "control": "play",
            "player_state": "playing",
            "track": "超时空辉夜姬",
            "artist": "Yachiyo",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls == [("open", "Music"), ("control", "play")]


def test_apple_music_open_and_play_reports_media_key_fallback(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: {
            "ok": True,
            "action": "app.open",
            "summary": "Opened Music",
            "data": {"app_name": app_name},
        },
    )
    monkeypatch.setattr(
        desktop_mod,
        "apple_music_control",
        lambda action: {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": "Apple Music play attempted via media key fallback",
            "data": {
                "control": action,
                "player_state": "unknown",
                "track": "",
                "artist": "",
                "fallback": "system_media_key",
                "fallback_control": "toggle",
                "media_key": "Play/Pause",
                "playback_state_unverified": True,
            },
            "permission_error": False,
            "missing_permissions": ["music_app", "automation"],
            "permission_targets": ["music_app", "automation"],
            "recovery_hints": ["Grant Automation permission."],
            "recovery_actions": [
                {
                    "label": "打开自动化权限",
                    "tool": "app.open",
                    "input": {"app_name": "自动化权限"},
                    "permission_target": "automation",
                    "risk_level": "low",
                }
            ],
            "fallback_used": True,
            "fallback": "system_media_key",
            "fallback_result": {"media_key": {"ok": True}},
        },
    )

    result = desktop_mod.apple_music_open_and_play()

    assert result["ok"] is True
    assert result["summary"] == "Opened Music and attempted playback with media key fallback"
    assert result["data"] == {
        "app_name": "Music",
        "open_ok": True,
        "open_summary": "Opened Music",
        "playback_ok": True,
        "control": "play",
        "player_state": "unknown",
        "track": "",
        "artist": "",
        "fallback": "system_media_key",
        "fallback_control": "toggle",
        "media_key": "Play/Pause",
        "playback_state_unverified": True,
    }
    assert result["permission_error"] is False
    assert result["permission_targets"] == ["music_app", "automation"]
    assert result["recovery_actions"][0]["permission_target"] == "automation"
    assert result["fallback_used"] is True
    assert result["fallback"] == "system_media_key"


def test_system_volume_executes_low_risk_volume_action(monkeypatch) -> None:
    calls = []

    def fake_osascript(script, args=None):
        calls.append((script, args))
        if not args:
            return {"ok": True, "stdout": "40|false", "stderr": ""}
        return {"ok": True, "stdout": "50|false", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)

    result = desktop_mod.system_volume("up")

    assert result == {
        "ok": True,
        "action": "system.volume",
        "summary": "System volume increased from 40% to 50%",
        "data": {
            "requested_action": "up",
            "old_level": 40,
            "old_muted": False,
            "level": 50,
            "muted": False,
            "changed": True,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls[0][1] is None
    assert calls[1][1] == ["50", "false"]


def test_clipboard_write_uses_system_clipboard_without_echoing_text(monkeypatch) -> None:
    calls = []

    def fake_run(command, *, input=None, text=None, capture_output=None, timeout=None, check=None):
        calls.append(
            {
                "command": command,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "timeout": timeout,
                "check": check,
            }
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.clipboard_write("hello world")

    assert result == {
        "ok": True,
        "action": "clipboard.write",
        "summary": "Copied 11 characters to clipboard",
        "data": {
            "text_length": 11,
            "platform": "macos",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls == [
        {
            "command": ["pbcopy"],
            "input": "hello world",
            "text": True,
            "capture_output": True,
            "timeout": 3,
            "check": False,
        }
    ]
    assert "hello world" not in result["summary"]
    assert "hello world" not in str(result["data"])


def test_clipboard_read_uses_system_clipboard_with_bounded_preview(monkeypatch) -> None:
    calls = []

    def fake_run(command, *, capture_output=None, text=None, timeout=None, check=None):
        calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "check": check,
            }
        )
        return subprocess.CompletedProcess(command, 0, "hello world", "")

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod.subprocess, "run", fake_run)

    result = desktop_mod.clipboard_read(max_chars=5)

    assert result == {
        "ok": True,
        "action": "clipboard.read",
        "summary": "Read 11 characters from clipboard",
        "data": {
            "text": "hello",
            "text_length": 11,
            "truncated": True,
            "max_chars": 5,
            "platform": "macos",
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls == [
        {
            "command": ["pbpaste"],
            "capture_output": True,
            "text": True,
            "timeout": 5,
            "check": False,
        }
    ]


def test_clipboard_read_rejects_invalid_preview_limit(monkeypatch) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")

    result = desktop_mod.clipboard_read(max_chars=True)

    assert result["ok"] is False
    assert result["action"] == "clipboard.read"
    assert "max_chars must be an integer" in result["error"]


def test_apple_music_control_permission_failure_returns_music_and_automation_targets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "_run_osascript",
        lambda _script, _args=None: {
            "ok": False,
            "action": "osascript",
            "summary": "osascript failed",
            "error": "Not authorized to send Apple events to Music.",
            "permission_error": True,
            "fallback_used": False,
        },
    )
    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )

    result = desktop_mod.apple_music_control("next")

    assert result["ok"] is False
    assert result["action"] == "media.apple_music_control"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["music_app", "automation"]
    assert result["permission_targets"] == ["music_app", "automation"]
    assert result["fallback_used"] is True


def test_apple_music_control_uses_media_key_fallback_when_automation_fails(
    monkeypatch,
) -> None:
    calls = []

    def fake_osascript(_script, args=None):
        calls.append(args)
        if len(calls) == 1:
            return {
                "ok": True,
                "stdout": "error|-1743|Not authorized to send Apple events to Music.",
                "stderr": "",
            }
        return {"ok": True, "stdout": "pressed|toggle", "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)
    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )

    result = desktop_mod.apple_music_control("play")

    assert result["ok"] is True
    assert result["action"] == "media.apple_music_control"
    assert result["summary"] == "Apple Music play attempted via media key fallback"
    assert result["data"] == {
        "control": "play",
        "player_state": "unknown",
        "track": "",
        "artist": "",
        "fallback": "system_media_key",
        "fallback_control": "toggle",
        "media_key": "Play/Pause",
        "playback_state_unverified": True,
        "direct_error": "Not authorized to send Apple events to Music.",
    }
    assert result["permission_error"] is False
    assert result["missing_permissions"] == ["music_app", "automation"]
    assert result["permission_targets"] == ["music_app", "automation"]
    assert result["fallback_used"] is True
    assert result["fallback"] == "system_media_key"
    assert result["fallback_result"]["media_key"] == {
        "ok": True,
        "action": "media.apple_music.media_key",
        "summary": "Pressed Play/Pause media key for Apple Music",
        "data": {
            "requested_control": "play",
            "media_control": "toggle",
            "media_key": "Play/Pause",
            "key_code": 100,
        },
        "permission_error": False,
        "fallback_used": False,
    }
    assert calls == [["play"], ["100", "toggle"]]


def test_apple_music_open_and_play_permission_failure_returns_music_and_automation_targets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(
        desktop_mod,
        "app_open",
        lambda app_name: {"ok": True, "action": "app.open", "data": {"app_name": app_name}},
    )
    monkeypatch.setattr(
        desktop_mod,
        "apple_music_control",
        lambda action: {
            "ok": False,
            "action": "media.apple_music_control",
            "summary": "media.apple_music_control failed",
            "error": "Not authorized to send Apple events to Music.",
            "data": {"control": action},
            "permission_error": True,
            "fallback_used": True,
        },
    )

    result = desktop_mod.apple_music_open_and_play()

    assert result["ok"] is False
    assert result["action"] == "media.apple_music_open_and_play"
    assert result["permission_error"] is True
    assert result["missing_permissions"] == ["music_app", "automation"]
    assert result["permission_targets"] == ["music_app", "automation"]
    assert result["fallback_used"] is True
