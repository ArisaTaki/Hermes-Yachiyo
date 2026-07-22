"""Tests for tool descriptor and policy gate code split out of agent_runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    HIGH_RISK_DESKTOP_TOOL_NAMES,
    KNOWN_AGENT_TOOLS,
    LOW_RISK_BROWSER_TOOL_NAMES,
    LOW_RISK_DESKTOP_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    MEMORY_KINDS,
    MEMORY_SCOPES,
    MEMORY_TOOL_NAMES,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES,
    PolicyGate,
    RuntimePolicyCompiler,
    ToolDescriptor,
    ToolDescriptorRegistry,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    planner_first_direct_tool_selection,
)


def test_tool_policy_classes_and_constants_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.ToolDescriptor is ToolDescriptor
    assert agent_runtime.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert agent_runtime.PolicyGate is PolicyGate
    assert agent_runtime.TOOL_DESCRIPTORS is TOOL_DESCRIPTORS
    assert agent_runtime._TOOL_FUNCTION_NAMES is TOOL_FUNCTION_NAMES
    assert agent_runtime._TOOL_NAME_ALIASES is TOOL_NAME_ALIASES
    assert agent_runtime._KNOWN_AGENT_TOOLS is KNOWN_AGENT_TOOLS
    assert agent_runtime._HIGH_RISK_AGENT_TOOLS is HIGH_RISK_AGENT_TOOLS
    assert agent_runtime._MEMORY_TOOL_NAMES is MEMORY_TOOL_NAMES
    assert agent_runtime._FUTURE_TASK_TOOL_NAMES is FUTURE_TASK_TOOL_NAMES
    assert agent_runtime._MEMORY_SCOPES is MEMORY_SCOPES
    assert agent_runtime._MEMORY_KINDS is MEMORY_KINDS
    assert agent_runtime.RuntimePolicyCompiler is RuntimePolicyCompiler
    assert agent_runtime.NativeRunEngine._default_tool_policy is RuntimePolicyCompiler.default_tool_policy
    assert agent_runtime.NativeRunEngine._default_workspace_policy is RuntimePolicyCompiler.default_workspace_policy


def test_model_tool_schema_uses_function_aliases_and_strict_parameters() -> None:
    schemas = ToolDescriptorRegistry.model_tool_schemas(
        ["workspace.read", "workspace.write_patch", "unknown.tool"]
    )

    function_names = [schema["function"]["name"] for schema in schemas]
    assert function_names == ["workspace_read", "workspace_write_patch"]
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["additionalProperties"] is False

    write_patch = schemas[1]["function"]["parameters"]
    assert write_patch["required"] == ["path"]
    assert set(write_patch["properties"]) == {
        "path",
        "patch",
        "expected_sha256",
        "base_sha256",
    }


def test_tool_payload_validation_rejects_unknown_and_undeclared_fields() -> None:
    with pytest.raises(AgentRuntimeError):
        ToolDescriptorRegistry.validate_payload("unknown.tool", {})

    with pytest.raises(AgentRuntimeError, match="undeclared|未声明"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.read",
            {"path": "README.md", "extra": "nope"},
        )


def test_app_open_schema_accepts_explicit_background_delivery_hint() -> None:
    ToolDescriptorRegistry.validate_payload(
        "app.open",
        {"app_name": "TextEdit", "bring_to_front": False},
    )

    schema = ToolDescriptorRegistry.model_tool_schemas(["app.open"])[0][
        "function"
    ]["parameters"]
    assert schema["properties"]["bring_to_front"]["type"] == "boolean"

    with pytest.raises(AgentRuntimeError, match="bring_to_front.*布尔"):
        ToolDescriptorRegistry.validate_payload(
            "app.open",
            {"app_name": "TextEdit", "bring_to_front": "false"},
        )


def test_music_app_control_tool_is_low_risk_and_validates_payload() -> None:
    assert "media.music_app_control" in LOW_RISK_DESKTOP_TOOL_NAMES
    assert TOOL_FUNCTION_NAMES["media.music_app_control"] == "media_music_app_control"

    ToolDescriptorRegistry.validate_payload(
        "media.music_app_control",
        {"app_name": "Spotify", "action": "pause"},
    )
    with pytest.raises(AgentRuntimeError, match="app_name"):
        ToolDescriptorRegistry.validate_payload(
            "media.music_app_control",
            {"action": "pause"},
        )
    with pytest.raises(AgentRuntimeError, match="action"):
        ToolDescriptorRegistry.validate_payload(
            "media.music_app_control",
            {"app_name": "Spotify", "action": "shuffle"},
        )


def test_system_media_control_tool_is_low_risk_and_validates_payload() -> None:
    assert "media.system_control" in LOW_RISK_DESKTOP_TOOL_NAMES
    assert TOOL_FUNCTION_NAMES["media.system_control"] == "media_system_control"

    ToolDescriptorRegistry.validate_payload("media.system_control", {"action": "pause"})
    with pytest.raises(AgentRuntimeError, match="action"):
        ToolDescriptorRegistry.validate_payload("media.system_control", {"action": "shuffle"})


def test_desktop_safe_shortcut_actions_are_low_risk_and_validated() -> None:
    assert "desktop.safe_shortcut" in LOW_RISK_DESKTOP_TOOL_NAMES

    ToolDescriptorRegistry.validate_payload(
        "desktop.safe_shortcut",
        {"action": "switch_previous_app"},
    )
    ToolDescriptorRegistry.validate_payload(
        "desktop.safe_shortcut",
        {"action": "switch_next_app"},
    )
    ToolDescriptorRegistry.validate_payload(
        "desktop.safe_shortcut",
        {"action": "hide_other_apps"},
    )
    ToolDescriptorRegistry.validate_payload(
        "desktop.safe_shortcut",
        {"action": "toggle_full_screen"},
    )
    with pytest.raises(AgentRuntimeError, match="action"):
        ToolDescriptorRegistry.validate_payload(
            "desktop.safe_shortcut",
            {"action": "switch_random_app"},
        )


def test_app_command_shortcut_actions_are_explicitly_validated() -> None:
    for action, app_name in (
        ("command_palette", "Visual Studio Code"),
        ("obsidian_command_palette", "Obsidian"),
        ("preferences", "Slack"),
    ):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_shortcut",
            {"app_name": app_name, "action": action},
        )
    with pytest.raises(AgentRuntimeError, match="action"):
        ToolDescriptorRegistry.validate_payload(
            "app.focus_and_safe_shortcut",
            {"app_name": "Visual Studio Code", "action": "arbitrary_palette"},
        )


def test_write_patch_payload_validation_requires_patch_and_matching_hash_aliases() -> None:
    with pytest.raises(AgentRuntimeError, match="patch"):
        ToolDescriptorRegistry.validate_payload("workspace.write_patch", {"path": "a.txt"})

    valid_hash = "a" * 64
    ToolDescriptorRegistry.validate_payload(
        "workspace.write_patch",
        {"path": "a.txt", "patch": "--- a\n+++ b\n", "expected_sha256": valid_hash},
    )

    with pytest.raises(AgentRuntimeError, match="64"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.write_patch",
            {"path": "a.txt", "patch": "--- a\n+++ b\n", "expected_sha256": "bad"},
        )

    with pytest.raises(AgentRuntimeError, match="expected_sha256"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.write_patch",
            {
                "path": "a.txt",
                "patch": "--- a\n+++ b\n",
                "expected_sha256": valid_hash,
                "base_sha256": "b" * 64,
            },
        )


def test_file_organize_tool_is_high_risk_and_validates_payload() -> None:
    assert "file.organize" in HIGH_RISK_AGENT_TOOLS
    assert TOOL_FUNCTION_NAMES["file.organize"] == "file_organize"

    ToolDescriptorRegistry.validate_payload(
        "file.organize",
        {
            "path": "Downloads",
            "operation": "organize",
            "file_type": "invoice",
            "destination": "Invoices",
            "conflict_strategy": "keep_both",
            "limit": 50,
        },
    )
    with pytest.raises(AgentRuntimeError, match="operation"):
        ToolDescriptorRegistry.validate_payload(
            "file.organize",
            {"path": "Downloads", "operation": "delete"},
        )
    with pytest.raises(AgentRuntimeError, match="conflict_strategy"):
        ToolDescriptorRegistry.validate_payload(
            "file.organize",
            {
                "path": "Downloads",
                "operation": "organize",
                "conflict_strategy": "overwrite",
            },
        )


def test_memory_payload_validation_rejects_invalid_scope_and_kind() -> None:
    with pytest.raises(AgentRuntimeError, match="scope"):
        ToolDescriptorRegistry.validate_payload(
            "memory.add",
            {"content": "remember this", "scope": "team"},
        )

    with pytest.raises(AgentRuntimeError, match="kind"):
        ToolDescriptorRegistry.validate_payload(
            "memory.add",
            {"content": "remember this", "kind": "credential"},
        )


def test_policy_gate_normalizes_allowed_tool_entries() -> None:
    assert PolicyGate.allows_tool("terminal.run", [" workspace.read ", "terminal.run"])
    assert not PolicyGate.allows_tool("terminal.run", ["workspace.read"])


def test_workspace_read_accepts_planner_source_kind_metadata() -> None:
    ToolDescriptorRegistry.validate_payload(
        "workspace.read",
        {"path": "inputs/sales.csv", "source_kind": "csv"},
    )


def test_default_daily_agent_policy_exposes_desktop_tools_with_medium_risk_approval() -> None:
    policy = RuntimePolicyCompiler.default_tool_policy("custom")
    allowed_tools = set(policy["allowed_tools"])

    assert set(LOW_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(LOW_RISK_BROWSER_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEDIUM_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(HIGH_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEDIUM_RISK_BROWSER_TOOL_NAMES).issubset(allowed_tools)
    assert {"workspace.list", "workspace.read", "data.analyze"}.issubset(
        allowed_tools
    )
    assert not (allowed_tools & set(HIGH_RISK_AGENT_TOOLS))
    assert policy["approval_required"] == {
        "app.quit": True,
        "app.open_and_click_ui_element": True,
        "app.focus_and_click_ui_element": True,
        "app.open_and_type_into_ui_element": True,
        "app.focus_and_type_into_ui_element": True,
        "app.open_and_hotkey": True,
        "app.focus_and_hotkey": True,
        "desktop.permissions.verify": True,
        "desktop.close_window": True,
        "desktop.quit_app": True,
        "desktop.hotkey": True,
        "desktop.submit_foreground": True,
        "desktop.shortcut": True,
        "desktop.type": True,
        "desktop.type_text": True,
        "desktop.click": True,
        "desktop.click_ui_element": True,
        "desktop.type_into_ui_element": True,
        "browser.click": True,
        "browser.type_text": True,
        "file.organize": True,
        "fs.move_file": True,
        "python.run": True,
        "terminal.run": True,
        "workspace.write_patch": True,
    }


def test_default_custom_policy_routes_data_analysis_without_terminal() -> None:
    policy = RuntimePolicyCompiler.default_tool_policy("custom")
    allowed_tools = policy["allowed_tools"]

    selection = planner_first_direct_tool_selection(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools,
        legacy_tool_requests=lambda _prompt, _allowed_tools: [],
    )

    assert "terminal.run" not in allowed_tools
    assert selection.selected_source == "runtime_planner"
    assert [request["tool"] for request in selection.requests] == ["data.analyze"]


def test_default_orchestrator_policy_keeps_workspace_and_low_risk_desktop_tools() -> None:
    policy = RuntimePolicyCompiler.default_tool_policy("orchestrator")
    allowed_tools = set(policy["allowed_tools"])

    assert {"workspace.list", "workspace.read"}.issubset(allowed_tools)
    assert set(LOW_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(LOW_RISK_BROWSER_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEDIUM_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(HIGH_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEDIUM_RISK_BROWSER_TOOL_NAMES).issubset(allowed_tools)
    assert allowed_tools & set(HIGH_RISK_AGENT_TOOLS) == {"file.organize"}
    assert policy["approval_required"]["file.organize"] is True


def test_runtime_policy_compiler_projects_tool_workspace_and_agent_runtime() -> None:
    compiler = RuntimePolicyCompiler()

    tool_policy = compiler.compile_tool_policy(
        "coding",
        {
            "allowed_tools": [
                " workspace.read ",
                "terminal.run",
                "terminal.run",
                "unknown.tool",
            ],
            "approval_required": {"workspace.write_patch": True, "memory.add": True},
        },
    )
    assert tool_policy == {
        "allowed_tools": ["workspace.read", "terminal.run"],
        "approval_required": {"terminal.run": True, "memory.add": True},
    }

    workspace_policy = compiler.compile_workspace_policy(
        {
            "default_workdir": " /tmp/project ",
            "readable_scopes": "., docs",
            "writable_scopes": ["", "src", None],
        }
    )
    assert workspace_policy == {
        "default_workdir": "/tmp/project",
        "readable_scopes": [".", "docs"],
        "writable_scopes": ["src"],
    }

    runtime = compiler.compile_agent_runtime(
        {
            "category": "research",
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "workspace_policy": {"readable_scopes": "notes"},
            "skill_ids": ["skill-1"],
        }
    )
    assert runtime["runtime"] == "oha_agent"
    assert runtime["tool_policy"]["allowed_tools"] == ["skill.read", "workspace.read"]
    assert runtime["workspace_policy"]["readable_scopes"] == ["notes"]
    assert runtime["progress_events"] == [
        "agent.run.started",
        "agent.runtime.compiled",
        "agent.model.response",
        "agent.tool.call",
        "agent.artifact.write",
        "agent.run.completed",
        "agent.run.failed",
    ]


def test_native_runtime_uses_split_runtime_policy_compiler(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_policy, RuntimePolicyCompiler)
        assert service._compile_tool_policy(
            "custom",
            {"allowed_tools": "workspace.read"},
        ) == {
            "allowed_tools": ["workspace.read"],
            "approval_required": {},
        }
    finally:
        service.close()


def test_tool_payload_validation_rejects_sensitive_values_before_persistence() -> None:
    with pytest.raises(AgentRuntimeError, match="sensitive|敏感"):
        ToolDescriptorRegistry.validate_payload(
            "artifact.write",
            {
                "path": "notes.md",
                "content": "OPENAI_API_KEY=sk-testsecret123456",
            },
        )
