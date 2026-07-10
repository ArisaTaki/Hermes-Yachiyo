"""Tests for main chat model loop runner split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime import main_chat_model_loop
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.main_chat_model_loop import (
    MainChatModelLoopRunner,
    build_runtime_main_chat_model_loop_runner,
)
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


class FakeProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "profile-chat"}


def test_main_chat_model_loop_builder_remains_exported_from_legacy_module() -> None:
    assert (
        agent_runtime._build_runtime_main_chat_model_loop_runner
        is build_runtime_main_chat_model_loop_runner
    )


def test_build_runtime_main_chat_model_loop_runner_wires_runtime_dependencies() -> None:
    runner = build_runtime_main_chat_model_loop_runner(
        get_run=lambda _run_id: {"run_id": "run-1", "kind": "main_chat_run", "timeline": []},
        profile_service_factory=FakeProfileService,
        model_profile_config_private=lambda _profile_id: {},
        main_chat_agent_config=lambda **kwargs: {"agent_id": "builtin:yachiyo-main", **kwargs},
        compile_agent_runtime=lambda _agent: {"tool_policy": {}, "workspace_policy": {}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=FakeRuntimeAgentTimeline(),
        timeline_factory=_timeline,
        update_run=lambda _run_id, **payload: {"run_id": "run-1", **payload},
        append_run_event=lambda _run_id, event_type, payload: {
            "event_type": event_type,
            "payload": payload,
        },
        task_model_events=FakeTaskModelEvents(),
        tool_brokers=FakeToolBrokers(),
        continue_custom_api_agent=lambda *_args, **_kwargs: "done",
        main_chat_pending_approval=lambda pending, **payload: {"pending": pending, **payload},
        approval_pause=FakeApprovalPause(),
        terminal_run_or_none=lambda _run_id: None,
    )

    assert isinstance(runner, MainChatModelLoopRunner)
    assert runner._default_profile_id() == "profile-chat"
    assert getattr(runner._run_budget, "__self__", None) is None
    assert getattr(runner._check_context_budget, "__self__", None) is None


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


def test_main_chat_model_loop_runner_forwards_runtime_execution_context() -> None:
    continue_calls: list[dict[str, Any]] = []
    runner, _state = _runner()
    envelope = {"envelope_id": "env-main", "requests": [{"tool_name": "app.open"}]}
    metadata = {"yachiyo_runtime_planner": True}

    def continue_custom_api_agent(
        _agent: dict[str, Any],
        _context: str,
        _broker: dict[str, Any],
        _timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        continue_calls.append(kwargs)
        return "done"

    runner._continue_custom_api_agent = continue_custom_api_agent

    result = runner.execute(
        "run-1",
        [{"role": "user", "content": "打开 Apple Music"}],
        runtime_execution_envelope=envelope,
        runtime_execution_metadata=metadata,
    )

    assert result["status"] == "running"
    assert continue_calls[0]["runtime_execution_envelope"] is envelope
    forwarded_metadata = continue_calls[0]["runtime_execution_metadata"]
    assert forwarded_metadata["yachiyo_runtime_planner"] is True
    assert forwarded_metadata["desktop_execution_policy"]["mode"] == "preview_input"


def test_main_chat_model_loop_runner_passes_approval_policy_to_broker() -> None:
    runner, state = _runner()
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {
            "allowed_tools": ["desktop.type_text"],
            "approval_required": {"desktop.type_text": True},
        },
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    result = runner.execute("run-1", [{"role": "user", "content": "输入 hello"}])

    assert result["status"] == "running"
    assert state["tool_brokers"].calls[0]["approvals"] == {"desktop.type_text": True}


def test_main_chat_model_loop_runner_treats_runtime_envelope_as_direct_without_profile() -> None:
    continue_calls: list[dict[str, Any]] = []
    runner, state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {"allowed_tools": ["app.open"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }
    envelope = {
        "requests": [
            {
                "request_id": "open-music",
                "tool_name": "app.open",
                "input": {"app_name": "Music"},
            }
        ]
    }

    def continue_custom_api_agent(
        agent: dict[str, Any],
        _context: str,
        _broker: dict[str, Any],
        _timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        continue_calls.append({"agent": agent, "kwargs": kwargs})
        return "opened"

    runner._continue_custom_api_agent = continue_custom_api_agent

    result = runner.execute(
        "run-1",
        [{"role": "user", "content": "打开 Apple Music"}],
        runtime_execution_envelope=envelope,
    )

    assert result["status"] == "running"
    assert result["result"] == "opened"
    assert continue_calls[0]["agent"]["model_profile_id"] == ""
    assert continue_calls[0]["kwargs"]["runtime_execution_envelope"] is envelope
    assert [event_type for event_type, _payload in state["events"]] == [
        "model.output.completed"
    ]


def test_main_chat_model_loop_runner_uses_runtime_planner_without_profile_before_legacy(
) -> None:
    assert not hasattr(main_chat_model_loop, "daily_desktop_intent_tool_request")
    assert not hasattr(main_chat_model_loop, "daily_desktop_intent_tool_requests")
    assert not hasattr(main_chat_model_loop, "daily_desktop_intent_candidates")

    continue_calls: list[dict[str, Any]] = []
    runner, state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {"allowed_tools": ["app.open", "desktop.click_ui_element"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    def continue_custom_api_agent(
        agent: dict[str, Any],
        _context: str,
        broker: dict[str, Any],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        continue_calls.append(
            {
                "agent": agent,
                "broker": broker,
                "timeline": timeline,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        return "opened"

    runner._continue_custom_api_agent = continue_custom_api_agent

    result = runner.execute(
        "run-1",
        [{"role": "user", "content": "打开 PixelForge 并点击导出按钮"}],
    )

    assert result["status"] == "running"
    assert result["result"] == "opened"
    assert continue_calls[0]["agent"]["model_profile_id"] == ""
    assert [event_type for event_type, _payload in state["events"]] == [
        "model.output.completed"
    ]
    assert state["tool_brokers"].calls == [
        {
            "run_id": "run-1",
            "workspace_policy": {"default_workdir": "/tmp/project"},
        }
    ]


def test_main_chat_model_loop_runner_keeps_profile_required_for_planner_model_followup() -> None:
    runner, _state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {"allowed_tools": ["workspace.list", "workspace.read", "artifact.write"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    def continue_custom_api_agent(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("model-followup planner requests should not bypass profile readiness")

    runner._continue_custom_api_agent = continue_custom_api_agent

    with pytest.raises(
        agent_runtime.AgentRuntimeError,
        match="native_agent_not_ready:chat_model_profile_required",
    ):
        runner.execute("run-1", [{"role": "user", "content": "写一份项目总结报告"}])


def test_main_chat_model_loop_runner_treats_discovered_app_followup_as_direct() -> None:
    continue_calls: list[dict[str, Any]] = []
    runner, state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {
            "allowed_tools": [
                "desktop.list_apps",
                "desktop.open_app",
                "desktop.active_window",
            ],
        },
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    def continue_custom_api_agent(
        agent: dict[str, Any],
        _context: str,
        broker: dict[str, Any],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        continue_calls.append(
            {
                "agent": agent,
                "broker": broker,
                "timeline": timeline,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        return "opened"

    runner._continue_custom_api_agent = continue_custom_api_agent

    result = runner.execute(
        "run-1",
        [{"role": "user", "content": "找一个能编辑 PDF 的本机应用并打开它"}],
    )

    assert result["status"] == "running"
    assert result["result"] == "opened"
    assert continue_calls[0]["agent"]["model_profile_id"] == ""
    assert [event_type for event_type, _payload in state["events"]] == [
        "model.output.completed"
    ]


def test_main_chat_model_loop_runner_projects_approval_required_without_bypassing_gate() -> None:
    def raise_approval(*_args: Any, **_kwargs: Any) -> str:
        raise AgentApprovalRequired({"tool": "terminal.run", "approval_id": "approval-1"})

    runner, state = _runner()
    runner._continue_custom_api_agent = raise_approval
    envelope = {"envelope_id": "env-approval", "requests": [{"tool_name": "terminal.run"}]}
    metadata = {"yachiyo_runtime_planner": True}

    result = runner.execute(
        "run-1",
        [{"role": "user", "content": "run command"}],
        runtime_execution_envelope=envelope,
        runtime_execution_metadata=metadata,
    )

    assert result["status"] == "approval_required"
    pending = state["approval_pause"].calls[0]["pending_approval"]
    assert {
        key: value
        for key, value in pending.items()
        if key != "runtime_execution_metadata"
    } == {
        "pending": {"tool": "terminal.run", "approval_id": "approval-1"},
        "model_profile_id": "profile-chat",
        "tool_policy": {"allowed_tools": ["workspace.read"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
        "runtime_execution_envelope": envelope,
    }
    assert pending["runtime_execution_metadata"]["yachiyo_runtime_planner"] is True
    assert pending["runtime_execution_metadata"]["desktop_execution_policy"]["mode"] == "preview_input"


def test_main_chat_model_loop_runner_reports_provider_blocker_without_chat_profile() -> None:
    runner, state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {"allowed_tools": ["app.focus"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    def fail_after_provider_block(
        _agent: dict[str, Any],
        _context: str,
        _broker: dict[str, Any],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> str:
        timeline.append(
            _timeline(
                "agent.tool.skipped",
                "app.focus",
                result={
                    "ok": False,
                    "error": "desktop_execution_policy_blocked",
                    "blocking_conditions": [
                        "loopback_desktop_backend",
                        "real_virtual_desktop_backend_required",
                    ],
                },
            )
        )
        raise agent_runtime.AgentRuntimeError(
            "Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。"
        )

    runner._continue_custom_api_agent = fail_after_provider_block
    envelope = {
        "requests": [
            {
                "request_id": "focus-browser",
                "tool_name": "app.focus",
                "input": {"app_name": "Google Chrome"},
            }
        ]
    }

    with pytest.raises(agent_runtime.AgentRuntimeError, match="隔离桌面 Provider"):
        runner.execute(
            "run-1",
            [{"role": "user", "content": "打开 Chrome 后退一下"}],
            runtime_execution_envelope=envelope,
        )

    assert state["updates"][-1]["status"] == "failed"
    assert "Chat Profile" not in state["updates"][-1]["result"]
    event_type, event_payload = state["events"][-1]
    assert event_type == "agent.desktop.permission_recovery"
    assert event_payload["error"] == state["updates"][-1]["result"]
    assert event_payload["status"] == "blocked"
    assert event_payload["blocking_conditions"] == [
        "loopback_desktop_backend",
        "real_virtual_desktop_backend_required",
    ]
    assert event_payload["recovery_actions"] == [
        {
            "tool": "desktop.provider_session.start",
            "label": "Start isolated desktop provider",
            "input": {"diagnostic_route": "/yachiyo/studio/tools"},
            "planning_reason": "desktop_provider_session_recovery",
            "permission_target": "isolated_desktop_provider",
            "risk_level": "medium",
            "approval_required": True,
            "approval_status": "pending",
        }
    ]


def test_main_chat_model_loop_runner_preserves_unrelated_error_after_provider_block() -> None:
    runner, state = _runner()
    runner._default_profile_id = lambda: ""
    runner._compile_agent_runtime = lambda _agent: {
        "tool_policy": {"allowed_tools": ["app.focus"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }

    def fail_with_unrelated_error(
        _agent: dict[str, Any],
        _context: str,
        _broker: dict[str, Any],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> str:
        timeline.append(
            _timeline(
                "agent.tool.skipped",
                "app.focus",
                result={
                    "error": "desktop_execution_policy_blocked",
                    "blocking_conditions": ["sandbox_desktop_provider_required"],
                },
            )
        )
        raise agent_runtime.AgentRuntimeError("planner payload malformed")

    runner._continue_custom_api_agent = fail_with_unrelated_error

    with pytest.raises(agent_runtime.AgentRuntimeError, match="planner payload malformed"):
        runner.execute(
            "run-1",
            [{"role": "user", "content": "打开 Chrome 后退一下"}],
            runtime_execution_envelope={
                "requests": [
                    {
                        "request_id": "focus-browser",
                        "tool_name": "app.focus",
                        "input": {"app_name": "Google Chrome"},
                    }
                ]
            },
        )

    assert state["updates"][-1]["result"] == "planner payload malformed"
    assert state["events"][-1][0] == "model.request.failed"


def test_main_chat_model_loop_runner_forwards_provider_recovery_actions() -> None:
    action = {
        "tool": "desktop.provider_session.start",
        "label": "Configure release provider",
        "input": {"provider_id": "provider-1"},
        "permission_target": "isolated_desktop_provider",
        "risk_level": "medium",
        "approval_required": True,
        "deferred_continuation": [
            {"tool": "app.focus", "input": {"app_name": "Google Chrome"}}
        ],
    }
    failure = main_chat_model_loop._desktop_provider_required_failure(
        [
            _timeline(
                "agent.tool.skipped",
                "app.focus",
                result={
                    "error": "desktop_execution_policy_blocked",
                    "blocking_conditions": ["sandbox_desktop_provider_required"],
                    "recovery_actions": [action],
                },
            )
        ]
    )

    assert failure["recovery_actions"] == [action]
    assert failure["recovery_actions"][0] is not action


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
        assert getattr(service.main_chat_model_loop._run_budget, "__self__", None) is not service
        assert getattr(service.main_chat_model_loop._check_context_budget, "__self__", None) is not service
    finally:
        service.close()
