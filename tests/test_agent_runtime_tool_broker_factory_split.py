"""Tests for ToolBroker factory setup split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.foreground_lock_scope import foreground_lock_broker_kwargs
from apps.shell.agent.runtime.tool_brokers import (
    RuntimeToolBrokerFactory,
    write_artifact_with_tool_broker,
)
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.foreground_lock import ForegroundActionLock
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBroker:
    def __init__(self, workspace_policy: dict[str, Any], artifact_root: Path, **kwargs: Any) -> None:
        self.workspace_policy = workspace_policy
        self.artifact_root = artifact_root
        self.kwargs = kwargs
        self.writes: list[tuple[str, str]] = []

    def artifact_write(self, artifact_path: str, content: str) -> dict[str, Any]:
        self.writes.append((artifact_path, content))
        return {"ok": True, "path": artifact_path, "bytes": len(content.encode("utf-8"))}


class FakeSharedToolBrokers:
    def __init__(self) -> None:
        self.broker = FakeBroker({}, Path("/tmp/artifacts"))
        self.calls: list[dict[str, Any]] = []

    def for_run(
        self,
        *,
        run_id: str,
        workspace_policy: dict[str, Any],
        artifacts_dir: Path | None = None,
        **kwargs: Any,
    ) -> FakeBroker:
        self.calls.append(
            {
                "run_id": run_id,
                "workspace_policy": workspace_policy,
                "artifacts_dir": artifacts_dir,
                **kwargs,
            }
        )
        return self.broker


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
        approvals={"desktop.type_text": True},
        default_runnable_id="agent-1",
        skills=skills,
    )

    assert isinstance(broker, FakeBroker)
    assert broker.workspace_policy is workspace_policy
    assert broker.artifact_root == tmp_path / "artifacts" / "run-1"
    assert broker.kwargs["approvals"] == {"desktop.type_text": True}
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

    broker = factory.for_main_chat(
        run_id="run-chat",
        workspace_policy={},
        approvals={"browser.click": True},
    )

    assert broker.kwargs["approvals"] == {"browser.click": True}
    assert broker.kwargs["future_task_store"] == {
        "future": {
            "source_run_id": "run-chat",
            "default_runnable_id": "builtin:yachiyo-main",
        }
    }


def test_runtime_tool_broker_factory_can_use_custom_artifacts_dir(tmp_path) -> None:
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "agent-artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    broker = factory.for_run(
        run_id="workflow-run-1",
        workspace_policy={},
        artifacts_dir=tmp_path / "workflow-artifacts",
    )

    assert broker.artifact_root == tmp_path / "workflow-artifacts" / "workflow-run-1"


def test_runtime_tool_broker_factory_can_share_group_foreground_lock(tmp_path) -> None:
    foreground_lock = ForegroundActionLock()
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    first_broker = factory.for_run(
        run_id="run-1",
        workspace_policy={},
        foreground_lock=foreground_lock,
        foreground_lock_owner="group-run-1:run-1",
    )
    second_broker = factory.for_run(
        run_id="run-2",
        workspace_policy={},
        foreground_lock=foreground_lock,
        foreground_lock_owner="group-run-1:run-2",
    )

    assert first_broker.kwargs["foreground_lock"] is foreground_lock
    assert first_broker.kwargs["foreground_lock_owner"] == "group-run-1:run-1"
    assert second_broker.kwargs["foreground_lock"] is foreground_lock
    assert second_broker.kwargs["foreground_lock_owner"] == "group-run-1:run-2"


def test_runtime_tool_broker_factory_reuses_foreground_lock_by_group_key(tmp_path) -> None:
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    first_broker = factory.for_run(
        run_id="run-1",
        workspace_policy={},
        foreground_lock_key="group-run-1",
    )
    second_broker = factory.for_run(
        run_id="run-2",
        workspace_policy={},
        foreground_lock_key="group-run-1",
    )
    third_broker = factory.for_run(
        run_id="run-3",
        workspace_policy={},
        foreground_lock_key="group-run-2",
    )

    assert first_broker.kwargs["foreground_lock"] is second_broker.kwargs["foreground_lock"]
    assert third_broker.kwargs["foreground_lock"] is not first_broker.kwargs["foreground_lock"]
    assert first_broker.kwargs["foreground_lock_owner"] == "group-run-1:run-1"
    assert second_broker.kwargs["foreground_lock_owner"] == "group-run-1:run-2"
    assert third_broker.kwargs["foreground_lock_owner"] == "group-run-2:run-3"


def test_foreground_lock_scope_prefers_group_then_workflow() -> None:
    assert foreground_lock_broker_kwargs(
        run_id="run-1",
        run_group_id="group-run-1",
        workflow_run_id="workflow-run-1",
    ) == {
        "foreground_lock_key": "group-run-1",
        "foreground_lock_owner": "group-run-1:run-1",
    }
    assert foreground_lock_broker_kwargs(
        run_id="child-run-1",
        workflow_run_id="workflow-run-1",
    ) == {
        "foreground_lock_key": "workflow:workflow-run-1",
        "foreground_lock_owner": "workflow:workflow-run-1:child-run-1",
    }
    assert foreground_lock_broker_kwargs(run_id="run-1") == {}


def test_runtime_tool_broker_factory_reuses_foreground_lock_by_workflow_key(tmp_path) -> None:
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    first_broker = factory.for_run(
        run_id="run-1",
        workspace_policy={},
        **foreground_lock_broker_kwargs(
            run_id="run-1",
            workflow_run_id="workflow-run-1",
        ),
    )
    second_broker = factory.for_run(
        run_id="run-2",
        workspace_policy={},
        **foreground_lock_broker_kwargs(
            run_id="run-2",
            workflow_run_id="workflow-run-1",
        ),
    )

    assert first_broker.kwargs["foreground_lock"] is second_broker.kwargs["foreground_lock"]
    assert first_broker.kwargs["foreground_lock_owner"] == "workflow:workflow-run-1:run-1"
    assert second_broker.kwargs["foreground_lock_owner"] == "workflow:workflow-run-1:run-2"


def test_runtime_tool_broker_factory_writes_artifact_for_custom_artifacts_dir(tmp_path) -> None:
    factory = RuntimeToolBrokerFactory(
        agent_artifacts_dir=tmp_path / "agent-artifacts",
        tool_broker_factory=FakeBroker,
        memory_store=lambda **kwargs: {"memory": kwargs},
        future_task_store=lambda **kwargs: {"future": kwargs},
        main_chat_agent_id="builtin:yachiyo-main",
    )

    artifact = factory.write_artifact_for_run(
        run_id="workflow-run-1",
        workspace_policy={},
        artifacts_dir=tmp_path / "workflow-artifacts",
        artifact_path="reports/final.md",
        content="Final workflow summary",
    )

    assert artifact == {
        "ok": True,
        "path": "reports/final.md",
        "bytes": len("Final workflow summary".encode("utf-8")),
    }


def test_write_artifact_with_tool_broker_uses_shared_factory(tmp_path) -> None:
    tool_brokers = FakeSharedToolBrokers()

    artifact = write_artifact_with_tool_broker(
        tool_brokers=tool_brokers,
        run_id=" workflow-run-1 ",
        workspace_policy={"default_workdir": str(tmp_path)},
        artifacts_dir=tmp_path / "workflow-artifacts",
        artifact_path="reports/final.md",
        content="Final workflow summary",
    )

    assert artifact["ok"] is True
    assert tool_brokers.calls == [
        {
            "run_id": "workflow-run-1",
            "workspace_policy": {"default_workdir": str(tmp_path)},
            "artifacts_dir": tmp_path / "workflow-artifacts",
        }
    ]
    assert tool_brokers.broker.writes == [("reports/final.md", "Final workflow summary")]


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
