"""Custom API Agent model/tool loop."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.config import MAIN_CHAT_AGENT_ID
from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
)
from apps.shell.agent.tools.policy import DAILY_BROWSER_TOOL_NAMES, DAILY_DESKTOP_TOOL_NAMES

_DIRECT_DAILY_DESKTOP_TOOLS = {
    "app.open",
    "app.focus",
    "media.apple_music_play",
    "screen.capture",
    "desktop.active_window",
    "browser.open_url",
    "browser.current_page",
    "browser.extract_text",
    "browser.screenshot",
}


class RuntimeCustomApiAgentLoop:
    """Runs the model/tool loop for native-profile and custom API Agents."""

    def __init__(
        self,
        *,
        agent_model_config_private: Callable[[dict[str, Any]], dict[str, Any]],
        compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        check_context_budget: Callable[[Any, list[dict[str, Any]]], None],
        tool_schemas: Callable[[list[str]], list[dict[str, Any]]],
        normalize_tool_iteration: Callable[[Any], int],
        max_tool_iterations: int,
        operating_doctrine: str,
        memory_tool_names: set[str] | frozenset[str] | tuple[str, ...],
        future_task_tool_names: set[str] | frozenset[str] | tuple[str, ...],
        call_model: Callable[..., Any],
        coalesce_model_message: Callable[[Any], dict[str, Any]],
        message_visible_content_text: Callable[[dict[str, Any]], str],
        model_message_metadata: Callable[[dict[str, Any]], dict[str, Any]],
        tool_requests_from_message: Callable[[dict[str, Any], str], list[dict[str, Any]]],
        timeline_factory: Callable[..., dict[str, Any]],
        limit_model_output: Callable[[Any], tuple[str, bool]],
        model_output_text_factory: Callable[..., str],
        tool_loop_projection: Any,
        run_tool_requests: Callable[..., None],
        error_type: type[Exception],
        append_run_event: Callable[[str, str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._agent_model_config_private = agent_model_config_private
        self._compile_agent_runtime = compile_agent_runtime
        self._run_budget = run_budget
        self._check_context_budget = check_context_budget
        self._tool_schemas = tool_schemas
        self._normalize_tool_iteration = normalize_tool_iteration
        self._max_tool_iterations = max_tool_iterations
        self._operating_doctrine = operating_doctrine
        self._memory_tool_names = set(memory_tool_names)
        self._future_task_tool_names = set(future_task_tool_names)
        self._call_model = call_model
        self._coalesce_model_message = coalesce_model_message
        self._message_visible_content_text = message_visible_content_text
        self._model_message_metadata = model_message_metadata
        self._tool_requests_from_message = tool_requests_from_message
        self._timeline = timeline_factory
        self._limit_model_output = limit_model_output
        self._model_output_text_factory = model_output_text_factory
        self._tool_loop_projection = tool_loop_projection
        self._run_tool_requests = run_tool_requests
        self._error_type = error_type
        self._append_run_event = append_run_event

    def run(
        self,
        agent: dict[str, Any],
        context: str,
        broker: Any,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        messages: list[dict[str, Any]] | None = None,
        start_iteration: int = 0,
        run_id: str = "",
        budget: Any | None = None,
    ) -> str:
        model_config = self._agent_model_config_private(agent)
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        model = str(model_config.get("model") or "").strip()
        api_key = str(model_config.get("api_key") or "").strip()
        if not base_url or not model or not api_key:
            raise self._error_type("Agent 模型 Profile 缺少 base_url、model 或 API Key")
        runtime = self._compile_agent_runtime(agent)
        allowed_tools = runtime["tool_policy"].get("allowed_tools") or []
        default_messages = messages is None
        if messages is None:
            messages = self._initial_messages(context, allowed_tools)
        else:
            self._ensure_runtime_system_message(messages, allowed_tools)
        budget = budget or self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        tools = self._tool_schemas(allowed_tools)
        start_iteration = self._normalize_tool_iteration(start_iteration)
        if default_messages or start_iteration == 0:
            planning_context = context if default_messages else self._latest_user_intent_text(messages)
            planned_tool_request = daily_desktop_intent_tool_request(planning_context, allowed_tools)
            if planned_tool_request:
                planned_tool = str(planned_tool_request.get("tool") or "")
                planned_input = planned_tool_request.get("input") or {}
                planned_payload = {
                    "tool": planned_tool,
                    "status": "planned",
                    "source": "daily_desktop_intent",
                    "planning_reason": "clear_daily_desktop_intent",
                    "input_preview": planned_input,
                }
                timeline.append(
                    self._timeline(
                        "agent.desktop.intent_planned",
                        planned_tool,
                        **planned_payload,
                    )
                )
                if run_id and self._append_run_event is not None:
                    self._append_run_event(
                        run_id,
                        "agent.desktop.intent_planned",
                        planned_payload,
                    )
                self._run_tool_requests(
                    [planned_tool_request],
                    allowed_tools,
                    broker,
                    messages,
                    timeline,
                    artifacts,
                    next_iteration=start_iteration,
                    run_id=run_id,
                    budget=budget,
                )
                direct_result = self._direct_daily_desktop_result(
                    agent,
                    planned_tool,
                    planned_input,
                    timeline,
                    run_id=run_id,
                )
                if direct_result:
                    return direct_result
            else:
                candidates = daily_desktop_intent_candidates(planning_context)
                if candidates:
                    self._record_unavailable_desktop_intent(
                        candidates[0],
                        allowed_tools=allowed_tools,
                        messages=messages,
                        timeline=timeline,
                        run_id=run_id,
                    )
        for iteration in range(start_iteration, self._max_tool_iterations):
            self._check_context_budget(budget, messages)
            budget.claim_model_call()
            message = self._coalesce_model_message(
                self._call_model(base_url, model, api_key, messages, tools=tools, stream=True)
            )
            content = self._message_visible_content_text(message)
            tool_requests = self._tool_requests_from_message(message, content)
            detail = content[:500] if content else ", ".join(
                request["tool"] for request in tool_requests
            )[:500]
            timeline.append(self._timeline("agent.model.response", detail))
            if not tool_requests:
                if not content.strip():
                    raise self._error_type("Native Agent 模型返回了空回复")
                result_text, truncated = self._limit_model_output(content)
                return self._model_output_text_factory(
                    result_text,
                    metadata=self._model_message_metadata(message),
                    truncated=truncated,
                )

            if tool_requests[0].get("protocol") == "tool_calls":
                messages.append(self._tool_loop_projection.assistant_message_for_history(message))
            else:
                messages.append({"role": "assistant", "content": content})
            self._run_tool_requests(
                tool_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                next_iteration=iteration + 1,
                run_id=run_id,
                budget=budget,
            )
        artifact_completion = self._tool_loop_projection.artifact_completion(timeline, artifacts)
        if artifact_completion:
            timeline.append(
                self._timeline(
                    "agent.tool.loop_limit_completed",
                    "artifact.write completed before model final output",
                    artifact_paths=[
                        str(artifact.get("path") or "")
                        for artifact in artifacts
                        if artifact.get("kind") != "context" and str(artifact.get("path") or "").strip()
                    ],
                    loop_limit_detail=self._tool_loop_projection.loop_limit_detail(timeline),
                )
            )
            return artifact_completion
        raise self._error_type(
            "custom_api Agent 工具循环超过上限；"
            f"{self._tool_loop_projection.loop_limit_detail(timeline)}"
        )

    def _record_unavailable_desktop_intent(
        self,
        candidate: dict[str, Any],
        *,
        allowed_tools: list[str],
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        tool_name = str(candidate.get("tool") or "").strip()
        payload = candidate.get("input") if isinstance(candidate.get("input"), dict) else {}
        event_payload = {
            "tool": tool_name,
            "status": "unavailable",
            "source": "daily_desktop_intent",
            "reason": "tool_not_allowed",
            "input_preview": payload,
            "allowed_tools": [str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()],
        }
        timeline.append(
            self._timeline(
                "agent.desktop.intent_unavailable",
                tool_name,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.desktop.intent_unavailable", event_payload)
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Desktop intent for {tool_name} was not executed because this Agent "
                    f"does not allow {tool_name}. Allowed tools: "
                    f"{', '.join(event_payload['allowed_tools']) or 'none'}."
                ),
            }
        )

    def _direct_daily_desktop_result(
        self,
        agent: dict[str, Any],
        planned_tool: str,
        planned_input: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> str:
        if str(agent.get("agent_id") or "").strip() != MAIN_CHAT_AGENT_ID:
            return ""
        if planned_tool not in _DIRECT_DAILY_DESKTOP_TOOLS:
            return ""
        tool_event = self._latest_tool_call_event(timeline, planned_tool)
        if not tool_event:
            return ""
        result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
        if result.get("approval_required"):
            return ""
        summary = self._daily_desktop_summary(planned_tool, planned_input, result)
        if not summary:
            return ""
        event_payload = {
            "tool": planned_tool,
            "source": "daily_desktop_intent",
            "result": result,
            "summary": summary,
        }
        timeline.append(
            self._timeline(
                "agent.desktop.intent_completed",
                planned_tool,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.desktop.intent_completed", event_payload)
        return summary

    @staticmethod
    def _latest_tool_call_event(
        timeline: list[dict[str, Any]],
        planned_tool: str,
    ) -> dict[str, Any] | None:
        for event in reversed(timeline):
            if event.get("event") != "agent.tool.call":
                continue
            if str(event.get("detail") or "") == planned_tool:
                return event
        return None

    @staticmethod
    def _daily_desktop_summary(
        tool_name: str,
        planned_input: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        result_summary = str(result.get("summary") or "").strip()
        if result.get("ok"):
            if tool_name == "app.open":
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已打开 {app_name}。" if app_name else (result_summary or "已打开应用。")
            if tool_name == "app.focus":
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已切换到 {app_name}。" if app_name else (result_summary or "已切换到应用。")
            if tool_name == "media.apple_music_play":
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                track = str(data.get("track") or "").strip()
                artist = str(data.get("artist") or "").strip()
                query = _payload_text(result, planned_input, "query")
                if track:
                    return f"已在 Apple Music 播放：{track}{f' - {artist}' if artist else ''}。"
                return f"已尝试在 Apple Music 播放：{query}。" if query else (result_summary or "已尝试播放。")
            if tool_name == "screen.capture":
                return result_summary or "已截取当前屏幕。"
            if tool_name == "desktop.active_window":
                return result_summary or _active_window_summary(result)
            if tool_name == "browser.open_url":
                url = _payload_text(result, planned_input, "url")
                return f"已打开网页：{url}。" if url else (result_summary or "已打开网页。")
            if tool_name == "browser.current_page":
                return result_summary or _browser_page_summary(result)
            if tool_name == "browser.extract_text":
                return result_summary or _browser_text_summary(result)
            if tool_name == "browser.screenshot":
                return result_summary or "已截取当前网页。"
            return result_summary or "已执行桌面操作。"

        fallback = result.get("fallback_result") if isinstance(result.get("fallback_result"), dict) else {}
        if tool_name == "media.apple_music_play" and fallback.get("ok"):
            query = _payload_text(result, planned_input, "query")
            return (
                f"没能直接播放 {query}，但已打开 Apple Music。"
                if query
                else "没能直接播放，但已打开 Apple Music。"
            )
        error = str(result.get("error") or result_summary or "工具返回失败").strip()
        permission_targets = result.get("permission_targets")
        if result.get("permission_error") or permission_targets:
            targets = ", ".join(str(item) for item in permission_targets or [] if str(item))
            suffix = f" 缺少权限：{targets}。" if targets else ""
            return f"桌面操作未完成：{error}。{suffix}".strip()
        return f"桌面操作未完成：{error}。"

    def _latest_user_intent_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if str(message.get("role") or "") != "user":
                continue
            content = self._message_visible_content_text(message).strip()
            if content.startswith("Tool result for ") or content.startswith("Desktop intent for "):
                continue
            if content:
                return content
        return ""

    def _ensure_runtime_system_message(
        self,
        messages: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> None:
        runtime_message = self._system_message(allowed_tools)
        if messages and str(messages[0].get("role") or "") == "system":
            content = str(messages[0].get("content") or "")
            if "Oha-Yachiyo Agent Runtime" in content:
                return
            messages[0] = {
                **messages[0],
                "content": f"{runtime_message['content']}\n\n{content}",
            }
            return
        messages.insert(0, runtime_message)

    def _initial_messages(self, context: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        return [
            self._system_message(allowed_tools),
            {"role": "user", "content": context},
        ]

    def _system_message(self, allowed_tools: list[str]) -> dict[str, Any]:
        allowed_tool_text = ", ".join(allowed_tools) or "none"
        memory_tool_guidance = (
            "Use memory.add, memory.replace, and memory.remove only for stable user preferences, durable facts, "
            "task commitments, reusable summaries, or explicit forget/correction requests; never store secrets. "
            if any(tool in allowed_tools for tool in self._memory_tool_names)
            else ""
        )
        future_task_guidance = (
            "Use future_task.schedule/list/cancel for explicit reminders, follow-up commitments, standing orders, "
            "or recurring summaries; do not schedule hidden future work without user intent. "
            if any(tool in allowed_tools for tool in self._future_task_tool_names)
            else ""
        )
        desktop_tool_guidance = (
            "For desktop requests, prefer structured desktop tools such as screen.capture, "
            "desktop.active_window, app.open/app.focus, media.apple_music_play, "
            "desktop.click, desktop.hotkey, and desktop.type_text when they are allowed. "
            "For explicit daily commands, map 'play <song>' or '播放<歌曲>' to "
            "media.apple_music_play, screen capture requests to screen.capture, and current "
            "or foreground window questions to desktop.active_window before answering. "
            "For browser or web-page requests, prefer structured browser tools such as "
            "browser.open_url, browser.current_page, browser.click, browser.type_text, "
            "browser.extract_text, and browser.screenshot when they are allowed. "
            "When browser.click has no Chrome CDP, use screen observation and explicit "
            "fallback_x/fallback_y coordinates instead of guessing selector positions. "
            "Do not replace these structured desktop or browser actions with terminal.run. "
            "If a desktop or browser permission is missing, explain the exact missing permission "
            "and continue with the safest fallback. "
            if any(tool in allowed_tools for tool in DAILY_DESKTOP_TOOL_NAMES)
            or any(tool in allowed_tools for tool in DAILY_BROWSER_TOOL_NAMES)
            else ""
        )
        system_prompt = (
            "You are running inside Oha-Yachiyo Agent Runtime. "
            "Follow the Agent functional instructions, persona prompt, user goal, and exact output requests. "
            "If those instructions require an exact phrase or format, return exactly that final output. "
            "Return concise final output unless the Agent instructions require otherwise. "
            f"{self._operating_doctrine}\n"
            "Prefer native tool_calls when available. "
            "If the model endpoint does not support tool_calls and a controlled tool is needed, respond as JSON "
            "{\"action\":\"tool\",\"tool\":\"workspace.list\",\"input\":{}}. "
            "Do not request tools that are not listed as allowed. "
            "If no tools are allowed, do not request tools. "
            "Do not request a tool solely because of the output contract; use tools only when the user goal "
            "or an explicit deliverable requires them. "
            f"{memory_tool_guidance}"
            f"{future_task_guidance}"
            f"{desktop_tool_guidance}"
            "If the user asks not to create, save, write, or modify files, provide the content inline and do "
            "not request file-writing tools. If the user asks not to run or execute commands, do not request "
            "command-execution tools. "
            "Workspace tools only accept paths relative to the configured Default Workdir. Never pass absolute "
            "paths to workspace tools. If a required target is outside that workspace and terminal.run is "
            "allowed, use terminal.run instead. A failed workspace tool call is recoverable: follow its hint "
            "or switch tools instead of stopping or retrying the same invalid path. "
            f"Request at most one high-risk tool per turn.\n\nAllowed tools: {allowed_tool_text}"
        )
        return {"role": "system", "content": system_prompt}


def _payload_text(result: dict[str, Any], planned_input: dict[str, Any], key: str) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return str(data.get(key) or planned_input.get(key) or "").strip()


def _active_window_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(data.get("app_name") or "").strip()
    title = str(data.get("title") or "").strip()
    if app_name and title:
        return f"当前前台窗口是 {app_name}：{title}。"
    if app_name:
        return f"当前前台应用是 {app_name}。"
    return "已读取当前前台窗口。"


def _browser_page_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    title = str(data.get("title") or "").strip()
    url = str(data.get("url") or "").strip()
    if title and url:
        return f"当前网页是 {title}：{url}。"
    if url:
        return f"当前网页是 {url}。"
    return "已读取当前网页信息。"


def _browser_text_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    text = str(data.get("text") or result.get("text") or "").strip()
    if not text:
        return "已读取当前网页文本。"
    if len(text) > 1200:
        text = f"{text[:1200]}..."
    return text
