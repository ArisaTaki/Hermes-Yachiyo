"""Tests for Agent Run creation split out of the legacy runtime."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.agent_runs import (
    AgentRunStart,
    RuntimeAgentRunAsyncCoordinator,
    RuntimeAgentRunCoordinator,
    RuntimeAgentRunExecutor,
    RuntimeAgentRunStarter,
    _with_entrypoint_runtime_planner,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _ImmediateThread:
    def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self._target()


@dataclass
class _PreparedAgentRun:
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    context: str = "prepared-context"
    broker: Any = "prepared-broker"


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


def test_agent_run_executor_projects_completed_agent_run() -> None:
    calls: list[tuple[str, Any]] = []
    prepared = _PreparedAgentRun(
        timeline=[{"event": "agent.run.started"}],
        artifacts=[{"path": "context.md"}],
    )

    class _Preparer:
        @staticmethod
        def prepare(
            run_id: str,
            agent: dict[str, Any],
            user_goal: str,
            upstream: str,
            *,
            run_group_id: str = "",
            workflow_run_id: str = "",
        ) -> _PreparedAgentRun:
            calls.append(
                (
                    "prepare",
                    run_id,
                    agent["agent_id"],
                    user_goal,
                    upstream,
                    run_group_id,
                    workflow_run_id,
                )
            )
            return prepared

        @staticmethod
        def write_context_artifact(run_id: str, preparation: _PreparedAgentRun) -> None:
            calls.append(("context", run_id, preparation.context))

    class _Outcomes:
        @staticmethod
        def completed(run_id: str, result: str, *, timeline: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append(("completed", run_id, result, timeline, artifacts))
            return {"run_id": run_id, "status": "completed", "result": result}

    executor = RuntimeAgentRunExecutor(
        preparer=_Preparer(),
        continue_custom_api_agent=lambda agent, context, broker, timeline, artifacts, **kwargs: calls.append(
            ("continue", agent["agent_id"], context, broker, timeline, artifacts, kwargs)
        )
        or "Done",
        agent_run_outcomes=_Outcomes(),
        approval_pause=object(),
    )

    result = executor.execute(
        "run-1",
        {"agent_id": "agent-1"},
        "Ship",
        "Upstream",
        run_group_id="group-1",
    )

    assert result == {"run_id": "run-1", "status": "completed", "result": "Done"}
    assert calls == [
        ("prepare", "run-1", "agent-1", "Ship", "Upstream", "group-1", ""),
        ("context", "run-1", "prepared-context"),
        (
            "continue",
            "agent-1",
            "prepared-context",
            "prepared-broker",
            prepared.timeline,
            prepared.artifacts,
            {
                "daily_desktop_planning_context": "",
                "direct_tool_request": None,
                "direct_tool_requests": None,
                "run_id": "run-1",
            },
        ),
        ("completed", "run-1", "Done", prepared.timeline, prepared.artifacts),
    ]


def test_agent_run_executor_passes_workflow_run_id_to_preparer() -> None:
    calls: list[tuple[str, str]] = []
    prepared = _PreparedAgentRun(timeline=[], artifacts=[])

    class _Preparer:
        @staticmethod
        def prepare(
            run_id: str,
            _agent: dict[str, Any],
            _user_goal: str,
            _upstream: str,
            *,
            run_group_id: str = "",
            workflow_run_id: str = "",
        ) -> _PreparedAgentRun:
            calls.append(("prepare", f"{run_id}:{run_group_id}:{workflow_run_id}"))
            return prepared

        @staticmethod
        def write_context_artifact(_run_id: str, _preparation: _PreparedAgentRun) -> None:
            calls.append(("context", _run_id))

    class _Outcomes:
        @staticmethod
        def completed(
            run_id: str,
            result: str,
            *,
            timeline: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
        ) -> dict[str, Any]:
            return {"run_id": run_id, "status": "completed", "result": result}

    executor = RuntimeAgentRunExecutor(
        preparer=_Preparer(),
        continue_custom_api_agent=lambda *_args, **_kwargs: "Done",
        agent_run_outcomes=_Outcomes(),
        approval_pause=object(),
    )

    assert executor.execute(
        "child-run-1",
        {"agent_id": "agent-1"},
        "Ship",
        workflow_run_id="workflow-run-1",
    ) == {"run_id": "child-run-1", "status": "completed", "result": "Done"}
    assert calls == [
        ("prepare", "child-run-1::workflow-run-1"),
        ("context", "child-run-1"),
    ]


def test_agent_run_executor_projects_tool_approval_pause() -> None:
    prepared = _PreparedAgentRun(timeline=[{"event": "agent.run.started"}], artifacts=[])
    pending = {"approval_id": "approval-1", "tool": "terminal.run"}

    class _Preparer:
        @staticmethod
        def prepare(*_args: Any, **_kwargs: Any) -> _PreparedAgentRun:
            return prepared

        @staticmethod
        def write_context_artifact(*_args: Any) -> None:
            return None

    class _ApprovalPause:
        @staticmethod
        def project_tool_required(
            run_id: str,
            *,
            pending_approval: dict[str, Any],
            timeline: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
        ) -> dict[str, Any]:
            return {
                "run_id": run_id,
                "status": "approval_required",
                "pending_approval": pending_approval,
                "timeline": timeline,
                "artifacts": artifacts,
            }

    executor = RuntimeAgentRunExecutor(
        preparer=_Preparer(),
        continue_custom_api_agent=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AgentApprovalRequired(pending)
        ),
        agent_run_outcomes=object(),
        approval_pause=_ApprovalPause(),
    )

    assert executor.execute("run-approval", {"agent_id": "agent-1"}, "Ship") == {
        "run_id": "run-approval",
        "status": "approval_required",
        "pending_approval": pending,
        "timeline": prepared.timeline,
        "artifacts": prepared.artifacts,
    }


def test_agent_run_executor_projects_failed_agent_run() -> None:
    prepared = _PreparedAgentRun(timeline=[{"event": "agent.run.started"}], artifacts=[])

    class _Preparer:
        @staticmethod
        def prepare(*_args: Any, **_kwargs: Any) -> _PreparedAgentRun:
            return prepared

        @staticmethod
        def write_context_artifact(*_args: Any) -> None:
            return None

    class _Outcomes:
        @staticmethod
        def failed(run_id: str, exc: Exception, *, timeline: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
                "timeline": timeline,
                "artifacts": artifacts,
            }

    executor = RuntimeAgentRunExecutor(
        preparer=_Preparer(),
        continue_custom_api_agent=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("execution failed")
        ),
        agent_run_outcomes=_Outcomes(),
        approval_pause=object(),
    )

    assert executor.execute("run-failed", {"agent_id": "agent-1"}, "Ship") == {
        "run_id": "run-failed",
        "status": "failed",
        "error": "execution failed",
        "timeline": prepared.timeline,
        "artifacts": prepared.artifacts,
    }


def test_agent_run_runtime_planner_entrypoint_overlays_stale_desktop_policy() -> None:
    agent = {
        "agent_id": "agent-yachiyo",
        "name": "Yachiyo",
        "tool_policy": {
            "allowed_tools": ["workspace.read"],
            "approval_required": {},
        },
    }

    enriched = _with_entrypoint_runtime_planner(
        agent,
        {
            "runtime_planner_entrypoint": True,
            "user_goal": "能否帮我播放apple Music?",
        },
    )

    allowed = enriched["tool_policy"]["allowed_tools"]
    approval_required = enriched["tool_policy"]["approval_required"]
    assert "_daily_desktop_policy_overlay" not in agent
    assert enriched["_runtime_planner_entrypoint"] is True
    assert enriched["_daily_desktop_policy_overlay"] is True
    assert allowed[:1] == ["workspace.read"]
    assert "desktop.list_apps" in allowed
    assert "app.open" in allowed
    assert "media.music_app_open_and_play" in allowed
    assert approval_required["desktop.hotkey"] is True
    assert approval_required["app.open_and_click_ui_element"] is True


def test_agent_run_runtime_planner_entrypoint_does_not_overlay_howto_question() -> None:
    agent = {
        "agent_id": "agent-yachiyo",
        "name": "Yachiyo",
        "tool_policy": {
            "allowed_tools": ["workspace.read"],
            "approval_required": {},
        },
    }

    enriched = _with_entrypoint_runtime_planner(
        agent,
        {
            "runtime_planner_entrypoint": True,
            "user_goal": "怎么播放 Apple Music？",
        },
    )

    assert enriched is agent
    assert enriched["tool_policy"]["allowed_tools"] == ["workspace.read"]


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
            return AgentRunStart({"run_id": "run-1", "run_group_id": "group-1"}, root_group=True)

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
    assert calls[3] == (
        "execute",
        "run-1",
        "agent-1",
        "Ship",
        {"upstream": "Context", "run_group_id": "group-1"},
    )
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


def test_agent_run_async_coordinator_returns_processing_and_completes_in_background() -> None:
    completions: list[dict[str, Any]] = []

    class _Starter:
        def start_async(self, payload: dict[str, Any], *, agent: dict[str, Any]) -> AgentRunStart:
            return AgentRunStart(
                {"run_id": "run-1", "kind": "agent_run", "run_group_id": "group-1"},
                root_group=True,
            )

    coordinator = RuntimeAgentRunAsyncCoordinator(
        get_agent_private=lambda agent_id: {"agent_id": agent_id, "name": "Runner"},
        validate_agent_run_readiness=lambda _agent: None,
        starter=_Starter(),  # type: ignore[arg-type]
        execute_agent_run=lambda run_id, agent, user_goal, **kwargs: {
            "run_id": run_id,
            "status": "completed",
            "user_goal": user_goal,
            **kwargs,
        },
        project_agent_run_group_if_root=lambda result: {**result, "group_projected": True},
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"], "kind": "agent"},
        update_run=lambda *_args, **_kwargs: {},
        runtime_agent_timeline=object(),
        runtime_agent_run_events=object(),
        redact_error=str,
        error_type=agent_runtime.AgentRuntimeError,
        thread_factory=_ImmediateThread,
    )

    result = coordinator.create_async(
        {"agent_id": "agent-1", "user_goal": "Ship", "upstream": "Context"},
        on_complete=completions.append,
    )

    assert result["status"] == "processing"
    assert result["agent_run_id"] == "run-1"
    assert result["runnable"] == {"id": "agent-1", "kind": "agent"}
    assert completions == [
        {
            "run_id": "run-1",
            "status": "completed",
            "user_goal": "Ship",
            "upstream": "Context",
            "run_group_id": "group-1",
            "group_projected": True,
        }
    ]


def test_agent_run_async_coordinator_projects_background_failure() -> None:
    completions: list[dict[str, Any]] = []
    failed_events: list[tuple[str, str]] = []
    updates: list[dict[str, Any]] = []

    class _Starter:
        def start_async(self, payload: dict[str, Any], *, agent: dict[str, Any]) -> AgentRunStart:
            return AgentRunStart({"run_id": "run-fail", "kind": "agent_run"}, root_group=False)

    class _Timeline:
        @staticmethod
        def failed(error: str) -> dict[str, str]:
            return {"event": "agent.run.failed", "detail": error}

    class _Events:
        @staticmethod
        def failed(run_id: str, error: str) -> None:
            failed_events.append((run_id, error))

    def fail_execute(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("secret failure")

    coordinator = RuntimeAgentRunAsyncCoordinator(
        get_agent_private=lambda agent_id: {"agent_id": agent_id, "name": "Runner"},
        validate_agent_run_readiness=lambda _agent: None,
        starter=_Starter(),  # type: ignore[arg-type]
        execute_agent_run=fail_execute,
        project_agent_run_group_if_root=lambda result: result,
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"]},
        update_run=lambda run_id, **kwargs: updates.append({"run_id": run_id, **kwargs}) or {"run_id": run_id},
        runtime_agent_timeline=_Timeline(),
        runtime_agent_run_events=_Events(),
        redact_error=lambda error: str(error).replace("secret", "[redacted]"),
        error_type=agent_runtime.AgentRuntimeError,
        thread_factory=_ImmediateThread,
    )

    result = coordinator.create_async({"agent_id": "agent-1", "user_goal": "Ship"}, on_complete=completions.append)

    assert result["status"] == "processing"
    assert failed_events == [("run-fail", "[redacted] failure")]
    assert updates == [
        {
            "run_id": "run-fail",
            "status": "failed",
            "result": "[redacted] failure",
            "timeline": [{"event": "agent.run.failed", "detail": "[redacted] failure"}],
            "artifacts": [],
            "pending_approval": None,
        }
    ]
    assert completions == [{"run_id": "run-fail", "kind": "agent_run", "status": "failed", "result": "[redacted] failure"}]


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
        assert agent_runtime.RuntimeAgentRunAsyncCoordinator is RuntimeAgentRunAsyncCoordinator
        assert agent_runtime.RuntimeAgentRunExecutor is RuntimeAgentRunExecutor
        assert isinstance(service.agent_run_starter, RuntimeAgentRunStarter)
        assert isinstance(service.agent_run_coordinator, RuntimeAgentRunCoordinator)
        assert isinstance(service.agent_run_async_coordinator, RuntimeAgentRunAsyncCoordinator)
        assert isinstance(service.agent_run_executor, RuntimeAgentRunExecutor)
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
