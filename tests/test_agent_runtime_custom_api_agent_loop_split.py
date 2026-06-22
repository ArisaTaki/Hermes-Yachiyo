"""Tests for custom API Agent loop split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.desktop_intents import daily_desktop_intent_tool_request
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
            "tool_policy": {
                "allowed_tools": [
                    "memory.add",
                    "future_task.schedule",
                    "screen.capture",
                    "media.apple_music_play",
                    "browser.open_url",
                ]
            },
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
    assert calls[0]["kwargs"]["tools"] == [
        {"name": "memory.add"},
        {"name": "future_task.schedule"},
        {"name": "screen.capture"},
        {"name": "media.apple_music_play"},
        {"name": "browser.open_url"},
    ]
    assert "Follow approval gates." in calls[0]["messages"][0]["content"]
    assert "memory.add" in calls[0]["messages"][0]["content"]
    assert "future_task.schedule" in calls[0]["messages"][0]["content"]
    assert "prefer structured desktop tools" in calls[0]["messages"][0]["content"]
    assert "prefer structured browser tools" in calls[0]["messages"][0]["content"]
    assert (
        "Do not replace these structured desktop or browser actions with terminal.run"
        in calls[0]["messages"][0]["content"]
    )
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


def test_custom_api_agent_loop_routes_daily_desktop_intents_to_structured_tools() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    goals = [
        (
            "播放超时空辉夜姬",
            "media.apple_music_play",
            {"query": "超时空辉夜姬"},
        ),
        (
            "截个图看看",
            "screen.capture",
            {"reason": "user asked to capture the screen"},
        ),
        (
            "当前窗口是什么",
            "desktop.active_window",
            {},
        ),
    ]
    responses = []
    for _goal, tool, payload in goals:
        responses.extend([
            {"role": "assistant", "content": tool, "tool_payload": payload},
            {"role": "assistant", "content": f"{tool} done"},
        ])

    def tool_requests_from_message(message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        tool = content.strip()
        if tool in {"media.apple_music_play", "screen.capture", "desktop.active_window"}:
            return [
                {
                    "tool": tool,
                    "input": dict(message.get("tool_payload") or {}),
                    "protocol": "tool_calls",
                }
            ]
        return []

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "media.apple_music_play",
                    "screen.capture",
                    "desktop.active_window",
                ]
            },
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use desktop tools for desktop intents.",
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
                "messages": list(messages_arg),
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        ),
        error_type=agent_runtime.AgentRuntimeError,
    )

    for goal, tool, payload in goals:
        result = loop.run(
            {"name": "Yachiyo"},
            goal,
            broker={"broker": True},
            timeline=timeline,
            artifacts=[],
            run_id=f"run-{tool}",
        )

        assert str(result) == f"{tool} done"
        assert tool_runs[-1]["tool_requests"] == [
            {"tool": tool, "input": payload, "protocol": "tool_calls"}
        ]
        assert tool_runs[-1]["allowed_tools"] == [
            "media.apple_music_play",
            "screen.capture",
            "desktop.active_window",
        ]
        assert "terminal.run" not in tool_runs[-1]["allowed_tools"]
        assert goal in tool_runs[-1]["messages"][1]["content"]


def test_daily_desktop_intent_planner_maps_clear_chat_commands_only() -> None:
    allowed_tools = [
        "media.apple_music_play",
        "screen.capture",
        "desktop.active_window",
    ]

    assert daily_desktop_intent_tool_request("播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("截个图看看", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("当前窗口是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("怎么截图？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要真的播放超时空辉夜姬，只告诉我怎么做", allowed_tools) is None
    assert daily_desktop_intent_tool_request("播放超时空辉夜姬", ["workspace.read"]) is None


def test_custom_api_agent_loop_preplans_clear_daily_desktop_intent_before_text_response() -> None:
    budget = FakeBudget()
    order: list[str] = []
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    def run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        order.append("tool")
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": list(messages_arg),
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        messages_arg.append(
            {
                "role": "user",
                "content": (
                    'Tool result for media.apple_music_play: {"ok": false, '
                    '"permission_error": true, "permission_targets": ["music_app", "automation"]}'
                ),
            }
        )

    def call_model(_base_url, _model, _api_key, messages, **_kwargs):
        order.append("model")
        assert "Tool result for media.apple_music_play" in messages[-1]["content"]
        return {"role": "assistant", "content": "Music 权限未就绪，请打开诊断。"}

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "media.apple_music_play",
                    "screen.capture",
                    "desktop.active_window",
                ]
            },
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "播放超时空辉夜姬",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-music",
    )

    assert str(result) == "Music 权限未就绪，请打开诊断。"
    assert order == ["tool", "model"]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "media.apple_music_play",
            "input": {"query": "超时空辉夜姬"},
        }
    ]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-music"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert timeline[0] == {
        "event": "agent.desktop.intent_planned",
        "detail": "media.apple_music_play",
        "input_preview": {"query": "超时空辉夜姬"},
    }


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
        assert getattr(service.custom_api_agent_loop._run_budget, "__self__", None) is not service
        assert getattr(service.custom_api_agent_loop._check_context_budget, "__self__", None) is not service
        assert getattr(service.custom_api_agent_loop._limit_model_output, "__self__", None) is not service

        service.runtime_limits = RunBudgetLimits(max_model_output_chars=5)
        limited, truncated = service.custom_api_agent_loop._limit_model_output("abcdefghi")
        assert truncated is True
        assert limited == "abcde"
    finally:
        service.close()
