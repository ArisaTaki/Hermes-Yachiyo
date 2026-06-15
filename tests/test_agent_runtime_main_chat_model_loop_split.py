"""Tests for main chat model loop runner split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.main_chat_model_loop import MainChatModelLoopRunner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    pass


class FakeRuntimeAgentTimeline:
    @staticmethod
    def compiled(**payload: Any) -> dict[str, Any]:
        return {"event": "agent.runtime.compiled", **payload}


class FakeTaskModelEvents:
    @staticmethod
    def model_request_started_payload(**payload: Any) -> dict[str, Any]:
        return {"started": payload}

    @staticmethod
    def model_request_failed_payload(error: str) -> dict[str, Any]:
        return {"error": error}

    @staticmethod
    def model_output_completed_payload(
        content: str,
        *,
        truncated: bool,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {"content": content, "truncated": truncated, **metadata}


class FakeToolBrokers:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def for_main_chat(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"broker": kwargs}


class FakeApprovalPause:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def project_tool_required(self, run_id: str, **payload: Any) -> dict[str, Any]:
        self.calls.append({"run_id": run_id, **payload})
        return {"run_id": run_id, "status": "approval_required", **payload}


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _runner(**overrides: Any) -> tuple[MainChatModelLoopRunner, dict[str, Any]]:
    state: dict[str, Any] = {
        "run": {"run_id": "run-1", "kind": "main_chat_run", "timeline": [], "artifacts": []},
        "updates": [],
        "events": [],
        "tool_brokers": FakeToolBrokers(),
        "approval_pause": FakeApprovalPause(),
    }
    runner = MainChatModelLoopRunner(
        get_run=lambda _run_id: state["run"],
        default_profile_id=lambda: "profile-chat",
        model_profile_config_private=lambda _profile_id: {
            "base_url": "https://model.local",
            "model": "test-model",
            "api_key": "key",
        },
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "category": "orchestrator",
            **kwargs,
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=FakeRuntimeAgentTimeline(),
        timeline_factory=_timeline,
        update_run=lambda _run_id, **payload: state["updates"].append(payload)
        or {**state["run"], **payload},
        append_run_event=lambda _run_id, event_type, payload: state["events"].append(
            (event_type, payload)
        )
        or {"event_type": event_type, "payload": payload},
        task_model_events=FakeTaskModelEvents(),
        tool_brokers=state["tool_brokers"],
        continue_custom_api_agent=lambda *_args, **_kwargs: "done",
        main_chat_pending_approval=lambda pending, **payload: {"pending": pending, **payload},
        approval_pause=state["approval_pause"],
        terminal_run_or_none=lambda _run_id: None,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
        model_output_metadata=lambda _value: {"finish_reason": "stop"},
        error_type=agent_runtime.AgentRuntimeError,
    )
    for name, value in overrides.items():
        setattr(runner, name, value)
    return runner, state


def test_main_chat_model_loop_runner_projects_successful_loop() -> None:
    runner, state = _runner()

    result = runner.execute("run-1", [{"role": "user", "content": "hi"}])

    assert result["status"] == "running"
    assert result["result"] == "done"
    assert state["tool_brokers"].calls == [
        {
            "run_id": "run-1",
            "workspace_policy": {"default_workdir": "/tmp/project"},
        }
    ]
    assert state["updates"][0]["status"] == "running"
    assert state["updates"][-1]["pending_approval"] is None
    assert [event_type for event_type, _payload in state["events"]] == [
        "model.request.started",
        "model.output.completed",
    ]
    assert state["events"][-1][1]["finish_reason"] == "stop"


def test_main_chat_model_loop_runner_projects_approval_required_without_bypassing_gate() -> None:
    def raise_approval(*_args: Any, **_kwargs: Any) -> str:
        raise AgentApprovalRequired({"tool": "terminal.run", "approval_id": "approval-1"})

    runner, state = _runner()
    runner._continue_custom_api_agent = raise_approval

    result = runner.execute("run-1", [{"role": "user", "content": "run command"}])

    assert result["status"] == "approval_required"
    assert state["approval_pause"].calls[0]["pending_approval"] == {
        "pending": {"tool": "terminal.run", "approval_id": "approval-1"},
        "model_profile_id": "profile-chat",
        "tool_policy": {"allowed_tools": ["workspace.read"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }


def test_native_runtime_installs_main_chat_model_loop_runner(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.MainChatModelLoopRunner is MainChatModelLoopRunner
        assert isinstance(service.main_chat_model_loop, MainChatModelLoopRunner)
        assert getattr(service.main_chat_model_loop._check_context_budget, "__self__", None) is not service
    finally:
        service.close()
