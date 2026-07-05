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
    HIGH_RISK_DESKTOP_TOOL_NAMES,
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
    assert "TaskIntent" in config["instructions"]
    assert "discover -> act -> verify" in config["instructions"]
    assert "choose capabilities before app-specific rules" in config["instructions"]
    assert "Daily entrypoint operating manual" in config["instructions"]
    assert "intent to capabilities before choosing concrete tools" in config["instructions"]
    assert "Treat mounted Skills as execution manuals" in config["instructions"]
    assert "planner decisions, tool attempts, approvals, artifacts, failures" in config["instructions"]
    assert "Do not start tool-capable requests with claims" in config["instructions"]
    assert "Siri, Shortcuts, browser-only fallbacks, or manual user steps" in config["instructions"]
    assert (
        "until the allowed runtime tools have been attempted or the missing capability/permission has been observed"
        in config["instructions"]
    )
    assert "approval cards and pause/resume execution" in config["instructions"]
    assert "After a failed tool result, read the error and hint" in config["instructions"]
    assert "do not retry the same unchanged failing request" in config["instructions"]
    assert "legacy tool mapping in the Chat prompt is compatibility reference only" in config["instructions"]
    assert "不是封闭能力表" in config["instructions"]
    assert "常见意图映射" not in config["instructions"]
    assert "旧兼容映射不是封闭能力表" in config["instructions"]
    assert "能力类别包括" in config["instructions"]
    assert "not as fixed branches that must be prewritten" in config["instructions"]
    assert "Do not answer with recipes like 'you can open the app yourself'" in config["instructions"]
    assert "attempt the corresponding capability path before offering external assistants" in config[
        "instructions"
    ]
    assert "discover available applications/windows/UI first" in config["instructions"]
    assert (
        "prefer data.analyze for straightforward CSV/TSV/JSON/JSONL/XLSX/text-table reports, "
        "CSV summaries, HTML reports, and simple chart artifacts"
        in config["instructions"]
    )
    assert "For code tasks, inspect the workspace before code or shell execution" in config["instructions"]
    assert "only when the plan contains a concrete command" in config["instructions"]
    assert "python.run" in config["instructions"]
    assert "select the relevant capability path rather than desktop app launch as the default" in config[
        "instructions"
    ]
    assert "media.apple_music_play" in config["instructions"]
    assert "media.apple_music_open_and_play" in config["instructions"]
    assert "media.apple_music_control" in config["instructions"]
    assert "媒体播放也按可发现桌面应用处理" in config["instructions"]
    assert "media.apple_music_* 只是兼容 fallback，不是默认规划模型" in config["instructions"]
    assert "screen.capture" in config["instructions"]
    assert "desktop.permissions" in config["instructions"]
    assert "desktop.active_window" in config["instructions"]
    assert "desktop.list_apps" in config["instructions"]
    assert "未知应用名、不确定窗口或需要 UI 上下文时" in config["instructions"]
    assert "优先使用 app.open_and_* / app.focus_and_* 这类 app-scoped 工具" in config[
        "instructions"
    ]
    assert "只用于用户明确要求操作当前前台，或 app-scoped 工具不可用时的兼容 fallback" in config[
        "instructions"
    ]
    assert "desktop.running_apps" in config["instructions"]
    assert "desktop.windows" in config["instructions"]
    assert "app.status" in config["instructions"]
    assert "notes.create" in config["instructions"]
    assert "app.open_and_safe_type_text" in config["instructions"]
    assert "app.focus_and_safe_type_text" in config["instructions"]
    assert "app.open_and_safe_shortcut" in config["instructions"]
    assert "app.focus_and_safe_shortcut" in config["instructions"]
    assert "Shift+Tab" in config["instructions"]
    assert "desktop.reveal_path" in config["instructions"]
    assert "browser.open_url" in config["instructions"]
    assert "browser.open_url_and_extract_text" in config["instructions"]
    assert "browser.open_url_and_screenshot" in config["instructions"]
    assert "desktop.submit_foreground" in config["instructions"]
    assert "网页、搜索查询或 URL" in config["instructions"]
    assert "desktop.click_ui_element" in config["instructions"]
    assert "低风险桌面动作默认直接执行" in config["instructions"]
    assert "多个明确低风险桌面动作" in config["instructions"]
    assert "Runtime 生成审批卡" in config["instructions"]
    assert "terminal.run" in config["instructions"]
    assert "权限缺失" in config["instructions"]
    assert "approval/policy gate" in config["instructions"]
    assert "data.analyze" in config["instructions"]
    assert "workspace.write_patch" in config["instructions"]
    assert "file.organize" in config["instructions"]
    assert config["model_profile_id"] == "profile-chat"
    assert config["output_contract"] == "chat"
    assert config["workspace_policy"] == {
        "default_workdir": str(projects_dir),
        "readable_scopes": ["."],
        "writable_scopes": ["."],
    }
    assert projects_dir.exists()
    assert trusted == [(config["workspace_policy"], "main_chat", True)]
    assert "workspace.read" in config["tool_policy"]["allowed_tools"]
    assert "data.analyze" in config["tool_policy"]["allowed_tools"]
    assert "workspace.write_patch" in config["tool_policy"]["allowed_tools"]
    assert "file.organize" in config["tool_policy"]["allowed_tools"]
    assert "python.run" in config["tool_policy"]["allowed_tools"]
    assert "artifact.write" in config["tool_policy"]["allowed_tools"]
    allowed_tools = set(config["tool_policy"]["allowed_tools"])
    assert set(DAILY_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(MEMORY_TOOL_NAMES).issubset(allowed_tools)
    assert set(FUTURE_TASK_TOOL_NAMES).issubset(allowed_tools)
    assert allowed_tools & set(HIGH_RISK_AGENT_TOOLS) == {
        "file.organize",
        "python.run",
        "terminal.run",
        "workspace.write_patch",
    }
    assert config["tool_policy"]["approval_required"] == {
        tool: True
        for tool in (
            "file.organize",
            "python.run",
            "terminal.run",
            "workspace.write_patch",
            *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
            *HIGH_RISK_DESKTOP_TOOL_NAMES,
            *MEDIUM_RISK_BROWSER_TOOL_NAMES,
        )
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
    assert {
        "workspace.list",
        "workspace.read",
        "data.analyze",
        "workspace.write_patch",
        "file.organize",
        "artifact.write",
        "terminal.run",
        "python.run",
    }.issubset(allowed_tools)
    assert policy["approval_required"]["file.organize"] is True
    assert policy["approval_required"]["python.run"] is True
    assert policy["approval_required"]["terminal.run"] is True
    assert policy["approval_required"]["workspace.write_patch"] is True
    for tool in (
        *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
        *HIGH_RISK_DESKTOP_TOOL_NAMES,
        *MEDIUM_RISK_BROWSER_TOOL_NAMES,
    ):
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
    assert agent["workspace_policy"]["readable_scopes"] == ["."]
    assert agent["workspace_policy"]["writable_scopes"] == ["."]
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
        assert config["workspace_policy"]["writable_scopes"] == []
        assert config["tool_policy"] == service._main_chat_tool_policy()
    finally:
        service.close()
