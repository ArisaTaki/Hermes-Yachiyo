"""Tests for ToolBroker factory setup split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.tool_brokers import RuntimeToolBrokerFactory
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBroker:
    def __init__(self, workspace_policy: dict[str, Any], artifact_root: Path, **kwargs: Any) -> None:
        self.workspace_policy = workspace_policy
        self.artifact_root = artifact_root
        self.kwargs = kwargs


def test_runtime_tool_broker_factory_builds_run_scoped_broker(tmp_path) -> None:
    memory_calls: list[dict[str, Any]] = []
    future_calls: list[dict[str, Any]] = []
    workspace_policy = {"default_workdir": str(tmp_path)}
    skills = [{"skill_id": "skill-1"}]
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: memory_calls.append(kwargs) or {"memory": kwargs},
        future_task_store=lambda **kwargs: future_calls.append(kwargs) or {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    broker = factory.for_run(
        run_id=" run-1 ",
        workspace_policy=workspace_policy,
        default_runnable_id="agent-1",
        skills=skills,
    )

    assert isinstance(broker, FakeBroker)
    assert broker.workspace_policy is workspace_policy
    assert broker.artifact_root == tmp_path / "artifacts" / "run-1"
    assert broker.kwargs["skills"] is skills
    assert broker.kwargs["memory_store"] == {"memory": {"source_run_id": "run-1"}}
    assert broker.kwargs["future_task_store"] == {
        "future": {"source_run_id": "run-1", "default_runnable_id": "agent-1"}
    }
    assert memory_calls == [{"source_run_id": "run-1"}]
    assert future_calls == [{"source_run_id": "run-1", "default_runnable_id": "agent-1"}]


def test_runtime_tool_broker_factory_uses_main_chat_default_runnable(tmp_path) -> None:
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    broker = factory.for_main_chat(run_id="run-chat", workspace_policy={})

    assert broker.kwargs["future_task_store"] == {
        "future": {
            "source_run_id": "run-chat",
            "default_runnable_id": "builtin:yachiyo-main",
        }
    }


def test_native_runtime_installs_tool_broker_factory(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolBrokerFactory is RuntimeToolBrokerFactory
        assert isinstance(service.tool_brokers, RuntimeToolBrokerFactory)

        broker = service.tool_brokers.for_main_chat(
            run_id="run-chat",
            workspace_policy={
                "default_workdir": str(tmp_path),
                "readable_scopes": ["."],
                "writable_scopes": [],
            },
        )

        assert isinstance(broker, ToolBroker)
        assert broker.artifact_root == service.agent_artifacts_dir / "run-chat"
        assert broker.memory_store.source_run_id == "run-chat"
        assert broker.future_task_store.default_runnable_id == "builtin:yachiyo-main"
    finally:
        service.close()
