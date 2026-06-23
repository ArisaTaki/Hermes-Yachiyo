"""Tests for the split ToolBroker dispatch registry."""

from __future__ import annotations

import subprocess

import pytest

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
        "desktop_active_window",
        "desktop_running_apps",
        "app_open",
        "app_focus",
        "desktop_reveal_path",
        "media_apple_music_play",
        "media_apple_music_control",
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


def test_desktop_reveal_path_schema_accepts_local_path() -> None:
    ToolDescriptorRegistry.validate_payload(
        "desktop.reveal_path",
        {"path": "~/Downloads/report.pdf"},
    )

    with pytest.raises(AgentRuntimeError, match="desktop.reveal_path 参数 path 必须是非空字符串"):
        ToolDescriptorRegistry.validate_payload("desktop.reveal_path", {"path": ""})


def test_compile_tool_policy_accepts_desktop_tools_with_foreground_approval() -> None:
    compiler = RuntimePolicyCompiler()

    policy = compiler.compile_tool_policy(
        "custom",
        {"allowed_tools": ["screen.capture", "desktop.click", "desktop.type_text", "terminal.run"]},
    )

    assert policy["allowed_tools"] == [
        "screen.capture",
        "desktop.click",
        "desktop.type_text",
        "terminal.run",
    ]
    assert policy["approval_required"] == {
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
        "desktop_reveal_path",
        lambda path: calls.append(("reveal", path)) or {"ok": True, "path": path},
    )
    monkeypatch.setattr(
        broker,
        "desktop_running_apps",
        lambda: calls.append(("running",)) or {"ok": True, "apps": ["Finder"]},
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
        "desktop.hotkey",
        {"key": "l", "modifiers": ["command"]},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.click",
        {"x": 12, "y": 34, "click_count": 2},
    ) == {"ok": True}
    assert dispatch_tool_call(
        broker,
        "desktop.reveal_path",
        {"path": "~/Downloads/report.pdf"},
    ) == {"ok": True, "path": "~/Downloads/report.pdf"}
    assert dispatch_tool_call(broker, "desktop.running_apps", {}) == {
        "ok": True,
        "apps": ["Finder"],
    }
    assert calls == [
        ("music", "超时空辉夜姬"),
        ("music_control", "pause"),
        ("hotkey", "l", ["command"]),
        ("click", 12, 34, 2),
        ("reveal", "~/Downloads/report.pdf"),
        ("running",),
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
    assert result["fallback_used"] is True


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
