"""Tests for Agent chat entrypoint runtime setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_chat_entrypoints import (
    RuntimeAgentChatEntrypointSetup,
    build_runtime_agent_chat_entrypoint_setup,
)
from apps.shell.agent.runtime.agent_runs import RuntimeAgentRunAsyncCoordinator
from apps.shell.agent.runtime.main_chat_config import (
    MainChatRuntimeConfigBuilder,
    MainChatVirtualAgentProjector,
)
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester
from apps.shell.agent.runtime.run_timeline import RuntimeRunTimelineService
from apps.shell.agent.runtime.tool_brokers import RuntimeToolBrokerFactory


class _FakeProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "profile-chat"}


def test_agent_chat_entrypoint_setup_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeAgentChatEntrypointSetup is RuntimeAgentChatEntrypointSetup
    assert (
        agent_runtime._build_runtime_agent_chat_entrypoint_setup
        is build_runtime_agent_chat_entrypoint_setup
    )


def test_build_runtime_agent_chat_entrypoint_setup_wires_collaborators(tmp_path: Path) -> None:
    setup = build_runtime_agent_chat_entrypoint_setup(
        get_agent_private=lambda agent_id: {"agent_id": agent_id},
        validate_agent_run_readiness=lambda _agent: None,
        agent_run_starter=object(),
        execute_agent_run=lambda *_args, **_kwargs: {"ok": True},
        project_agent_run_group_if_root=lambda result: result,
        resolve_runnable=lambda **_kwargs: None,
        update_run=lambda *_args, **_kwargs: {"ok": True},
        runtime_agent_timeline=object(),
        runtime_agent_run_events=object(),
        call_custom_api=lambda *_args, **_kwargs: "ok",
        runs=object(),
        run_groups=object(),
        runtime_events=object(),
        run_artifacts=object(),
        agent_workspaces_dir=tmp_path / "workspaces",
        agent_artifacts_dir=tmp_path / "artifacts",
        memory_store=object(),
        future_task_store=object(),
        insert_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        link_task_run=lambda **_kwargs: None,
        get_run=lambda run_id: {"run_id": run_id, "timeline": []},
        task_run_links=object(),
        runtime_task_events=object(),
        runtime_timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        compile_tool_policy=lambda _category, policy: dict(policy),
        compile_workspace_policy=lambda policy: dict(policy),
        trust_workspace_from_policy=lambda *_args, **_kwargs: None,
        profile_service_factory=_FakeProfileService,
        workspace_status=lambda: {"initialized": False, "dirs": {}},
    )

    assert isinstance(setup, RuntimeAgentChatEntrypointSetup)
    assert isinstance(setup.agent_run_async_coordinator, RuntimeAgentRunAsyncCoordinator)
    assert isinstance(setup.agent_model_tester, RuntimeAgentModelTester)
    assert isinstance(setup.run_timeline, RuntimeRunTimelineService)
    assert isinstance(setup.main_chat_config, MainChatRuntimeConfigBuilder)
    assert isinstance(setup.main_chat_virtual_agent_projector, MainChatVirtualAgentProjector)
    assert isinstance(setup.tool_brokers, RuntimeToolBrokerFactory)
    assert isinstance(setup.main_chat_runs, MainChatRunLifecycle)
    assert setup.main_chat_virtual_agent_projector.virtual_agent()["model_profile_id"] == "profile-chat"
