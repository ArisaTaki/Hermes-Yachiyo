"""Tests for custom API Agent loop split out of the legacy runtime."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime import custom_api_agent as custom_api_agent_module
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
from apps.shell.agent.runtime.tool_approvals import ToolPendingApprovalBuilder
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_requests import normalize_tool_name
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES, PolicyGate
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import (
    planner_direct_tool_requests,
    planner_tool_requests,
)
from apps.shell.yachiyo_agent.planner_projection import planner_selection_payload


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


def _private_runtime_loop(
    *,
    append_run_event=None,
) -> RuntimeCustomApiAgentLoop:
    return RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": []}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=1,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: {},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda _message: "",
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )


_PLANNER_EVENT_TYPES = {
    "agent.intent.selected",
    "agent.plan.created",
    "agent.plan.step",
    "agent.plan.selection",
    "agent.replan.requested",
    "agent.task.todo.updated",
    "agent.task.checkpoint.updated",
}


def _non_planner_timeline_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in timeline
        if event.get("event") not in _PLANNER_EVENT_TYPES
    ]


def _non_planner_run_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event_type") not in _PLANNER_EVENT_TYPES
    ]


def _planner_selection_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in timeline if event.get("event") == "agent.plan.selection"]


def test_recovery_actions_projects_retry_input_contract_fields() -> None:
    retry_input_schema = {
        "type": "object",
        "required": ["x", "y"],
        "properties": {
            "x": {"type": "number", "minimum": 0},
            "y": {"type": "number", "minimum": 0},
        },
    }

    actions = custom_api_agent_module._recovery_actions(
        {
            "recovery_actions": [
                {
                    "label": "截取屏幕重新定位控件",
                    "tool": "screen.capture",
                    "input": {"reason": "capture before coordinate click"},
                    "permission_target": "screen_observation",
                    "risk_level": "low",
                    "retry_tool": "desktop.click",
                    "recovery_retry_tool": "desktop.click",
                    "retry_input": {"click_count": 1},
                    "recovery_retry_input": {"click_count": 1},
                    "retry_input_schema": retry_input_schema,
                    "recovery_retry_input_schema": retry_input_schema,
                    "retry_input_source": "screen_capture_artifact",
                    "recovery_retry_input_source": "screen_capture_artifact",
                    "retry_artifact_tool": "screen.capture",
                    "recovery_retry_artifact_tool": "screen.capture",
                    "retry_artifact_kind": "image",
                    "recovery_retry_artifact_kind": "image",
                    "followup_tool": "desktop.type_text",
                    "recovery_followup_tool": "desktop.type_text",
                    "followup_input": {
                        "text_source": "original_request",
                        "character_count": 5,
                    },
                    "recovery_followup_input": {
                        "text_source": "original_request",
                        "character_count": 5,
                    },
                    "required_retry_fields": ["x", "y"],
                    "recommended_tools": ["screen.capture", "desktop.click", "desktop.type_text"],
                    "target": "Send",
                }
            ]
        }
    )

    assert actions == [
        {
            "label": "截取屏幕重新定位控件",
            "tool": "screen.capture",
            "input": {"reason": "capture before coordinate click"},
            "permission_target": "screen_observation",
            "risk_level": "low",
            "retry_tool": "desktop.click",
            "recovery_retry_tool": "desktop.click",
            "retry_input": {"click_count": 1},
            "recovery_retry_input": {"click_count": 1},
            "retry_input_schema": retry_input_schema,
            "recovery_retry_input_schema": retry_input_schema,
            "retry_input_source": "screen_capture_artifact",
            "recovery_retry_input_source": "screen_capture_artifact",
            "retry_artifact_tool": "screen.capture",
            "recovery_retry_artifact_tool": "screen.capture",
            "retry_artifact_kind": "image",
            "recovery_retry_artifact_kind": "image",
            "followup_tool": "desktop.type_text",
            "recovery_followup_tool": "desktop.type_text",
            "followup_input": {
                "text_source": "original_request",
                "character_count": 5,
            },
            "recovery_followup_input": {
                "text_source": "original_request",
                "character_count": 5,
            },
            "required_retry_fields": ["x", "y"],
            "recommended_tools": ["screen.capture", "desktop.click", "desktop.type_text"],
        }
    ]


def test_daily_desktop_sequence_summary_includes_runtime_readiness_skips() -> None:
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": []}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=1,
        operating_doctrine="",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: {},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda _message: "",
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=agent_runtime.AgentRuntimeError,
    )
    requests = [
        {
            "tool": "desktop.inspect_app",
            "input": {"app_name": "PixelForge"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "tool": "app.open_and_click_ui_element",
            "input": {"app_name": "PixelForge", "target": "登录"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.inspect_app",
            input_preview={"app_name": "PixelForge"},
            result={
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
            },
        ),
        _timeline(
            "agent.tool.skipped",
            "app.open_and_click_ui_element",
            input_preview={"app_name": "PixelForge", "target": "登录"},
            result={
                "ok": False,
                "skipped": True,
                "blocked_by_runtime_readiness": True,
                "tool": "app.open_and_click_ui_element",
                "error": "app_not_found",
                "blocking_conditions": ["app_not_found", "foreground_not_ready"],
                "source_tool": "desktop.inspect_app",
                "source_summary": "No installed app matched PixelForge",
                "recovery_actions": [
                    {
                        "label": "重新发现应用",
                        "tool": "desktop.list_apps",
                        "input": {"query": "PixelForge", "limit": 20},
                        "permission_target": "app_discovery",
                        "risk_level": "low",
                    }
                ],
            },
        ),
    ]

    result = loop._direct_daily_desktop_sequence_result(
        requests,
        timeline,
        tool_timeline_start=0,
    )

    assert result == (
        "桌面操作已暂停：前置检查未确认目标应用可接收前台输入："
        "app_not_found, foreground_not_ready。No installed app matched PixelForge。"
        "可直接打开：重新发现应用。"
    )
    completed = next(
        event for event in timeline if event.get("event") == "agent.desktop.intent_completed"
    )
    assert completed["event"] == "agent.desktop.intent_completed"
    assert completed["result"]["blocked_by_runtime_readiness"] is True
    assert completed["steps"][-1]["tool"] == "app.open_and_click_ui_element"
    recovery = next(
        event for event in timeline if event.get("event") == "agent.desktop.permission_recovery"
    )
    assert recovery["recovery_actions"][0]["tool"] == "desktop.list_apps"


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

    def denied(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        trace: dict[str, Any] | None = None,
    ) -> None:
        self._append(run_id, "agent.tool.denied", tool_name, input_preview, "denied", **(trace or {}))

    def requested(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
        trace: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            run_id,
            "tool.requested",
            tool_name,
            input_preview,
            "requested",
            approved=approved,
            **(trace or {}),
        )

    def failed(self, run_id: str, tool_name: str, input_preview: Any, **kwargs: Any) -> None:
        trace = kwargs.get("trace") if isinstance(kwargs.get("trace"), dict) else {}
        self._append(run_id, "tool.failed", tool_name, input_preview, "failed", **trace)

    def started(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        *,
        approved: bool = False,
        trace: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            run_id,
            "tool.started",
            tool_name,
            input_preview,
            "running",
            approved=approved,
            **(trace or {}),
        )

    def result(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
        trace: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            run_id,
            "tool.completed" if tool_result.get("ok") else "tool.failed",
            tool_name,
            input_preview,
            "completed" if tool_result.get("ok") else "failed",
            approved=approved,
            output_preview=tool_result,
            **(trace or {}),
        )

    def agent_tool_call(
        self,
        run_id: str,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
        *,
        approved: bool = False,
        trace: dict[str, Any] | None = None,
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
                    **(trace or {}),
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
    assert "TaskIntent" in calls[0]["messages"][0]["content"]
    assert "discover -> act -> verify" in calls[0]["messages"][0]["content"]
    assert "choose capabilities before app-specific rules" in calls[0]["messages"][0]["content"]
    assert "Daily entrypoint operating manual" in calls[0]["messages"][0]["content"]
    assert "planner decisions, tool attempts, approvals, artifacts, failures" in calls[0]["messages"][0]["content"]
    assert "approval cards and pause/resume execution" in calls[0]["messages"][0]["content"]
    assert "After a failed tool result, read the error and hint" in calls[0]["messages"][0]["content"]
    assert "do not retry the same unchanged failing request" in calls[0]["messages"][0]["content"]
    assert "not as fixed branches that must be prewritten" in calls[0]["messages"][0]["content"]
    assert (
        "Do not answer with recipes like 'you can open the app yourself'"
        in calls[0]["messages"][0]["content"]
    )
    assert "discover available applications/windows/UI first" in calls[0]["messages"][0]["content"]
    assert (
        "prefer data.analyze for straightforward CSV/TSV/JSON/JSONL/XLSX/text-table reports, "
        "CSV summaries, HTML reports, and simple chart artifacts"
        in calls[0]["messages"][0]["content"]
    )
    assert "Resolve arbitrary app names through app/window/UI discovery" in calls[0]["messages"][0]["content"]
    assert "instead of requiring app-specific aliases or manual user steps" in calls[0]["messages"][0]["content"]
    assert "memory.add" in calls[0]["messages"][0]["content"]
    assert "future_task.schedule" in calls[0]["messages"][0]["content"]
    assert "prefer structured desktop tools" in calls[0]["messages"][0]["content"]
    assert "desktop.list_apps" in calls[0]["messages"][0]["content"]
    assert "uncertain app names to desktop.list_apps before app.open" in calls[0]["messages"][0]["content"]
    assert "prefer app-scoped foreground tools" in calls[0]["messages"][0]["content"]
    assert "so Runtime can bind the action to the target app" in calls[0]["messages"][0]["content"]
    assert "app.open_and_safe_shortcut or app.focus_and_safe_shortcut when app-scoped tools are allowed" in (
        calls[0]["messages"][0]["content"]
    )
    assert "app.open/app.focus followed by desktop.safe_shortcut only as a compatibility fallback" in calls[0][
        "messages"
    ][0]["content"]
    assert "Do not default song search or playback queries to media.apple_music_play" in (
        calls[0]["messages"][0]["content"]
    )
    assert "treat the media app as a discoverable desktop resource" in (
        calls[0]["messages"][0]["content"]
    )
    assert "Apple Music-specific tools are compatibility fallbacks" in (
        calls[0]["messages"][0]["content"]
    )
    assert "map 'play <song>'" not in calls[0]["messages"][0]["content"]
    assert "prefer structured browser tools" in calls[0]["messages"][0]["content"]
    assert (
        "Do not replace these structured desktop or browser actions with terminal.run"
        in calls[0]["messages"][0]["content"]
    )
    assert timeline[-1] == {"event": "agent.model.response", "detail": "final answer"}


def _runtime_planner_guidance_prompt(prompt: str, allowed_tools: list[str]) -> str:
    budget = FakeBudget()
    calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local/",
            "model": "test-model",
            "api_key": "key",
        },
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": allowed_tools}},
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: 0 if not isinstance(value, int) else value,
        max_tool_iterations=3,
        operating_doctrine="Follow approval gates.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, messages, **_kwargs: calls.append(
            list(messages)
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
        {"name": "Planner"},
        prompt,
        broker=object(),
        timeline=timeline,
        artifacts=[],
        run_id="run-planner-guidance",
    )

    assert str(result) == "final answer"
    return calls[0][0]["content"]


def test_custom_api_agent_loop_injects_runtime_planner_guidance_for_data_analysis() -> None:
    system_prompt = _runtime_planner_guidance_prompt(
        "请分析 sales.csv 并输出数据分析报告",
        ["workspace.read", "terminal.run", "artifact.write"],
    )

    assert "Runtime planner guidance" in system_prompt
    assert "discover -> act -> verify" in system_prompt
    assert "Daily entrypoint operating manual" in system_prompt
    assert "intent to capabilities before choosing concrete tools" in system_prompt
    assert "Treat mounted Skills as execution manuals" in system_prompt
    assert "After a failed tool result, read the error and hint" in system_prompt
    assert "approval cards and pause/resume execution" in system_prompt
    assert "legacy tool mapping in the Chat prompt is compatibility reference only" in system_prompt
    assert "not as fixed branches that must be prewritten" in system_prompt
    assert "selected intent=data_analysis" in system_prompt
    assert "workspace.read -> terminal.run -> artifact.write" in system_prompt
    assert "artifact expected=analysis-report.md" in system_prompt
    assert "route to Studio=yes" in system_prompt
    assert "2. Run reproducible data analysis: terminal.run" in system_prompt
    assert "action=run_python_analysis" in system_prompt
    assert "approval required" in system_prompt
    assert "approval gates still apply" in system_prompt


def test_custom_api_agent_loop_guides_report_generation_toward_artifacts() -> None:
    system_prompt = _runtime_planner_guidance_prompt(
        "请根据现有文档写一份项目报告",
        ["workspace.list", "artifact.write"],
    )

    assert "selected intent=report_generation" in system_prompt
    assert "workspace.list -> artifact.write" in system_prompt
    assert "artifact expected=report.md" in system_prompt
    assert "1. Gather available context: workspace.list" in system_prompt
    assert "2. Write report artifact: artifact.write" in system_prompt
    assert "Use available tools to execute the request" in system_prompt


def test_custom_api_agent_loop_guides_desktop_tasks_to_app_scoped_operation_path() -> None:
    system_prompt = _runtime_planner_guidance_prompt(
        "打开 PixelForge 并点击导出按钮",
        [
            "desktop.list_apps",
            "app.open_and_click_ui_element",
            "app.open",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
    )

    assert "selected intent=desktop_operation" in system_prompt
    assert "app.open_and_click_ui_element -> desktop.ui_elements" in system_prompt
    assert "Follow the planned tool path in order" in system_prompt
    assert "do not replace app-scoped app.*_and_* foreground tools" in system_prompt
    assert "unless the app-scoped tool is unavailable" in system_prompt


def test_custom_api_agent_loop_preserves_post_mutation_ui_verification_requests() -> None:
    requests = [
        {
            "tool": "desktop.inspect_app",
            "input": {"app_name": "Notion", "open_if_needed": True, "focus": True},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "tool": "desktop.click_ui_element",
            "input": {"target": "New Page"},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "tool": "desktop.ui_elements",
            "input": {"limit": 80},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]

    filtered = custom_api_agent_module._drop_trailing_daily_desktop_verify_requests(requests)

    assert [request["tool"] for request in filtered] == [
        "desktop.inspect_app",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]


def test_custom_api_agent_loop_still_drops_unmarked_trailing_verify_requests() -> None:
    requests = [
        {"tool": "desktop.list_apps", "input": {"query": "Notes"}},
        {"tool": "app.open", "input": {"app_name": "Notes"}},
        {"tool": "desktop.ui_elements", "input": {"limit": 80}},
    ]

    filtered = custom_api_agent_module._drop_trailing_daily_desktop_verify_requests(requests)

    assert [request["tool"] for request in filtered] == ["desktop.list_apps", "app.open"]


def test_custom_api_agent_loop_guides_code_tasks_without_bypassing_approval() -> None:
    system_prompt = _runtime_planner_guidance_prompt(
        "请检查这个仓库代码并运行测试",
        ["workspace.list", "terminal.run", "artifact.write"],
    )

    assert "selected intent=code_task" in system_prompt
    assert "workspace.list -> terminal.run -> artifact.write" in system_prompt
    assert "route to Studio=yes" in system_prompt
    assert "inspect the workspace before shell execution" in system_prompt
    assert "only when the plan contains a concrete command" in system_prompt
    assert "1. Inspect workspace: workspace.list" in system_prompt
    assert "2. Run code diagnostic: terminal.run" in system_prompt
    assert "terminal execution remains approval-gated" in system_prompt
    assert "3. Write result artifact: artifact.write" in system_prompt
    assert "approval gates still apply" in system_prompt


def test_custom_api_agent_loop_guides_workflow_and_group_runs_as_studio_handoffs() -> None:
    workflow_prompt = RuntimeCustomApiAgentLoop._runtime_planner_guidance(
        "运行 Daily Summary workflow",
        ["workflow.run", "group.run", "artifact.write"],
    )
    group_prompt = RuntimeCustomApiAgentLoop._runtime_planner_guidance(
        "让研究员和写作者两个 Agent 协作，研究 Hermes 和 Hanako 的差异并产出报告",
        ["agent.group_run", "artifact.write"],
    )

    assert "selected intent=workflow_orchestration" in workflow_prompt
    assert "planned tool path=workflow.run" in workflow_prompt
    assert "route to Studio=yes" in workflow_prompt
    assert "Studio orchestration handoff: this is an Agent Studio Workflow plan" in workflow_prompt
    assert "not a normal model-only recipe" in workflow_prompt
    assert "do not claim the workflow or group run completed" in workflow_prompt
    assert "concrete run snapshot/run id" in workflow_prompt

    assert "selected intent=multi_agent" in group_prompt
    assert "planned tool path=agent.group_run" in group_prompt
    assert "Studio orchestration handoff: this is an Agent Studio GroupRun plan" in group_prompt
    assert "Preserve the planner intent, target, approvals, artifacts, and timeline context" in group_prompt


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


def test_custom_api_agent_loop_prefetches_runtime_planner_data_source_before_model() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "请分析 data/sales.csv 并输出报告"}]

    def fake_run_tool_requests(tool_requests, allowed_tools, broker, messages_arg, timeline_arg, artifacts, **kwargs):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        request = tool_requests[0]
        input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
        result = {
            "ok": True,
            "path": "data/sales.csv",
            "content": "region,revenue\nEast,10\nWest,20",
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                str(request.get("tool") or ""),
                input_preview=input_preview,
                result=result,
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.read", "terminal.run", "artifact.write"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for data analysis.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "analysis ready"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-data-prefetch",
    )

    assert str(result) == "analysis ready"
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.read",
            "input": {"path": "data/sales.csv"},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_data_source",
            "continue_to_model": True,
        }
    ]
    assert tool_runs[0]["allowed_tools"] == ["workspace.read", "terminal.run", "artifact.write"]
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    followup_event = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert planned_event["source"] == "runtime_planner"
    assert followup_event["planning_reason"] == "planner_prefetch_data_source"
    assert followup_event["observation_tools"] == ["workspace.read"]
    assert followup_event["content_snapshot"] == {
        "source_tool": "workspace.read",
        "ok": True,
        "path": "data/sales.csv",
        "text_length": 30,
        "truncated": False,
        "text": "region,revenue\nEast,10\nWest,20",
    }
    assert model_calls[0][0]["role"] == "system"
    assert "selected intent=data_analysis" in model_calls[0][0]["content"]
    assert model_calls[0][-1]["role"] == "user"
    assert "Observed content snapshot:" in model_calls[0][-1]["content"]
    assert "region,revenue\nEast,10\nWest,20" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_prefetches_code_context_before_diagnostic_terminal() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    messages = [{"role": "user", "content": "修复这个仓库里的 failing tests"}]
    timeline: list[dict[str, Any]] = []

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ) -> None:
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            result = (
                {"ok": True, "path": ".", "entries": ["pyproject.toml", "tests"]}
                if tool_name == "workspace.list"
                else {
                    "ok": True,
                    "command": "python -m pytest",
                    "stdout": "2 passed",
                    "stderr": "",
                    "exit_code": 0,
                }
            )
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["workspace.list", "terminal.run", "artifact.write"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for code diagnostics.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "diagnostic ready"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Coder"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-code-diagnostic",
    )

    assert str(result) == "diagnostic ready"
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "workspace.list",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_prefetch_code_context",
        },
        {
            "protocol": "json_fallback",
            "tool": "terminal.run",
            "input": {"command": "python -m pytest"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_code_diagnostic",
            "continue_to_model": True,
        },
    ]
    planned_tools = [
        event["tool"]
        for event in timeline
        if event["event"] == "agent.desktop.intent_planned"
    ]
    assert planned_tools == ["workspace.list", "terminal.run"]
    followup_event = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup_event["planning_reason"] == "planner_fallback_code_diagnostic"
    assert followup_event["observation_tools"] == ["terminal.run"]
    assert model_calls[0][0]["role"] == "system"
    assert "selected intent=code_task" in model_calls[0][0]["content"]
    assert "Observed content snapshot:" in model_calls[0][-1]["content"]
    assert "2 passed" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_auto_analyzes_captured_visible_table() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "分析桌面上这个表格并输出报告"}]

    def fake_run_tool_requests(tool_requests, allowed_tools, broker, messages_arg, timeline_arg, artifacts, **kwargs):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        request = tool_requests[0]
        tool = str(request.get("tool") or "")
        input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
        if tool == "desktop.ui_elements":
            result = {
                "ok": True,
                "data": {
                    "elements": [
                        {"value": "| region | revenue |"},
                        {"value": "| --- | ---: |"},
                        {"value": "| East | 10 |"},
                        {"value": "| West | 20 |"},
                    ],
                    "count": 4,
                },
            }
        elif tool == "data.analyze":
            result = {
                "ok": True,
                "path": str(input_preview.get("display_path") or ""),
                "source_kind": str(input_preview.get("source_kind") or ""),
                "rows": 2,
                "analyzed_rows": 2,
                "columns": ["region", "revenue"],
                "artifact_path": "analysis-report.md",
                "artifact_paths": ["analysis-report.md"],
                "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
                "summary": "Analyzed captured UI table.",
            }
        else:
            result = {"ok": True}
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                tool,
                input_preview=input_preview,
                result=result,
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["desktop.ui_elements", "data.analyze", "artifact.write"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for captured data analysis.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "model should not be needed"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-visible-table-analysis",
    )

    assert "已分析" in str(result)
    assert model_calls == []
    assert [run["tool_requests"][0]["tool"] for run in tool_runs] == [
        "desktop.ui_elements",
        "data.analyze",
    ]
    assert tool_runs[0]["tool_requests"][0] == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "text", "limit": 80},
        "source": "runtime_planner",
        "planning_reason": "planner_prefetch_data_source",
        "continue_to_model": True,
    }
    assert tool_runs[1]["tool_requests"][0] == {
        "protocol": "json_fallback",
        "tool": "data.analyze",
        "input": {
            "content": (
                "| region | revenue |\n"
                "| --- | ---: |\n"
                "| East | 10 |\n"
                "| West | 20 |"
            ),
            "display_path": "captured:desktop.ui_elements",
            "artifact_path": "analysis-report.md",
            "source_kind": "text_table",
            "requested_outputs": ["report"],
            "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
        },
        "source": "runtime_planner",
        "planning_reason": "planner_builtin_data_analysis",
    }
    auto_plan_event = [
        event
        for event in timeline
        if event["event"] == "agent.desktop.intent_planned"
        and event["detail"] == "data.analyze"
    ][0]
    assert auto_plan_event["planning_reason"] == "planner_builtin_data_analysis"
    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "read-data-context",
        "analyze-data-context",
    ]
    completed_checkpoints = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["status"] == "completed"
    ]
    assert {
        event["step_id"] for event in completed_checkpoints
    } >= {
        "read-data-context",
        "analyze-data-context",
    }
    assert not any(event["event"] == "agent.model.followup_context" for event in timeline)


def test_custom_api_agent_loop_surfaces_builtin_data_analysis_followup_context() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "请分析 data/sales.csv 并把结果发给小明"}]

    def fake_run_tool_requests(tool_requests, allowed_tools, broker, messages_arg, timeline_arg, artifacts, **kwargs):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        request = tool_requests[0]
        input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
        result = {
            "ok": True,
            "path": "data/sales.csv",
            "source_kind": "csv",
            "rows": 3,
            "analyzed_rows": 3,
            "columns": ["region", "revenue", "units"],
            "artifact_paths": ["analysis-report.md", "analysis-chart.png"],
            "artifact_manifest": [
                {"path": "analysis-report.md", "kind": "markdown"},
                {"path": "analysis-chart.png", "kind": "chart"},
            ],
            "summary": "Analyzed data/sales.csv: 3 rows, 3 columns. Report: analysis-report.md.",
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                str(request.get("tool") or ""),
                input_preview=input_preview,
                result=result,
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["data.analyze", "workspace.read", "terminal.run", "artifact.write"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for data analysis.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "analysis ready"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-data-analysis-followup",
    )

    assert str(result) == "analysis ready"
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": "data/sales.csv",
                "artifact_path": "analysis-report.md",
                "source_kind": "csv",
                "requested_outputs": ["analysis_report"],
                "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
            },
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
            "continue_to_model": True,
        }
    ]
    followup_event = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup_event["planning_reason"] == "planner_builtin_data_analysis"
    assert followup_event["observation_tools"] == ["data.analyze"]
    assert followup_event["content_snapshot"]["source_tool"] == "data.analyze"
    assert followup_event["content_snapshot"]["rows"] == 3
    assert followup_event["content_snapshot"]["columns"] == ["region", "revenue", "units"]
    assert followup_event["content_snapshot"]["artifact_paths"] == [
        "analysis-report.md",
        "analysis-chart.png",
    ]
    assert model_calls[0][-1]["role"] == "user"
    assert "Observed content snapshot:" in model_calls[0][-1]["content"]
    assert "Data analysis result for data/sales.csv (csv)." in model_calls[0][-1]["content"]
    assert "Artifacts: analysis-report.md (markdown), analysis-chart.png (chart)" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_records_replan_request_for_runtime_planner_tool_failure() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    run_events: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "请分析 data/sales.csv 并输出报告"}]
    model_responses = [
        {"role": "assistant", "content": "run fallback"},
        {"role": "assistant", "content": "analysis fallback noted"},
    ]

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            result = (
                {
                    "ok": False,
                    "error": "unsupported chart type",
                    "hint": "fall back to python analysis",
                }
                if tool_name == "data.analyze"
                else {
                    "ok": True,
                    "command": input_preview.get("command", ""),
                    "stdout": "fallback analysis complete\n",
                    "stderr": "",
                    "returncode": 0,
                }
            )
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    def fake_tool_requests_from_message(
        _message: dict[str, Any],
        content: str,
    ) -> list[dict[str, Any]]:
        if content == "run fallback":
            return [
                {
                    "tool": "terminal.run",
                    "input": {"command": "python analyze_sales.py data/sales.csv"},
                    "protocol": "json_fallback",
                }
            ]
        return []

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {"base_url": "https://model.local", "model": "m", "api_key": "k"},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["data.analyze", "terminal.run", "artifact.write"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for data analysis.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or model_responses.pop(0),
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=fake_tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-data-replan",
    )

    assert str(result) == "analysis fallback noted"
    assert len(model_calls) == 2
    assert tool_runs[0]["tool_requests"][0]["tool"] == "data.analyze"
    assert tool_runs[1]["tool_requests"][0] == {
        "tool": "terminal.run",
        "input": {"command": "python analyze_sales.py data/sales.csv"},
        "protocol": "json_fallback",
    }
    replan_events = [
        event for event in timeline if event["event"] == "agent.replan.requested"
    ]
    assert len(replan_events) == 1
    payload = replan_events[0]["payload"]
    assert payload["trigger"] == "tool_failure"
    assert payload["run_id"] == "run-data-replan"
    assert payload["source_step_id"] == "analyze-data-file"
    assert payload["source_tool_name"] == "data.analyze"
    assert payload["target_capability_id"] == "data.analysis"
    assert payload["fallback_tools"] == ["terminal.run"]
    assert payload["failure_event_type"] == "agent.tool.call"
    assert "unsupported chart type" in payload["failure_detail"]
    assert "terminal.run" in payload["replan_prompt"]
    todo_events = [
        event for event in timeline if event["event"] == "agent.task.todo.updated"
    ]
    checkpoint_events = [
        event for event in timeline if event["event"] == "agent.task.checkpoint.updated"
    ]
    initial_todo = [
        event
        for event in todo_events
        if event["step_id"] == "analyze-data-file" and event["status"] == "pending"
    ][0]
    blocked_todo = [
        event
        for event in todo_events
        if event["step_id"] == "analyze-data-file" and event["status"] == "blocked"
    ][0]
    blocked_checkpoint = [
        event
        for event in checkpoint_events
        if event["step_id"] == "analyze-data-file" and event["status"] == "blocked"
    ][0]
    assert initial_todo["previous_status"] == ""
    assert initial_todo["todo"]["status"] == "pending"
    assert blocked_todo["todo"]["status"] == "blocked"
    assert "unsupported chart type" in blocked_checkpoint["result_preview"]["error"]
    replan_context = [
        event
        for event in timeline
        if event["event"] == "agent.model.followup_context"
        and event.get("planning_reason") == "planner_replan_after_tool_failure"
    ][0]
    assert replan_context["replan_requests"][0]["request_id"] == payload["request_id"]
    assert replan_context["fallback_tools"] == ["terminal.run"]
    assert replan_context["task_progress"]["blocked_steps"] == ["analyze-data-file"]
    assert any(
        item.get("path") == "data/sales.csv"
        for item in replan_context["task_progress"]["workspace_items"]
    )
    assert any(
        message["role"] == "user"
        and "Runtime replan context" in message["content"]
        and "terminal.run" in message["content"]
        and "blocked_steps: analyze-data-file" in message["content"]
        for message in model_calls[0]
    )
    assert any(
        event["event_type"] == "agent.replan.requested"
        and event["payload"]["request_id"] == payload["request_id"]
        for event in run_events
    )
    assert any(
        event["event_type"] == "agent.model.followup_context"
        and event["payload"]["planning_reason"] == "planner_replan_after_tool_failure"
        for event in run_events
    )
    assert any(
        event["event_type"] == "agent.task.todo.updated"
        and event["payload"]["step_id"] == "analyze-data-file"
        and event["payload"]["status"] == "blocked"
        for event in run_events
    )


def test_custom_api_agent_loop_records_replan_request_for_runtime_planner_verification_gap() -> None:
    run_events: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    decision = RuntimePlanner().decision(
        "帮我打开一个设计工具，搜索 logo 模板",
        allowed_tools=allowed_tools,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": allowed_tools}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for desktop actions.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": ""},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda *_args, **_kwargs: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    def build_timeline(verification_result: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            _timeline(
                "agent.tool.call",
                "desktop.list_apps",
                input_preview={"query": "design", "limit": 20},
                result={"ok": True, "data": {"apps": [{"name": "Figma"}]}},
            ),
            _timeline(
                "agent.tool.call",
                "app.open",
                input_preview={"app_name": "Figma"},
                result={"ok": True, "data": {"app_name": "Figma"}},
            ),
            _timeline(
                "agent.tool.call",
                "desktop.safe_shortcut",
                input_preview={"action": "find"},
                result={"ok": True},
            ),
            _timeline(
                "agent.tool.call",
                "desktop.safe_type_text",
                input_preview={"text": "logo 模板"},
                result={"ok": True},
            ),
            _timeline(
                "agent.tool.call",
                "desktop.search_submit",
                input_preview={},
                result={"ok": True},
            ),
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                input_preview={},
                result=verification_result,
            ),
        ]

    empty_timeline = build_timeline(
        {"ok": True, "data": {"elements": [], "count": 0, "text_item_count": 0}}
    )
    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=empty_timeline,
        tool_timeline_start=0,
        run_id="run-verify-replan",
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["trigger"] == "verification_failed"
    assert payload["run_id"] == "run-verify-replan"
    assert payload["source_step_id"] == "verify-desktop-result"
    assert payload["source_tool_name"] == "desktop.ui_elements"
    assert "no UI elements or readable text" in payload["failure_detail"]
    assert any(event["event"] == "agent.replan.requested" for event in empty_timeline)
    assert any(
        event["event_type"] == "agent.replan.requested"
        and event["payload"]["request_id"] == payload["request_id"]
        for event in run_events
    )
    messages: list[dict[str, Any]] = []
    loop._append_replan_followup_context(
        payloads,
        allowed_tools=allowed_tools,
        messages=messages,
        timeline=empty_timeline,
        run_id="run-verify-replan",
    )
    assert messages
    assert "post-action verification did not confirm" in messages[0]["content"]
    followup_context = [
        event
        for event in empty_timeline
        if event["event"] == "agent.model.followup_context"
    ][0]
    assert (
        followup_context["planning_reason"]
        == "planner_replan_after_verification_failed"
    )
    assert followup_context["trigger"] == "verification_failed"
    assert followup_context["triggers"] == ["verification_failed"]
    recovery_requests = custom_api_agent_module._auto_replan_verification_recovery_requests(
        payloads,
        [
            *allowed_tools,
            "desktop.active_window",
            "desktop.list_windows",
            "screen.capture",
        ],
    )
    assert [request["tool"] for request in recovery_requests] == [
        "desktop.active_window",
        "desktop.list_windows",
        "screen.capture",
    ]
    assert all(request["continue_to_model"] is True for request in recovery_requests)
    assert {
        request["replan_request_id"] for request in recovery_requests
    } == {payload["request_id"]}
    assert {
        request["replan_trigger"] for request in recovery_requests
    } == {"verification_failed"}
    loop._record_auto_model_followup_app_write_plan(
        recovery_requests,
        timeline=empty_timeline,
        run_id="run-verify-replan",
    )
    recovery_plan_events = [
        event
        for event in empty_timeline
        if event["event"] == "agent.desktop.intent_planned"
        and event.get("planning_reason") == "planner_verification_recovery_observation"
    ]
    assert [event["tool"] for event in recovery_plan_events] == [
        "desktop.active_window",
        "desktop.list_windows",
        "screen.capture",
    ]
    assert all(event["continue_to_model"] is True for event in recovery_plan_events)
    assert {
        event["replan_request_id"] for event in recovery_plan_events
    } == {payload["request_id"]}

    run_events.clear()
    readable_timeline = build_timeline(
        {
            "ok": True,
            "data": {
                "elements": [{"role": "AXStaticText", "value": "Logo templates"}],
                "count": 1,
                "text_item_count": 1,
            },
        }
    )
    assert (
        loop._record_runtime_planner_replan_events(
            decision,
            timeline=readable_timeline,
            tool_timeline_start=0,
            run_id="run-readable-verify",
        )
        == []
    )
    assert not any(event["event"] == "agent.replan.requested" for event in readable_timeline)
    assert run_events == []


def test_custom_api_agent_loop_records_replan_request_for_runtime_planner_unavailable_steps() -> None:
    run_events: list[dict[str, Any]] = []
    allowed_tools = ["desktop.list_apps", "app.open"]
    decision = RuntimePlanner().decision(
        "帮我打开一个设计工具，搜索 logo 模板",
        allowed_tools=allowed_tools,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": allowed_tools}},
        run_budget=lambda _run_id, _timeline_value: FakeBudget(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed_tools: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for desktop actions.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": ""},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda *_args, **_kwargs: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "design", "limit": 20},
            result={"ok": True, "data": {"apps": [{"name": "Figma"}]}},
        ),
        _timeline(
            "agent.tool.call",
            "app.open",
            input_preview={"app_name": "Figma"},
            result={"ok": True, "data": {"app_name": "Figma"}},
        ),
    ]

    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-unavailable-replan",
    )

    assert {payload["trigger"] for payload in payloads} == {"tool_unavailable"}
    assert {
        payload["source_step_id"] for payload in payloads
    } == {
        "focus-app-search-field",
        "type-app-search-query",
        "submit-app-search",
        "verify-desktop-result",
    }
    assert all(payload["run_id"] == "run-unavailable-replan" for payload in payloads)
    assert all(payload["failure_event_type"] == "agent.plan.step" for payload in payloads)
    assert any("desktop.ui_operation" in payload["failure_detail"] for payload in payloads)
    assert any(
        payload["metadata"]["capability_id"] == "desktop.ui_operation"
        and payload["metadata"]["step_status"] == "unavailable"
        for payload in payloads
    )
    messages: list[dict[str, Any]] = []
    loop._append_replan_followup_context(
        payloads,
        allowed_tools=allowed_tools,
        messages=messages,
        timeline=timeline,
        run_id="run-unavailable-replan",
    )
    assert "planned tool is unavailable" in messages[0]["content"]
    followup_context = [
        event
        for event in timeline
        if event["event"] == "agent.model.followup_context"
    ][0]
    assert followup_context["planning_reason"] == "planner_replan_after_tool_unavailable"
    assert followup_context["triggers"] == ["tool_unavailable"]
    assert any(
        item["capability_id"] == "desktop.ui_operation"
        and "desktop.safe_type_text" in item["missing_tools"]
        for item in followup_context["capability_recovery"]
    )
    assert [
        event["payload"]["request_id"]
        for event in run_events
        if event["event_type"] == "agent.replan.requested"
    ] == [payload["request_id"] for payload in payloads]
    assert (
        loop._record_runtime_planner_replan_events(
            decision,
            timeline=timeline,
            tool_timeline_start=0,
            run_id="run-unavailable-replan",
        )
        == []
    )


def test_custom_api_agent_loop_preserves_unavailable_runtime_plan_without_tool_requests() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    run_events: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "请分析 data/sales.csv 并输出报告"}]
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local/",
            "model": "test-model",
            "api_key": "key",
        },
        compile_agent_runtime=lambda _agent: {"tool_policy": {"allowed_tools": []}},
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner and keep replan context visible.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "需要开启数据分析能力后继续。"},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda *_args, **_kwargs: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=lambda *args, **kwargs: tool_runs.append(
            {"args": args, "kwargs": kwargs}
        ),
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-all-unavailable",
    )

    assert str(result) == "需要开启数据分析能力后继续。"
    assert tool_runs == []
    assert any(event["event"] == "agent.plan.created" for event in timeline)
    assert any(event["event"] == "agent.task.todo.updated" for event in timeline)
    replan_events = [
        event for event in timeline if event["event"] == "agent.replan.requested"
    ]
    assert len(replan_events) == 3
    assert {
        event["payload"]["source_step_id"] for event in replan_events
    } == {
        "inspect-data-source",
        "run-analysis",
        "write-analysis-artifact",
    }
    assert {event["payload"]["trigger"] for event in replan_events} == {
        "tool_unavailable"
    }
    followup_context = [
        event
        for event in timeline
        if event["event"] == "agent.model.followup_context"
    ][0]
    assert followup_context["planning_reason"] == "planner_replan_after_tool_unavailable"
    assert followup_context["triggers"] == ["tool_unavailable"]
    recovery_by_capability = {
        item["capability_id"]: item
        for item in followup_context["capability_recovery"]
    }
    data_recovery = recovery_by_capability["data.analysis"]
    assert data_recovery["missing_tools"] == ["data.analyze", "terminal.run", "python.run"]
    assert data_recovery["recommended_enable_tools"] == [
        "data.analyze",
        "terminal.run",
        "python.run",
    ]
    assert data_recovery["suggested_action"] == "enable_tools"
    assert recovery_by_capability["artifact.write"]["missing_tools"] == ["artifact.write"]
    assert not any(
        event["event"] == "agent.desktop.intent_unavailable" for event in timeline
    )
    assert model_calls
    assert any(
        message["role"] == "user"
        and "Runtime replan context" in message["content"]
        and "planned tool is unavailable" in message["content"]
        and "enable_tools=data.analyze" in message["content"]
        and "failed_step: run-analysis" in message["content"]
        for message in model_calls[0]
    )
    assert [
        event["payload"]["request_id"]
        for event in run_events
        if event["event_type"] == "agent.replan.requested"
    ] == [event["payload"]["request_id"] for event in replan_events]


def test_custom_api_agent_loop_writes_data_analysis_report_to_target_app() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "请分析 data/sales.csv 并把报告写进 Obsidian 新笔记"}]
    generated = "销售分析报告\n- East revenue 10\n- West revenue 20"

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool_name == "data.analyze":
                result = {
                    "ok": True,
                    "path": "data/sales.csv",
                    "source_kind": "csv",
                    "rows": 2,
                    "analyzed_rows": 2,
                    "columns": ["region", "revenue"],
                    "artifact_paths": ["analysis-report.md"],
                    "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
                    "summary": "Analyzed data/sales.csv: 2 rows, 2 columns. Report: analysis-report.md.",
                }
            elif tool_name == "app.focus_and_safe_type_text":
                result = {
                    "ok": True,
                    "app_name": input_preview.get("app_name"),
                    "text": input_preview.get("text"),
                }
            else:
                result = {"ok": True}
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "data.analyze",
                    "artifact.write",
                    "app.focus_and_safe_shortcut",
                    "app.focus_and_safe_type_text",
                    "desktop.ui_elements",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-data-analysis-app-write",
    )

    assert "Obsidian" in str(result)
    assert "输入文字" in str(result)
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": "data/sales.csv",
                "artifact_path": "analysis-report.md",
                "source_kind": "csv",
                "requested_outputs": ["report"],
                "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
            },
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
            "continue_to_model": True,
        }
    ]
    assert [request["tool"] for request in tool_runs[1]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text",
        "desktop.ui_elements",
    ]
    assert tool_runs[1]["tool_requests"][0]["input"] == {
        "app_name": "Obsidian",
        "action": "new_note",
    }
    assert tool_runs[1]["tool_requests"][1]["input"] == {
        "app_name": "Obsidian",
        "text": generated,
    }
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["followup_target"]["app_name"] == "Obsidian"
    assert followup["followup_target"]["container_action"] == "new_note"
    assert followup["content_snapshot"]["source_tool"] == "data.analyze"
    assert any(
        event["event"] == "agent.desktop.intent_planned"
        and event["detail"] == "app.focus_and_safe_type_text"
        and event["planning_reason"] == "planner_followup_app_write"
        for event in timeline
    )
    assert len(model_calls) == 1
    assert "Data analysis result for data/sales.csv (csv)." in model_calls[0][-1]["content"]
    assert "written into Obsidian" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_writes_captured_data_analysis_to_target_app() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [
        {
            "role": "user",
            "content": "读取当前网页内容，分析里面的表格并把报告写进 Notion 新页面",
        }
    ]
    captured_table = "| region | revenue |\n| --- | ---: |\n| East | 10 |\n| West | 20 |"
    generated = "网页表格分析报告\n- East revenue 10\n- West revenue 20"

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool_name == "browser.extract_text":
                result = {
                    "ok": True,
                    "text": captured_table,
                    "url": "https://example.test/report",
                }
            elif tool_name == "data.analyze":
                result = {
                    "ok": True,
                    "path": str(input_preview.get("display_path") or ""),
                    "source_kind": str(input_preview.get("source_kind") or ""),
                    "rows": 2,
                    "analyzed_rows": 2,
                    "columns": ["region", "revenue"],
                    "artifact_paths": ["analysis-report.md"],
                    "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
                    "summary": "Analyzed captured browser table.",
                }
            elif tool_name == "app.focus_and_safe_type_text":
                result = {
                    "ok": True,
                    "app_name": input_preview.get("app_name"),
                    "text": input_preview.get("text"),
                }
            else:
                result = {"ok": True}
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "browser.extract_text",
                    "browser.current_page",
                    "data.analyze",
                    "artifact.write",
                    "app.focus_and_safe_shortcut",
                    "app.focus_and_safe_type_text",
                    "desktop.ui_elements",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-captured-data-analysis-app-write",
    )

    assert "Notion" in str(result)
    assert "输入文字" in str(result)
    assert [run["tool_requests"][0]["tool"] for run in tool_runs] == [
        "browser.extract_text",
        "data.analyze",
        "app.focus_and_safe_shortcut",
    ]
    assert tool_runs[1]["tool_requests"][0] == {
        "protocol": "json_fallback",
        "tool": "data.analyze",
        "input": {
            "content": captured_table,
            "display_path": "https://example.test/report",
            "artifact_path": "analysis-report.md",
            "source_kind": "text_table",
            "requested_outputs": ["report"],
            "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
        },
        "source": "runtime_planner",
        "planning_reason": "planner_builtin_data_analysis",
    }
    assert [request["tool"] for request in tool_runs[2]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text",
        "desktop.ui_elements",
    ]
    assert tool_runs[2]["tool_requests"][0]["input"] == {
        "app_name": "Notion",
        "action": "new_document",
    }
    assert tool_runs[2]["tool_requests"][1]["input"] == {
        "app_name": "Notion",
        "text": generated,
    }
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["planning_reason"] == "planner_model_followup_context"
    assert followup["observation_tools"] == ["browser.extract_text", "data.analyze"]
    assert followup["followup_target"]["app_name"] == "Notion"
    assert followup["followup_target"]["container_action"] == "new_document"
    assert followup["content_snapshot"]["source_tool"] == "data.analyze"
    assert len(model_calls) == 1
    assert "Data analysis result for https://example.test/report (text_table)." in (
        model_calls[0][-1]["content"]
    )
    assert "written into Notion" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_sends_captured_data_analysis_to_communication_target() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [
        {
            "role": "user",
            "content": "读取当前网页内容，分析里面的表格并把报告发给 Slack 的 yachiyo",
        }
    ]
    captured_table = "| region | revenue |\n| --- | ---: |\n| East | 10 |\n| West | 20 |"
    generated = "网页表格分析报告\n- East revenue 10\n- West revenue 20"

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool_name == "browser.extract_text":
                result = {
                    "ok": True,
                    "text": captured_table,
                    "url": "https://example.test/report",
                }
            elif tool_name == "data.analyze":
                result = {
                    "ok": True,
                    "path": str(input_preview.get("display_path") or ""),
                    "source_kind": str(input_preview.get("source_kind") or ""),
                    "rows": 2,
                    "analyzed_rows": 2,
                    "columns": ["region", "revenue"],
                    "artifact_paths": ["analysis-report.md"],
                    "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
                    "summary": "Analyzed captured browser table.",
                }
            elif tool_name in {"app.focus_and_safe_shortcut", "desktop.safe_type_text"}:
                result = {"ok": True, **input_preview}
            else:
                result = {"ok": True}
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "browser.extract_text",
                    "browser.current_page",
                    "data.analyze",
                    "artifact.write",
                    "app.focus_and_safe_shortcut",
                    "desktop.safe_type_text",
                    "desktop.search_submit",
                    "desktop.submit_foreground",
                    "desktop.ui_elements",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Analyst"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-captured-data-analysis-communication",
    )

    assert "Slack" in str(result)
    assert "输入文字" in str(result)
    assert [run["tool_requests"][0]["tool"] for run in tool_runs] == [
        "browser.extract_text",
        "data.analyze",
        "app.focus_and_safe_shortcut",
    ]
    assert [request["tool"] for request in tool_runs[2]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert tool_runs[2]["tool_requests"][0]["input"] == {
        "app_name": "Slack",
        "action": "find",
    }
    assert tool_runs[2]["tool_requests"][1]["input"] == {"text": "yachiyo"}
    assert tool_runs[2]["tool_requests"][3]["input"] == {"text": generated}
    assert tool_runs[2]["tool_requests"][4]["input"] == {"action": "send"}
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["followup_target"]["kind"] == "communication_message"
    assert followup["followup_target"]["app_name"] == "Slack"
    assert followup["followup_target"]["recipient"] == "yachiyo"
    assert followup["followup_target"]["send_allowed"] is True
    assert any(
        event["event"] == "agent.desktop.intent_planned"
        and event["detail"] == "desktop.submit_foreground"
        and event["planning_reason"] == "planner_followup_communication"
        for event in timeline
    )
    assert len(model_calls) == 1
    assert "message to yachiyo in Slack" in model_calls[0][-1]["content"]
    assert "Data analysis result for https://example.test/report (text_table)." in (
        model_calls[0][-1]["content"]
    )


def test_custom_api_agent_loop_sends_visible_text_summary_to_communication_target() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [
        {
            "role": "user",
            "content": "把当前窗口内容总结一下发给微信文件传输助手",
        }
    ]
    visible_text = "Q2 sales increased 12%. Renewal risk is concentrated in East accounts."
    generated = "当前窗口摘要：Q2 销售增长 12%，续约风险集中在 East 客户。"

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            result = (
                {
                    "ok": True,
                    "elements": [
                        {
                            "role": "text",
                            "value": visible_text,
                        }
                    ],
                }
                if tool_name == "desktop.ui_elements"
                else {"ok": True, **input_preview}
            )
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "desktop.ui_elements",
                    "app.focus_and_safe_shortcut",
                    "desktop.safe_type_text",
                    "desktop.search_submit",
                    "desktop.submit_foreground",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-visible-text-communication",
    )

    assert "WeChat" in str(result)
    assert "输入文字" in str(result)
    assert [run["tool_requests"][0]["tool"] for run in tool_runs] == [
        "desktop.ui_elements",
        "app.focus_and_safe_shortcut",
    ]
    assert [request["tool"] for request in tool_runs[1]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert tool_runs[1]["tool_requests"][0]["input"] == {
        "app_name": "WeChat",
        "action": "find",
    }
    assert tool_runs[1]["tool_requests"][1]["input"] == {"text": "文件传输助手"}
    assert tool_runs[1]["tool_requests"][3]["input"] == {"text": generated}
    assert tool_runs[1]["tool_requests"][4]["input"] == {"action": "send"}
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["observation_tools"] == ["desktop.ui_elements"]
    assert followup["followup_target"]["kind"] == "communication_message"
    assert followup["followup_target"]["app_name"] == "WeChat"
    assert followup["followup_target"]["recipient"] == "文件传输助手"
    assert followup["followup_target"]["transform"] == "summary"
    assert followup["content_snapshot"]["source_tool"] == "desktop.ui_elements"
    assert visible_text in model_calls[0][-1]["content"]
    assert "message to 文件传输助手 in WeChat" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_pauses_followup_communication_send_for_approval() -> None:
    budget = FakeBudget()
    tool_runs: list[list[dict[str, Any]]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    messages = [
        {
            "role": "user",
            "content": "把当前窗口内容总结一下发给微信文件传输助手",
        }
    ]
    visible_text = "Q2 sales increased 12%. Renewal risk is concentrated in East accounts."
    generated = "当前窗口摘要：Q2 销售增长 12%，续约风险集中在 East 客户。"

    def fake_run_tool_requests(
        tool_requests,
        _allowed_tools,
        _broker,
        _messages_arg,
        timeline_arg,
        _artifacts,
        **_kwargs,
    ):
        tool_runs.append(list(tool_requests))
        if len(tool_runs) == 1:
            assert [request["tool"] for request in tool_requests] == ["desktop.ui_elements"]
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    "desktop.ui_elements",
                    input_preview={"role_filter": "text", "limit": 80},
                    result={
                        "ok": True,
                        "elements": [
                            {
                                "role": "text",
                                "value": visible_text,
                            }
                        ],
                    },
                )
            )
            return
        assert [request["tool"] for request in tool_requests] == [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ]
        raise AgentApprovalRequired(
            {
                "approval_id": "approval-followup-send",
                "tool": "desktop.submit_foreground",
                "input_preview": {"action": "send"},
                "risk_level": "high",
                "policy_reason": "发送前台内容需要确认。",
            }
        )

    def fake_call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        model_calls.append(list(model_messages))
        return {"role": "assistant", "content": generated}

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "desktop.ui_elements",
                    "app.focus_and_safe_shortcut",
                    "desktop.safe_type_text",
                    "desktop.search_submit",
                    "desktop.submit_foreground",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=fake_call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )

    try:
        loop.run(
            {"name": "Yachiyo"},
            "ignored context",
            broker={"broker": True},
            timeline=timeline,
            artifacts=[],
            messages=messages,
            run_id="run-visible-text-send-approval",
        )
    except AgentApprovalRequired as exc:
        assert exc.pending_approval["approval_id"] == "approval-followup-send"
    else:
        raise AssertionError("expected AgentApprovalRequired")

    assert len(model_calls) == 1
    assert len(tool_runs) == 2
    approval_event = timeline[-1]
    assert approval_event == {
        "event": "agent.desktop.intent_approval_required",
        "detail": "desktop.submit_foreground",
        "tool": "desktop.submit_foreground",
        "status": "approval_required",
        "source": "runtime_planner",
        "reason": "tool_policy_requires_approval",
        "input_preview": {"action": "send"},
        "approval_id": "approval-followup-send",
        "risk_level": "high",
        "policy_reason": "发送前台内容需要确认。",
        "planning_reason": "planner_followup_communication",
    }
    assert appended_events[-1] == {
        "run_id": "run-visible-text-send-approval",
        "event_type": "agent.desktop.intent_approval_required",
        "payload": {
            "tool": "desktop.submit_foreground",
            "status": "approval_required",
            "source": "runtime_planner",
            "reason": "tool_policy_requires_approval",
            "input_preview": {"action": "send"},
            "approval_id": "approval-followup-send",
            "risk_level": "high",
            "policy_reason": "发送前台内容需要确认。",
            "planning_reason": "planner_followup_communication",
        },
    }


def test_model_followup_context_payload_preserves_multiple_content_snapshots() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "workspace.read",
            input_preview={"path": "data/sales.csv"},
            result={
                "ok": True,
                "path": "data/sales.csv",
                "content": "region,revenue\nEast,10\nWest,20",
            },
        ),
        _timeline(
            "agent.tool.call",
            "data.analyze",
            input_preview={"path": "data/sales.csv", "source_kind": "csv"},
            result={
                "ok": True,
                "path": "data/sales.csv",
                "source_kind": "csv",
                "rows": 2,
                "columns": ["region", "revenue"],
                "artifact_paths": ["analysis-report.md"],
                "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
            },
        ),
    ]

    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "workspace.read",
                "planning_reason": "planner_prefetch_data_source",
                "continue_to_model": True,
            },
            {
                "tool": "data.analyze",
                "planning_reason": "planner_builtin_data_analysis",
                "continue_to_model": True,
            },
        ],
        {
            "artifacts_expected": ["analysis-report.md"],
            "decision_id": "decision-1",
            "plan_id": "plan-1",
            "intent_kind": "data_analysis",
        },
        allowed_tools=["workspace.read", "data.analyze", "artifact.write"],
        timeline=timeline,
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["planning_reason"] == "planner_model_followup_context"
    assert payload["observation_tools"] == ["workspace.read", "data.analyze"]
    assert payload["content_snapshot"]["source_tool"] == "data.analyze"
    assert [snapshot["source_tool"] for snapshot in payload["content_snapshots"]] == [
        "workspace.read",
        "data.analyze",
    ]
    assert payload["content_snapshots"][0]["text"] == "region,revenue\nEast,10\nWest,20"
    assert payload["content_snapshots"][1]["artifact_paths"] == ["analysis-report.md"]
    assert "Observed context snapshots:" in message
    assert "[1] workspace.read" in message
    assert "[2] data.analyze" in message
    assert "Data analysis result for data/sales.csv (csv)." in message


def test_model_followup_context_instructs_pending_report_plan_steps() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "workspace.list",
                "planning_reason": "planner_prefetch_report_context",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "report_generation",
            "artifacts_expected": ["report.md"],
            "tool_plan": {
                "steps": [
                    {
                        "step_id": "inspect-report-file-scope",
                        "title": "Inspect report file scope",
                        "capability_id": "file.workspace_read",
                        "tool_name": "workspace.list",
                        "input_preview": {
                            "path": "~/Downloads/report.pdf",
                            "file_type": "pdf",
                            "pattern": "*.pdf",
                        },
                        "risk_level": "low",
                        "approval_required": False,
                        "status": "planned",
                    },
                    {
                        "step_id": "extract-report-file-context",
                        "title": "Extract report file context",
                        "capability_id": "terminal.execution",
                        "tool_name": "terminal.run",
                        "input_preview": {
                            "path": "~/Downloads/report.pdf",
                            "file_type": "pdf",
                            "pattern": "*.pdf",
                            "operation": "extract_text_for_report",
                        },
                        "risk_level": "medium",
                        "approval_required": True,
                        "depends_on": ["inspect-report-file-scope"],
                        "status": "planned",
                    },
                    {
                        "step_id": "write-report-artifact",
                        "title": "Write report artifact",
                        "capability_id": "artifact.write",
                        "tool_name": "artifact.write",
                        "input_preview": {
                            "path": "report.md",
                            "body_source": "local_file_context",
                        },
                        "risk_level": "low",
                        "approval_required": False,
                        "depends_on": ["extract-report-file-context"],
                        "status": "planned",
                    },
                ]
            },
        },
        allowed_tools=[
            "workspace.list",
            "terminal.run",
            "artifact.write",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "workspace.list",
                input_preview={"path": "~/Downloads/report.pdf"},
                result={"ok": True, "files": [{"path": "~/Downloads/report.pdf"}]},
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert [step["step_id"] for step in payload["pending_plan_steps"]] == [
        "extract-report-file-context",
        "write-report-artifact",
    ]
    assert "Continue the pending Runtime Plan steps in order" in message
    assert "extract-report-file-context via terminal.run" in message
    assert "write-report-artifact via artifact.write" in message
    assert "medium risk approval required" in message
    assert "synthesize a concrete, safe command" in message
    assert "Call artifact.write next" not in message


def test_model_followup_context_instructs_generated_app_write() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "browser.extract_text",
                "planning_reason": "planner_prefetch_report_context",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "report_generation",
            "followup_target": {
                "kind": "app_write",
                "app_name": "Obsidian",
                "target_action": "app_paste",
                "body_source": "model_generated_content",
                "container_action": "new_note",
                "context_source": "current_page_content",
            },
        },
        allowed_tools=[
            "browser.extract_text",
            "app.focus_and_safe_shortcut",
            "app.focus_and_safe_type_text",
            "desktop.ui_elements",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.extract_text",
                input_preview={},
                result={"ok": True, "text": "Raw current page text"},
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"] == {
        "kind": "app_write",
        "app_name": "Obsidian",
        "target_action": "app_paste",
        "body_source": "model_generated_content",
        "write_allowed": True,
        "recommended_tools": ["app.focus_and_safe_shortcut", "app.focus_and_safe_type_text"],
        "verify_tools": ["desktop.ui_elements"],
        "container_action": "new_note",
        "context_source": "current_page_content",
    }
    assert "written into Obsidian" in message
    assert "new_note" in message
    assert "app.focus_and_safe_type_text" in message
    assert "Do not write the raw observed source" in message

    assert custom_api_agent_module._model_followup_app_write_requests(
        "整理后的摘要",
        payload["followup_target"],
        ["app.focus_and_safe_shortcut", "app.focus_and_safe_type_text", "desktop.ui_elements"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "new_note"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_app_write",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": "Obsidian", "text": "整理后的摘要"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_app_write",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_app_write",
        },
    ]
    assert custom_api_agent_module._latest_model_followup_target(
        [
            _timeline(
                "agent.model.followup_context",
                "planner_prefetch_report_context",
                followup_target=payload["followup_target"],
                content_snapshot={
                    "source_tool": "browser.extract_text",
                    "ok": False,
                    "summary": "Screen Recording permission is missing.",
                },
            )
        ]
    ) == {}


def test_model_followup_context_instructs_discovered_app_search_result_selection() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "desktop.list_apps",
                "planning_reason": "planner_desktop_operation",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "desktop_operation",
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "safe_shortcut_action": "find",
                "app_search": {
                    "query": "logo 模板",
                    "submit": True,
                    "result_selection": {
                        "action": "click",
                        "tool": "desktop.click_ui_element",
                        "input": {"target": "第一个结果", "click_count": 1},
                    },
                },
            },
        },
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
        timeline=[],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"]["app_search"]["result_selection"]["action"] == "click"
    assert "search query 'logo 模板'" in message
    assert "select the requested app-search result '第一个结果'" in message
    assert "desktop.click_ui_element" in message
    assert "pause for approval" in message

    confirm_payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "desktop.list_apps",
                "planning_reason": "planner_desktop_operation",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "desktop_operation",
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "safe_shortcut_action": "find",
                "app_search": {
                    "query": "logo 模板",
                    "submit": True,
                    "submit_action": "confirm",
                    "result_selection": {
                        "action": "key_confirm",
                        "key": {"tool": "desktop.safe_key", "input": {"action": "arrow_down"}},
                        "confirm": {
                            "tool": "desktop.submit_foreground",
                            "input": {"action": "confirm"},
                        },
                    },
                },
            },
        },
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
        timeline=[],
    )
    confirm_message = custom_api_agent_module._model_followup_context_message(confirm_payload)

    assert "desktop.safe_key" in confirm_message
    assert "approval-gated desktop.submit_foreground confirm" in confirm_message
    assert "until the approval-gated confirm tool has executed" in confirm_message


def test_model_followup_context_instructs_generated_discovered_app_write() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "data.analyze",
                "planning_reason": "planner_builtin_data_analysis",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "data_analysis",
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "markdown",
                "app_name_source": "desktop.list_apps",
                "target_action": "safe_shortcut",
                "body_source": "model_generated_content",
                "safe_shortcut_action": "new_document",
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            },
        },
        allowed_tools=[
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "data.analyze",
                input_preview={"path": "sales.csv", "source_kind": "csv"},
                result={
                    "ok": True,
                    "path": "sales.csv",
                    "source_kind": "csv",
                    "rows": 2,
                    "columns": ["region", "revenue"],
                    "artifact_paths": ["analysis-report.md"],
                    "artifact_manifest": [{"path": "analysis-report.md", "kind": "markdown"}],
                },
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"] == {
        "kind": "desktop_discovered_app_action",
        "app_query": "markdown",
        "app_name_source": "desktop.list_apps",
        "target_action": "safe_shortcut",
        "recommended_tools": [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
        ],
        "verify_tools": ["desktop.ui_elements"],
        "safe_shortcut_action": "new_document",
        "body_source": "model_generated_content",
        "post_action_observation": {
            "tool": "desktop.ui_elements",
            "input": {},
        },
    }
    assert "Data analysis result for sales.csv (csv)." in message
    assert "call desktop.list_apps for 'markdown'" in message
    assert "insert the generated content" in message
    assert "Do not write the raw observed source" in message
    assert custom_api_agent_module._model_followup_app_write_requests(
        "## 分析报告\n\n收入增长。",
        payload["followup_target"],
        [
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "markdown", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_discovered_app_write",
        }
    ]
    assert custom_api_agent_module._model_followup_discovered_app_write_requests_after_discovery(
        "## 分析报告\n\n收入增长。",
        payload["followup_target"],
        [
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        ],
        [
            _timeline(
                "agent.tool.call",
                "desktop.list_apps",
                input_preview={"query": "markdown", "limit": 20},
                result={
                    "ok": True,
                    "action": "desktop.list_apps",
                    "summary": "Found Obsidian",
                    "data": {
                        "query": "markdown",
                        "apps": [
                            {
                                "name": "Obsidian",
                                "path": "/Applications/Obsidian.app",
                                "match_score": 91,
                            }
                        ],
                    },
                },
            )
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "new_document"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_discovered_app_write",
            "input_resolution": {
                "tool": "app.open_and_safe_shortcut",
                "field": "app_name",
                "requested_app_name": "markdown",
                "resolved_app_name": "Obsidian",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Obsidian.app",
                "app_resolution_score": "91",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "## 分析报告\n\n收入增长。"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_discovered_app_write",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_discovered_app_write",
        },
    ]


def test_model_followup_context_preserves_discovered_canvas_remaining_action() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "desktop.ui_elements",
                "planning_reason": "planner_discovered_app_followup",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "desktop_operation",
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "绘图",
                "target_action": "open_app",
                "creative_canvas": {"kind": "image_canvas"},
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {"limit": 80},
                    "continue_to_model": True,
                },
                "pending_user_action": "画一个圆并保存到桌面",
            },
            "tool_plan": {
                "steps": [
                    {
                        "step_id": "open-selected-discovered-app",
                        "tool_name": "app.open",
                        "capability_id": "desktop.app_discovery",
                        "action": "open_selected_app",
                        "status": "planned",
                    },
                    {
                        "step_id": "observe-selected-discovered-app",
                        "tool_name": "desktop.ui_elements",
                        "capability_id": "desktop.app_discovery",
                        "action": "inspect_ui",
                        "status": "planned",
                    },
                    {
                        "step_id": "draw-circle",
                        "tool_name": "desktop.click_ui_element",
                        "capability_id": "desktop.ui_operation",
                        "action": "draw_shape",
                        "input_preview": {"target": "circle shape tool"},
                        "risk_level": "low",
                        "approval_required": False,
                        "status": "planned",
                    },
                    {
                        "step_id": "save-image",
                        "tool_name": "desktop.shortcut",
                        "capability_id": "desktop.ui_operation",
                        "action": "shortcut",
                        "input_preview": {"key": "s", "modifiers": ["command"]},
                        "risk_level": "medium",
                        "approval_required": True,
                        "status": "planned",
                    },
                    {
                        "step_id": "verify-saved-image",
                        "tool_name": "screen.capture",
                        "capability_id": "desktop.visual_verification",
                        "action": "verify_result",
                        "risk_level": "low",
                        "approval_required": False,
                        "status": "planned",
                    },
                ]
            },
        },
        allowed_tools=[
            "desktop.list_apps",
            "app.open",
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
            "desktop.ui_elements",
            "desktop.shortcut",
            "screen.capture",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                input_preview={"limit": 80},
                result={
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "data": {"elements": [{"role": "button", "name": "Shape"}]},
                },
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"]["creative_canvas"] == {"kind": "image_canvas"}
    assert payload["followup_target"]["pending_user_action"] == "画一个圆并保存到桌面"
    assert [step["step_id"] for step in payload["pending_plan_steps"]] == [
        "draw-circle",
        "save-image",
        "verify-saved-image",
    ]
    assert "The remaining user action is: '画一个圆并保存到桌面'" in message
    assert "continue toward that action after the canvas is available" in message
    assert "Continue the pending Runtime Plan steps in order" in message
    assert "draw-circle via desktop.click_ui_element" in message
    assert "Call desktop UI tools next instead of replying inline" in message
    pending_plan_requests = custom_api_agent_module._model_followup_pending_plan_requests(
        payload,
        [
            "desktop.click_ui_element",
            "screen.capture",
            "desktop.shortcut",
            "terminal.run",
        ],
    )
    assert pending_plan_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "circle shape tool"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "step_id": "draw-circle",
            "capability_id": "desktop.ui_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.shortcut",
            "input": {"key": "s", "modifiers": ["command"]},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "step_id": "save-image",
            "capability_id": "desktop.ui_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "screen.capture",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "step_id": "verify-saved-image",
            "capability_id": "desktop.visual_verification",
        },
    ]
    planned_timeline: list[dict[str, Any]] = []
    _private_runtime_loop()._record_auto_model_followup_app_write_plan(
        pending_plan_requests,
        timeline=planned_timeline,
        run_id="run-pending-plan",
    )
    assert [
        (event["tool"], event["step_id"], event["capability_id"])
        for event in planned_timeline
        if event["event"] == "agent.desktop.intent_planned"
    ] == [
        ("desktop.click_ui_element", "draw-circle", "desktop.ui_operation"),
        ("desktop.shortcut", "save-image", "desktop.ui_operation"),
        ("screen.capture", "verify-saved-image", "desktop.visual_verification"),
    ]
    assert custom_api_agent_module._model_followup_pending_plan_requests(
        {
            **payload,
            "pending_plan_steps": [
                {
                    "step_id": "run-script",
                    "tool_name": "terminal.run",
                    "capability_id": "terminal.execution",
                    "input_preview": {"operation": "generate_report"},
                }
            ],
        },
        ["terminal.run"],
    ) == []


def test_model_followup_pending_plan_auto_dispatches_discovered_app_hotkeys() -> None:
    assert custom_api_agent_module._model_followup_pending_plan_requests(
        {
            "planning_reason": "planner_discovered_app_followup",
            "pending_plan_steps": [
                {
                    "step_id": "hotkey-selected-discovered-app",
                    "tool_name": "app.focus_and_hotkey",
                    "capability_id": "desktop.ui_operation",
                    "input_preview": {
                        "app_name": "<selected app from desktop.list_apps>",
                        "selection_source": "desktop.list_apps",
                        "query": "image",
                        "key": "s",
                        "modifiers": ["command"],
                    },
                },
                {
                    "step_id": "fallback-hotkey",
                    "tool_name": "desktop.hotkey",
                    "capability_id": "desktop.ui_operation",
                    "input_preview": {"key": "w", "modifiers": ["command"]},
                },
            ],
        },
        ["app.focus_and_hotkey", "desktop.hotkey"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_hotkey",
            "input": {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": "image",
                "key": "s",
                "modifiers": ["command"],
            },
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "step_id": "hotkey-selected-discovered-app",
            "capability_id": "desktop.ui_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "w", "modifiers": ["command"]},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "step_id": "fallback-hotkey",
            "capability_id": "desktop.ui_operation",
        },
    ]


def test_model_followup_pending_plan_dispatches_short_multi_step_workflow() -> None:
    pending_steps = [
        {
            "step_id": "type-selected-recipient",
            "tool_name": "app.focus_and_type_into_ui_element",
            "capability_id": "desktop.ui_operation",
            "input_preview": {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": "messaging",
                "target": "recipient",
                "text": "Alice",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "step_id": "submit-selected-recipient",
            "tool_name": "desktop.search_submit",
            "capability_id": "desktop.ui_operation",
            "input_preview": {},
        },
        {
            "step_id": "type-selected-body",
            "tool_name": "app.focus_and_type_into_ui_element",
            "capability_id": "desktop.ui_operation",
            "input_preview": {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": "messaging",
                "target": "message",
                "text": "hello",
                "role_filter": "text",
                "limit": 80,
            },
        },
        {
            "step_id": "send-selected-message",
            "tool_name": "desktop.submit_foreground",
            "capability_id": "desktop.ui_operation",
            "input_preview": {"action": "send"},
        },
        {
            "step_id": "verify-selected-message",
            "tool_name": "screen.capture",
            "capability_id": "desktop.visual_verification",
            "input_preview": {"reason": "verify selected discovered app action"},
        },
    ]

    requests = custom_api_agent_module._model_followup_pending_plan_requests(
        {
            "planning_reason": "planner_discovered_app_followup",
            "pending_plan_steps": pending_steps,
        },
        [
            "app.focus_and_type_into_ui_element",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "screen.capture",
        ],
    )

    assert [request["tool"] for request in requests] == [
        "app.focus_and_type_into_ui_element",
        "desktop.search_submit",
        "app.focus_and_type_into_ui_element",
        "desktop.submit_foreground",
        "screen.capture",
    ]
    assert [request["step_id"] for request in requests] == [
        "type-selected-recipient",
        "submit-selected-recipient",
        "type-selected-body",
        "send-selected-message",
        "verify-selected-message",
    ]
    assert all(
        request["planning_reason"] == "planner_discovered_app_followup"
        for request in requests
    )


def test_model_followup_context_dispatches_discovered_app_operation_plan() -> None:
    prompt = "找一个 PDF 阅读器，向下滚动两页"
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "app.focus_and_safe_scroll",
        "screen.capture",
    ]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    planner_requests = planner_tool_requests(prompt, allowed_tools)
    selection_payload = planner_selection_payload(
        decision=decision,
        planner_requests=planner_requests,
        legacy_requests=[],
        selected_requests=planner_requests,
        selected_source="runtime_planner",
        selected_reason="runtime_planner_direct",
    )

    followup_context = custom_api_agent_module._model_followup_context_payload(
        planner_requests,
        selection_payload,
        allowed_tools=allowed_tools,
        timeline=[
            _timeline(
                "agent.tool.call",
                "desktop.list_apps",
                input_preview={"query": "pdf", "limit": 20},
                result={
                    "ok": True,
                    "action": "desktop.list_apps",
                    "data": {
                        "query": "pdf",
                        "apps": [
                            {
                                "name": "Preview",
                                "path": "/System/Applications/Preview.app",
                                "match_score": 90,
                            }
                        ],
                    },
                },
            )
        ],
    )
    requests = custom_api_agent_module._model_followup_pending_plan_requests(
        followup_context,
        allowed_tools,
    )

    assert [step["step_id"] for step in followup_context["pending_plan_steps"]] == [
        "open-selected-discovered-app",
        "scroll-selected-discovered-app",
        "verify-selected-discovered-app-action",
    ]
    assert [request["tool"] for request in requests] == [
        "app.open",
        "app.focus_and_safe_scroll",
        "screen.capture",
    ]
    assert requests[0]["input"] == {
        "app_name": "<selected app from desktop.list_apps>",
        "selection_source": "desktop.list_apps",
        "query": "pdf",
    }
    assert requests[1]["input"] == {
        "app_name": "<selected app from desktop.list_apps>",
        "selection_source": "desktop.list_apps",
        "query": "pdf",
        "direction": "down",
        "pages": 2,
    }
    assert requests[2]["input"] == {"reason": "verify selected discovered app action"}


def test_model_followup_context_discovers_generic_communication_app_after_analysis() -> None:
    target = {
        "kind": "desktop_discovered_app_action",
        "app_query": "chat",
        "app_name_source": "desktop.list_apps",
        "target_action": "safe_shortcut",
        "safe_shortcut_action": "new_message",
        "body_source": "model_generated_content",
        "communication_compose": {
            "recipient": "Alice",
            "send_action": "send",
            "channel": "message",
        },
        "content_transform_hint": "report",
        "post_action_observation": {
            "tool": "desktop.ui_elements",
            "input": {},
        },
    }
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "data.analyze",
                "planning_reason": "planner_builtin_data_analysis",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "data_analysis",
            "followup_target": target,
        },
        allowed_tools=[
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "data.analyze",
                input_preview={"path": "sales.csv", "source_kind": "csv"},
                result={
                    "ok": True,
                    "path": "sales.csv",
                    "source_kind": "csv",
                    "rows": 2,
                    "columns": ["region", "revenue"],
                    "artifact_paths": ["analysis-report.md", "analysis-chart.png"],
                },
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"]["kind"] == "desktop_discovered_app_action"
    assert payload["followup_target"]["app_query"] == "chat"
    assert payload["followup_target"]["communication_compose"] == {
        "channel": "message",
        "recipient": "Alice",
        "send_action": "send",
    }
    assert payload["followup_target"]["transform"] == "report"
    assert "call desktop.list_apps for 'chat'" in message
    assert "Apply the requested content transform: report." in message
    assert custom_api_agent_module._model_followup_app_write_requests(
        "销售分析报告\n- East revenue 10\n- West revenue 20",
        payload["followup_target"],
        [
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "chat", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_discovered_app_write",
        }
    ]
    discovered_requests = custom_api_agent_module._model_followup_discovered_app_write_requests_after_discovery(
        "销售分析报告\n- East revenue 10\n- West revenue 20",
        payload["followup_target"],
        [
            "data.analyze",
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
        [
            _timeline(
                "agent.tool.call",
                "desktop.list_apps",
                input_preview={"query": "chat", "limit": 20},
                result={
                    "ok": True,
                    "action": "desktop.list_apps",
                    "summary": "Found Slack",
                    "data": {
                        "query": "chat",
                        "best_match": {
                            "name": "Slack",
                            "path": "/Applications/Slack.app",
                            "match_score": 96,
                        },
                    },
                },
            )
        ],
    )

    assert [request["tool"] for request in discovered_requests] == [
        "app.open_and_safe_shortcut",
        "desktop.ui_elements",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert discovered_requests[0]["input"] == {"app_name": "Slack", "action": "new_message"}
    assert discovered_requests[2]["input"] == {"text": "Alice"}
    assert discovered_requests[4]["input"] == {
        "text": "销售分析报告\n- East revenue 10\n- West revenue 20"
    }
    assert discovered_requests[5]["input"] == {"action": "send"}


def test_model_followup_context_instructs_generated_note_write() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "browser.extract_text",
                "planning_reason": "planner_prefetch_information_capture_context",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "information_capture",
            "followup_target": {
                "kind": "note_write",
                "target_action": "create_note",
                "body_source": "model_generated_content",
                "context_source": "current_page_content",
                "tool": "notes.create",
            },
        },
        allowed_tools=["browser.extract_text", "notes.create"],
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.extract_text",
                input_preview={},
                result={"ok": True, "data": {"text": "Raw current page text"}},
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"] == {
        "kind": "note_write",
        "target_action": "create_note",
        "body_source": "model_generated_content",
        "write_allowed": True,
        "recommended_tools": ["notes.create"],
        "context_source": "current_page_content",
    }
    assert "saved as a note in Notes" in message
    assert "call notes.create next" in message
    assert "Do not write the raw observed source" in message
    assert custom_api_agent_module._model_followup_app_write_requests(
        "整理后的网页摘要",
        payload["followup_target"],
        ["notes.create"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "整理后的网页摘要"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_note_write",
        }
    ]


def test_model_followup_context_instructs_generated_artifact_write() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "browser.extract_text",
                "planning_reason": "planner_fallback_web_research",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "web_research",
            "artifacts_expected": ["Downloads/research-summary.md"],
            "followup_target": {
                "kind": "artifact_write",
                "target_action": "write_artifact",
                "path": "Downloads/research-summary.md",
                "body_source": "model_generated_content",
                "tool": "artifact.write",
                "intent_kind": "web_research",
            },
        },
        allowed_tools=["browser.extract_text", "artifact.write"],
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.extract_text",
                input_preview={},
                result={"ok": True, "data": {"text": "Raw current page text"}},
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"] == {
        "kind": "artifact_write",
        "target_action": "write_artifact",
        "path": "Downloads/research-summary.md",
        "body_source": "model_generated_content",
        "write_allowed": True,
        "recommended_tools": ["artifact.write"],
        "intent_kind": "web_research",
    }
    assert "durable artifact" in message
    assert "call artifact.write next" in message
    assert "do not write the raw observed source" in message
    assert custom_api_agent_module._model_followup_app_write_requests(
        "整理后的网页摘要",
        payload["followup_target"],
        ["artifact.write"],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "artifact.write",
            "input": {
                "path": "Downloads/research-summary.md",
                "content": "整理后的网页摘要",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_followup_artifact_write",
        }
    ]


def test_model_followup_context_writes_artifact_before_specific_communication() -> None:
    payload = custom_api_agent_module._model_followup_context_payload(
        [
            {
                "tool": "browser.open_url_and_extract_text",
                "planning_reason": "planner_fallback_web_research",
                "continue_to_model": True,
            }
        ],
        {
            "intent_kind": "web_research",
            "artifacts_expected": ["research-summary.md"],
            "followup_target": {
                "kind": "communication_message",
                "recipient": "yachiyo",
                "body_source": "model_generated_content",
                "send_action": "send",
                "mode": "focus",
                "app_name": "Slack",
                "transform": "report",
                "artifact_write": {
                    "target_action": "write_artifact",
                    "path": "research-summary.md",
                    "body_source": "model_generated_content",
                    "tool": "artifact.write",
                    "intent_kind": "web_research",
                },
            },
        },
        allowed_tools=[
            "browser.open_url_and_extract_text",
            "artifact.write",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.open_url_and_extract_text",
                input_preview={"url": "https://example.com"},
                result={"ok": True, "text": "Raw page text"},
            )
        ],
    )
    message = custom_api_agent_module._model_followup_context_message(payload)

    assert payload["followup_target"]["artifact_write"] == {
        "target_action": "write_artifact",
        "path": "research-summary.md",
        "body_source": "model_generated_content",
        "tool": "artifact.write",
        "write_allowed": True,
        "recommended_tools": ["artifact.write"],
        "intent_kind": "web_research",
    }
    assert "Before the delivery step, call artifact.write" in message
    assert "do not stop after writing the artifact" in message.lower()
    assert custom_api_agent_module._model_followup_app_write_requests(
        "整理后的网页研究报告",
        payload["followup_target"],
        [
            "artifact.write",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "artifact.write",
            "input": {
                "path": "research-summary.md",
                "content": "整理后的网页研究报告",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_followup_artifact_write",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "整理后的网页研究报告"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_followup_communication",
        },
    ]


def test_custom_api_agent_loop_writes_generated_followup_content_to_target_app() -> None:
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "把当前网页总结一下并保存到 Obsidian 新笔记"}]
    generated = "整理后的摘要\n- 八千代支持读取网页并写入目标应用"

    def fake_run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
        tool_runs.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages_arg,
                "timeline": timeline_arg,
                "artifacts": artifacts,
                "kwargs": kwargs,
            }
        )
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool_name == "browser.extract_text":
                result = {
                    "ok": True,
                    "text": "Raw page text about Yachiyo runtime.",
                }
            elif tool_name == "app.focus_and_safe_type_text":
                result = {
                    "ok": True,
                    "app_name": input_preview.get("app_name"),
                    "text": input_preview.get("text"),
                }
            else:
                result = {"ok": True}
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "browser.extract_text",
                    "browser.current_page",
                    "app.focus_and_safe_shortcut",
                    "app.focus_and_safe_type_text",
                    "desktop.ui_elements",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=FakeToolLoopProjection(),
        run_tool_requests=fake_run_tool_requests,
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "ignored context",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        messages=messages,
        run_id="run-followup-app-write",
    )

    assert "Obsidian" in str(result)
    assert "输入文字" in str(result)
    assert [request["tool"] for request in tool_runs[0]["tool_requests"]] == [
        "browser.extract_text"
    ]
    assert [request["tool"] for request in tool_runs[1]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text",
        "desktop.ui_elements",
    ]
    assert tool_runs[1]["tool_requests"][0]["input"] == {
        "app_name": "Obsidian",
        "action": "new_note",
    }
    assert tool_runs[1]["tool_requests"][1]["input"] == {
        "app_name": "Obsidian",
        "text": generated,
    }
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["followup_target"]["app_name"] == "Obsidian"
    assert followup["followup_target"]["container_action"] == "new_note"
    assert followup["followup_target"]["recommended_tools"] == [
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text"
    ]
    assert any(
        event["event"] == "agent.desktop.intent_planned"
        and event["detail"] == "app.focus_and_safe_type_text"
        and event["planning_reason"] == "planner_followup_app_write"
        for event in timeline
    )
    assert len(model_calls) == 1
    assert "written into Obsidian" in model_calls[0][-1]["content"]


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
    assert daily_desktop_intent_tool_request("退出全屏", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "toggle_full_screen"},
    }
    assert daily_desktop_intent_tool_request("leave full screen", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "toggle_full_screen"},
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
    assert daily_desktop_intent_tool_request("打开 Finder 新建文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "new_folder"},
    }
    assert daily_desktop_intent_tool_request("Finder 新建文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "new_folder"},
    }
    assert daily_desktop_intent_tool_request("Finder make a new folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "new_folder"},
    }
    assert daily_desktop_intent_tool_request("打开 Slack 新建消息", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "new_message"},
    }
    assert daily_desktop_intent_tool_request("Slack 新建消息", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "new_message"},
    }
    assert daily_desktop_intent_tool_request("微信新建聊天", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "WeChat", "action": "new_message"},
    }
    assert daily_desktop_intent_tool_request("Word 新建消息", allowed_tools) is None
    assert daily_desktop_intent_tool_request("打开 Finder 重命名选中文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "rename_selected"},
    }
    assert daily_desktop_intent_tool_request("Finder 重命名选中文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "rename_selected"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 上一级文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "parent_folder"},
    }
    assert daily_desktop_intent_tool_request("Finder 上一级目录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "parent_folder"},
    }
    assert daily_desktop_intent_tool_request("在 Finder 里显示简介", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_get_info"},
    }
    assert daily_desktop_intent_tool_request("Finder get info", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_get_info"},
    }
    assert daily_desktop_intent_tool_request("打开 Finder 复制选中文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "copy"},
    }
    assert daily_desktop_intent_tool_request("Finder 复制选中文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "copy"},
    }
    assert daily_desktop_intent_tool_request("打开隔空投送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_airdrop"},
    }
    assert daily_desktop_intent_tool_request("Finder 打开隔空投送", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_airdrop"},
    }
    assert daily_desktop_intent_tool_request("打开网络位置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_network"},
    }
    assert daily_desktop_intent_tool_request("Finder 打开网络", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_network"},
    }
    assert daily_desktop_intent_tool_request("打开最近使用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_recents"},
    }
    assert daily_desktop_intent_tool_request("Finder 打开最近使用", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Finder", "action": "finder_recents"},
    }
    assert daily_desktop_intent_tool_request("打开网络设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "网络"},
    }
    assert daily_desktop_intent_tool_request("Slack按空格", allowed_tools) != {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "action": "finder_quick_look"},
    }
    assert daily_desktop_intent_tool_request("Chrome 新建文件夹", allowed_tools) is None
    assert daily_desktop_intent_tool_request("新建文件夹", allowed_tools) is None
    assert daily_desktop_intent_tool_request("Finder 删除选中文件", allowed_tools) is None
    assert daily_desktop_intent_tool_request("Finder 把选中文件移到废纸篓", allowed_tools) is None
    assert daily_desktop_intent_tool_request("打开系统活动监视器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Activity Monitor"},
    }
    assert daily_desktop_intent_tool_request("打开磁盘工具", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Disk Utility"},
    }
    assert daily_desktop_intent_tool_request("打开控制台", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Console"},
    }
    assert daily_desktop_intent_tool_request("打开字体册", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Font Book"},
    }
    assert daily_desktop_intent_tool_request("打开图片查看器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Preview"},
    }
    assert daily_desktop_intent_tool_request("打开系统信息", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "System Information"},
    }
    assert daily_desktop_intent_tool_request("打开脚本编辑器", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Script Editor"},
    }
    assert daily_desktop_intent_tool_request("打开语音备忘录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Voice Memos"},
    }
    assert daily_desktop_intent_tool_request("打开音频 MIDI 设置", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Audio MIDI Setup"},
    }
    assert daily_desktop_intent_tool_request("打开色彩同步实用工具", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "ColorSync Utility"},
    }
    assert daily_desktop_intent_tool_request("打开迁移助理", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open",
        "input": {"app_name": "Migration Assistant"},
    }
    assert daily_desktop_intent_tool_request("打开当前网页的开发者工具", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "open_devtools"},
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
        "desktop.safe_key",
        "desktop.submit_foreground",
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
    assert daily_desktop_intent_tool_requests("在 Finder 搜索 report 并打开第一个结果", allowed_tools) == [
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
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 2},
        },
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 搜索 Alice 并选择第一个结果", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "第一个结果", "role_filter": "", "limit": 80, "click_count": 1},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack search Alice then choose first result",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "first result", "role_filter": "", "limit": 80, "click_count": 1},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "在 Slack 搜索 Alice 并选择第一个结果",
            ["app.focus_and_safe_shortcut", "desktop.safe_type_text", "desktop.search_submit"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("在 Slack 搜索 Alice 后按下箭头再确认", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack search Alice then press down arrow and enter",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "Slack search Alice then press down arrow and enter",
            ["app.focus_and_safe_shortcut", "desktop.safe_type_text", "desktop.safe_key", "desktop.hotkey"],
        )
        == []
    )


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
    assert daily_desktop_intent_tool_requests("在微信里的通讯录按钮点一下", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "通讯录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 的搜索按钮点一下", allowed_tools) == [
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
    assert daily_desktop_intent_tool_requests("在 Linear 上的创建按钮点击", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests("在微信里的通讯录按钮双击", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "WeChat",
                "target": "通讯录",
                "role_filter": "button",
                "limit": 80,
                "click_count": 2,
            },
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 Slack 的搜索按钮点一下",
        ["desktop.safe_type_text"],
    ) == []


def test_daily_desktop_intent_planner_routes_click_then_submit_sequences() -> None:
    allowed_tools = [
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "desktop.submit_foreground",
    ]

    assert daily_desktop_intent_tool_requests("Slack 点击确认按钮然后确认", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "确认",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Linear 点击创建按钮然后确认", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack click Confirm button then confirm",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Confirm",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Linear click Create button then press enter",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "Create",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests("Slack click Send button then send", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Send",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "Slack click Confirm button then confirm",
            ["app.focus_and_click_ui_element"],
        )
        == []
    )


def test_daily_desktop_intent_planner_routes_click_type_submit_sequences() -> None:
    allowed_tools = [
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.submit_foreground",
    ]

    assert daily_desktop_intent_tool_requests("Slack 点击消息框输入 hello 并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
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
    assert daily_desktop_intent_tool_requests(
        "打开 Slack 点击消息框输入 hello 并发送",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "消息",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
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
    assert daily_desktop_intent_tool_requests(
        "Slack click message field and type hello then send",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "message",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
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
    assert daily_desktop_intent_tool_requests("Slack 点击搜索框输入 Alice 并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack 点击搜索按钮然后输入 Alice",
        allowed_tools,
    ) == [
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
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack click Search button then type Alice",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Search",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 Linear 里点击创建按钮然后输入 Task title",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "创建",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Task title"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Slack 点击搜索按钮然后输入 Alice 并回车",
        allowed_tools,
    ) == [
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
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Alice"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "Slack click message field and type hello then send",
            ["app.focus_and_click_ui_element", "desktop.safe_type_text", "desktop.hotkey"],
        )
        == []
    )


def test_daily_desktop_intent_planner_routes_app_command_palette_and_preferences() -> None:
    allowed_tools = [
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "system.settings_open",
    ]
    cases = (
        ("打开 VS Code 命令面板", "app.open_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("在 VS Code 里打开命令面板", "app.focus_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("VS Code command palette", "app.focus_and_safe_shortcut", "Visual Studio Code", "command_palette"),
        ("打开 Obsidian 命令面板", "app.open_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("在 Obsidian 里打开命令面板", "app.focus_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("Obsidian command palette", "app.focus_and_safe_shortcut", "Obsidian", "obsidian_command_palette"),
        ("打开 Slack 偏好设置", "app.open_and_safe_shortcut", "Slack", "preferences"),
        ("在 Slack 里打开偏好设置", "app.focus_and_safe_shortcut", "Slack", "preferences"),
        ("Slack preferences", "app.focus_and_safe_shortcut", "Slack", "preferences"),
        ("打开 Chrome 设置", "app.open_and_safe_shortcut", "Google Chrome", "preferences"),
        ("在 Chrome 里打开设置", "app.focus_and_safe_shortcut", "Google Chrome", "preferences"),
        ("Chrome settings", "app.focus_and_safe_shortcut", "Google Chrome", "preferences"),
    )

    for prompt, tool_name, app_name, action in cases:
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": {"app_name": app_name, "action": action},
            }
        ]

    assert daily_desktop_intent_tool_requests("打开设置", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "system.settings_open",
            "input": {"target": "系统设置"},
        }
    ]
    assert daily_desktop_intent_tool_requests(
        "在 Slack 里打开偏好设置",
        ["system.settings_open"],
    ) == []


def test_daily_desktop_intent_planner_routes_command_palette_input_and_execution() -> None:
    allowed_tools = [
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.safe_key",
        "desktop.submit_foreground",
    ]

    assert daily_desktop_intent_tool_requests(
        "在 VS Code 里打开命令面板输入 Format Document",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "打开 VS Code 命令面板并输入 Format Document",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 VS Code 里打开命令面板输入 Format Document 并回车",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "VS Code run command Format Document",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 VS Code 里打开命令面板输入 Format Document 然后选择第一个结果",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 VS Code 里打开命令面板输入 Format Document 后按下箭头再确认",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_key",
            "input": {"action": "arrow_down", "repeat_count": 1},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "VS Code command palette type Format Document then select first result",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Visual Studio Code", "action": "command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Format Document"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "Obsidian command palette type Toggle reading view and press enter",
        allowed_tools,
    ) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "obsidian_command_palette"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "Toggle reading view"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "confirm"},
        },
    ]
    assert daily_desktop_intent_tool_requests(
        "在 VS Code 里执行命令 Format Document",
        ["app.focus_and_safe_shortcut", "desktop.safe_type_text"],
    ) == []


def test_daily_desktop_intent_planner_routes_app_scoped_safe_keys_and_scroll() -> None:
    allowed_tools = [
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.focus_and_click_ui_element",
    ]

    assert daily_desktop_intent_tool_requests("在 Slack 里按 Tab", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "tab", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里按两次 Tab", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "tab", "repeat_count": 2},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里按 Command F", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里向下滚动两页", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_scroll",
            "input": {"app_name": "Slack", "direction": "down", "pages": 2},
        }
    ]
    assert daily_desktop_intent_tool_requests("切到 Slack 后取消", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Slack", "action": "escape", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 后取消", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Slack", "action": "escape", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Finder 然后按下方向键", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_key",
            "input": {"app_name": "Finder", "action": "arrow_down", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Finder 里按上方向键", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_key",
            "input": {"app_name": "Finder", "action": "arrow_up", "repeat_count": 1},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里按回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_hotkey",
            "input": {"app_name": "Slack", "key": "return", "modifiers": []},
        }
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 后按回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Slack", "key": "return", "modifiers": []},
        }
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里按确认按钮", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "确认",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        }
    ]
    assert daily_desktop_intent_tool_requests(
        "在 Slack 里按 Tab",
        ["app.focus_and_click_ui_element"],
    ) == []
    assert daily_desktop_intent_tool_requests(
        "在 Slack 里按回车",
        ["app.focus_and_click_ui_element"],
    ) == []
    assert daily_desktop_intent_tool_requests(
        "在 Slack 里向下滚动两页",
        ["app.focus_and_safe_key"],
    ) == []


def test_daily_desktop_intent_planner_routes_dynamic_sources_to_ui_inputs() -> None:
    allowed_tools = [
        "desktop.safe_shortcut",
        "desktop.click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_click_ui_element",
    ]
    selected_copy = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
    }
    current_page_link_copy = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy_current_page_link"},
    }
    current_content_copy = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "select_all"},
        },
        selected_copy,
    ]
    foreground_search_click = {
        "protocol": "json_fallback",
        "tool": "desktop.click_ui_element",
        "input": {"target": "搜索", "role_filter": "text", "limit": 80, "click_count": 1},
    }
    paste = {
        "protocol": "json_fallback",
        "tool": "desktop.safe_shortcut",
        "input": {"action": "paste"},
    }

    assert daily_desktop_intent_tool_requests("把选中的内容输入到搜索框", allowed_tools) == [
        selected_copy,
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把选中的内容填到当前输入框", allowed_tools) == [
        selected_copy,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容输入到搜索框", allowed_tools) == [
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容填到当前输入框", allowed_tools) == [
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把当前网页链接输入到地址栏", allowed_tools) == [
        current_page_link_copy,
        {
            "protocol": "json_fallback",
            "tool": "desktop.click_ui_element",
            "input": {"target": "地址", "role_filter": "text", "limit": 80, "click_count": 1},
        },
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把当前页面内容输入到搜索框", allowed_tools) == [
        *current_content_copy,
        foreground_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把当前页面内容输入到当前输入框", allowed_tools) == []
    assert daily_desktop_intent_tool_requests(
        "把选中的内容输入到搜索框",
        ["desktop.safe_type_text"],
    ) == []

    slack_search_click = {
        "protocol": "json_fallback",
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Slack",
            "target": "搜索",
            "role_filter": "text",
            "limit": 80,
            "click_count": 1,
        },
    }
    for prompt in (
        "把选中的内容输入到 Slack 搜索框",
        "Slack 搜索框输入选中的内容",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            selected_copy,
            slack_search_click,
            paste,
        ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容输入到 Slack 搜索框", allowed_tools) == [
        slack_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把当前网页链接输入到 Slack 搜索框", allowed_tools) == [
        current_page_link_copy,
        slack_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("把当前页面内容输入到 Slack 搜索框", allowed_tools) == [
        *current_content_copy,
        slack_search_click,
        paste,
    ]
    assert daily_desktop_intent_tool_requests("打开 Slack 搜索框输入选中的内容", allowed_tools) == [
        selected_copy,
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_click_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "搜索",
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            },
        },
        paste,
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
    assert daily_desktop_intent_tool_requests("在 Slack 的消息框输入 hello", allowed_tools) == [
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
        }
    ]
    assert daily_desktop_intent_tool_requests("在微信里的搜索框输入文件传输助手", allowed_tools) == [
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
    assert daily_desktop_intent_tool_requests("在 Linear 上的搜索框输入 ticket 并回车", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_type_into_ui_element",
            "input": {
                "app_name": "Linear",
                "target": "搜索",
                "text": "ticket",
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
    assert (
        daily_desktop_intent_tool_requests(
            "在 Slack 的消息框输入 hello",
            ["app.focus_and_safe_shortcut", "desktop.safe_type_text"],
        )
        == []
    )


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
    assert daily_desktop_intent_tool_requests("在 Slack 里发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在微信里确认发送", allowed_tools) == [
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
    assert daily_desktop_intent_tool_requests("在 Slack 里提交当前输入", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "submit"},
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
    today_2000 = f"{date.today().isoformat()}T20:00"
    tomorrow = date.today() + timedelta(days=1)
    after_tomorrow = date.today() + timedelta(days=2)
    tomorrow_0900 = f"{tomorrow.isoformat()}T09:00"
    tomorrow_1000 = f"{tomorrow.isoformat()}T10:00"
    tomorrow_1100 = f"{tomorrow.isoformat()}T11:00"
    tomorrow_1500 = f"{tomorrow.isoformat()}T15:00"
    tomorrow_1600 = f"{tomorrow.isoformat()}T16:00"
    after_tomorrow_0900 = f"{after_tomorrow.isoformat()}T09:00"

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
    assert daily_desktop_intent_tool_requests("Chrome 打开下载内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "chrome://downloads/"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Chrome extensions", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "chrome://extensions/"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
        },
    ]
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
    ]
    assert daily_desktop_intent_tool_requests("把当前链接复制给我", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
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
    selected_search_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "搜索选中的内容",
        "搜索当前选中文字",
        "用浏览器搜索选中的内容",
        "用 Google 搜索选中的内容",
        "google selected text",
        "search selected text",
        "search the current selection",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_search_requests
        )
    assert daily_desktop_intent_tool_requests("用 Safari 搜索选中的内容", allowed_tools) == [
        selected_search_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_search_requests[2],
        selected_search_requests[3],
    ]
    assert daily_desktop_intent_tool_requests("search selected text", ["browser.open_url"]) == []
    clipboard_search_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "把剪贴板内容拿去搜索",
        "搜索剪贴板内容",
        "用浏览器搜索剪贴板内容",
        "用 Google 搜索剪贴板内容",
        "search the clipboard",
        "search clipboard contents",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == clipboard_search_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "搜索剪贴板内容",
            ["browser.open_url", "clipboard.read"],
        )
        == []
    )
    assert daily_desktop_intent_tool_request("google clipboard", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "browser.open_url",
        "input": {"url": "https://www.google.com/search?q=clipboard"},
    }
    selected_find_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "在当前页面查找选中的内容",
        "在当前网页查找当前选中文字",
        "用选中内容查找当前页面",
        "find selected text on current page",
        "find current selection in page",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_find_requests
        )
    clipboard_find_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "find"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "在当前页面查找剪贴板内容",
        "用剪贴板内容查找当前网页",
        "find clipboard contents on current page",
        "find the clipboard in current page",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == clipboard_find_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "在当前页面查找剪贴板内容",
            ["desktop.safe_type_text"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("在微信里查找选中的内容", allowed_tools) == [
        selected_find_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "find"},
        },
        selected_find_requests[2],
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 里查找剪贴板内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "find"},
        },
        clipboard_find_requests[1],
    ]
    selected_open_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "打开选中的链接",
        "打开当前选中的网址",
        "用浏览器打开选中的链接",
        "open selected link",
        "open selected URL",
        "open the current selection in browser",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_open_requests
        )
    assert daily_desktop_intent_tool_requests("用 Safari 打开选中的链接", allowed_tools) == [
        selected_open_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_open_requests[2],
        selected_open_requests[3],
    ]
    assert daily_desktop_intent_tool_requests("open selected link in Safari", allowed_tools) == [
        selected_open_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Safari", "action": "focus_address_bar"},
        },
        selected_open_requests[2],
        selected_open_requests[3],
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "open selected URL",
            ["browser.open_url", "app.open"],
        )
        == []
    )
    clipboard_open_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
    ]
    for prompt in (
        "打开剪贴板里的链接",
        "打开剪贴板内容里的网址",
        "用浏览器打开剪贴板内容",
        "open clipboard link",
        "open the clipboard URL",
        "open clipboard contents",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == clipboard_open_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "打开剪贴板里的链接",
            ["clipboard.read", "browser.open_url"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("打开当前网页链接", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "browser.current_page",
            "input": {},
        }
    ]
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
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
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
    assert daily_desktop_intent_tool_requests("微信给文件传输助手粘贴并发送", allowed_tools) == [
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容发给微信文件传输助手", allowed_tools) == [
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Slack find Alice paste and send", allowed_tools) == [
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("send clipboard to Slack Alice", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("微信给文件传输助手发送选中的内容", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Slack send selected text to Alice", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    wechat_selected_text_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests("把当前选中文本发给微信文件传输助手", allowed_tools)
        == wechat_selected_text_requests
    )
    assert (
        daily_desktop_intent_tool_requests("复制当前选中内容发给微信文件传输助手", allowed_tools)
        == wechat_selected_text_requests
    )
    assert daily_desktop_intent_tool_requests("把当前选中文件发给微信文件传输助手", allowed_tools) == []
    wechat_current_page_link_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests("把当前网页链接发给微信文件传输助手", allowed_tools)
        == wechat_current_page_link_requests
    )
    assert (
        daily_desktop_intent_tool_requests("复制当前网页链接发给微信文件传输助手", allowed_tools)
        == wechat_current_page_link_requests
    )
    assert (
        daily_desktop_intent_tool_requests("复制当前网页链接并发给微信文件传输助手", allowed_tools)
        == wechat_current_page_link_requests
    )
    assert daily_desktop_intent_tool_requests("open Slack send current page link to Alice", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
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
    assert daily_desktop_intent_tool_requests("在备忘录里新建 明天买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "notes.create",
            "input": {"body": "明天买牛奶"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在备忘录里创建一条笔记 hello", allowed_tools) == [
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
    selected_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容创建成提醒事项",
        "把当前选中文字加入提醒事项",
        "用选中内容新建提醒",
        "create a reminder from selected text",
        "add selected text to reminders",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_reminder_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "create a reminder from selected text",
            ["reminders.create"],
        )
        == []
    )
    clipboard_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容创建成提醒事项",
        "把剪贴板内容加入提醒事项",
        "用剪贴板内容新建提醒",
        "create a reminder from clipboard",
        "create a reminder from the clipboard",
        "add clipboard contents to reminders",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == clipboard_reminder_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把剪贴板内容加入提醒事项",
            ["clipboard.read", "reminders.create"],
        )
        == []
    )
    current_page_link_reminder_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接创建成提醒事项",
        "把当前网页链接加入提醒事项",
        "用当前网页链接新建提醒",
        "create a reminder from current page link",
        "add current page link to reminders",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_page_link_reminder_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把当前网页链接加入提醒事项",
            ["browser.current_page", "reminders.create"],
        )
        == []
    )
    current_content_reminder_requests = [
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
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Reminders", "action": "new_reminder"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容创建成提醒事项",
        "把当前窗口内容创建成提醒事项",
        "create a reminder from current page content",
        "add current window content to reminders",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_content_reminder_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把当前页面内容创建成提醒事项",
            ["desktop.ui_elements", "reminders.create"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("打开提醒事项添加买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶"},
        },
    ]
    assert daily_desktop_intent_tool_requests("提醒我明天买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶", "due_at": tomorrow_0900},
        },
    ]
    assert daily_desktop_intent_tool_requests("新建提醒事项 明天买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶", "due_at": tomorrow_0900},
        },
    ]
    assert daily_desktop_intent_tool_requests("创建提醒事项 后天买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶", "due_at": after_tomorrow_0900},
        },
    ]
    assert daily_desktop_intent_tool_requests("提醒我今晚买牛奶", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "reminders.create",
            "input": {"title": "买牛奶", "due_at": today_2000},
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
    selected_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容创建成日历事件",
        "把当前选中文字加入日历",
        "用选中内容新建日程",
        "create a calendar event from selected text",
        "add selected text to calendar",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_calendar_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "create a calendar event from selected text",
            ["calendar.create_event"],
        )
        == []
    )
    clipboard_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容创建成日历事件",
        "把剪贴板内容加入日历",
        "用剪贴板内容新建日程",
        "create a calendar event from clipboard",
        "add clipboard contents to calendar",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == clipboard_calendar_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把剪贴板内容加入日历",
            ["clipboard.read", "calendar.create_event"],
        )
        == []
    )
    current_page_link_calendar_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接创建成日历事件",
        "把当前网页链接加入日历",
        "用当前网页链接新建日程",
        "create a calendar event from current page link",
        "add current page link to calendar",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_page_link_calendar_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把当前网页链接加入日历",
            ["browser.current_page", "calendar.create_event"],
        )
        == []
    )
    current_content_calendar_requests = [
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
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Calendar", "action": "new_event"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容创建成日历事件",
        "把当前窗口内容加入日历",
        "create a calendar event from current page content",
        "add current window content to calendar",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_content_calendar_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把当前页面内容创建成日历事件",
            ["desktop.ui_elements", "calendar.create_event"],
        )
        == []
    )
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
    assert daily_desktop_intent_tool_requests("创建日历 明天上午10点开会", allowed_tools) == [
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
    assert daily_desktop_intent_tool_requests("创建日历 家庭", allowed_tools) == []
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
    assert daily_desktop_intent_tool_request("打开日历新建会议", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("Calendar new event", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("Calendar new meeting", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Calendar", "action": "new_event"},
    }
    assert daily_desktop_intent_tool_request("打开邮件新建邮件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_safe_shortcut",
        "input": {"app_name": "Mail", "action": "new_message"},
    }
    assert daily_desktop_intent_tool_request("Mail compose email", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Mail", "action": "new_message"},
    }
    assert daily_desktop_intent_tool_request("Outlook 新建邮件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Microsoft Outlook", "action": "new_message"},
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
    assert daily_desktop_intent_tool_request("打开 Chrome 并按回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.open_and_hotkey",
        "input": {"app_name": "Google Chrome", "key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("Chrome 按回车", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_hotkey",
        "input": {"app_name": "Google Chrome", "key": "return", "modifiers": []},
    }
    assert daily_desktop_intent_tool_request("Slack press Space", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.focus_and_hotkey",
        "input": {"app_name": "Slack", "key": "space", "modifiers": []},
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
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "focus_address_bar"},
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
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Google Chrome", "action": "focus_address_bar"},
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
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
            "tool": "desktop.safe_shortcut",
            "input": {"action": "focus_address_bar"},
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
    assert daily_desktop_intent_tool_requests("打开截图工具", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "screenshot_toolbar"},
        },
    ]
    assert daily_desktop_intent_tool_requests("截取选区", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "screenshot_selection"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open screenshot toolbar", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "screenshot_toolbar"},
        },
    ]
    assert daily_desktop_intent_tool_requests("screen recording toolbar", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "screenshot_toolbar"},
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
    assert daily_desktop_intent_tool_requests("打开微信然后隐藏", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "WeChat"},
        },
    ]
    assert daily_desktop_intent_tool_requests("切到微信然后隐藏", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "WeChat"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "WeChat"},
        },
    ]
    assert daily_desktop_intent_tool_requests("打开 Chrome 然后最小化", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.minimize",
            "input": {"app_name": "Google Chrome"},
        },
    ]
    assert daily_desktop_intent_tool_requests("focus Slack and then hide", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus",
            "input": {"app_name": "Slack"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.hide",
            "input": {"app_name": "Slack"},
        },
    ]
    assert daily_desktop_intent_tool_request("切到微信然后显示", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "app.show",
        "input": {"app_name": "WeChat"},
    }
    safe_window_tools = ["app.hide", "app.minimize", "app.show"]
    assert daily_desktop_intent_tool_requests("Chrome 退出一下", safe_window_tools) == []
    assert daily_desktop_intent_tool_requests("Chrome 关闭一下", safe_window_tools) == []
    assert daily_desktop_intent_tool_requests("打开微信然后隐藏", ["app.open"]) == []
    assert daily_desktop_intent_tool_requests("切到微信然后隐藏", ["app.focus"]) == []
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
    assert daily_desktop_intent_tool_request("打开最后下载的文件", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "latest_download"},
    }
    assert daily_desktop_intent_tool_request("打开上一个下载的文件", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("open Applications folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/Applications"},
    }
    assert daily_desktop_intent_tool_request("打开实用工具文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/Applications/Utilities"},
    }
    assert daily_desktop_intent_tool_request("open Utilities folder", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "/Applications/Utilities"},
    }
    assert daily_desktop_intent_tool_request("打开资源库文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Library"},
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
    assert daily_desktop_intent_tool_request("在 Finder 中显示实用工具文件夹", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.reveal_path",
        "input": {"path": "/Applications/Utilities"},
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
    assert daily_desktop_intent_tool_request("打开个人主目录", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("打开下载列表", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载记录", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载页面", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("打开下载文件夹并排序", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
        "input": {"path": "~/Downloads"},
    }
    assert daily_desktop_intent_tool_request("open downloads page", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.open_path",
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
    assert daily_desktop_intent_tool_request("让 Spotify 播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("让 Spotify 暂停", allowed_tools) is None
    music_app_control_tools = [*allowed_tools, "media.music_app_control"]
    assert daily_desktop_intent_tool_request("让 Spotify 暂停", music_app_control_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_control",
        "input": {"app_name": "Spotify", "action": "pause"},
    }
    assert daily_desktop_intent_tool_request("让 Spotify 下一首", music_app_control_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_control",
        "input": {"app_name": "Spotify", "action": "next"},
    }
    assert daily_desktop_intent_tool_request("打开 Spotify 并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("把 Spotify 打开然后播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("把网易云打开然后播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "网易云音乐"},
    }
    assert daily_desktop_intent_tool_request("Spotify 随便放一首", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "Spotify"},
    }
    assert daily_desktop_intent_tool_request("网易云给我放点歌", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.music_app_open_and_play",
        "input": {"app_name": "网易云音乐"},
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
    assert daily_desktop_intent_tool_requests("让 Spotify 播放周杰伦", allowed_tools) == [
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
    assert daily_desktop_intent_tool_request("让 Apple Music 播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("请 Apple Music 播放", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("打开音乐听听", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("音乐听听", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开音乐听一下", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("打开 Apple Music 并播放", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "media.apple_music_open_and_play",
        "input": {},
    }
    assert daily_desktop_intent_tool_request("把 Apple Music 打开然后播放", allowed_tools) == {
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
    assert daily_desktop_intent_tool_request("Apple Music 随便播一首", allowed_tools) == {
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
    for prompt, action in (
        ("Music pause", "pause"),
        ("Music stop", "pause"),
        ("Music next", "next"),
        ("Apple Music next", "next"),
        ("Music previous", "previous"),
        ("Apple Music previous", "previous"),
        ("Music resume", "play"),
        ("Apple Music resume", "play"),
    ):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) == {
            "protocol": "json_fallback",
            "tool": "media.apple_music_control",
            "input": {"action": action},
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
    for prompt in (
        "静音当前标签页",
        "把当前标签页静音",
        "取消静音当前标签页",
        "mute current tab",
        "mute this tab",
        "unmute current tab",
    ):
        assert daily_desktop_intent_tool_request(prompt, allowed_tools) is None
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
    clipboard_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把剪贴板内容写进备忘录",
        "把剪贴板内容记到备忘录",
        "把剪贴板内容放到备忘录",
        "把剪贴板内容加到笔记",
        "把剪贴板内容新建成备忘录",
        "用剪贴板内容新建备忘录",
        "在备忘录里新建剪贴板内容",
        "paste clipboard into a new note",
        "create a note from clipboard",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == clipboard_note_requests
    assert (
        daily_desktop_intent_tool_requests(
            "把剪贴板内容写进备忘录",
            ["clipboard.read", "notes.create"],
        )
        == []
    )
    selected_text_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容写进备忘录",
        "把当前选中文字保存到备忘录",
        "把选中的文字新建成备忘录",
        "把选中的内容加入备忘录",
        "save selected text to a new note",
        "create a note from selected text",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_text_note_requests
        )
    assert (
        daily_desktop_intent_tool_requests("create a note from selected text", ["notes.create"])
        == []
    )
    current_page_link_note_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页链接写进备忘录",
        "把当前网页链接保存到备忘录",
        "把当前网页存到备忘录",
        "把当前网页加入备忘录",
        "save current page link to a note",
        "create a note from current page link",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == (
            current_page_link_note_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "create a note from current page link",
            ["notes.create", "browser.current_page"],
        )
        == []
    )
    current_content_note_requests = [
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
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Notes", "action": "new_note"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把当前网页内容写进备忘录",
        "把当前页面内容保存到备忘录",
        "把当前网页正文新建成备忘录",
        "把当前网页文字放到笔记",
        "把当前页面复制到备忘录",
        "复制当前页面内容到备忘录",
        "把当前窗口内容写进备忘录",
        "把当前应用内容保存到备忘录",
        "save current page content to a new note",
        "create a note from current page content",
        "copy current page to a note",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == (
            current_content_note_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "create a note from current page content",
            ["notes.create", "browser.current_page"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("把当前屏幕内容写进备忘录", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {"role_filter": "text", "limit": 80},
        }
    ]
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
    assert daily_desktop_intent_tool_request("登录按钮在哪", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "button", "limit": 80},
    }
    assert daily_desktop_intent_tool_request("能看到哪些按钮", allowed_tools) == {
        "protocol": "json_fallback",
        "tool": "desktop.ui_elements",
        "input": {"role_filter": "button", "limit": 80},
    }
    assert daily_desktop_intent_tool_request("where is the login button", allowed_tools) == {
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
        "tool": "desktop.safe_shortcut",
        "input": {"action": "focus_address_bar"},
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
    assert daily_desktop_intent_tool_requests("粘贴后发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("当前输入框粘贴并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容粘贴并发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    selected_paste_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
    ]
    for prompt in (
        "把选中的内容粘贴到当前输入框",
        "把当前选中文字粘贴到这里",
        "copy selected text and paste here",
        "paste selected text into current input",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == selected_paste_requests
        )
    assert daily_desktop_intent_tool_requests("把选中文本粘贴并发送", allowed_tools) == [
        *selected_paste_requests,
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert (
        daily_desktop_intent_tool_requests(
            "把选中的内容粘贴到当前输入框",
            ["desktop.submit_foreground"],
        )
        == []
    )
    for prompt, app_name in (
        ("把选中的内容粘贴到 Slack", "Slack"),
        ("把选中的内容粘贴到 Slack 当前输入框", "Slack"),
        ("把选中的内容粘贴到微信", "WeChat"),
        ("copy selection into Slack", "Slack"),
        ("paste selected text in Slack", "Slack"),
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            selected_paste_requests[0],
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_shortcut",
                "input": {"app_name": app_name, "action": "paste"},
            },
        ]
    for prompt in ("打开 Slack 粘贴选中内容", "open Slack paste selected text"):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            selected_paste_requests[0],
            {
                "protocol": "json_fallback",
                "tool": "app.open_and_safe_shortcut",
                "input": {"app_name": "Slack", "action": "paste"},
            },
        ]
    current_page_link_paste_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
        selected_paste_requests[1],
    ]
    for prompt in (
        "把当前网页链接粘贴到当前输入框",
        "paste current page link here",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_page_link_paste_requests
        )
    assert daily_desktop_intent_tool_requests("把当前网页链接粘贴到 Slack", allowed_tools) == [
        current_page_link_paste_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    assert daily_desktop_intent_tool_requests("在 Slack 粘贴当前网页链接", allowed_tools) == [
        current_page_link_paste_requests[0],
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    assert daily_desktop_intent_tool_requests("把剪贴板内容粘贴到 Slack", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    current_content_copy_requests = [
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
    for prompt in (
        "复制当前网页内容",
        "把当前页面内容复制到剪贴板",
        "copy current page text",
        "copy current window content",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_content_copy_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "复制当前网页内容",
            ["browser.current_page"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("复制当前网页链接", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "copy_current_page_link"},
        },
    ]
    for prompt in (
        "把当前窗口内容粘贴到 Slack",
        "把当前页面内容粘贴到 Slack",
        "paste current page content into Slack",
        "在 Slack 粘贴当前页面内容",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == [
            *current_content_copy_requests,
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_shortcut",
                "input": {"app_name": "Slack", "action": "paste"},
            },
        ]
    assert daily_desktop_intent_tool_requests("打开 Slack 粘贴当前页面内容", allowed_tools) == [
        *current_content_copy_requests,
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
    ]
    for prompt in (
        "把当前页面内容粘贴到当前输入框",
        "paste current page content here",
    ):
        assert daily_desktop_intent_tool_requests(prompt, allowed_tools) == []
    current_content_comm_requests = [
        *current_content_copy_requests,
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
        {"protocol": "json_fallback", "tool": "desktop.search_submit", "input": {}},
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_shortcut",
            "input": {"action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    for prompt in (
        "把当前窗口内容发给微信文件传输助手",
        "把当前页面内容发给微信文件传输助手",
        "微信给文件传输助手发送当前页面内容",
    ):
        assert (
            daily_desktop_intent_tool_requests(prompt, allowed_tools)
            == current_content_comm_requests
        )
    assert (
        daily_desktop_intent_tool_requests(
            "把当前页面内容发给微信文件传输助手",
            ["desktop.ui_elements"],
        )
        == []
    )
    assert daily_desktop_intent_tool_requests("打开微信粘贴后发送", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "WeChat", "action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
    assert daily_desktop_intent_tool_requests("open Slack paste and send", allowed_tools) == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Slack", "action": "paste"},
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
        },
    ]
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
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found installed app: Notes",
                    "data": {"matches": [{"name": "Notes"}]},
                }
            elif tool == "app.open_and_safe_type_text":
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
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Read foreground UI",
                    "data": {"elements": [{"role": "text", "label": "hello"}]},
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
                    "desktop.list_apps",
                    "app.open_and_safe_type_text",
                    "desktop.safe_shortcut",
                    "desktop.ui_elements",
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
                "tool": "desktop.list_apps",
                "input": {"query": "Notes", "limit": 20},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "app.open_and_safe_type_text",
                "input": {"app_name": "Notes", "text": "hello"},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.ui_elements",
                "input": {},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
        ]
    ]
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["detail"] for event in planned_events] == [
        "desktop.list_apps",
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
    ]
    assert [event["source"] for event in planned_events] == [
        "runtime_planner",
        "runtime_planner",
        "runtime_planner",
        "runtime_planner",
    ]
    selection_events = [
        event for event in timeline if event["event"] == "agent.plan.selection"
    ]
    assert selection_events[0]["selection_source"] == "runtime_planner"
    assert selection_events[0]["selection_reason"] == "runtime_planner_full_plan_execution"
    assert selection_events[0]["plan_tools"] == [
        "desktop.list_apps",
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
    ]
    assert selection_events[0]["selected_tools"] == [
        "desktop.list_apps",
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
    ]
    assert selection_events[0]["plan_step_count"] == 4
    completed = [event for event in timeline if event["event"] == "agent.desktop.intent_completed"]
    assert completed[-1]["detail"] == "desktop.safe_shortcut"
    assert completed[-1]["tools"] == [
        "desktop.list_apps",
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
        "desktop.ui_elements",
    ]
    assert [step["tool"] for step in completed[-1]["steps"]] == completed[-1]["tools"]


def test_custom_api_agent_loop_executes_named_app_scope_without_model_or_legacy_rules(
    monkeypatch,
) -> None:
    def fail_legacy_daily_planner(*_args, **_kwargs):
        raise AssertionError("named app scope should be handled by runtime planner")

    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        fail_legacy_daily_planner,
    )

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
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found installed app: SuperData Studio",
                    "data": {"matches": [{"name": "SuperData Studio"}]},
                }
            elif tool == "app.focus_and_safe_type_text":
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
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Read foreground UI",
                    "data": {"app_name": "SuperData Studio", "elements": []},
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
                    "desktop.list_apps",
                    "app.focus_and_safe_type_text",
                    "desktop.ui_elements",
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
            AssertionError("named app scope should execute without calling the model")
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
        "在一个叫 SuperData Studio 的应用里输入 hello",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-named-app-scope",
    )

    assert result == "已切到 SuperData Studio 并输入文字（5 个字符）。"
    assert tool_runs == [
        [
            {
                "protocol": "json_fallback",
                "tool": "desktop.list_apps",
                "input": {"query": "SuperData Studio", "limit": 20},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "app.focus_and_safe_type_text",
                "input": {"app_name": "SuperData Studio", "text": "hello"},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
            {
                "protocol": "json_fallback",
                "tool": "desktop.ui_elements",
                "input": {},
                "source": "runtime_planner",
                "planning_reason": "planner_desktop_operation",
            },
        ]
    ]
    selection_events = [
        event for event in timeline if event["event"] == "agent.plan.selection"
    ]
    assert selection_events[0]["selection_source"] == "runtime_planner"
    assert selection_events[0]["selected_tools"] == [
        "desktop.list_apps",
        "app.focus_and_safe_type_text",
        "desktop.ui_elements",
    ]


def test_custom_api_agent_loop_continues_discovered_communication_app_without_model(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
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
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found installed app: Slack",
                    "data": {
                        "query": payload["query"],
                        "best_match": {
                            "name": "Slack",
                            "path": "/Applications/Slack.app",
                            "match_score": 96,
                            "match_confidence": "high",
                            "match_reason": "category:messaging",
                        },
                        "matches": [
                            {
                                "name": "Slack",
                                "path": "/Applications/Slack.app",
                                "match_score": 96,
                                "match_confidence": "high",
                                "match_reason": "category:messaging",
                            }
                        ],
                    },
                }
            elif tool == "app.open_and_safe_shortcut":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Opened Slack and created a new message",
                    "data": {
                        "app_name": payload["app_name"],
                        "shortcut_action": payload["action"],
                    },
                }
            elif tool == "desktop.inspect_app":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Inspected Slack",
                    "data": {
                        "app_name": payload["app_name"],
                        "focus_verified": True,
                        "ui_elements": {
                            "ok": True,
                            "data": {
                                "app_name": payload["app_name"],
                                "elements": [
                                    {"role": "text", "name": "recipient"},
                                    {"role": "text", "name": "message"},
                                ],
                            },
                        },
                    },
                }
            elif tool == "app.focus_and_type_into_ui_element":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": f"Typed into {payload['target']}",
                    "data": {
                        "app_name": payload["app_name"],
                        "target": payload["target"],
                        "character_count": len(payload["text"]),
                    },
                }
            elif tool == "desktop.search_submit":
                result = {"ok": True, "action": tool, "summary": "Selected recipient", "data": {}}
            elif tool == "desktop.submit_foreground":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Sent foreground message",
                    "data": {"submit_action": payload["action"]},
                }
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Read foreground UI",
                    "data": {"app_name": "Slack", "elements": []},
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
                    "desktop.list_apps",
                    "app.open_and_safe_shortcut",
                    "desktop.inspect_app",
                    "app.focus_and_type_into_ui_element",
                    "desktop.search_submit",
                    "desktop.submit_foreground",
                    "desktop.ui_elements",
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
            AssertionError("discovered communication compose should not call model")
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
        "打开一个聊天软件，给 Alice 发送 hello",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-discovered-communication-compose",
    )

    assert "Slack" in str(result)
    assert "确认发送" in str(result)
    assert [request["tool"] for request in tool_runs[0]] == ["desktop.list_apps"]
    assert [request["tool"] for request in tool_runs[1]] == [
        "app.open_and_safe_shortcut",
        "desktop.inspect_app",
        "app.focus_and_type_into_ui_element",
        "desktop.search_submit",
        "app.focus_and_type_into_ui_element",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert tool_runs[1][0]["input"] == {"app_name": "Slack", "action": "new_message"}
    assert tool_runs[1][1]["input"] == {
        "app_name": "Slack",
        "open_if_needed": False,
        "focus": True,
        "role_filter": "text",
        "limit": 80,
    }
    assert tool_runs[1][2]["input"] == {
        "app_name": "Slack",
        "target": "recipient",
        "text": "Alice",
        "role_filter": "text",
        "limit": 80,
    }
    assert tool_runs[1][4]["input"] == {
        "app_name": "Slack",
        "target": "message",
        "text": "hello",
        "role_filter": "text",
        "limit": 80,
    }
    assert tool_runs[1][5]["input"] == {"action": "send"}
    assert tool_runs[1][0]["input_resolution"] == {
        "tool": "app.open_and_safe_shortcut",
        "field": "app_name",
        "requested_app_name": "messaging",
        "resolved_app_name": "Slack",
        "source_tool": "desktop.list_apps",
        "app_resolution_score": "96",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "category:messaging",
        "resolved_app_path": "/Applications/Slack.app",
    }
    selection_events = _planner_selection_events(timeline)
    assert selection_events[0]["followup_target"]["communication_compose"] == {
        "channel": "message",
        "recipient": "Alice",
        "body": "hello",
        "send_action": "send",
    }
    completed = [event for event in timeline if event["event"] == "agent.desktop.intent_completed"]
    assert completed[-1]["tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.inspect_app",
        "app.focus_and_type_into_ui_element",
        "desktop.search_submit",
        "app.focus_and_type_into_ui_element",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]


def test_custom_api_agent_loop_preserves_discovered_app_compose_remaining_requests_on_approval(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    tool_calls: list[tuple[str, dict[str, Any]]] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        appended_events.append({"run_id": run_id, "event_type": event_type, "payload": payload})

    def call_agent_tool(
        tool_request,
        _allowed_tools,
        _broker,
        timeline_arg,
        *,
        artifacts=None,
        run_id="",
        budget=None,
    ):
        tool = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        tool_calls.append((tool, payload))
        if tool == "desktop.list_apps":
            result = {
                "ok": True,
                "action": tool,
                "summary": "Found installed app: Slack",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Slack",
                        "path": "/Applications/Slack.app",
                        "match_score": 96,
                        "match_confidence": "high",
                        "match_reason": "category:messaging",
                    },
                    "matches": [
                        {
                            "name": "Slack",
                            "path": "/Applications/Slack.app",
                            "match_score": 96,
                            "match_confidence": "high",
                            "match_reason": "category:messaging",
                        }
                    ],
                },
            }
        elif tool == "app.open_and_safe_shortcut":
            result = {
                "ok": True,
                "action": tool,
                "summary": "Opened Slack and created a new message",
                "data": {"app_name": payload["app_name"], "shortcut_action": payload["action"]},
            }
        elif tool == "desktop.inspect_app":
            result = {
                "ok": True,
                "action": tool,
                "summary": "Inspected Slack",
                "data": {
                    "app_name": payload["app_name"],
                    "ready_for_foreground_action": True,
                    "checks": {"app_running": True, "frontmost": True},
                    "ui_elements": {
                        "ok": True,
                        "data": {
                            "app_name": payload["app_name"],
                            "elements": [
                                {"role": "text", "name": "recipient"},
                                {"role": "text", "name": "message"},
                            ],
                        },
                    },
                },
            }
        elif tool == "app.focus_and_type_into_ui_element":
            result = {
                "ok": False,
                "approval_required": True,
                "tool": tool,
                "risk_level": "medium",
                "policy_reason": "Typing into a foreground app needs review.",
            }
        else:
            raise AssertionError(f"unexpected tool before approval pause: {tool}")
        timeline_arg.append(_timeline("agent.tool.call", tool, input_preview=payload, result=result))
        if run_id:
            append_run_event(
                run_id,
                "agent.tool.call",
                {"tool": tool, "input_preview": payload, "result": result},
            )
        return result

    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda _user_goal, _tool_name: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "approval-1",
            now=lambda: "2026-06-30T00:00:00Z",
        ),
        call_agent_tool=call_agent_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "desktop.list_apps",
                    "app.open_and_safe_shortcut",
                    "desktop.inspect_app",
                    "app.focus_and_type_into_ui_element",
                    "desktop.search_submit",
                    "desktop.submit_foreground",
                    "desktop.ui_elements",
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
            AssertionError("approval-paused discovered compose should not call model")
        ),
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    try:
        loop.run(
            {"name": "Yachiyo"},
            "打开一个聊天软件，给 Alice 发送 hello",
            broker={"broker": True},
            timeline=timeline,
            artifacts=[],
            run_id="run-discovered-compose-approval",
        )
    except AgentApprovalRequired as exc:
        pending = exc.pending_approval
    else:
        raise AssertionError("expected discovered app compose to pause for approval")

    assert [tool for tool, _payload in tool_calls] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.inspect_app",
        "app.focus_and_type_into_ui_element",
    ]
    assert pending["tool"] == "app.focus_and_type_into_ui_element"
    assert pending["tool_request"]["input"] == {
        "app_name": "Slack",
        "target": "recipient",
        "text": "Alice",
        "role_filter": "text",
        "limit": 80,
    }
    assert pending["risk_level"] == "medium"
    assert pending["policy_reason"] == "Typing into a foreground app needs review."
    remaining_requests = pending["remaining_tool_requests"]
    assert [request["tool"] for request in remaining_requests] == [
        "desktop.search_submit",
        "app.focus_and_type_into_ui_element",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert remaining_requests[1]["input"] == {
        "app_name": "Slack",
        "target": "message",
        "text": "hello",
        "role_filter": "text",
        "limit": 80,
    }
    assert remaining_requests[2]["input"] == {"action": "send"}
    assert remaining_requests[1]["source"] == "runtime_planner"
    assert remaining_requests[1]["planning_reason"] == "planner_discovered_app_followup"
    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "discover_apps-desktop-state",
        "open-selected-discovered-app",
        "inspect-selected-communication-compose-ui",
    ]
    blocked_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "blocked"
    ]
    assert [event["step_id"] for event in blocked_todos] == [
        "fill-selected-communication-recipient"
    ]
    waiting_checkpoints = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["status"] == "waiting_approval"
        and event.get("source_event", {}).get("event") == "agent.tool.call"
    ]
    assert [event["step_id"] for event in waiting_checkpoints] == [
        "fill-selected-communication-recipient"
    ]
    approval_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_approval_required"
    ]
    assert approval_events[-1] == {
        "event": "agent.desktop.intent_approval_required",
        "detail": "app.focus_and_type_into_ui_element",
        "tool": "app.focus_and_type_into_ui_element",
        "status": "approval_required",
        "source": "runtime_planner",
        "reason": "tool_policy_requires_approval",
        "input_preview": {
            "app_name": "Slack",
            "target": "recipient",
            "text": "Alice",
            "role_filter": "text",
            "limit": 80,
        },
        "planning_reason": "planner_discovered_app_followup",
        "approval_id": "approval-1",
        "risk_level": "medium",
        "policy_reason": "Typing into a foreground app needs review.",
    }
    assert appended_events[-1]["event_type"] == "agent.desktop.intent_approval_required"
    assert appended_events[-1]["payload"]["source"] == "runtime_planner"
    assert appended_events[-1]["payload"]["planning_reason"] == "planner_discovered_app_followup"


def test_custom_api_agent_loop_completes_resolved_discovered_app_open_without_model_followup(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    tool_calls: list[tuple[str, dict[str, Any]]] = []
    model_calls: list[Any] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        appended_events.append({"run_id": run_id, "event_type": event_type, "payload": payload})

    def call_agent_tool(
        tool_request,
        _allowed_tools,
        _broker,
        timeline_arg,
        *,
        artifacts=None,
        run_id="",
        budget=None,
    ):
        tool = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        tool_calls.append((tool, payload))
        if tool == "desktop.list_apps":
            result = {
                "ok": True,
                "action": tool,
                "summary": "Found installed app: Safari",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Safari",
                        "path": "/Applications/Safari.app",
                        "match_score": 93,
                        "match_confidence": "high",
                    },
                    "apps": [
                        {
                            "name": "Safari",
                            "path": "/Applications/Safari.app",
                            "match_score": 93,
                            "match_confidence": "high",
                        }
                    ],
                },
            }
        elif tool == "app.open":
            result = {
                "ok": True,
                "action": tool,
                "summary": f"Opened {payload['app_name']}",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        else:
            raise AssertionError(f"unexpected tool: {tool}")
        timeline_arg.append(_timeline("agent.tool.call", tool, input_preview=payload, result=result))
        if run_id:
            append_run_event(
                run_id,
                "agent.tool.call",
                {"tool": tool, "input_preview": payload, "result": result},
            )
        return result

    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=tool_input_preview,
        run_budget=lambda _run_id, _timeline_value: budget,
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda _user_goal, _tool_name: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "approval-1",
            now=lambda: "2026-06-30T00:00:00Z",
        ),
        call_agent_tool=call_agent_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["desktop.list_apps", "app.open"]},
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use desktop tools for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: model_calls.append(_args) or (_ for _ in ()).throw(
            AssertionError("resolved discovered app open should not call model")
        ),
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "找一个能编辑 PDF 的本机应用并打开它",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-discovered-open",
    )

    assert "Safari" in str(result)
    assert tool_calls == [
        ("desktop.list_apps", {"query": "pdf", "limit": 20}),
        ("app.open", {"app_name": "Safari"}),
    ]
    assert model_calls == []
    assert not any(event["event"] == "agent.model.followup_context" for event in timeline)
    assert not any(event["event_type"] == "agent.model.followup_context" for event in appended_events)
    completed = [
        event for event in timeline if event["event"] == "agent.desktop.intent_completed"
    ]
    assert completed[-1]["tools"] == ["desktop.list_apps", "app.open"]


def test_auto_discovered_app_open_followup_verifies_active_window() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "browser", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found Safari",
                "data": {
                    "query": "browser",
                    "apps": [
                        {
                            "name": "Safari",
                            "path": "/Applications/Safari.app",
                            "match_score": 93,
                        }
                    ],
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "browser",
                "target_action": "open_app",
            }
        },
        ["app.open", "desktop.active_window"],
        timeline,
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Safari"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "app.open",
                "field": "app_name",
                "requested_app_name": "browser",
                "resolved_app_name": "Safari",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Safari.app",
                "app_resolution_score": "93",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
        },
    ]

    alias_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "browser",
                "target_action": "open_app",
            }
        },
        ["desktop.open_app", "desktop.active_window"],
        timeline,
    )

    assert alias_requests[0]["tool"] == "desktop.open_app"
    assert alias_requests[0]["input"] == {"app_name": "Safari"}
    assert alias_requests[0]["input_resolution"]["tool"] == "desktop.open_app"
    assert alias_requests[1]["tool"] == "desktop.active_window"

    read_ui_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "browser",
                "target_action": "open_app",
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {"role_filter": "text", "limit": 80},
                },
            }
        },
        ["desktop.open_app", "desktop.read_ui"],
        timeline,
    )

    assert [request["tool"] for request in read_ui_requests] == [
        "desktop.open_app",
        "desktop.read_ui",
    ]
    assert read_ui_requests[1]["input"] == {"role_filter": "text", "limit": 80}
    assert read_ui_requests[1]["source"] == "runtime_planner"
    assert read_ui_requests[1]["planning_reason"] == "planner_discovered_app_followup"

    continuing_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "browser",
                "target_action": "open_app",
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {"limit": 80},
                    "continue_to_model": True,
                },
            }
        },
        ["desktop.open_app", "desktop.read_ui"],
        timeline,
    )

    assert [request["tool"] for request in continuing_requests] == [
        "desktop.open_app",
        "desktop.read_ui",
    ]
    assert continuing_requests[1]["input"] == {"limit": 80}
    assert continuing_requests[1]["continue_to_model"] is True


def test_discovered_app_direct_completion_requires_planned_verification() -> None:
    planned_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "browser", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
            "continue_to_model": True,
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": "browser",
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]
    selection_payload = {
        "followup_target": {
            "kind": "desktop_discovered_app_action",
            "app_query": "browser",
            "target_action": "open_app",
        }
    }
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "browser", "limit": 20},
            result={
                "ok": True,
                "data": {
                    "query": "browser",
                    "apps": [
                        {
                            "name": "Safari",
                            "path": "/Applications/Safari.app",
                            "match_score": 93,
                            "match_confidence": "high",
                        }
                    ],
                    "best_match": {
                        "name": "Safari",
                        "path": "/Applications/Safari.app",
                        "match_score": 93,
                        "match_confidence": "high",
                    },
                },
            },
        ),
        _timeline(
            "agent.tool.call",
            "app.open",
            input_preview={"app_name": "Safari"},
            result={"ok": True},
        ),
        _timeline(
            "agent.tool.call",
            "desktop.active_window",
            input_preview={},
            result={"ok": True, "data": {"app_name": "Chrome", "title": "Search"}},
        ),
    ]

    assert (
        custom_api_agent_module._runtime_planner_completed_discovered_app_direct_action(
            planned_requests,
            selection_payload,
            timeline,
            tool_timeline_start=0,
        )
        is False
    )

    timeline[-1] = _timeline(
        "agent.tool.call",
        "desktop.active_window",
        input_preview={},
        result={"ok": True, "data": {"app_name": "Safari", "title": "Start Page"}},
    )
    assert (
        custom_api_agent_module._runtime_planner_completed_discovered_app_direct_action(
            planned_requests,
            selection_payload,
            timeline,
            tool_timeline_start=0,
        )
        is True
    )


def test_runtime_planner_progress_records_auto_discovered_app_observation() -> None:
    decision = RuntimePlanner().decision(
        "打开一个能画图的应用，画一个圆并保存到桌面",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.ui_elements"],
    )
    appended_events: list[dict[str, Any]] = []
    loop = _private_runtime_loop(
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )
    timeline = [
        _timeline(
            "agent.task.todo.updated",
            "Discover desktop state",
            source="runtime_planner",
            decision_id=decision.decision_id,
            step_id="discover_apps-desktop-state",
            status="completed",
        )
    ]
    tool_timeline_start = len(timeline)
    timeline.extend(
        [
            _timeline(
                "agent.tool.call",
                "app.open",
                input_preview={"app_name": "Pixelmator Pro"},
                result={
                    "ok": True,
                    "action": "app.open",
                    "data": {"app_name": "Pixelmator Pro"},
                },
            ),
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                input_preview={"limit": 80},
                result={
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "data": {"elements": [{"role": "button", "name": "Shape"}]},
                },
            ),
        ]
    )

    loop._record_runtime_planner_task_progress_events(
        decision,
        timeline=timeline,
        tool_timeline_start=tool_timeline_start,
        run_id="run-discovered-observe",
    )

    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "discover_apps-desktop-state",
        "open-selected-discovered-app",
        "observe-selected-discovered-app",
    ]
    completed_checkpoints = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_checkpoints] == [
        "open-selected-discovered-app",
        "observe-selected-discovered-app",
    ]
    assert [
        event["payload"]["step_id"]
        for event in appended_events
        if event["event_type"] == "agent.task.todo.updated"
    ] == ["open-selected-discovered-app", "observe-selected-discovered-app"]


def test_runtime_planner_replans_empty_auto_discovered_app_observation() -> None:
    decision = RuntimePlanner().decision(
        "打开一个能画图的应用，画一个圆并保存到桌面",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.ui_elements"],
    )
    run_events: list[dict[str, Any]] = []
    loop = _private_runtime_loop(
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload}
        ),
    )
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.open",
            input_preview={"app_name": "Pixelmator Pro"},
            result={"ok": True, "data": {"app_name": "Pixelmator Pro"}},
        ),
        _timeline(
            "agent.tool.call",
            "desktop.ui_elements",
            input_preview={"limit": 80},
            result={"ok": True, "data": {"elements": [], "count": 0}},
        ),
    ]

    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-discovered-observe-replan",
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_step_id"] == "observe-selected-discovered-app"
    assert payload["source_tool_name"] == "desktop.ui_elements"
    assert "no UI elements or readable text" in payload["failure_detail"]
    assert [
        event["payload"]["request_id"]
        for event in run_events
        if event["event_type"] == "agent.replan.requested"
    ] == [payload["request_id"]]

    recovery_requests = custom_api_agent_module._auto_replan_verification_recovery_requests(
        payloads,
        ["desktop.active_window", "desktop.list_windows", "screen.capture"],
    )
    assert [request["tool"] for request in recovery_requests] == [
        "desktop.active_window",
        "desktop.list_windows",
        "screen.capture",
    ]
    assert all(request["continue_to_model"] is True for request in recovery_requests)
    assert {
        request["replan_request_id"] for request in recovery_requests
    } == {payload["request_id"]}


def test_runtime_planner_replan_maps_tool_failure_to_plan_step_without_request_trace() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    loop = _private_runtime_loop()
    timeline = [
        _timeline(
            "agent.tool.call",
            "data.analyze",
            input_preview={"path": "sales.csv"},
            result={"ok": False, "error": "unsupported chart type"},
        )
    ]

    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-analysis",
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["trigger"] == "tool_failure"
    assert payload["source_step_id"] == "analyze-data-file"
    assert payload["source_tool_name"] == "data.analyze"
    assert payload["target_capability_id"] == "data.analysis"
    assert payload["fallback_tools"] == ["terminal.run"]
    assert payload["metadata"]["step_title"] == "Analyze data file"
    assert payload["metadata"]["step_action"] == "analyze_data_file"
    assert "failed_step: analyze-data-file" in payload["replan_prompt"]


def test_runtime_planner_replan_accepts_tool_failed_timeline_events() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    loop = _private_runtime_loop()
    timeline = [
        _timeline(
            "agent.tool.failed",
            "data.analyze",
            input_preview={"path": "sales.csv"},
            result={"ok": False, "error": "parser crashed"},
            status="failed",
        )
    ]

    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-tool-failed",
    )
    loop._record_runtime_planner_task_progress_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-tool-failed",
    )

    assert len(payloads) == 1
    assert payloads[0]["failure_event_type"] == "agent.tool.failed"
    assert payloads[0]["source_step_id"] == "analyze-data-file"
    blocked_todo = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["step_id"] == "analyze-data-file"
        and event["status"] == "blocked"
    ][0]
    assert blocked_todo["source_event"] == {
        "event": "agent.tool.failed",
        "detail": "data.analyze",
    }


def test_auto_replan_fallback_recovery_reuses_safe_file_inputs() -> None:
    decision = RuntimePlanner().decision(
        "请分析 legacy-report.xls 并输出报告",
        allowed_tools=[
            "workspace.read",
            "desktop.open_path",
            "browser.current_page",
            "terminal.run",
            "artifact.write",
        ],
    )
    loop = _private_runtime_loop()
    timeline = [
        _timeline(
            "agent.tool.call",
            "workspace.read",
            input_preview={"path": "legacy-report.xls"},
            result={"ok": False, "error": "unsupported file encoding"},
        )
    ]

    payloads = loop._record_runtime_planner_replan_events(
        decision,
        timeline=timeline,
        tool_timeline_start=0,
        run_id="run-file-replan",
    )
    fallback_requests = custom_api_agent_module._auto_replan_fallback_recovery_requests(
        payloads,
        ["desktop.open_path", "browser.current_page", "terminal.run"],
    )

    assert [request["tool"] for request in fallback_requests] == [
        "desktop.open_path",
        "browser.current_page",
    ]
    assert fallback_requests[0]["input"] == {"path": "legacy-report.xls"}
    assert fallback_requests[1]["input"] == {}
    assert {request["continue_to_model"] for request in fallback_requests} == {True}
    assert {request["planning_reason"] for request in fallback_requests} == {
        "planner_replan_fallback_recovery"
    }
    assert {request["replan_trigger"] for request in fallback_requests} == {"tool_failure"}
    assert {request["step_id"] for request in fallback_requests} == {"inspect-data-source"}
    assert all(request.get("replan_request_id") for request in fallback_requests)

    data_failure = [
        {
            "request_id": "replan-terminal",
            "trigger": "tool_failure",
            "source_step_id": "analyze-data-file",
            "target_capability_id": "data.analysis",
            "fallback_tools": ["terminal.run"],
            "metadata": {"input_preview": {"path": "sales.csv"}},
        }
    ]
    assert (
        custom_api_agent_module._auto_replan_fallback_recovery_requests(
            data_failure,
            ["terminal.run"],
        )
        == []
    )


def test_runtime_planner_progress_completes_blocked_step_after_replan_recovery() -> None:
    decision = RuntimePlanner().decision(
        "请分析 legacy-report.xls 并输出报告",
        allowed_tools=[
            "workspace.read",
            "desktop.open_path",
            "browser.current_page",
            "terminal.run",
            "artifact.write",
        ],
    )
    loop = _private_runtime_loop()
    timeline = [
        _timeline(
            "agent.task.todo.updated",
            "Inspect data source",
            source="runtime_planner",
            decision_id=decision.decision_id,
            plan_id=decision.plan.plan_id,
            step_id="inspect-data-source",
            tool="workspace.read",
            status="blocked",
            todo={"status": "blocked", "title": "Inspect data source"},
        ),
        _timeline(
            "agent.task.checkpoint.updated",
            "Verify Inspect data source",
            source="runtime_planner",
            decision_id=decision.decision_id,
            plan_id=decision.plan.plan_id,
            step_id="inspect-data-source",
            tool="workspace.read",
            status="blocked",
            checkpoint={"status": "blocked", "title": "Verify Inspect data source"},
        ),
    ]
    tool_timeline_start = len(timeline)
    timeline.append(
        _timeline(
            "agent.tool.call",
            "desktop.open_path",
            input_preview={"path": "legacy-report.xls"},
            result={"ok": True, "data": {"path": "legacy-report.xls"}},
            step_id="inspect-data-source",
            capability_id="file.workspace_read",
            replan_request_id="replan-file",
            replan_trigger="tool_failure",
        )
    )

    loop._record_runtime_planner_task_progress_events(
        decision,
        timeline=timeline,
        tool_timeline_start=tool_timeline_start,
        run_id="run-file-recovery",
    )

    completed_todo = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["step_id"] == "inspect-data-source"
        and event["status"] == "completed"
    ][0]
    completed_checkpoint = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["step_id"] == "inspect-data-source"
        and event["status"] == "completed"
    ][0]
    assert completed_todo["source_event"] == {
        "event": "agent.tool.call",
        "detail": "desktop.open_path",
    }
    assert completed_checkpoint["source_event"] == completed_todo["source_event"]


def test_auto_discovered_app_compose_followup_types_and_verifies() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "markdown", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found Obsidian",
                "data": {
                    "query": "markdown",
                    "apps": [
                        {
                            "name": "Obsidian",
                            "path": "/Applications/Obsidian.app",
                            "match_score": 91,
                        }
                    ],
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "markdown",
                "target_action": "safe_shortcut",
                "safe_shortcut_action": "new_document",
                "compose_text": "周报",
                "body_source": "explicit_user_text",
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        ["app.open_and_safe_shortcut", "desktop.safe_type_text", "desktop.ui_elements"],
        timeline,
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "new_document"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "app.open_and_safe_shortcut",
                "field": "app_name",
                "requested_app_name": "markdown",
                "resolved_app_name": "Obsidian",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Obsidian.app",
                "app_resolution_score": "91",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "周报"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
        },
    ]


def test_auto_discovered_app_search_followup_types_submits_and_verifies() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "image", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found Figma",
                "data": {
                    "query": "image",
                    "apps": [
                        {
                            "name": "Figma",
                            "path": "/Applications/Figma.app",
                            "match_score": 94,
                        }
                    ],
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "safe_shortcut_action": "find",
                "app_search": {
                    "query": "logo 模板",
                    "target": "搜索",
                    "submit": True,
                    "verify": True,
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Figma", "action": "find"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "app.open_and_safe_shortcut",
                "field": "app_name",
                "requested_app_name": "image",
                "resolved_app_name": "Figma",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Figma.app",
                "app_resolution_score": "94",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.safe_type_text",
            "input": {"text": "logo 模板"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "desktop.safe_type_text",
                "field": "app_name",
                "requested_app_name": "image",
                "resolved_app_name": "Figma",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Figma.app",
                "app_resolution_score": "94",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.search_submit",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "desktop.search_submit",
                "field": "app_name",
                "requested_app_name": "image",
                "resolved_app_name": "Figma",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Figma.app",
                "app_resolution_score": "94",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
        },
    ]
    click_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "app_search": {
                    "query": "logo 模板",
                    "target": "搜索",
                    "submit": True,
                    "focus": {
                        "tool": "desktop.click_ui_element",
                        "input": {
                            "target": "搜索",
                            "role_filter": "text",
                            "click_count": 1,
                            "limit": 80,
                        },
                    },
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open",
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert [request["tool"] for request in click_requests] == [
        "app.open",
        "desktop.click_ui_element",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.ui_elements",
    ]
    assert click_requests[1]["input"] == {
        "target": "搜索",
        "role_filter": "text",
        "click_count": 1,
        "limit": 80,
    }
    assert click_requests[1]["input_resolution"]["resolved_app_name"] == "Figma"
    assert click_requests[2]["input"] == {"text": "logo 模板"}
    result_click_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "safe_shortcut_action": "find",
                "app_search": {
                    "query": "logo 模板",
                    "target": "搜索",
                    "submit": True,
                    "result_selection": {
                        "action": "click",
                        "tool": "desktop.click_ui_element",
                        "input": {
                            "target": "第一个结果",
                            "role_filter": "",
                            "limit": 80,
                            "click_count": 1,
                        },
                    },
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert [request["tool"] for request in result_click_requests] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert result_click_requests[3]["input"] == {
        "target": "第一个结果",
        "role_filter": "",
        "limit": 80,
        "click_count": 1,
    }
    assert result_click_requests[3]["input_resolution"]["resolved_app_name"] == "Figma"

    key_confirm_requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "image",
                "target_action": "app_search",
                "safe_shortcut_action": "find",
                "app_search": {
                    "query": "logo 模板",
                    "target": "搜索",
                    "submit": True,
                    "submit_action": "confirm",
                    "result_selection": {
                        "action": "key_confirm",
                        "key": {
                            "tool": "desktop.safe_key",
                            "input": {"action": "arrow_down", "repeat_count": 1},
                        },
                        "confirm": {
                            "tool": "desktop.submit_foreground",
                            "input": {"action": "confirm"},
                        },
                    },
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert [request["tool"] for request in key_confirm_requests] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.safe_key",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert key_confirm_requests[2]["input"] == {"action": "arrow_down", "repeat_count": 1}
    assert key_confirm_requests[3]["input"] == {"action": "confirm"}


def test_auto_discovered_app_generated_write_followup_returns_to_model() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "markdown", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found Obsidian",
                "data": {
                    "query": "markdown",
                    "apps": [
                        {
                            "name": "Obsidian",
                            "path": "/Applications/Obsidian.app",
                            "match_score": 91,
                        }
                    ],
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_app_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_app_action",
                "app_query": "markdown",
                "target_action": "safe_shortcut",
                "safe_shortcut_action": "new_document",
                "body_source": "model_generated_content",
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        ["app.open_and_safe_shortcut", "desktop.safe_type_text", "desktop.ui_elements"],
        timeline,
    )

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": "Obsidian", "action": "new_document"},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "input_resolution": {
                "tool": "app.open_and_safe_shortcut",
                "field": "app_name",
                "requested_app_name": "markdown",
                "resolved_app_name": "Obsidian",
                "source_tool": "desktop.list_apps",
                "resolved_app_path": "/Applications/Obsidian.app",
                "app_resolution_score": "91",
            },
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "planner_discovered_app_followup",
            "continue_to_model": True,
        },
    ]


def test_custom_api_agent_loop_auto_dispatches_creative_pending_steps(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    tool_runs: list[list[dict[str, Any]]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.shortcut",
        "screen.capture",
    ]

    def run_tool_requests(
        tool_requests,
        _allowed_tools,
        _broker,
        messages_arg,
        timeline_arg,
        _artifacts,
        **_kwargs,
    ):
        tool_runs.append([dict(request) for request in tool_requests])
        for request in tool_requests:
            tool = str(request.get("tool") or "")
            payload = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found Pixelmator Pro",
                    "data": {
                        "query": "image",
                        "best_match": {
                            "name": "Pixelmator Pro",
                            "path": "/Applications/Pixelmator Pro.app",
                            "match_score": 96,
                            "match_confidence": "high",
                        },
                    },
                }
            elif tool == "app.open":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Opened Pixelmator Pro",
                    "data": {"app_name": payload.get("app_name")},
                }
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {
                        "elements": [
                            {"role": "button", "name": "Circle"},
                            {"role": "button", "name": "Save"},
                        ],
                        "count": 2,
                    },
                }
            elif tool == "desktop.click_ui_element":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {"target": payload.get("target")},
                }
            elif tool == "desktop.shortcut":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {
                        "key": payload.get("key"),
                        "modifiers": payload.get("modifiers"),
                    },
                }
            elif tool == "screen.capture":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {"path": "artifacts/creative-result.png"},
                }
            else:
                raise AssertionError(f"unexpected tool: {tool}")
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool,
                    input_preview=payload,
                    result=result,
                )
            )
            messages_arg.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool}: {result}",
                }
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": allowed_tools},
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda tools: [{"name": tool} for tool in tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use runtime planner for desktop actions.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "继续执行剩余桌面计划。"},
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
        "打开一个能画图的应用，画一个圆并保存到桌面",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-creative-followup",
    )

    assert [request["tool"] for request in tool_runs[0]] == ["desktop.list_apps"]
    assert [request["tool"] for request in tool_runs[1]] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert [request["tool"] for request in tool_runs[2]] == [
        "desktop.click_ui_element",
        "desktop.shortcut",
        "screen.capture",
    ]
    assert tool_runs[2][0]["input"] == {
        "target": "circle ellipse shape",
        "role_filter": "button",
        "limit": 80,
        "click_count": 1,
    }
    assert tool_runs[2][1]["input"] == {"key": "s", "modifiers": ["command"]}
    assert "Command+S" in str(result)
    assert len(model_calls) == 1
    assert "Continue the pending Runtime Plan steps in order" in model_calls[0][-1]["content"]
    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "discover_apps-desktop-state",
        "open-selected-discovered-app",
        "observe-selected-discovered-app",
        "select-discovered-app-circle-tool",
        "save-discovered-app-creative-result",
        "verify-discovered-app-creative-result",
    ]


def test_runtime_planner_keeps_generic_app_discovery_when_later_ui_tools_unavailable() -> None:
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "desktop.ui_elements",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
    ]

    full_requests = planner_tool_requests(
        "打开一个能画图的应用，画一个圆并保存到桌面",
        allowed_tools,
    )
    direct_requests = planner_direct_tool_requests(
        "打开一个能画图的应用，画一个圆并保存到桌面",
        allowed_tools,
    )

    assert full_requests == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "image", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
            "continue_to_model": True,
        }
    ]
    assert direct_requests == full_requests


def test_custom_api_agent_loop_auto_dispatches_generic_discovered_app_pending_steps(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    tool_runs: list[list[dict[str, Any]]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    allowed_tools = [
        "desktop.list_apps",
        "app.open",
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "screen.capture",
    ]

    def run_tool_requests(
        tool_requests,
        _allowed_tools,
        _broker,
        messages_arg,
        timeline_arg,
        _artifacts,
        **_kwargs,
    ):
        tool_runs.append([dict(request) for request in tool_requests])
        for request in tool_requests:
            tool = str(request.get("tool") or "")
            payload = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found Pixelmator Pro",
                    "data": {
                        "query": "image",
                        "best_match": {
                            "name": "Pixelmator Pro",
                            "path": "/Applications/Pixelmator Pro.app",
                            "match_score": 96,
                            "match_confidence": "high",
                        },
                    },
                }
            elif tool == "app.open":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Opened Pixelmator Pro",
                    "data": {"app_name": payload.get("app_name")},
                }
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {
                        "elements": [
                            {"role": "button", "name": "Export"},
                            {"role": "button", "name": "Share"},
                        ],
                        "count": 2,
                    },
                }
            elif tool == "desktop.click_ui_element":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {"target": payload.get("target")},
                }
            elif tool == "screen.capture":
                result = {
                    "ok": True,
                    "action": tool,
                    "data": {"path": "artifacts/export-dialog.png"},
                }
            else:
                raise AssertionError(f"unexpected tool: {tool}")
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool,
                    input_preview=payload,
                    result=result,
                )
            )
            messages_arg.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool}: {result}",
                }
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": allowed_tools},
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda tools: [{"name": tool} for tool in tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use runtime planner for desktop actions.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": "继续执行剩余桌面计划。"},
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

    loop.run(
        {"name": "Yachiyo"},
        "打开一个能编辑图片的应用，然后点击导出",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-generic-discovered-app-followup",
    )

    assert [request["tool"] for request in tool_runs[0]] == ["desktop.list_apps"]
    assert [request["tool"] for request in tool_runs[1]] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert [request["tool"] for request in tool_runs[2]] == [
        "desktop.click_ui_element",
        "screen.capture",
    ]
    assert tool_runs[2][0]["input"] == {
        "target": "导出",
        "role_filter": "",
        "click_count": 1,
        "limit": 80,
    }
    assert len(model_calls) == 1
    assert "Continue the pending Runtime Plan steps in order" in model_calls[0][-1]["content"]
    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "discover_apps-desktop-state",
        "open-selected-discovered-app",
        "observe-selected-discovered-app",
        "operate-selected-discovered-app-ui",
        "verify-selected-discovered-app-action",
    ]


def test_custom_api_agent_loop_executes_explicit_direct_tool_request_list() -> None:
    budget = FakeBudget()
    tool_runs: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    direct_tool_requests = [
        {
            "protocol": "json_fallback",
            "tool": "desktop.list_apps",
            "input": {"query": "Notes", "limit": 20},
            "source": "runtime_planner",
            "planning_reason": "explicit_full_plan",
        },
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Notes"},
            "source": "runtime_planner",
            "planning_reason": "explicit_full_plan",
        },
        {
            "protocol": "json_fallback",
            "tool": "desktop.active_window",
            "input": {},
            "source": "runtime_planner",
            "planning_reason": "explicit_full_plan",
        },
    ]

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
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found installed app: Notes",
                    "data": {"matches": [{"name": "Notes"}]},
                }
            elif tool == "app.open":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Opened Notes",
                    "data": {"app_name": payload["app_name"], "launch_verified": True},
                }
            elif tool == "desktop.active_window":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Frontmost app is Notes",
                    "data": {"app_name": "Notes"},
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
                    "desktop.list_apps",
                    "app.open",
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
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explicit direct tool request list should not call model")
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
        "ignored",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-explicit-direct-list",
        direct_tool_requests=direct_tool_requests,
    )

    assert result == "已打开 Notes。"
    assert tool_runs == [direct_tool_requests]
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["detail"] for event in planned_events] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert not [event for event in timeline if event["event"] == "agent.plan.selection"]
    completed = [event for event in timeline if event["event"] == "agent.desktop.intent_completed"]
    assert completed[-1]["detail"] == "desktop.active_window"
    assert completed[-1]["tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]


def test_custom_api_agent_loop_prefers_runtime_planner_desktop_before_legacy_rules(
    monkeypatch,
) -> None:
    def fail_legacy_daily_planner(*_args, **_kwargs):
        raise AssertionError("legacy desktop planner should not run before runtime planner")

    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        fail_legacy_daily_planner,
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_candidates",
        fail_legacy_daily_planner,
    )

    budget = FakeBudget()
    appended_events: list[tuple[str, str, dict[str, Any]]] = []
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
            if tool == "app.open":
                result = {
                    "ok": True,
                    "action": "app.open",
                    "data": {"app_name": payload["app_name"]},
                }
            elif tool == "desktop.click_ui_element":
                result = {
                    "ok": True,
                    "action": "desktop.click_ui_element",
                    "data": {
                        "target": payload["target"],
                        "x": 120,
                        "y": 240,
                        "click_count": 1,
                    },
                }
            else:
                raise AssertionError(f"unexpected tool: {tool}")
            timeline_arg.append(
                _timeline("agent.tool.call", tool, input_preview=payload, result=result)
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["app.open", "desktop.click_ui_element"]},
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
            AssertionError("runtime planner fallback should not call model")
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
            (run_id, event_type, payload)
        ),
    )

    result = loop.run(
        {"name": "Yachiyo"},
        "打开 PixelForge 并点击导出按钮",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-planner-fallback",
    )

    assert "PixelForge" in str(result)
    assert "导出" in str(result)
    planner_events = [
        event
        for event in timeline
        if event["event"] == "agent.intent.selected" or event["event"].startswith("agent.plan.")
    ]
    assert [event["event"] for event in planner_events[:3]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.plan.step",
    ]
    assert planner_events[0]["payload"]["intent"]["kind"] == "desktop_operation"
    planner_tools = [
        step["tool_name"]
        for step in planner_events[1]["payload"]["plan"]["tool_plan"]["steps"]
        if step.get("tool_name")
    ]
    assert planner_tools == ["app.open", "desktop.click_ui_element"]
    assert [event_type for _run_id, event_type, _payload in appended_events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    appended_plan_tools = [
        step["tool_name"]
        for step in appended_events[1][2]["plan"]["tool_plan"]["steps"]
        if step.get("tool_name")
    ]
    assert appended_plan_tools == ["app.open", "desktop.click_ui_element"]
    assert [request["tool"] for request in tool_runs[0]] == [
        "app.open",
        "desktop.click_ui_element",
    ]
    todo_events = [
        event for event in timeline if event["event"] == "agent.task.todo.updated"
    ]
    checkpoint_events = [
        event for event in timeline if event["event"] == "agent.task.checkpoint.updated"
    ]
    planned_todos = [event for event in todo_events if event["status"] == "pending"]
    completed_todos = [event for event in todo_events if event["status"] == "completed"]
    completed_checkpoints = [
        event for event in checkpoint_events if event["status"] == "completed"
    ]
    assert [event["step_id"] for event in planned_todos] == [
        "open-or-focus-app",
        "operate-foreground-ui",
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "open-or-focus-app",
        "operate-foreground-ui",
    ]
    assert [event["status"] for event in completed_checkpoints] == [
        "completed",
        "completed",
    ]
    assert completed_todos[0]["todo"]["status"] == "completed"
    assert completed_checkpoints[1]["checkpoint"]["status"] == "completed"
    assert any(
        event_type == "agent.task.todo.updated"
        and payload["step_id"] == "operate-foreground-ui"
        and payload["status"] == "completed"
        for _run_id, event_type, payload in appended_events
    )
    assert tool_runs[0][0]["source"] == "runtime_planner"
    assert tool_runs[0][1]["input"] == {
        "target": "导出",
        "role_filter": "button",
        "limit": 80,
        "click_count": 1,
    }
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["source"] for event in planned_events] == [
        "runtime_planner",
        "runtime_planner",
    ]


def test_custom_api_agent_loop_executes_runtime_planner_desktop_click_with_ui_verification(
    monkeypatch,
) -> None:
    def fail_legacy_daily_planner(*_args, **_kwargs):
        raise AssertionError("legacy desktop planner should not run before runtime planner")

    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        fail_legacy_daily_planner,
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_candidates",
        fail_legacy_daily_planner,
    )

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
            if tool == "desktop.inspect_app":
                result = {
                    "ok": True,
                    "action": "desktop.inspect_app",
                    "summary": "Inspected Notion",
                    "data": {
                        "app_name": payload["app_name"],
                        "elements": [{"role": "button", "label": "New Page"}],
                    },
                }
            elif tool == "app.focus_and_click_ui_element":
                result = {
                    "ok": True,
                    "action": "app.focus_and_click_ui_element",
                    "data": {
                        "app_name": payload["app_name"],
                        "target": payload["target"],
                        "x": 120,
                        "y": 240,
                        "click_count": 1,
                    },
                }
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "summary": "Read foreground UI after click",
                    "data": {"elements": [{"role": "heading", "label": "Untitled"}]},
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
                    "desktop.inspect_app",
                    "app.focus",
                    "desktop.click_ui_element",
                    "app.focus_and_click_ui_element",
                    "desktop.ui_elements",
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
            AssertionError("runtime planner desktop operation should not call model")
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
        "在 Notion 点击 New Page",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-planner-desktop-click-verify",
    )

    assert "Notion" in str(result)
    assert [request["tool"] for request in tool_runs[0]] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert tool_runs[0][-1]["source"] == "runtime_planner"
    assert tool_runs[0][-1]["planning_reason"] == "planner_desktop_operation"
    assert tool_runs[0][-1]["input"] == {"limit": 80}

    selection = _planner_selection_events(timeline)[0]
    assert selection["selected_tools"] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert selection["plan_tools"] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]

    completed = [event for event in timeline if event["event"] == "agent.desktop.intent_completed"]
    assert completed[-1]["tools"] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert [step["tool"] for step in completed[-1]["steps"]] == completed[-1]["tools"]


def test_custom_api_agent_loop_prefers_runtime_planner_media_before_legacy_rules(
    monkeypatch,
) -> None:
    def fail_legacy_daily_planner(*_args, **_kwargs):
        raise AssertionError("legacy desktop planner should not run before runtime planner")

    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        fail_legacy_daily_planner,
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_candidates",
        fail_legacy_daily_planner,
    )

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
            if tool != "media.apple_music_open_and_play":
                raise AssertionError(f"unexpected tool: {tool}")
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool,
                    input_preview=payload,
                    result={
                        "ok": True,
                        "action": "media.apple_music_open_and_play",
                        "data": {"playback_state_unverified": True},
                    },
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["media.apple_music_open_and_play"]},
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use media tools for playback intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime planner media fallback should not call model")
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
        "能否帮我播放 Apple Music?",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-planner-media-fallback",
    )

    assert "Apple Music" in str(result)
    assert [request["tool"] for request in tool_runs[0]] == ["media.apple_music_open_and_play"]
    assert tool_runs[0][0]["source"] == "runtime_planner"
    assert tool_runs[0][0]["planning_reason"] == "planner_fallback_media_playback"
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["detail"] for event in planned_events] == ["media.apple_music_open_and_play"]
    assert planned_events[0]["planning_reason"] == "planner_fallback_media_playback"


def test_custom_api_agent_loop_executes_runtime_planner_media_app_search_verify(
    monkeypatch,
) -> None:
    def fail_legacy_daily_planner(*_args, **_kwargs):
        raise AssertionError("legacy desktop planner should not run for planner media app search")

    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        fail_legacy_daily_planner,
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_candidates",
        fail_legacy_daily_planner,
    )

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
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool,
                    input_preview=payload,
                    result={"ok": True, "action": tool, "data": {}},
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "app.open_and_safe_shortcut",
                    "desktop.safe_type_text",
                    "desktop.search_submit",
                    "desktop.ui_elements",
                ]
            },
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use planner app-search fallback for media queries.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime planner media app search should not call model")
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
        "打开 Apple Music 搜索超时空辉夜姬并播放",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-planner-media-app-search",
    )

    assert str(result)
    assert [request["tool"] for request in tool_runs[0]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]
    assert {request["source"] for request in tool_runs[0]} == {"runtime_planner"}
    planned_events = [
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    ]
    assert [event["detail"] for event in planned_events] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]
    completed_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_completed"
    )
    assert completed_event["source"] == "runtime_planner"
    assert completed_event["tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]
    assert [step["tool"] for step in completed_event["steps"]] == completed_event["tools"]
    assert completed_event["planning_reason"] == "planner_fallback_media_playback"


def test_auto_discovered_media_playback_followup_searches_clicks_and_verifies() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "music", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found VLC",
                "data": {
                    "query": "music",
                    "best_match": {
                        "name": "VLC",
                        "path": "/Applications/VLC.app",
                        "match_score": 94,
                        "match_confidence": "high",
                        "match_reason": "category:music",
                    },
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_media_playback_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_media_playback",
                "app_query": "music",
                "app_name_source": "desktop.list_apps",
                "target_action": "safe_shortcut",
                "safe_shortcut_action": "find",
                "media_playback_query": "超时空辉夜姬",
                "result_selection": {
                    "target": "first result",
                    "role_filter": "",
                    "limit": 80,
                    "click_count": 1,
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert [request["tool"] for request in requests] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert requests[0]["input"] == {"app_name": "VLC", "action": "find"}
    assert requests[3]["input"] == {
        "app_name": "VLC",
        "target": "first result",
        "role_filter": "",
        "limit": 80,
        "click_count": 1,
    }
    assert requests[0]["input_resolution"] == {
        "tool": "app.open_and_safe_shortcut",
        "field": "app_name",
        "requested_app_name": "music",
        "resolved_app_name": "VLC",
        "source_tool": "desktop.list_apps",
        "app_resolution_score": "94",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "category:music",
        "resolved_app_path": "/Applications/VLC.app",
    }
    assert requests[3]["input_resolution"]["resolved_app_name"] == "VLC"


def test_auto_discovered_media_playback_followup_clicks_play_without_query() -> None:
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.list_apps",
            input_preview={"query": "music", "limit": 20},
            result={
                "ok": True,
                "action": "desktop.list_apps",
                "summary": "Found VLC",
                "data": {
                    "query": "music",
                    "best_match": {
                        "name": "VLC",
                        "path": "/Applications/VLC.app",
                        "match_score": 94,
                        "match_confidence": "high",
                        "match_reason": "category:music",
                    },
                },
            },
        )
    ]

    requests = custom_api_agent_module._auto_discovered_media_playback_followup_requests(
        {
            "followup_target": {
                "kind": "desktop_discovered_media_playback",
                "app_query": "music",
                "app_name_source": "desktop.list_apps",
                "target_action": "play_control",
                "result_selection": {
                    "target": "play 播放",
                    "role_filter": "button",
                    "limit": 80,
                    "click_count": 1,
                },
                "post_action_observation": {
                    "tool": "desktop.ui_elements",
                    "input": {},
                },
            }
        },
        [
            "app.open",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        timeline,
    )

    assert [request["tool"] for request in requests] == [
        "app.open",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert requests[0]["input"] == {"app_name": "VLC"}
    assert requests[1]["input"] == {
        "app_name": "VLC",
        "target": "play 播放",
        "role_filter": "button",
        "limit": 80,
        "click_count": 1,
    }
    assert requests[1]["input_resolution"]["resolved_app_name"] == "VLC"


def test_custom_api_agent_loop_continues_discovered_media_app_without_model(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.custom_api_agent.daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
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
            if tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Found installed app: VLC",
                    "data": {
                        "query": payload["query"],
                        "best_match": {
                            "name": "VLC",
                            "path": "/Applications/VLC.app",
                            "match_score": 94,
                            "match_confidence": "high",
                            "match_reason": "category:music",
                        },
                    },
                }
            elif tool == "app.open_and_safe_shortcut":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Opened VLC search",
                    "data": {
                        "app_name": payload["app_name"],
                        "shortcut_action": payload["action"],
                    },
                }
            elif tool == "desktop.safe_type_text":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Typed media query",
                    "data": {"character_count": len(payload["text"])},
                }
            elif tool == "desktop.search_submit":
                result = {"ok": True, "action": tool, "summary": "Submitted search", "data": {}}
            elif tool == "app.focus_and_click_ui_element":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Clicked first result",
                    "data": {
                        "app_name": payload["app_name"],
                        "target": payload["target"],
                    },
                }
            elif tool == "desktop.ui_elements":
                result = {
                    "ok": True,
                    "action": tool,
                    "summary": "Read foreground UI",
                    "data": {"app_name": "VLC", "elements": []},
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
                    "desktop.list_apps",
                    "app.open_and_safe_shortcut",
                    "desktop.safe_type_text",
                    "desktop.search_submit",
                    "app.focus_and_click_ui_element",
                    "desktop.ui_elements",
                ]
            },
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Use desktop tools for discoverable media playback.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("discovered media playback should not call model")
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
        "打开一个能播放音乐的应用，搜索超时空辉夜姬并播放",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-discovered-media-playback",
    )

    assert str(result)
    assert [request["tool"] for request in tool_runs[0]] == ["desktop.list_apps"]
    assert [request["tool"] for request in tool_runs[1]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert tool_runs[1][0]["input"] == {"app_name": "VLC", "action": "find"}
    assert tool_runs[1][3]["input"] == {
        "app_name": "VLC",
        "target": "first result",
        "role_filter": "",
        "limit": 80,
        "click_count": 1,
    }
    selection_events = _planner_selection_events(timeline)
    assert selection_events[0]["followup_target"]["kind"] == "desktop_discovered_media_playback"
    assert selection_events[0]["followup_target"]["media_playback_query"] == "超时空辉夜姬"
    completed_event = [
        event for event in timeline if event["event"] == "agent.desktop.intent_completed"
    ][-1]
    assert completed_event["source"] == "runtime_planner"
    assert completed_event["planning_reason"] == "planner_discovered_media_playback_followup"
    assert completed_event["tools"] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    completed_todos = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_todos] == [
        "discover-media-app",
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
        "play-media-search-result",
        "verify-media-search",
    ]
    completed_checkpoints = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["status"] == "completed"
    ]
    assert [event["step_id"] for event in completed_checkpoints] == [
        "discover-media-app",
        "focus-media-app-search",
        "type-media-search-query",
        "submit-media-search",
        "play-media-search-result",
        "verify-media-search",
    ]


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
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["media.apple_music_play"]
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert [event["event"] for event in non_planner_timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert non_planner_timeline[1]["detail"] == "media.apple_music_play"
    assert non_planner_timeline[1]["result"]["ok"] is True
    assert non_planner_timeline[-1]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"
    non_planner_run_events = _non_planner_run_events(run_events)
    assert [event["event_type"] for event in non_planner_run_events] == [
        "agent.desktop.intent_planned",
        "agent.tool.policy_decision",
        "tool.requested",
        "tool.started",
        "tool.completed",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert non_planner_run_events[0]["payload"]["tool"] == "media.apple_music_play"
    assert non_planner_run_events[0]["payload"]["source"] == "runtime_planner"
    assert non_planner_run_events[1]["payload"]["tool"] == "media.apple_music_play"
    assert non_planner_run_events[1]["payload"]["decision"] == "allow"
    assert non_planner_run_events[1]["payload"]["reason"] == "agent_tool_policy"
    assert non_planner_run_events[1]["payload"]["policy_overlay"] is False
    assert non_planner_run_events[-1]["payload"]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"


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
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["media.apple_music_play"]
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert [event["event"] for event in non_planner_timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert non_planner_timeline[-1]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"
    non_planner_run_events = _non_planner_run_events(run_events)
    assert [event["event_type"] for event in non_planner_run_events] == [
        "agent.desktop.intent_planned",
        "agent.tool.policy_decision",
        "tool.requested",
        "tool.started",
        "tool.completed",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert non_planner_run_events[1]["payload"]["tool"] == "media.apple_music_play"
    assert non_planner_run_events[1]["payload"]["decision"] == "allow"
    assert non_planner_run_events[1]["payload"]["reason"] == "agent_tool_policy"
    assert non_planner_run_events[1]["payload"]["policy_overlay"] is False
    assert non_planner_run_events[-1]["payload"]["summary"] == "已在 Apple Music 播放：超时空辉夜姬。"


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
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["media.apple_music_play"]
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert [event["event"] for event in non_planner_timeline] == [
        "agent.desktop.intent_planned",
        "agent.desktop.permission_preflight",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    preflight = non_planner_timeline[1]
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
    non_planner_run_events = _non_planner_run_events(run_events)
    assert [event["event_type"] for event in non_planner_run_events[:2]] == [
        "agent.desktop.intent_planned",
        "agent.desktop.permission_preflight",
    ]
    assert non_planner_run_events[1]["payload"]["diagnostic_route"] == "/yachiyo/readiness"
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
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["browser.open_url"]
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event["tool"] == "browser.open_url"
    assert planned_event["source"] == "daily_desktop_intent"
    assert planned_event["planning_reason"] == "clear_daily_desktop_intent"
    assert planned_event["input_preview"] == {"url": url}
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert non_planner_timeline[-1]["event"] == "agent.desktop.intent_completed"
    assert non_planner_timeline[-1]["summary"] == f"已打开网页：{url}。"
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
    data_analyze = RuntimeCustomApiAgentLoop._daily_desktop_summary(
        "data.analyze",
        {"path": "sales.csv", "artifact_path": "analysis-report.md"},
        {
            "ok": True,
            "path": "sales.csv",
            "rows": 3,
            "columns": ["region", "revenue"],
            "artifact": {"path": "analysis-report.md"},
        },
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
    assert data_analyze == "已分析「sales.csv」（3 行、2 列）。报告已写入 analysis-report.md。"
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
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        }
    ]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-main-chat"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert _planner_selection_events(timeline)[0]["selected_tools"] == [
        "media.apple_music_open_and_play"
    ]
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event["tool"] == "media.apple_music_open_and_play"
    assert planned_event["source"] == "runtime_planner"
    assert planned_event["planning_reason"] == "planner_fallback_media_playback"
    assert planned_event["input_preview"] == {}


def test_custom_api_agent_loop_preplans_runtime_browser_research_before_model(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
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
        request = tool_requests[0]
        result = {
            "ok": True,
            "action": "browser.open_url_and_extract_text",
            "data": {"url": request["input"]["url"], "text": "Example Domain"},
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                "browser.open_url_and_extract_text",
                input_preview=request["input"],
                result=result,
            )
        )
        messages_arg.append(
            {
                "role": "user",
                "content": f"Tool result for browser.open_url_and_extract_text: {result}",
            }
        )

    def call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        order.append("model")
        assert any(
            "Tool result for browser.open_url_and_extract_text" in str(message.get("content") or "")
            for message in model_messages
        )
        assert model_messages[-1]["role"] == "user"
        assert "Observed content snapshot:" in model_messages[-1]["content"]
        assert "Example Domain" in model_messages[-1]["content"]
        return {"role": "assistant", "content": "总结完成。"}

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["browser.open_url_and_extract_text"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use browser tools for web research.",
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
        "调研 https://example.com 并总结报告",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-browser-research",
    )

    assert str(result) == "总结完成。"
    assert order == ["tool", "model"]
    followup_event = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup_event["content_snapshot"] == {
        "source_tool": "browser.open_url_and_extract_text",
        "ok": True,
        "url": "https://example.com",
        "text_length": 14,
        "truncated": False,
        "text": "Example Domain",
    }
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "continue_to_model": True,
        }
    ]
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event == {
        "event": "agent.desktop.intent_planned",
        "detail": "browser.open_url_and_extract_text",
        "tool": "browser.open_url_and_extract_text",
        "status": "planned",
        "source": "runtime_planner",
        "planning_reason": "planner_fallback_web_research",
        "input_preview": {"url": "https://example.com"},
        "continue_to_model": True,
    }


def test_custom_api_agent_loop_writes_web_research_report_to_target_app(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    tool_runs: list[dict[str, Any]] = []
    model_calls: list[list[dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    generated = "Example Domain 调研报告\n- 这是一个示例域名。"

    def run_tool_requests(
        tool_requests,
        allowed_tools,
        broker,
        messages_arg,
        timeline_arg,
        artifacts,
        **kwargs,
    ):
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
        for request in tool_requests:
            tool_name = str(request.get("tool") or "")
            input_preview = request.get("input") if isinstance(request.get("input"), dict) else {}
            if tool_name == "browser.open_url_and_extract_text":
                result = {
                    "ok": True,
                    "action": "browser.open_url_and_extract_text",
                    "data": {
                        "url": input_preview.get("url"),
                        "text": "Example Domain\nThis domain is for use in examples.",
                    },
                }
            else:
                result = {"ok": True, **input_preview}
            timeline_arg.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    input_preview=input_preview,
                    result=result,
                )
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "browser.open_url_and_extract_text",
                    "app.focus_and_safe_shortcut",
                    "app.focus_and_safe_type_text",
                    "desktop.ui_elements",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner follow-up context.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda _base_url, _model, _api_key, model_messages, **_kwargs: model_calls.append(
            list(model_messages)
        )
        or {"role": "assistant", "content": generated},
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
        "调研 https://example.com 的信息并把报告写进 Notion 新页面",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-web-research-app-write",
    )

    assert "Notion" in str(result)
    assert "输入文字" in str(result)
    assert [run["tool_requests"][0]["tool"] for run in tool_runs] == [
        "browser.open_url_and_extract_text",
        "app.focus_and_safe_shortcut",
    ]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "browser.open_url_and_extract_text",
            "input": {"url": "https://example.com"},
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_web_research",
            "continue_to_model": True,
        }
    ]
    assert [request["tool"] for request in tool_runs[1]["tool_requests"]] == [
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text",
        "desktop.ui_elements",
    ]
    assert tool_runs[1]["tool_requests"][0]["input"] == {
        "app_name": "Notion",
        "action": "new_document",
    }
    assert tool_runs[1]["tool_requests"][1]["input"] == {
        "app_name": "Notion",
        "text": generated,
    }
    followup = next(
        event for event in timeline if event["event"] == "agent.model.followup_context"
    )
    assert followup["followup_target"]["kind"] == "app_write"
    assert followup["followup_target"]["app_name"] == "Notion"
    assert followup["followup_target"]["container_action"] == "new_document"
    assert followup["content_snapshot"]["source_tool"] == "browser.open_url_and_extract_text"
    assert len(model_calls) == 1
    assert "Example Domain" in model_calls[0][-1]["content"]
    assert "written into Notion" in model_calls[0][-1]["content"]


def test_custom_api_agent_loop_preserves_runtime_planner_source_on_direct_completion(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
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
        request = tool_requests[0]
        result = {
            "ok": True,
            "action": "browser.open_url",
            "data": {"url": request["input"]["url"]},
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                "browser.open_url",
                input_preview=request["input"],
                result=result,
            )
        )

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
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use browser tools for web requests.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct runtime planner browser open should not call model")
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
        "打开 https://example.com",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-browser-open",
    )

    assert str(result) == "已打开网页：https://example.com。"
    assert timeline[-1] == {
        "event": "agent.desktop.intent_completed",
        "detail": "browser.open_url",
        "tool": "browser.open_url",
        "source": "runtime_planner",
        "input_preview": {"url": "https://example.com"},
        "result": {
            "ok": True,
            "action": "browser.open_url",
            "data": {"url": "https://example.com"},
        },
        "summary": "已打开网页：https://example.com。",
        "planning_reason": "planner_fallback_web_research",
    }


def test_custom_api_agent_loop_preplans_daily_reminder_without_model() -> None:
    budget = FakeBudget()
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
        request = tool_requests[0]
        result = {
            "ok": True,
            "action": "reminders.create",
            "data": {"title": request["input"]["title"]},
        }
        timeline_arg.append(
            _timeline(
                "agent.tool.call",
                "reminders.create",
                input_preview=request["input"],
                result=result,
            )
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["reminders.create"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for explicit reminders.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct runtime planner reminder should not call model")
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
        "创建提醒事项：买牛奶",
        broker={"broker": True},
        timeline=timeline,
        artifacts=[],
        run_id="run-reminder",
    )

    assert str(result) == "已创建提醒事项：买牛奶。"
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event == {
        "event": "agent.desktop.intent_planned",
        "detail": "reminders.create",
        "tool": "reminders.create",
        "status": "planned",
        "source": "runtime_planner",
        "planning_reason": "planner_fallback_schedule",
        "input_preview": {"title": "买牛奶"},
    }
    assert timeline[-1]["event"] == "agent.desktop.intent_completed"
    assert timeline[-1]["source"] == "runtime_planner"


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
    messages = [{"role": "user", "content": "按 Command+Option+P"}]

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
                    '"data": {"key": "p", "modifiers": ["command", "option"]}}'
                ),
            }
        )

    def call_model(_base_url, _model, _api_key, model_messages, **_kwargs):
        order.append("model")
        assert "Tool result for desktop.hotkey" in model_messages[-1]["content"]
        return {"role": "assistant", "content": "已发送 Command+Option+P。"}

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

    assert str(result) == "已发送 Command+Option+P。"
    assert order == ["tool", "model"]
    assert tool_runs[0]["tool_requests"] == [
        {
            "protocol": "json_fallback",
            "tool": "desktop.hotkey",
            "input": {"key": "p", "modifiers": ["command", "option"]},
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_hotkey",
        }
    ]
    assert tool_runs[0]["allowed_tools"] == ["desktop.hotkey"]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-hotkey"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["desktop.hotkey"]
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event == {
        "event": "agent.desktop.intent_planned",
        "detail": "desktop.hotkey",
        "tool": "desktop.hotkey",
        "status": "planned",
        "source": "runtime_planner",
        "planning_reason": "planner_desktop_hotkey",
        "input_preview": {"key": "p", "modifiers": ["command", "option"]},
    }


def test_main_chat_daily_hotkey_intent_returns_deterministic_result_without_model() -> None:
    budget = FakeBudget()
    order: list[str] = []
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "按 Command+Option+P"}]

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
            "data": {"key": "p", "modifiers": ["command", "option"]},
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

    assert str(result) == "已发送快捷键：Command+Option+P。"
    assert order == ["tool"]
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["desktop.hotkey"]
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert [event["event"] for event in non_planner_timeline] == [
        "agent.desktop.intent_planned",
        "agent.tool.call",
        "agent.desktop.intent_completed",
    ]
    assert non_planner_timeline[-1]["summary"] == "已发送快捷键：Command+Option+P。"
    assert appended_events[-1] == {
        "run_id": "run-hotkey-direct",
        "event_type": "agent.desktop.intent_completed",
        "payload": {
            "tool": "desktop.hotkey",
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_hotkey",
            "input_preview": {"key": "p", "modifiers": ["command", "option"]},
            "result": {
                "ok": True,
                "action": "desktop.hotkey",
                "data": {"key": "p", "modifiers": ["command", "option"]},
            },
            "summary": "已发送快捷键：Command+Option+P。",
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
            "input_preview": {"key": "p", "modifiers": ["command", "option"]},
        },
        {
            "event": "agent.desktop.intent_approval_required",
            "detail": "desktop.hotkey",
            "tool": "desktop.hotkey",
            "status": "approval_required",
            "source": "daily_desktop_intent",
            "reason": "tool_policy_requires_approval",
            "input_preview": {"key": "p", "modifiers": ["command", "option"]},
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.hotkey",
            "input_preview": {"key": "p", "modifiers": ["command", "option"]},
            "result": {
                "ok": True,
                "action": "desktop.hotkey",
                "data": {"key": "p", "modifiers": ["command", "option"]},
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
            {"role": "user", "content": "按 Command+Option+P"},
            {"role": "user", "content": "Tool result for desktop.hotkey: ok"},
        ],
        start_iteration=0,
        run_id="run-hotkey-resume",
        budget=budget,
    )

    assert str(result) == "已发送快捷键：Command+Option+P。"
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
            "input_preview": {"app_name": "Notes", "key": "p", "modifiers": ["command", "option"]},
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
            "input_preview": {"app_name": "Notes", "key": "p", "modifiers": ["command", "option"]},
        },
        {
            "event": "agent.tool.call",
            "detail": "app.open_and_hotkey",
            "input_preview": {"app_name": "Notes", "key": "p", "modifiers": ["command", "option"]},
            "result": {
                "ok": True,
                "action": "app.open_and_hotkey",
                "data": {"app_name": "Notes", "key": "p", "modifiers": ["command", "option"]},
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
            {"role": "user", "content": "打开 Notes，然后按 Command+Option+P，再复制"},
            {"role": "user", "content": "Tool result for app.open_and_hotkey: ok"},
        ],
        start_iteration=0,
        run_id="run-sequence-resume",
        budget=budget,
    )

    assert str(result) == "已打开 Notes 并发送快捷键：Command+Option+P。 已复制选中内容。"
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
    messages = [{"role": "user", "content": "按 Command+Option+P"}]

    def run_tool_requests(*_args, **_kwargs):
        raise AgentApprovalRequired(
            {
                "approval_id": "approval-hotkey",
                "tool": "desktop.hotkey",
                "input_preview": {"key": "p", "modifiers": ["command", "option"]},
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

    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["desktop.hotkey"]
    non_planner_timeline = _non_planner_timeline_events(timeline)
    assert [event["event"] for event in non_planner_timeline] == [
        "agent.desktop.intent_planned",
        "agent.desktop.intent_approval_required",
    ]
    assert non_planner_timeline[-1] == {
        "event": "agent.desktop.intent_approval_required",
        "detail": "desktop.hotkey",
        "tool": "desktop.hotkey",
        "status": "approval_required",
        "source": "daily_desktop_intent",
        "reason": "tool_policy_requires_approval",
        "input_preview": {"key": "p", "modifiers": ["command", "option"]},
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
            "input_preview": {"key": "p", "modifiers": ["command", "option"]},
            "approval_id": "approval-hotkey",
            "risk_level": "medium",
            "policy_reason": "前台快捷键需要确认。",
        },
    }


def test_custom_api_agent_loop_preserves_runtime_planner_source_on_approval_required(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_tool_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        custom_api_agent_module,
        "daily_desktop_intent_candidates",
        lambda *_args, **_kwargs: [],
    )
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    appended_events: list[dict[str, Any]] = []

    def run_tool_requests(*_args, **_kwargs):
        raise AgentApprovalRequired(
            {
                "approval_id": "approval-export",
                "tool": "app.open_and_click_ui_element",
                "input_preview": {
                    "app_name": "PixelForge",
                    "target": "导出",
                    "role_filter": "button",
                    "limit": 80,
                    "click_count": 1,
                },
                "risk_level": "medium",
                "policy_reason": "点击前台控件需要确认。",
            }
        )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.local",
            "model": "m",
            "api_key": "k",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["app.open_and_click_ui_element"]}
        },
        run_budget=lambda _run_id, _timeline_value: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda allowed_tools: [{"name": tool} for tool in allowed_tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="Use runtime planner for desktop intents.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("approval-required runtime planner intent should not call model")
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
            {"name": "Yachiyo"},
            "打开 PixelForge 并点击导出按钮",
            broker={"broker": True},
            timeline=timeline,
            artifacts=[],
            run_id="run-runtime-planner-approval",
        )
    except AgentApprovalRequired as exc:
        assert exc.pending_approval["approval_id"] == "approval-export"
    else:
        raise AssertionError("expected AgentApprovalRequired")

    assert timeline[-1]["event"] == "agent.desktop.intent_approval_required"
    assert timeline[-1]["source"] == "runtime_planner"
    assert timeline[-1]["planning_reason"] == "planner_fallback_desktop_operation"
    assert appended_events[-1]["event_type"] == "agent.desktop.intent_approval_required"
    assert appended_events[-1]["payload"]["source"] == "runtime_planner"
    assert appended_events[-1]["payload"]["planning_reason"] == (
        "planner_fallback_desktop_operation"
    )


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
            "source": "runtime_planner",
            "planning_reason": "planner_fallback_media_playback",
        }
    ]
    assert tool_runs[0]["kwargs"]["run_id"] == "run-music"
    assert tool_runs[0]["kwargs"]["next_iteration"] == 0
    assert _planner_selection_events(timeline)[0]["selected_tools"] == ["media.apple_music_play"]
    planned_event = next(
        event for event in timeline if event["event"] == "agent.desktop.intent_planned"
    )
    assert planned_event["tool"] == "media.apple_music_play"
    assert planned_event["source"] == "runtime_planner"
    assert planned_event["planning_reason"] == "planner_fallback_media_playback"
    assert planned_event["input_preview"] == {"query": "超时空辉夜姬"}
    non_planner_appended = _non_planner_run_events(appended_events)
    assert [event["event_type"] for event in non_planner_appended] == [
        "agent.desktop.intent_planned",
        "agent.tool.policy_decision",
    ]
    assert non_planner_appended[0]["payload"]["tool"] == "media.apple_music_play"
    assert non_planner_appended[0]["payload"]["source"] == "runtime_planner"
    assert non_planner_appended[0]["payload"]["planning_reason"] == "planner_fallback_media_playback"
    policy_payload = non_planner_appended[1]["payload"]
    assert policy_payload["tool"] == "media.apple_music_play"
    assert policy_payload["decision"] == "allow"
    assert policy_payload["reason"] == "agent_tool_policy"
    assert policy_payload["policy_overlay"] is False
    assert policy_payload["input_preview"] == {"query": "超时空辉夜姬"}


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
