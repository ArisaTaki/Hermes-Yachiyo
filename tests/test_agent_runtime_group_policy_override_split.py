"""Runtime seams for group-level Agent policy overrides."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell.agent.runtime.agent_runs import (
    AgentRunStart,
    RuntimeAgentRunAsyncCoordinator,
)
from apps.shell.agent.runtime.runnables import RuntimeRunnableRunCoordinator


def test_runnable_run_coordinator_passes_agent_override_to_async_agent_run() -> None:
    captured: dict[str, Any] = {}
    override = {
        "agent_id": "agent-desktop",
        "name": "Desktop Agent",
        "tool_policy": {"allowed_tools": ["screen.capture"], "approval_required": {}},
    }
    coordinator = RuntimeRunnableRunCoordinator(
        resolve_runnable=lambda **_kwargs: {"kind": "agent", "id": "agent-desktop"},
        create_agent_run=lambda _payload: pytest.fail("async path expected"),
        create_workflow_run=lambda _payload: pytest.fail("agent path expected"),
        create_agent_run_async=lambda payload, **_kwargs: captured.setdefault(
            "payload",
            {
                **payload,
                "run_id": "run-agent",
                "run_group_id": "group-run",
            },
        ),
        create_workflow_run_async=lambda _payload, **_kwargs: pytest.fail("agent path expected"),
    )

    run = coordinator.create_run_async(
        runnable_id="agent-desktop",
        user_goal="Inspect the desktop",
        agent_override=override,
    )

    assert captured["payload"]["agent_override"] is override
    assert run["runnable"] == {"kind": "agent", "id": "agent-desktop"}


def test_agent_run_async_uses_agent_override_without_persisted_lookup() -> None:
    captured: dict[str, Any] = {}
    override = {
        "agent_id": "agent-desktop",
        "name": "Desktop Agent",
        "enabled": True,
        "tool_policy": {
            "allowed_tools": ["workspace.read", "screen.capture"],
            "approval_required": {},
        },
    }

    coordinator = RuntimeAgentRunAsyncCoordinator(
        get_agent_private=lambda _agent_id: pytest.fail("override should avoid lookup"),
        validate_agent_run_readiness=lambda agent: captured.setdefault("validated", agent),
        starter=_FakeStarter(captured),
        execute_agent_run=lambda run_id, agent, user_goal, **_kwargs: captured.setdefault(
            "executed",
            {
                "run_id": run_id,
                "agent": agent,
                "user_goal": user_goal,
                "status": "completed",
            },
        ),
        project_agent_run_group_if_root=lambda run: run,
        resolve_runnable=lambda **_kwargs: {"kind": "agent", "id": "agent-desktop"},
        update_run=lambda *_args, **_kwargs: pytest.fail("no failure expected"),
        runtime_agent_timeline=SimpleNamespace(failed=lambda error: {"error": error}),
        runtime_agent_run_events=SimpleNamespace(failed=lambda *_args: None),
        redact_error=str,
        error_type=RuntimeError,
        thread_factory=_ImmediateThread,
    )
    completed: list[dict[str, Any]] = []

    run = coordinator.create_async(
        {
            "agent_id": "agent-desktop",
            "user_goal": "Inspect the desktop",
            "agent_override": override,
        },
        on_complete=completed.append,
    )

    assert captured["validated"]["tool_policy"]["allowed_tools"] == [
        "workspace.read",
        "screen.capture",
    ]
    assert captured["starter_agent"] == captured["validated"]
    assert captured["executed"]["agent"] == captured["validated"]
    assert run["status"] == "processing"
    assert completed[0]["status"] == "completed"


def test_agent_run_async_rejects_mismatched_agent_override() -> None:
    coordinator = RuntimeAgentRunAsyncCoordinator(
        get_agent_private=lambda _agent_id: pytest.fail("mismatched override should fail first"),
        validate_agent_run_readiness=lambda _agent: None,
        starter=_FakeStarter({}),
        execute_agent_run=lambda *_args, **_kwargs: {},
        project_agent_run_group_if_root=lambda run: run,
        resolve_runnable=lambda **_kwargs: {"kind": "agent", "id": "agent-desktop"},
        update_run=lambda *_args, **_kwargs: None,
        runtime_agent_timeline=SimpleNamespace(failed=lambda error: {"error": error}),
        runtime_agent_run_events=SimpleNamespace(failed=lambda *_args: None),
        redact_error=str,
        error_type=RuntimeError,
        thread_factory=_ImmediateThread,
    )

    with pytest.raises(RuntimeError, match="agent_override"):
        coordinator.create_async(
            {
                "agent_id": "agent-desktop",
                "user_goal": "Inspect the desktop",
                "agent_override": {"agent_id": "agent-other"},
            }
        )


class _FakeStarter:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def start_async(self, payload: dict[str, Any], *, agent: dict[str, Any]) -> AgentRunStart:
        self._captured["starter_payload"] = payload
        self._captured["starter_agent"] = agent
        return AgentRunStart(
            {
                "run_id": "run-agent",
                "run_group_id": "group-run",
                "runnable_id": agent["agent_id"],
                "user_goal": payload["user_goal"],
            },
            root_group=False,
        )


class _ImmediateThread:
    def __init__(self, *, target: Any, **_kwargs: Any) -> None:
        self._target = target

    def start(self) -> None:
        self._target()
