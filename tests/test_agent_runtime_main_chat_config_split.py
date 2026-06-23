"""Tests for main chat runtime config split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.main_chat_config import (
    MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS,
    MainChatRuntimeConfigBuilder,
    MainChatVirtualAgentProjector,
)
from apps.shell.agent.tools.policy import (
    DAILY_DESKTOP_TOOL_NAMES,
    FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    MEMORY_TOOL_NAMES,
    RuntimePolicyCompiler,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_main_chat_config_builder_projects_daily_entrypoint_runtime(tmp_path) -> None:
    compiler = RuntimePolicyCompiler()
    trusted: list[tuple[dict[str, Any], str, bool]] = []
    projects_dir = tmp_path / "projects"

    builder = MainChatRuntimeConfigBuilder(
        main_chat_agent_id="builtin:yachiyo-main",
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        workspace_status=lambda: {"initialized": True, "dirs": {"projects": str(projects_dir)}},
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        trust_workspace_from_policy=lambda policy, *, source, commit: trusted.append(
            (policy, source, commit)
        ),
        memory_tool_names=sorted(MEMORY_TOOL_NAMES),
        future_task_tool_names=sorted(FUTURE_TASK_TOOL_NAMES),
        desktop_tool_names=sorted(DAILY_DESKTOP_TOOL_NAMES),
    )

    config = builder.agent_config(model_profile_id=" profile-chat ")

    assert config["agent_id"] == "builtin:yachiyo-main"
    assert config["instructions"] == MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS
    assert "桌面执行型 Agent" in config["instructions"]
    assert "优先调用工具尝试执行" in config["instructions"]
    assert "media.apple_music_play" in config["instructions"]
    assert "media.apple_music_open_and_play" in config["instructions"]
    assert "media.apple_music_control" in config["instructions"]
    assert "screen.capture" in config["instructions"]
    assert "desktop.permissions" in config["instructions"]
    assert "desktop.active_window" in config["instructions"]
    assert "desktop.running_apps" in config["instructions"]
    assert "desktop.windows" in config["instructions"]
    assert "app.status" in config["instructions"]
    assert "app.open_and_safe_type_text" in config["instructions"]
    assert "app.focus_and_safe_type_text" in config["instructions"]
    assert "app.open_and_safe_shortcut" in config["instructions"]
    assert "app.focus_and_safe_shortcut" in config["instructions"]
    assert "desktop.reveal_path" in config["instructions"]
    assert "browser.open_url" in config["instructions"]
    assert "browser.open_url_and_extract_text" in config["instructions"]
    assert "browser.open_url_and_screenshot" in config["instructions"]
    assert "常见网站名或搜索查询" in config["instructions"]
    assert "desktop.click" in config["instructions"]
    assert "低风险桌面动作默认直接执行" in config["instructions"]
    assert "Runtime 生成审批卡" in config["instructions"]
    assert "权限缺失" in config["instructions"]
    assert "approval/policy gate" in config["instructions"]
    assert config["model_profile_id"] == "profile-chat"
    assert config["output_contract"] == "chat"
    assert config["workspace_policy"] == {
        "default_workdir": str(projects_dir),
        "readable_scopes": ["."],
        "writable_scopes": [],
    }
    assert projects_dir.exists()
    assert trusted == [(config["workspace_policy"], "main_chat", True)]
    assert "workspace.read" in config["tool_policy"]["allowed_tools"]
    assert "artifact.write" in config["tool_policy"]["allowed_tools"]
    allowed_tools = set(config["tool_policy"]["allowed_tools"])
    assert set(DAILY_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEMORY_TOOL_NAMES).issubset(allowed_tools)
    assert set(FUTURE_TASK_TOOL_NAMES).issubset(allowed_tools)
    assert not (allowed_tools & set(HIGH_RISK_AGENT_TOOLS))
    assert config["tool_policy"]["approval_required"] == {
        tool: True
        for tool in (*MEDIUM_RISK_DESKTOP_TOOL_NAMES, *MEDIUM_RISK_BROWSER_TOOL_NAMES)
    }


def test_main_chat_config_builder_overlays_daily_desktop_tools_on_explicit_policy(tmp_path) -> None:
    compiler = RuntimePolicyCompiler()
    builder = MainChatRuntimeConfigBuilder(
        main_chat_agent_id="builtin:yachiyo-main",
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        workspace_status=lambda: {},
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        trust_workspace_from_policy=lambda *_args, **_kwargs: None,
        memory_tool_names=sorted(MEMORY_TOOL_NAMES),
        future_task_tool_names=sorted(FUTURE_TASK_TOOL_NAMES),
        desktop_tool_names=sorted(DAILY_DESKTOP_TOOL_NAMES),
    )

    policy = builder.tool_policy(
        {
            "allowed_tools": ["workspace.read", "terminal.run"],
            "approval_required": {"terminal.run": True},
        }
    )

    allowed_tools = set(policy["allowed_tools"])
    assert set(DAILY_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEMORY_TOOL_NAMES).issubset(allowed_tools)
    assert set(FUTURE_TASK_TOOL_NAMES).issubset(allowed_tools)
    assert {"workspace.list", "workspace.read", "artifact.write", "terminal.run"}.issubset(
        allowed_tools
    )
    assert policy["approval_required"]["terminal.run"] is True
    for tool in (*MEDIUM_RISK_DESKTOP_TOOL_NAMES, *MEDIUM_RISK_BROWSER_TOOL_NAMES):
        assert policy["approval_required"][tool] is True


def test_main_chat_config_builder_projects_virtual_agent_without_trusting_workspace(tmp_path) -> None:
    compiler = RuntimePolicyCompiler()
    trusted: list[tuple[dict[str, Any], str, bool]] = []
    builder = MainChatRuntimeConfigBuilder(
        main_chat_agent_id="builtin:yachiyo-main",
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        workspace_status=lambda: {},
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        trust_workspace_from_policy=lambda policy, *, source, commit: trusted.append(
            (policy, source, commit)
        ),
        memory_tool_names=sorted(MEMORY_TOOL_NAMES),
        future_task_tool_names=sorted(FUTURE_TASK_TOOL_NAMES),
    )

    agent = builder.virtual_agent(default_profile_id="profile-chat")

    assert agent["virtual"] is True
    assert agent["system"] is True
    assert agent["builtin"] is True
    assert agent["instructions"] == MAIN_CHAT_DESKTOP_AGENT_INSTRUCTIONS
    assert agent["model_config"]["api_key_configured"] is True
    assert agent["workspace_policy"]["default_workdir"] == str(
        tmp_path / "agent-workspaces" / "builtin-yachiyo-main"
    )
    assert trusted == []


def test_main_chat_virtual_agent_projector_reads_default_profile_id(tmp_path) -> None:
    compiler = RuntimePolicyCompiler()
    builder = MainChatRuntimeConfigBuilder(
        main_chat_agent_id="builtin:yachiyo-main",
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        workspace_status=lambda: {},
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        trust_workspace_from_policy=lambda *_args, **_kwargs: None,
        memory_tool_names=sorted(MEMORY_TOOL_NAMES),
        future_task_tool_names=sorted(FUTURE_TASK_TOOL_NAMES),
    )
    projector = MainChatVirtualAgentProjector(
        main_chat_config=builder,
        default_profile_id=lambda: "profile-chat",
    )

    agent = projector.virtual_agent()

    assert agent["agent_id"] == "builtin:yachiyo-main"
    assert agent["model_profile_id"] == "profile-chat"
    assert agent["model_config"]["api_key_configured"] is True


def test_main_chat_virtual_agent_projector_tolerates_default_profile_failure(tmp_path) -> None:
    compiler = RuntimePolicyCompiler()
    builder = MainChatRuntimeConfigBuilder(
        main_chat_agent_id="builtin:yachiyo-main",
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        workspace_status=lambda: {},
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        trust_workspace_from_policy=lambda *_args, **_kwargs: None,
        memory_tool_names=sorted(MEMORY_TOOL_NAMES),
        future_task_tool_names=sorted(FUTURE_TASK_TOOL_NAMES),
    )

    def fail_default_profile_id() -> str:
        raise RuntimeError("profile service unavailable")

    projector = MainChatVirtualAgentProjector(
        main_chat_config=builder,
        default_profile_id=fail_default_profile_id,
    )

    agent = projector.virtual_agent()

    assert agent["model_profile_id"] == ""
    assert agent["model_config"]["api_key_configured"] is False


def test_native_runtime_installs_main_chat_config_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.MainChatRuntimeConfigBuilder is MainChatRuntimeConfigBuilder
        assert agent_runtime.MainChatVirtualAgentProjector is MainChatVirtualAgentProjector
        assert isinstance(service.main_chat_config, MainChatRuntimeConfigBuilder)
        assert isinstance(service.main_chat_virtual_agent_projector, MainChatVirtualAgentProjector)

        config = service._main_chat_agent_config(
            model_profile_id="profile-chat",
            workspace_policy={
                "default_workdir": str(tmp_path / "daily"),
                "readable_scopes": ".",
                "writable_scopes": [],
            },
        )

        assert config["agent_id"] == "builtin:yachiyo-main"
        assert config["workspace_policy"]["readable_scopes"] == ["."]
        assert config["tool_policy"] == service._main_chat_tool_policy()
    finally:
        service.close()
