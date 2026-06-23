"""Tests for custom API Agent loop split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.config import MAIN_CHAT_AGENT_ID
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
)
from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_requests import normalize_tool_name
from apps.shell.agent.tools.policy import PolicyGate
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    def __init__(self) -> None:
        self.claims = 0
        self.tool_claims: list[tuple[str, bool]] = []

    def claim_model_call(self) -> None:
        self.claims += 1

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.tool_claims.append((tool_name, terminal_execution))


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


class RecordingDesktopBroker:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(self, tool_name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        self.order.append("tool")
        self.calls.append((tool_name, payload, approved))
        return {
            "ok": True,
            "action": tool_name,
            "summary": "Playing 超时空辉夜姬",
            "data": {"query": payload.get("query"), "track": "超时空辉夜姬"},
            "permission_error": False,
            "fallback_used": False,
        }


class RecordingToolCallEvents:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    def denied(self, run_id: str, tool_name: str, input_preview: Any) -> None:
        self._append(run_id, "agent.tool.denied", tool_name, input_preview, "denied")

    def requested(self, run_id: str, tool_name: str, input_preview: Any, *, approved: bool = False) -> None:
        self._append(run_id, "tool.requested", tool_name, input_preview, "requested", approved=approved)

    def failed(self, run_id: str, tool_name: str, input_preview: Any, **_kwargs: Any) -> None:
        self._append(run_id, "tool.failed", tool_name, input_preview, "failed")

    def started(self, run_id: str, tool_name: str, input_preview: Any, *, approved: bool = False) -> None:
        self._append(run_id, "tool.started", tool_name, input_preview, "running", approved=approved)

    def result(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
    ) -> None:
        self._append(
            run_id,
            "tool.completed" if tool_result.get("ok") else "tool.failed",
            tool_name,
            input_preview,
            "completed" if tool_result.get("ok") else "failed",
            approved=approved,
            output_preview=tool_result,
        )

    def agent_tool_call(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
    ) -> None:
        if not run_id:
            return
        self.events.append(
            {
                "run_id": run_id,
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": tool_name,
                    "input_preview": input_preview,
                    "result": tool_result,
                    "approved": approved,
                },
            }
        )

    def _append(
        self,
        run_id: str,
        event_type: str,
        tool_name: str,
        input_preview: Any,
        status: str,
        **extra: Any,
    ) -> None:
        if not run_id:
            return
        self.events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": {
                    "tool": tool_name,
                    "input_preview": input_preview,
                    "status": status,
                    **extra,
                },
            }
        )


class NoopTraceEvents:
    @staticmethod
    def memory_skill_trace_event(
        _tool_name: str,
        _input_preview: Any,
        _tool_result: dict[str, Any],
    ) -> None:
        return None

    @staticmethod
    def artifact_created_payload(
        tool_result: dict[str, Any],
        *,
        run_id: str,
        source_tool: str = "",
    ) -> dict[str, Any]:
        return {"run_id": run_id, "source_tool": source_tool, "path": tool_result.get("path")}


class NoopPendingApprovalBuilder:
    @staticmethod
    def build(
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "approval_id": "approval-1",
            "tool": tool_request.get("tool"),
            "messages": messages,
            "next_iteration": next_iteration,
            "remaining_tool_requests": remaining_tool_requests,
        }


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


def test_custom_api_agent_loop_injects_runtime_prompt_for_existing_messages() -> None:
    budget = FakeBudget()
    calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "帮我读取页面正文"}]

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local/",
            "model": "test-model",
            "api_key": "key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["browser.extract_text"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Follow approval gates.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "final answer"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
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
        "ignored context",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-1",
    )

    assert str(result) == "final answer"
    assert messages[0]["role"] == "system"
    assert "Oha-Yachiyo Agent Runtime" in messages[0]["content"]
    assert "Prefer native tool_calls" in messages[0]["content"]
    assert "{\"action\":\"tool\"" in messages[0]["content"]
    assert "browser.extract_text" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "帮我读取页面正文"}
    assert calls[0][0] == messages[0]


def test_custom_api_agent_loop_merges_runtime_prompt_with_existing_system_message() -> None:
    budget = FakeBudget()
    calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [
        {
            "role": "system",
            "content": "[Oha-Yachiyo 群组派活]\noha.group_dispatch",
        },
        {"role": "user", "content": "请安排 Coding"},
    ]

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local/",
            "model": "test-model",
            "api_key": "key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.read"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Follow approval gates.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "final answer"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
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
        "ignored context",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-1",
    )

    assert str(result) == "final answer"
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Oha-Yachiyo Agent Runtime" in messages[0]["content"]
    assert "oha.group_dispatch" in messages[0]["content"]
    assert calls[0][0] == messages[0]


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
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "existing"}
    assert messages[2] == {"role": "assistant", "content": "need tool"}


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
        "app.open",
        "app.focus",
        "media.apple_music_play",
        "media.apple_music_control",
        "screen.capture",
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "app.status",
        "browser.open_url",
        "browser.current_page",
        "browser.extract_text",
        "browser.screenshot",
        "desktop.reveal_path",
        "desktop.hotkey",
        "desktop.type_text",
        "desktop.click",
    ]

    assert daily_desktop_intent_tool_request("打开 https://example.com/docs", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://example.com/docs"},
    }
    assert daily_desktop_intent_tool_request("打开 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 B站", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.bilibili.com"},
    }
    assert daily_desktop_intent_tool_request("打开小红书", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.xiaohongshu.com"},
    }
    assert daily_desktop_intent_tool_request("打开 ChatGPT", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://chatgpt.com"},
    }
    assert daily_desktop_intent_tool_request("搜一下 Yachiyo desktop agent", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.google.com/search?q=Yachiyo+desktop+agent"},
    }
    assert daily_desktop_intent_tool_request("搜索 超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {
            "url": "https://www.google.com/search?q=%E8%B6%85%E6%97%B6%E7%A9%BA%E8%BE%89%E5%A4%9C%E5%A7%AC"
        },
    }
    assert daily_desktop_intent_tool_request("当前网页是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("读取当前网页正文", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("读一下这个网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("截取当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("切换到 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("能否帮我播放 Apple Music?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("打开 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("打开浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("打开 Cursor", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Cursor"},
    }
    assert daily_desktop_intent_tool_request("运行 Cursor", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Cursor"},
    }
    assert daily_desktop_intent_tool_request("打开 VS Code", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Visual Studio Code"},
    }
    assert daily_desktop_intent_tool_request("打开设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "System Settings"},
    }
    assert daily_desktop_intent_tool_request("打开邮箱", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Mail"},
    }
    assert daily_desktop_intent_tool_request("打开地图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Maps"},
    }
    assert daily_desktop_intent_tool_request("打开照片", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Photos"},
    }
    assert daily_desktop_intent_tool_request("打开预览", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Preview"},
    }
    assert daily_desktop_intent_tool_request("打开计算器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Calculator"},
    }
    assert daily_desktop_intent_tool_request("打开应用商店", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "App Store"},
    }
    assert daily_desktop_intent_tool_request("打开活动监视器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Activity Monitor"},
    }
    assert daily_desktop_intent_tool_request("打开设置的隐私与安全性", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "设置的隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开屏幕录制权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "屏幕录制权限"},
    }
    assert daily_desktop_intent_tool_request("打开辅助功能权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "辅助功能权限"},
    }
    assert daily_desktop_intent_tool_request("打开桌面权限设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开需要的权限设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("检查桌面权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能控制桌面？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("check desktop permissions", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示 ~/Downloads/report.pdf", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads/report.pdf"},
    }
    assert daily_desktop_intent_tool_request("打开 ~/Downloads/report.pdf", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads/report.pdf"},
    }
    assert daily_desktop_intent_tool_request("在访达中显示下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示 ~/Downloads/测试文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads/测试文件夹"},
    }
    assert daily_desktop_intent_tool_request("打开下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "下载文件夹"},
    }
    assert daily_desktop_intent_tool_request("打开下载", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "下载"},
    }
    assert daily_desktop_intent_tool_request("打开 Arc 浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Arc"},
    }
    assert daily_desktop_intent_tool_request("播放音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("来点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("放首歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("暂停音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    assert daily_desktop_intent_tool_request("下一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("上一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "previous"},
    }
    assert daily_desktop_intent_tool_request("播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("在 Apple Music 播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("播放 Music For a Sushi Restaurant", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Music For a Sushi Restaurant"},
    }
    assert daily_desktop_intent_tool_request("play Space Oddity in Apple Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Space Oddity"},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 播放超时空辉夜姬", ["app.open"]) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("播放 Apple Music", ["media.apple_music_control"]) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("能否帮我播放apple Music?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("截个图看看", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("帮我看看现在屏幕", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("当前窗口是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在开了哪些应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列出正在运行的应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("what apps are running", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列出窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Chrome 有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("show Slack windows", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Chrome 开着吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Music 在运行吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("is Slack running", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("检查一下 Slack 是否在运行", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("按 Command+L", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "l", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("按 Ctrl Shift P", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "p", "modifiers": ["control", "shift"]},
    }
    assert daily_desktop_intent_tool_request("输入 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("点击 120, 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click",
        "input": {"x": 120, "y": 240, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("双击 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click",
        "input": {"x": 120, "y": 240, "click_count": 2},
    }
    assert daily_desktop_intent_tool_request("怎么截图？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么打开 github.com？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么搜索 GitHub？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要真的播放超时空辉夜姬，只告诉我怎么做", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要真的点击 120, 240，只告诉我怎么做", allowed_tools) is None
    assert daily_desktop_intent_tool_request("请运行一个会失败的命令", allowed_tools) is None
    assert daily_desktop_intent_tool_request("查看系统状态", allowed_tools) is None
    assert daily_desktop_intent_candidates("播放超时空辉夜姬")[0] == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_candidates("trigger provider failure") == []
    assert daily_desktop_intent_candidates("Turn the research notes into an implementation plan.") == []
    assert daily_desktop_intent_candidates("为什么不能控制桌面？") == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.permissions",
            "input": {},
        }
    ]
    assert daily_desktop_intent_candidates("怎么截图？") == []
    assert daily_desktop_intent_tool_request("播放 Apple Music", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("播放超时空辉夜姬", ["workspace.read"]) is None
    assert daily_desktop_intent_tool_request("打开 github.com", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开 GitHub", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开小红书", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开 ~/Downloads/report.pdf", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("列出正在运行的应用", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("现在开了哪些应用", ["desktop.active_window"]) is None
    assert daily_desktop_intent_tool_request("当前窗口是什么", ["desktop.windows"]) is None
    assert daily_desktop_intent_tool_request("Chrome 开着吗", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("ChatGPT 打开了吗", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("检查一下 Slack 是否在运行", ["browser.open_url"]) is None
    assert daily_desktop_intent_tool_request("检查桌面权限", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("搜索 open hanako", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("按 Command+L", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("放一下", allowed_tools) is None
    assert daily_desktop_intent_tool_request("播放一下", allowed_tools) is None
    assert daily_desktop_intent_tool_request("点击发送按钮", allowed_tools) is None


def test_custom_api_agent_loop_executes_desktop_intent_with_real_tool_runner_before_model() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    run_events: list[dict[str, Any]] = []
    broker = RecordingDesktopBroker(order)
    projection = RuntimeToolLoopProjectionBuilder()
    tool_call_events = RecordingToolCallEvents(run_events)
    trace_events = NoopTraceEvents()
    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        allows_tool=PolicyGate.allows_tool,
    )
    runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        user_goal_from_messages=lambda messages: str(messages[1].get("content") or ""),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        tool_loop_projection=projection,
        pending_approval_builder=NoopPendingApprovalBuilder(),
        call_agent_tool=executor.execute,
    )
    operations = RuntimeToolOperations(
        tool_request_runner=runner,
        tool_call_executor=executor,
    )

    def call_model(*_args, **_kwargs):
        raise AssertionError("allowed custom desktop intent should not ask the model to restate permissions")

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["media.apple_music_play"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=operations.run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"agent_id": "agent-music", "name": "Music Agent"},
        "播放超时空辉夜姬",
        broker=broker,
        timeline=timeline,
        artifacts=artifacts,
        run_id="run-real-desktop-intent",
        budget=budget,
    )

    assert str(result) == "已在 Apple Music 播放：超时空辉夜姬。"
    assert order == ["tool"]
    assert broker.calls == [("media.apple_music_play", {"query": "超时空辉夜姬"}, False)]
    assert budget.tool_claims == [("media.apple_music_play", False)]
    assert budget.claims == 0
    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert timeline[1]["detail"] == "media.apple_music_play"
    assert timeline[1]["result"]["ok"] is True
    assert timeline[-1]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"
    assert [event["event_type"] for event in run_events] == [
        "agent.desktop.intent_planned",
        "tool.requested",
        "tool.started",
        "tool.completed",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert run_events[0]["payload"] == {
        "tool": "media.apple_music_play",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {"query": "超时空辉夜姬"},
    }
    assert run_events[-1]["payload"]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"


def test_main_chat_desktop_intent_returns_deterministic_result_without_model() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    run_events: list[dict[str, Any]] = []
    broker = RecordingDesktopBroker(order)
    projection = RuntimeToolLoopProjectionBuilder()
    tool_call_events = RecordingToolCallEvents(run_events)
    trace_events = NoopTraceEvents()
    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        allows_tool=PolicyGate.allows_tool,
    )
    runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        user_goal_from_messages=lambda messages: str(messages[1].get("content") or ""),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        tool_loop_projection=projection,
        pending_approval_builder=NoopPendingApprovalBuilder(),
        call_agent_tool=executor.execute,
    )
    operations = RuntimeToolOperations(
        tool_request_runner=runner,
        tool_call_executor=executor,
    )

    def fail_model(*_args, **_kwargs):
        raise AssertionError("main chat direct desktop intent should not call the model")

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["media.apple_music_play"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=fail_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=operations.run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
        "播放超时空辉夜姬",
        broker=broker,
        timeline=timeline,
        artifacts=artifacts,
        run_id="run-main-chat-desktop-intent",
        budget=budget,
    )

    assert str(result) == "已在 Apple Music 播放：超时空辉夜姬。"
    assert order == ["tool"]
    assert budget.tool_claims == [("media.apple_music_play", False)]
    assert budget.claims == 0
    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert timeline[-1]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"
    assert [event["event_type"] for event in run_events] == [
        "agent.desktop.intent_planned",
        "tool.requested",
        "tool.started",
        "tool.completed",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert run_events[-1]["payload"]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"


def test_main_chat_browser_search_intent_returns_deterministic_result_without_model() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    run_events: list[dict[str, Any]] = []
    broker = RecordingDesktopBroker(order)
    projection = RuntimeToolLoopProjectionBuilder()
    tool_call_events = RecordingToolCallEvents(run_events)
    trace_events = NoopTraceEvents()
    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        allows_tool=PolicyGate.allows_tool,
    )
    runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        user_goal_from_messages=lambda messages: str(messages[1].get("content") or ""),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
        tool_loop_projection=projection,
        pending_approval_builder=NoopPendingApprovalBuilder(),
        call_agent_tool=executor.execute,
    )
    operations = RuntimeToolOperations(
        tool_request_runner=runner,
        tool_call_executor=executor,
    )

    def fail_model(*_args, **_kwargs):
        raise AssertionError("main chat browser search intent should not call the model")

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["browser.open_url"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=fail_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=operations.run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
        "搜一下 Yachiyo desktop agent",
        broker=broker,
        timeline=timeline,
        artifacts=artifacts,
        run_id="run-main-chat-browser-search",
        budget=budget,
    )

    url = "https://www.google.com/search?q=Yachiyo+desktop+agent"
    assert str(result) == f"已打开网页：{url}。"
    assert order == ["tool"]
    assert broker.calls == [("browser.open_url", {"url": url}, False)]
    assert budget.tool_claims == [("browser.open_url", False)]
    assert budget.claims == 0
    assert timeline[0] == {
        "event": "agent.desktop.intent_planned",
        "detail": "browser.open_url",
        "tool": "browser.open_url",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {"url": url},
    }
    assert timeline[-1]["event"] == "agent.desktop.intent_completed"
    assert timeline[-1]["summary"] == f"已打开网页：{url}。"
    assert run_events[-1]["event_type"] == "agent.desktop.intent_completed"
    assert run_events[-1]["payload"]["summary"] == f"已打开网页：{url}。"


def test_main_chat_desktop_intent_permission_failure_includes_recovery_hint() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_play",
        {"query": "超时空辉夜姬"},
        {
            "ok": False,
            "error": "Not authorized to send Apple events to Music.",
            "permission_error": True,
            "permission_targets": ["music_app", "automation"],
            "recovery_hints": [
                "Open Music.app once, confirm the track exists in the local library.",
                "Grant Automation permission in System Settings.",
            ],
        },
    )

    assert "桌面操作未完成：Not authorized to send Apple events to Music." in result
    assert "缺少权限：music_app, automation" in result
    assert "你可以这样处理：" in result
    assert "Open Music.app once" in result
    assert "Grant Automation permission" in result


def test_main_chat_desktop_intent_summarizes_apple_music_control() -> None:
    pause = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_control",
        {"action": "pause"},
        {
            "ok": True,
            "summary": "Apple Music pause executed",
            "data": {"control": "pause", "player_state": "paused"},
        },
    )
    next_track = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_control",
        {"action": "next"},
        {
            "ok": True,
            "summary": "Apple Music next executed",
            "data": {
                "control": "next",
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        },
    )

    assert pause == "已暂停 Apple Music。"
    assert next_track == "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。"


def test_main_chat_desktop_intent_summarizes_finder_reveal() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.reveal_path",
        {"path": "~/Downloads/report.pdf"},
        {
            "ok": True,
            "summary": "Revealed report.pdf in Finder",
            "data": {"open_target": "finder_reveal"},
        },
    )

    assert result == "已在 Finder 中显示：~/Downloads/report.pdf。"


def test_main_chat_desktop_intent_summarizes_running_apps() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.running_apps",
        {},
        {
            "ok": True,
            "summary": "Running apps: Finder, Google Chrome, Music",
            "data": {
                "apps": [
                    {"name": "Finder", "pid": 101, "frontmost": False},
                    {"name": "Google Chrome", "pid": 202, "frontmost": True},
                    {"name": "Music", "pid": 303, "frontmost": False},
                ],
                "frontmost": "Google Chrome",
            },
        },
    )

    assert result == "正在运行的应用：Finder, Google Chrome, Music。前台是 Google Chrome。"


def test_main_chat_desktop_intent_summarizes_windows() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.windows",
        {"app_name": "Google Chrome"},
        {
            "ok": True,
            "summary": "Open windows: Google Chrome: ChatGPT",
            "data": {
                "app_name": "Google Chrome",
                "windows": [
                    {
                        "app_name": "Google Chrome",
                        "pid": 202,
                        "index": 1,
                        "frontmost": True,
                        "title": "ChatGPT",
                    }
                ],
                "count": 1,
            },
        },
    )

    assert result == "当前窗口：Google Chrome: ChatGPT。"


def test_main_chat_desktop_intent_summarizes_app_status() -> None:
    running = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.status",
        {"app_name": "Google Chrome"},
        {
            "ok": True,
            "summary": "Google Chrome is running",
            "data": {"app_name": "Google Chrome", "running": True},
        },
    )
    stopped = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.status",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Slack is not running",
            "data": {"app_name": "Slack", "running": False},
        },
    )

    assert running == "Google Chrome 当前正在运行。"
    assert stopped == "Slack 当前没有运行。"


def test_main_chat_desktop_intent_summarizes_desktop_permissions() -> None:
    ready = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.permissions",
        {},
        {
            "ok": True,
            "summary": "Desktop execution permissions are ready.",
            "permission_targets": [],
            "affected_tools": [],
        },
    )
    missing = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.permissions",
        {},
        {
            "ok": True,
            "summary": "Missing desktop permissions",
            "permission_targets": ["screen_recording", "automation"],
            "affected_tools": ["screen.capture", "media.apple_music_play"],
            "recovery_actions": [
                {
                    "label": "打开屏幕录制权限",
                    "tool": "app.open",
                    "input": {"app_name": "屏幕录制权限"},
                },
                {
                    "label": "打开自动化权限",
                    "tool": "app.open",
                    "input": {"app_name": "自动化权限"},
                },
            ],
        },
    )

    assert ready == "桌面执行权限已就绪。"
    assert missing == (
        "桌面执行权限还缺少：screen_recording, automation。"
        "受影响工具：screen.capture, media.apple_music_play。"
        "可直接打开：打开屏幕录制权限、打开自动化权限。"
    )


def test_main_chat_desktop_intent_summarizes_app_and_browser_execution_details() -> None:
    app_unverified = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open",
        {"app_name": "Google Chrome"},
        {
            "ok": True,
            "summary": "Opened Google Chrome",
            "data": {"app_name": "Google Chrome", "launch_verified": False},
        },
    )
    browser_fallback = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.open_url",
        {"url": "https://example.com"},
        {
            "ok": True,
            "summary": "Opened URL in the system browser: https://example.com",
            "data": {"url": "https://example.com"},
            "fallback_used": True,
            "fallback": "system_browser",
        },
    )
    app_not_found = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open",
        {"app_name": "Missing App"},
        {
            "ok": False,
            "error": "Application not found.",
            "error_code": "app_not_found",
            "recovery_hints": ["确认应用已安装，或换用精确应用名。"],
        },
    )

    assert app_unverified == "已向 macOS 发送打开 Google Chrome 的请求，但未能确认它已启动。"
    assert browser_fallback == "已用系统浏览器打开网页：https://example.com。"
    assert app_not_found == "桌面操作未完成：Application not found. 你可以这样处理：确认应用已安装，或换用精确应用名。"


def test_custom_api_agent_loop_preplans_main_chat_message_desktop_intent() -> None:
    budget = FakeBudget()
    order: list[str] = []
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "能否帮我播放 Apple Music?"}]

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
                "content": 'Tool result for app.open: {"ok": true, "data": {"app_name": "Music"}}',
            }
        )

    def call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        order.append("model")
        assert "Tool result for app.open" in model_messages[-1]["content"]
        return {"role": "assistant", "content": "已打开 Music。"}

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "app.open",
                    "media.apple_music_play",
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
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-main-chat",
    )

    assert str(result) == "已打开 Music。"
    assert order == ["tool", "model"]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Music"},
        }
    ]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-main-chat"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert timeline[0] == {
        "event": "agent.desktop.intent_planned",
        "detail": "app.open",
        "tool": "app.open",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {"app_name": "Music"},
    }


def test_custom_api_agent_loop_records_unavailable_desktop_intent_when_tool_is_missing() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []

    def run_tool_requests(*_args, **_kwargs):
        raise AssertionError("unavailable desktop intent must not bypass allowed_tools")

    def call_model(*_args, **_kwargs):
        raise AssertionError("unavailable desktop intent should return a runtime policy summary")

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.read"]}
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
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": payload,
            }
        ),
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "播放超时空辉夜姬",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-missing-tool",
    )

    assert str(result) == (
        "这个 Agent 当前没有开启 media.apple_music_play，所以不能直接执行「播放 Apple Music」。"
        "请改用八千代日常入口，或在 Agent Studio 给该 Agent 开启桌面执行能力。"
        "当前允许的工具：workspace.read。"
    )
    assert order == []
    assert timeline[0] == {
        "event": "agent.desktop.intent_unavailable",
        "detail": "media.apple_music_play",
        "tool": "media.apple_music_play",
        "status": "unavailable",
        "source": "daily_desktop_intent",
        "reason": "tool_not_allowed",
        "blocked_by": "agent_tool_policy",
        "blocked_summary": (
            "这个 Agent 当前没有开启 media.apple_music_play，所以不能直接执行「播放 Apple Music」。"
            "请改用八千代日常入口，或在 Agent Studio 给该 Agent 开启桌面执行能力。"
            "当前允许的工具：workspace.read。"
        ),
        "recovery_actions": [
            "改用八千代日常入口执行这个桌面指令。",
            "在 Agent Studio 为该 Agent 开启桌面执行能力。",
        ],
        "input_preview": {"query": "超时空辉夜姬"},
        "allowed_tools": ["workspace.read"],
    }
    assert appended_events == [
        {
            "run_id": "run-missing-tool",
            "event_type": "agent.desktop.intent_unavailable",
            "payload": {
                "tool": "media.apple_music_play",
                "status": "unavailable",
                "source": "daily_desktop_intent",
                "reason": "tool_not_allowed",
                "blocked_by": "agent_tool_policy",
                "blocked_summary": (
                    "这个 Agent 当前没有开启 media.apple_music_play，所以不能直接执行「播放 Apple Music」。"
                    "请改用八千代日常入口，或在 Agent Studio 给该 Agent 开启桌面执行能力。"
                    "当前允许的工具：workspace.read。"
                ),
                "recovery_actions": [
                    "改用八千代日常入口执行这个桌面指令。",
                    "在 Agent Studio 为该 Agent 开启桌面执行能力。",
                ],
                "input_preview": {"query": "超时空辉夜姬"},
                "allowed_tools": ["workspace.read"],
            },
        }
    ]


def test_custom_api_agent_loop_preplans_foreground_hotkey_without_bypassing_runner() -> None:
    budget = FakeBudget()
    order: list[str] = []
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "按 Command+L"}]

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
                    'Tool result for desktop.hotkey: {"ok": true, '
                    '"data": {"key": "l", "modifiers": ["command"]}}'
                ),
            }
        )

    def call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        order.append("model")
        assert "Tool result for desktop.hotkey" in model_messages[-1]["content"]
        return {"role": "assistant", "content": "已发送 Command+L。"}

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "desktop.hotkey",
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
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-hotkey",
    )

    assert str(result) == "已发送 Command+L。"
    assert order == ["tool", "model"]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        }
    ]
    assert tool_runs[0]["allowed_tools"] == ["desktop.hotkey"]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-hotkey"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert timeline[0] == {
        "event": "agent.desktop.intent_planned",
        "detail": "desktop.hotkey",
        "tool": "desktop.hotkey",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {"key": "l", "modifiers": ["command"]},
    }


def test_main_chat_daily_hotkey_intent_returns_deterministic_result_without_model() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "按 Command+L"}]

    def run_tool_requests(
        tool_requests,
        _allowed_tools,
        _broker,
        messages_arg,
        timeline_arg,
        _artifacts,
        **_kwargs,
    ):
        order.append("tool")
        request = tool_requests[0]
        result = {
            "ok": True,
            "action": "desktop.hotkey",
            "data": {"key": "l", "modifiers": ["command"]},
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                "desktop.hotkey",
                input_preview=request["input"],
                result=result,
            )
        )
        messages_arg.append(
            {"role": "user", "content": f"Tool result for desktop.hotkey: {result}"}
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["desktop.hotkey"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("successful daily hotkey intent should not call the model")
        ),
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
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-hotkey-direct",
    )

    assert str(result) == "已发送快捷键：Command+L。"
    assert order == ["tool"]
    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert timeline[-1]["summary"] == "已发送快捷键：Command+L。"
    assert appended_events[-1] == {
        "run_id": "run-hotkey-direct",
        "event_type": "agent.desktop.intent_completed",
        "payload": {
            "tool": "desktop.hotkey",
            "source": "daily_desktop_intent",
            "input_preview": {"key": "l", "modifiers": ["command"]},
            "result": {
                "ok": True,
                "action": "desktop.hotkey",
                "data": {"key": "l", "modifiers": ["command"]},
            },
            "summary": "已发送快捷键：Command+L。",
        },
    }


def test_main_chat_daily_hotkey_resume_summarizes_approved_tool_without_replanning() -> None:
    budget = FakeBudget()
    timeline = [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "desktop.hotkey",
            "tool": "desktop.hotkey",
            "status": "planned",
            "source": "daily_desktop_intent",
            "planning_reason": "clear_daily_desktop_intent",
            "input_preview": {"key": "l", "modifiers": ["command"]},
        },
        {
            "event": "agent.desktop.intent_approval_required",
            "detail": "desktop.hotkey",
            "tool": "desktop.hotkey",
            "status": "approval_required",
            "source": "daily_desktop_intent",
            "reason": "tool_policy_requires_approval",
            "input_preview": {"key": "l", "modifiers": ["command"]},
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.hotkey",
            "input_preview": {"key": "l", "modifiers": ["command"]},
            "result": {
                "ok": True,
                "action": "desktop.hotkey",
                "data": {"key": "l", "modifiers": ["command"]},
            },
        },
    ]
    appended_events: list[dict[str, Any]] = []

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["desktop.hotkey"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("approved daily hotkey resume should not call the model")
        ),
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("approved daily hotkey resume should not re-run the planner")
        ),
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
        "",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=[
            {"role": "user", "content": "按 Command+L"},
            {"role": "user", "content": "Tool result for desktop.hotkey: ok"},
        ],
        start_iteration=0,
        run_id="run-hotkey-resume",
        budget=budget,
    )

    assert str(result) == "已发送快捷键：Command+L。"
    assert timeline[-1]["event"] == "agent.desktop.intent_completed"
    assert appended_events[-1]["event_type"] == "agent.desktop.intent_completed"


def test_custom_api_agent_loop_records_desktop_intent_approval_required_before_pause() -> None:
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "按 Command+L"}]

    def run_tool_requests(*_args, **_kwargs):
        raise AgentApprovalRequired(
            {
                "approval_id": "approval-hotkey",
                "tool": "desktop.hotkey",
                "input_preview": {"key": "l", "modifiers": ["command"]},
                "risk_level": "medium",
                "policy_reason": "前台快捷键需要确认。",
            }
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["desktop.hotkey"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("approval-required desktop intent should not call model")
        ),
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
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    try:
        loop.run(
            {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
            "ignored context",
            broker={"broker": True},
            timeline=timeline,
            artifacts=[],
            messages=messages,
            run_id="run-hotkey-approval",
        )
    except AgentApprovalRequired as exc:
        assert exc.pending_approval["approval_id"] == "approval-hotkey"
    else:
        raise AssertionError("expected AgentApprovalRequired")

    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.desktop.intent_approval_required",
    ]
    assert timeline[-1] == {
        "event": "agent.desktop.intent_approval_required",
        "detail": "desktop.hotkey",
        "tool": "desktop.hotkey",
        "status": "approval_required",
        "source": "daily_desktop_intent",
        "reason": "tool_policy_requires_approval",
        "input_preview": {"key": "l", "modifiers": ["command"]},
        "approval_id": "approval-hotkey",
        "risk_level": "medium",
        "policy_reason": "前台快捷键需要确认。",
    }
    assert appended_events[-1] == {
        "run_id": "run-hotkey-approval",
        "event_type": "agent.desktop.intent_approval_required",
        "payload": {
            "tool": "desktop.hotkey",
            "status": "approval_required",
            "source": "daily_desktop_intent",
            "reason": "tool_policy_requires_approval",
            "input_preview": {"key": "l", "modifiers": ["command"]},
            "approval_id": "approval-hotkey",
            "risk_level": "medium",
            "policy_reason": "前台快捷键需要确认。",
        },
    }


def test_custom_api_agent_loop_preplans_clear_daily_desktop_intent_before_text_response() -> None:
    budget = FakeBudget()
    order: list[str] = []
    tool_runs: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []

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
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": payload,
            }
        ),
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
        "tool": "media.apple_music_play",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {"query": "超时空辉夜姬"},
    }
    assert appended_events == [
        {
            "run_id": "run-music",
            "event_type": "agent.desktop.intent_planned",
            "payload": {
                "tool": "media.apple_music_play",
                "status": "planned",
                "source": "daily_desktop_intent",
                "planning_reason": "clear_daily_desktop_intent",
                "input_preview": {"query": "超时空辉夜姬"},
            },
        }
    ]


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
        assert getattr(service.custom_api_agent_loop._append_run_event, "__self__", None) is service
        assert getattr(service.custom_api_agent_loop._run_budget, "__self__", None) is not service
        assert getattr(service.custom_api_agent_loop._check_context_budget, "__self__", None) is not service
        assert getattr(service.custom_api_agent_loop._limit_model_output, "__self__", None) is not service

        service.runtime_limits = RunBudgetLimits(max_model_output_chars=5)
        limited, truncated = service.custom_api_agent_loop._limit_model_output("abcdefghi")
        assert truncated is True
        assert limited == "abcde"
    finally:
        service.close()
