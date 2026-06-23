"""Tests for the split ToolBroker dispatch registry."""

from __future__ import annotations

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
        "app_show",
        "app_hide",
        "app_minimize",
        "app_quit",
        "desktop_reveal_path",
        "desktop_open_path",
        "media_apple_music_play",
        "media_apple_music_control",
        "system_volume",
        "clipboard_write",
        "desktop_safe_shortcut",
        "desktop_safe_type_text",
        "desktop_safe_click",
        "desktop_hide_app",
        "desktop_minimize_window",
        "desktop_close_window",
        "desktop_hotkey",
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


def test_app_hide_schema_requires_app_name() -> None:
    ToolDescriptorRegistry.validate_payload("app.hide", {"app_name": "Slack"})

    with pytest.raises(AgentRuntimeError, match="app.hide 参数 app_name 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("app.hide", {"app_name": ""})


def test_desktop_safe_shortcut_schema_accepts_only_whitelisted_actions() -> None:
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "copy"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "new_tab"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "browser_back"})
    ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "browser_forward"})

    with pytest.raises(AgentRuntimeError, match="desktop.safe_shortcut 参数 action 必须是"):
        ToolDescriptorRegistry.validate_payload("desktop.safe_shortcut", {"action": "close_tab"})


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
                "app.quit",
                "desktop.close_window",
                "desktop.click",
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
        "app.quit",
        "desktop.close_window",
        "desktop.click",
        "desktop.type_text",
        "terminal.run",
    ]
    assert policy["approval_required"] == {
        "app.quit": True,
        "desktop.close_window": True,
        "desktop.click": True,
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
        "browser.click",
        {"selector": "#submit", "fallback_x": 12, "fallback_y": 34.5, "click_count": 2},
    )

    with pytest.raises(AgentRuntimeError, match="browser.click 参数 fallback_x 必须是非负坐标数字"):
        ToolDescriptorRegistry.validate_payload(
            "browser.click",
            {"selector": "#submit", "fallback_x": -1, "fallback_y": 34},
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
        "desktop_safe_shortcut",
        lambda action: calls.append(("safe_shortcut", action)) or {"ok": True},
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
        "desktop_hotkey",
        lambda key, *, modifiers=None: calls.append(("hotkey", key, modifiers))
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
        "desktop.safe_shortcut",
        {"action": "copy"},
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
        "desktop.hotkey",
        {"key": "l", "modifiers": ["command"]},
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
        "app.status",
        {"app_name": "Google Chrome"},
    ) == {"ok": True, "app_name": "Google Chrome"}
    assert calls == [
        ("music", "超时空辉夜姬"),
        ("music_control", "pause"),
        ("safe_shortcut", "copy"),
        ("safe_type_text", "hello"),
        ("safe_click", 12, 34),
        ("hotkey", "l", ["command"]),
        ("click", 12, 34, 2),
        ("hide_app",),
        ("focus_window", "Slack", "general"),
        ("show_named_app", "Slack"),
        ("hide_named_app", "Slack"),
        ("minimize_named_app", "Slack"),
        ("minimize_window",),
        ("close_window",),
        ("reveal", "~/Downloads/report.pdf"),
        ("permissions",),
        ("running",),
        ("windows", "Google Chrome"),
        ("status", "Google Chrome"),
    ]


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
        "browser_click",
        lambda selector, *, fallback_x=None, fallback_y=None, click_count=1: calls.append(
            ("click", selector, fallback_x, fallback_y, click_count)
        )
        or {"ok": True},
    )
    monkeypatch.setattr(
        broker,
        "browser_type_text",
        lambda selector, text: calls.append(("type", selector, text)) or {"ok": True},
    )

    assert dispatch_tool_call(
        broker,
        "browser.open_url",
        {"url": "https://example.com"},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.click",
        {"selector": "#go", "fallback_x": 12, "fallback_y": 34, "click_count": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "browser.type_text",
        {"selector": "#q", "text": "八千代"},
    ) == {"ok": True}
    assert calls == [
        ("open", "https://example.com"),
        ("click", "#go", 12, 34, 2),
        ("type", "#q", "八千代"),
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
        "media.apple_music_play",
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
