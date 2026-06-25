"""Tests for custom API Agent loop split out of the legacy runtime."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.config import MAIN_CHAT_AGENT_ID
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_entrypoint_tool_requests,
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
    daily_desktop_intent_tool_requests,
    daily_desktop_metadata_tool_request,
    daily_desktop_recovery_prompt,
)
from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_requests import normalize_tool_name
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES, PolicyGate
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


class PermissionPreflightDesktopBroker(RecordingDesktopBroker):
    def desktop_permission_preflight(self) -> dict[str, Any]:
        self.order.append("preflight")
        return {
            "ok": True,
            "action": "desktop.permission_preflight",
            "permission_error": True,
            "permission_targets": ["automation"],
            "affected_tools": ["media.apple_music_play"],
            "recovery_hints": ["Grant Automation permission."],
            "recovery_actions": [
                {
                    "label": "打开自动化权限",
                    "tool": "system.settings_open",
                    "input": {"target": "自动化权限"},
                    "permission_target": "automation",
                    "risk_level": "low",
                }
            ],
            "diagnostic_route": "/yachiyo/readiness",
            "data": {
                "ready": False,
                "permission_targets": ["automation"],
                "affected_tools": ["media.apple_music_play"],
            },
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


def test_daily_desktop_intent_planner_handles_postposed_open_observe_and_finder_selection() -> None:
    allowed_tools = list(DAILY_DESKTOP_TOOL_NAMES)

    assert daily_desktop_intent_tool_requests(
        "把微信打开然后看看有没有未读",
        allowed_tools,
    ) == [
        {"protocol": "json_fallback", "tool": "app.open", "input": {"app_name": "WeChat"}},
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "打开微信读一下当前聊天",
        allowed_tools,
    ) == [
        {"protocol": "json_fallback", "tool": "app.open", "input": {"app_name": "WeChat"}},
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_request("把日历启动起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Calendar"},
    }
    assert daily_desktop_intent_tool_request("启动Chrome起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 选择的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "finder_selection"},
    }
    assert daily_desktop_intent_tool_request("打开Finder然后按空格", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_quick_look"},
    }
    assert daily_desktop_intent_tool_request("Finder按空格", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_quick_look"},
    }
    assert daily_desktop_intent_tool_request("Slack按空格", allowed_tools) != {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "finder_quick_look"},
    }
    assert daily_desktop_intent_tool_request("打开系统活动监视器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Activity Monitor"},
    }
    assert daily_desktop_intent_tool_request("把Chrome打开然后新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("把Chrome启动起来然后新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("把Chrome启动起来刷新一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("启动Chrome起来刷新一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("把Chrome打开然后刷新", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("把Chrome打开然后后退", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "browser_back"},
    }

def test_daily_desktop_intent_planner_routes_finder_find_language() -> None:
    allowed_tools = [
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.click_ui_element",
    ]

    assert daily_desktop_intent_tool_requests("打开 Finder 找下载文件", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "下载文件"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Finder 找下载文件", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "下载文件"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Finder look for Downloads", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Downloads"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Finder 查找 Downloads 然后打开第一个", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Downloads"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 2},
        },
    ]
    assert daily_desktop_intent_tool_requests("Finder 搜索 report 然后点击第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "report"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 1},
        },
    ]


def test_daily_desktop_intent_planner_routes_spotlight_search_language() -> None:
    allowed_tools = list(DAILY_DESKTOP_TOOL_NAMES)
    expected = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "spotlight_search"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]

    for prompt in (
        "Spotlight 搜索 yachiyo",
        "打开 Spotlight 搜索 yachiyo",
        "用 Spotlight 搜索 yachiyo",
        "聚焦搜索 yachiyo",
        "打开聚焦搜索 yachiyo",
        "spotlight search yachiyo",
        "open Spotlight and search yachiyo",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == expected

    assert daily_desktop_intent_tool_requests("打开聚焦搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "spotlight_search"},
        }
    ]
    assert daily_desktop_intent_tool_requests(
        "Spotlight 搜索 yachiyo",
        ["desktop.safe_shortcut"],
    ) == []


def test_daily_desktop_intent_planner_routes_browser_extract_text_language() -> None:
    allowed_tools = [
        "app.focus",
        "browser.extract_text",
    ]

    for prompt in ("read current webpage", "extract current page text"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
        }

    assert daily_desktop_intent_tool_requests("focus Chrome and extract page text", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
        },
    ]


def test_daily_desktop_intent_planner_routes_app_prefix_click_language() -> None:
    allowed_tools = [
        "app.focus",
        "browser.click",
        "app.focus_and_click_ui_element",
    ]

    assert daily_desktop_intent_tool_requests("Chrome 点登录", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "text=登录", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("Slack 点搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("微信点搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]


def test_daily_desktop_intent_planner_routes_app_search_field_typing_language() -> None:
    allowed_tools = [
        "app.open",
        "app.focus",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.hotkey",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]

    assert daily_desktop_intent_tool_requests("在微信搜索文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信搜索文件传输助手并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信点击搜索框输入文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
    ]


def test_daily_desktop_intent_planner_routes_app_scoped_submit_language() -> None:
    allowed_tools = [
        "app.open",
        "app.focus",
        "desktop.submit_foreground",
    ]

    assert daily_desktop_intent_tool_requests("打开微信发送当前消息", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信按回车发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信提交当前内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "submit"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome press return to send", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]


def test_daily_desktop_intent_planner_maps_clear_chat_commands_only() -> None:
    allowed_tools = [
        "app.open",
        "app.focus",
        "app.focus_window",
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "media.apple_music_play",
        "media.apple_music_status",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "system.settings_open",
        "system.volume",
        "system.brightness",
        "system.display_sleep",
        "system.screen_saver_start",
        "clipboard.write",
        "clipboard.read",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
        "screen.capture",
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "desktop.ui_elements",
        "app.status",
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.current_page",
        "browser.click",
        "browser.extract_text",
        "browser.screenshot",
        "browser.type_text",
        "desktop.reveal_path",
        "desktop.open_path",
        "desktop.hide_app",
        "desktop.show_all_apps",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.search_submit",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type_text",
        "desktop.click",
        "terminal.run",
    ]
    today_1500 = f"{date.today().isoformat()}T15:00"
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_1000 = f"{tomorrow.isoformat()}T10:00"
    tomorrow_1100 = f"{tomorrow.isoformat()}T11:00"
    tomorrow_1500 = f"{tomorrow.isoformat()}T15:00"
    tomorrow_1600 = f"{tomorrow.isoformat()}T16:00"

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
    assert daily_desktop_intent_tool_request("打开网页 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 127.0.0.1:5173", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "http://127.0.0.1:5173"},
    }
    assert daily_desktop_intent_tool_request("打开本地 127.0.0.1:5173", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "http://127.0.0.1:5173"},
    }
    assert daily_desktop_intent_tool_request("open 192.168.1.10:8000/status", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "http://192.168.1.10:8000/status"},
    }
    assert daily_desktop_intent_tool_request("github.com 打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 首页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("上 GitHub", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("把 GitHub 打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 B站", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.bilibili.com"},
    }
    assert daily_desktop_intent_tool_request("打开 B 站首页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.bilibili.com"},
    }
    assert daily_desktop_intent_tool_request("上 B 站", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.bilibili.com"},
    }
    assert daily_desktop_intent_tool_request("打开小红书", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.xiaohongshu.com"},
    }
    assert daily_desktop_intent_tool_request("打开推特", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://x.com"},
    }
    assert daily_desktop_intent_tool_request("打开推特首页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://x.com"},
    }
    assert daily_desktop_intent_tool_request("打开贴吧", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://tieba.baidu.com"},
    }
    assert daily_desktop_intent_tool_request("打开 ChatGPT", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://chatgpt.com"},
    }
    assert daily_desktop_intent_tool_request("用浏览器打开 ChatGPT", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://chatgpt.com"},
    }
    assert daily_desktop_intent_tool_request("打开 ChatGPT 客户端", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "ChatGPT"},
    }
    assert daily_desktop_intent_tool_request("打开 Claude 桌面版", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Claude"},
    }
    assert daily_desktop_intent_tool_request("打开飞书客户端", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "飞书"},
    }
    assert daily_desktop_intent_tool_request("启动企业微信客户端", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "WeCom"},
    }
    assert daily_desktop_intent_tool_request("打开短信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Messages"},
    }
    assert daily_desktop_intent_tool_request("微信帮我打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("把 Finder 拉起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Finder"},
    }
    assert daily_desktop_intent_tool_request("拉起来 Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Finder"},
    }
    assert daily_desktop_intent_tool_request("open WeChat for me", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("可以帮我打开 GitHub 吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("帮我打开 GitHub 官网", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开浏览器并访问 GitHub", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("what page am I on?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前网页是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_requests("把当前网址放到剪贴板", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("把当前链接复制给我", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_request("read this page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("summarize current page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("summarize current webpage", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("读当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("总结当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("当前网页讲了什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("screenshot this page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("screenshot current webpage", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("what app am I using?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("bring Chrome to front", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 并读一下页面", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 看看内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 github.com 读一下内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 并概括内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("open github.com and summarize", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("打开 https://example.com/docs 并读一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://example.com/docs"},
    }
    assert daily_desktop_intent_tool_request("打开网页并读一下 example.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://example.com"},
    }
    assert daily_desktop_intent_tool_request("打开网页并总结 https://example.com/docs", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://example.com/docs"},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("open github.com and read the page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("summarize https://example.com after opening it", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://example.com"},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 并截个图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://github.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 访问 github.com 并截图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://github.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 截图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://github.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("open github.com and take a screenshot", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://github.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("打开网页并截图 example.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://example.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("screenshot https://example.com after opening it", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://example.com",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 并读一下页面", ["browser.open_url"]) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("看看当前网页内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("这是哪个网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 GitHub 并读一下页面", ["browser.extract_text"]) is None
    assert daily_desktop_intent_tool_request("打开 Chrome 并访问 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 访问 github.com 并读一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("浏览器打开 GitHub 然后读一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("open browser and visit github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request(
        "open Chrome and type github.com into address bar",
        allowed_tools,
    ) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request(
        "open Chrome and type github.com and press enter",
        allowed_tools,
    ) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开浏览器并访问 GitHub", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("用浏览器打开 Apple Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://music.apple.com"},
    }
    assert daily_desktop_intent_tool_request("搜一下 Yachiyo desktop agent", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.google.com/search?q=Yachiyo+desktop+agent"},
    }
    assert daily_desktop_intent_tool_request("查 OpenAI 最新消息", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.google.com/search?q=OpenAI+%E6%9C%80%E6%96%B0%E6%B6%88%E6%81%AF"},
    }
    assert daily_desktop_intent_tool_request("百度一下 八千代 agent", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.baidu.com/s?wd=%E5%85%AB%E5%8D%83%E4%BB%A3+agent"},
    }
    assert daily_desktop_intent_tool_request("百度 open hanako", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.baidu.com/s?wd=open+hanako"},
    }
    assert daily_desktop_intent_tool_request("搜索 超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {
            "url": "https://www.google.com/search?q=%E8%B6%85%E6%97%B6%E7%A9%BA%E8%BE%89%E5%A4%9C%E5%A7%AC"
        },
    }
    assert daily_desktop_intent_tool_request("搜索 oha yachiyo 并读一下结果", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://www.google.com/search?q=oha+yachiyo"},
    }
    assert daily_desktop_intent_tool_request("search oha yachiyo and summarize results", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_extract_text",
        "input": {"url": "https://www.google.com/search?q=oha+yachiyo"},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("用浏览器搜索 oha yachiyo 并截图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://www.google.com/search?q=oha+yachiyo",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_request("google oha yachiyo and screenshot results", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url_and_screenshot",
        "input": {
            "url": "https://www.google.com/search?q=oha+yachiyo",
            "reason": "user asked to capture the browser page after opening a URL",
        },
    }
    assert daily_desktop_intent_tool_requests("打开浏览器搜索天气然后点第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=%E5%A4%A9%E6%B0%94"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 搜索 yachiyo 然后打开第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 新建标签页然后搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "new_tab"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 新建标签页然后搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "new_tab"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Safari 新建标签页然后搜索 apple news", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "new_tab"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=apple+news"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 后退再刷新", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "browser_back"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "refresh"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 搜索 OpenAI 并打开第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("在 Chrome 里搜索 OpenAI 并打开第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 YouTube 搜索 lo fi 并播放", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.youtube.com/results?search_query=lo+fi"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("YouTube 搜索 lo fi 并打开第一个", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.youtube.com/results?search_query=lo+fi"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("YouTube 搜索 lo fi", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.youtube.com/results?search_query=lo+fi"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在 B站 搜索 周杰伦 并播放", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://search.bilibili.com/all?keyword=%E5%91%A8%E6%9D%B0%E4%BC%A6"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "打开 YouTube 搜索 lo fi 并播放",
        ["browser.open_url", "media.apple_music_play"],
    ) == []
    assert daily_desktop_intent_tool_requests("在浏览器里搜索 oha yachiyo 然后点第一个", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=oha+yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("百度一下 八千代 agent 然后打开第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.baidu.com/s?wd=%E5%85%AB%E5%8D%83%E4%BB%A3+agent"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "search-result=1", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_request("当前网页是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前标签页是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("看下这个网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.current_page",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("读取当前网页正文", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前网页读一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("读一下这个网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
    }
    assert daily_desktop_intent_tool_requests("打开 Chrome 读取当前页", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.extract_text",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 当前页是什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_request("截取当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("截一下当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("当前网页截一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_request("页面截个图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.screenshot",
        "input": {"reason": "user asked to capture the browser page"},
    }
    assert daily_desktop_intent_tool_requests("切到 Chrome 截图当前页", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.screenshot",
            "input": {"reason": "user asked to capture the browser page"},
        },
    ]
    assert daily_desktop_intent_tool_request("点击当前网页上的登录按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {"selector": "text=登录", "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("打开第一个搜索结果", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {"selector": "search-result=1", "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("点击网页上的 Submit", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {"selector": "text=Submit", "click_count": 1},
    }
    assert daily_desktop_intent_tool_requests("打开 Chrome 点击登录按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "text=登录", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("切到 Chrome 点击登录按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "text=登录", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 点网页上的登录按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.click",
            "input": {"selector": "text=登录", "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_request("点击当前网页 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {
            "selector": "point=120,240",
            "fallback_x": 120,
            "fallback_y": 240,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("点击网页坐标 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {
            "selector": "point=120,240",
            "fallback_x": 120,
            "fallback_y": 240,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("双击当前网页 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {
            "selector": "point=120,240",
            "fallback_x": 120,
            "fallback_y": 240,
            "click_count": 2,
        },
    }
    assert daily_desktop_intent_tool_request("在网页搜索框输入 yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.type_text",
        "input": {
            "selector": (
                'input[type="search"], input[name="q"], textarea[name="q"], '
                'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                'input[aria-label*="search" i], input[placeholder*="search" i]'
            ),
            "text": "yachiyo",
        },
    }
    assert daily_desktop_intent_tool_requests(
        "打开 Chrome 网页搜索框输入 yachiyo 然后搜索",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.type_text",
            "input": {
                "selector": (
                    'input[type="search"], input[name="q"], textarea[name="q"], '
                    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                    'input[aria-label*="search" i], input[placeholder*="search" i]'
                ),
                "text": "yachiyo",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "切到 Safari 在网页搜索框输入 weather",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Safari"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.type_text",
            "input": {
                "selector": (
                    'input[type="search"], input[name="q"], textarea[name="q"], '
                    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                    'input[aria-label*="search" i], input[placeholder*="search" i]'
                ),
                "text": "weather",
            },
        },
    ]
    assert daily_desktop_intent_tool_request("在网页坐标 120 240 输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.type_text",
        "input": {
            "selector": "point=120,240",
            "text": "hello",
            "fallback_x": 120,
            "fallback_y": 240,
        },
    }
    assert daily_desktop_intent_tool_request("输入 hello 到网页坐标 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.type_text",
        "input": {
            "selector": "point=120,240",
            "text": "hello",
            "fallback_x": 120,
            "fallback_y": 240,
        },
    }
    assert daily_desktop_intent_tool_request("填写当前网页的搜索框为 yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.type_text",
        "input": {
            "selector": (
                'input[type="search"], input[name="q"], textarea[name="q"], '
                'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                'input[aria-label*="search" i], input[placeholder*="search" i]'
            ),
            "text": "yachiyo",
        },
    }
    assert daily_desktop_intent_tool_request("在当前网页搜索框输入 yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.type_text",
        "input": {
            "selector": (
                'input[type="search"], input[name="q"], textarea[name="q"], '
                'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                'input[aria-label*="search" i], input[placeholder*="search" i]'
            ),
            "text": "yachiyo",
        },
    }
    assert daily_desktop_intent_tool_requests("在搜索框输入 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("type yachiyo into search field", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "search", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("在搜索框输入 yachiyo 并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开搜索框输入 yachiyo 回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("在搜索框输入 yachiyo 并确认", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("type yachiyo into search field then enter", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_request("在搜索框输入 yachiyo", ["desktop.type_text"]) is None
    assert daily_desktop_intent_tool_request("切换到 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("能不能切到 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("切到微信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("切一下微信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("把 Chrome 切到前台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Slack 切到前台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Chrome 到前台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("微信切过来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("微信切一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("go back to WeChat", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("switch back to WeChat", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 的 general 窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_window",
        "input": {"app_name": "Slack", "title_contains": "general"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack general 窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_window",
        "input": {"app_name": "Slack", "title_contains": "general"},
    }
    assert daily_desktop_intent_tool_request("focus Slack window titled general", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_window",
        "input": {"app_name": "Slack", "title_contains": "general"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 的 general 窗口", ["app.focus"]) is None
    assert daily_desktop_intent_tool_request("打开 Notes 并输入 hello yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "Notes", "text": "hello yachiyo"},
    }
    assert daily_desktop_intent_tool_request("打开 Word 输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "Microsoft Word", "text": "hello"},
    }
    assert daily_desktop_intent_tool_request("open Notes and type hello yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "Notes", "text": "hello yachiyo"},
    }
    assert daily_desktop_intent_tool_request("打开微信发你好", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "WeChat", "text": "你好"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack send hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_type_text",
        "input": {"app_name": "Slack", "text": "hello"},
    }
    assert daily_desktop_intent_tool_request("open Notes and new note", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("open Notes and make a new note", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("open Calendar and create a new calendar event", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("打开 Notes 并新建笔记", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("打开备忘录新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("打开备忘录新建一条", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("打开提醒事项新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Reminders", "action": "new_reminder"},
    }
    assert daily_desktop_intent_tool_requests("打开提醒事项新建提醒", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开日历新建日程", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("打开日历新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("打开 Word 新建文档", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Microsoft Word", "action": "new_document"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 开新标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并按 Command T", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 并按 Command N", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "new_window"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并按 Command L", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_hotkey",
        "input": {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("打开浏览器新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开 Word 保存文档", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_hotkey",
        "input": {"app_name": "Microsoft Word", "key": "s", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("打开微信发送 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "WeChat", "text": "hello"},
    }
    assert daily_desktop_intent_tool_request("打开 Slack 点搜索", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "搜索",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_requests("打开微信搜文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信给文件传输助手发 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信发消息给张三说你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在微信给张三发你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信给张三说你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信发消息给张三你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信找张三并发送你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信找张三输入你好", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "张三"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "你好"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 找 Alice 并发送 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开信息给 Alice 发 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Messages", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开备忘录新建笔记输入 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("新建一个备忘录写 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("新建备忘录 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("记一下 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("帮我记下 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "新建一个备忘录写 hello",
        ["app.open_and_safe_shortcut", "desktop.safe_type_text"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("新建一个提醒事项 买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开提醒事项添加买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶"},
        },
    ]
    assert daily_desktop_intent_tool_requests("提醒我明天下午三点开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "开会", "due_at": tomorrow_1500},
        },
    ]
    assert daily_desktop_intent_tool_requests("创建明天上午10点开会的提醒", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "开会", "due_at": tomorrow_1000},
        },
    ]
    assert daily_desktop_intent_tool_requests("创建日历事件 明天下午三点开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("创建明天上午10点开会的日程", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1000,
                "end_at": tomorrow_1100,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("把明天上午10点开会加到日历", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1000,
                "end_at": tomorrow_1100,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("明天下午三点日历上加一个开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("日历上加一个明天下午三点开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("明天下午三点创建一个日程开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("明天下午三点安排一个开会", allowed_tools) == []
    assert daily_desktop_intent_tool_requests("打开日历新建日程 明天下午三点开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "calendar.create_event",
            "input": {
                "title": "开会",
                "start_at": tomorrow_1500,
                "end_at": tomorrow_1600,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("新建一条笔记记下 明天十点开会", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "明天十点开会"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开备忘录新建一个笔记写 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开备忘录写 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Word 新建文档输入 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Microsoft Word", "action": "new_document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开浏览器搜索 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开新标签并搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("百度新标签搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.baidu.com/s?wd=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("百度搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.baidu.com/s?wd=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开百度搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.baidu.com/s?wd=OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开 Excel 然后新建表格", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Microsoft Excel", "action": "new_document"},
    }
    assert daily_desktop_intent_tool_request(
        "open Word and create a new document",
        allowed_tools,
    ) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Microsoft Word", "action": "new_document"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并在地址栏输入 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("Chrome 地址栏输入 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("在地址栏输入 github.com", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("在地址栏输入 github.com 并回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("地址栏输入 yachiyo 并回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.google.com/search?q=yachiyo"},
    }
    assert daily_desktop_intent_tool_request(
        "type github.com into address bar then enter",
        allowed_tools,
    ) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("在 Chrome 输入 github.com 再回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并输入 github.com 再回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://github.com"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并在消息框输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_type_into_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "消息",
            "text": "hello",
            "role_filter": "text",
            "limit": 80,
        },
    }
    assert daily_desktop_intent_tool_request("切到 Slack 在消息框输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_type_into_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "消息",
            "text": "hello",
            "role_filter": "text",
            "limit": 80,
        },
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 新建标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 刷新页面", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("Chrome 查找一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "find"},
    }
    assert daily_desktop_intent_tool_request("Chrome 打开搜索", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "find"},
    }
    assert daily_desktop_intent_tool_request("Google Chrome 查找一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "find"},
    }
    assert daily_desktop_intent_tool_request("Slack 查找一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "find"},
    }
    assert daily_desktop_intent_tool_request("Chrome 后退", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("Chrome 后退一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 后退一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("切到 Chrome 后退一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并粘贴", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "paste"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并按 Command F", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "find"},
    }
    assert daily_desktop_intent_tool_request("Slack 粘贴", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "paste"},
    }
    assert daily_desktop_intent_tool_request("Notes 新建笔记", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("Notes 新建一个笔记", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("备忘录新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Notes", "action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("提醒事项新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Reminders", "action": "new_reminder"},
    }
    assert daily_desktop_intent_tool_request("日历新建日程", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("日历新建", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("Calendar new event", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("打开 Notes write hello yachiyo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_type_text",
        "input": {"app_name": "Notes", "text": "hello yachiyo"},
    }
    assert daily_desktop_intent_tool_request("focus Chrome and then new tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并按 Tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_key",
        "input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("Chrome 按 Tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_key",
        "input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("Chrome 切到下一个输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_key",
        "input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("Chrome 下箭头", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_key",
        "input": {"app_name": "Google Chrome", "action": "arrow_down", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并按三次下箭头", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_key",
        "input": {"app_name": "Slack", "action": "arrow_down", "repeat_count": 3},
    }
    assert daily_desktop_intent_tool_request("切到 Chrome 按三次下箭头", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_key",
        "input": {"app_name": "Google Chrome", "action": "arrow_down", "repeat_count": 3},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并向下滚动两页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_scroll",
        "input": {"app_name": "Google Chrome", "direction": "down", "pages": 2},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并上滑", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_scroll",
        "input": {"app_name": "Slack", "direction": "up", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("Chrome 向下滚动一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_scroll",
        "input": {"app_name": "Google Chrome", "direction": "down", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("Google Chrome 上滑一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_scroll",
        "input": {"app_name": "Google Chrome", "direction": "up", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 并点击 120, 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_click",
        "input": {"app_name": "Google Chrome", "x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并点 320 180", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_click",
        "input": {"app_name": "Slack", "x": 320, "y": 180},
    }
    assert daily_desktop_intent_tool_request("Chrome 点击 120, 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_click",
        "input": {"app_name": "Google Chrome", "x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("Google Chrome 单击 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_click",
        "input": {"app_name": "Google Chrome", "x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("Chrome 输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_type_text",
        "input": {"app_name": "Google Chrome", "text": "hello"},
    }
    assert daily_desktop_intent_tool_request("Notes 输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_type_text",
        "input": {"app_name": "Notes", "text": "hello"},
    }
    assert daily_desktop_intent_tool_requests("打开 Chrome 并点击登录按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Google Chrome",
                "target": "登录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_intent_tool_request("切到 Slack 并点击 Send 按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "Send",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("click the Send button in Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "Send",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("press Send in Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "Send",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("微信点击搜索框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "WeChat",
            "target": "搜索",
            "role_filter": "text",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("click the login button in Chrome", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Google Chrome",
            "target": "login",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request(
        "type hello into message field in Slack",
        allowed_tools,
    ) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_type_into_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "message",
            "text": "hello",
            "role_filter": "text",
            "limit": 80,
        },
    }
    assert daily_desktop_intent_tool_requests(
        "fill search field in Chrome with yachiyo",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_request("在 Slack 点击发送按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "发送",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("点击 Slack 发送按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "发送",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        },
    }
    assert daily_desktop_intent_tool_request("在 Slack 消息框输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_type_into_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "消息",
            "text": "hello",
            "role_filter": "text",
            "limit": 80,
        },
    }
    assert daily_desktop_intent_tool_requests("Chrome 搜索框输入 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_request("微信消息框输入 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_type_into_ui_element",
        "input": {
            "app_name": "WeChat",
            "target": "消息",
            "text": "hello",
            "role_filter": "text",
            "limit": 80,
        },
    }
    assert daily_desktop_intent_tool_request("打开 Notes 并输入 hello yachiyo", ["app.open"]) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Notes"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack 并粘贴", ["app.focus"]) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_requests("打开 Notes，输入 hello，再复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "Notes", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Notes 并输入 hello，再复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "Notes", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 并新建标签页，然后粘贴", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "new_tab"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后按 Tab", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后向下滚动两页", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_scroll",
            "input": {"app_name": "Google Chrome", "direction": "down", "pages": 2},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后点击 120, 240", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_click",
            "input": {"app_name": "Google Chrome", "x": 120, "y": 240},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后点击登录按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Google Chrome",
                "target": "登录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 然后点击搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack，然后点击搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Notes，然后按 Command+L，再复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Chrome and press command l", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "open Chrome and type github.com and press enter",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
        },
    ]
    assert daily_desktop_intent_tool_requests("按 Command+L，再输入 github.com，再按回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "github.com"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("按 Command+L，再输入 yachiyo，再按回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "l", "modifiers": ["command"]},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("全选，再复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("选择全部并复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信然后全选再复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信然后全选复制", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("复制当前窗口内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_intent_tool_requests("粘贴到当前窗口", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        }
    ]
    safe_shortcut_cases = (
        ("把这个网页关掉", "close_tab"),
        ("close this tab", "close_tab"),
        ("重新打开刚才关闭的标签页", "reopen_closed_tab"),
        ("刷新一下这个网页", "refresh"),
        ("打开一个新窗口", "new_window"),
        ("新建浏览器窗口", "new_window"),
        ("下一个标签", "next_tab"),
        ("上一个标签", "previous_tab"),
    )
    for prompt, action in safe_shortcut_cases:
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": action},
        }
    assert daily_desktop_intent_tool_requests("输入 hello 到前台", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        }
    ]
    assert daily_desktop_intent_tool_requests("按 Tab，再按下箭头", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "tab", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Finder，然后新建窗口", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "new_window"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Notes，然后搜索 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Finder and search Downloads", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Downloads"},
        },
    ]
    assert daily_desktop_intent_tool_requests("看一下屏幕，然后点击 120 240", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_click",
            "input": {"x": 120, "y": 240},
        },
    ]
    assert daily_desktop_intent_tool_requests("观察一下屏幕", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("屏幕上有什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    for prompt in (
        "拍一下屏幕",
        "看一下我现在的界面",
        "look at my screen",
        "what is on my screen",
        "screenshot my screen",
        "show me the screen",
        "look at the desktop",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            {
                "protocol": "json_fallback",
                "tool": "screen.capture",
                "input": {"reason": "user asked to capture the screen"},
            },
        ]
    assert daily_desktop_intent_tool_requests("你看到什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("当前界面有什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("看看", allowed_tools) == []
    assert daily_desktop_intent_tool_requests("Chrome 观察一下", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 当前界面有什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("看一下 Chrome 当前界面", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 当前界面", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("看一下屏幕，然后向下滚动", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "down", "pages": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信然后截图", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信然后看看屏幕", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("截图然后双击 120 240", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.click",
            "input": {"x": 120, "y": 240, "click_count": 2},
        },
    ]
    assert daily_desktop_intent_tool_requests("看看屏幕，然后输入 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("切到 Slack，然后查找 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_requests("切到 Chrome 后退", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "browser_back"},
        }
    ]
    assert daily_desktop_intent_tool_requests("点搜索框输入 yachiyo 然后搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("点击当前窗口搜索框输入 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Finder，然后搜索下载", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Finder", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "下载"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开浏览器，然后搜索下雨", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=%E4%B8%8B%E9%9B%A8"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后搜索 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=yachiyo"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Notes 并输入 hello，再复制", ["app.open"]) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Notes"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开浏览器并访问 GitHub", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Notes 并输入 再见", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "Notes", "text": "再见"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome，然后在地址栏输入 github.com", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://github.com"},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 并在搜索框输入 yachiyo 并搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "Google Chrome",
                "target": "搜索",
                "text": "yachiyo",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 点击搜索框输入 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 点击搜索栏输入 yachiyo 并搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    assert daily_desktop_intent_tool_requests("打开微信在搜索框输入文件传输助手并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信搜索框输入文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests("微信搜索框输入文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests("微信在搜索框输入文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests(
        "打开微信搜索框输入文件传输助手并回车",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "搜索",
                "text": "文件传输助手",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_requests("在微信搜索文件传输助手", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Apple Music 搜索超时空辉夜姬", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Music", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "超时空辉夜姬"},
        },
    ]
    assert daily_desktop_intent_tool_requests("用 Apple Music 搜索超时空辉夜姬并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Music", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "超时空辉夜姬"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("用浏览器搜索天气", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url",
            "input": {"url": "https://www.google.com/search?q=%E5%A4%A9%E6%B0%94"},
        }
    ]
    assert daily_desktop_intent_tool_requests("微信搜索文件传输助手然后输入 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信搜索文件传输助手然后发送 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信点搜索输入文件传输助手并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "文件传输助手"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 点击搜索框输入 yachiyo", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 搜索框输入 yachiyo 并搜索", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("切到 Slack 并在消息框输入 hello 并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "text": "hello",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信消息框输入 hello 并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "消息",
                "text": "hello",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信输入 hello 并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信发送 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信发送 hello", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "WeChat", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 输入 https://example.com 并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "Google Chrome", "text": "https://example.com"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
        },
    ]
    assert daily_desktop_intent_tool_request("退出 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.quit",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("关闭微信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.quit",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("退出当前应用", ["app.quit"]) is None
    assert daily_desktop_intent_tool_request("关闭当前 app", ["app.quit"]) is None
    assert daily_desktop_intent_tool_requests("关闭微信窗口", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信关闭窗口", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信关闭当前窗口", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome close window", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.close_window",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信关闭窗口", ["desktop.close_window"]) == []
    assert daily_desktop_intent_tool_requests("关闭微信窗口", ["app.quit"]) == []
    assert daily_desktop_intent_tool_request("把 Slack 关掉", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.quit",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("close Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.quit",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("显示 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("把微信调出来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("把 Chrome 叫出来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("把 Slack 显示出来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Slack 显示出来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Chrome 显示一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("打开 Slack 并切到前台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("打开微信到前台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("切到 Slack，如果没打开就打开", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("打开 Slack 并切到前台", ["app.focus"]) == {
        "protocol": "json_fallback",
        "tool": "app.focus",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("还原微信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("别切到 Slack", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要显示 Slack", allowed_tools) is None
    assert daily_desktop_intent_tool_request("unhide Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("显示 GitHub", allowed_tools) != {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "GitHub"},
    }
    assert daily_desktop_intent_tool_request("隐藏 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("隐藏微信", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("把微信隐藏一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("把 Chrome 藏起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("hide Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Chrome 隐藏一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Chrome 收起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.hide",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("隐藏 Slack", ["desktop.hide_app"]) is None
    assert daily_desktop_intent_tool_request("最小化 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.minimize",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("把 Slack 最小化一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.minimize",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("minimize Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.minimize",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("Chrome 最小化一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.minimize",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Finder 最小化一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.minimize",
        "input": {"app_name": "Finder"},
    }
    safe_window_tools = ["app.hide", "app.minimize", "app.show"]
    assert daily_desktop_intent_tool_requests("Chrome 退出一下", safe_window_tools) == []
    assert daily_desktop_intent_tool_requests("Chrome 关闭一下", safe_window_tools) == []
    assert daily_desktop_intent_tool_request("最小化当前窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前窗口最小化", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前窗口最小化", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把这个窗口最小化", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把窗口收起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("最小化 Slack", ["desktop.minimize_window"]) is None
    assert daily_desktop_intent_tool_request("关闭当前窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("关闭一下当前窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前窗口关掉", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前窗口关了", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前窗口关一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("close current window", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.close_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("minimize current window", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("隐藏当前应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前应用隐藏一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把这个应用隐藏起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把当前 app 藏起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前应用隐藏一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("hide current app", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hide_app",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("显示隐藏的应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.show_all_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("显示所有隐藏应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.show_all_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("show all hidden apps", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.show_all_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("显示隐藏的应用", ["app.show"]) is None
    assert daily_desktop_intent_tool_request("当前应用最小化", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("前台应用最小化", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.minimize_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("别关闭当前窗口", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要关掉这个窗口", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要隐藏当前应用", allowed_tools) is None
    assert daily_desktop_intent_tool_request("别最小化当前窗口", allowed_tools) is None
    long_design_request = (
        '我看了一下当前桌面，class="plan-dropdown-item" 的显示有问题，'
        "plan 的名字的显示区域被挤压到显示不出来文字，需要修改。\n\n"
        "除功能以外，设计风格想要麻烦再出一版新的设计看一下。要求：\n"
        "1. 仅对画面元素和 UI 进行调整，保持现有功能 100% 不变。\n"
        "2. 风格修改为多巴胺风格。\n"
        "3. 请不要覆盖原文件，生成一个新的 html 文件"
    )
    assert daily_desktop_intent_tool_request(long_design_request, allowed_tools) is None
    assert daily_desktop_intent_tool_request("能否帮我播放 Apple Music?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    for prompt in ("当前播放什么", "现在播放什么歌", "Apple Music 现在在播什么", "音乐现在放的什么"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "media.apple_music_status",
            "input": {},
        }
    assert daily_desktop_intent_tool_request("现在播放什么歌", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("Can you play Apple Music?", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("please start playing Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Slack", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("open the Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Finder"},
    }
    assert daily_desktop_intent_tool_request("把 Slack 打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("打开浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("浏览器打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("帮我开一下浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    for prompt in (
        "打开网页",
        "打开一个网页",
        "打开空白网页",
        "打开本地网页",
        "打开网址",
        "打开链接",
        "打开网站",
        "open a browser",
        "open a webpage",
        "open blank page",
        "open local page",
    ):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        }
    assert daily_desktop_intent_tool_request("打开本地", allowed_tools) is None
    assert daily_desktop_intent_tool_request("open The Archive", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "The Archive"},
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
    assert daily_desktop_intent_tool_requests("切到微信看看界面", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信看看界面", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信查看界面元素", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("读取 Chrome 界面控件", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开系统设置看看有哪些选项", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "系统设置"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开系统设置看看", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "系统设置"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信看看有什么按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("Chrome 当前界面有哪些按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("当前页面有哪些按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信窗口列表", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.windows",
            "input": {"app_name": "WeChat"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开终端运行 ls", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "terminal.run",
        "input": {"command": "ls"},
    }
    assert daily_desktop_intent_tool_request("运行 ls | head", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "terminal.run",
        "input": {"command": "ls | head", "shell": True},
    }
    assert daily_desktop_intent_tool_request("打开 VS Code", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Visual Studio Code"},
    }
    assert daily_desktop_intent_tool_request("打开设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "系统设置"},
    }
    assert daily_desktop_intent_tool_request("打开系统偏好设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "系统设置"},
    }
    assert daily_desktop_intent_tool_request("打开声音设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "声音"},
    }
    assert daily_desktop_intent_tool_request("打开蓝牙", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "蓝牙"},
    }
    assert daily_desktop_intent_tool_request("打开蓝牙设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "蓝牙"},
    }
    assert daily_desktop_intent_tool_request("打开 Wi-Fi", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "Wi-Fi"},
    }
    assert daily_desktop_intent_tool_request("打开 Wi-Fi 设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "Wi-Fi"},
    }
    assert daily_desktop_intent_tool_request("打开系统设置蓝牙", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "蓝牙"},
    }
    assert daily_desktop_intent_tool_request("打开 WiFi 设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "Wi-Fi"},
    }
    assert daily_desktop_intent_tool_request("打开网络设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "网络"},
    }
    assert daily_desktop_intent_tool_request("打开网络", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "网络"},
    }
    assert daily_desktop_intent_tool_request("打开电池设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "电池"},
    }
    assert daily_desktop_intent_tool_request("open battery settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "电池"},
    }
    assert daily_desktop_intent_tool_request("打开鼠标设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "鼠标"},
    }
    assert daily_desktop_intent_tool_request("open mouse settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "鼠标"},
    }
    assert daily_desktop_intent_tool_request("打开触控板设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "触控板"},
    }
    assert daily_desktop_intent_tool_request("open trackpad settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "触控板"},
    }
    assert daily_desktop_intent_tool_request("打开打印机设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "打印机与扫描仪"},
    }
    assert daily_desktop_intent_tool_request("open printers settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "打印机与扫描仪"},
    }
    assert daily_desktop_intent_tool_request("打开桌面与程序坞设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "桌面与程序坞"},
    }
    assert daily_desktop_intent_tool_request("open desktop and dock settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "桌面与程序坞"},
    }
    assert daily_desktop_intent_tool_request("打开软件更新", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "软件更新"},
    }
    assert daily_desktop_intent_tool_request("open software update", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "软件更新"},
    }
    assert daily_desktop_intent_tool_request("打开显示器设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "显示器"},
    }
    assert daily_desktop_intent_tool_request("打开显示设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "显示器"},
    }
    assert daily_desktop_intent_tool_request("打开隐私", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开定位权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "定位服务"},
    }
    assert daily_desktop_intent_tool_request("打开文件管理器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Finder"},
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
    assert daily_desktop_intent_tool_requests("打开活动监视器看看 CPU", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Activity Monitor"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开日历看看今天安排", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Calendar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开微信看看有没有新消息", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 看消息", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Discord and read messages", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Discord"},
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {"reason": "user asked to capture the screen"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开设置的隐私与安全性", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开屏幕录制权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "屏幕录制权限"},
    }
    assert daily_desktop_intent_tool_request("打开辅助功能权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "辅助功能权限"},
    }
    assert daily_desktop_intent_tool_request("打开系统设置里的辅助功能", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "辅助功能权限"},
    }
    assert daily_desktop_intent_tool_request("打开自动化权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "自动化权限"},
    }
    assert daily_desktop_intent_tool_request("打开辅助功能权限", ["app.open"]) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "辅助功能权限"},
    }
    for prompt, target in (
        ("修复自动化权限", "自动化权限"),
        ("修一下屏幕录制权限", "屏幕录制权限"),
        ("修复辅助功能权限", "辅助功能权限"),
        ("修复输入监控权限", "输入监控"),
        ("修复完全磁盘访问权限", "完全磁盘访问"),
        ("fix screen recording permissions", "屏幕录制权限"),
        ("fix full disk access permissions", "完全磁盘访问"),
        ("fix input monitoring permissions", "输入监控"),
    ):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": target},
        }
    assert daily_desktop_intent_tool_request("open accessibility settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "辅助功能权限"},
    }
    assert daily_desktop_intent_tool_request("open Bluetooth settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "蓝牙"},
    }
    assert daily_desktop_intent_tool_request("打开麦克风权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "麦克风"},
    }
    assert daily_desktop_intent_tool_request("打开输入监控权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "输入监控"},
    }
    assert daily_desktop_intent_tool_request("打开完全磁盘访问权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "完全磁盘访问"},
    }
    assert daily_desktop_intent_tool_request("打开摄像头权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "摄像头"},
    }
    assert daily_desktop_intent_tool_request("打开桌面权限设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开隐私设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开系统隐私设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("open desktop permissions", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("打开需要的权限设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "隐私与安全性"},
    }
    assert daily_desktop_intent_tool_request("检查桌面权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("需要什么权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("你需要哪些权限", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能控制桌面？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能打开应用？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能播放 Apple Music？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能读取屏幕？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("为什么不能查看屏幕？", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.permissions",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("怎么不能播放 Apple Music？", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("在 Finder 中显示 ~/Downloads/report.pdf", ["app.show"]) is None
    assert daily_desktop_intent_tool_request("打开 ~/Downloads/report.pdf", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads/report.pdf"},
    }
    assert daily_desktop_intent_tool_request("打开最近下载的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_download"},
    }
    assert daily_desktop_intent_tool_request("open latest downloaded file", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_download"},
    }
    assert daily_desktop_intent_tool_request("打开刚才的截图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_screenshot"},
    }
    assert daily_desktop_intent_tool_request("open latest screenshot", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_screenshot"},
    }
    assert daily_desktop_intent_tool_request("打开桌面最新文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_desktop_item"},
    }
    assert daily_desktop_intent_tool_request("open latest file on desktop", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_desktop_item"},
    }
    assert daily_desktop_intent_tool_request("打开选中的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "finder_selection"},
    }
    assert daily_desktop_intent_tool_request("open selected Finder item", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "finder_selection"},
    }
    assert daily_desktop_intent_tool_request("把 ~/Downloads/report.pdf 打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads/report.pdf"},
    }
    assert daily_desktop_intent_tool_request("在访达中显示下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("把下载文件夹在 Finder 里显示一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("把下载文件夹在 Finder 里显示出来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("show Downloads folder in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 并显示下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开图片文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Pictures"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 打开照片目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Pictures"},
    }
    assert daily_desktop_intent_tool_request("打开公共文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Public"},
    }
    assert daily_desktop_intent_tool_request("打开 Public 文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Public"},
    }
    assert daily_desktop_intent_tool_request("打开影片文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Movies"},
    }
    assert daily_desktop_intent_tool_request("打开音乐目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Music"},
    }
    assert daily_desktop_intent_tool_request("打开 Music 文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Music"},
    }
    assert daily_desktop_intent_tool_request("打开家目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~"},
    }
    assert daily_desktop_intent_tool_request("open Finder and show Downloads folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("open Finder then show Downloads folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示最近下载的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_download"},
    }
    assert daily_desktop_intent_tool_request("reveal latest download in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_download"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示最新截图", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_screenshot"},
    }
    assert daily_desktop_intent_tool_request("reveal latest screenshot in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_screenshot"},
    }
    assert daily_desktop_intent_tool_request("显示桌面最新文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_desktop_item"},
    }
    assert daily_desktop_intent_tool_request("show latest desktop item in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "latest_desktop_item"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示选中的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "finder_selection"},
    }
    assert daily_desktop_intent_tool_request("reveal selected file in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "finder_selection"},
    }
    assert daily_desktop_intent_tool_request("launch Finder and show Desktop folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Desktop"},
    }
    assert daily_desktop_intent_tool_request("open Finder and open Downloads folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示 ~/Downloads/测试文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads/测试文件夹"},
    }
    assert daily_desktop_intent_tool_request("show ~/Downloads/report.pdf in Finder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads/report.pdf"},
    }
    assert daily_desktop_intent_tool_request("打开下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("把下载文件夹打开一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("把下载文件夹拉起来", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("拉起下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 并打开下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 看看下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开访达看看下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 看看桌面文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Desktop"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开访达下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开访达里的下载文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载目录给我看", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载目录一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开我的下载", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开我的文稿", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Documents"},
    }
    assert daily_desktop_intent_tool_request("打开回收站", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/.Trash"},
    }
    assert daily_desktop_intent_tool_request("显示下载目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("显示当前项目", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "."},
    }
    assert daily_desktop_intent_tool_request("在 Finder 中显示当前项目", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "."},
    }
    assert daily_desktop_intent_tool_request("可以帮我打开下载文件夹吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开应用程序文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/Applications"},
    }
    assert daily_desktop_intent_tool_request("打开当前仓库", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "."},
    }
    assert daily_desktop_intent_tool_request("open current repo", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "."},
    }
    assert daily_desktop_intent_tool_request("打开临时目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/tmp"},
    }
    assert daily_desktop_intent_tool_request("打开根目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/"},
    }
    for prompt in ("打开文件夹", "打开一个文件夹", "open folder", "open a folder"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Finder"},
        }
    for prompt in (
        "打开当前项目",
        "打开项目文件夹",
        "打开工作区",
        "在 Finder 中打开当前项目",
        "open current project",
        "open project folder",
        "open workspace",
    ):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.open_path",
            "input": {"path": "."},
        }
    assert daily_desktop_intent_tool_request("打开项目", allowed_tools) is None
    assert daily_desktop_intent_tool_request("打开 Arc 浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Arc"},
    }
    assert daily_desktop_intent_tool_request("打开 Zoom", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "zoom.us"},
    }
    assert daily_desktop_intent_tool_request("打开 Word", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Microsoft Word"},
    }
    assert daily_desktop_intent_tool_request("启动 iTerm2", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "iTerm"},
    }
    assert daily_desktop_intent_tool_request("打开 Teams", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Microsoft Teams"},
    }
    assert daily_desktop_intent_tool_request("打开网易云音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "网易云音乐"},
    }
    assert daily_desktop_intent_tool_request("播放网易云音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "网易云音乐"},
    }
    assert daily_desktop_intent_tool_request("播放 QQ 音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "QQ音乐"},
    }
    assert daily_desktop_intent_tool_request("播放 Spotify", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("播放 Spotify", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("打开 Spotify 并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_requests("打开 Spotify 播放周杰伦", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周杰伦"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Spotify 播放周杰伦", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周杰伦"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]
    assert daily_desktop_intent_tool_request("用 Spotify 播放音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_requests("用 Spotify 播放周杰伦", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周杰伦"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Spotify 搜索 Taylor Swift 并播放", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Spotify", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Taylor Swift"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "Spotify"},
        },
    ]
    assert daily_desktop_intent_tool_requests("网易云音乐搜索周杰伦并播放", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "网易云音乐", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周杰伦"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "网易云音乐"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开 Spotify 播放周杰伦", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("打开 Spotify 并播放", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("打开 Spotify 并播放", ["media.apple_music_control"]) is None
    assert daily_desktop_intent_tool_request("打开 Spotify 播放周杰伦", ["media.music_app_open_and_play"]) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("打开网易云音乐并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "网易云音乐"},
    }
    assert daily_desktop_intent_tool_requests("打开网易云音乐播放周杰伦", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "网易云音乐", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周杰伦"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "media.music_app_open_and_play",
            "input": {"app_name": "网易云音乐"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开音乐播放器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("打开默认浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("启动系统默认浏览器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("打开苹果音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("启动播放器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("播放音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("来点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("随便放点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("放点歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("我想听歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("听一首歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("播点东西", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("play something", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("I want to listen to music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("帮我播放点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开音乐并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 播放音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 随便放点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 播放周杰伦", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "周杰伦"},
    }
    assert daily_desktop_intent_tool_request("我想听超时空辉夜姬吧", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("播放超时空辉夜姬 Apple Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 并播放", ["media.apple_music_control"]) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("Apple Music 播放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Apple Music 放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("音乐放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Music 放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("放首歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("来一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("给我来点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("放音乐听听", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("听点音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("想听音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("播放苹果音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("帮我用 Apple Music 放一首歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("用 Apple Music 随便放点歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("播放一下 Apple Music 里的歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Apple Music 随便放点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Music app play something", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("start playing in Music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("给我来点音乐", ["media.apple_music_control"]) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("帮我用 Apple Music 放一首歌", ["media.apple_music_control"]) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("来一首", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("帮我用 Apple Music 放一首歌", ["media.apple_music_play"]) is None
    assert daily_desktop_intent_tool_request("暂停音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    assert daily_desktop_intent_tool_request("pause the music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    assert daily_desktop_intent_tool_request("停止一下音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    assert daily_desktop_intent_tool_request("继续放歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("接着放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("接着播", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("播放继续", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("继续当前音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("恢复音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("continue playing music", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("play playback", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("恢复音乐", ["app.show"]) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("下一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("切歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("换首歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("跳过这首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("skip this song", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "next"},
    }
    assert daily_desktop_intent_tool_request("上一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "previous"},
    }
    assert daily_desktop_intent_tool_request("别放了", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    assert daily_desktop_intent_tool_request("关掉音乐", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "pause"},
    }
    for prompt in ("现在播放什么", "当前在播什么", "Apple Music 正在播什么", "查看播放状态"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "media.apple_music_status",
            "input": {},
        }
    assert daily_desktop_intent_tool_request("播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("超时空辉夜姬播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("周杰伦播放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "周杰伦"},
    }
    assert daily_desktop_intent_tool_request("超时空辉夜姬放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("来一首超时空辉夜姬", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("用 Apple Music 播放超时空辉夜姬", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("帮我在 Apple Music 搜一下超时空辉夜姬并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 搜索超时空辉夜姬并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_tool_request("Apple Music 搜索超时空辉夜姬并播放", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("search Space Oddity in Apple Music and play it", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Space Oddity"},
    }
    assert daily_desktop_intent_tool_request("Apple Music search Space Oddity and play it", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Space Oddity"},
    }
    assert daily_desktop_intent_tool_request("Apple Music play Space Oddity", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Space Oddity"},
    }
    assert daily_desktop_intent_tool_request("play Apple Music Space Oddity", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "Space Oddity"},
    }
    assert daily_desktop_intent_tool_request("open Apple Music and search Space Oddity and play it", allowed_tools) == {
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
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("Spotify 播放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("网易云音乐播放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "网易云音乐"},
    }
    assert daily_desktop_intent_tool_request("当前音量是多少", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "status"},
    }
    assert daily_desktop_intent_tool_request("把音量调到 35%", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 35},
    }
    assert daily_desktop_intent_tool_request("音量设成 35", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 35},
    }
    assert daily_desktop_intent_tool_request("设成 35 音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 35},
    }
    assert daily_desktop_intent_tool_request("设置音量为 40", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 40},
    }
    assert daily_desktop_intent_tool_request("把系统音量调到百分之 20", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 20},
    }
    assert daily_desktop_intent_tool_request("音量调一半", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 50},
    }
    assert daily_desktop_intent_tool_request("把音量调满", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 100},
    }
    assert daily_desktop_intent_tool_request("音量 50", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "set", "level": 50},
    }
    assert daily_desktop_intent_tool_request("调大音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("放大音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("把音量放大", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("Apple Music 放大音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("声音大点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("turn it up", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("make it louder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "up"},
    }
    assert daily_desktop_intent_tool_request("声音小一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("缩小音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("把音量缩小", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("Apple Music 缩小音量", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("太吵了小点声", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("turn it down", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("make it quieter", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "down"},
    }
    assert daily_desktop_intent_tool_request("静音", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "mute"},
    }
    assert daily_desktop_intent_tool_request("关掉声音", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "mute"},
    }
    assert daily_desktop_intent_tool_request("声音关掉", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "mute"},
    }
    assert daily_desktop_intent_tool_request("别出声", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "mute"},
    }
    assert daily_desktop_intent_tool_request("turn sound off", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "mute"},
    }
    assert daily_desktop_intent_tool_request("取消静音", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "unmute"},
    }
    assert daily_desktop_intent_tool_request("把声音打开", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "unmute"},
    }
    assert daily_desktop_intent_tool_request("turn sound on", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.volume",
        "input": {"action": "unmute"},
    }
    assert daily_desktop_intent_tool_request("屏幕亮一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 2},
    }
    assert daily_desktop_intent_tool_request("亮一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 2},
    }
    assert daily_desktop_intent_tool_request("再亮一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 2},
    }
    assert daily_desktop_intent_tool_request("亮一点点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 1},
    }
    assert daily_desktop_intent_tool_request("亮度调高三下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 3},
    }
    assert daily_desktop_intent_tool_request("亮度大一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 2},
    }
    assert daily_desktop_intent_tool_request("屏幕太暗了", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "up", "step": 2},
    }
    assert daily_desktop_intent_tool_request("屏幕暗一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "down", "step": 2},
    }
    assert daily_desktop_intent_tool_request("暗一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "down", "step": 2},
    }
    assert daily_desktop_intent_tool_request("调暗一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "down", "step": 2},
    }
    assert daily_desktop_intent_tool_request("亮度小一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "down", "step": 2},
    }
    assert daily_desktop_intent_tool_request("dim the screen", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.brightness",
        "input": {"action": "down", "step": 2},
    }
    assert daily_desktop_intent_tool_request("关闭屏幕", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.display_sleep",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("turn off the display", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.display_sleep",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("sleep my Mac", allowed_tools) is None
    assert daily_desktop_intent_tool_request("启动屏幕保护程序", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.screen_saver_start",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("start screen saver", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.screen_saver_start",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("open screen saver settings", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "屏幕保护程序"},
    }
    assert daily_desktop_intent_tool_request("漂亮一点", allowed_tools) is None
    assert daily_desktop_intent_tool_request("亮度调到 50%", allowed_tools) is None
    assert daily_desktop_intent_tool_request("把 047e43ac 复制到剪贴板", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "047e43ac"},
    }
    assert daily_desktop_intent_tool_request("写入剪贴板：hello world", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("写入剪贴板 hello world", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("把这段话复制到剪贴板：hello world", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("复制以下内容：hello world", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("剪贴板写入 hello world", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("把 hello 复制一下到剪贴板", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello"},
    }
    assert daily_desktop_intent_tool_request("把 hello 复制一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello"},
    }
    assert daily_desktop_intent_tool_request(
        "把 hello 复制一下",
        ["app.focus_and_safe_shortcut"],
    ) is None
    assert daily_desktop_intent_tool_request("把当前窗口内容复制一下", ["clipboard.write"]) is None
    assert daily_desktop_intent_tool_request("复制一下 hello world", allowed_tools) is None
    assert daily_desktop_intent_tool_request("copy hello world to clipboard", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello world"},
    }
    assert daily_desktop_intent_tool_request("剪贴板里是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.read",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("读一下剪贴板", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.read",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("粘贴板读下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.read",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("read clipboard", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.read",
        "input": {},
    }
    for prompt in ("把剪贴板读给我", "读取 clipboard", "what is on my clipboard"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        }
    assert daily_desktop_intent_tool_request("读取剪贴板", ["clipboard.write"]) is None
    assert daily_desktop_intent_tool_requests("读一下选中的内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("选中的是什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("我选中了什么", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("选中内容复制给我", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("read selected text", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "clipboard.read",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("读一下选中的内容", ["clipboard.read"]) == []
    assert daily_desktop_intent_tool_request("截个图看看", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("屏幕截一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("截当前屏幕", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("帮我看看现在屏幕", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("当前屏幕是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("show me the screen", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "screen.capture",
        "input": {"reason": "user asked to capture the screen"},
    }
    assert daily_desktop_intent_tool_request("当前窗口是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在用的是哪个 App", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在前台是什么", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("我正在用什么应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前是什么天气", allowed_tools) is None
    assert daily_desktop_intent_tool_request("what is the frontmost window", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在开了哪些应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前有哪些 App 在运行", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在有哪些应用在运行", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列出正在运行的应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.running_apps",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列一下打开的应用", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("看看当前窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.active_window",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("现在有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("当前应用有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("前台应用有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列一下当前应用窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("看看打开了哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("窗口列表", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("显示当前窗口列表", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("所有窗口列一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("列出 Chrome 窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("列出Chrome窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("list windows in Chrome", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("what windows are open in Chrome", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Chrome 有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("当前界面有哪些按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "button", "limit": 80},
    }
    assert daily_desktop_intent_tool_requests("what buttons are visible in Slack", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_requests("what can I click in Chrome", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "", "limit": 80},
        },
    ]
    assert daily_desktop_intent_tool_request("列出当前窗口控件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "", "limit": 80},
    }
    assert daily_desktop_intent_tool_request("当前界面有哪些输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "text", "limit": 80},
    }
    assert daily_desktop_intent_tool_request("Slack窗口列表", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("显示微信窗口列表", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "WeChat"},
    }
    assert daily_desktop_intent_tool_request("帮我看看 Slack 有哪些窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Slack"},
    }
    assert daily_desktop_intent_tool_request("看一下 Slack 的窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.windows",
        "input": {"app_name": "Slack"},
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
    assert daily_desktop_intent_tool_request("看看 Chrome 开了没", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Google Chrome"},
    }
    assert daily_desktop_intent_tool_request("Music 在运行吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "Music"},
    }
    assert daily_desktop_intent_tool_request("Zoom 开着吗", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.status",
        "input": {"app_name": "zoom.us"},
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
    assert daily_desktop_intent_tool_requests("查看当前应用有哪些按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        }
    ]
    assert daily_desktop_intent_tool_requests("看看当前界面有哪些按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "button", "limit": 80},
        }
    ]
    assert daily_desktop_intent_tool_requests("当前界面有哪些输入框", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "text", "limit": 80},
        }
    ]
    assert daily_desktop_intent_tool_request("按 Command+L", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "l", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("按 Command V", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_intent_tool_request("按 Shift Command Z", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "redo"},
    }
    assert daily_desktop_intent_tool_request("按 Command Option P", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "p", "modifiers": ["command", "option"]},
    }
    assert daily_desktop_intent_tool_request("按 Ctrl Shift P", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "p", "modifiers": ["control", "shift"]},
    }
    assert daily_desktop_intent_tool_request("按一下回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("按确认键", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("enter", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("敲一下回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("hit enter", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("tap the return key", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("发送当前消息", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("发送当前内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("当前输入框发送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("前台发送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("发送前台内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("当前消息发出", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("按回车发送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("当前输入框按回车发送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("press return to send", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("发送 hello", allowed_tools) is None
    assert daily_desktop_intent_tool_request("send current message", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
    }
    assert daily_desktop_intent_tool_request("提交当前表单", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("提交当前内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("当前输入框提交", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("前台提交", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("提交前台内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("按回车提交", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("当前输入框按回车提交", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("press enter to submit", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("submit current form", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "submit"},
    }
    assert daily_desktop_intent_tool_request("确认当前内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("前台确认", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("确认前台内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("按回车确认", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("press enter to confirm", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("confirm current dialog", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.submit_foreground",
        "input": {"action": "confirm"},
    }
    assert daily_desktop_intent_tool_request("复制选中内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("复制一下选中的内容", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("复制选中文字", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("复制选中文本", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("粘贴一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_intent_tool_request("把剪贴板内容粘贴到当前输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_intent_tool_request("粘贴到这里", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_intent_tool_request("全选", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "select_all"},
    }
    assert daily_desktop_intent_tool_request("撤销", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "undo"},
    }
    assert daily_desktop_intent_tool_request("重做", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "redo"},
    }
    assert daily_desktop_intent_tool_request("copy selected text", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("copy current selection", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("new tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("open new tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("打开新标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("新建标签", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_tab"},
    }
    assert daily_desktop_intent_tool_request("重新打开刚关闭的标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "reopen_closed_tab"},
    }
    assert daily_desktop_intent_tool_request("恢复上次关闭的标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "reopen_closed_tab"},
    }
    assert daily_desktop_intent_tool_request("关闭当前标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "close_tab"},
    }
    assert daily_desktop_intent_tool_request("close current tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "close_tab"},
    }
    assert daily_desktop_intent_tool_request("切到下一个标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "next_tab"},
    }
    assert daily_desktop_intent_tool_request("switch to next tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "next_tab"},
    }
    assert daily_desktop_intent_tool_request("切到上一个标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "previous_tab"},
    }
    assert daily_desktop_intent_tool_request("previous tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "previous_tab"},
    }
    assert daily_desktop_intent_tool_request("打开新窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_window"},
    }
    assert daily_desktop_intent_tool_request("新建笔记", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("创建备忘录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_note"},
    }
    assert daily_desktop_intent_tool_request("创建一个提醒", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_reminder"},
    }
    assert daily_desktop_intent_tool_request("新建日程", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("创建一个日程", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("新建窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "new_window"},
    }
    assert daily_desktop_intent_tool_request("打开新窗口", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开查找", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "find"},
    }
    assert daily_desktop_intent_tool_request("页面里查找", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "find"},
    }
    assert daily_desktop_intent_tool_request("open find", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "find"},
    }
    assert daily_desktop_intent_tool_request("find on page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "find"},
    }
    assert daily_desktop_intent_tool_requests("查找 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("页面查找 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在当前页面搜索 OpenAI", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "OpenAI"},
        },
    ]
    assert daily_desktop_intent_tool_request("打开查找", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("刷新一下页面", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("刷新当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("浏览器刷新", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("refresh page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("reload page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("重新打开关闭的标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "reopen_closed_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 重新打开关闭的标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "reopen_closed_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 复制选中文字", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "copy"},
    }
    assert daily_desktop_intent_tool_request("Slack 粘贴到当前输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "paste"},
    }
    assert daily_desktop_intent_tool_request("Chrome 浏览器刷新", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "refresh"},
    }
    assert daily_desktop_intent_tool_request("Chrome 关闭当前标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "close_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 切到下一个标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "next_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 切到上一个标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "previous_tab"},
    }
    assert daily_desktop_intent_tool_request("Chrome 重新打开刚关闭的标签页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "reopen_closed_tab"},
    }
    assert daily_desktop_intent_tool_request("返回上一页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("浏览器后退", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("前进一页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_forward"},
    }
    assert daily_desktop_intent_tool_request("前进下一页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_forward"},
    }
    assert daily_desktop_intent_tool_request("go back", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("go back one page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("back page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_back"},
    }
    assert daily_desktop_intent_tool_request("go forward", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_forward"},
    }
    assert daily_desktop_intent_tool_request("forward page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "browser_forward"},
    }
    assert daily_desktop_intent_tool_request("锁一下屏", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "lock_screen"},
    }
    assert daily_desktop_intent_tool_request("复制选中内容", ["desktop.hotkey"]) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "c", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("输入 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("输入文本 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("在当前输入框输入文本 hello", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "hello"},
    }
    assert daily_desktop_intent_tool_request("帮我打 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("敲入 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("把 你好八千代 输入进去", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("在当前窗口写入 你好八千代", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("写入 你好八千代", allowed_tools) is None
    assert daily_desktop_intent_tool_request("别打 你好八千代", allowed_tools) is None
    assert daily_desktop_intent_tool_request("输入 你好八千代", ["desktop.type_text"]) == {
        "protocol": "json_fallback",
        "tool": "desktop.type_text",
        "input": {"text": "你好八千代"},
    }
    assert daily_desktop_intent_tool_request("点击 120, 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_click",
        "input": {"x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("点 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_click",
        "input": {"x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("在坐标 120 240 点一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_click",
        "input": {"x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("单击 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_click",
        "input": {"x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("点击 120, 240", ["desktop.click"]) == {
        "protocol": "json_fallback",
        "tool": "desktop.click",
        "input": {"x": 120, "y": 240, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("双击 120 240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click",
        "input": {"x": 120, "y": 240, "click_count": 2},
    }
    assert daily_desktop_intent_tool_request("点击屏幕 120,240", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_click",
        "input": {"x": 120, "y": 240},
    }
    assert daily_desktop_intent_tool_request("别点 120 240", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要双击 120 240", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么截图？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么打开 github.com？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么搜索 GitHub？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("怎么播放 Apple Music？", allowed_tools) is None
    assert daily_desktop_intent_tool_request("总结当前网页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.extract_text",
        "input": {},
        "presentation": "summary",
    }
    assert daily_desktop_intent_tool_request("点击搜索", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "搜索", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("当前界面点击登录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("前台点登录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("current window click Login", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "Login", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("不要真的播放超时空辉夜姬，只告诉我怎么做", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要真的点击 120, 240，只告诉我怎么做", allowed_tools) is None
    assert daily_desktop_intent_tool_request("不要打开 Slack", allowed_tools) is None
    assert daily_desktop_intent_tool_request("别把 GitHub 打开", allowed_tools) is None
    assert daily_desktop_intent_tool_request("请运行一个会失败的命令", allowed_tools) is None
    assert daily_desktop_intent_tool_request("提醒我下午三点开会", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "reminders.create",
        "input": {"title": "开会", "due_at": today_1500},
    }
    assert daily_desktop_intent_tool_request("新建一个提醒事项 明天下午三点开会", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "reminders.create",
        "input": {"title": "开会", "due_at": tomorrow_1500},
    }
    assert daily_desktop_intent_tool_request("创建日历事件 明天下午三点开会", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "calendar.create_event",
        "input": {"title": "开会", "start_at": tomorrow_1500, "end_at": tomorrow_1600},
    }
    assert daily_desktop_intent_tool_request("创建明天上午10点开会的日程", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "calendar.create_event",
        "input": {
            "title": "开会",
            "start_at": f"{tomorrow.isoformat()}T10:00",
            "end_at": f"{tomorrow.isoformat()}T11:00",
        },
    }
    assert daily_desktop_intent_tool_request("创建明天上午10点开会的提醒", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "reminders.create",
        "input": {"title": "开会", "due_at": f"{tomorrow.isoformat()}T10:00"},
    }
    assert daily_desktop_intent_tool_request("查看系统状态", allowed_tools) is None
    assert daily_desktop_intent_candidates("播放超时空辉夜姬")[0] == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
    }
    assert daily_desktop_intent_candidates("trigger provider failure") == []
    assert daily_desktop_intent_candidates("Turn the research notes into an implementation plan.") == []
    assert daily_desktop_intent_candidates(
        "请做一个很长的移动端验收方案，包含信息架构、状态层级、审批提醒、"
        "失败提示、运行详情入口、产物入口、连续审批提示、长文本完整展示、"
        "主模型最终整理和用户下一步动作，并保留结尾标记 long-goal-tail-marker-917263"
    ) == []
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
    assert daily_desktop_intent_tool_request("把 GitHub 打开一下", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开小红书", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开新标签页", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("打开 ~/Downloads/report.pdf", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("把下载文件夹打开一下", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("拉起下载文件夹", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("列出正在运行的应用", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("现在开了哪些应用", ["desktop.active_window"]) is None
    assert daily_desktop_intent_tool_request("当前窗口是什么", ["desktop.windows"]) is None
    assert daily_desktop_intent_tool_request("Chrome 开着吗", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("ChatGPT 打开了吗", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("检查一下 Slack 是否在运行", ["browser.open_url"]) is None
    assert daily_desktop_intent_tool_request("退出 Slack", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("关闭当前窗口", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("最小化当前窗口", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("隐藏当前应用", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("检查桌面权限", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("搜索 open hanako", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("按 Command+L", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("向下滚动", ["desktop.type_text"]) is None
    assert daily_desktop_intent_tool_request("按 Tab", ["desktop.type_text"]) is None
    assert daily_desktop_intent_tool_request("调大音量", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("复制 hello 到剪贴板", ["app.open"]) is None
    assert daily_desktop_intent_tool_request("复制 hello 到剪贴板", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "clipboard.write",
        "input": {"text": "hello"},
    }
    assert daily_desktop_intent_tool_request("放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("播放一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_control",
        "input": {"action": "play"},
    }
    assert daily_desktop_intent_tool_request("点击发送按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "发送", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("click Send button", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "Send", "role_filter": "button", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("click the search field", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "search", "role_filter": "text", "limit": 80, "click_count": 1},
    }
    assert daily_desktop_intent_tool_request("点击发送按钮", ["desktop.click"]) is None
    assert daily_desktop_intent_tool_request("点击当前网页上的发送按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.click",
        "input": {"selector": "text=发送", "click_count": 1},
    }
    for prompt in ("向下滚动", "向下滚动一点", "当前窗口向下滚动一点"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "down", "pages": 1},
        }
    for prompt in ("滚动一下", "页面滚动一下", "scroll", "scroll a little"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "down", "pages": 1},
        }
    for prompt in ("滚动到下面一点", "滚到下面一点", "滑到下方一点"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "down", "pages": 1},
        }
    for prompt in ("滚动到上面一点", "滚到上面一点", "滑到上方一点"):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "desktop.safe_scroll",
            "input": {"direction": "up", "pages": 1},
        }
    assert daily_desktop_intent_tool_request("向上滚动两页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "up", "pages": 2},
    }
    assert daily_desktop_intent_tool_request("向上滚动一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "up", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("翻到下一页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "down", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("滚动到底部", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "down", "pages": 10},
    }
    assert daily_desktop_intent_tool_request("回到顶部", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "up", "pages": 10},
    }
    assert daily_desktop_intent_tool_request("打开 Chrome 翻到下一页", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_scroll",
        "input": {"app_name": "Google Chrome", "direction": "down", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("Chrome 向下滚动一点", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_scroll",
        "input": {"app_name": "Google Chrome", "direction": "down", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("scroll down 3 pages", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "down", "pages": 3},
    }
    assert daily_desktop_intent_tool_request("scroll the page down", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "down", "pages": 1},
    }
    assert daily_desktop_intent_tool_request("scroll to bottom", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_scroll",
        "input": {"direction": "down", "pages": 10},
    }
    assert daily_desktop_intent_tool_request("按 Tab", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("切到下一个输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("切到上一个输入框", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "shift_tab", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("按三次下箭头", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "arrow_down", "repeat_count": 3},
    }
    assert daily_desktop_intent_tool_request("按向下箭头三次", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "arrow_down", "repeat_count": 3},
    }
    assert daily_desktop_intent_tool_request("press escape", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "escape", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("回到桌面", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_key",
        "input": {"action": "show_desktop", "repeat_count": 1},
    }
    assert daily_desktop_intent_tool_request("按回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("空格一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "space", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("当前窗口按回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("前台按回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("press enter in current window", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("退出当前应用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "q", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("关闭当前 app", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.hotkey",
        "input": {"key": "q", "modifiers": ["command"]},
    }
    assert daily_desktop_intent_tool_request("当前窗口按 Command V", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }
    assert daily_desktop_intent_tool_request("复制这个", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    assert daily_desktop_intent_tool_request("应用窗口都显示一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "application_windows"},
    }
    assert daily_desktop_intent_tool_request("显示当前应用的所有窗口", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "application_windows"},
    }
    assert daily_desktop_intent_tool_request("这段文字复制到剪贴板", allowed_tools) is None
    assert daily_desktop_intent_tool_request("恢复这个权限", allowed_tools) is None


def test_daily_desktop_entrypoint_tool_requests_share_metadata_and_sequence_detection() -> None:
    allowed_tools = [
        "app.open",
        "system.settings_open",
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
    ]
    metadata = {
        "desktop_permission_recovery": True,
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "辅助功能权限"},
        "recovery_risk_level": "low",
    }

    assert daily_desktop_entrypoint_tool_requests(
        "打开 Notes，输入 hello，再复制",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_type_text",
            "input": {"app_name": "Notes", "text": "hello"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
    ]
    assert daily_desktop_entrypoint_tool_requests(
        "恢复权限",
        allowed_tools,
        metadata=metadata,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "辅助功能权限"},
            "source": "daily_desktop_metadata",
            "planning_reason": "structured_recovery_metadata",
        }
    ]
    assert daily_desktop_entrypoint_tool_requests(
        "怎么播放 Apple Music？",
        allowed_tools,
    ) == []


def test_custom_api_agent_loop_executes_multi_step_daily_desktop_intent_without_model() -> None:
    budget = FakeBudget()
    tool_runs: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def run_tool_requests(
        tool_requests,
        _allowed_tools,
        _broker,
        _messages_arg,
        timeline_arg,
        _artifacts,
        **_kwargs,
    ):
        tool_runs.append(tool_requests)
        for tool_request in tool_requests:
            tool = str(tool_request.get("tool") or "")
            payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
            if tool == "app.open_and_safe_type_text":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Focused app and completed foreground action",
                    "data": {
                        "app_name": payload["app_name"],
                        "foreground_action": "safe_type_text",
                        "character_count": len(payload["text"]),
                        "explicit_user_text": True,
                    },
                }
            elif tool == "desktop.safe_shortcut":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Executed safe shortcut: copy",
                    "data": {"shortcut_action": payload["action"]},
                }
            else:
                raise AssertionError(f"unexpected tool: {tool}")
            timeline_arg.append(
                _timeline("agent.tool.call", tool, input_preview=payload, result=result)
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "app.open_and_safe_type_text",
                    "desktop.safe_shortcut",
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
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("multi-step daily desktop intent should not call model")
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
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "打开 Notes，输入 hello，再复制",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-multi-daily",
    )

    assert result == "已打开 Notes 并输入文字（5 个字符）。 已复制选中内容。"
    assert tool_runs == [
        [
            {
                "protocol": "json_fallback",
                "tool": "app.open_and_safe_type_text",
                "input": {"app_name": "Notes", "text": "hello"},
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
            },
        ]
    ]
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["detail"] for event in planned_events] == [
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
    ]
    completed = [event for event in timeline if event["event"] == "agent.desktop.intent_completed"]
    assert completed[-1]["detail"] == "desktop.safe_shortcut"
    assert completed[-1]["tools"] == ["app.open_and_safe_type_text", "desktop.safe_shortcut"]


def test_daily_desktop_recovery_prompt_accepts_low_risk_open_actions() -> None:
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "system.settings_open",
            "recovery_input": {"target": "屏幕录制权限"},
            "recovery_risk_level": "low",
        }
    ) == "打开屏幕录制权限"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.open",
            "recovery_input": {"app_name": "Music"},
            "recovery_risk_level": "low",
        }
    ) == "打开Music"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.focus",
            "recovery_input": {"app_name": "Google Chrome"},
            "recovery_risk_level": "low",
        }
    ) == "切到Google Chrome"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.focus_window",
            "recovery_input": {"app_name": "Google Chrome", "window_title": "ChatGPT"},
            "recovery_risk_level": "low",
        }
    ) == "切到Google Chrome ChatGPT窗口"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.show",
            "recovery_input": {"app_name": "Music"},
            "recovery_risk_level": "low",
        }
    ) == "显示Music"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.status",
            "recovery_input": {"app_name": "Music"},
            "recovery_risk_level": "low",
        }
    ) == "检查Music是否打开"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.open_and_safe_key",
            "recovery_input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
            "recovery_risk_level": "low",
        }
    ) == "打开Google Chrome并按Tab"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.focus_and_safe_click",
            "recovery_input": {"app_name": "Google Chrome", "x": 120, "y": 240},
            "recovery_risk_level": "low",
        }
    ) == "切到Google Chrome并点击 120, 240"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.click_ui_element",
            "recovery_input": {"target": "Send", "role_filter": "button"},
            "recovery_risk_level": "low",
        }
    ) == "点击前台控件Send"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.type_into_ui_element",
            "recovery_input": {"target": "Search", "text": "hello", "role_filter": "text"},
            "recovery_risk_level": "low",
        }
    ) == "在前台控件Search输入hello"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.open_and_click_ui_element",
            "recovery_input": {"app_name": "Slack", "target": "Send", "role_filter": "button"},
            "recovery_risk_level": "low",
        }
    ) == "打开Slack并点击前台控件Send"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.focus_and_type_into_ui_element",
            "recovery_input": {
                "app_name": "Slack",
                "target": "Message",
                "text": "hello",
                "role_filter": "text",
            },
            "recovery_risk_level": "low",
        }
    ) == "切到Slack并在前台控件Message输入hello"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.open_url",
            "recovery_input": {"url": "https://github.com"},
            "recovery_risk_level": "low",
        }
    ) == "打开 https://github.com"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.open_url_and_extract_text",
            "recovery_input": {"url": "https://github.com", "selector": ""},
            "recovery_risk_level": "low",
        }
    ) == "打开并读取 https://github.com"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.open_url_and_screenshot",
            "recovery_input": {"url": "https://github.com"},
            "recovery_risk_level": "low",
        }
    ) == "打开并截取 https://github.com"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.screenshot",
            "recovery_input": {"reason": "structured recovery"},
            "recovery_risk_level": "low",
        }
    ) == "截取当前网页"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.open_path",
            "recovery_input": {"path": "~/Downloads"},
            "recovery_risk_level": "low",
        }
    ) == "打开 ~/Downloads"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "media.apple_music_control",
            "recovery_input": {"action": "pause"},
            "recovery_risk_level": "low",
        }
    ) == "暂停音乐"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "media.apple_music_play",
            "recovery_input": {"query": "超时空辉夜姬"},
            "recovery_risk_level": "low",
        }
    ) == "播放超时空辉夜姬"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "media.apple_music_open_and_play",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "打开Apple Music并播放"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "media.music_app_open_and_play",
            "recovery_input": {"app_name": "Spotify"},
            "recovery_risk_level": "low",
        }
    ) == "打开Spotify并播放"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "system.volume",
            "recovery_input": {"action": "set", "level": 35},
            "recovery_risk_level": "low",
        }
    ) == "把音量调到 35%"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "system.brightness",
            "recovery_input": {"action": "down"},
            "recovery_risk_level": "low",
        }
    ) == "屏幕暗一点"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "clipboard.read",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "读取剪贴板"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "clipboard.write",
            "recovery_input": {"text": "hello"},
            "recovery_risk_level": "low",
        }
    ) == "复制hello到剪贴板"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "screen.capture",
            "recovery_input": {"reason": "user asked"},
            "recovery_risk_level": "low",
        }
    ) == "截图当前屏幕"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.permissions",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "检查桌面权限"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.active_window",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "查看当前窗口"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.running_apps",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "查看正在运行的应用"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.windows",
            "recovery_input": {"app_name": "Google Chrome"},
            "recovery_risk_level": "low",
        }
    ) == "查看Google Chrome窗口"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.ui_elements",
            "recovery_input": {"role_filter": "button", "limit": 80},
            "recovery_risk_level": "low",
        }
    ) == "查看当前界面控件"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.current_page",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "查看当前网页"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "browser.extract_text",
            "recovery_input": {},
            "recovery_risk_level": "low",
        }
    ) == "读取当前网页正文"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.safe_shortcut",
            "recovery_input": {"action": "copy"},
            "recovery_risk_level": "low",
        }
    ) == "复制选中内容"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.safe_key",
            "recovery_input": {"action": "arrow_down", "repeat_count": 3},
            "recovery_risk_level": "low",
        }
    ) == "按下箭头3次"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.safe_scroll",
            "recovery_input": {"direction": "down", "pages": 2},
            "recovery_risk_level": "low",
        }
    ) == "向下滚动2页"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.safe_click",
            "recovery_input": {"x": 120, "y": 240},
            "recovery_risk_level": "low",
        }
    ) == "点击 120, 240"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.safe_type_text",
            "recovery_input": {"text": "hello"},
            "recovery_risk_level": "low",
        }
    ) == "输入hello"
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "desktop.click",
            "recovery_input": {"x": 120, "y": 240},
            "recovery_risk_level": "low",
        }
    ) == ""
    assert daily_desktop_recovery_prompt(
        {
            "desktop_permission_recovery": True,
            "recovery_tool": "app.open",
            "recovery_input": {"app_name": "Terminal"},
            "recovery_risk_level": "high",
        }
    ) == ""


def test_daily_desktop_metadata_tool_request_filters_retry_actions() -> None:
    metadata = {
        "desktop_permission_recovery": True,
        "desktop_permission_retry": True,
        "recovery_action_kind": "retry_original",
        "recovery_tool": "media.apple_music_play",
        "recovery_input": {"query": "超时空辉夜姬"},
    }

    assert daily_desktop_metadata_tool_request(metadata) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_play",
        "input": {"query": "超时空辉夜姬"},
        "source": "daily_desktop_metadata",
        "planning_reason": "structured_recovery_metadata",
    }
    assert daily_desktop_metadata_tool_request(metadata, ["media.apple_music_play"]) is not None
    assert daily_desktop_metadata_tool_request(metadata, ["app.open"]) is None
    assert daily_desktop_metadata_tool_request(
        {
            "desktop_permission_recovery": True,
            "desktop_permission_retry": True,
            "recovery_tool": "terminal.run",
            "recovery_input": {"command": "rm -rf /"},
        }
    ) is None


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
        "agent.tool.policy_decision",
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
    assert run_events[1]["payload"]["tool"] == "media.apple_music_play"
    assert run_events[1]["payload"]["decision"] == "allow"
    assert run_events[1]["payload"]["reason"] == "agent_tool_policy"
    assert run_events[1]["payload"]["policy_overlay"] is False
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
        "agent.tool.policy_decision",
        "tool.requested",
        "tool.started",
        "tool.completed",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert run_events[1]["payload"]["tool"] == "media.apple_music_play"
    assert run_events[1]["payload"]["decision"] == "allow"
    assert run_events[1]["payload"]["reason"] == "agent_tool_policy"
    assert run_events[1]["payload"]["policy_overlay"] is False
    assert run_events[-1]["payload"]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"


def test_main_chat_desktop_intent_records_permission_preflight_before_tool_execution() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    run_events: list[dict[str, Any]] = []
    broker = PermissionPreflightDesktopBroker(order)
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
        raise AssertionError("permission preflight desktop intent should not call model")

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
        run_id="run-main-chat-desktop-preflight",
        budget=budget,
    )

    assert str(result) == "已在 Apple Music 播放：超时空辉夜姬。"
    assert order == ["preflight", "tool"]
    assert [event["event"] for event in timeline] == [
        "agent.desktop.intent_planned",
        "agent.desktop.permission_preflight",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    preflight = timeline[1]
    assert preflight["tool"] == "media.apple_music_play"
    assert preflight["permission_targets"] == ["automation"]
    assert preflight["affected_tools"] == ["media.apple_music_play"]
    assert preflight["recovery_actions"] == [
        {
            "label": "打开自动化权限",
            "tool": "system.settings_open",
            "input": {"target": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        }
    ]
    assert [event["event_type"] for event in run_events[:2]] == [
        "agent.desktop.intent_planned",
        "agent.desktop.permission_preflight",
    ]
    assert run_events[1]["payload"]["diagnostic_route"] == "/yachiyo/readiness"
    assert "model.request.started" not in [event["event_type"] for event in run_events]


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
            "fallback_used": True,
            "fallback_result": {"ok": True, "data": {"app_name": "Music"}},
            "recovery_hints": [
                "Open Music.app once, confirm the track exists in the local library.",
                "Grant Automation permission in System Settings.",
            ],
            "recovery_actions": [
                {
                    "label": "打开 Apple Music",
                    "tool": "app.open",
                    "input": {"app_name": "Music"},
                    "permission_target": "music_app",
                    "risk_level": "low",
                },
                {
                    "label": "打开自动化权限",
                    "tool": "system.settings_open",
                    "input": {"target": "自动化权限"},
                    "permission_target": "automation",
                    "risk_level": "low",
                },
            ],
        },
    )

    assert "桌面操作未完成：Not authorized to send Apple events to Music." in result
    assert "缺少权限：music_app, automation" in result
    assert "你可以这样处理：" in result
    assert "Open Music.app once" in result
    assert "Grant Automation permission" in result
    assert "没能直接播放" not in result
    assert "可直接打开：打开 Apple Music、打开自动化权限。" in result


def test_main_chat_desktop_intent_summarizes_apple_music_search_fallback() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_play",
        {"query": "超时空辉夜姬"},
        {
            "ok": False,
            "error": "Music did not return a playable track",
            "permission_error": False,
            "fallback_used": True,
            "fallback": "apple_music_search",
            "fallback_result": {
                "ok": True,
                "action": "media.apple_music.search",
                "data": {
                    "query": "超时空辉夜姬",
                    "url": "https://music.apple.com/search?term=%E8%B6%85",
                },
            },
            "data": {
                "query": "超时空辉夜姬",
                "status": "not_found",
                "search_opened": True,
            },
        },
    )

    assert result == "没能直接播放 超时空辉夜姬，但已打开 Apple Music 搜索。"


def test_main_chat_desktop_intent_permission_failure_records_recovery_event() -> None:
    appended_events: list[dict[str, Any]] = []
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": []}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=1,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: {},
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
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )
    result_payload = {
        "ok": False,
        "error": "screen recording permission denied",
        "permission_error": True,
        "permission_targets": ["screen_recording"],
        "recovery_hints": ["Grant Screen Recording permission."],
        "recovery_actions": [
            {
                "label": "打开屏幕录制权限",
                "tool": "system.settings_open",
                "input": {"target": "屏幕录制权限"},
                "permission_target": "screen_recording",
                "risk_level": "low",
            }
        ],
    }
    expected_recovery_actions = [
        {
            **result_payload["recovery_actions"][0],
            "recovery_retry_input": {"reason": "user asked to capture the screen"},
            "recovery_retry_prompt": "截图当前屏幕",
            "recovery_retry_tool": "screen.capture",
            "retry_input": {"reason": "user asked to capture the screen"},
            "retry_prompt": "截图当前屏幕",
            "retry_tool": "screen.capture",
        }
    ]
    timeline = [
        _timeline(
            "agent.desktop.intent_planned",
            "screen.capture",
            tool="screen.capture",
            input_preview={"reason": "user asked to capture the screen"},
        ),
        _timeline(
            "agent.tool.call",
            "screen.capture",
            tool="screen.capture",
            result=result_payload,
        ),
    ]

    summary = loop._direct_daily_desktop_result(
        {"agent_id": MAIN_CHAT_AGENT_ID, "name": "Yachiyo"},
        "screen.capture",
        {"reason": "user asked to capture the screen"},
        timeline,
        run_id="run-screen-permission",
    )

    assert "桌面操作未完成：screen recording permission denied" in summary
    assert [event["event"] for event in timeline[-2:]] == [
        "agent.desktop.intent_completed",
        "agent.desktop.permission_recovery",
    ]
    recovery = timeline[-1]
    assert recovery["tool"] == "screen.capture"
    assert recovery["permission_targets"] == ["screen_recording"]
    assert recovery["affected_tools"] == ["screen.capture"]
    assert recovery["recovery_hints"][0] == "Grant Screen Recording permission."
    assert any("屏幕录制" in hint for hint in recovery["recovery_hints"])
    assert recovery["recovery_actions"] == expected_recovery_actions
    assert appended_events[-1]["event_type"] == "agent.desktop.permission_recovery"
    assert appended_events[-1]["payload"]["recovery_actions"] == expected_recovery_actions


def test_main_chat_desktop_intent_summarizes_apple_music_control() -> None:
    open_and_play = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_open_and_play",
        {},
        {
            "ok": True,
            "summary": "Opened Music and started playback",
            "data": {
                "control": "play",
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        },
    )
    open_and_play_fallback = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_open_and_play",
        {},
        {
            "ok": True,
            "summary": "Opened Music and attempted playback with media key fallback",
            "data": {
                "control": "play",
                "player_state": "unknown",
                "fallback": "system_media_key",
                "fallback_control": "toggle",
                "media_key": "Play/Pause",
                "playback_state_unverified": True,
            },
        },
    )
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
    next_track_fallback = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "media.apple_music_control",
        {"action": "next"},
        {
            "ok": True,
            "summary": "Apple Music next attempted via media key fallback",
            "data": {
                "control": "next",
                "player_state": "unknown",
                "fallback": "system_media_key",
                "fallback_control": "next",
                "media_key": "Next",
                "playback_state_unverified": True,
            },
        },
    )

    assert pause == "已暂停 Apple Music。"
    assert next_track == "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。"
    assert next_track_fallback == "已用媒体键尝试切到下一首 Apple Music。"
    assert open_and_play == "已打开 Apple Music 并开始播放。当前：超时空辉夜姬 - Yachiyo。"
    assert open_and_play_fallback == "已打开 Apple Music，并用媒体键尝试开始播放。"


def test_main_chat_desktop_intent_summarizes_system_volume() -> None:
    status = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.volume",
        {"action": "status"},
        {
            "ok": True,
            "summary": "System volume is 42%",
            "data": {"requested_action": "status", "level": 42, "muted": False},
        },
    )
    set_level = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.volume",
        {"action": "set", "level": 35},
        {
            "ok": True,
            "summary": "System volume set to 35%",
            "data": {"requested_action": "set", "old_level": 20, "level": 35, "muted": False},
        },
    )
    increased = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.volume",
        {"action": "up"},
        {
            "ok": True,
            "summary": "System volume increased from 40% to 50%",
            "data": {"requested_action": "up", "old_level": 40, "level": 50, "muted": False},
        },
    )
    muted = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.volume",
        {"action": "mute"},
        {
            "ok": True,
            "summary": "System volume muted",
            "data": {"requested_action": "mute", "old_level": 50, "level": 50, "muted": True},
        },
    )

    assert status == "当前系统音量是 42%。"
    assert set_level == "已把系统音量调到 35%。"
    assert increased == "已把系统音量从 40% 调高到 50%。"
    assert muted == "已将系统音量静音。"


def test_main_chat_desktop_intent_summarizes_system_brightness() -> None:
    increased = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.brightness",
        {"action": "up"},
        {
            "ok": True,
            "summary": "Display brightness increased",
            "data": {"requested_action": "up", "step": 2},
        },
    )
    decreased = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.brightness",
        {"action": "down", "step": 1},
        {
            "ok": True,
            "summary": "Display brightness decreased",
            "data": {"requested_action": "down", "step": 1},
        },
    )

    assert increased == "已调高屏幕亮度（2 格）。"
    assert decreased == "已调低屏幕亮度。"


def test_main_chat_desktop_intent_summarizes_system_display_sleep() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.display_sleep",
        {},
        {
            "ok": True,
            "summary": "Display sleep requested",
            "data": {"requested_action": "sleep"},
        },
    )

    assert result == "已让显示器睡眠。"


def test_main_chat_desktop_intent_summarizes_system_screen_saver_start() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "system.screen_saver_start",
        {},
        {
            "ok": True,
            "summary": "Screen saver start requested",
            "data": {"requested_action": "start"},
        },
    )

    assert result == "已启动屏幕保护程序。"


def test_main_chat_desktop_intent_summarizes_clipboard_write_without_echoing_text() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "clipboard.write",
        {"text": "047e43ac"},
        {
            "ok": True,
            "summary": "Copied 8 characters to clipboard",
            "data": {"text_length": 8, "platform": "macos"},
        },
    )

    assert result == "已复制 8 个字符到剪贴板。"
    assert "047e43ac" not in result


def test_main_chat_desktop_intent_summarizes_clipboard_read_preview() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "clipboard.read",
        {},
        {
            "ok": True,
            "summary": "Read 11 characters from clipboard",
            "data": {"text": "hello world", "text_length": 11, "truncated": False},
        },
    )
    empty = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "clipboard.read",
        {},
        {
            "ok": True,
            "summary": "Read 0 characters from clipboard",
            "data": {"text": "", "text_length": 0, "truncated": False},
        },
    )

    assert result == "剪贴板内容：hello world"
    assert empty == "剪贴板是空的。"


def test_main_chat_desktop_intent_summarizes_native_content_creation() -> None:
    note = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "notes.create",
        {"body": "hello"},
        {
            "ok": True,
            "summary": "Created note",
            "data": {"title": "hello", "body_length": 5},
        },
    )
    reminder = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "reminders.create",
        {"title": "开会", "due_at": "2026-06-25T15:00"},
        {
            "ok": True,
            "summary": "Created reminder",
            "data": {"title": "开会", "due_at": "2026-06-25T15:00"},
        },
    )
    calendar_event = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "calendar.create_event",
        {"title": "开会", "start_at": "2026-06-25T15:00", "end_at": "2026-06-25T16:00"},
        {
            "ok": True,
            "summary": "Created calendar event",
            "data": {"title": "开会", "start_at": "2026-06-25T15:00", "end_at": "2026-06-25T16:00"},
        },
    )

    assert note == "已创建备忘录：hello（5 个字符）。"
    assert reminder == "已创建提醒事项：开会（2026-06-25T15:00）。"
    assert calendar_event == "已创建日历事件：开会（2026-06-25T15:00 - 2026-06-25T16:00）。"


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


def test_main_chat_desktop_intent_summarizes_browser_current_page() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.current_page",
        {},
        {
            "ok": True,
            "summary": "Current browser page: ChatGPT",
            "data": {"title": "ChatGPT", "url": "https://chatgpt.com/"},
        },
    )
    failed = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.current_page",
        {},
        {
            "ok": False,
            "summary": "Chrome CDP unavailable",
            "data": {},
        },
    )

    assert result == "当前网页是 ChatGPT：https://chatgpt.com/。"
    assert failed == "桌面操作未完成：Chrome CDP unavailable。"


def test_main_chat_desktop_intent_summarizes_browser_extract_text_and_screenshot() -> None:
    text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.extract_text",
        {},
        {
            "ok": True,
            "summary": "Extracted 30 characters from browser page",
            "data": {"text": "Yachiyo desktop agent runtime"},
        },
    )
    summary_text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.extract_text",
        {},
        {
            "ok": True,
            "summary": "Extracted 30 characters from browser page",
            "data": {
                "text": (
                    "Yachiyo desktop agent runtime makes local tools observable.\n"
                    "Run Timeline records tool calls, approvals, and artifacts.\n"
                    "Agent Studio keeps workflow debugging available."
                )
            },
        },
        presentation="summary",
    )
    screenshot = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.screenshot",
        {},
        {
            "ok": True,
            "summary": "Captured current browser page",
            "data": {"path": "browser/current-page.png"},
        },
    )
    failed = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.extract_text",
        {},
        {
            "ok": False,
            "summary": "Chrome CDP unavailable",
            "data": {},
        },
    )

    assert text == "Yachiyo desktop agent runtime"
    assert summary_text == (
        "网页内容摘要：\n"
        "- Yachiyo desktop agent runtime makes local tools observable.\n"
        "- Run Timeline records tool calls, approvals, and artifacts.\n"
        "- Agent Studio keeps workflow debugging available."
    )
    assert screenshot == "已截取当前网页。"
    assert failed == "桌面操作未完成：Chrome CDP unavailable。"


def test_main_chat_desktop_intent_summarizes_browser_open_composites() -> None:
    text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.open_url_and_extract_text",
        {"url": "https://github.com"},
        {
            "ok": True,
            "summary": "Extracted 29 characters from browser page",
            "data": {"url": "https://github.com", "text": "GitHub: Let us build from here"},
        },
    )
    screenshot = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.open_url_and_screenshot",
        {"url": "https://github.com"},
        {
            "ok": True,
            "summary": "Opened browser page and captured screenshot",
            "data": {"url": "https://github.com", "path": "browser/current-page.png"},
        },
    )
    partial_text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.open_url_and_extract_text",
        {"url": "https://github.com"},
        {
            "ok": False,
            "summary": "Opened browser page but could not extract text",
            "permission_error": True,
            "permission_targets": ["chrome_cdp"],
            "fallback_result": {
                "open": {"ok": True, "data": {"url": "https://github.com"}},
                "extract_text": {"ok": False, "error": "Chrome CDP unavailable"},
            },
        },
    )

    assert text == "GitHub: Let us build from here"
    assert screenshot == "已打开网页并截取当前网页。"
    assert partial_text == (
        "已打开网页，但没能读取网页文本。 缺少权限：chrome_cdp。 "
        "你可以这样处理：启动或配置 Chrome DevTools/CDP 连接后再重试浏览器控制。"
    )


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


def test_main_chat_desktop_intent_summarizes_active_window() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.active_window",
        {},
        {
            "ok": True,
            "summary": "Active window: Google Chrome - ChatGPT",
            "data": {
                "app_name": "Google Chrome",
                "pid": 202,
                "title": "ChatGPT",
            },
        },
    )

    assert result == "当前前台窗口是 Google Chrome：ChatGPT。"


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


def test_main_chat_desktop_intent_summarizes_ui_elements() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.ui_elements",
        {"role_filter": "button", "limit": 80},
        {
            "ok": True,
            "summary": "Google Chrome UI elements: AXButton: Send",
            "data": {
                "app_name": "Google Chrome",
                "title": "ChatGPT",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "Send",
                        "enabled": True,
                        "center": {"x": 120, "y": 240},
                    },
                    {
                        "role": "AXTextField",
                        "description": "Message",
                        "enabled": True,
                        "center": {"x": 80, "y": 220},
                    },
                ],
                "count": 2,
            },
        },
    )

    assert result == "当前 Google Chrome 界面控件：Button Send（120, 240）; TextField Message（80, 220）。"


def test_main_chat_desktop_intent_summarizes_click_ui_element() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.click_ui_element",
        {"target": "发送", "role_filter": "button", "limit": 80, "click_count": 1},
        {
            "ok": True,
            "summary": "Clicked foreground UI element: Send",
            "data": {
                "x": 120,
                "y": 240,
                "click_count": 1,
                "target": "发送",
                "matched_label": "Send",
            },
        },
    )

    assert result == "已点击前台控件：Send（120, 240）。"


def test_main_chat_desktop_intent_summarizes_type_into_ui_element() -> None:
    result = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.type_into_ui_element",
        {"target": "搜索", "text": "yachiyo", "role_filter": "text", "limit": 80},
        {
            "ok": True,
            "summary": "Typed into foreground UI element: Search",
            "data": {
                "target": "搜索",
                "matched_label": "Search",
                "character_count": 7,
            },
        },
    )

    assert result == "已在前台控件 Search 输入文字（7 个字符）。"


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
                    "tool": "system.settings_open",
                    "input": {"target": "屏幕录制权限"},
                },
                {
                    "label": "打开自动化权限",
                    "tool": "system.settings_open",
                    "input": {"target": "自动化权限"},
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
            "recovery_actions": [
                {
                    "label": "打开应用程序文件夹",
                    "tool": "desktop.open_path",
                    "input": {"path": "/Applications"},
                    "permission_target": "app_not_found",
                    "risk_level": "low",
                },
                {
                    "label": "打开 App Store",
                    "tool": "app.open",
                    "input": {"app_name": "App Store"},
                    "permission_target": "app_not_found",
                    "risk_level": "low",
                },
            ],
        },
    )
    app_quit = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.quit",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Quit Slack",
            "data": {"app_name": "Slack", "running": False},
        },
    )
    app_quit_still_running = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.quit",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Sent quit request to Slack",
            "data": {"app_name": "Slack", "running": True},
        },
    )
    app_focus_window = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.focus_window",
        {"app_name": "Slack", "title_contains": "general"},
        {
            "ok": True,
            "summary": "Focused Slack window: general",
            "data": {"app_name": "Slack", "window_title": "general"},
        },
    )
    safe_shortcut = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_shortcut",
        {"action": "copy"},
        {
            "ok": True,
            "summary": "Executed safe shortcut: copy",
            "data": {"shortcut_action": "copy", "key": "c", "modifiers": ["command"]},
        },
    )
    safe_reopen_closed_tab = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_shortcut",
        {"action": "reopen_closed_tab"},
        {
            "ok": True,
            "summary": "Executed safe shortcut: reopen closed tab",
            "data": {
                "shortcut_action": "reopen_closed_tab",
                "key": "t",
                "modifiers": ["command", "shift"],
            },
        },
    )
    safe_close_tab = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_shortcut",
        {"action": "close_tab"},
        {
            "ok": True,
            "summary": "Executed safe shortcut: close tab",
            "data": {"shortcut_action": "close_tab", "key": "w", "modifiers": ["command"]},
        },
    )
    safe_next_tab = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_shortcut",
        {"action": "next_tab"},
        {
            "ok": True,
            "summary": "Executed safe shortcut: next tab",
            "data": {"shortcut_action": "next_tab", "key": "]", "modifiers": ["command", "shift"]},
        },
    )
    safe_previous_tab = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_shortcut",
        {"action": "previous_tab"},
        {
            "ok": True,
            "summary": "Executed safe shortcut: previous tab",
            "data": {"shortcut_action": "previous_tab", "key": "[", "modifiers": ["command", "shift"]},
        },
    )
    safe_key = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_key",
        {"action": "arrow_down", "repeat_count": 3},
        {
            "ok": True,
            "summary": "Pressed safe foreground key: Down Arrow x3",
            "data": {
                "key_action": "arrow_down",
                "key_label": "Down Arrow",
                "key_code": 125,
                "repeat_count": 3,
                "explicit_user_key": True,
            },
        },
    )
    safe_type_text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_type_text",
        {"text": "你好八千代"},
        {
            "ok": True,
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": 5, "explicit_user_text": True},
        },
    )
    app_open_safe_type_text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Notes",
                "foreground_action": "safe_type_text",
                "character_count": 5,
                "explicit_user_text": True,
            },
        },
    )
    app_focus_safe_shortcut = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.focus_and_safe_shortcut",
        {"app_name": "Slack", "action": "paste"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Slack",
                "foreground_action": "safe_shortcut",
                "shortcut_action": "paste",
            },
        },
    )
    app_open_new_document = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_shortcut",
        {"app_name": "Microsoft Word", "action": "new_document"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Microsoft Word",
                "foreground_action": "safe_shortcut",
                "shortcut_action": "new_document",
            },
        },
    )
    app_open_new_reminder = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_shortcut",
        {"app_name": "Reminders", "action": "new_reminder"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Reminders",
                "foreground_action": "safe_shortcut",
                "shortcut_action": "new_reminder",
            },
        },
    )
    app_open_new_event = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_shortcut",
        {"app_name": "Calendar", "action": "new_event"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Calendar",
                "foreground_action": "safe_shortcut",
                "shortcut_action": "new_event",
            },
        },
    )
    app_open_safe_key = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_key",
        {"app_name": "Google Chrome", "action": "tab"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Google Chrome",
                "foreground_action": "safe_key",
                "key_action": "tab",
                "key_label": "Tab",
                "key_code": 48,
                "repeat_count": 1,
                "explicit_user_key": True,
            },
        },
    )
    app_open_safe_scroll = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_scroll",
        {"app_name": "Google Chrome", "direction": "down", "pages": 2},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Google Chrome",
                "foreground_action": "safe_scroll",
                "direction": "down",
                "pages": 2,
                "explicit_user_scroll": True,
            },
        },
    )
    app_open_safe_click = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_click",
        {"app_name": "Google Chrome", "x": 120, "y": 240},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Google Chrome",
                "foreground_action": "safe_click",
                "x": 120,
                "y": 240,
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        },
    )
    app_open_click_ui_element = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_click_ui_element",
        {"app_name": "Google Chrome", "target": "登录"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Google Chrome",
                "foreground_action": "click_ui_element",
                "target": "登录",
                "matched_label": "登录",
                "x": 120,
                "y": 240,
                "click_count": 1,
            },
        },
    )
    app_open_type_into_ui_element = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_type_into_ui_element",
        {"app_name": "Google Chrome", "target": "地址", "text": "github.com"},
        {
            "ok": True,
            "summary": "Focused app and completed foreground action",
            "data": {
                "app_name": "Google Chrome",
                "foreground_action": "type_into_ui_element",
                "target": "地址",
                "matched_label": "Address",
                "character_count": 10,
            },
        },
    )
    app_open_safe_type_text_failed = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_type_text",
        {"app_name": "Notes", "text": "hello"},
        {
            "ok": False,
            "action": "app.open_and_safe_type_text",
            "permission_error": True,
            "permission_targets": ["accessibility"],
            "fallback_result": {
                "open": {"ok": True, "action": "app.open"},
                "focus": {"ok": True, "action": "app.focus"},
                "safe_type_text": {"ok": False, "action": "desktop.safe_type_text"},
            },
        },
    )
    app_open_safe_key_failed = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.open_and_safe_key",
        {"app_name": "Google Chrome", "action": "tab"},
        {
            "ok": False,
            "action": "app.open_and_safe_key",
            "permission_error": True,
            "permission_targets": ["accessibility"],
            "recovery_actions": [
                {
                    "label": "打开辅助功能权限",
                    "tool": "system.settings_open",
                    "input": {"target": "辅助功能权限"},
                    "permission_target": "accessibility",
                    "risk_level": "low",
                }
            ],
            "fallback_result": {
                "open": {"ok": True, "action": "app.open"},
                "focus": {"ok": True, "action": "app.focus"},
                "safe_key": {"ok": False, "action": "desktop.safe_key"},
            },
        },
    )
    safe_click = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_click",
        {"x": 120, "y": 240},
        {
            "ok": True,
            "summary": "Clicked explicit foreground coordinate at (120, 240)",
            "data": {
                "x": 120,
                "y": 240,
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        },
    )
    safe_scroll = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.safe_scroll",
        {"direction": "down", "pages": 2},
        {
            "ok": True,
            "summary": "Scrolled foreground desktop down 2 pages",
            "data": {
                "direction": "down",
                "pages": 2,
                "key_code": 121,
                "explicit_user_scroll": True,
            },
        },
    )
    app_show = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.show",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Showed Slack",
            "data": {"app_name": "Slack", "show_status": "shown"},
        },
    )
    app_show_launched = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.show",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Launched and showed Slack",
            "data": {"app_name": "Slack", "show_status": "launched"},
        },
    )
    app_hide = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.hide",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Hid Slack",
            "data": {"app_name": "Slack"},
        },
    )
    app_minimize = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "app.minimize",
        {"app_name": "Slack"},
        {
            "ok": True,
            "summary": "Minimized Slack",
            "data": {"app_name": "Slack", "window_count": 2},
        },
    )
    close_window = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.close_window",
        {},
        {"ok": True, "summary": "Closed the foreground window"},
    )
    minimize_window = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.minimize_window",
        {},
        {"ok": True, "summary": "Minimized the foreground window"},
    )
    hide_app = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.hide_app",
        {},
        {"ok": True, "summary": "Hid the foreground app"},
    )
    show_all_apps = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.show_all_apps",
        {},
        {"ok": True, "summary": "Showed hidden apps", "data": {"shown_app_count": 2}},
    )
    browser_click = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.click",
        {"selector": "text=登录"},
        {
            "ok": True,
            "summary": "Clicked browser selector: text=登录",
            "data": {"selector": "text=登录", "label": "登录"},
        },
    )
    browser_click_point = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.click",
        {"selector": "point=120,240"},
        {
            "ok": True,
            "summary": "Clicked browser selector: point=120,240",
            "data": {"selector": "point=120,240", "x": 120, "y": 240},
        },
    )
    browser_type_text = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.type_text",
        {"selector": "input[type=\"search\"]", "text": "yachiyo"},
        {
            "ok": True,
            "summary": "Typed text into browser selector: input[type=\"search\"]",
            "data": {"selector": "input[type=\"search\"]", "length": 7},
        },
    )
    browser_type_text_point = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "browser.type_text",
        {"selector": "point=120,240", "text": "hello"},
        {
            "ok": True,
            "summary": "Typed text into browser selector: point=120,240",
            "data": {"selector": "point=120,240", "length": 5, "x": 120, "y": 240},
        },
    )
    submit_foreground = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "desktop.submit_foreground",
        {"action": "send"},
        {
            "ok": True,
            "summary": "Submitted foreground send action",
            "data": {"submit_action": "send"},
        },
    )
    terminal_run = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "terminal.run",
        {"command": "printf ok"},
        {"ok": True, "stdout": "ok\n", "stderr": "", "returncode": 0},
    )
    terminal_failed = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "terminal.run",
        {"command": "false"},
        {"ok": False, "stdout": "", "stderr": "failed", "returncode": 1},
    )

    assert app_unverified == "已向 macOS 发送打开 Google Chrome 的请求，但未能确认它已启动。"
    assert browser_fallback == "已用系统浏览器打开网页：https://example.com。"
    assert app_quit == "已退出 Slack。"
    assert app_quit_still_running == "已向 Slack 发送退出请求，但它可能仍在运行。"
    assert app_focus_window == "已切换到 Slack 的 general 窗口。"
    assert safe_shortcut == "已复制选中内容。"
    assert safe_reopen_closed_tab == "已重新打开关闭的标签页。"
    assert safe_close_tab == "已关闭标签页。"
    assert safe_next_tab == "已切到下一个标签页。"
    assert safe_previous_tab == "已切到上一个标签页。"
    assert safe_key == "已按下箭头（3 次）。"
    assert safe_type_text == "已向前台输入文字（5 个字符）。"
    assert app_open_safe_type_text == "已打开 Notes 并输入文字（5 个字符）。"
    assert app_focus_safe_shortcut == "已切到 Slack 并粘贴。"
    assert app_open_new_document == "已打开 Microsoft Word 并新建文档。"
    assert app_open_new_reminder == "已打开 Reminders 并新建提醒事项。"
    assert app_open_new_event == "已打开 Calendar 并新建日程。"
    assert app_open_safe_key == "已打开 Google Chrome 并按Tab。"
    assert app_open_safe_scroll == "已打开 Google Chrome 并向下滚动前台界面（2 页）。"
    assert app_open_safe_click == "已打开 Google Chrome 并点击前台位置：120, 240。"
    assert app_open_click_ui_element == "已打开 Google Chrome 并点击前台控件：登录（120, 240）。"
    assert app_open_type_into_ui_element == "已打开 Google Chrome 并在前台控件 Address 输入文字（10 个字符）。"
    assert app_open_safe_type_text_failed == (
        "已打开 Notes，但没能输入文字。 缺少权限：accessibility。"
        " 你可以这样处理：在 macOS 系统设置 > 隐私与安全性 > 辅助功能 中允许 Oha-Yachiyo 或当前运行环境。"
    )
    assert app_open_safe_key_failed == (
        "已打开 Google Chrome，但没能按Tab。 缺少权限：accessibility。"
        " 你可以这样处理：在 macOS 系统设置 > 隐私与安全性 > 辅助功能 中允许 Oha-Yachiyo 或当前运行环境。"
        "可直接打开：打开辅助功能权限。"
    )
    assert safe_click == "已点击前台位置：120, 240。"
    assert safe_scroll == "已向下滚动前台界面（2 页）。"
    assert app_show == "已显示 Slack。"
    assert app_show_launched == "已打开并显示 Slack。"
    assert app_hide == "已隐藏 Slack。"
    assert app_minimize == "已最小化 Slack。"
    assert close_window == "已关闭当前窗口。"
    assert minimize_window == "已最小化当前窗口。"
    assert hide_app == "已隐藏当前应用。"
    assert show_all_apps == "已显示所有隐藏应用。"
    assert browser_click == "已点击网页元素：登录。"
    assert browser_click_point == "已点击网页位置：120, 240。"
    assert browser_type_text == "已在网页元素 input[type=\"search\"]输入文字（7 个字符）。"
    assert browser_type_text_point == "已在网页位置：120, 240 输入文字（5 个字符）。"
    assert submit_foreground == "已确认发送前台内容。"
    assert terminal_run == "已运行命令：printf ok。\n输出：ok"
    assert terminal_failed == "命令执行失败：false。 退出码：1。 stderr：failed"
    assert app_not_found == (
        "已尝试启动 Missing App，但 macOS 没找到这个应用。 "
        "你可以这样处理：确认应用已安装，或换用精确应用名。"
        "可直接打开：打开应用程序文件夹、打开 App Store。"
    )


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
                "content": (
                    'Tool result for media.apple_music_open_and_play: '
                    '{"ok": true, "data": {"app_name": "Music"}}'
                ),
            }
        )

    def call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        order.append("model")
        assert "Tool result for media.apple_music_open_and_play" in model_messages[-1]["content"]
        return {"role": "assistant", "content": "已打开并播放 Music。"}

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
                    "media.apple_music_open_and_play",
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

    assert str(result) == "已打开并播放 Music。"
    assert order == ["tool", "model"]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "media.apple_music_open_and_play",
            "input": {},
        }
    ]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-main-chat"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert timeline[0] == {
        "event": "agent.desktop.intent_planned",
        "detail": "media.apple_music_open_and_play",
        "tool": "media.apple_music_open_and_play",
        "status": "planned",
        "source": "daily_desktop_intent",
        "planning_reason": "clear_daily_desktop_intent",
        "input_preview": {},
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


def test_main_chat_daily_sequence_resume_summarizes_approved_and_remaining_tools() -> None:
    budget = FakeBudget()
    timeline = [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "app.open_and_hotkey",
            "tool": "app.open_and_hotkey",
            "status": "planned",
            "source": "daily_desktop_intent",
            "planning_reason": "clear_daily_desktop_intent",
            "input_preview": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
        },
        {
            "event": "agent.desktop.intent_planned",
            "detail": "desktop.safe_shortcut",
            "tool": "desktop.safe_shortcut",
            "status": "planned",
            "source": "daily_desktop_intent",
            "planning_reason": "clear_daily_desktop_intent",
            "input_preview": {"action": "copy"},
        },
        {
            "event": "agent.desktop.intent_approval_required",
            "detail": "app.open_and_hotkey",
            "tool": "app.open_and_hotkey",
            "status": "approval_required",
            "source": "daily_desktop_intent",
            "reason": "tool_policy_requires_approval",
            "input_preview": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
        },
        {
            "event": "agent.tool.call",
            "detail": "app.open_and_hotkey",
            "input_preview": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
            "result": {
                "ok": True,
                "action": "app.open_and_hotkey",
                "data": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
            },
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.safe_shortcut",
            "input_preview": {"action": "copy"},
            "result": {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "data": {"action": "copy"},
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
            "tool_policy": {
                "allowed_tools": [
                    "app.open_and_hotkey",
                    "desktop.safe_shortcut",
                ]
            }
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
            AssertionError("approved daily sequence resume should not call the model")
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
            AssertionError("approved daily sequence resume should not re-run the planner")
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
            {"role": "user", "content": "打开 Notes，然后按 Command+L，再复制"},
            {"role": "user", "content": "Tool result for app.open_and_hotkey: ok"},
        ],
        start_iteration=0,
        run_id="run-sequence-resume",
        budget=budget,
    )

    assert str(result) == "已打开 Notes 并发送快捷键：Command+L。 已复制选中内容。"
    assert timeline[-1]["event"] == "agent.desktop.intent_completed"
    assert timeline[-1]["tools"] == ["app.open_and_hotkey", "desktop.safe_shortcut"]
    assert [step["tool"] for step in timeline[-1]["steps"]] == [
        "app.open_and_hotkey",
        "desktop.safe_shortcut",
    ]
    assert appended_events[-1]["event_type"] == "agent.desktop.intent_completed"
    assert appended_events[-1]["payload"]["summary"] == str(result)


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
        },
        {
            "run_id": "run-music",
            "event_type": "agent.tool.policy_decision",
            "payload": {
                "tool": "media.apple_music_play",
                "status": "allowed",
                "decision": "allow",
                "source": "daily_desktop_intent",
                "reason": "agent_tool_policy",
                "policy_scope": "daily_desktop",
                "policy_overlay": False,
                "input_preview": {"query": "超时空辉夜姬"},
                "allowed_tools": [
                    "media.apple_music_play",
                    "screen.capture",
                    "desktop.active_window",
                ],
                "planning_reason": "clear_daily_desktop_intent",
            },
        },
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
