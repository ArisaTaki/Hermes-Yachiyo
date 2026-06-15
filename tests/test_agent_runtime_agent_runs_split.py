"""Tests for Agent Run creation split out of the legacy runtime."""

from __future__ import annotations

import threading
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_runs import AgentRunStart, RuntimeAgentRunCoordinator, RuntimeAgentRunStarter
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _starter(
    state: dict[str, Any],
    *,
    client_request_id_from_payload=lambda payload: str(payload.get("client_run_id") or ""),
) -> RuntimeAgentRunStarter:
    def get_run_group(run_group_id: str) -> dict[str, Any]:
        state.setdefault("validated_groups", []).append(run_group_id)
        return {"run_group_id": run_group_id}

    def insert_run_group(**kwargs: Any) -> dict[str, Any]:
        run_group_id = f"group-{len(state.setdefault('groups', [])) + 1}"
        group = {"run_group_id": run_group_id, **kwargs}
        state["groups"].append(group)
        return group

    def insert_run(**kwargs: Any) -> dict[str, Any]:
        run = {"run_id": f"run-{len(state.setdefault('runs', [])) + 1}", **kwargs}
        state["runs"].append(run)
        client_request_id = str(kwargs.get("client_request_id") or "")
        if client_request_id:
            state.setdefault("by_client", {})[client_request_id] = {**run, "idempotent": True}
        return run

    return RuntimeAgentRunStarter(
        get_run_group=get_run_group,
        insert_run_group=insert_run_group,
        insert_run=insert_run,
        run_by_client_request_id=lambda value: state.setdefault("by_client", {}).get(value),
        client_request_id_from_payload=client_request_id_from_payload,
        agent_workspace_dir=lambda agent: str((agent.get("workspace_policy") or {}).get("default_workdir") or ""),
    )


def test_agent_run_starter_creates_root_group_and_preserves_idempotency() -> None:
    state: dict[str, Any] = {}
    starter = _starter(state)
    agent = {
        "agent_id": "agent-1",
        "name": "Runner",
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }
    payload = {"agent_id": "agent-1", "user_goal": "Finish", "client_run_id": "client-1"}

    first = starter.start_sync(payload, agent=agent, lock=threading.RLock())
    second = starter.start_sync(payload, agent=agent, lock=threading.RLock())

    assert first.existing is False
    assert first.root_group is True
    assert first.run["kind"] == "agent_run"
    assert first.run["runnable_id"] == "agent-1"
    assert first.run["run_group_id"] == "group-1"
    assert first.run["client_request_id"] == "client-1"
    assert state["groups"] == [
        {
            "run_group_id": "group-1",
            "title": "Runner: Finish",
            "source": "agent",
            "workspace_dir": "/tmp/project",
        }
    ]
    assert second.existing is True
    assert second.run["idempotent"] is True
    assert second.run["run_id"] == first.run["run_id"]
    assert len(state["runs"]) == 1


def test_agent_run_starter_uses_existing_group_without_root_projection() -> None:
    state: dict[str, Any] = {}
    starter = _starter(state)

    start = starter.start_sync(
        {
            "agent_id": "agent-1",
            "user_goal": "Run in group",
            "run_group_id": "group-existing",
        },
        agent={"agent_id": "agent-1", "name": "Runner"},
        lock=threading.RLock(),
    )

    assert start.root_group is False
    assert start.run["run_group_id"] == "group-existing"
    assert state["validated_groups"] == ["group-existing"]
    assert state.get("groups") is None


def test_agent_run_starter_async_preserves_legacy_non_idempotent_behavior() -> None:
    state: dict[str, Any] = {}

    def unexpected_client_request_id(_payload: dict[str, Any]) -> str:
        raise AssertionError("async agent runs should not consult client request id")

    starter = _starter(state, client_request_id_from_payload=unexpected_client_request_id)
    start = starter.start_async(
        {"agent_id": "agent-1", "user_goal": "Run later", "client_run_id": "ignored-client-id"},
        agent={"agent_id": "agent-1", "name": "Runner"},
    )

    assert start.root_group is True
    assert start.run["client_request_id"] == ""
    assert len(state["runs"]) == 1


def test_agent_run_coordinator_validates_starts_executes_and_projects_root_group() -> None:
    calls: list[tuple[str, Any]] = []

    class _Starter:
        def start_sync(self, payload: dict[str, Any], *, agent: dict[str, Any], lock: Any) -> AgentRunStart:
            calls.append(("start", payload, agent, lock))
            return AgentRunStart({"run_id": "run-1"}, root_group=True)

    coordinator = RuntimeAgentRunCoordinator(
        get_agent_private=lambda agent_id: calls.append(("agent", agent_id)) or {
            "agent_id": agent_id,
            "name": "Runner",
        },
        validate_agent_run_readiness=lambda agent: calls.append(("readiness", agent["agent_id"])),
        starter=_Starter(),  # type: ignore[arg-type]
        execute_agent_run=lambda run_id, agent, user_goal, **kwargs: calls.append(
            ("execute", run_id, agent["agent_id"], user_goal, kwargs)
        )
        or {"run_id": run_id, "status": "completed"},
        project_agent_run_group_if_root=lambda result: calls.append(("project", result["run_id"]))
        or {**result, "group_projected": True},
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = coordinator.create_sync({"agent_id": "agent-1", "user_goal": "Ship", "upstream": "Context"})

    assert result == {"run_id": "run-1", "status": "completed", "group_projected": True}
    assert calls[0] == ("agent", "agent-1")
    assert calls[1] == ("readiness", "agent-1")
    assert calls[3] == ("execute", "run-1", "agent-1", "Ship", {"upstream": "Context"})
    assert calls[4] == ("project", "run-1")


def test_agent_run_coordinator_returns_existing_idempotent_run_without_execution() -> None:
    class _Starter:
        def start_sync(self, payload: dict[str, Any], *, agent: dict[str, Any], lock: Any) -> AgentRunStart:
            return AgentRunStart({"run_id": "existing", "idempotent": True}, root_group=False, existing=True)

    coordinator = RuntimeAgentRunCoordinator(
        get_agent_private=lambda agent_id: {"agent_id": agent_id, "name": "Runner"},
        validate_agent_run_readiness=lambda _agent: None,
        starter=_Starter(),  # type: ignore[arg-type]
        execute_agent_run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not execute")),
        project_agent_run_group_if_root=lambda result: result,
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    assert coordinator.create_sync({"agent_id": "agent-1", "user_goal": "Ship"}) == {
        "run_id": "existing",
        "idempotent": True,
    }


def test_native_runtime_uses_split_agent_run_starter(tmp_path, monkeypatch) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    model_calls: list[list[dict[str, Any]]] = []

    def fake_chat(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, str]:
        model_calls.append(messages)
        return {"content": "Done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        assert agent_runtime.RuntimeAgentRunStarter is RuntimeAgentRunStarter
        assert agent_runtime.RuntimeAgentRunCoordinator is RuntimeAgentRunCoordinator
        assert isinstance(service.agent_run_starter, RuntimeAgentRunStarter)
        assert isinstance(service.agent_run_coordinator, RuntimeAgentRunCoordinator)
        agent = service.create_agent(
            {
                "name": "Starter Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )

        first = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Finish", "client_run_id": "starter-client-1"}
        )
        second = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Finish", "client_run_id": "starter-client-1"}
        )

        assert first["status"] == "completed"
        assert second["idempotent"] is True
        assert second["run_id"] == first["run_id"]
        assert len(model_calls) == 1
    finally:
        service.close()
