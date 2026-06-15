"""Tests for tool-call execution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    def __init__(self) -> None:
        self.claims: list[tuple[str, bool]] = []

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.claims.append((tool_name, terminal_execution))


class FakeToolCallEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def denied(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("denied", args, kwargs))

    def requested(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("requested", args, kwargs))

    def failed(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("failed", args, kwargs))

    def started(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("started", args, kwargs))

    def result(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("result", args, kwargs))

    def agent_tool_call(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("agent_tool_call", args, kwargs))


class FakeTraceEvents:
    def memory_skill_trace_event(
        self,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "memory.add":
            return None
        return {
            "event_type": "memory.write.add",
            "payload": {"tool": tool_name, "input_preview": input_preview, "ok": tool_result.get("ok")},
        }

    def artifact_created_payload(
        self,
        tool_result: dict[str, Any],
        *,
        run_id: str,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "path": tool_result.get("path"),
            "source_tool": "artifact.write",
        }


class FakeBroker:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(self, tool_name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        self.calls.append((tool_name, payload, approved))
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


class FakePendingApprovalBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(
        self,
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pending = {
            "approval_id": "approval-1",
            "tool": tool_request.get("tool"),
            "messages": messages,
            "next_iteration": next_iteration,
            "remaining_tool_requests": remaining_tool_requests,
        }
        self.calls.append(pending)
        return pending


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _executor(
    *,
    tool_call_events: FakeToolCallEvents,
    trace_events: FakeTraceEvents | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
    allows_tool=None,
) -> RuntimeToolCallExecutor:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events or FakeTraceEvents(),
        append_run_event=append_run_event,
        allows_tool=allows_tool,
    )


def _runner(
    *,
    call_agent_tool,
    pending_approval_builder: FakePendingApprovalBuilder | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> RuntimeToolRequestRunner:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda user_goal, tool_name: (
            "no terminal"
            if tool_name == "terminal.run" and "no commands" in user_goal
            else ""
        ),
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=pending_approval_builder or FakePendingApprovalBuilder(),
        call_agent_tool=call_agent_tool,
    )


def test_runtime_tool_call_executor_denies_unallowed_tools_before_broker_call() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {"tool": "terminal.run", "input": {"command": "echo hi"}},
            ["workspace.read"],
            broker,
            timeline,
            run_id="run-1",
            budget=budget,
        )

    assert budget.claims == [("terminal.run", False)]
    assert broker.calls == []
    assert timeline == [
        {
            "event": "agent.tool.denied",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
        }
    ]
    assert [call[0] for call in events.calls] == ["denied"]


def test_runtime_tool_call_executor_uses_injected_policy_gate() -> None:
    events = FakeToolCallEvents()
    policy_calls: list[tuple[str, list[str]]] = []
    executor = _executor(
        tool_call_events=events,
        allows_tool=lambda tool_name, allowed_tools: policy_calls.append(
            (tool_name, allowed_tools)
        )
        or False,
    )
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {"tool": "workspace.read", "input": {"path": "README.md"}},
            ["workspace.read"],
            broker,
            [],
            budget=FakeBudget(),
        )

    assert policy_calls == [("workspace.read", ["workspace.read"])]
    assert broker.calls == []


def test_runtime_tool_call_executor_projects_workspace_failure_as_tool_result() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker(AgentRuntimeError("outside workspace"))

    result = executor.execute(
        {"tool": "workspace.read", "input": {"path": "../secret.txt"}},
        ["workspace.read", "terminal.run"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["tool"] == "workspace.read"
    assert result["suggested_tool"] == "terminal.run"
    assert "relative paths" in result["hint"]
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"] == result
    assert [call[0] for call in events.calls] == [
        "requested",
        "started",
        "result",
        "agent_tool_call",
    ]


def test_runtime_tool_call_executor_records_non_workspace_failures() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)

    with pytest.raises(AgentRuntimeError, match="boom"):
        executor.execute(
            {"tool": "terminal.run", "input": {"command": "echo hi"}},
            ["terminal.run"],
            FakeBroker(AgentRuntimeError("boom")),
            [],
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert [call[0] for call in events.calls] == ["requested", "started", "failed"]


def test_runtime_tool_call_executor_projects_trace_and_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []

    artifact_result = executor.execute(
        {"tool": "artifact.write", "input": {"path": "notes.md", "content": "body"}},
        ["artifact.write"],
        FakeBroker({"ok": True, "path": "notes.md", "content": "body"}),
        [],
        artifacts=artifacts,
        run_id="run-1",
        budget=FakeBudget(),
    )
    memory_result = executor.execute(
        {"tool": "memory.add", "input": {"content": "remember"}},
        ["memory.add"],
        FakeBroker({"ok": True, "memory_id": "mem-1"}),
        [],
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert artifact_result["ok"] is True
    assert memory_result["ok"] is True
    assert artifacts == [{"kind": "tool_artifact", **artifact_result}]
    assert ("run-1", "artifact.created", {"run_id": "run-1", "path": "notes.md", "source_tool": "artifact.write"}) in run_events
    assert ("run-1", "memory.write.add", {"tool": "memory.add", "input_preview": {"content": "remember"}, "ok": True}) in run_events


def test_native_runtime_uses_split_tool_call_executor(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolCallExecutor is RuntimeToolCallExecutor
        assert isinstance(service.tool_call_executor, RuntimeToolCallExecutor)
    finally:
        service.close()


def test_runtime_tool_request_runner_blocks_tools_disallowed_by_user_goal() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "no commands please"}]
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: calls.append("call_agent_tool") or {"ok": True},
        run_events=run_events,
    )

    runner.run(
        [{"tool": "terminal.run", "input": {"command": "echo hi"}}],
        ["terminal.run"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert calls == []
    assert budget.claims == [("terminal.run", False)]
    assert timeline == [
        {
            "event": "agent.tool.skipped",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
            "result": {
                "ok": False,
                "blocked_by_user_goal": True,
                "tool": "terminal.run",
                "error": "no terminal",
                "hint": (
                    "Do not ask for approval. Continue with an inline answer "
                    "that follows the user's stated constraint."
                ),
            },
        }
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert "blocked_by_user_goal" in messages[-1]["content"]


def test_runtime_tool_request_runner_raises_pending_approval_with_remaining_requests() -> None:
    pending_builder = FakePendingApprovalBuilder()
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "terminal.run",
        },
    )
    messages = [{"role": "user", "content": "run command"}]
    requests = [
        {"tool": "terminal.run", "input": {"command": "echo hi"}},
        {"tool": "workspace.read", "input": {"path": "README.md"}},
    ]

    with pytest.raises(AgentApprovalRequired) as exc:
        runner.run(
            requests,
            ["terminal.run", "workspace.read"],
            FakeBroker({"ok": True}),
            messages,
            [],
            [],
            next_iteration=7,
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert exc.value.pending_approval["approval_id"] == "approval-1"
    assert exc.value.pending_approval["next_iteration"] == 7
    assert exc.value.pending_approval["remaining_tool_requests"] == [requests[1]]


def test_runtime_tool_request_runner_projects_fatal_failures_and_success_messages() -> None:
    first_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "returncode": 1,
            "error": "failed",
        },
    )
    fatal_timeline: list[dict[str, Any]] = []
    with pytest.raises(AgentRuntimeError, match="terminal.run 执行失败"):
        first_runner.run(
            [{"tool": "terminal.run", "input": {"command": "npm test"}}],
            ["terminal.run"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "run command"}],
            fatal_timeline,
            [],
            next_iteration=1,
            run_id="run-1",
            budget=FakeBudget(),
        )
    assert fatal_timeline == [
        {
            "event": "agent.tool.failed",
            "detail": "terminal.run",
            "input_preview": {"command": "npm test"},
            "result": {"ok": False, "returncode": 1, "error": "failed"},
            "status": "failed",
        }
    ]

    messages = [{"role": "user", "content": "read file"}]
    second_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True, "content": "hello"},
    )
    second_runner.run(
        [{"tool": "workspace.read", "input": {"path": "README.md"}}],
        ["workspace.read"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=2,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert messages[-1] == {
        "role": "user",
        "content": 'Tool result for workspace.read: {"ok": true, "content": "hello"}',
    }


def test_native_runtime_uses_split_tool_request_runner(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolRequestRunner is RuntimeToolRequestRunner
        assert isinstance(service.tool_request_runner, RuntimeToolRequestRunner)
    finally:
        service.close()
