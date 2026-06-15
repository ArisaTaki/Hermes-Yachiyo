"""Tests for custom API Agent loop split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    def __init__(self) -> None:
        self.claims = 0

    def claim_model_call(self) -> None:
        self.claims += 1


class FakeToolLoopProjection:
    @staticmethod
    def assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        return {"role": "assistant", "content": message.get("content")}

    @staticmethod
    def artifact_completion(_timeline: list[dict[str, Any]], _artifacts: list[dict[str, Any]]) -> str | None:
        return None

    @staticmethod
    def loop_limit_detail(_timeline: list[dict[str, Any]]) -> str:
        return "loop detail"


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def test_custom_api_agent_loop_builds_runtime_prompt_and_returns_model_output() -> None:
    budget = FakeBudget()
    calls: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local/",
            "model": "test-model",
            "api_key": "key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["memory.add", "future_task.schedule"]},
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: 0 if not isinstance(value, int) else value,
        max_tool_iterations=3,
        operating_doctrine="Follow approval gates.",
        memory_tool_names={"memory.add"},
        future_task_tool_names={"future_task.schedule"},
        call_model=lambda base_url, model, api_key, messages, **kwargs: calls.append(
            {
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        or {"role": "assistant", "content": "final answer", "finish_reason": "stop"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda message: {"finish_reason": message.get("finish_reason")},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Agent"},
        "User context",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        start_iteration="bad",
        run_id="run-1",
    )

    assert str(result) == "final answer"
    assert result.model_metadata == {"finish_reason": "stop"}
    assert result.output_truncated is False
    assert budget.claims == 1
    assert calls[0]["base_url"] == "https://model.local"
    assert calls[0]["kwargs"]["stream"] is True
    assert calls[0]["kwargs"]["tools"] == [{"name": "memory.add"}, {"name": "future_task.schedule"}]
    assert "Follow approval gates." in calls[0]["messages"][0]["content"]
    assert "memory.add" in calls[0]["messages"][0]["content"]
    assert "future_task.schedule" in calls[0]["messages"][0]["content"]
    assert timeline[-1] == {"event": "agent.model.response", "detail": "final answer"}


def test_custom_api_agent_loop_delegates_tool_requests_without_bypassing_runner() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    def tool_requests_from_message(_message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        if content == "need tool":
            return [{"tool": "workspace.read", "input": {}, "protocol": "tool_calls"}]
        return []

    messages = [{"role": "user", "content": "existing"}]
    responses = [
        {"role": "assistant", "content": "need tool", "tool_calls": [{"id": "call-1"}]},
        {"role": "assistant", "content": "done"},
    ]
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": ["workspace.read"]}},
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: responses.pop(0),
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda tool_requests, allowed_tools, broker, messages_arg, timeline_arg, artifacts, **kwargs: tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        ),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Agent"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-1",
    )

    assert str(result) == "done"
    assert budget.claims == 2
    assert tool_runs[0]["tool_requests"] == [{"tool": "workspace.read", "input": {}, "protocol": "tool_calls"}]
    assert tool_runs[0]["allowed_tools"] == ["workspace.read"]
    assert tool_runs[0]["kwargs"]["next_iteration"] == 1
    assert messages[1] == {"role": "assistant", "content": "need tool"}


def test_native_runtime_installs_custom_api_agent_loop(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeCustomApiAgentLoop is RuntimeCustomApiAgentLoop
        assert isinstance(service.custom_api_agent_loop, RuntimeCustomApiAgentLoop)
        assert service.custom_api_agent_loop._tool_schemas is RuntimeToolOperations.model_tool_schemas
        assert getattr(service.custom_api_agent_loop._check_context_budget, "__self__", None) is not service
        assert getattr(service.custom_api_agent_loop._limit_model_output, "__self__", None) is not service

        service.runtime_limits = RunBudgetLimits(max_model_output_chars=5)
        limited, truncated = service.custom_api_agent_loop._limit_model_output("abcdefghi")
        assert truncated is True
        assert limited == "abcde"
    finally:
        service.close()
