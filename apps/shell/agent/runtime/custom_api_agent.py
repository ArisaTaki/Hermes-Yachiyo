"""Custom API Agent model/tool loop."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.tools.policy import DAILY_BROWSER_TOOL_NAMES, DAILY_DESKTOP_TOOL_NAMES

_DIRECT_DAILY_DESKTOP_TOOLS = {
    "app.open",
    "app.focus",
    "app.quit",
    "media.apple_music_play",
    "media.apple_music_control",
    "system.volume",
    "clipboard.write",
    "screen.capture",
    "desktop.permissions",
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.windows",
    "app.status",
    "desktop.reveal_path",
    "desktop.open_path",
    "browser.open_url",
    "browser.current_page",
    "browser.extract_text",
    "browser.screenshot",
    "desktop.hide_app",
    "desktop.minimize_window",
    "desktop.close_window",
    "desktop.hotkey",
    "desktop.type_text",
    "desktop.click",
}

_DAILY_DESKTOP_TOOL_LABELS = {
    "screen.capture": "截取屏幕",
    "desktop.permissions": "检查桌面权限",
    "desktop.active_window": "读取当前窗口",
    "desktop.running_apps": "读取运行中应用",
    "desktop.windows": "读取窗口列表",
    "app.status": "检查应用状态",
    "desktop.reveal_path": "在 Finder 中显示",
    "desktop.open_path": "打开本地路径",
    "app.open": "打开应用",
    "app.focus": "聚焦应用",
    "app.quit": "退出应用",
    "media.apple_music_play": "播放 Apple Music",
    "media.apple_music_control": "控制 Apple Music",
    "system.volume": "控制系统音量",
    "clipboard.write": "写入剪贴板",
    "desktop.hide_app": "隐藏当前应用",
    "desktop.minimize_window": "最小化当前窗口",
    "desktop.close_window": "关闭当前窗口",
    "desktop.hotkey": "发送快捷键",
    "desktop.type_text": "输入前台文字",
    "desktop.click": "点击前台界面",
    "browser.open_url": "打开网页",
    "browser.current_page": "读取当前网页",
    "browser.extract_text": "提取网页文本",
    "browser.screenshot": "截取网页",
    "browser.click": "点击网页元素",
    "browser.type_text": "填写网页输入",
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
        runtime = self._compile_agent_runtime(agent)
        allowed_tools = runtime["tool_policy"].get("allowed_tools") or []
        default_messages = messages is None
        if messages is None:
            messages = self._initial_messages(context, allowed_tools)
        else:
            self._ensure_runtime_system_message(messages, allowed_tools)
        budget = budget or self._run_budget(run_id, timeline)
        self._check_context_budget(budget, messages)
        start_iteration = self._normalize_tool_iteration(start_iteration)
        if not default_messages and start_iteration == 0:
            resumed_result = self._direct_existing_daily_desktop_result(
                agent,
                timeline,
                run_id=run_id,
            )
            if resumed_result:
                return resumed_result
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
                try:
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
                except AgentApprovalRequired as exc:
                    self._record_desktop_intent_approval_required(
                        planned_tool,
                        planned_input,
                        pending_approval=exc.pending_approval,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    raise
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
                    unavailable_summary = self._record_unavailable_desktop_intent(
                        candidates[0],
                        allowed_tools=allowed_tools,
                        messages=messages,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    if unavailable_summary:
                        return unavailable_summary
        model_config = self._agent_model_config_private(agent)
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        model = str(model_config.get("model") or "").strip()
        api_key = str(model_config.get("api_key") or "").strip()
        if not base_url or not model or not api_key:
            raise self._error_type("Agent 模型 Profile 缺少 base_url、model 或 API Key")
        tools = self._tool_schemas(allowed_tools)
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
    ) -> str:
        tool_name = str(candidate.get("tool") or "").strip()
        payload = candidate.get("input") if isinstance(candidate.get("input"), dict) else {}
        summary = self._unavailable_desktop_intent_summary(tool_name, allowed_tools)
        event_payload = {
            "tool": tool_name,
            "status": "unavailable",
            "source": "daily_desktop_intent",
            "reason": "tool_not_allowed",
            "blocked_by": "agent_tool_policy",
            "blocked_summary": summary,
            "recovery_actions": [
                "改用八千代日常入口执行这个桌面指令。",
                "在 Agent Studio 为该 Agent 开启桌面执行能力。",
            ],
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
        return summary

    @staticmethod
    def _unavailable_desktop_intent_summary(tool_name: str, allowed_tools: list[str]) -> str:
        label = _DAILY_DESKTOP_TOOL_LABELS.get(tool_name) or tool_name or "桌面动作"
        allowed = ", ".join(str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip())
        allowed_suffix = f"当前允许的工具：{allowed}。" if allowed else "当前没有开启可执行工具。"
        return (
            f"这个 Agent 当前没有开启 {tool_name}，所以不能直接执行「{label}」。"
            "请改用八千代日常入口，或在 Agent Studio 给该 Agent 开启桌面执行能力。"
            f"{allowed_suffix}"
        )

    def _record_desktop_intent_approval_required(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        pending_approval: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        event_payload = {
            "tool": tool_name,
            "status": "approval_required",
            "source": "daily_desktop_intent",
            "reason": "tool_policy_requires_approval",
            "input_preview": tool_input,
        }
        for key in ("approval_id", "risk_level", "policy_reason"):
            value = str(pending_approval.get(key) or "").strip()
            if value:
                event_payload[key] = value
        timeline.append(
            self._timeline(
                "agent.desktop.intent_approval_required",
                tool_name,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.desktop.intent_approval_required", event_payload)

    def _direct_daily_desktop_result(
        self,
        _agent: dict[str, Any],
        planned_tool: str,
        planned_input: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> str:
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
            "input_preview": planned_input,
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
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if data.get("launch_verified") is False and app_name:
                    return f"已向 macOS 发送打开 {app_name} 的请求，但未能确认它已启动。"
                return f"已打开 {app_name}。" if app_name else (result_summary or "已打开应用。")
            if tool_name == "app.focus":
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已切换到 {app_name}。" if app_name else (result_summary or "已切换到应用。")
            if tool_name == "app.quit":
                app_name = _payload_text(result, planned_input, "app_name")
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if data.get("running") is True and app_name:
                    return f"已向 {app_name} 发送退出请求，但它可能仍在运行。"
                return f"已退出 {app_name}。" if app_name else (result_summary or "已退出应用。")
            if tool_name == "media.apple_music_play":
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                track = str(data.get("track") or "").strip()
                artist = str(data.get("artist") or "").strip()
                query = _payload_text(result, planned_input, "query")
                if track:
                    return f"已在 Apple Music 播放：{track}{f' - {artist}' if artist else ''}。"
                return f"已尝试在 Apple Music 播放：{query}。" if query else (result_summary or "已尝试播放。")
            if tool_name == "media.apple_music_control":
                return _apple_music_control_summary(result, planned_input) or result_summary or "已控制 Apple Music。"
            if tool_name == "system.volume":
                return _system_volume_summary(result, planned_input) or result_summary or "已处理系统音量。"
            if tool_name == "clipboard.write":
                return _clipboard_write_summary(result, planned_input) or result_summary or "已写入剪贴板。"
            if tool_name == "screen.capture":
                return result_summary or "已截取当前屏幕。"
            if tool_name == "desktop.permissions":
                return _desktop_permissions_summary(result) or result_summary or "已检查桌面权限。"
            if tool_name == "desktop.active_window":
                return result_summary or _active_window_summary(result)
            if tool_name == "desktop.running_apps":
                return _running_apps_summary(result) or result_summary or "已读取运行中的应用。"
            if tool_name == "desktop.windows":
                return _windows_summary(result, planned_input) or result_summary or "已读取窗口列表。"
            if tool_name == "app.status":
                return _app_status_summary(result, planned_input) or result_summary or "已检查应用状态。"
            if tool_name == "desktop.reveal_path":
                path = _payload_text(result, planned_input, "path")
                return f"已在 Finder 中显示：{path}。" if path else (result_summary or "已在 Finder 中显示。")
            if tool_name == "desktop.open_path":
                return _desktop_open_path_summary(result, planned_input) or result_summary or "已打开本地路径。"
            if tool_name == "desktop.hide_app":
                return "已隐藏当前应用。"
            if tool_name == "desktop.minimize_window":
                return "已最小化当前窗口。"
            if tool_name == "desktop.close_window":
                return "已关闭当前窗口。"
            if tool_name == "browser.open_url":
                url = _payload_text(result, planned_input, "url")
                if result.get("fallback_used") and result.get("fallback") == "system_browser":
                    return f"已用系统浏览器打开网页：{url}。" if url else (result_summary or "已用系统浏览器打开网页。")
                return f"已打开网页：{url}。" if url else (result_summary or "已打开网页。")
            if tool_name == "browser.current_page":
                return result_summary or _browser_page_summary(result)
            if tool_name == "browser.extract_text":
                return result_summary or _browser_text_summary(result)
            if tool_name == "browser.screenshot":
                return result_summary or "已截取当前网页。"
            if tool_name == "desktop.hotkey":
                hotkey = _hotkey_text(result, planned_input)
                return f"已发送快捷键：{hotkey}。" if hotkey else (result_summary or "已发送快捷键。")
            if tool_name == "desktop.type_text":
                text = _payload_text(result, planned_input, "text")
                if text:
                    return f"已向前台输入文字（{len(text)} 个字符）。"
                return result_summary or "已向前台输入文字。"
            if tool_name == "desktop.click":
                click = _click_text(result, planned_input)
                return f"已点击前台位置：{click}。" if click else (result_summary or "已点击前台界面。")
            return result_summary or "已执行桌面操作。"

        fallback = result.get("fallback_result") if isinstance(result.get("fallback_result"), dict) else {}
        if tool_name == "media.apple_music_play" and fallback.get("ok"):
            query = _payload_text(result, planned_input, "query")
            return (
                f"没能直接播放 {query}，但已打开 Apple Music。"
                if query
                else "没能直接播放，但已打开 Apple Music。"
            )
        if tool_name == "media.apple_music_control" and fallback.get("ok"):
            action = _payload_text(result, planned_input, "action")
            label = _apple_music_control_label(action)
            return f"没能直接{label}，但已打开 Apple Music。" if label else "没能直接控制，但已打开 Apple Music。"
        error = str(result.get("error") or result_summary or "工具返回失败").strip()
        permission_targets = result.get("permission_targets")
        if result.get("permission_error") or permission_targets:
            targets = ", ".join(str(item) for item in permission_targets or [] if str(item))
            diagnostics = _permission_diagnostics(result)
            suffix = f" 缺少权限：{targets}。" if targets else ""
            return f"桌面操作未完成：{_sentence(error)}{suffix}{diagnostics}".strip()
        diagnostics = _permission_diagnostics(result)
        return f"桌面操作未完成：{_sentence(error)}{diagnostics}".strip()

    def _direct_existing_daily_desktop_result(
        self,
        agent: dict[str, Any],
        timeline: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> str:
        tool_event = self._latest_tool_call_event_for_daily_desktop_intent(timeline)
        if not tool_event:
            return ""
        tool_name = str(tool_event.get("detail") or tool_event.get("tool") or "").strip()
        planned_input = self._latest_daily_desktop_input(timeline, tool_name)
        if planned_input is None:
            return ""
        return self._direct_daily_desktop_result(
            agent,
            tool_name,
            planned_input,
            timeline,
            run_id=run_id,
        )

    @staticmethod
    def _latest_tool_call_event_for_daily_desktop_intent(
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for event in reversed(timeline):
            if event.get("event") == "agent.desktop.intent_completed":
                return None
            if event.get("event") != "agent.tool.call":
                continue
            tool_name = str(event.get("detail") or event.get("tool") or "").strip()
            if tool_name in _DIRECT_DAILY_DESKTOP_TOOLS:
                return event
        return None

    @staticmethod
    def _latest_daily_desktop_input(
        timeline: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any] | None:
        for event in reversed(timeline):
            event_type = str(event.get("event") or "").strip()
            if event_type not in {
                "agent.desktop.intent_planned",
                "agent.desktop.intent_approval_required",
            }:
                continue
            event_tool = str(event.get("tool") or event.get("detail") or "").strip()
            if event_tool != tool_name:
                continue
            if str(event.get("source") or "") != "daily_desktop_intent":
                continue
            input_preview = event.get("input_preview")
            return dict(input_preview) if isinstance(input_preview, dict) else {}
        return None

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
            "desktop.permissions, desktop.active_window, desktop.running_apps, desktop.windows, app.status, app.open/app.focus/app.quit, desktop.reveal_path, desktop.open_path, media.apple_music_play, "
            "media.apple_music_control, system.volume, clipboard.write, desktop.hide_app, desktop.minimize_window, desktop.close_window, desktop.click, desktop.hotkey, and desktop.type_text "
            "when they are allowed. For explicit daily commands, map 'play <song>' or "
            "'播放<歌曲>' to media.apple_music_play; map pause/resume/next/previous media "
            "commands to media.apple_music_control; map volume status/set/up/down/mute/unmute "
            "commands to system.volume; map explicit 'copy/write to clipboard' requests to "
            "clipboard.write without reading clipboard contents; map screen capture requests to "
            "screen.capture, and current or foreground window questions to desktop.active_window "
            "before answering; map running/open app list questions to desktop.running_apps; "
            "map open window list questions to desktop.windows; "
            "map single app running/open status questions to app.status; "
            "map explicit app quit/close/exit requests to app.quit; "
            "map desktop permission diagnostics and 'why can't you control/open/click/play' "
            "questions to desktop.permissions; "
            "map 'show/reveal in Finder' requests to desktop.reveal_path and safe local "
            "file or folder open requests to desktop.open_path. "
            "Map explicit current/foreground app hide requests to desktop.hide_app. "
            "Map explicit current/foreground window minimize requests to desktop.minimize_window. "
            "Map explicit current/foreground window close requests to desktop.close_window. "
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


def _hotkey_text(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    key = str(data.get("key") or planned_input.get("key") or "").strip()
    raw_modifiers = data.get("modifiers") or planned_input.get("modifiers") or []
    modifiers = [str(item).strip() for item in raw_modifiers if str(item).strip()] if isinstance(raw_modifiers, list) else []
    parts = [*_hotkey_modifier_labels(modifiers), key.upper() if len(key) == 1 else key]
    return "+".join(part for part in parts if part)


def _hotkey_modifier_labels(modifiers: list[str]) -> list[str]:
    labels = {
        "command": "Command",
        "cmd": "Command",
        "shift": "Shift",
        "option": "Option",
        "alt": "Option",
        "control": "Control",
        "ctrl": "Control",
    }
    return [labels.get(modifier.lower(), modifier) for modifier in modifiers]


def _click_text(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    x = data.get("x", planned_input.get("x"))
    y = data.get("y", planned_input.get("y"))
    click_count = data.get("click_count", planned_input.get("click_count"))
    if x in (None, "") or y in (None, ""):
        return ""
    count_text = "双击 " if str(click_count or "") == "2" else ""
    return f"{count_text}{x}, {y}"


def _active_window_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(data.get("app_name") or "").strip()
    title = str(data.get("title") or "").strip()
    if app_name and title:
        return f"当前前台窗口是 {app_name}：{title}。"
    if app_name:
        return f"当前前台应用是 {app_name}。"
    return "已读取当前前台窗口。"


def _desktop_permissions_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_targets = result.get("permission_targets") or data.get("permission_targets") or []
    targets = _text_list(raw_targets)
    if not targets:
        return "桌面执行权限已就绪。"
    raw_tools = result.get("affected_tools") or data.get("affected_tools") or []
    affected_tools = _text_list(raw_tools)
    target_text = ", ".join(targets[:6])
    target_suffix = " 等" if len(targets) > 6 else ""
    if not affected_tools:
        return _append_recovery_action_summary(
            f"桌面执行权限还缺少：{target_text}{target_suffix}。",
            result,
        )
    tool_text = ", ".join(affected_tools[:6])
    tool_suffix = " 等" if len(affected_tools) > 6 else ""
    return _append_recovery_action_summary(
        f"桌面执行权限还缺少：{target_text}{target_suffix}。受影响工具：{tool_text}{tool_suffix}。",
        result,
    )


def _append_recovery_action_summary(text: str, result: dict[str, Any]) -> str:
    labels = _recovery_action_labels(result)
    if not labels:
        return text
    return f"{text}可直接打开：{'、'.join(labels[:4])}。"


def _recovery_action_labels(result: dict[str, Any]) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_actions = result.get("recovery_actions") or data.get("recovery_actions") or []
    if not isinstance(raw_actions, list):
        return []
    labels: list[str] = []
    for action in raw_actions:
        if isinstance(action, dict):
            label = str(action.get("label") or action.get("tool") or "").strip()
        else:
            label = str(action or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _running_apps_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_apps = data.get("apps")
    if not isinstance(raw_apps, list):
        return ""
    names = []
    for item in raw_apps:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    if not names:
        return "当前没有读取到正在运行的前台应用。"
    visible = names[:8]
    suffix = f" 等 {len(names)} 个应用" if len(names) > len(visible) else ""
    frontmost = str(data.get("frontmost") or "").strip()
    frontmost_text = f"前台是 {frontmost}。" if frontmost else ""
    return f"正在运行的应用：{', '.join(visible)}{suffix}。{frontmost_text}"


def _windows_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_windows = data.get("windows")
    if not isinstance(raw_windows, list):
        return ""
    app_filter = str(data.get("app_name") or planned_input.get("app_name") or "").strip()
    if not raw_windows:
        return f"没有读取到 {app_filter} 的窗口。" if app_filter else "没有读取到打开的窗口。"
    items = []
    for item in raw_windows[:8]:
        if not isinstance(item, dict):
            continue
        app_name = str(item.get("app_name") or "").strip()
        title = str(item.get("title") or "").strip()
        if title and app_name:
            items.append(f"{app_name}: {title}")
        elif app_name:
            items.append(app_name)
        elif title:
            items.append(title)
    if not items:
        return ""
    suffix = f" 等 {len(raw_windows)} 个窗口" if len(raw_windows) > len(items) else ""
    return f"当前窗口：{'; '.join(items)}{suffix}。"


def _app_status_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(data.get("app_name") or planned_input.get("app_name") or "").strip()
    running = data.get("running")
    if not app_name or not isinstance(running, bool):
        return ""
    return f"{app_name} 当前{'正在运行' if running else '没有运行'}。"


def _text_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    elif value in (None, ""):
        raw_items = []
    else:
        raw_items = [value]
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


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


def _apple_music_control_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("control") or planned_input.get("action") or "").strip()
    label = _apple_music_control_label(action)
    if not label:
        return ""
    track = str(data.get("track") or "").strip()
    artist = str(data.get("artist") or "").strip()
    track_text = f"当前：{track}{f' - {artist}' if artist else ''}。" if track else ""
    return f"已{label} Apple Music。{track_text}"


def _apple_music_control_label(action: str) -> str:
    return {
        "toggle": "切换播放/暂停",
        "play": "继续播放",
        "pause": "暂停",
        "next": "切到下一首",
        "previous": "切到上一首",
    }.get(str(action or "").strip(), "")


def _system_volume_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("requested_action") or planned_input.get("action") or "").strip()
    level = data.get("level")
    muted = data.get("muted")
    old_level = data.get("old_level")
    try:
        level_text = f"{int(level)}%"
    except (TypeError, ValueError):
        level_text = ""
    try:
        old_level_text = f"{int(old_level)}%"
    except (TypeError, ValueError):
        old_level_text = ""
    if action == "status":
        if level_text:
            return f"当前系统音量是 {level_text}{'，已静音' if muted else ''}。"
        return ""
    if action == "set" and level_text:
        return f"已把系统音量调到 {level_text}。"
    if action == "up" and old_level_text and level_text:
        return f"已把系统音量从 {old_level_text} 调高到 {level_text}。"
    if action == "down" and old_level_text and level_text:
        return f"已把系统音量从 {old_level_text} 调低到 {level_text}。"
    if action == "mute":
        return "已将系统音量静音。"
    if action == "unmute":
        return f"已取消系统静音{f'，当前音量 {level_text}' if level_text else ''}。"
    return ""


def _clipboard_write_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    length = data.get("text_length")
    if not isinstance(length, int):
        text = str(planned_input.get("text") or "")
        length = len(text) if text else 0
    return f"已复制 {length} 个字符到剪贴板。" if length else "已写入剪贴板。"


def _desktop_open_path_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    path = str(data.get("path") or planned_input.get("path") or "").strip()
    if not path:
        return ""
    if data.get("is_dir") is True:
        return f"已打开文件夹：{path}。"
    return f"已打开文件：{path}。"


def _sentence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith(("。", ".", "!", "！", "?", "？")):
        return text
    return f"{text}。"


def _permission_diagnostics(result: dict[str, Any]) -> str:
    hints = _string_list(result.get("recovery_hints"))
    if not hints:
        hints = _permission_target_hints(_string_list(result.get("permission_targets")))
    if not hints:
        return ""
    return " 你可以这样处理：" + " ".join(hints)


def _permission_target_hints(targets: list[str]) -> list[str]:
    hints_by_target = {
        "accessibility": "在 macOS 系统设置 > 隐私与安全性 > 辅助功能 中允许 Oha-Yachiyo 或当前运行环境。",
        "automation": "在 macOS 系统设置 > 隐私与安全性 > 自动化 中允许 Oha-Yachiyo 控制目标 App/System Events。",
        "music_app": "先打开 Music.app，确认歌曲在资料库里，并在系统弹窗出现时允许自动化控制 Music。",
        "screen_recording": "在 macOS 系统设置 > 隐私与安全性 > 屏幕录制 中允许 Oha-Yachiyo 或当前运行环境。",
        "chrome_cdp": "启动或配置 Chrome DevTools/CDP 连接后再重试浏览器控制。",
    }
    hints: list[str] = []
    for target in targets:
        hint = hints_by_target.get(target)
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
