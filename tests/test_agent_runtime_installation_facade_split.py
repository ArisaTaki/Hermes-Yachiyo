"""Tests for runtime installation facade methods split out of the legacy runtime."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from apps.shell import agent_runtime
from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.engine_state import build_runtime_engine_state
from apps.shell.agent.runtime.installation_facade import RuntimeInstallationFacadeMixin
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
)
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationCoordinator
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_installation_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeInstallationFacadeMixin is RuntimeInstallationFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeInstallationFacadeMixin)
    for method_name in (
        "_install_runtime_model_adapters",
        "_install_runtime_foundation",
        "_install_runtime_definition_layer",
        "_install_runtime_run_layer",
        "_install_runtime_memory_and_core",
        "_install_runtime_agent_chat_entrypoints",
        "_install_runtime_engine_state",
        "_install_runtime_recorders",
        "_install_runtime_definition_services",
        "_install_runtime_run_services",
        "_install_runtime_memory_services",
        "_install_runtime_core_services",
        "_install_runtime_run_timeline",
        "_install_runtime_main_chat_config",
        "_install_runtime_tool_brokers",
        "_install_runtime_main_chat_runs",
        "_install_runtime_main_chat_model",
        "_install_runtime_main_chat_model_loop",
        "_install_runtime_tooling",
        "_install_runtime_custom_api_agent_loop",
        "_install_runtime_agent_services",
        "_install_runtime_approval_services",
        "_install_runtime_approval_transitions",
        "_install_runtime_tool_approval_resume",
        "_install_runtime_workflow_execution_services",
        "_install_runtime_workflow_planning_services",
        "_install_runtime_runnable_services",
        "_install_runtime_workflow_transition_services",
        "_install_runtime_run_cancellation",
        "_install_runtime_run_rerun",
        "_install_runtime_run_deletion",
        "_install_runtime_shutdown",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_installation_facade_installs_model_adapters(monkeypatch) -> None:
    calls: list[tuple[str, str, str, list[dict[str, str]]]] = []

    def fake_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        **_kwargs,
    ) -> dict[str, str]:
        calls.append((base_url, model, api_key, messages))
        return {"content": "patched"}

    monkeypatch.setattr(agent_runtime, "openai_compatible_chat_message", fake_chat)
    engine = object.__new__(agent_runtime.NativeRunEngine)

    engine._install_runtime_model_adapters()

    assert isinstance(engine.model_profile_chat_adapter, RuntimeModelProfileChatAdapter)
    assert isinstance(engine.openai_compatible_chat_adapter, RuntimeOpenAICompatibleChatAdapter)
    assert engine.model_profile_chat_adapter.call(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hi"}],
    ) == {"content": "patched"}
    assert calls == [
        (
            "https://api.example.test/v1",
            "demo-model",
            "sk-test",
            [{"role": "user", "content": "hi"}],
        )
    ]


def test_installation_facade_installs_engine_state_under_legacy_attributes(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    state = build_runtime_engine_state(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
    )
    engine = object.__new__(agent_runtime.NativeRunEngine)
    try:
        engine._install_runtime_engine_state(state)

        assert engine.workspace_dir == state.workspace_dir
        assert engine.db_path == state.db_path
        assert engine._credential_store is credential_store
        assert engine.skills_dir == state.skills_dir
        assert engine.agent_artifacts_dir == state.agent_artifacts_dir
        assert engine.workflow_artifacts_dir == state.workflow_artifacts_dir
        assert engine.runtime_limits is state.runtime_limits
        assert engine._conn is state.conn
        assert isinstance(engine.runtime_credentials, RuntimeCredentialService)
    finally:
        state.conn.close()
        credential_store.close()


def test_installation_facade_installs_cancellation_and_service_bundles() -> None:
    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._run_cancel_locks = {}
    engine._run_cancel_locks_guard = threading.RLock()
    run_cancellation = SimpleNamespace(cancel_once=lambda run_id: {"run_id": run_id})
    runnable_services = SimpleNamespace(
        future_task_scheduler="future",
        chat_runnable_parser="parser",
        runnable_catalog="catalog",
        runnable_run_coordinator="coordinator",
    )

    engine._install_runtime_run_cancellation(run_cancellation)
    engine._install_runtime_runnable_services(runnable_services)

    assert engine.run_cancellation is run_cancellation
    assert isinstance(engine.run_cancellation_coordinator, RuntimeRunCancellationCoordinator)
    assert engine.run_cancellation_coordinator._cancel_once is run_cancellation.cancel_once
    assert engine.future_task_scheduler == "future"
    assert engine.chat_runnable_parser == "parser"
    assert engine.runnable_catalog == "catalog"
    assert engine.runnable_run_coordinator == "coordinator"


def test_installation_facade_installs_agent_chat_entrypoints(monkeypatch) -> None:
    class CapturedCollaborator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    for name in (
        "RuntimeAgentRunAsyncCoordinator",
        "RuntimeAgentModelTester",
        "RuntimeRunTimelineService",
        "MainChatRuntimeConfigBuilder",
        "MainChatVirtualAgentProjector",
        "RuntimeToolBrokerFactory",
        "MainChatRunLifecycle",
    ):
        monkeypatch.setattr(agent_runtime, name, CapturedCollaborator)

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.agent_run_starter = "starter"
    engine.runtime_agent_timeline = "agent-timeline"
    engine.runtime_agent_run_events = "agent-run-events"
    engine.openai_compatible_chat_adapter = SimpleNamespace(call="custom-api-call")
    engine.runs = "runs"
    engine.run_groups = "run-groups"
    engine.runtime_events = "runtime-events"
    engine.run_artifacts = "run-artifacts"
    engine.agent_workspaces_dir = "agent-workspaces"
    engine.agent_artifacts_dir = "agent-artifacts"
    engine._memory_store = "memory-store"
    engine._future_task_store = "future-task-store"
    engine._insert_run = "insert-run"
    engine.link_task_run = "link-task-run"
    engine.get_run = "get-run"
    engine._update_run = "update-run"
    engine.task_run_links = "task-run-links"
    engine.runtime_task_events = "task-events"

    engine._install_runtime_agent_chat_entrypoints(
        runtime_timeline_factory="timeline-factory",
    )

    assert isinstance(engine.agent_run_async_coordinator, CapturedCollaborator)
    assert engine.agent_run_async_coordinator.kwargs["starter"] == "starter"
    assert isinstance(engine.agent_model_tester, CapturedCollaborator)
    assert engine.agent_model_tester.kwargs["call_custom_api"] == "custom-api-call"
    assert isinstance(engine.run_timeline, CapturedCollaborator)
    assert engine.run_timeline.kwargs["runs"] == "runs"
    assert isinstance(engine.main_chat_config, CapturedCollaborator)
    assert engine.main_chat_config.kwargs["agent_workspaces_dir"] == "agent-workspaces"
    assert isinstance(engine.main_chat_virtual_agent_projector, CapturedCollaborator)
    assert isinstance(engine.tool_brokers, CapturedCollaborator)
    assert engine.tool_brokers.kwargs["memory_store"] == "memory-store"
    assert isinstance(engine.main_chat_runs, CapturedCollaborator)
    assert engine.main_chat_runs.kwargs["timeline_factory"] == "timeline-factory"
