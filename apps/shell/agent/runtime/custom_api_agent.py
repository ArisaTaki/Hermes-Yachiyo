"""Custom API Agent model/tool loop."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from apps.shell.agent.runtime.approval_tool_sets import (
    APPROVAL_PLAN_TOOLS as _DAILY_DESKTOP_APPROVAL_PLAN_TOOLS,
    SAFE_SHORTCUT_APPROVAL_TOOLS as _SAFE_SHORTCUT_HOTKEY_TOOLS,
)
from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_metadata_tool_request,
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_request,
    daily_desktop_intent_tool_requests,
)
from apps.shell.agent.runtime.desktop_tool_labels import (
    DAILY_DESKTOP_TOOL_LABELS as _DAILY_DESKTOP_TOOL_LABELS,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.followup_content_snapshot import (
    followup_content_snapshots,
    latest_followup_content_snapshot,
)
from apps.shell.agent.runtime.tool_execution import (
    _discovered_app_name_for_query,
    _discovered_app_resolution_evidence,
)
from apps.shell.agent.tools.policy import (
    DAILY_BROWSER_TOOL_NAMES,
    DAILY_DESKTOP_TOOL_NAMES,
)
from apps.shell.yachiyo_agent.desktop_plan_hints import hotkey_hint
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    DirectToolSelection,
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.planner_execution import (
    planner_execution_tool_requests,
    planner_tool_requests,
)
from apps.shell.yachiyo_agent.planner_projection import planner_selection_payload
from apps.shell.yachiyo_agent.runtime_doctrine import YACHIYO_RUNTIME_OPERATING_MANUAL

_DIRECT_DAILY_DESKTOP_TOOLS = {
    *DAILY_DESKTOP_TOOL_NAMES,
    "artifact.write",
    "data.analyze",
    "terminal.run",
}

_DAILY_DESKTOP_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.running_apps",
    "desktop.windows",
    "desktop.permissions",
}

_DAILY_DESKTOP_DISCOVERY_PREFIX_TOOLS = {
    "desktop.list_apps",
    "desktop.running_apps",
    "desktop.permissions",
}

_DAILY_DESKTOP_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.windows",
    "desktop.ui_elements",
}

_DAILY_DESKTOP_PLAN_SOURCES = {
    "daily_desktop_intent",
    "runtime_planner",
}

_APP_FOREGROUND_ACTION_TOOLS = {
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
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        daily_desktop_planning_context: str | None = None,
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
        if not default_messages:
            resumed_result = self._direct_existing_daily_desktop_result(
                agent,
                timeline,
                run_id=run_id,
            )
            if resumed_result:
                return resumed_result
        if default_messages or start_iteration == 0:
            planning_context = (
                str(daily_desktop_planning_context or "").strip()
                if daily_desktop_planning_context is not None
                else context if default_messages else self._latest_user_intent_text(messages)
            )
            direct_planned_tool_request = self._direct_daily_desktop_tool_request(
                direct_tool_request,
                allowed_tools,
            )
            direct_planned_tool_requests = self._direct_daily_desktop_tool_requests(
                direct_tool_requests,
                allowed_tools,
            )
            runtime_planner_decision = None
            direct_tool_selection_payload: dict[str, Any] = {}
            if direct_planned_tool_requests:
                planned_tool_requests = direct_planned_tool_requests
                if any(
                    bool(request.get("continue_to_model"))
                    and str(request.get("source") or "").strip() == "runtime_planner"
                    for request in direct_planned_tool_requests
                    if isinstance(request, dict)
                ):
                    (
                        runtime_planner_decision,
                        planner_execution_requests,
                        direct_tool_selection_payload,
                    ) = self._runtime_planner_tool_requests(
                        planning_context,
                        allowed_tools,
                    )
                    if planner_execution_requests:
                        planned_tool_requests = planner_execution_requests
            elif direct_planned_tool_request:
                planned_tool_requests = [direct_planned_tool_request]
            else:
                (
                    runtime_planner_decision,
                    planned_tool_requests,
                    direct_tool_selection_payload,
                ) = self._runtime_planner_tool_requests(
                    planning_context,
                    allowed_tools,
                )
                if not planned_tool_requests:
                    runtime_planner_decision = None
                    direct_tool_selection_payload = {}
                    planned_tool_requests = daily_desktop_intent_tool_requests(
                        planning_context,
                        allowed_tools,
                    )
                    approval_hotkey_request = self._approval_hotkey_request_for_safe_shortcut(
                        planning_context,
                        planned_tool_requests,
                        allowed_tools,
                    )
                    if approval_hotkey_request:
                        planned_tool_requests = [approval_hotkey_request]
            if planned_tool_requests:
                if runtime_planner_decision is not None:
                    self._record_runtime_planner_events(
                        runtime_planner_decision,
                        timeline=timeline,
                        run_id=run_id,
                    )
                self._record_direct_tool_selection_event(
                    direct_tool_selection_payload,
                    timeline=timeline,
                    run_id=run_id,
                )
                for planned_tool_request in planned_tool_requests:
                    planned_tool = str(planned_tool_request.get("tool") or "")
                    planned_input = planned_tool_request.get("input") or {}
                    planned_payload = {
                        "tool": planned_tool,
                        "status": "planned",
                        "source": str(planned_tool_request.get("source") or "daily_desktop_intent"),
                        "planning_reason": str(
                            planned_tool_request.get("planning_reason") or "clear_daily_desktop_intent"
                        ),
                        "input_preview": planned_input,
                    }
                    presentation = str(planned_tool_request.get("presentation") or "").strip()
                    if presentation:
                        planned_payload["presentation"] = presentation
                    if planned_tool_request.get("continue_to_model"):
                        planned_payload["continue_to_model"] = True
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
                execution_tool_requests = planned_tool_requests
                if self._has_approval_plan_tool(planned_tool_requests):
                    execution_tool_requests = _visible_daily_desktop_completed_steps(
                        planned_tool_requests
                    )
                    if not execution_tool_requests:
                        execution_tool_requests = planned_tool_requests
                self._record_desktop_permission_preflight(
                    execution_tool_requests,
                    broker,
                    timeline=timeline,
                    run_id=run_id,
                )
                self._record_desktop_tool_policy_decisions(
                    execution_tool_requests,
                    allowed_tools=allowed_tools,
                    agent=agent,
                    run_id=run_id,
                )
                tool_timeline_start = len(timeline)
                try:
                    self._run_tool_requests(
                        execution_tool_requests,
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
                    pending_approval = (
                        exc.pending_approval if isinstance(exc.pending_approval, dict) else {}
                    )
                    planned_tool = str(
                        pending_approval.get("tool")
                        or execution_tool_requests[0].get("tool")
                        or ""
                    )
                    approval_request = self._planned_request_for_tool(
                        execution_tool_requests,
                        planned_tool,
                    )
                    planned_input = self._pending_approval_input_preview(
                        pending_approval,
                        approval_request,
                        execution_tool_requests[0] if execution_tool_requests else {},
                    )
                    self._record_desktop_intent_approval_required(
                        planned_tool,
                        planned_input,
                        pending_approval=exc.pending_approval,
                        timeline=timeline,
                        run_id=run_id,
                        source=self._approval_event_source(approval_request, planned_tool),
                        planning_reason=self._approval_event_planning_reason(
                            approval_request,
                            planned_tool,
                        ),
                    )
                    raise
                replan_payloads = self._record_runtime_planner_replan_events(
                    runtime_planner_decision,
                    timeline=timeline,
                    tool_timeline_start=tool_timeline_start,
                    run_id=run_id,
                )
                self._record_runtime_planner_task_progress_events(
                    runtime_planner_decision,
                    timeline=timeline,
                    tool_timeline_start=tool_timeline_start,
                    run_id=run_id,
                )
                continue_to_model = bool(replan_payloads) or any(
                    bool(request.get("continue_to_model"))
                    for request in planned_tool_requests
                    if isinstance(request, dict)
                )
                if continue_to_model:
                    followup_selection_payload = _selection_payload_with_timeline_fallback(
                        direct_tool_selection_payload,
                        timeline,
                    )
                    auto_followup_request = self._auto_data_analysis_request_from_discovery(
                        planned_tool_requests,
                        allowed_tools,
                        followup_selection_payload,
                        timeline,
                    )
                    if replan_payloads:
                        self._append_replan_followup_context(
                            replan_payloads,
                            allowed_tools=allowed_tools,
                            messages=messages,
                            timeline=timeline,
                            run_id=run_id,
                        )
                    if auto_followup_request:
                        auto_payload = {
                            "tool": str(auto_followup_request.get("tool") or ""),
                            "status": "planned",
                            "source": str(auto_followup_request.get("source") or "runtime_planner"),
                            "planning_reason": str(
                                auto_followup_request.get("planning_reason")
                                or "planner_builtin_data_analysis"
                            ),
                            "input_preview": (
                                auto_followup_request.get("input")
                                if isinstance(auto_followup_request.get("input"), dict)
                                else {}
                            ),
                        }
                        timeline.append(
                            self._timeline(
                                "agent.desktop.intent_planned",
                                str(auto_followup_request.get("tool") or ""),
                                **auto_payload,
                            )
                        )
                        if run_id and self._append_run_event is not None:
                            self._append_run_event(
                                run_id,
                                "agent.desktop.intent_planned",
                                auto_payload,
                            )
                        self._record_desktop_tool_policy_decisions(
                            [auto_followup_request],
                            allowed_tools=allowed_tools,
                            agent=agent,
                            run_id=run_id,
                        )
                        self._run_tool_requests(
                            [auto_followup_request],
                            allowed_tools,
                            broker,
                            messages,
                            timeline,
                            artifacts,
                            next_iteration=start_iteration,
                            run_id=run_id,
                            budget=budget,
                        )
                        if _selection_payload_has_model_followup_target(
                            followup_selection_payload
                        ):
                            auto_followup_request = {
                                **auto_followup_request,
                                "continue_to_model": True,
                            }
                            planned_tool_requests = [
                                *planned_tool_requests,
                                auto_followup_request,
                            ]
                        else:
                            direct_result = self._direct_daily_desktop_result(
                                agent,
                                "data.analyze",
                                (
                                    auto_followup_request.get("input")
                                    if isinstance(auto_followup_request.get("input"), dict)
                                    else {}
                                ),
                                timeline,
                                run_id=run_id,
                                source=str(auto_followup_request.get("source") or "runtime_planner"),
                                planning_reason=str(
                                    auto_followup_request.get("planning_reason")
                                    or "planner_builtin_data_analysis"
                                ),
                            )
                            if direct_result:
                                return direct_result
                    auto_discovered_app_requests = _auto_discovered_followup_requests(
                        followup_selection_payload,
                        allowed_tools,
                        timeline,
                    )
                    if auto_discovered_app_requests:
                        self._record_auto_model_followup_app_write_plan(
                            auto_discovered_app_requests,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_permission_preflight(
                            auto_discovered_app_requests,
                            broker,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_tool_policy_decisions(
                            auto_discovered_app_requests,
                            allowed_tools=allowed_tools,
                            agent=agent,
                            run_id=run_id,
                        )
                        auto_tool_timeline_start = len(timeline)
                        try:
                            self._run_tool_requests(
                                auto_discovered_app_requests,
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
                            pending_approval = (
                                exc.pending_approval
                                if isinstance(exc.pending_approval, dict)
                                else {}
                            )
                            planned_tool = str(
                                pending_approval.get("tool")
                                or auto_discovered_app_requests[0].get("tool")
                                or ""
                            )
                            approval_request = self._planned_request_for_tool(
                                auto_discovered_app_requests,
                                planned_tool,
                            )
                            planned_input = self._pending_approval_input_preview(
                                pending_approval,
                                approval_request,
                                (
                                    auto_discovered_app_requests[0]
                                    if auto_discovered_app_requests
                                    else {}
                                ),
                            )
                            self._record_desktop_intent_approval_required(
                                planned_tool,
                                planned_input,
                                pending_approval=exc.pending_approval,
                                timeline=timeline,
                                run_id=run_id,
                                source=self._approval_event_source(
                                    approval_request,
                                    planned_tool,
                                ),
                                planning_reason=self._approval_event_planning_reason(
                                    approval_request,
                                    planned_tool,
                                ),
                            )
                            raise
                        if any(
                            bool(request.get("continue_to_model"))
                            for request in auto_discovered_app_requests
                            if isinstance(request, dict)
                        ):
                            planned_tool_requests = [
                                *planned_tool_requests,
                                *auto_discovered_app_requests,
                            ]
                        else:
                            direct_result = self._direct_daily_desktop_sequence_result(
                                auto_discovered_app_requests,
                                timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            if direct_result:
                                return direct_result
                    self._append_model_followup_context(
                        planned_tool_requests,
                        followup_selection_payload,
                        allowed_tools=allowed_tools,
                        messages=messages,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    direct_result = ""
                elif len(execution_tool_requests) == 1:
                    planned_tool = str(execution_tool_requests[0].get("tool") or "")
                    planned_input = execution_tool_requests[0].get("input") or {}
                    presentation = str(execution_tool_requests[0].get("presentation") or "").strip()
                    direct_result = self._direct_daily_desktop_result(
                        agent,
                        planned_tool,
                        planned_input,
                        timeline,
                        run_id=run_id,
                        presentation=presentation,
                        source=str(
                            execution_tool_requests[0].get("source") or "daily_desktop_intent"
                        ),
                        planning_reason=str(
                            execution_tool_requests[0].get("planning_reason") or ""
                        ),
                    )
                else:
                    direct_result = self._direct_daily_desktop_sequence_result(
                        execution_tool_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                        run_id=run_id,
                    )
                if direct_result:
                    return direct_result
            else:
                direct_candidate = (
                    direct_tool_request
                    if isinstance(direct_tool_request, dict)
                    and str(direct_tool_request.get("tool") or "").strip()
                    else None
                )
                candidates = [direct_candidate] if direct_candidate else daily_desktop_intent_candidates(planning_context)
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
                followup_target = _latest_model_followup_target(timeline)
                auto_app_write_requests = _model_followup_app_write_requests(
                    content,
                    followup_target,
                    allowed_tools,
                )
                if auto_app_write_requests:
                    messages.append({"role": "assistant", "content": content})
                    self._record_auto_model_followup_app_write_plan(
                        auto_app_write_requests,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    self._record_desktop_permission_preflight(
                        auto_app_write_requests,
                        broker,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    self._record_desktop_tool_policy_decisions(
                        auto_app_write_requests,
                        allowed_tools=allowed_tools,
                        agent=agent,
                        run_id=run_id,
                    )
                    tool_timeline_start = len(timeline)
                    try:
                        self._run_tool_requests(
                            auto_app_write_requests,
                            allowed_tools,
                            broker,
                            messages,
                            timeline,
                            artifacts,
                            next_iteration=iteration + 1,
                            run_id=run_id,
                            budget=budget,
                        )
                        discovered_app_write_requests = (
                            _model_followup_discovered_app_write_requests_after_discovery(
                                content,
                                followup_target,
                                allowed_tools,
                                timeline,
                            )
                        )
                        if discovered_app_write_requests:
                            self._record_auto_model_followup_app_write_plan(
                                discovered_app_write_requests,
                                timeline=timeline,
                                run_id=run_id,
                            )
                            self._record_desktop_permission_preflight(
                                discovered_app_write_requests,
                                broker,
                                timeline=timeline,
                                run_id=run_id,
                            )
                            self._record_desktop_tool_policy_decisions(
                                discovered_app_write_requests,
                                allowed_tools=allowed_tools,
                                agent=agent,
                                run_id=run_id,
                            )
                            self._run_tool_requests(
                                discovered_app_write_requests,
                                allowed_tools,
                                broker,
                                messages,
                                timeline,
                                artifacts,
                                next_iteration=iteration + 1,
                                run_id=run_id,
                                budget=budget,
                            )
                            auto_app_write_requests = [
                                *auto_app_write_requests,
                                *discovered_app_write_requests,
                            ]
                    except AgentApprovalRequired as exc:
                        pending_approval = (
                            exc.pending_approval if isinstance(exc.pending_approval, dict) else {}
                        )
                        planned_tool = str(
                            pending_approval.get("tool")
                            or auto_app_write_requests[0].get("tool")
                            or ""
                        )
                        approval_request = self._planned_request_for_tool(
                            auto_app_write_requests,
                            planned_tool,
                        )
                        planned_input = self._pending_approval_input_preview(
                            pending_approval,
                            approval_request,
                            auto_app_write_requests[0] if auto_app_write_requests else {},
                        )
                        self._record_desktop_intent_approval_required(
                            planned_tool,
                            planned_input,
                            pending_approval=exc.pending_approval,
                            timeline=timeline,
                            run_id=run_id,
                            source=self._approval_event_source(approval_request, planned_tool),
                            planning_reason=self._approval_event_planning_reason(
                                approval_request,
                                planned_tool,
                            ),
                        )
                        raise
                    direct_result = self._direct_daily_desktop_sequence_result(
                        auto_app_write_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                        run_id=run_id,
                    )
                    if direct_result:
                        return direct_result
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

    @staticmethod
    def _direct_daily_desktop_tool_request(
        tool_request: dict[str, Any] | None,
        allowed_tools: list[str],
    ) -> dict[str, Any] | None:
        if not isinstance(tool_request, dict):
            return None
        tool_name = str(tool_request.get("tool") or "").strip()
        if not tool_name:
            return None
        allowed = {str(tool or "").strip() for tool in allowed_tools}
        if tool_name not in allowed:
            return None
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        return {
            **tool_request,
            "tool": tool_name,
            "input": dict(payload),
        }

    @classmethod
    def _direct_daily_desktop_tool_requests(
        cls,
        tool_requests: list[dict[str, Any]] | None,
        allowed_tools: list[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(tool_requests, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for tool_request in tool_requests:
            cleaned_request = cls._direct_daily_desktop_tool_request(
                tool_request,
                allowed_tools,
            )
            if cleaned_request:
                cleaned.append(cleaned_request)
        if any(
            str(request.get("planning_reason") or "").strip() == "explicit_full_plan"
            for request in cleaned
        ):
            return cleaned
        requests = planner_execution_tool_requests(cleaned, allowed_tools)
        if any(
            str(request.get("planning_reason") or "").strip() == "explicit_full_plan"
            for request in requests
        ):
            return _drop_trailing_daily_desktop_verify_requests(requests) or requests
        return requests

    @staticmethod
    def _auto_data_analysis_request_from_discovery(
        planned_tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
        selection_payload: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        allowed = {str(tool or "").strip() for tool in allowed_tools}
        if "data.analyze" not in allowed:
            return None
        if not any(
            str(request.get("planning_reason") or "").strip() == "planner_prefetch_data_source"
            and bool(request.get("continue_to_model"))
            for request in planned_tool_requests
            if isinstance(request, dict)
        ):
            return None
        captured_request = _auto_data_analysis_request_from_captured_content(
            planned_tool_requests,
            selection_payload,
            timeline,
        )
        if captured_request:
            return captured_request
        latest_list = _latest_workspace_list_event(timeline)
        if latest_list is None:
            return None
        result = latest_list.get("result") if isinstance(latest_list.get("result"), dict) else {}
        if result.get("ok") is not True:
            return None
        entries = result.get("entries")
        if not isinstance(entries, list):
            return None
        data_files = [
            str(entry.get("name") or "").strip()
            for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("type") or "").strip() == "file"
            and _data_analysis_file_kind(str(entry.get("name") or "")) != ""
        ]
        if len(data_files) != 1:
            return None
        list_input = latest_list.get("input_preview") if isinstance(latest_list.get("input_preview"), dict) else {}
        base_path = str(list_input.get("path") or result.get("path") or "").strip()
        path = _join_workspace_list_path(base_path, data_files[0])
        artifact_paths = ["analysis-report.md"]
        return {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": {
                "path": path,
                "artifact_path": artifact_paths[0],
                "source_kind": _data_analysis_file_kind(path),
                "requested_outputs": ["report"],
                "artifact_manifest": [{"path": artifact_paths[0], "kind": "markdown"}],
            },
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
        }

    def _append_model_followup_context(
        self,
        planned_tool_requests: list[dict[str, Any]],
        selection_payload: dict[str, Any],
        *,
        allowed_tools: list[str],
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        payload = _model_followup_context_payload(
            planned_tool_requests,
            selection_payload,
            allowed_tools=allowed_tools,
            timeline=timeline,
        )
        if not payload:
            return
        messages.append(
            {
                "role": "user",
                "content": _model_followup_context_message(payload),
            }
        )
        timeline.append(
            self._timeline(
                "agent.model.followup_context",
                str(payload.get("planning_reason") or "model_followup"),
                **payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.model.followup_context", payload)

    def _append_replan_followup_context(
        self,
        replan_payloads: list[dict[str, Any]],
        *,
        allowed_tools: list[str],
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        payload = _model_replan_followup_context_payload(
            replan_payloads,
            allowed_tools=allowed_tools,
            timeline=timeline,
        )
        if not payload:
            return
        messages.append(
            {
                "role": "user",
                "content": _model_replan_followup_context_message(payload),
            }
        )
        timeline.append(
            self._timeline(
                "agent.model.followup_context",
                str(payload.get("planning_reason") or "planner_replan_after_tool_failure"),
                **payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.model.followup_context", payload)

    def _record_auto_model_followup_app_write_plan(
        self,
        tool_requests: list[dict[str, Any]],
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        for request in tool_requests:
            tool_name = str(request.get("tool") or "").strip()
            if not tool_name:
                continue
            payload = {
                "tool": tool_name,
                "status": "planned",
                "source": str(request.get("source") or "runtime_planner"),
                "planning_reason": str(
                    request.get("planning_reason") or "planner_followup_app_write"
                ),
                "input_preview": (
                    request.get("input") if isinstance(request.get("input"), dict) else {}
                ),
            }
            timeline.append(
                self._timeline(
                    "agent.desktop.intent_planned",
                    tool_name,
                    **payload,
                )
            )
            if run_id and self._append_run_event is not None:
                self._append_run_event(run_id, "agent.desktop.intent_planned", payload)

    @staticmethod
    def _planned_request_for_tool(
        planned_tool_requests: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any]:
        clean_tool = str(tool_name or "").strip()
        for request in planned_tool_requests:
            if str(request.get("tool") or "").strip() == clean_tool:
                return request
        return planned_tool_requests[0] if planned_tool_requests else {}

    @staticmethod
    def _pending_approval_input_preview(
        pending_approval: dict[str, Any],
        planned_request: dict[str, Any],
        fallback_request: dict[str, Any],
    ) -> dict[str, Any]:
        for candidate in (
            pending_approval.get("input_preview"),
            pending_approval.get("input"),
            planned_request.get("input") if isinstance(planned_request, dict) else None,
            fallback_request.get("input") if isinstance(fallback_request, dict) else None,
        ):
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    @staticmethod
    def _approval_event_source(
        planned_request: dict[str, Any],
        tool_name: str,
    ) -> str:
        planning_reason = str(planned_request.get("planning_reason") or "").strip()
        if planning_reason == "planner_desktop_hotkey" or "hotkey" in str(tool_name or ""):
            return "daily_desktop_intent"
        return str(planned_request.get("source") or "daily_desktop_intent")

    @staticmethod
    def _approval_event_planning_reason(
        planned_request: dict[str, Any],
        tool_name: str,
    ) -> str:
        planning_reason = str(planned_request.get("planning_reason") or "").strip()
        if planning_reason == "planner_desktop_hotkey" or "hotkey" in str(tool_name or ""):
            return ""
        if (
            planning_reason == "planner_desktop_operation"
            and str(tool_name or "").strip().endswith("_click_ui_element")
        ):
            return "planner_fallback_desktop_operation"
        return planning_reason

    @staticmethod
    def _approval_hotkey_request_for_safe_shortcut(
        planning_context: str,
        tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> dict[str, Any] | None:
        if len(tool_requests) != 1 or not isinstance(tool_requests[0], dict):
            return None
        safe_request = tool_requests[0]
        safe_tool = str(safe_request.get("tool") or "").strip()
        hotkey_tool = _SAFE_SHORTCUT_HOTKEY_TOOLS.get(safe_tool, "")
        allowed = {str(tool or "").strip() for tool in allowed_tools}
        if not hotkey_tool or hotkey_tool not in allowed:
            return None
        hotkey = hotkey_hint(planning_context)
        if not hotkey:
            return None
        safe_input = safe_request.get("input") if isinstance(safe_request.get("input"), dict) else {}
        if str(safe_input.get("action") or "").strip() != "focus_address_bar":
            return None
        payload = dict(hotkey)
        app_name = str(safe_input.get("app_name") or "").strip()
        if app_name:
            payload = {"app_name": app_name, **payload}
        return {
            "protocol": "json_fallback",
            "tool": hotkey_tool,
            "input": payload,
            "source": "daily_desktop_intent",
            "planning_reason": "explicit_hotkey_requires_approval",
        }

    def _runtime_planner_tool_requests(
        self,
        planning_context: str,
        allowed_tools: list[str],
    ) -> tuple[Any | None, list[dict[str, Any]], dict[str, Any]]:
        try:
            selection: DirectToolSelection = planner_first_direct_tool_selection(
                planning_context,
                allowed_tools,
                legacy_tool_requests=daily_desktop_intent_tool_requests,
                legacy_postprocess=lambda requests: [
                    self._approval_hotkey_request_for_safe_shortcut(
                        planning_context,
                        requests,
                        allowed_tools,
                    )
                    or request
                    for request in requests
                ],
            )
            if selection.selected_source == "runtime_planner" and selection.decision is not None:
                full_plan_requests = planner_tool_requests(
                    planning_context,
                    allowed_tools,
                )
                execution_requests = planner_execution_tool_requests(
                    full_plan_requests,
                    allowed_tools,
                )
                execution_requests = self._legacy_return_hotkey_projection(
                    planning_context,
                    execution_requests,
                    allowed_tools,
                )
                execution_requests = _drop_trailing_daily_desktop_verify_requests(execution_requests)
                if execution_requests and (
                    not self._has_approval_plan_tool(execution_requests)
                    or _direct_action_with_active_window_verification(execution_requests)
                ):
                    return (
                        selection.decision,
                        execution_requests,
                        planner_selection_payload(
                            decision=selection.decision,
                            planner_requests=full_plan_requests,
                            legacy_requests=[],
                            selected_requests=execution_requests,
                            selected_source="runtime_planner",
                            selected_reason="runtime_planner_full_plan_execution",
                        ),
                    )
            execution_requests = planner_execution_tool_requests(
                selection.requests,
                allowed_tools,
            )
            execution_requests = self._legacy_return_hotkey_projection(
                planning_context,
                execution_requests,
                allowed_tools,
            )
            execution_requests = _drop_trailing_daily_desktop_verify_requests(execution_requests)
            event_payload = selection.event_payload
            if execution_requests != selection.requests:
                execution_tools = [
                    str(request.get("tool") or "").strip()
                    for request in execution_requests
                    if str(request.get("tool") or "").strip()
                ]
                event_payload = {
                    **selection.event_payload,
                    "selected_tools": execution_tools,
                    "selected_request_count": len(execution_requests),
                    "execution_tools": execution_tools,
                    "execution_request_count": len(execution_requests),
                }
            return selection.decision, execution_requests, event_payload
        except Exception:
            return None, [], {}

    @staticmethod
    def _legacy_return_hotkey_projection(
        planning_context: str,
        requests: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> list[dict[str, Any]]:
        if not requests or "desktop.hotkey" not in {str(tool or "").strip() for tool in allowed_tools}:
            return requests
        if not RuntimeCustomApiAgentLoop._legacy_explicit_return_key_prompt(planning_context):
            return requests
        updated: list[dict[str, Any]] = []
        converted = False
        for request in requests:
            tool_name = str(request.get("tool") or "").strip()
            payload = request.get("input") if isinstance(request.get("input"), dict) else {}
            if (
                not converted
                and tool_name == "desktop.submit_foreground"
                and str(payload.get("action") or "").strip() == "confirm"
            ):
                updated.append(
                    {
                        **request,
                        "tool": "desktop.hotkey",
                        "input": {"key": "return", "modifiers": []},
                        "planning_reason": "planner_desktop_hotkey",
                    }
                )
                converted = True
                continue
            updated.append(request)
        return updated

    @staticmethod
    def _legacy_explicit_return_key_prompt(planning_context: str) -> bool:
        value = str(planning_context or "").strip()
        if re.search(r"(?:发送|提交|send|submit).{0,8}(?:回车|enter|return)", value, flags=re.IGNORECASE):
            return False
        return bool(
            re.search(
                r"(?:并|再|然后|接着|之后|后|and\s+then|then)?.{0,8}"
                r"(?:按|敲|触发|press|hit|tap)?\s*(?:回车键?|enter|return)(?:\s|$|[。！？!?，,])",
                value,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _has_approval_plan_tool(tool_requests: list[dict[str, Any]]) -> bool:
        return any(
            isinstance(request, dict)
            and str(request.get("tool") or "").strip() in _DAILY_DESKTOP_APPROVAL_PLAN_TOOLS
            for request in tool_requests
        )

    def _record_runtime_planner_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        decision_id = str(getattr(decision, "decision_id", "") or "").strip()
        if decision_id and any(
            str(event.get("decision_id") or "") == decision_id
            or str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), dict)
                    else {}
                ).get("decision_id")
                or ""
            )
            == decision_id
            for event in timeline
            if isinstance(event, dict)
        ):
            return
        try:
            from apps.shell.yachiyo_agent.planner_projection import (
                planner_run_event_payloads,
                planner_timeline_events,
            )
        except Exception:
            return
        for event in planner_timeline_events(decision):
            timeline.append(event)
        if run_id and self._append_run_event is not None:
            for event_type, payload in planner_run_event_payloads(decision):
                self._append_run_event(run_id, event_type, payload)
        self._record_runtime_planner_initial_task_events(
            decision,
            timeline=timeline,
            run_id=run_id,
        )

    def _record_runtime_planner_initial_task_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        for event_type, detail, payload in _runtime_planner_initial_task_updates(decision):
            if _runtime_task_update_exists(timeline, event_type, payload):
                continue
            timeline.append(self._timeline(event_type, detail, **payload))
            if run_id and self._append_run_event is not None:
                self._append_run_event(run_id, event_type, payload)

    def _record_direct_tool_selection_event(
        self,
        payload: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        if not payload:
            return
        event_payload = dict(payload)
        detail = str(
            event_payload.get("selection_source")
            or event_payload.get("selection_reason")
            or "direct_tool_selection"
        )
        timeline.append(
            self._timeline(
                "agent.plan.selection",
                detail,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.plan.selection", event_payload)

    def _record_runtime_planner_replan_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        tool_timeline_start: int,
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        if decision is None:
            return []
        try:
            from apps.shell.yachiyo_agent.planner_projection import (
                planner_replan_timeline_event,
            )
        except Exception:
            return []
        existing_request_ids = {
            str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), dict)
                    else {}
                ).get("request_id")
                or ""
            )
            for event in timeline
            if isinstance(event, dict)
            and str(event.get("event") or "").strip() == "agent.replan.requested"
        }
        payloads: list[dict[str, Any]] = []
        for event in list(timeline[tool_timeline_start:]):
            if not isinstance(event, dict):
                continue
            if str(event.get("event") or "").strip() != "agent.tool.call":
                continue
            result = event.get("result") if isinstance(event.get("result"), dict) else {}
            if not _tool_result_requests_replan(result):
                continue
            tool_name = str(event.get("detail") or "").strip()
            failure_payload = {
                "event_type": "agent.tool.call",
                "tool_name": tool_name,
                "input_preview": (
                    event.get("input_preview")
                    if isinstance(event.get("input_preview"), dict)
                    else {}
                ),
                "result": result,
            }
            replan_event = planner_replan_timeline_event(
                decision,
                failure_payload,
                run_id=run_id,
            )
            if not replan_event:
                continue
            payload = (
                replan_event.get("payload")
                if isinstance(replan_event.get("payload"), dict)
                else {}
            )
            request_id = str(payload.get("request_id") or "").strip()
            if request_id and request_id in existing_request_ids:
                continue
            if request_id:
                existing_request_ids.add(request_id)
            timeline.append(replan_event)
            payload_dict = dict(payload)
            payloads.append(payload_dict)
            if run_id and self._append_run_event is not None:
                self._append_run_event(run_id, "agent.replan.requested", payload_dict)
        return payloads

    def _record_runtime_planner_task_progress_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        tool_timeline_start: int,
        run_id: str = "",
    ) -> None:
        plan = getattr(decision, "plan", None)
        if plan is None:
            return
        task_core = getattr(plan, "task_core", None)
        tool_plan = getattr(plan, "tool_plan", None)
        if task_core is None or tool_plan is None:
            return
        steps = list(getattr(tool_plan, "steps", []) or [])
        if not steps:
            return
        todo_by_step = {
            str(getattr(todo, "step_id", "") or "").strip(): todo
            for todo in list(getattr(task_core, "todos", []) or [])
            if str(getattr(todo, "step_id", "") or "").strip()
        }
        checkpoints_by_step: dict[str, list[Any]] = {}
        for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
            step_id = str(getattr(checkpoint, "after_step_id", "") or "").strip()
            if not step_id:
                continue
            checkpoints_by_step.setdefault(step_id, []).append(checkpoint)
        tool_events = [
            event
            for event in timeline[tool_timeline_start:]
            if isinstance(event, dict)
            and str(event.get("event") or "").strip()
            in {"agent.tool.call", "agent.tool.skipped"}
        ]
        event_index = 0
        core_id = str(getattr(task_core, "core_id", "") or "").strip()
        workspace = getattr(task_core, "workspace", None)
        workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
        plan_id = str(getattr(plan, "plan_id", "") or "").strip()
        decision_id = str(getattr(decision, "decision_id", "") or "").strip()
        for step in steps:
            tool_name = str(getattr(step, "tool_name", "") or "").strip()
            step_id = str(getattr(step, "step_id", "") or "").strip()
            if not tool_name or not step_id:
                continue
            tool_event: dict[str, Any] | None = None
            while event_index < len(tool_events):
                candidate = tool_events[event_index]
                event_index += 1
                if str(candidate.get("detail") or "").strip() == tool_name:
                    tool_event = candidate
                    break
            if tool_event is None:
                continue
            result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
            todo_status = _task_todo_status_for_tool_result(
                str(tool_event.get("event") or ""),
                result,
            )
            checkpoint_status = _task_checkpoint_status_for_todo_status(todo_status, result)
            source_event = {
                "event": str(tool_event.get("event") or ""),
                "detail": str(tool_event.get("detail") or ""),
            }
            base_payload = {
                "source": "runtime_planner",
                "core_id": core_id,
                "workspace_id": workspace_id,
                "decision_id": decision_id,
                "plan_id": plan_id,
                "step_id": step_id,
                "tool": tool_name,
                "source_event": source_event,
                "result_preview": _task_progress_result_preview(result),
            }
            todo = todo_by_step.get(step_id)
            if todo is not None:
                todo_payload = _snapshot_payload(todo)
                todo_payload["status"] = todo_status
                payload = {
                    **base_payload,
                    "todo_id": str(getattr(todo, "todo_id", "") or "").strip(),
                    "status": todo_status,
                    "previous_status": str(getattr(todo, "status", "") or "pending"),
                    "todo": todo_payload,
                }
                timeline.append(
                    self._timeline(
                        "agent.task.todo.updated",
                        str(getattr(todo, "title", "") or step_id),
                        **payload,
                    )
                )
                if run_id and self._append_run_event is not None:
                    self._append_run_event(run_id, "agent.task.todo.updated", payload)
            for checkpoint in checkpoints_by_step.get(step_id, []):
                checkpoint_payload = _snapshot_payload(checkpoint)
                checkpoint_payload["status"] = checkpoint_status
                payload = {
                    **base_payload,
                    "checkpoint_id": str(
                        getattr(checkpoint, "checkpoint_id", "") or ""
                    ).strip(),
                    "status": checkpoint_status,
                    "previous_status": str(
                        getattr(checkpoint, "status", "") or "planned"
                    ),
                    "checkpoint": checkpoint_payload,
                }
                timeline.append(
                    self._timeline(
                        "agent.task.checkpoint.updated",
                        str(getattr(checkpoint, "title", "") or step_id),
                        **payload,
                    )
                )
                if run_id and self._append_run_event is not None:
                    self._append_run_event(
                        run_id,
                        "agent.task.checkpoint.updated",
                        payload,
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

    def _record_desktop_permission_preflight(
        self,
        planned_tool_requests: list[dict[str, Any]],
        broker: Any,
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        payload = _desktop_permission_preflight_event_payload(
            planned_tool_requests,
            broker,
        )
        if not payload:
            return
        detail = str(payload.get("tool") or "desktop.permissions")
        timeline.append(
            self._timeline(
                "agent.desktop.permission_preflight",
                detail,
                **payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(
                run_id,
                "agent.desktop.permission_preflight",
                payload,
            )

    def _record_desktop_tool_policy_decisions(
        self,
        planned_tool_requests: list[dict[str, Any]],
        *,
        allowed_tools: list[str],
        agent: dict[str, Any],
        run_id: str = "",
    ) -> None:
        if not run_id or self._append_run_event is None:
            return
        allowed = [
            str(tool or "").strip()
            for tool in allowed_tools
            if str(tool or "").strip()
        ]
        policy_overlay = agent.get("_daily_desktop_policy_overlay") is True
        reason = "daily_desktop_policy_overlay" if policy_overlay else "agent_tool_policy"
        for request in planned_tool_requests:
            tool_name = str(request.get("tool") or "").strip()
            if not tool_name:
                continue
            payload = {
                "tool": tool_name,
                "status": "allowed",
                "decision": "allow",
                "source": str(request.get("source") or "daily_desktop_intent"),
                "reason": reason,
                "policy_scope": "daily_desktop",
                "policy_overlay": policy_overlay,
                "input_preview": request.get("input") if isinstance(request.get("input"), dict) else {},
                "allowed_tools": allowed,
            }
            planning_reason = str(
                request.get("planning_reason") or "clear_daily_desktop_intent"
            ).strip()
            if planning_reason:
                payload["planning_reason"] = planning_reason
            self._append_run_event(run_id, "agent.tool.policy_decision", payload)

    def _record_desktop_intent_approval_required(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        pending_approval: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str,
        source: str = "daily_desktop_intent",
        planning_reason: str = "",
    ) -> None:
        event_payload = {
            "tool": tool_name,
            "status": "approval_required",
            "source": str(source or "daily_desktop_intent"),
            "reason": "tool_policy_requires_approval",
            "input_preview": tool_input,
        }
        clean_planning_reason = str(planning_reason or "").strip()
        if clean_planning_reason:
            event_payload["planning_reason"] = clean_planning_reason
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
        presentation: str = "",
        source: str = "daily_desktop_intent",
        planning_reason: str = "",
    ) -> str:
        if planned_tool not in _DIRECT_DAILY_DESKTOP_TOOLS:
            return ""
        tool_event = self._latest_tool_call_event(timeline, planned_tool)
        if not tool_event:
            return ""
        result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
        if result.get("approval_required"):
            return ""
        result = _with_retry_recovery_action(planned_tool, planned_input, result)
        tool_event["result"] = result
        executed_input = (
            tool_event.get("input_preview")
            if isinstance(tool_event.get("input_preview"), dict)
            else planned_input
        )
        clean_presentation = str(presentation or "").strip()
        summary = self._daily_desktop_summary(
            planned_tool,
            executed_input,
            result,
            presentation=clean_presentation,
        )
        if not summary:
            return ""
        event_payload = {
            "tool": planned_tool,
            "source": str(source or "daily_desktop_intent"),
            "input_preview": executed_input,
            "result": result,
            "summary": summary,
        }
        clean_planning_reason = str(planning_reason or "").strip()
        if clean_planning_reason:
            event_payload["planning_reason"] = clean_planning_reason
        if clean_presentation:
            event_payload["presentation"] = clean_presentation
        timeline.append(
            self._timeline(
                "agent.desktop.intent_completed",
                planned_tool,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.desktop.intent_completed", event_payload)
        recovery_payload = _desktop_permission_recovery_event_payload(
            planned_tool,
            executed_input,
            result,
        )
        if recovery_payload:
            timeline.append(
                self._timeline(
                    "agent.desktop.permission_recovery",
                    planned_tool,
                    **recovery_payload,
                )
            )
            if run_id and self._append_run_event is not None:
                self._append_run_event(
                    run_id,
                    "agent.desktop.permission_recovery",
                    recovery_payload,
                )
        return summary

    def _direct_daily_desktop_sequence_result(
        self,
        planned_tool_requests: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        *,
        tool_timeline_start: int,
        run_id: str = "",
    ) -> str:
        tool_events = [
            event
            for event in timeline[tool_timeline_start:]
            if event.get("event") in {"agent.tool.call", "agent.tool.skipped"}
        ]
        event_index = 0
        completed_steps: list[dict[str, Any]] = []
        for planned_tool_request in planned_tool_requests:
            planned_tool = str(planned_tool_request.get("tool") or "")
            if planned_tool not in _DIRECT_DAILY_DESKTOP_TOOLS:
                return ""
            planned_input = planned_tool_request.get("input")
            if not isinstance(planned_input, dict):
                planned_input = {}
            tool_event: dict[str, Any] | None = None
            while event_index < len(tool_events):
                candidate = tool_events[event_index]
                event_index += 1
                if str(candidate.get("detail") or "") == planned_tool:
                    candidate_result = (
                        candidate.get("result") if isinstance(candidate.get("result"), dict) else {}
                    )
                    if candidate_result.get("approval_required"):
                        continue
                    tool_event = candidate
                    break
            if tool_event is None:
                return ""
            result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
            if result.get("approval_required"):
                return ""
            result = _with_retry_recovery_action(planned_tool, planned_input, result)
            tool_event["result"] = result
            executed_input = (
                tool_event.get("input_preview")
                if isinstance(tool_event.get("input_preview"), dict)
                else planned_input
            )
            presentation = str(planned_tool_request.get("presentation") or "").strip()
            summary = self._daily_desktop_summary(
                planned_tool,
                executed_input,
                result,
                presentation=presentation,
            )
            if not summary:
                return ""
            completed_step = {
                "tool": planned_tool,
                "input_preview": executed_input,
                "result": result,
                "summary": summary,
            }
            if presentation:
                completed_step["presentation"] = presentation
            completed_steps.append(completed_step)
        visible_steps = _visible_daily_desktop_completed_steps(completed_steps)
        summary_steps = _daily_desktop_sequence_summary_steps(visible_steps)
        summary = _combine_daily_desktop_summaries(
            [
                str(step.get("summary") or "")
                for step in summary_steps
                if isinstance(step, dict)
            ]
        )
        if not summary:
            return ""
        last_step = visible_steps[-1]
        completed_tools_steps = (
            visible_steps
            if any(
                isinstance(event.get("result"), dict)
                and event["result"].get("approval_required")
                for event in tool_events
            )
            else completed_steps
        )
        clean_source = str(
            (planned_tool_requests[0].get("source") if planned_tool_requests else "")
            or "daily_desktop_intent"
        )
        planning_reasons = {
            str(request.get("planning_reason") or "").strip()
            for request in planned_tool_requests
            if str(request.get("planning_reason") or "").strip()
        }
        event_payload = {
            "tool": str(last_step.get("tool") or ""),
            "tools": _planned_daily_desktop_tools(planned_tool_requests)
            or [str(step.get("tool") or "") for step in completed_tools_steps],
            "input_preview": (
                last_step.get("input_preview") if isinstance(last_step.get("input_preview"), dict) else {}
            ),
            "result": last_step.get("result") if isinstance(last_step.get("result"), dict) else {},
            "source": clean_source,
            "steps": completed_steps,
            "summary": summary,
        }
        if len(planning_reasons) == 1:
            event_payload["planning_reason"] = next(iter(planning_reasons))
        presentation = str(last_step.get("presentation") or "").strip()
        if presentation:
            event_payload["presentation"] = presentation
        timeline.append(
            self._timeline(
                "agent.desktop.intent_completed",
                str(last_step.get("tool") or ""),
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, "agent.desktop.intent_completed", event_payload)
        for step in completed_steps:
            recovery_payload = _desktop_permission_recovery_event_payload(
                str(step.get("tool") or ""),
                step.get("input_preview") if isinstance(step.get("input_preview"), dict) else {},
                step.get("result") if isinstance(step.get("result"), dict) else {},
            )
            if recovery_payload:
                timeline.append(
                    self._timeline(
                        "agent.desktop.permission_recovery",
                        str(step.get("tool") or ""),
                        **recovery_payload,
                    )
                )
                if run_id and self._append_run_event is not None:
                    self._append_run_event(
                        run_id,
                        "agent.desktop.permission_recovery",
                        recovery_payload,
                    )
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
        *,
        presentation: str = "",
    ) -> str:
        result_summary = str(result.get("summary") or "").strip()
        if result.get("ok"):
            if tool_name in {"app.open", "desktop.open_app"}:
                app_name = _payload_text(result, planned_input, "app_name")
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if data.get("launch_verified") is False and app_name:
                    return f"已向 macOS 发送打开{_display_target_name(app_name, '的请求')}，但未能确认它已启动。"
                return f"已打开{_display_target_name(app_name)}。" if app_name else (result_summary or "已打开应用。")
            if tool_name in {"app.focus", "desktop.focus_app"}:
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已切换到{_display_target_name(app_name)}。" if app_name else (result_summary or "已切换到应用。")
            if tool_name == "app.focus_window":
                app_name = _payload_text(result, planned_input, "app_name")
                title = _payload_text(result, planned_input, "window_title") or _payload_text(
                    result,
                    planned_input,
                    "title_contains",
                )
                if app_name and title:
                    return f"已切换到{_display_target_name(app_name, f'的 {title} 窗口')}。"
                return result_summary or "已切换到指定窗口。"
            if tool_name in {"app.open_and_safe_type_text", "app.focus_and_safe_type_text"}:
                app_name = _payload_text(result, planned_input, "app_name")
                text = _payload_text(result, planned_input, "text")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                if text:
                    detail = f"并输入文字（{len(text)} 个字符）"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并输入文字")
                return result_summary or f"已{action}{target or '并输入文字'}。"
            if tool_name in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                shortcut = _safe_shortcut_summary(result, planned_input)
                if shortcut:
                    detail = f"并{shortcut.removeprefix('已').removesuffix('。')}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并执行快捷动作")
                return result_summary or f"已{action}{target or '并执行快捷动作'}。"
            if tool_name in {"app.open_and_safe_key", "app.focus_and_safe_key"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                safe_key = _safe_key_summary(result, planned_input)
                if safe_key:
                    detail = f"并{safe_key.removeprefix('已').removesuffix('。')}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并按前台导航键")
                return result_summary or f"已{action}{target or '并按前台导航键'}。"
            if tool_name in {"app.open_and_hotkey", "app.focus_and_hotkey"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                hotkey = _hotkey_text(result, planned_input)
                if hotkey:
                    detail = f"并发送快捷键：{hotkey}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并发送快捷键")
                return result_summary or f"已{action}{target or '并发送快捷键'}。"
            if tool_name in {"app.open_and_safe_scroll", "app.focus_and_safe_scroll"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                safe_scroll = _safe_scroll_summary(result, planned_input)
                if safe_scroll:
                    detail = f"并{safe_scroll.removeprefix('已').removesuffix('。')}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并滚动前台界面")
                return result_summary or f"已{action}{target or '并滚动前台界面'}。"
            if tool_name in {"app.open_and_safe_click", "app.focus_and_safe_click"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                click = _click_text(result, planned_input)
                if click:
                    detail = f"并点击前台位置：{click}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并点击前台界面")
                return result_summary or f"已{action}{target or '并点击前台界面'}。"
            if tool_name in {"app.open_and_click_ui_element", "app.focus_and_click_ui_element"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                click_ui = _click_ui_element_summary(result, planned_input)
                if click_ui:
                    detail = f"并{click_ui.removeprefix('已').removesuffix('。')}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并点击前台控件")
                return result_summary or f"已{action}{target or '并点击前台控件'}。"
            if tool_name in {"app.open_and_type_into_ui_element", "app.focus_and_type_into_ui_element"}:
                app_name = _payload_text(result, planned_input, "app_name")
                action = "打开" if tool_name.startswith("app.open") else "切到"
                type_into = _type_into_ui_element_summary(result, planned_input)
                if type_into:
                    detail = f"并{type_into.removeprefix('已').removesuffix('。')}"
                    target = _display_target_name(app_name, detail)
                    return f"已{action}{target or detail}。"
                target = _display_target_name(app_name, "并填写前台控件")
                return result_summary or f"已{action}{target or '并填写前台控件'}。"
            if tool_name == "app.show":
                app_name = _payload_text(result, planned_input, "app_name")
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if data.get("show_status") == "launched" and app_name:
                    return f"已打开并显示{_display_target_name(app_name)}。"
                return f"已显示{_display_target_name(app_name)}。" if app_name else (result_summary or "已显示应用。")
            if tool_name == "app.hide":
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已隐藏{_display_target_name(app_name)}。" if app_name else (result_summary or "已隐藏应用。")
            if tool_name == "app.minimize":
                app_name = _payload_text(result, planned_input, "app_name")
                return f"已最小化{_display_target_name(app_name)}。" if app_name else (result_summary or "已最小化应用。")
            if tool_name == "app.quit":
                app_name = _payload_text(result, planned_input, "app_name")
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if data.get("running") is True and app_name:
                    return f"已向{_display_target_name(app_name, '发送退出请求')}，但它可能仍在运行。"
                return f"已退出{_display_target_name(app_name)}。" if app_name else (result_summary or "已退出应用。")
            if tool_name == "media.apple_music_play":
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                track = str(data.get("track") or "").strip()
                artist = str(data.get("artist") or "").strip()
                query = _payload_text(result, planned_input, "query")
                if track:
                    return f"已在 Apple Music 播放：{track}{f' - {artist}' if artist else ''}。"
                return f"已尝试在 Apple Music 播放：{query}。" if query else (result_summary or "已尝试播放。")
            if tool_name == "media.apple_music_status":
                return _apple_music_status_summary(result) or result_summary or "已读取 Apple Music 播放状态。"
            if tool_name == "media.apple_music_open_and_play":
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                track = str(data.get("track") or "").strip()
                artist = str(data.get("artist") or "").strip()
                track_text = f"当前：{track}{f' - {artist}' if artist else ''}。" if track else ""
                if data.get("playback_state_unverified"):
                    return f"已打开 Apple Music，并用媒体键尝试开始播放。{track_text}"
                return f"已打开 Apple Music 并开始播放。{track_text}"
            if tool_name == "media.apple_music_control":
                return _apple_music_control_summary(result, planned_input) or result_summary or "已控制 Apple Music。"
            if tool_name == "media.music_app_open_and_play":
                return _music_app_open_and_play_summary(result, planned_input) or result_summary or "已尝试播放音乐。"
            if tool_name == "media.music_app_control":
                return _music_app_control_summary(result, planned_input) or result_summary or "已尝试控制音乐应用。"
            if tool_name == "media.system_control":
                return _system_media_control_summary(result, planned_input) or result_summary or "已尝试控制当前媒体。"
            if tool_name == "system.settings_open":
                return _system_settings_open_summary(result, planned_input) or result_summary or "已打开系统设置。"
            if tool_name == "system.volume":
                return _system_volume_summary(result, planned_input) or result_summary or "已处理系统音量。"
            if tool_name == "system.brightness":
                return _system_brightness_summary(result, planned_input) or result_summary or "已调整屏幕亮度。"
            if tool_name == "system.display_sleep":
                return "已让显示器睡眠。"
            if tool_name == "system.screen_saver_start":
                return "已启动屏幕保护程序。"
            if tool_name == "clipboard.write":
                return _clipboard_write_summary(result, planned_input) or result_summary or "已写入剪贴板。"
            if tool_name == "clipboard.read":
                return _clipboard_read_summary(result) or result_summary or "已读取剪贴板。"
            if tool_name == "notes.create":
                return _notes_create_summary(result, planned_input) or result_summary or "已创建备忘录。"
            if tool_name == "artifact.write":
                path = str(result.get("path") or planned_input.get("path") or "").strip()
                return f"已生成文件：{path}。" if path else (result_summary or "已写入 Artifact。")
            if tool_name == "reminders.create":
                return _reminders_create_summary(result, planned_input) or result_summary or "已创建提醒事项。"
            if tool_name == "calendar.create_event":
                return _calendar_create_event_summary(result, planned_input) or result_summary or "已创建日历事件。"
            if tool_name == "screen.capture":
                return result_summary or "已截取当前屏幕。"
            if tool_name == "desktop.permissions":
                return _desktop_permissions_summary(result) or result_summary or "已检查桌面权限。"
            if tool_name == "desktop.active_window":
                return _active_window_summary(result) or result_summary or "已读取当前前台窗口。"
            if tool_name == "desktop.list_apps":
                return _installed_apps_summary(result) or result_summary or "已发现已安装应用。"
            if tool_name == "desktop.running_apps":
                return _running_apps_summary(result) or result_summary or "已读取运行中的应用。"
            if tool_name == "desktop.windows":
                return _windows_summary(result, planned_input) or result_summary or "已读取窗口列表。"
            if tool_name == "desktop.ui_elements":
                return _ui_elements_summary(result) or result_summary or "已读取当前界面控件。"
            if tool_name == "desktop.inspect_app":
                return _inspect_app_result_summary(result) or result_summary or "已检查应用。"
            if tool_name == "app.status":
                return _app_status_summary(result, planned_input) or result_summary or "已检查应用状态。"
            if tool_name == "desktop.reveal_path":
                path = _desktop_path_summary_path(result, planned_input)
                return f"已在 Finder 中显示：{path}。" if path else (result_summary or "已在 Finder 中显示。")
            if tool_name == "desktop.open_path":
                return _desktop_open_path_summary(result, planned_input) or result_summary or "已打开本地路径。"
            if tool_name == "desktop.open_path_with_app":
                return (
                    _desktop_open_path_with_app_summary(result, planned_input)
                    or result_summary
                    or "已用应用打开本地路径。"
                )
            if tool_name == "desktop.hide_app":
                return "已隐藏当前应用。"
            if tool_name == "desktop.show_all_apps":
                return "已显示所有隐藏应用。"
            if tool_name == "desktop.minimize_window":
                return "已最小化当前窗口。"
            if tool_name == "desktop.close_window":
                return "已关闭当前窗口。"
            if tool_name == "desktop.quit_app":
                return "已请求退出当前应用。"
            if tool_name == "data.analyze":
                return _data_analyze_summary(result, planned_input) or result_summary or "已分析数据。"
            if tool_name == "terminal.run":
                return _terminal_run_summary(result, planned_input)
            if tool_name == "browser.open_url":
                url = _payload_text(result, planned_input, "url")
                if result.get("fallback_used") and result.get("fallback") == "system_browser":
                    return f"已用系统浏览器打开网页：{url}。" if url else (result_summary or "已用系统浏览器打开网页。")
                return f"已打开网页：{url}。" if url else (result_summary or "已打开网页。")
            if tool_name == "browser.open_url_and_extract_text":
                if result.get("ok") is True:
                    if presentation == "summary":
                        return _browser_text_digest_summary(result)
                    return _browser_text_summary(result)
                return result_summary or _browser_text_summary(result)
            if tool_name == "browser.open_url_and_screenshot":
                if result.get("ok") is True:
                    return "已打开网页并截取当前网页。"
                return result_summary or "已打开网页，但没能截取当前网页。"
            if tool_name == "browser.current_page":
                if result.get("ok") is True:
                    return _browser_page_summary(result)
                return result_summary or _browser_page_summary(result)
            if tool_name == "browser.click":
                if result.get("ok") is True:
                    return _browser_click_summary(result, planned_input)
                return result_summary or "没能点击网页元素。"
            if tool_name == "browser.type_text":
                if result.get("ok") is True:
                    return _browser_type_text_summary(result, planned_input)
                return result_summary or "没能填写网页输入。"
            if tool_name == "browser.extract_text":
                if result.get("ok") is True:
                    if presentation == "summary":
                        return _browser_text_digest_summary(result)
                    return _browser_text_summary(result)
                return result_summary or _browser_text_summary(result)
            if tool_name == "browser.screenshot":
                if result.get("ok") is True:
                    return "已截取当前网页。"
                return result_summary or "已截取当前网页。"
            if tool_name == "desktop.safe_shortcut":
                return _safe_shortcut_summary(result, planned_input) or result_summary or "已执行快捷动作。"
            if tool_name == "desktop.safe_key":
                return _safe_key_summary(result, planned_input) or result_summary or "已按前台导航键。"
            if tool_name == "desktop.safe_type_text":
                text = _payload_text(result, planned_input, "text")
                if text:
                    return f"已向前台输入文字（{len(text)} 个字符）。"
                return result_summary or "已向前台输入文字。"
            if tool_name == "desktop.safe_click":
                click = _click_text(result, planned_input)
                return f"已点击前台位置：{click}。" if click else (result_summary or "已点击前台界面。")
            if tool_name == "desktop.safe_scroll":
                return _safe_scroll_summary(result, planned_input) or result_summary or "已滚动前台界面。"
            if tool_name == "desktop.search_submit":
                return "已提交前台搜索。" if result.get("ok") is True else (result_summary or "没能提交前台搜索。")
            if tool_name == "desktop.click_ui_element":
                return _click_ui_element_summary(result, planned_input) or result_summary or "已点击前台控件。"
            if tool_name == "desktop.type_into_ui_element":
                return _type_into_ui_element_summary(result, planned_input) or result_summary or "已填写前台控件。"
            if tool_name == "desktop.hotkey":
                hotkey = _hotkey_text(result, planned_input)
                return f"已发送快捷键：{hotkey}。" if hotkey else (result_summary or "已发送快捷键。")
            if tool_name == "desktop.submit_foreground":
                action = _payload_text(result, planned_input, "submit_action") or _payload_text(
                    result,
                    planned_input,
                    "action",
                )
                return {
                    "send": "已确认发送前台内容。",
                    "submit": "已确认提交前台内容。",
                    "confirm": "已确认前台操作。",
                }.get(action, result_summary or "已确认前台提交动作。")
            if tool_name == "desktop.type_text":
                text = _payload_text(result, planned_input, "text")
                if text:
                    return f"已向前台输入文字（{len(text)} 个字符）。"
                return result_summary or "已向前台输入文字。"
            if tool_name == "desktop.click":
                click = _click_text(result, planned_input)
                return f"已点击前台位置：{click}。" if click else (result_summary or "已点击前台界面。")
            return result_summary or "已执行桌面操作。"

        error = str(result.get("error") or result_summary or "工具返回失败").strip()
        permission_targets = result.get("permission_targets")
        fallback = result.get("fallback_result") if isinstance(result.get("fallback_result"), dict) else {}
        if result.get("blocked_by_runtime_readiness"):
            conditions = _text_list(result.get("blocking_conditions")) or ([error] if error else [])
            condition_text = ", ".join(conditions)
            source_summary = str(result.get("source_summary") or "").strip()
            detail = (
                f"前置检查未确认目标应用可接收前台输入：{condition_text}。"
                if condition_text
                else "前置检查未确认目标应用可接收前台输入。"
            )
            if source_summary:
                detail = f"{detail}{source_summary}。"
            return _append_recovery_action_summary(f"桌面操作已暂停：{detail}", result)
        if tool_name == "app.open" and str(result.get("error_code") or "") == "app_not_found":
            app_name = _payload_text(result, planned_input, "app_name")
            target = _display_target_name(app_name)
            diagnostics = _permission_diagnostics(result)
            return _append_recovery_action_summary(
                f"已尝试启动{target}，但 macOS 没找到这个应用。{diagnostics}".strip(),
                result,
            )
        if tool_name in {"browser.open_url_and_extract_text", "browser.open_url_and_screenshot"}:
            opened = fallback.get("open") if isinstance(fallback.get("open"), dict) else {}
            if opened.get("ok"):
                targets = ", ".join(str(item) for item in permission_targets or [] if str(item))
                diagnostics = _permission_diagnostics(result)
                suffix = f" 缺少权限：{targets}。" if targets else ""
                partial_summary = (
                    "已打开网页，但没能读取网页文本。"
                    if tool_name == "browser.open_url_and_extract_text"
                    else "已打开网页，但没能截取当前网页。"
                )
                return _append_recovery_action_summary(
                    f"{partial_summary}{suffix}{diagnostics}".strip(),
                    result,
                )
        if tool_name in _APP_FOREGROUND_ACTION_TOOLS:
            foreground_summary = _app_foreground_action_failed_summary(
                tool_name,
                planned_input,
                result,
            )
            if foreground_summary:
                return foreground_summary
        if result.get("permission_error") or permission_targets:
            targets = ", ".join(str(item) for item in permission_targets or [] if str(item))
            diagnostics = _permission_diagnostics(result)
            suffix = f" 缺少权限：{targets}。" if targets else ""
            return _append_recovery_action_summary(
                f"桌面操作未完成：{_sentence(error)}{suffix}{diagnostics}".strip(),
                result,
            )
        if tool_name == "media.apple_music_play" and fallback.get("ok"):
            query = _payload_text(result, planned_input, "query")
            if str(fallback.get("action") or "") == "media.apple_music.search":
                return (
                    f"没能直接播放 {query}，但已打开 Apple Music 搜索。"
                    if query
                    else "没能直接播放，但已打开 Apple Music 搜索。"
                )
            return (
                f"没能直接播放 {query}，但已打开 Apple Music。"
                if query
                else "没能直接播放，但已打开 Apple Music。"
            )
        if tool_name == "media.apple_music_open_and_play":
            control = fallback.get("control") if isinstance(fallback.get("control"), dict) else {}
            opened = fallback.get("open") if isinstance(fallback.get("open"), dict) else {}
            if control.get("fallback_used") or opened.get("ok"):
                return "已打开 Apple Music，但没能直接开始播放。"
        if tool_name == "media.apple_music_control" and fallback.get("ok"):
            action = _payload_text(result, planned_input, "action")
            label = _apple_music_control_label(action)
            return f"没能直接{label}，但已打开 Apple Music。" if label else "没能直接控制，但已打开 Apple Music。"
        if tool_name == "terminal.run":
            return _terminal_run_summary(result, planned_input)
        diagnostics = _permission_diagnostics(result)
        return f"桌面操作未完成：{_sentence(error)}{diagnostics}".strip()

    def _direct_existing_daily_desktop_result(
        self,
        agent: dict[str, Any],
        timeline: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> str:
        sequence_result = self._direct_existing_daily_desktop_sequence_result(
            timeline,
            run_id=run_id,
        )
        if sequence_result:
            return sequence_result
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

    def _direct_existing_daily_desktop_sequence_result(
        self,
        timeline: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> str:
        sequence = self._latest_uncompleted_daily_desktop_sequence(timeline)
        if sequence is None:
            return ""
        requests = _visible_daily_desktop_completed_steps(sequence["requests"])
        if not requests:
            requests = sequence["requests"]
        return self._direct_daily_desktop_sequence_result(
            requests,
            timeline,
            tool_timeline_start=sequence["start_index"] + 1,
            run_id=run_id,
        )

    @staticmethod
    def _latest_uncompleted_daily_desktop_sequence(
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        requests: list[dict[str, Any]] = []
        start_index = -1
        for index, event in enumerate(timeline):
            event_type = str(event.get("event") or "").strip()
            if event_type == "agent.desktop.intent_completed":
                requests = []
                start_index = -1
                continue
            if event_type != "agent.desktop.intent_planned":
                continue
            source = str(event.get("source") or "").strip()
            if source not in _DAILY_DESKTOP_PLAN_SOURCES:
                continue
            tool_name = str(event.get("tool") or event.get("detail") or "").strip()
            if not tool_name:
                continue
            input_preview = event.get("input_preview")
            request = {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": dict(input_preview) if isinstance(input_preview, dict) else {},
                "source": source,
            }
            planning_reason = str(event.get("planning_reason") or "").strip()
            if planning_reason:
                request["planning_reason"] = planning_reason
            if start_index < 0:
                start_index = index
            requests.append(request)
        if start_index < 0 or len(requests) < 2:
            return None
        return {"start_index": start_index, "requests": requests}

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
            if str(event.get("source") or "").strip() not in _DAILY_DESKTOP_PLAN_SOURCES:
                continue
            input_preview = event.get("input_preview")
            return dict(input_preview) if isinstance(input_preview, dict) else {}
        return None

    def _latest_user_intent_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if str(message.get("role") or "") != "user":
                continue
            content = self._message_visible_content_text(message).strip()
            if (
                content.startswith("Tool result for ")
                or content.startswith("Desktop intent for ")
                or content.startswith("Runtime follow-up context:")
            ):
                continue
            if content:
                return content
        return ""

    def _ensure_runtime_system_message(
        self,
        messages: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> None:
        runtime_message = self._system_message(
            allowed_tools,
            planner_context=self._latest_user_intent_text(messages),
        )
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
            self._system_message(allowed_tools, planner_context=context),
            {"role": "user", "content": context},
        ]

    def _system_message(
        self,
        allowed_tools: list[str],
        *,
        planner_context: str = "",
    ) -> dict[str, Any]:
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
            "desktop.permissions, desktop.active_window, desktop.list_apps, desktop.running_apps, desktop.windows, desktop.ui_elements, app.status, app.open/app.focus/app.focus_window/app.open_and_safe_type_text/app.focus_and_safe_type_text/app.open_and_safe_shortcut/app.focus_and_safe_shortcut/app.open_and_safe_key/app.focus_and_safe_key/app.open_and_hotkey/app.focus_and_hotkey/app.open_and_safe_scroll/app.focus_and_safe_scroll/app.open_and_safe_click/app.focus_and_safe_click/app.open_and_click_ui_element/app.focus_and_click_ui_element/app.open_and_type_into_ui_element/app.focus_and_type_into_ui_element/app.show/app.hide/app.minimize/app.quit, desktop.reveal_path, desktop.open_path, media.apple_music_play, "
            "media.apple_music_open_and_play, media.apple_music_control, media.music_app_open_and_play, media.music_app_control, media.system_control, system.settings_open, system.volume, system.brightness, system.display_sleep, system.screen_saver_start, clipboard.write, clipboard.read, notes.create, reminders.create, calendar.create_event, desktop.safe_shortcut, desktop.safe_key, desktop.safe_type_text, desktop.search_submit, desktop.safe_click, desktop.safe_scroll, desktop.click_ui_element, desktop.type_into_ui_element, desktop.hide_app, desktop.show_all_apps, desktop.minimize_window, desktop.close_window, desktop.quit_app, desktop.click, desktop.hotkey, desktop.submit_foreground, and desktop.type_text "
            "when they are allowed. When the user names an app or discovery resolves an app, prefer app-scoped "
            "foreground tools such as app.open_and_click_ui_element, app.focus_and_click_ui_element, "
            "app.open_and_type_into_ui_element, app.focus_and_type_into_ui_element, app.*_and_safe_shortcut, "
            "app.*_and_safe_key, app.*_and_safe_scroll, and app.*_and_safe_click so Runtime can bind the action "
            "to the target app. Use bare desktop.click_ui_element, desktop.type_into_ui_element, desktop.safe_* "
            "foreground tools only for explicit current-foreground requests or when the app-scoped tool is not "
            "available after discovery/focus. For explicit media requests, treat the media app as a discoverable "
            "desktop resource instead of an Apple Music-only branch: resolve named or uncertain media apps "
            "through desktop.list_apps when available, open or focus the app, search/type the requested query "
            "with app/desktop tools, submit, and verify with UI/window observations. Do not default song search "
            "or playback queries to media.apple_music_play when generic app discovery/search tools are allowed; "
            "use media.apple_music_play, media.apple_music_open_and_play, media.apple_music_control, "
            "media.music_app_open_and_play, media.music_app_control, or media.system_control only as allowed "
            "runtime media execution/fallback tools. Map named app pause/resume/next/previous commands to "
            "media.music_app_control or media.apple_music_control when direct control is requested; map generic "
            "current media pause/resume/next/previous commands to media.system_control; map macOS System Settings pane or permission page open requests to system.settings_open; map volume status/set/up/down/mute/unmute "
            "commands to system.volume; map explicit relative brightness up/down commands to system.brightness; map explicit display sleep or turn-off-screen commands to system.display_sleep; map explicit start-screen-saver commands to system.screen_saver_start; map explicit 'copy/write to clipboard' requests to "
            "clipboard.write without reading clipboard contents; map explicit clipboard content read/status questions to clipboard.read; map explicit selected text read requests to desktop.safe_shortcut(copy) followed by clipboard.read; map explicit create/new note requests with user-provided body text to notes.create; map explicit reminder creation requests with a clear title to reminders.create, adding due_at only when the local date/time is deterministic; map explicit calendar event creation requests with a clear title and deterministic local start time to calendar.create_event; map screen capture requests to "
            "screen.capture, and current or foreground window questions to desktop.active_window "
            "before answering; map installed/available app discovery or uncertain app names to desktop.list_apps before app.open; map running/open app list questions to desktop.running_apps; "
            "map open window list questions to desktop.windows; "
            "map explicit current-page reading/extraction requests to browser.extract_text; "
            "map foreground UI control/button/input field list questions to desktop.ui_elements; "
            "map explicit foreground UI control/button clicks by visible label to desktop.click_ui_element; "
            "map explicit foreground text input by visible input field label to desktop.type_into_ui_element; "
            "map single app running/open status questions to app.status; "
            "map explicit app window focus requests with a title substring to app.focus_window; "
            "map Chrome/Edge/Brave downloads, bookmarks, and extensions page requests to app open/focus address bar, desktop.safe_type_text with the whitelisted internal URL, then desktop.search_submit; "
            "map common whitelisted foreground shortcuts such as copy/paste/copy current page link/select all/undo/redo/find/focus address bar/new tab/new private window/close tab/next tab/previous tab/next window/previous window/app switching/hide other apps/toggle current-window full screen/Mission Control/Application Windows/Spotlight/Emoji picker/screenshot selection/screenshot or recording toolbar/Lock Screen/Force Quit dialog/new window/new document/new note/new reminder/new event/refresh/bookmark page/history/DevTools/page zoom/browser back/browser forward/reopen closed tab to desktop.safe_shortcut; "
            "map Finder or app open/focus followed by new-folder, new-document, new-message, new-reminder, new-event, "
            "rename, info, parent-folder, command-palette, preferences, or similar whitelisted app shortcuts to "
            "app.open_and_safe_shortcut or app.focus_and_safe_shortcut when app-scoped tools are allowed; use "
            "app.open/app.focus followed by desktop.safe_shortcut only as a compatibility fallback. "
            "map app open/focus followed by explicit safe navigation keys, scroll, single-click coordinates, "
            "visible-label clicks, or visible-field typing to app.*_and_safe_key, app.*_and_safe_scroll, "
            "app.*_and_safe_click, app.*_and_click_ui_element, or app.*_and_type_into_ui_element when available; "
            "fall back to app.open/app.focus followed by desktop.safe_key, desktop.safe_scroll, desktop.safe_click, "
            "desktop.click_ui_element, or desktop.type_into_ui_element only when app-scoped tools are unavailable. "
            "map explicit foreground navigation keys such as Escape, Tab, Shift+Tab, arrow keys, Home, End, Page Up, and Page Down to desktop.safe_key; "
            "map explicit user-provided foreground typing requests to desktop.safe_type_text; "
            "map explicit foreground search/find query submission to desktop.search_submit; "
            "map explicit user-provided single-click coordinates to desktop.safe_click; "
            "map explicit current foreground scroll/page up/page down requests to desktop.safe_scroll; "
            "when the user explicitly chains multiple low-risk desktop actions, execute them in order and let Runtime pause for approval if a later action requires it; "
            "map explicit named app show/unhide/restore requests to app.show, named app hide requests to app.hide, named app minimize requests to app.minimize, and app quit/close/exit requests to app.quit; "
            "map desktop permission diagnostics and 'why can't you control/open/click/play' "
            "questions to desktop.permissions; "
            "map 'show/reveal in Finder' requests to desktop.reveal_path and safe local "
            "file or folder open requests to desktop.open_path. "
            "Map explicit current/foreground app hide requests to desktop.hide_app. "
            "Map explicit show all hidden apps requests to desktop.show_all_apps. "
            "Map explicit current/foreground window minimize requests to desktop.minimize_window. "
            "Map explicit current/foreground window close requests to desktop.close_window. "
            "Map explicit current/foreground app quit/close/exit requests to desktop.quit_app. "
            "Map explicit foreground message send, form submit, and confirmation requests to desktop.submit_foreground; it is high-risk and Runtime must show approval before pressing Return. "
            "For browser or web-page requests, prefer structured browser tools such as "
            "browser.open_url, browser.open_url_and_extract_text, browser.open_url_and_screenshot, "
            "browser.current_page, browser.click, browser.type_text, browser.extract_text, "
            "and browser.screenshot when they are allowed. "
            "When browser.click has no Chrome CDP, use screen observation and explicit "
            "fallback_x/fallback_y coordinates instead of guessing selector positions. "
            "Do not replace these structured desktop or browser actions with terminal.run. "
            "If a desktop or browser permission is missing, explain the exact missing permission "
            "and continue with the safest fallback. "
            if any(tool in allowed_tools for tool in DAILY_DESKTOP_TOOL_NAMES)
            or any(tool in allowed_tools for tool in DAILY_BROWSER_TOOL_NAMES)
            else ""
        )
        has_tools = bool(allowed_tools)
        runtime_manual = f"{YACHIYO_RUNTIME_OPERATING_MANUAL} " if has_tools else ""
        tool_call_guidance = (
            "Prefer native tool_calls when available. "
            "If the model endpoint does not support tool_calls and a controlled tool is needed, respond as JSON "
            "{\"action\":\"tool\",\"tool\":\"workspace.list\",\"input\":{}}. "
            "Do not request tools that are not listed as allowed. "
            if has_tools
            else "No tools are allowed for this run; answer directly without requesting tools. "
        )
        workspace_guidance = (
            "Workspace tools only accept paths relative to the configured Default Workdir. Never pass absolute "
            "paths to workspace tools. If a required target is outside that workspace and terminal.run is "
            "allowed, use terminal.run instead. A failed workspace tool call is recoverable: follow its hint "
            "or switch tools instead of stopping or retrying the same invalid path. "
            if has_tools
            else ""
        )
        system_prompt = (
            "You are running inside Oha-Yachiyo Agent Runtime. "
            "Follow the Agent functional instructions, persona prompt, user goal, and exact output requests. "
            "If those instructions require an exact phrase or format, return exactly that final output. "
            "Return concise final output unless the Agent instructions require otherwise. "
            f"{runtime_manual}"
            f"{self._operating_doctrine}\n"
            f"{tool_call_guidance}"
            "Do not request a tool solely because of the output contract; use tools only when the user goal "
            "or an explicit deliverable requires them. "
            f"{memory_tool_guidance}"
            f"{future_task_guidance}"
            f"{desktop_tool_guidance}"
            "If the user asks not to create, save, write, or modify files, provide the content inline and do "
            "not request file-writing tools. If the user asks not to run or execute commands, do not request "
            "command-execution tools. "
            f"{workspace_guidance}"
            f"{self._runtime_planner_guidance(planner_context, allowed_tools)}"
            f"Request at most one high-risk tool per turn.\n\nAllowed tools: {allowed_tool_text}"
        )
        return {"role": "system", "content": system_prompt}

    @staticmethod
    def _runtime_planner_guidance(
        planner_context: str,
        allowed_tools: list[str],
    ) -> str:
        clean_context = str(planner_context or "").strip()
        if not clean_context:
            return ""
        try:
            from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner
        except Exception:
            return ""
        try:
            decision = RuntimePlanner().decision(
                clean_context,
                allowed_tools=allowed_tools,
            )
        except Exception:
            return ""
        if decision.selected_intent.kind == "general":
            return ""
        steps = list(decision.plan.tool_plan.steps)
        tool_path = [
            str(step.tool_name or step.capability_id or "").strip()
            for step in steps
            if str(step.tool_name or step.capability_id or "").strip()
        ]
        if not tool_path:
            return ""
        intent_kind = str(decision.selected_intent.kind or "").strip()
        missing = ", ".join(decision.plan.tool_plan.missing_capabilities) or "none"
        outputs = ", ".join(decision.selected_intent.expected_outputs) or "unspecified"
        artifacts = ", ".join(decision.plan.tool_plan.artifacts_expected) or "none"
        route_to_studio = "yes" if decision.plan.route_to_studio else "no"
        studio_handoff_guidance = ""
        if intent_kind in {"workflow_orchestration", "multi_agent"}:
            studio_surface = (
                "Workflow"
                if intent_kind == "workflow_orchestration"
                else "GroupRun"
            )
            studio_handoff_guidance = (
                f"Studio orchestration handoff: this is an Agent Studio {studio_surface} plan, "
                "not a normal model-only recipe. Preserve the planner intent, target, approvals, "
                "artifacts, and timeline context; do not claim the workflow or group run completed "
                "unless Runtime or Agent Studio returns a concrete run snapshot/run id. "
            )
        step_guidance = []
        for index, step in enumerate(steps, start=1):
            tool_or_capability = str(step.tool_name or step.capability_id or "").strip()
            if not tool_or_capability:
                continue
            approval = "approval required" if step.approval_required else "approval not preflagged"
            action = str(getattr(step, "action", "") or "").strip()
            action_text = f"action={action}; " if action else ""
            reason = str(step.reason or "").strip()
            reason_text = f"; reason={reason}" if reason else ""
            step_guidance.append(
                f"{index}. {step.title}: {tool_or_capability} "
                f"({action_text}capability={step.capability_id}; status={step.status}; "
                f"risk={step.risk_level}; {approval}{reason_text})"
            )
        steps_text = " ".join(step_guidance)
        return (
            "Runtime planner guidance: "
            f"selected intent={decision.selected_intent.kind}; "
            f"expected outputs={outputs}; "
            f"planned tool path={' -> '.join(tool_path)}; "
            f"missing required capabilities={missing}; "
            f"artifact expected={artifacts}; "
            f"route to Studio={route_to_studio}. "
            f"Plan steps: {steps_text}. "
            f"{studio_handoff_guidance}"
            "Follow the planned tool path in order when the named tools are allowed; do not replace app-scoped "
            "app.*_and_* foreground tools with a looser app.open/app.focus plus desktop.* sequence unless the "
            "app-scoped tool is unavailable. "
            "Use available tools to execute the request when the plan names an allowed tool; do not provide "
            "only manual instructions unless required capabilities are missing, user constraints forbid tools, "
            "or policy blocks execution. If a required step is unavailable, explain the missing capability "
            "instead of fabricating execution. Existing tool policy and approval gates still apply. "
        )


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


def _click_ui_element_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    label = str(data.get("matched_label") or data.get("target") or planned_input.get("target") or "").strip()
    point = _click_text(result, planned_input)
    if label and point:
        return f"已点击前台控件：{label}（{point}）。"
    if label:
        return f"已点击前台控件：{label}。"
    if point:
        return f"已点击前台控件位置：{point}。"
    return ""


def _type_into_ui_element_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    label = str(data.get("matched_label") or data.get("target") or planned_input.get("target") or "").strip()
    count = data.get("character_count")
    if not isinstance(count, int):
        text = str(planned_input.get("text") or "").strip()
        count = len(text) if text else 0
    count_text = f"（{count} 个字符）" if count else ""
    if label:
        return f"已在前台控件 {label} 输入文字{count_text}。"
    if count_text:
        return f"已在前台控件输入文字{count_text}。"
    return ""


def _app_foreground_action_failed_summary(
    tool_name: str,
    planned_input: dict[str, Any],
    result: dict[str, Any],
) -> str:
    fallback = result.get("fallback_result") if isinstance(result.get("fallback_result"), dict) else {}
    setup = fallback.get("focus") if isinstance(fallback.get("focus"), dict) else {}
    if not setup.get("ok"):
        return ""
    app_name = _payload_text(result, planned_input, "app_name")
    action = "打开" if tool_name.startswith("app.open") else "切到"
    target = _display_target_name(app_name)
    failed_action = _app_foreground_action_phrase(tool_name, result, planned_input)
    targets = ", ".join(str(item) for item in result.get("permission_targets") or [] if str(item))
    diagnostics = _permission_diagnostics(result)
    suffix = f" 缺少权限：{targets}。" if targets else ""
    return _append_recovery_action_summary(
        f"已{action}{target}，但没能{failed_action}。{suffix}{diagnostics}".strip(),
        result,
    )


def _app_foreground_action_phrase(
    tool_name: str,
    result: dict[str, Any],
    planned_input: dict[str, Any],
) -> str:
    if tool_name.endswith("safe_type_text"):
        return "输入文字"
    if tool_name.endswith("safe_shortcut"):
        return _action_phrase_from_done_summary(
            _safe_shortcut_summary(result, planned_input),
            "执行快捷动作",
        )
    if tool_name.endswith("safe_key"):
        return _action_phrase_from_done_summary(
            _safe_key_summary(result, planned_input),
            "按前台导航键",
        )
    if tool_name.endswith("safe_scroll"):
        return _action_phrase_from_done_summary(
            _safe_scroll_summary(result, planned_input),
            "滚动前台界面",
        )
    if tool_name.endswith("safe_click"):
        point = _click_text(result, planned_input)
        return f"点击前台位置：{point}" if point else "点击前台位置"
    if tool_name.endswith("click_ui_element"):
        return _action_phrase_from_done_summary(
            _click_ui_element_summary(result, planned_input),
            "点击前台控件",
        )
    if tool_name.endswith("type_into_ui_element"):
        return _action_phrase_from_done_summary(
            _type_into_ui_element_summary(result, planned_input),
            "填写前台控件",
        )
    if tool_name.endswith("hotkey"):
        hotkey = _hotkey_text(result, planned_input)
        return f"发送快捷键：{hotkey}" if hotkey else "发送快捷键"
    return "执行前台动作"


def _action_phrase_from_done_summary(summary: str, fallback: str) -> str:
    text = str(summary or "").strip()
    if not text:
        return fallback
    if text.startswith("已"):
        text = text[1:]
    return text.removesuffix("。") or fallback


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
    legacy_apple_music_tools = [
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    ]
    tool_text = ", ".join(affected_tools[:6])
    tool_suffix = " 等" if len(affected_tools) > 6 else ""
    if all(tool in affected_tools for tool in legacy_apple_music_tools) and affected_tools != legacy_apple_music_tools:
        legacy_tool_text = ", ".join(legacy_apple_music_tools)
        return _append_recovery_action_summary(
            (
                f"桌面执行权限还缺少：{target_text}{target_suffix}。"
                f"受影响工具：{legacy_tool_text}。完整受影响工具：{tool_text}{tool_suffix}。"
            ),
            result,
        )
    return _append_recovery_action_summary(
        f"桌面执行权限还缺少：{target_text}{target_suffix}。受影响工具：{tool_text}{tool_suffix}。",
        result,
    )


def _desktop_permission_recovery_event_payload(
    tool_name: str,
    planned_input: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    permission_targets = _ordered_text_list(
        [
            *_string_list(result.get("permission_targets")),
            *_string_list(result.get("missing_permissions")),
            *_string_list(data.get("permission_targets")),
            *_string_list(data.get("missing_permissions")),
        ]
    )
    recovery_hints = _ordered_text_list(
        [
            *_string_list(result.get("recovery_hints")),
            *_string_list(data.get("recovery_hints")),
            *_permission_target_hints(permission_targets),
        ]
    )
    recovery_actions = _recovery_actions(result)
    affected_tools = _ordered_text_list(
        [
            *_string_list(result.get("affected_tools")),
            *_string_list(data.get("affected_tools")),
            tool_name,
        ]
    )
    legacy_apple_music_tools = [
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    ]
    if (
        {"music_app", "automation"}.issubset(set(permission_targets))
        and set(legacy_apple_music_tools).issubset(set(affected_tools))
    ):
        affected_tools = _ordered_text_list([*legacy_apple_music_tools, tool_name])
    has_recovery_signal = (
        bool(permission_targets)
        or bool(recovery_hints)
        or bool(recovery_actions)
        or bool(result.get("permission_error"))
    )
    if not has_recovery_signal:
        return {}
    return {
        "tool": tool_name,
        "source": "daily_desktop_intent",
        "status": "permission_recovery_available",
        "input_preview": planned_input,
        "permission_targets": permission_targets,
        "affected_tools": affected_tools,
        "recovery_hints": recovery_hints,
        "recovery_actions": recovery_actions,
    }


def _desktop_permission_preflight_event_payload(
    planned_tool_requests: list[dict[str, Any]],
    broker: Any,
) -> dict[str, Any]:
    planned_tools = _ordered_text_list(
        [str(request.get("tool") or "") for request in planned_tool_requests]
    )
    planned_tools = [tool for tool in planned_tools if tool and tool != "desktop.permissions"]
    if not planned_tools:
        return {}
    desktop_permission_preflight = getattr(broker, "desktop_permission_preflight", None)
    if not callable(desktop_permission_preflight):
        return {}
    try:
        result = desktop_permission_preflight()
    except Exception:
        return {}
    if not isinstance(result, dict):
        return {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    permission_targets = _ordered_text_list(
        [
            *_string_list(result.get("permission_targets")),
            *_string_list(result.get("missing_permissions")),
            *_string_list(data.get("permission_targets")),
            *_string_list(data.get("missing_permissions")),
        ]
    )
    if not permission_targets and not result.get("permission_error"):
        return {}
    affected_tools = _ordered_text_list(
        [
            *_string_list(result.get("affected_tools")),
            *_string_list(data.get("affected_tools")),
        ]
    )
    impacted_tools = [
        tool for tool in planned_tools if not affected_tools or tool in affected_tools
    ]
    if affected_tools and not impacted_tools:
        return {}
    recovery_hints = _ordered_text_list(
        [
            *_string_list(result.get("recovery_hints")),
            *_string_list(data.get("recovery_hints")),
            *_permission_target_hints(permission_targets),
        ]
    )
    recovery_actions = _recovery_actions(result)
    if not permission_targets and not recovery_hints and not recovery_actions:
        return {}
    return {
        "tool": impacted_tools[0] if impacted_tools else planned_tools[0],
        "tools": planned_tools,
        "source": "daily_desktop_intent",
        "status": "permission_preflight_available",
        "permission_targets": permission_targets,
        "affected_tools": impacted_tools or affected_tools,
        "recovery_hints": recovery_hints,
        "recovery_actions": recovery_actions,
        "diagnostic_route": str(
            result.get("diagnostic_route")
            or data.get("diagnostic_route")
            or "/yachiyo/readiness"
        ),
    }


def _append_recovery_action_summary(text: str, result: dict[str, Any]) -> str:
    labels = _recovery_action_labels(result)
    if not labels:
        return text
    return f"{text}可直接打开：{'、'.join(labels[:4])}。"


def _with_retry_recovery_action(
    tool_name: str,
    planned_input: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if not _has_permission_recovery_signal(result):
        return result
    if not isinstance(planned_input, dict):
        return result
    retry_request = daily_desktop_metadata_tool_request(
        {
            "desktop_permission_recovery": True,
            "desktop_permission_retry": True,
            "recovery_action_kind": "retry_original",
            "recovery_tool": tool_name,
            "recovery_input": planned_input,
            "recovery_retry_tool": tool_name,
            "recovery_retry_input": planned_input,
        },
        [tool_name],
    )
    if retry_request is None:
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_actions = result.get("recovery_actions") or data.get("recovery_actions") or []
    actions = [dict(action) for action in raw_actions if isinstance(action, dict)]
    if not actions:
        return result
    retry_prompt = _daily_desktop_retry_prompt(tool_name, planned_input)
    enriched_actions: list[dict[str, Any]] = []
    changed = False
    for action in actions:
        if str(action.get("tool") or "").strip() not in {"app.open", "system.settings_open"}:
            enriched_actions.append(action)
            continue
        enriched_action = dict(action)
        if not str(enriched_action.get("retry_tool") or "").strip():
            enriched_action["retry_tool"] = tool_name
            changed = True
        if not str(enriched_action.get("recovery_retry_tool") or "").strip():
            enriched_action["recovery_retry_tool"] = tool_name
            changed = True
        if not isinstance(enriched_action.get("retry_input"), dict):
            enriched_action["retry_input"] = dict(planned_input)
            changed = True
        if not isinstance(enriched_action.get("recovery_retry_input"), dict):
            enriched_action["recovery_retry_input"] = dict(planned_input)
            changed = True
        if retry_prompt and not str(enriched_action.get("retry_prompt") or "").strip():
            enriched_action["retry_prompt"] = retry_prompt
            changed = True
        if retry_prompt and not str(enriched_action.get("recovery_retry_prompt") or "").strip():
            enriched_action["recovery_retry_prompt"] = retry_prompt
            changed = True
        enriched_actions.append(enriched_action)
    if not changed:
        return result
    enriched = dict(result)
    enriched["recovery_actions"] = enriched_actions
    return enriched


def _has_permission_recovery_signal(result: dict[str, Any]) -> bool:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return bool(
        result.get("permission_error")
        or _string_list(result.get("permission_targets"))
        or _string_list(result.get("missing_permissions"))
        or _string_list(data.get("permission_targets"))
        or _string_list(data.get("missing_permissions"))
        or _recovery_actions(result)
    )


def _daily_desktop_retry_prompt(tool_name: str, planned_input: dict[str, Any]) -> str:
    if tool_name == "media.apple_music_play":
        query = str(planned_input.get("query") or "").strip()
        return f"播放{query}" if query else "播放音乐"
    if tool_name == "media.apple_music_open_and_play":
        return "打开Apple Music并播放"
    if tool_name == "media.music_app_open_and_play":
        app_name = str(planned_input.get("app_name") or "").strip()
        return f"打开{app_name}并播放" if app_name else "播放音乐"
    if tool_name == "system.settings_open":
        target = str(planned_input.get("target") or "").strip()
        return f"打开{target}" if target else "打开系统设置"
    if tool_name == "browser.extract_text":
        return "读取当前网页正文"
    if tool_name == "browser.screenshot":
        return "截取当前网页"
    if tool_name == "browser.current_page":
        return "查看当前网页"
    if tool_name == "screen.capture":
        return "截图当前屏幕"
    if tool_name == "desktop.active_window":
        return "查看当前窗口"
    if tool_name == "desktop.permissions":
        return "检查桌面权限"
    if tool_name == "desktop.safe_click":
        x = planned_input.get("x")
        y = planned_input.get("y")
        if x is not None and y is not None:
            return f"点击 {x}, {y}"
        return ""
    if tool_name == "app.open":
        app_name = str(planned_input.get("app_name") or "").strip()
        return f"打开{app_name}" if app_name else ""
    if tool_name == "app.focus":
        app_name = str(planned_input.get("app_name") or "").strip()
        return f"切到{app_name}" if app_name else ""
    if tool_name in _APP_FOREGROUND_ACTION_TOOLS:
        app_name = str(planned_input.get("app_name") or "").strip()
        if not app_name:
            return ""
        action = "打开" if tool_name.startswith("app.open") else "切到"
        phrase = _app_foreground_action_phrase(tool_name, {}, planned_input)
        return f"{action}{app_name}并{phrase}" if phrase else f"{action}{app_name}"
    return ""


def _recovery_actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_actions = result.get("recovery_actions") or data.get("recovery_actions") or []
    if not isinstance(raw_actions, list):
        return []
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue
        tool = str(raw_action.get("tool") or "").strip()
        label = str(raw_action.get("label") or tool).strip()
        permission_target = str(raw_action.get("permission_target") or "").strip()
        action_input = raw_action.get("input") if isinstance(raw_action.get("input"), dict) else {}
        key = (tool, repr(sorted(action_input.items())), permission_target)
        if not tool or key in seen:
            continue
        seen.add(key)
        action = {
            "label": label or tool,
            "tool": tool,
            "input": dict(action_input),
            "permission_target": permission_target,
            "risk_level": str(raw_action.get("risk_level") or "low"),
        }
        for text_key in (
            "action_kind",
            "recovery_action_kind",
            "retry_prompt",
            "recovery_retry_prompt",
            "retry_source_event_type",
            "recovery_retry_source_event_type",
            "retry_source_tool_call_id",
            "recovery_retry_source_tool_call_id",
            "retry_input_source",
            "recovery_retry_input_source",
            "retry_artifact_tool",
            "recovery_retry_artifact_tool",
            "retry_artifact_kind",
            "recovery_retry_artifact_kind",
            "retry_tool",
            "recovery_retry_tool",
            "followup_tool",
            "recovery_followup_tool",
        ):
            value = str(raw_action.get(text_key) or "").strip()
            if value:
                action[text_key] = value
        for dict_key in (
            "retry_input",
            "recovery_retry_input",
            "retry_input_schema",
            "recovery_retry_input_schema",
            "followup_input",
            "recovery_followup_input",
        ):
            value = raw_action.get(dict_key)
            if isinstance(value, dict):
                action[dict_key] = dict(value)
        for list_key in ("required_retry_fields", "recommended_tools"):
            value = raw_action.get(list_key)
            if isinstance(value, list):
                normalized = [str(item).strip() for item in value if str(item or "").strip()]
                if normalized:
                    action[list_key] = normalized
        if raw_action.get("desktop_permission_retry") is True:
            action["desktop_permission_retry"] = True
        actions.append(action)
    return actions


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


def _installed_apps_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_apps = data.get("apps")
    if not isinstance(raw_apps, list):
        raw_apps = data.get("matches")
    if not isinstance(raw_apps, list):
        return ""
    query = str(data.get("query") or "").strip()
    names = []
    for item in raw_apps:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    if not names:
        return f"没有找到匹配「{query}」的已安装应用。" if query else "没有读取到已安装应用。"
    visible = names[:8]
    total_count = data.get("total_count")
    try:
        total = int(total_count)
    except (TypeError, ValueError):
        total = len(names)
    suffix = f" 等 {total} 个应用" if total > len(visible) else ""
    prefix = f"匹配「{query}」的已安装应用" if query else "已安装应用"
    return f"{prefix}：{', '.join(visible)}{suffix}。"


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


def _ui_elements_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list):
        return ""
    app_name = str(data.get("app_name") or "").strip()
    title = str(data.get("title") or "").strip()
    if not raw_elements:
        scope = f"{app_name} {title}".strip()
        return f"没有读取到 {scope} 的界面控件。" if scope else "没有读取到当前界面控件。"
    items = []
    for item in raw_elements[:8]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "元素").replace("AX", "").strip()
        label = (
            str(item.get("name") or "").strip()
            or str(item.get("description") or "").strip()
            or str(item.get("value") or "").strip()
        )
        center = item.get("center") if isinstance(item.get("center"), dict) else {}
        point = ""
        if center.get("x") not in (None, "") and center.get("y") not in (None, ""):
            point = f"（{center['x']}, {center['y']}）"
        items.append(f"{role}{f' {label}' if label else ''}{point}")
    if not items:
        return ""
    suffix = f" 等 {len(raw_elements)} 个控件" if len(raw_elements) > len(items) else ""
    prefix = f"当前 {app_name} 界面控件" if app_name else "当前界面控件"
    return f"{prefix}：{'; '.join(items)}{suffix}。"


def _inspect_app_result_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if not data:
        return ""
    app_name = str(
        data.get("app_name")
        or data.get("discovered_app_name")
        or data.get("requested_app_name")
        or ""
    ).strip()
    ui_result = data.get("ui_elements") if isinstance(data.get("ui_elements"), dict) else {}
    ui_summary = _ui_elements_summary(ui_result) if ui_result else ""
    open_result = data.get("open_result") if isinstance(data.get("open_result"), dict) else {}
    focus_result = data.get("focus_result") if isinstance(data.get("focus_result"), dict) else {}
    if open_result.get("ok") is True and app_name:
        prefix = f"已打开 {app_name}。"
    elif (
        focus_result.get("ok") is True
        or data.get("focus_verified") is True
    ) and app_name:
        prefix = f"已切换到 {app_name}。"
    elif app_name:
        prefix = f"已检查 {app_name}。"
    else:
        prefix = "已检查应用。"
    return f"{prefix} {ui_summary}".strip() if ui_summary else prefix


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


def _browser_click_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    selector = str(data.get("selector") or planned_input.get("selector") or "").strip()
    point = _browser_point_selector_label(selector)
    if point:
        return f"已点击网页位置：{point}。"
    label = str(data.get("label") or "").strip()
    target = label or _browser_selector_label(selector)
    return f"已点击网页元素：{target}。" if target else "已点击网页元素。"


def _browser_type_text_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    selector = str(data.get("selector") or planned_input.get("selector") or "").strip()
    length = data.get("length") or data.get("character_count")
    if not isinstance(length, int):
        text = _payload_text(result, planned_input, "text")
        length = len(text) if text else 0
    point = _browser_point_selector_label(selector)
    if point:
        return f"已在网页位置：{point} 输入文字（{length} 个字符）。"
    target = _browser_selector_label(selector)
    if target:
        return f"已在网页{target}输入文字（{length} 个字符）。"
    return f"已向网页输入文字（{length} 个字符）。"


def _browser_selector_label(selector: str) -> str:
    clean = str(selector or "").strip()
    if clean.startswith("text="):
        return clean.removeprefix("text=").strip()
    point = _browser_point_selector_label(clean)
    if point:
        return f"位置 {point}"
    if clean in {
        'input[type="search"], input[name="q"], textarea[name="q"], input[aria-label*="搜索" i], input[placeholder*="搜索" i], input[aria-label*="search" i], input[placeholder*="search" i]',
    }:
        return "搜索框"
    if clean:
        return f"元素 {clean}"
    return ""


def _browser_point_selector_label(selector: str) -> str:
    clean = str(selector or "").strip()
    if not clean.startswith("point="):
        return ""
    parts = [part.strip() for part in clean.removeprefix("point=").split(",")]
    if len(parts) != 2 or not all(parts):
        return ""
    try:
        x = _browser_point_number_label(parts[0])
        y = _browser_point_number_label(parts[1])
    except ValueError:
        return ""
    return f"{x}, {y}"


def _browser_point_number_label(value: str) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _browser_text_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    text = str(data.get("text") or result.get("text") or "").strip()
    if not text:
        return "已读取当前网页文本。"
    if len(text) > 1200:
        text = f"{text[:1200]}..."
    return text


def _browser_text_digest_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    text = str(data.get("text") or result.get("text") or "").strip()
    if not text:
        return "已读取当前网页文本，但没有可见正文可总结。"
    points = _browser_text_digest_points(text)
    if not points:
        return "已读取当前网页文本，但没有足够正文可总结。"
    return "网页内容摘要：\n" + "\n".join(f"- {point}" for point in points)


def _browser_text_digest_points(text: str) -> list[str]:
    paragraphs = [
        _clean_browser_digest_line(line)
        for line in str(text or "").replace("\r", "\n").split("\n")
    ]
    candidates = [line for line in paragraphs if line]
    if len(candidates) < 2:
        candidates.extend(
            _clean_browser_digest_line(sentence)
            for sentence in _split_browser_digest_sentences(" ".join(candidates or [text]))
        )
    points: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        points.append(_truncate_browser_digest_point(candidate))
        if len(points) >= 4:
            break
    return points


def _split_browser_digest_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    current: list[str] = []
    for char in str(text or ""):
        current.append(char)
        if char in "。！？.!?":
            sentence = "".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []
    tail = "".join(current).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _clean_browser_digest_line(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    text = text.strip("-*•·#> ")
    if len(text) < 8:
        return ""
    return text


def _truncate_browser_digest_point(value: str, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _apple_music_control_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("control") or planned_input.get("action") or "").strip()
    label = _apple_music_control_label(action)
    if not label:
        return ""
    track = str(data.get("track") or "").strip()
    artist = str(data.get("artist") or "").strip()
    track_text = f"当前：{track}{f' - {artist}' if artist else ''}。" if track else ""
    if data.get("playback_state_unverified"):
        return f"已用媒体键尝试{label} Apple Music。{track_text}"
    return f"已{label} Apple Music。{track_text}"


def _apple_music_status_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("running") is False or str(data.get("player_state") or "").strip() == "not_running":
        return "Apple Music 当前没有运行。"
    state = str(data.get("player_state") or "").strip().lower()
    track = str(data.get("track") or "").strip()
    artist = str(data.get("artist") or "").strip()
    track_text = f"{track}{f' - {artist}' if artist else ''}" if track else ""
    if state == "playing" and track_text:
        return f"Apple Music 当前播放：{track_text}。"
    labels = {
        "playing": "正在播放",
        "paused": "已暂停",
        "stopped": "已停止",
    }
    label = labels.get(state, state or "状态未知")
    if track_text:
        return f"Apple Music 当前{label}：{track_text}。"
    return f"Apple Music 当前{label}，没有可读取的曲目。"


def _music_app_display_name(app_name: str, result: dict[str, Any]) -> str:
    clean_name = str(app_name or "").strip()
    action = str(result.get("action") or "").strip()
    if action.startswith("media.apple_music") or clean_name.casefold() in {
        "music",
        "apple music",
    }:
        return _display_target_name("Apple Music")
    return _display_target_name(clean_name)


def _music_app_open_and_play_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(data.get("app_name") or planned_input.get("app_name") or "").strip()
    if not app_name:
        return ""
    track = str(data.get("track") or "").strip()
    artist = str(data.get("artist") or "").strip()
    track_text = f"{track}{f' - {artist}' if artist else ''}" if track else ""
    if data.get("playback_state_unverified"):
        return f"已打开{_music_app_display_name(app_name, result)}，并用媒体键尝试开始播放。"
    suffix = f"当前：{track_text}。" if track_text else ""
    return f"已打开{_music_app_display_name(app_name, result)}，并开始播放。{suffix}"


def _music_app_control_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(data.get("app_name") or planned_input.get("app_name") or "").strip()
    action = str(data.get("control") or planned_input.get("action") or "").strip()
    label = _music_app_control_label(action)
    if not app_name or not label:
        return ""
    if data.get("running") is False:
        return f"{_display_target_name(app_name).strip() or app_name} 当前没有运行。"
    return f"已向{_display_target_name(app_name, '发送媒体键')}尝试{label}。"


def _system_media_control_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("control") or planned_input.get("action") or "").strip()
    label = _music_app_control_label(action)
    if not label:
        return ""
    return f"已发送媒体键尝试{label}当前媒体。"


def _music_app_control_label(action: str) -> str:
    return {
        "toggle": "切换播放/暂停",
        "play": "开始播放",
        "pause": "暂停",
        "next": "切到下一首",
        "previous": "切到上一首",
    }.get(str(action or "").strip(), "")


def _system_settings_open_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    label = str(data.get("settings_label") or "").strip()
    target = str(data.get("target") or planned_input.get("target") or "").strip()
    if target and target not in {"System Settings", "系统设置", "设置"}:
        return f"已打开系统设置：{target}。"
    if label and label != "System Settings":
        return f"已打开系统设置：{label}。"
    return "已打开系统设置。"


def _apple_music_control_label(action: str) -> str:
    return {
        "toggle": "切换播放/暂停",
        "play": "继续播放",
        "pause": "暂停",
        "next": "切到下一首",
        "previous": "切到上一首",
    }.get(str(action or "").strip(), "")


def _safe_shortcut_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("shortcut_action") or planned_input.get("action") or "").strip()
    label = {
        "copy": "复制选中内容",
        "copy_current_page_link": "复制当前网页链接",
        "paste": "粘贴",
        "select_all": "全选",
        "undo": "撤销",
        "redo": "重做",
        "find": "打开查找",
        "focus_address_bar": "聚焦地址栏",
        "new_tab": "新建标签页",
        "new_private_window": "新建私密窗口",
        "close_tab": "关闭标签页",
        "next_tab": "切到下一个标签页",
        "previous_tab": "切到上一个标签页",
        "next_window": "切到下一个窗口",
        "previous_window": "切到上一个窗口",
        "switch_previous_app": "切到上一个应用",
        "switch_next_app": "切到下一个应用",
        "hide_other_apps": "隐藏其他应用",
        "toggle_full_screen": "切换当前窗口全屏",
        "mission_control": "打开任务控制中心",
        "application_windows": "显示当前应用窗口",
        "spotlight_search": "打开 Spotlight",
        "emoji_picker": "打开 Emoji 面板",
        "screenshot_selection": "截取选区截图",
        "screenshot_toolbar": "打开截图/录屏工具",
        "lock_screen": "锁屏",
        "force_quit_dialog": "打开强制退出窗口",
        "new_window": "新建窗口",
        "new_document": "新建文档",
        "new_message": "新建消息",
        "new_folder": "新建文件夹",
        "rename_selected": "重命名 Finder 选中项",
        "finder_get_info": "显示 Finder 选中项简介",
        "parent_folder": "打开上一级文件夹",
        "new_note": "新建笔记",
        "new_reminder": "新建提醒事项",
        "new_event": "新建日程",
        "refresh": "刷新",
        "bookmark_page": "加入书签",
        "show_history": "打开历史记录",
        "open_devtools": "打开开发者工具",
        "zoom_in": "放大页面",
        "zoom_out": "缩小页面",
        "reset_zoom": "重置页面缩放",
        "browser_back": "返回上一页",
        "browser_forward": "前进一页",
        "reopen_closed_tab": "重新打开关闭的标签页",
        "finder_quick_look": "快速查看选中项",
    }.get(action, "")
    return f"已{label}。" if label else ""


def _safe_key_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("key_action") or planned_input.get("action") or "").strip()
    label = {
        "escape": "Escape",
        "tab": "Tab",
        "shift_tab": "Shift+Tab",
        "arrow_up": "上箭头",
        "arrow_down": "下箭头",
        "arrow_left": "左箭头",
        "arrow_right": "右箭头",
        "home": "Home",
        "end": "End",
        "page_up": "Page Up",
        "page_down": "Page Down",
        "show_desktop": "显示桌面",
    }.get(action, "")
    try:
        repeat_count = int(data.get("repeat_count") or planned_input.get("repeat_count") or 1)
    except (TypeError, ValueError):
        repeat_count = 1
    if not label:
        return ""
    if action == "show_desktop":
        return "已显示桌面。"
    suffix = "" if repeat_count == 1 else f"（{repeat_count} 次）"
    return f"已按{label}{suffix}。"


def _safe_scroll_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    direction = str(data.get("direction") or planned_input.get("direction") or "").strip().lower()
    label = {"down": "向下", "up": "向上"}.get(direction, "")
    try:
        pages = int(data.get("pages") or planned_input.get("pages") or 1)
    except (TypeError, ValueError):
        pages = 1
    if not label:
        return ""
    return f"已{label}滚动前台界面（{pages} 页）。"


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


def _system_brightness_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    action = str(data.get("requested_action") or planned_input.get("action") or "").strip()
    try:
        step = int(data.get("step") or planned_input.get("step") or 2)
    except (TypeError, ValueError):
        step = 2
    suffix = "" if step <= 1 else f"（{step} 格）"
    if action == "up":
        return f"已调高屏幕亮度{suffix}。"
    if action == "down":
        return f"已调低屏幕亮度{suffix}。"
    return ""


def _clipboard_write_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    length = data.get("text_length")
    if not isinstance(length, int):
        text = str(planned_input.get("text") or "")
        length = len(text) if text else 0
    return f"已复制 {length} 个字符到剪贴板。" if length else "已写入剪贴板。"


def _clipboard_read_summary(result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    text = str(data.get("text") or "")
    text_length = data.get("text_length")
    truncated = bool(data.get("truncated"))
    if not text:
        return "剪贴板是空的。" if text_length == 0 else ""
    suffix = "（内容较长，已截断预览）" if truncated else ""
    return f"剪贴板内容：{text}{suffix}"


def _notes_create_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    title = str(data.get("title") or planned_input.get("title") or "").strip()
    length = data.get("body_length")
    if not isinstance(length, int):
        body = str(planned_input.get("body") or "")
        length = len(body) if body else 0
    detail = f"：{title}" if title else ""
    suffix = f"（{length} 个字符）" if length else ""
    return f"已创建备忘录{detail}{suffix}。"


def _reminders_create_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    title = str(data.get("title") or planned_input.get("title") or "").strip()
    due_at = str(data.get("due_at") or planned_input.get("due_at") or "").strip()
    if not title:
        return ""
    return f"已创建提醒事项：{title}{f'（{due_at}）' if due_at else ''}。"


def _calendar_create_event_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    title = str(data.get("title") or planned_input.get("title") or "").strip()
    start_at = str(data.get("start_at") or planned_input.get("start_at") or "").strip()
    end_at = str(data.get("end_at") or planned_input.get("end_at") or "").strip()
    if not title:
        return ""
    time_text = ""
    if start_at and end_at:
        time_text = f"（{start_at} - {end_at}）"
    elif start_at:
        time_text = f"（{start_at}）"
    return f"已创建日历事件：{title}{time_text}。"


def _desktop_open_path_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    path = _desktop_path_summary_path(result, planned_input)
    if not path:
        return ""
    if data.get("is_dir") is True:
        return f"已打开文件夹：{path}。"
    return f"已打开文件：{path}。"


def _desktop_open_path_with_app_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    path = _desktop_path_summary_path(result, planned_input)
    app_name = str(data.get("app_name") or planned_input.get("app_name") or "").strip()
    if not path:
        return ""
    app_text = f"用 {app_name} " if app_name else "用应用"
    if data.get("is_dir") is True:
        return f"已{app_text}打开文件夹：{path}。"
    return f"已{app_text}打开文件：{path}。"


def _desktop_path_summary_path(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("desktop_object"):
        return str(
            data.get("display_path")
            or data.get("resolved_path")
            or data.get("expanded_path")
            or data.get("path")
            or planned_input.get("path")
            or ""
        ).strip()
    return str(data.get("path") or planned_input.get("path") or "").strip()


def _terminal_run_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    command = str(planned_input.get("command") or "").strip()
    command_text = f"：{command}" if command else ""
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    if result.get("ok"):
        if stdout:
            return f"已运行命令{command_text}。\n输出：{_terminal_output_preview(stdout)}"
        return f"已运行命令{command_text}。"
    parts = [f"命令执行失败{command_text}。"]
    returncode = result.get("returncode")
    if returncode not in (None, ""):
        parts.append(f"退出码：{returncode}。")
    if stderr:
        parts.append(f"stderr：{_terminal_output_preview(stderr)}")
    elif stdout:
        parts.append(f"stdout：{_terminal_output_preview(stdout)}")
    return " ".join(parts)


def _data_analyze_summary(result: dict[str, Any], planned_input: dict[str, Any]) -> str:
    path = str(result.get("path") or planned_input.get("path") or "").strip()
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    artifact_path = str(
        artifact.get("path")
        or result.get("artifact_path")
        or planned_input.get("artifact_path")
        or ""
    ).strip()
    rows = result.get("rows")
    columns = result.get("columns")
    column_count = len(columns) if isinstance(columns, list) else None
    source = f"「{path}」" if path else "数据文件"
    facts = []
    if rows not in (None, ""):
        facts.append(f"{rows} 行")
    if column_count is not None:
        facts.append(f"{column_count} 列")
    fact_text = f"（{ '、'.join(facts) }）" if facts else ""
    artifact_text = f"报告已写入 {artifact_path}。" if artifact_path else ""
    return f"已分析{source}{fact_text}。{artifact_text}".strip()


def _terminal_output_preview(value: str) -> str:
    text = str(value or "").strip()
    if len(text) > 600:
        return f"{text[:600]}..."
    return text


def _sentence(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith(("。", ".", "!", "！", "?", "？")):
        return text
    return f"{text}。"


def _combine_daily_desktop_summaries(summaries: list[str]) -> str:
    sentences = [_sentence(summary) for summary in summaries if str(summary or "").strip()]
    return " ".join(sentences)


def _model_followup_context_payload(
    planned_tool_requests: list[dict[str, Any]],
    selection_payload: dict[str, Any],
    *,
    allowed_tools: list[str],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    content_requests = [
        request
        for request in planned_tool_requests
        if isinstance(request, dict)
        and bool(request.get("continue_to_model"))
    ]
    if not content_requests:
        return {}
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    artifacts_expected = _string_list(selection_payload.get("artifacts_expected"))
    planning_reasons = _ordered_text_list(
        [
            str(request.get("planning_reason") or "").strip()
            for request in content_requests
            if str(request.get("planning_reason") or "").strip()
        ]
    )
    planning_reason = (
        planning_reasons[0]
        if len(planning_reasons) == 1
        else "planner_model_followup_context"
    )
    observation_tools = _ordered_text_list(
        [
            str(request.get("tool") or "").strip()
            for request in content_requests
            if str(request.get("tool") or "").strip()
        ]
    )
    payload: dict[str, Any] = {
        "source": "runtime_planner",
        "status": "ready",
        "planning_reason": planning_reason,
        "observation_tools": observation_tools,
        "artifact_write_allowed": "artifact.write" in allowed,
    }
    followup_target = _model_followup_target_payload(selection_payload, allowed)
    if followup_target:
        payload["followup_target"] = followup_target
    if artifacts_expected:
        payload["artifacts_expected"] = artifacts_expected
    pending_plan_steps = _model_followup_pending_plan_steps(
        selection_payload,
        content_requests,
    )
    if pending_plan_steps:
        payload["pending_plan_steps"] = pending_plan_steps
    content_snapshots = followup_content_snapshots(timeline, observation_tools)
    content_snapshot = content_snapshots[-1] if content_snapshots else latest_followup_content_snapshot(timeline, observation_tools)
    if content_snapshot:
        payload["content_snapshot"] = content_snapshot
    if content_snapshots:
        payload["content_snapshots"] = content_snapshots
    for key in ("decision_id", "plan_id", "intent_kind"):
        value = str(selection_payload.get(key) or "").strip()
        if value:
            payload[key] = value
    return payload


def _model_followup_pending_plan_steps(
    selection_payload: Mapping[str, Any],
    content_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps = _selection_tool_plan_steps(selection_payload)
    observation_tools = [
        str(request.get("tool") or "").strip()
        for request in content_requests
        if str(request.get("tool") or "").strip()
    ]
    if not steps or not observation_tools:
        return []

    start_index = _pending_plan_step_start_index(steps, observation_tools)
    if start_index <= 0:
        return []

    pending_steps: list[dict[str, Any]] = []
    for step in steps[start_index:]:
        step_payload = _model_followup_plan_step_payload(step)
        if not step_payload:
            continue
        pending_steps.append(step_payload)
        if len(pending_steps) >= 5:
            break
    return pending_steps


def _selection_tool_plan_steps(selection_payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tool_plan = (
        selection_payload.get("tool_plan")
        if isinstance(selection_payload.get("tool_plan"), Mapping)
        else {}
    )
    steps = tool_plan.get("steps") if isinstance(tool_plan, Mapping) else []
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, Mapping)]


def _pending_plan_step_start_index(
    steps: list[Mapping[str, Any]],
    observation_tools: list[str],
) -> int:
    cursor = 0
    last_match = -1
    for observed_tool in observation_tools:
        for index in range(cursor, len(steps)):
            tool_name = str(steps[index].get("tool_name") or "").strip()
            if tool_name != observed_tool:
                continue
            last_match = index
            cursor = index + 1
            break
    return last_match + 1 if last_match >= 0 else 0


def _model_followup_plan_step_payload(step: Mapping[str, Any]) -> dict[str, Any]:
    if str(step.get("status") or "planned").strip() not in {"", "planned"}:
        return {}
    step_id = str(step.get("step_id") or "").strip()
    tool_name = str(step.get("tool_name") or "").strip()
    if not step_id and not tool_name:
        return {}
    payload: dict[str, Any] = {
        "step_id": step_id,
        "title": str(step.get("title") or "").strip(),
        "tool_name": tool_name,
        "capability_id": str(step.get("capability_id") or "").strip(),
        "action": str(step.get("action") or "").strip(),
        "input_preview": (
            dict(step.get("input_preview"))
            if isinstance(step.get("input_preview"), Mapping)
            else {}
        ),
    }
    risk_level = str(step.get("risk_level") or "").strip()
    if risk_level:
        payload["risk_level"] = risk_level
    if bool(step.get("approval_required")):
        payload["approval_required"] = True
    depends_on = _string_list(step.get("depends_on"))
    if depends_on:
        payload["depends_on"] = depends_on
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


def _model_replan_followup_context_payload(
    replan_payloads: list[dict[str, Any]],
    *,
    allowed_tools: list[str],
    timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    requests: list[dict[str, Any]] = []
    fallback_candidates: list[str] = []
    failed_tools: list[str] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        request = {
            "request_id": str(payload.get("request_id") or "").strip(),
            "trigger": str(payload.get("trigger") or "").strip(),
            "source_step_id": str(payload.get("source_step_id") or "").strip(),
            "source_tool_name": str(payload.get("source_tool_name") or "").strip(),
            "target_capability_id": str(payload.get("target_capability_id") or "").strip(),
            "condition": str(payload.get("condition") or "").strip(),
            "reason": str(payload.get("reason") or "").strip(),
            "failure_event_type": str(payload.get("failure_event_type") or "").strip(),
            "failure_detail": str(payload.get("failure_detail") or "").strip(),
            "fallback_tools": _string_list(payload.get("fallback_tools")),
            "replan_prompt": str(payload.get("replan_prompt") or "").strip(),
        }
        requests.append(request)
        failed_tools.append(request["source_tool_name"])
        fallback_candidates.extend(request["fallback_tools"])
    if not requests:
        return {}
    fallback_candidates = _ordered_text_list(fallback_candidates)
    allowed_fallback_tools = [
        tool for tool in fallback_candidates if not allowed or tool in allowed
    ]
    first = requests[0]
    payload = {
        "source": "runtime_planner",
        "status": "ready",
        "planning_reason": "planner_replan_after_tool_failure",
        "replan_request_count": len(requests),
        "replan_requests": requests,
        "fallback_tools": allowed_fallback_tools,
        "fallback_tool_candidates": fallback_candidates,
        "failed_tools": _ordered_text_list(failed_tools),
        "trigger": first.get("trigger", ""),
        "failure_detail": first.get("failure_detail", ""),
        "source_tool_name": first.get("source_tool_name", ""),
        "target_capability_id": first.get("target_capability_id", ""),
    }
    for key in ("request_id", "decision_id", "plan_id", "core_id", "run_id", "task_id"):
        value = str((replan_payloads[0] if replan_payloads else {}).get(key) or "").strip()
        if value:
            payload[key] = value
    task_progress = _runtime_replan_task_progress_summary(
        replan_payloads,
        timeline or [],
    )
    if task_progress:
        payload["task_progress"] = task_progress
    return payload


def _model_replan_followup_context_message(payload: dict[str, Any]) -> str:
    requests = [
        request
        for request in payload.get("replan_requests", [])
        if isinstance(request, dict)
    ]
    fallback_tools = _string_list(payload.get("fallback_tools"))
    failed_tools = _string_list(payload.get("failed_tools"))
    lines = [
        "Runtime replan context: a planned tool failed or could not be verified.",
        (
            "Continue the existing task workspace. Do not ask the user to perform the "
            "tool-capable action manually."
        ),
        (
            "Inspect the failure, choose the next safe observable action, and keep all "
            "approval and policy gates."
        ),
    ]
    if failed_tools:
        lines.append(f"Failed tools: {', '.join(failed_tools)}.")
    if fallback_tools:
        lines.append(f"Preferred fallback tools: {', '.join(fallback_tools)}.")
    task_progress = (
        payload.get("task_progress")
        if isinstance(payload.get("task_progress"), dict)
        else {}
    )
    if task_progress:
        lines.append("Task progress:")
        for key, label in (
            ("completed_steps", "completed_steps"),
            ("blocked_steps", "blocked_steps"),
            ("pending_steps", "pending_steps"),
            ("waiting_approval_steps", "waiting_approval_steps"),
        ):
            values = _string_list(task_progress.get(key))
            if values:
                lines.append(f"- {label}: {', '.join(values)}")
        workspace_items = [
            item
            for item in task_progress.get("workspace_items", [])
            if isinstance(item, dict)
        ]
        if workspace_items:
            rendered_items = []
            for item in workspace_items[:8]:
                kind = str(item.get("kind") or "").strip()
                path = str(item.get("path") or item.get("title") or "").strip()
                if path:
                    rendered_items.append(f"{kind}:{path}" if kind else path)
            if rendered_items:
                lines.append(f"- workspace_items: {', '.join(rendered_items)}")
    for index, request in enumerate(requests[:3], start=1):
        detail = str(request.get("failure_detail") or "").strip()
        reason = str(request.get("reason") or "").strip()
        prompt = str(request.get("replan_prompt") or "").strip()
        lines.append(f"Replan request {index}:")
        if request.get("request_id"):
            lines.append(f"- request_id: {request['request_id']}")
        if request.get("source_step_id"):
            lines.append(f"- failed_step: {request['source_step_id']}")
        if request.get("source_tool_name"):
            lines.append(f"- failed_tool: {request['source_tool_name']}")
        if request.get("target_capability_id"):
            lines.append(f"- target_capability: {request['target_capability_id']}")
        if detail:
            lines.append(f"- failure_detail: {detail}")
        if reason:
            lines.append(f"- replan_reason: {reason}")
        if prompt:
            lines.append(f"- planner_replan_prompt: {prompt}")
    return "\n".join(lines)


def _runtime_replan_task_progress_summary(
    replan_payloads: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    if not timeline:
        return {}
    core_ids = {
        str(payload.get("core_id") or "").strip()
        for payload in replan_payloads
        if isinstance(payload, Mapping) and str(payload.get("core_id") or "").strip()
    }
    plan_ids = {
        str(payload.get("plan_id") or "").strip()
        for payload in replan_payloads
        if isinstance(payload, Mapping) and str(payload.get("plan_id") or "").strip()
    }
    todos_by_step: dict[str, dict[str, Any]] = {}
    checkpoints_by_step: dict[str, dict[str, Any]] = {}
    workspace_items: list[dict[str, Any]] = []
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        event_name = str(event.get("event") or "").strip()
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        core_id = str(event.get("core_id") or event_payload.get("core_id") or "").strip()
        plan_id = str(event.get("plan_id") or event_payload.get("plan_id") or "").strip()
        if core_ids and core_id and core_id not in core_ids:
            continue
        if plan_ids and plan_id and plan_id not in plan_ids:
            continue
        if event_name == "agent.task_core.created":
            task_core = (
                event_payload.get("task_core")
                if isinstance(event_payload.get("task_core"), Mapping)
                else {}
            )
            workspace = (
                task_core.get("workspace")
                if isinstance(task_core.get("workspace"), Mapping)
                else {}
            )
            workspace_items = _runtime_workspace_item_summaries(workspace.get("items"))
            continue
        if event_name == "agent.task.todo.updated":
            step_id = str(event.get("step_id") or "").strip()
            if not step_id:
                continue
            todo = event.get("todo") if isinstance(event.get("todo"), Mapping) else {}
            todos_by_step[step_id] = {
                "step_id": step_id,
                "title": str(todo.get("title") or event.get("detail") or step_id).strip(),
                "status": str(event.get("status") or todo.get("status") or "").strip(),
                "tool": str(event.get("tool") or todo.get("tool_name") or "").strip(),
                "approval_required": bool(todo.get("approval_required")),
            }
            continue
        if event_name == "agent.task.checkpoint.updated":
            step_id = str(event.get("step_id") or "").strip()
            if not step_id:
                continue
            checkpoint = (
                event.get("checkpoint")
                if isinstance(event.get("checkpoint"), Mapping)
                else {}
            )
            checkpoints_by_step[step_id] = {
                "step_id": step_id,
                "title": str(checkpoint.get("title") or event.get("detail") or step_id).strip(),
                "status": str(event.get("status") or checkpoint.get("status") or "").strip(),
                "checkpoint_id": str(
                    event.get("checkpoint_id") or checkpoint.get("checkpoint_id") or ""
                ).strip(),
            }

    todos = list(todos_by_step.values())
    checkpoints = list(checkpoints_by_step.values())
    if not todos and not checkpoints and not workspace_items:
        return {}
    summary: dict[str, Any] = {
        "todo_count": len(todos),
        "checkpoint_count": len(checkpoints),
        "todos": todos[:20],
        "checkpoints": checkpoints[:20],
    }
    for status, key in (
        ("completed", "completed_steps"),
        ("blocked", "blocked_steps"),
        ("pending", "pending_steps"),
        ("waiting_approval", "waiting_approval_steps"),
        ("skipped", "skipped_steps"),
    ):
        values = [
            str(todo.get("step_id") or "").strip()
            for todo in todos
            if str(todo.get("status") or "").strip() == status
            and str(todo.get("step_id") or "").strip()
        ]
        if values:
            summary[key] = values
    if workspace_items:
        summary["workspace_items"] = workspace_items
    return summary


def _runtime_workspace_item_summaries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summary = {
            "kind": str(item.get("kind") or "").strip(),
            "path": str(item.get("path") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "status": str(item.get("status") or "").strip(),
        }
        clean_summary = {
            key: value
            for key, value in summary.items()
            if value
        }
        if clean_summary:
            summaries.append(clean_summary)
    return summaries[:20]


def _selection_payload_with_timeline_fallback(
    selection_payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(selection_payload) if isinstance(selection_payload, Mapping) else {}
    if isinstance(payload.get("followup_target"), Mapping):
        return payload
    for event in reversed(timeline):
        if not isinstance(event, dict):
            continue
        if str(event.get("event") or "").strip() != "agent.plan.selection":
            continue
        target = event.get("followup_target")
        if not isinstance(target, Mapping):
            continue
        event_payload = {
            str(key): value
            for key, value in event.items()
            if key not in {"event", "detail", "timestamp"}
        }
        return {**event_payload, **payload, "followup_target": dict(target)}
    return payload


def _tool_result_requests_replan(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is True:
        return False
    if result.get("approval_required") or result.get("blocked_by_user_goal"):
        return False
    if result.get("ok") is False:
        return True
    if str(result.get("error") or "").strip():
        return True
    returncode = result.get("returncode")
    if returncode not in (None, "", 0, "0"):
        return True
    exit_code = result.get("exit_code")
    if exit_code not in (None, "", 0, "0"):
        return True
    return False


def _task_todo_status_for_tool_result(event_type: str, result: Mapping[str, Any]) -> str:
    if not isinstance(result, Mapping):
        return "blocked"
    if result.get("approval_required"):
        return "blocked"
    if str(event_type or "").strip() == "agent.tool.skipped":
        return "skipped" if result.get("blocked_by_user_goal") else "blocked"
    return "blocked" if _tool_result_requests_replan(result) else "completed"


def _task_checkpoint_status_for_todo_status(
    todo_status: str,
    result: Mapping[str, Any],
) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if todo_status == "completed":
        return "completed"
    return "blocked"


def _task_progress_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "action",
        "summary",
        "error",
        "hint",
        "returncode",
        "exit_code",
        "blocked_by_user_goal",
        "approval_required",
    ):
        if key in result:
            preview[key] = result.get(key)
    stderr = str(result.get("stderr") or "").strip()
    if stderr:
        preview["stderr"] = stderr[:500]
    return preview


def _runtime_planner_initial_task_updates(
    decision: Any,
) -> list[tuple[str, str, dict[str, Any]]]:
    plan = getattr(decision, "plan", None)
    task_core = getattr(plan, "task_core", None)
    tool_plan = getattr(plan, "tool_plan", None)
    if task_core is None or tool_plan is None:
        return []

    steps_by_id = {
        str(getattr(step, "step_id", "") or "").strip(): step
        for step in list(getattr(tool_plan, "steps", []) or [])
        if str(getattr(step, "step_id", "") or "").strip()
    }
    core_id = str(getattr(task_core, "core_id", "") or "").strip()
    workspace = getattr(task_core, "workspace", None)
    workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
    plan_id = str(getattr(plan, "plan_id", "") or "").strip()
    decision_id = str(getattr(decision, "decision_id", "") or "").strip()
    source_event = {"event": "agent.plan.created", "detail": "runtime_plan_created"}
    events: list[tuple[str, str, dict[str, Any]]] = []

    for todo in list(getattr(task_core, "todos", []) or []):
        step_id = str(getattr(todo, "step_id", "") or "").strip()
        step = steps_by_id.get(step_id)
        tool_name = str(
            getattr(step, "tool_name", "")
            or getattr(todo, "tool_name", "")
            or ""
        ).strip()
        status = str(getattr(todo, "status", "") or "pending").strip()
        todo_payload = _snapshot_payload(todo)
        todo_payload["status"] = status
        payload = {
            "source": "runtime_planner",
            "core_id": core_id,
            "workspace_id": workspace_id,
            "decision_id": decision_id,
            "plan_id": plan_id,
            "step_id": step_id,
            "tool": tool_name,
            "todo_id": str(getattr(todo, "todo_id", "") or "").strip(),
            "status": status,
            "previous_status": "",
            "source_event": source_event,
            "result_preview": {},
            "todo": todo_payload,
        }
        events.append(
            (
                "agent.task.todo.updated",
                str(getattr(todo, "title", "") or step_id),
                payload,
            )
        )

    for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
        step_id = str(getattr(checkpoint, "after_step_id", "") or "").strip()
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        status = str(getattr(checkpoint, "status", "") or "planned").strip()
        checkpoint_payload = _snapshot_payload(checkpoint)
        checkpoint_payload["status"] = status
        payload = {
            "source": "runtime_planner",
            "core_id": core_id,
            "workspace_id": workspace_id,
            "decision_id": decision_id,
            "plan_id": plan_id,
            "step_id": step_id,
            "tool": tool_name,
            "checkpoint_id": str(getattr(checkpoint, "checkpoint_id", "") or "").strip(),
            "status": status,
            "previous_status": "",
            "source_event": source_event,
            "result_preview": {},
            "checkpoint": checkpoint_payload,
        }
        events.append(
            (
                "agent.task.checkpoint.updated",
                str(getattr(checkpoint, "title", "") or step_id),
                payload,
            )
        )
    return events


def _runtime_task_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    identity_key = (
        "todo_id"
        if event_type == "agent.task.todo.updated"
        else "checkpoint_id"
        if event_type == "agent.task.checkpoint.updated"
        else ""
    )
    identity = str(payload.get(identity_key) or "").strip() if identity_key else ""
    status = str(payload.get("status") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    return any(
        isinstance(event, dict)
        and str(event.get("event") or "").strip() == event_type
        and (
            not decision_id
            or str(event.get("decision_id") or "").strip() == decision_id
            or str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), dict)
                    else {}
                ).get("decision_id")
                or ""
            ).strip()
            == decision_id
        )
        and (
            not identity
            or str(event.get(identity_key) or "").strip() == identity
            or str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), dict)
                    else {}
                ).get(identity_key)
                or ""
            ).strip()
            == identity
        )
        and (
            not status
            or str(event.get("status") or "").strip() == status
            or str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), dict)
                    else {}
                ).get("status")
                or ""
            ).strip()
            == status
        )
        for event in timeline
    )


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    if hasattr(snapshot, "model_dump"):
        return snapshot.model_dump(mode="json")
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    return {}


def _model_followup_context_message(payload: dict[str, Any]) -> str:
    artifacts = _string_list(payload.get("artifacts_expected"))
    artifact_write_allowed = bool(payload.get("artifact_write_allowed"))
    observation_tools = _string_list(payload.get("observation_tools"))
    observation_text = ", ".join(observation_tools) or "runtime observation tools"
    followup_target = payload.get("followup_target") if isinstance(payload.get("followup_target"), dict) else {}
    target_instruction = _model_followup_target_instruction(followup_target)
    pending_plan_instruction = _model_followup_pending_plan_instruction(payload)
    if target_instruction:
        artifact_instruction = (
            f"{_model_followup_chained_artifact_instruction(followup_target)}"
            f"{target_instruction}"
        )
    elif pending_plan_instruction:
        artifact_instruction = pending_plan_instruction
    elif artifact_write_allowed and artifacts:
        artifact_instruction = (
            "The user requested a durable output. Call artifact.write next with "
            f"path {artifacts[0]!r} and content derived from the observed context. "
            "Do not write an empty or placeholder artifact."
        )
    elif artifact_write_allowed:
        artifact_instruction = (
            "If the user requested a durable output, call artifact.write next with an appropriate "
            "path and content derived from the observed context. Do not write an empty artifact."
        )
    else:
        artifact_instruction = (
            "artifact.write is not allowed, so provide the requested summary or report inline."
        )
    snapshot_text = _followup_content_snapshots_message(payload)
    return (
        "Runtime follow-up context: source material has just been observed through "
        f"{observation_text}. Use the latest Tool result messages above as source material. "
        f"{snapshot_text}"
        f"{artifact_instruction} If the observation failed or lacks readable content, explain the "
        "missing permission, capability, or fallback without asking the user to manually repeat a "
        "tool-capable action."
    )


def _model_followup_pending_plan_instruction(payload: Mapping[str, Any]) -> str:
    steps = payload.get("pending_plan_steps")
    if not isinstance(steps, list):
        return ""
    normalized_steps = [
        step
        for step in steps
        if isinstance(step, Mapping)
        and (
            str(step.get("step_id") or "").strip()
            or str(step.get("tool_name") or "").strip()
        )
    ]
    if not normalized_steps:
        return ""
    items = []
    for index, step in enumerate(normalized_steps, start=1):
        tool_name = str(step.get("tool_name") or "").strip() or "available tool"
        step_id = str(step.get("step_id") or "").strip() or f"step-{index}"
        action = str(step.get("action") or "").strip()
        risk_level = str(step.get("risk_level") or "").strip()
        approval = " approval required" if bool(step.get("approval_required")) else ""
        preview = (
            step.get("input_preview")
            if isinstance(step.get("input_preview"), Mapping)
            else {}
        )
        preview_text = _model_followup_input_preview_text(preview)
        detail = f"[{index}] {step_id} via {tool_name}"
        if action:
            detail = f"{detail} action={action!r}"
        if risk_level or approval:
            detail = f"{detail} ({risk_level or 'low'} risk{approval})"
        if preview_text:
            detail = f"{detail} input_preview={preview_text}"
        items.append(detail)
    return (
        "Continue the pending Runtime Plan steps in order before giving a final answer: "
        + "; ".join(items)
        + ". If a pending terminal.execution step only has an abstract operation, synthesize a concrete, "
        "safe command from the observed files and request approval through the normal tool/policy gate. "
        "Do not skip directly to final prose while an available tool step is still pending."
    )


def _model_followup_input_preview_text(preview: Mapping[str, Any]) -> str:
    if not preview:
        return ""
    text = repr(dict(preview))
    if len(text) > 360:
        return f"{text[:357]}..."
    return text


def _model_followup_target_payload(
    selection_payload: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    app_name = str(target.get("app_name") or "").strip()
    kind = str(target.get("kind") or "").strip()
    if kind == "communication_message":
        return _model_followup_communication_target_payload(target, allowed)
    if kind == "desktop_discovered_app_action":
        return _model_followup_desktop_discovered_app_target_payload(target, allowed)
    if kind == "desktop_discovered_media_playback":
        return _model_followup_discovered_media_playback_target_payload(target, allowed)
    if kind == "artifact_write":
        return _model_followup_artifact_write_target_payload(target, allowed)
    if kind == "note_write":
        return _model_followup_note_write_target_payload(target, allowed)
    if kind != "app_write" or not app_name:
        return {}
    container_action = _model_followup_container_action(target)
    write_tools = _model_followup_app_write_tool_names(allowed, container_action)
    verify_tools = [
        tool
        for tool in ("desktop.ui_elements", "desktop.active_window", "screen.capture")
        if tool in allowed
    ]
    payload: dict[str, Any] = {
        "kind": "app_write",
        "app_name": app_name,
        "target_action": str(target.get("target_action") or "app_paste").strip(),
        "body_source": "model_generated_content",
        "write_allowed": bool(write_tools),
        "recommended_tools": write_tools,
        "verify_tools": verify_tools,
    }
    if container_action:
        payload["container_action"] = container_action
    context_source = str(target.get("context_source") or "").strip()
    if context_source:
        payload["context_source"] = context_source
    artifact_write = _model_followup_chained_artifact_write_payload(target, allowed)
    if artifact_write:
        payload["artifact_write"] = artifact_write
    return payload


def _model_followup_artifact_write_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    path = str(target.get("path") or "").strip()
    if not path:
        return {}
    write_allowed = "artifact.write" in allowed
    payload: dict[str, Any] = {
        "kind": "artifact_write",
        "target_action": str(target.get("target_action") or "write_artifact").strip(),
        "path": path,
        "body_source": "model_generated_content",
        "write_allowed": write_allowed,
        "recommended_tools": ["artifact.write"] if write_allowed else [],
    }
    context_source = str(target.get("context_source") or "").strip()
    if context_source:
        payload["context_source"] = context_source
    intent_kind = str(target.get("intent_kind") or "").strip()
    if intent_kind:
        payload["intent_kind"] = intent_kind
    return payload


def _model_followup_note_write_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    write_allowed = "notes.create" in allowed
    payload: dict[str, Any] = {
        "kind": "note_write",
        "target_action": str(target.get("target_action") or "create_note").strip(),
        "body_source": "model_generated_content",
        "write_allowed": write_allowed,
        "recommended_tools": ["notes.create"] if write_allowed else [],
    }
    context_source = str(target.get("context_source") or "").strip()
    if context_source:
        payload["context_source"] = context_source
    title = str(target.get("title") or "").strip()
    if title:
        payload["title"] = title
    folder_name = str(target.get("folder_name") or "").strip()
    if folder_name:
        payload["folder_name"] = folder_name
    return payload


def _model_followup_desktop_discovered_app_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    app_query = str(target.get("app_query") or "").strip()
    if not app_query:
        return {}
    recommended_tools = [
        tool
        for tool in (
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "app.open",
            "app.focus",
            "desktop.open_path_with_app",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
            "desktop.inspect_app",
            "app.focus_and_type_into_ui_element",
            "desktop.search_submit",
            "desktop.submit_foreground",
        )
        if tool in allowed
    ]
    verify_tools = [
        tool
        for tool in ("desktop.ui_elements", "desktop.active_window", "screen.capture")
        if tool in allowed
    ]
    payload: dict[str, Any] = {
        "kind": "desktop_discovered_app_action",
        "app_query": app_query,
        "app_name_source": str(target.get("app_name_source") or "desktop.list_apps").strip(),
        "target_action": str(target.get("target_action") or "").strip(),
        "recommended_tools": recommended_tools,
        "verify_tools": verify_tools,
    }
    safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
    if safe_shortcut_action:
        payload["safe_shortcut_action"] = safe_shortcut_action
    target_path = str(target.get("target_path") or "").strip()
    if target_path:
        payload["target_path"] = target_path
    compose_text = str(target.get("compose_text") or "").strip()
    if compose_text:
        payload["compose_text"] = compose_text
        payload["body_source"] = str(target.get("body_source") or "explicit_user_text").strip()
    body_source = str(target.get("body_source") or "").strip()
    if body_source and "body_source" not in payload:
        payload["body_source"] = body_source
    communication_compose = _discovered_app_communication_compose_payload(target)
    if communication_compose:
        payload["communication_compose"] = communication_compose
        payload["send_allowed"] = (
            communication_compose.get("send_action") == "send"
            and "desktop.submit_foreground" in allowed
        )
        transform = str(
            target.get("content_transform_hint")
            or target.get("transform")
            or ""
        ).strip()
        if transform:
            payload["transform"] = transform
    artifact_write = _model_followup_chained_artifact_write_payload(target, allowed)
    if artifact_write:
        payload["artifact_write"] = artifact_write
    creative_canvas = (
        target.get("creative_canvas")
        if isinstance(target.get("creative_canvas"), Mapping)
        else {}
    )
    if creative_canvas:
        payload["creative_canvas"] = dict(creative_canvas)
    return payload


def _model_followup_discovered_media_playback_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    app_query = str(target.get("app_query") or "").strip()
    media_query = str(target.get("media_playback_query") or "").strip()
    if not app_query or not media_query:
        return {}
    recommended_tools = [
        tool
        for tool in (
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "app.open",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "media.music_app_open_and_play",
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
            "desktop.click_ui_element",
        )
        if tool in allowed
    ]
    verify_tools = [
        tool
        for tool in ("desktop.ui_elements", "desktop.active_window", "screen.capture")
        if tool in allowed
    ]
    return {
        "kind": "desktop_discovered_media_playback",
        "app_query": app_query,
        "app_name_source": str(target.get("app_name_source") or "desktop.list_apps").strip(),
        "target_action": str(target.get("target_action") or "safe_shortcut").strip(),
        "safe_shortcut_action": str(target.get("safe_shortcut_action") or "find").strip(),
        "media_playback_query": media_query,
        "recommended_tools": recommended_tools,
        "verify_tools": verify_tools,
    }


def _model_followup_communication_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    recipient = str(target.get("recipient") or "").strip()
    if not recipient:
        return {}
    channel = str(target.get("channel") or "").strip()
    app_name = str(target.get("app_name") or "").strip()
    if not app_name and channel == "email":
        app_name = "Mail"
    if not app_name:
        return {}
    send_action = str(target.get("send_action") or "send").strip() or "send"
    mode = str(target.get("mode") or "focus").strip() or "focus"
    prepare_tools = _model_followup_communication_prepare_tool_names(
        allowed,
        app_name=app_name,
        mode=mode,
        channel=channel,
    )
    draft_allowed = bool(
        prepare_tools
        and "desktop.safe_type_text" in allowed
        and "desktop.search_submit" in allowed
    )
    send_allowed = send_action == "send" and "desktop.submit_foreground" in allowed
    verify_tools = [
        tool
        for tool in ("desktop.ui_elements", "desktop.active_window", "screen.capture")
        if tool in allowed
    ]
    payload: dict[str, Any] = {
        "kind": "communication_message",
        "app_name": app_name,
        "recipient": recipient,
        "body_source": "model_generated_content",
        "draft_allowed": draft_allowed,
        "mode": mode,
        "send_action": send_action,
        "send_allowed": send_allowed,
        "recommended_tools": [
            *prepare_tools,
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.safe_type_text",
            *(["desktop.submit_foreground"] if send_allowed else []),
        ] if draft_allowed else prepare_tools,
        "verify_tools": verify_tools,
    }
    if channel:
        payload["channel"] = channel
    transform = str(target.get("transform") or "").strip()
    if transform:
        payload["transform"] = transform
    artifact_write = _model_followup_chained_artifact_write_payload(target, allowed)
    if artifact_write:
        payload["artifact_write"] = artifact_write
    return payload


def _model_followup_chained_artifact_write_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    raw = (
        target.get("artifact_write")
        if isinstance(target.get("artifact_write"), Mapping)
        else {}
    )
    path = str(raw.get("path") or "").strip()
    if not path:
        return {}
    write_allowed = "artifact.write" in allowed
    payload: dict[str, Any] = {
        "target_action": str(raw.get("target_action") or "write_artifact").strip(),
        "path": path,
        "body_source": str(raw.get("body_source") or "model_generated_content").strip(),
        "tool": str(raw.get("tool") or "artifact.write").strip(),
        "write_allowed": write_allowed,
        "recommended_tools": ["artifact.write"] if write_allowed else [],
    }
    intent_kind = str(raw.get("intent_kind") or "").strip()
    if intent_kind:
        payload["intent_kind"] = intent_kind
    return payload


def _selection_payload_has_model_followup_target(
    selection_payload: Mapping[str, Any],
) -> bool:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    kind = str(target.get("kind") or "").strip()
    if kind == "app_write":
        return bool(str(target.get("app_name") or "").strip())
    if kind == "communication_message":
        return bool(str(target.get("recipient") or "").strip())
    if kind == "artifact_write":
        return bool(str(target.get("path") or "").strip())
    if kind == "note_write":
        return True
    if kind == "desktop_discovered_app_action":
        return bool(str(target.get("app_query") or "").strip())
    if kind == "desktop_discovered_media_playback":
        return bool(str(target.get("app_query") or "").strip())
    return False


def _auto_discovered_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for factory in (
        _auto_discovered_app_followup_requests,
        _auto_discovered_media_playback_followup_requests,
    ):
        requests = factory(selection_payload, allowed_tools, timeline)
        if requests:
            return requests
    return []


def _auto_discovered_app_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_discovered_app_followup",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    app_query = str(target.get("app_query") or "").strip()
    app_name = _discovered_app_name_for_query(timeline, app_query)
    if not app_name:
        return []
    resolution_evidence = _discovered_app_resolution_evidence(timeline, app_query, app_name)
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    source = "runtime_planner"
    planning_reason = str(planning_reason or "planner_discovered_app_followup").strip()
    if not planning_reason:
        planning_reason = "planner_discovered_app_followup"
    target_action = str(target.get("target_action") or "").strip()
    safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
    requests: list[dict[str, Any]] = []
    if target_action == "safe_shortcut" and safe_shortcut_action:
        requests.extend(
            _discovered_app_safe_shortcut_requests(
                app_query,
                app_name,
                safe_shortcut_action,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
        )
    elif target_action == "open_path_with_selected_app":
        target_path = str(target.get("target_path") or "").strip()
        if target_path:
            open_path_request = _discovered_app_open_path_request(
                app_query,
                app_name,
                target_path,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
            if open_path_request:
                requests.append(open_path_request)
    elif target_action in {"open_app", "open", "focus_app", "focus"}:
        open_request = _discovered_app_open_request(
            app_query,
            app_name,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if open_request:
            requests.append(open_request)
    communication_compose = _discovered_app_communication_compose_payload(target)
    if communication_compose:
        compose_requests = _discovered_app_communication_compose_requests(
            app_query,
            app_name,
            communication_compose,
            allowed,
            prepared=bool(requests),
            source=source,
            planning_reason=planning_reason,
        )
        if not compose_requests:
            return []
        requests.extend(compose_requests)
    compose_text = str(target.get("compose_text") or "").strip()
    if requests and compose_text and not communication_compose:
        type_request = _discovered_app_type_text_request(
            app_query,
            app_name,
            compose_text,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if type_request:
            requests.append(type_request)
    if not requests:
        return []
    if resolution_evidence:
        requests = [
            _with_discovered_app_resolution_evidence(request, resolution_evidence)
            for request in requests
        ]
    observation_request = _discovered_app_observation_request(
        target,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if observation_request:
        requests.append(observation_request)
    if (
        str(target.get("body_source") or "").strip() == "model_generated_content"
        and requests
    ):
        requests[-1]["continue_to_model"] = True
    return requests


def _auto_discovered_media_playback_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_discovered_media_playback_followup",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_media_playback":
        return []
    app_query = str(target.get("app_query") or "").strip()
    media_query = str(target.get("media_playback_query") or "").strip()
    if not app_query or not media_query:
        return []
    app_name = _discovered_app_name_for_query(timeline, app_query)
    if not app_name:
        return []
    resolution_evidence = _discovered_app_resolution_evidence(timeline, app_query, app_name)
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    source = "runtime_planner"
    planning_reason = str(planning_reason or "planner_discovered_media_playback_followup").strip()
    if not planning_reason:
        planning_reason = "planner_discovered_media_playback_followup"
    requests: list[dict[str, Any]] = []
    if str(target.get("target_action") or "").strip() == "safe_shortcut":
        safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
        if not safe_shortcut_action:
            return []
        requests.extend(
            _discovered_app_safe_shortcut_requests(
                app_query,
                app_name,
                safe_shortcut_action,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
        )
    else:
        open_request = _discovered_app_open_request(
            app_query,
            app_name,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if open_request:
            requests.append(open_request)
    if not requests or "desktop.safe_type_text" not in allowed:
        return []
    requests.append(
        _request_like(
            "desktop.safe_type_text",
            {"text": media_query},
            source=source,
            planning_reason=planning_reason,
        )
    )
    submit_request = _media_search_submit_request(
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if not submit_request:
        return []
    requests.append(submit_request)
    playback_request = _discovered_media_playback_request(
        app_query,
        app_name,
        target,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if not playback_request:
        return []
    requests.append(playback_request)
    observation_request = _discovered_app_observation_request(
        target,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if observation_request:
        requests.append(observation_request)
    if resolution_evidence:
        requests = [
            _with_discovered_app_resolution_evidence(request, resolution_evidence)
            for request in requests
        ]
    return requests


def _media_search_submit_request(
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    if "desktop.search_submit" in allowed:
        return _request_like(
            "desktop.search_submit",
            {},
            source=source,
            planning_reason=planning_reason,
        )
    if "desktop.submit_foreground" in allowed:
        return _request_like(
            "desktop.submit_foreground",
            {"action": "confirm"},
            source=source,
            planning_reason=planning_reason,
        )
    return {}


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _discovered_media_playback_request(
    app_query: str,
    app_name: str,
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    if "media.music_app_open_and_play" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "media.music_app_open_and_play",
                {"app_name": app_name},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    result_selection = (
        target.get("result_selection")
        if isinstance(target.get("result_selection"), Mapping)
        else {}
    )
    result_payload = {
        "target": str(result_selection.get("target") or "first result").strip(),
        "role_filter": str(result_selection.get("role_filter") or "").strip(),
        "limit": _positive_int(result_selection.get("limit"), default=80),
        "click_count": _positive_int(result_selection.get("click_count"), default=1),
    }
    if "app.focus_and_click_ui_element" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "app.focus_and_click_ui_element",
                {"app_name": app_name, **result_payload},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    if "app.open_and_click_ui_element" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "app.open_and_click_ui_element",
                {"app_name": app_name, **result_payload},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    if "desktop.click_ui_element" in allowed:
        return _request_like(
            "desktop.click_ui_element",
            result_payload,
            source=source,
            planning_reason=planning_reason,
        )
    return {}


def _discovered_app_safe_shortcut_requests(
    app_query: str,
    app_name: str,
    action: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    if "app.open_and_safe_shortcut" in allowed:
        return [
            _with_discovered_app_resolution(
                _request_like(
                    "app.open_and_safe_shortcut",
                    {"app_name": app_name, "action": action},
                    source=source,
                    planning_reason=planning_reason,
                ),
                app_query,
                app_name,
            )
        ]
    if "app.focus_and_safe_shortcut" in allowed:
        return [
            _with_discovered_app_resolution(
                _request_like(
                    "app.focus_and_safe_shortcut",
                    {"app_name": app_name, "action": action},
                    source=source,
                    planning_reason=planning_reason,
                ),
                app_query,
                app_name,
            )
        ]
    focus_tool = "app.open" if "app.open" in allowed else ("app.focus" if "app.focus" in allowed else "")
    if focus_tool and "desktop.safe_shortcut" in allowed:
        return [
            _with_discovered_app_resolution(
                _request_like(
                    focus_tool,
                    {"app_name": app_name},
                    source=source,
                    planning_reason=planning_reason,
                ),
                app_query,
                app_name,
            ),
            _request_like(
                "desktop.safe_shortcut",
                {"action": action},
                source=source,
                planning_reason=planning_reason,
            ),
        ]
    return []


def _discovered_app_open_path_request(
    app_query: str,
    app_name: str,
    path: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    if "desktop.open_path_with_app" not in allowed:
        return {}
    return _with_discovered_app_resolution(
        _request_like(
            "desktop.open_path_with_app",
            {"app_name": app_name, "path": path},
            source=source,
            planning_reason=planning_reason,
        ),
        app_query,
        app_name,
    )


def _discovered_app_open_request(
    app_query: str,
    app_name: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    tool_name = "app.open" if "app.open" in allowed else ("app.focus" if "app.focus" in allowed else "")
    if not tool_name:
        return {}
    return _with_discovered_app_resolution(
        _request_like(
            tool_name,
            {"app_name": app_name},
            source=source,
            planning_reason=planning_reason,
        ),
        app_query,
        app_name,
    )


def _discovered_app_type_text_request(
    app_query: str,
    app_name: str,
    text: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    if "desktop.safe_type_text" in allowed:
        return _request_like(
            "desktop.safe_type_text",
            {"text": text},
            source=source,
            planning_reason=planning_reason,
        )
    if "app.focus_and_safe_type_text" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "app.focus_and_safe_type_text",
                {"app_name": app_name, "text": text},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    return {}


def _discovered_app_communication_compose_payload(
    target: Mapping[str, Any],
) -> dict[str, str]:
    raw = (
        target.get("communication_compose")
        if isinstance(target.get("communication_compose"), Mapping)
        else {}
    )
    if not raw:
        return {}
    payload = {
        key: str(raw.get(key) or "").strip()
        for key in ("channel", "recipient", "body", "send_action")
        if str(raw.get(key) or "").strip()
    }
    if not payload.get("recipient") and not payload.get("body"):
        return {}
    payload.setdefault("send_action", "draft")
    return payload


def _discovered_app_communication_compose_requests(
    app_query: str,
    app_name: str,
    compose: Mapping[str, str],
    allowed: set[str],
    *,
    prepared: bool,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    recipient = str(compose.get("recipient") or "").strip()
    body = str(compose.get("body") or "").strip()
    if not recipient and not body:
        return []
    requests: list[dict[str, Any]] = []
    if not prepared:
        requests.extend(
            _discovered_app_safe_shortcut_requests(
                app_query,
                app_name,
                "new_message",
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
        )
        if not requests:
            return []
    inspect_request = _discovered_app_communication_inspect_request(
        app_query,
        app_name,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if inspect_request:
        requests.append(inspect_request)
    channel = str(compose.get("channel") or "").strip()
    if recipient:
        recipient_request = _discovered_app_type_into_ui_element_request(
            app_query,
            app_name,
            _discovered_communication_recipient_target(channel),
            recipient,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if not recipient_request or "desktop.search_submit" not in allowed:
            return []
        requests.append(recipient_request)
        requests.append(
            _request_like(
                "desktop.search_submit",
                {},
                source=source,
                planning_reason=planning_reason,
            )
        )
    if body:
        body_request = _discovered_app_type_into_ui_element_request(
            app_query,
            app_name,
            _discovered_communication_body_target(channel),
            body,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if not body_request:
            return []
        requests.append(body_request)
    if (
        str(compose.get("send_action") or "").strip() == "send"
        and body
        and "desktop.submit_foreground" in allowed
    ):
        requests.append(
            _request_like(
                "desktop.submit_foreground",
                {"action": "send"},
                source=source,
                planning_reason=planning_reason,
            )
        )
    return requests


def _discovered_app_communication_inspect_request(
    app_query: str,
    app_name: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    if "desktop.inspect_app" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "desktop.inspect_app",
                {
                    "app_name": app_name,
                    "open_if_needed": False,
                    "focus": True,
                    "role_filter": "text",
                    "limit": 80,
                },
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    if "desktop.ui_elements" in allowed:
        return _request_like(
            "desktop.ui_elements",
            {"role_filter": "text", "limit": 80},
            source=source,
            planning_reason=planning_reason,
        )
    return {}


def _discovered_app_type_into_ui_element_request(
    app_query: str,
    app_name: str,
    target: str,
    text: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    payload = {
        "target": target,
        "text": text,
        "role_filter": "text",
        "limit": 80,
    }
    if "app.focus_and_type_into_ui_element" in allowed:
        return _with_discovered_app_resolution(
            _request_like(
                "app.focus_and_type_into_ui_element",
                {"app_name": app_name, **payload},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
    if "desktop.type_into_ui_element" in allowed:
        return _request_like(
            "desktop.type_into_ui_element",
            payload,
            source=source,
            planning_reason=planning_reason,
        )
    if "desktop.safe_type_text" in allowed:
        return _request_like(
            "desktop.safe_type_text",
            {"text": text},
            source=source,
            planning_reason=planning_reason,
        )
    return {}


def _discovered_communication_recipient_target(channel: str) -> str:
    return "To" if str(channel or "").strip() == "email" else "recipient"


def _discovered_communication_body_target(channel: str) -> str:
    return "message body" if str(channel or "").strip() == "email" else "message"


def _discovered_app_observation_request(
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    post_action_observation = (
        target.get("post_action_observation")
        if isinstance(target.get("post_action_observation"), Mapping)
        else {}
    )
    if (
        str(target.get("target_action") or "").strip() == "open_path_with_selected_app"
        and not post_action_observation
    ):
        return {}
    target_action = str(target.get("target_action") or "").strip()
    if (
        not post_action_observation
        and target_action in {"open_app", "open", "focus_app", "focus"}
        and "desktop.active_window" in allowed
    ):
        return _request_like(
            "desktop.active_window",
            {},
            source=source,
            planning_reason=planning_reason,
        )
    tool_name = str(post_action_observation.get("tool") or "desktop.ui_elements").strip()
    raw_input = (
        post_action_observation.get("input")
        if isinstance(post_action_observation.get("input"), Mapping)
        else {}
    )
    if tool_name not in allowed:
        if "desktop.ui_elements" not in allowed:
            return {}
        tool_name = "desktop.ui_elements"
        raw_input = {}
    request = _request_like(
        tool_name,
        dict(raw_input),
        source=source,
        planning_reason=planning_reason,
    )
    if isinstance(target.get("creative_canvas"), Mapping):
        request["continue_to_model"] = True
    return request


def _with_discovered_app_resolution(
    request: dict[str, Any],
    app_query: str,
    app_name: str,
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or "").strip()
    return {
        **request,
        "input_resolution": {
            "tool": tool_name,
            "field": "app_name",
            "requested_app_name": app_query,
            "resolved_app_name": app_name,
            "source_tool": "desktop.list_apps",
        },
    }


def _with_discovered_app_resolution_evidence(
    request: dict[str, Any],
    evidence: Mapping[str, str],
) -> dict[str, Any]:
    if not evidence:
        return request
    resolution = (
        request.get("input_resolution")
        if isinstance(request.get("input_resolution"), dict)
        else {}
    )
    if not resolution:
        return request
    return {**request, "input_resolution": {**resolution, **dict(evidence)}}


def _model_followup_communication_prepare_tool_names(
    allowed: set[str],
    *,
    app_name: str,
    mode: str,
    channel: str,
) -> list[str]:
    action = _model_followup_communication_focus_action(channel)
    if mode == "open" and "app.open_and_safe_shortcut" in allowed:
        return ["app.open_and_safe_shortcut"]
    if "app.focus_and_safe_shortcut" in allowed:
        return ["app.focus_and_safe_shortcut"]
    if "app.open_and_safe_shortcut" in allowed:
        return ["app.open_and_safe_shortcut"]
    focus_tool = "app.open" if mode == "open" and "app.open" in allowed else ""
    if not focus_tool:
        focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if app_name and focus_tool and "desktop.safe_shortcut" in allowed and action:
        return [focus_tool, "desktop.safe_shortcut"]
    return []


def _model_followup_communication_focus_action(channel: str) -> str:
    return "new_message" if str(channel or "").strip() == "email" else "find"


def _model_followup_app_write_tool_names(
    allowed: set[str],
    container_action: str = "",
) -> list[str]:
    tools = _model_followup_container_tool_names(allowed) if container_action else []
    if container_action and not tools:
        return []
    if "app.focus_and_safe_type_text" in allowed:
        return [*tools, "app.focus_and_safe_type_text"]
    if "app.open_and_safe_type_text" in allowed:
        return [*tools, "app.open_and_safe_type_text"]
    focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if focus_tool and "desktop.safe_type_text" in allowed:
        return [*tools, focus_tool, "desktop.safe_type_text"]
    if focus_tool and "clipboard.write" in allowed and "desktop.safe_shortcut" in allowed:
        return [*tools, "clipboard.write", focus_tool, "desktop.safe_shortcut"]
    return []


def _model_followup_container_tool_names(allowed: set[str]) -> list[str]:
    if "app.focus_and_safe_shortcut" in allowed:
        return ["app.focus_and_safe_shortcut"]
    if "app.open_and_safe_shortcut" in allowed:
        return ["app.open_and_safe_shortcut"]
    focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if focus_tool and "desktop.safe_shortcut" in allowed:
        return [focus_tool, "desktop.safe_shortcut"]
    return []


def _model_followup_container_action(target: Mapping[str, Any]) -> str:
    action = str(target.get("container_action") or "").strip()
    return action if action in {"new_note", "new_document"} else ""


def _model_followup_target_instruction(target: Mapping[str, Any]) -> str:
    if not isinstance(target, Mapping):
        return ""
    kind = str(target.get("kind") or "").strip()
    if kind == "communication_message":
        return _model_followup_communication_instruction(target)
    if kind == "desktop_discovered_app_action":
        return _model_followup_desktop_discovered_app_instruction(target)
    if kind == "desktop_discovered_media_playback":
        return _model_followup_discovered_media_playback_instruction(target)
    if kind == "artifact_write":
        return _model_followup_artifact_write_instruction(target)
    if kind == "note_write":
        return _model_followup_note_write_instruction(target)
    app_name = str(target.get("app_name") or "").strip()
    if kind != "app_write" or not app_name:
        return ""
    if not bool(target.get("write_allowed")):
        return (
            f"The user requested the transformed content be written into {app_name}, "
            "but no allowed target-container creation or foreground text insertion tool is "
            "available. Explain the missing capability instead of claiming the app was updated."
        )
    tools = _string_list(target.get("recommended_tools"))
    verify_tools = _string_list(target.get("verify_tools"))
    container_action = _model_followup_container_action(target)
    tool_text = ", ".join(tools) or "the allowed desktop text insertion tools"
    verify_text = (
        f" Verify with {', '.join(verify_tools)} after writing."
        if verify_tools
        else ""
    )
    container_text = (
        f" First create the requested target container with {container_action}, then insert "
        "the generated transformed content. "
        if container_action
        else " "
    )
    return (
        f"The user requested the transformed content be written into {app_name}. "
        f"{container_text}"
        "After deriving the final transformed text, call desktop tools next instead of only "
        f"replying inline. Prefer {tool_text}; use the generated transformed content as the "
        "text input. Do not write the raw observed source when the user asked for summary, "
        f"cleanup, translation, or todo conversion.{verify_text} "
    )


def _model_followup_artifact_write_instruction(target: Mapping[str, Any]) -> str:
    path = str(target.get("path") or "").strip()
    if not path:
        return ""
    if not bool(target.get("write_allowed")):
        return (
            f"The user requested a durable artifact at {path!r}, but artifact.write is not "
            "available. Explain the missing capability instead of claiming the file was written."
        )
    tools = _string_list(target.get("recommended_tools"))
    tool_text = ", ".join(tools) or "artifact.write"
    return (
        f"The user requested a durable artifact at {path!r}. After deriving the final artifact "
        "content, call artifact.write next instead of only replying inline. "
        f"Prefer {tool_text}; use the generated transformed content as the content input. "
        "Do not write an empty or placeholder artifact, and do not write the raw observed source "
        "when the user asked for summary, cleanup, translation, or report generation. "
    )


def _model_followup_chained_artifact_instruction(target: Mapping[str, Any]) -> str:
    raw = target.get("artifact_write") if isinstance(target.get("artifact_write"), Mapping) else {}
    path = str(raw.get("path") or "").strip()
    if not path:
        return ""
    if not bool(raw.get("write_allowed")):
        return (
            f"The user also requested a durable artifact at {path!r}, but artifact.write is not "
            "available; continue the delivery step only if its tools are available and do not "
            "claim the file was written. "
        )
    return (
        f"Before the delivery step, call artifact.write with path {path!r} and the same generated "
        "final content, then continue with the requested app or communication delivery. Do not "
        "stop after writing the artifact. "
    )


def _model_followup_note_write_instruction(target: Mapping[str, Any]) -> str:
    if not bool(target.get("write_allowed")):
        return (
            "The user requested a note in Notes, but notes.create is not available. Explain "
            "the missing capability instead of claiming the note was created."
        )
    tools = _string_list(target.get("recommended_tools"))
    tool_text = ", ".join(tools) or "notes.create"
    return (
        "The user requested the transformed content be saved as a note in Notes. "
        "After deriving the final note body, call notes.create next instead of only "
        f"replying inline. Prefer {tool_text}; use the generated transformed content as "
        "the body input. Do not write the raw observed source when the user asked for "
        "summary, cleanup, translation, or todo conversion. "
    )


def _model_followup_desktop_discovered_app_instruction(target: Mapping[str, Any]) -> str:
    app_query = str(target.get("app_query") or "").strip()
    if not app_query:
        return ""
    creative_canvas = (
        target.get("creative_canvas")
        if isinstance(target.get("creative_canvas"), Mapping)
        else {}
    )
    tools = _string_list(target.get("recommended_tools"))
    verify_tools = _string_list(target.get("verify_tools"))
    target_path = str(target.get("target_path") or "").strip()
    tool_text = ", ".join(tools) or "the allowed desktop operation tools"
    verify_text = (
        f" Verify with {', '.join(verify_tools)} after the operation."
        if verify_tools
        else ""
    )
    communication_compose = (
        target.get("communication_compose")
        if isinstance(target.get("communication_compose"), Mapping)
        else {}
    )
    if communication_compose:
        recipient = str(communication_compose.get("recipient") or "").strip()
        body = str(communication_compose.get("body") or "").strip()
        send_action = str(communication_compose.get("send_action") or "draft").strip()
        transform = str(
            target.get("transform")
            or target.get("content_transform_hint")
            or ""
        ).strip()
        transform_text = f" Apply the requested content transform: {transform}." if transform else ""
        send_text = (
            " Send only through the approval-gated submit tool after the draft is filled."
            if send_action == "send"
            else " Prepare the draft only unless the user explicitly asks to send."
        )
        return (
            f"The user requested delivery through an app matching {app_query!r}. After deriving "
            f"the final content, call desktop.list_apps for {app_query!r}, select the best "
            "matching app, then open a new message in the discovered app, inspect the compose UI, fill the explicit "
            f"recipient {recipient!r}, and typing the explicit body {body!r}. "
            f"{transform_text} Prefer {tool_text}.{send_text}{verify_text} If these UI tools are unavailable, "
            "explain the missing capability instead of claiming the message was prepared. "
        )
    if target_path:
        return (
            f"The runtime discovered an app for {app_query!r}. Continue by opening "
            f"{target_path!r} with the discovered app using the allowed desktop tools. "
            f"Prefer {tool_text}.{verify_text} If direct open-with-app tooling is unavailable, "
            "explain the missing capability and do not claim the file was opened. "
        )
    if str(target.get("body_source") or "").strip() == "model_generated_content":
        safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
        container_text = (
            f" create the requested target container with {safe_shortcut_action!r}, then"
            if safe_shortcut_action
            else ""
        )
        return (
            f"The user requested the generated content be written into an app matching "
            f"{app_query!r}. After deriving the final content, call desktop.list_apps for "
            f"{app_query!r}, select the best matching app, then use desktop tools to"
            f"{container_text} insert the generated content. Prefer {tool_text}."
            f"{verify_text} Do not write the raw observed source when the user asked for "
            "summary, analysis, report generation, cleanup, translation, or todo conversion. "
            "If app discovery or text insertion tools are unavailable, explain the missing "
            "capability instead of claiming the app was updated. "
        )
    compose_text = str(target.get("compose_text") or "").strip()
    if compose_text:
        safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
        action_text = (
            f"run {safe_shortcut_action!r} in the discovered app, then type"
            if safe_shortcut_action
            else "open the discovered app, then type"
        )
        return (
            f"The runtime discovered an app for {app_query!r}. Continue by using desktop "
            f"tools to {action_text} the explicit user text {compose_text!r}. "
            f"Prefer {tool_text}.{verify_text} If text insertion tools are unavailable, "
            "explain the missing capability instead of claiming the app was updated. "
        )
    if creative_canvas:
        width = str(creative_canvas.get("width") or "").strip()
        height = str(creative_canvas.get("height") or "").strip()
        size_text = f" {width}x{height}" if width and height else ""
        return (
            f"The runtime already discovered and attempted to open the best app for {app_query!r}. "
            f"Use the latest UI observation to create or configure the requested{size_text} canvas. "
            f"Call desktop UI tools next instead of replying inline. Prefer {tool_text}."
            f"{verify_text} If the required fields are not visible, inspect the UI again before "
            "claiming completion. "
        )
    return (
        f"The runtime discovered an app for {app_query!r}. Continue the requested desktop action "
        f"with safe app or foreground tools next. Prefer {tool_text}.{verify_text} "
    )


def _model_followup_discovered_media_playback_instruction(target: Mapping[str, Any]) -> str:
    app_query = str(target.get("app_query") or "").strip()
    media_query = str(target.get("media_playback_query") or "").strip()
    if not app_query or not media_query:
        return ""
    tools = _string_list(target.get("recommended_tools"))
    verify_tools = _string_list(target.get("verify_tools"))
    tool_text = ", ".join(tools) or "the allowed desktop media operation tools"
    verify_text = (
        f" Verify with {', '.join(verify_tools)} after attempting playback."
        if verify_tools
        else ""
    )
    return (
        f"The runtime discovered an app for {app_query!r}. Continue by selecting the best "
        f"discovered app, opening its search UI, typing the media query {media_query!r}, "
        "submitting the search, and playing the first result with an allowed playback or UI "
        f"click tool. Prefer {tool_text}.{verify_text} If these tools are unavailable, explain "
        "the missing capability instead of asking the user to open the app manually. "
    )


def _model_followup_communication_instruction(target: Mapping[str, Any]) -> str:
    app_name = str(target.get("app_name") or "").strip()
    recipient = str(target.get("recipient") or "").strip()
    if not app_name or not recipient:
        return ""
    if not bool(target.get("draft_allowed")):
        return (
            f"The user requested a message to {recipient} in {app_name}, but the allowed "
            "desktop tools cannot safely focus the recipient and type a draft. Explain the "
            "missing capability instead of claiming the message was prepared."
        )
    tools = _string_list(target.get("recommended_tools"))
    verify_tools = _string_list(target.get("verify_tools"))
    transform = str(target.get("transform") or "").strip()
    transform_text = f" Apply the requested content transform: {transform}." if transform else ""
    send_text = (
        " Include the approval-gated send step only after the draft is typed."
        if bool(target.get("send_allowed"))
        else " Sending is not available in the allowed tools, so prepare the draft only."
    )
    verify_text = (
        f" Verify with {', '.join(verify_tools)} after drafting."
        if verify_tools
        else ""
    )
    return (
        f"The user requested the generated content be prepared as a message to {recipient} "
        f"in {app_name}. After deriving the final message body, call desktop tools next "
        "instead of only replying inline: focus the communication target, type the explicit "
        "recipient, submit/select the recipient, then type the generated message body."
        f"{transform_text} Prefer {', '.join(tools) or 'the allowed communication tools'}."
        f"{send_text}{verify_text} "
    )


def _latest_model_followup_target(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(timeline):
        if not isinstance(event, dict):
            continue
        if str(event.get("event") or "").strip() != "agent.model.followup_context":
            continue
        if not _followup_event_has_readable_source(event):
            return {}
        target = event.get("followup_target")
        if isinstance(target, dict):
            return dict(target)
    return {}


def _followup_event_has_readable_source(event: Mapping[str, Any]) -> bool:
    snapshots: list[dict[str, Any]] = []
    raw_snapshots = event.get("content_snapshots")
    if isinstance(raw_snapshots, list):
        snapshots.extend(item for item in raw_snapshots if isinstance(item, dict))
    raw_snapshot = event.get("content_snapshot")
    if isinstance(raw_snapshot, dict):
        snapshots.append(raw_snapshot)
    if not snapshots:
        return False
    return any(
        snapshot.get("ok") is not False
        and bool(str(snapshot.get("text") or "").strip())
        for snapshot in snapshots
    )


def _model_followup_app_write_requests(
    generated_content: str,
    target: Mapping[str, Any] | None,
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content or not isinstance(target, Mapping):
        return []
    artifact_requests = _model_followup_chained_artifact_write_requests(
        content,
        target,
        allowed_tools,
    )
    if str(target.get("kind") or "").strip() == "communication_message":
        return [
            *artifact_requests,
            *_model_followup_communication_requests(content, target, allowed_tools),
        ]
    if str(target.get("kind") or "").strip() == "artifact_write":
        return _model_followup_artifact_write_requests(content, target, allowed_tools)
    if str(target.get("kind") or "").strip() == "note_write":
        return [
            *artifact_requests,
            *_model_followup_note_write_requests(content, target, allowed_tools),
        ]
    if str(target.get("kind") or "").strip() == "desktop_discovered_app_action":
        return [
            *artifact_requests,
            *_model_followup_discovered_app_write_discovery_requests(
                content,
                target,
                allowed_tools,
            ),
        ]
    app_name = str(target.get("app_name") or "").strip()
    if str(target.get("kind") or "").strip() != "app_write" or not app_name:
        return artifact_requests
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planning_reason = "planner_followup_app_write"
    source = "runtime_planner"
    container_requests = _model_followup_container_requests(
        app_name,
        _model_followup_container_action(target),
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if _model_followup_container_action(target) and not container_requests:
        return []
    verify_request = (
        _request_like(
            "desktop.ui_elements",
            {},
            source=source,
            planning_reason=planning_reason,
        )
        if "desktop.ui_elements" in allowed
        else None
    )
    if "app.focus_and_safe_type_text" in allowed:
        requests = [
            *container_requests,
            _request_like(
                "app.focus_and_safe_type_text",
                {"app_name": app_name, "text": content},
                source=source,
                planning_reason=planning_reason,
            )
        ]
        return [*artifact_requests, *requests, *([verify_request] if verify_request else [])]
    if "app.open_and_safe_type_text" in allowed:
        requests = [
            *container_requests,
            _request_like(
                "app.open_and_safe_type_text",
                {"app_name": app_name, "text": content},
                source=source,
                planning_reason=planning_reason,
            )
        ]
        return [*artifact_requests, *requests, *([verify_request] if verify_request else [])]
    focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if focus_tool and "desktop.safe_type_text" in allowed:
        requests = [
            *container_requests,
            _request_like(
                focus_tool,
                {"app_name": app_name},
                source=source,
                planning_reason=planning_reason,
            ),
            _request_like(
                "desktop.safe_type_text",
                {"text": content},
                source=source,
                planning_reason=planning_reason,
            ),
        ]
        return [*artifact_requests, *requests, *([verify_request] if verify_request else [])]
    if focus_tool and "clipboard.write" in allowed and "desktop.safe_shortcut" in allowed:
        requests = [
            *container_requests,
            _request_like(
                "clipboard.write",
                {"text": content},
                source=source,
                planning_reason=planning_reason,
            ),
            _request_like(
                focus_tool,
                {"app_name": app_name},
                source=source,
                planning_reason=planning_reason,
            ),
            _request_like(
                "desktop.safe_shortcut",
                {"action": "paste"},
                source=source,
                planning_reason=planning_reason,
            ),
        ]
        return [*artifact_requests, *requests, *([verify_request] if verify_request else [])]
    return artifact_requests


def _model_followup_discovered_app_write_discovery_requests(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content or str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    if str(target.get("body_source") or "").strip() != "model_generated_content":
        return []
    app_query = str(target.get("app_query") or "").strip()
    if not app_query:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if "desktop.list_apps" not in allowed:
        return []
    target_action = str(target.get("target_action") or "").strip()
    safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
    communication_compose = _discovered_app_communication_compose_payload(target)
    can_prepare = False
    if target_action == "safe_shortcut" and safe_shortcut_action:
        can_prepare = (
            "app.open_and_safe_shortcut" in allowed
            or "app.focus_and_safe_shortcut" in allowed
            or (
                ("app.open" in allowed or "app.focus" in allowed)
                and "desktop.safe_shortcut" in allowed
            )
        )
    elif target_action in {"open_app", "open", "focus_app", "focus"}:
        can_prepare = "app.open" in allowed or "app.focus" in allowed
    if not can_prepare:
        return []
    if communication_compose:
        can_type = (
            "app.focus_and_type_into_ui_element" in allowed
            or "desktop.type_into_ui_element" in allowed
            or "desktop.safe_type_text" in allowed
        )
        can_send = (
            communication_compose.get("send_action") != "send"
            or "desktop.submit_foreground" in allowed
        )
        if not (can_type and "desktop.search_submit" in allowed and can_send):
            return []
        return [
            _request_like(
                "desktop.list_apps",
                {"query": app_query, "limit": 20},
                source="runtime_planner",
                planning_reason="planner_followup_discovered_app_write",
            )
        ]
    if not (
        "desktop.safe_type_text" in allowed
        or "app.focus_and_safe_type_text" in allowed
    ):
        return []
    return [
        _request_like(
            "desktop.list_apps",
            {"query": app_query, "limit": 20},
            source="runtime_planner",
            planning_reason="planner_followup_discovered_app_write",
        )
    ]


def _model_followup_discovered_app_write_requests_after_discovery(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content or str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    if str(target.get("body_source") or "").strip() != "model_generated_content":
        return []
    app_query = str(target.get("app_query") or "").strip()
    if not app_query or not _discovered_app_name_for_query(timeline, app_query):
        return []
    communication_compose = (
        target.get("communication_compose")
        if isinstance(target.get("communication_compose"), Mapping)
        else {}
    )
    followup_target = {
        **dict(target),
        "body_source": "explicit_user_text",
    }
    if communication_compose:
        followup_target["communication_compose"] = {
            **dict(communication_compose),
            "body": content,
        }
    else:
        followup_target["compose_text"] = content
    return _auto_discovered_app_followup_requests(
        {"followup_target": followup_target},
        allowed_tools,
        timeline,
        planning_reason="planner_followup_discovered_app_write",
    )


def _model_followup_chained_artifact_write_requests(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content:
        return []
    raw = (
        target.get("artifact_write")
        if isinstance(target.get("artifact_write"), Mapping)
        else {}
    )
    path = str(raw.get("path") or "").strip()
    if not path:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    tool_name = str(raw.get("tool") or "artifact.write").strip()
    if tool_name != "artifact.write" or tool_name not in allowed:
        return []
    return [
        _request_like(
            "artifact.write",
            {"path": path, "content": content},
            source="runtime_planner",
            planning_reason="planner_followup_artifact_write",
        )
    ]


def _model_followup_artifact_write_requests(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content or str(target.get("kind") or "").strip() != "artifact_write":
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if "artifact.write" not in allowed:
        return []
    path = str(target.get("path") or "").strip()
    if not path:
        return []
    return [
        _request_like(
            "artifact.write",
            {"path": path, "content": content},
            source="runtime_planner",
            planning_reason="planner_followup_artifact_write",
        )
    ]


def _model_followup_note_write_requests(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    if not content or str(target.get("kind") or "").strip() != "note_write":
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if "notes.create" not in allowed:
        return []
    payload: dict[str, Any] = {"body": content}
    title = str(target.get("title") or "").strip()
    if title:
        payload["title"] = title
    folder_name = str(target.get("folder_name") or "").strip()
    if folder_name:
        payload["folder_name"] = folder_name
    return [
        _request_like(
            "notes.create",
            payload,
            source="runtime_planner",
            planning_reason="planner_followup_note_write",
        )
    ]


def _model_followup_communication_requests(
    generated_content: str,
    target: Mapping[str, Any],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    content = str(generated_content or "").strip()
    app_name = str(target.get("app_name") or "").strip()
    recipient = str(target.get("recipient") or "").strip()
    if not content or not app_name or not recipient:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planning_reason = "planner_followup_communication"
    source = "runtime_planner"
    prepare_requests = _model_followup_communication_prepare_requests(
        app_name,
        str(target.get("mode") or "focus").strip() or "focus",
        str(target.get("channel") or "").strip(),
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if (
        not prepare_requests
        or "desktop.safe_type_text" not in allowed
        or "desktop.search_submit" not in allowed
    ):
        return []
    requests = [
        *prepare_requests,
        _request_like(
            "desktop.safe_type_text",
            {"text": recipient},
            source=source,
            planning_reason=planning_reason,
        ),
        _request_like(
            "desktop.search_submit",
            {},
            source=source,
            planning_reason=planning_reason,
        ),
        _request_like(
            "desktop.safe_type_text",
            {"text": content},
            source=source,
            planning_reason=planning_reason,
        ),
    ]
    if (
        str(target.get("send_action") or "").strip() == "send"
        and "desktop.submit_foreground" in allowed
    ):
        requests.append(
            _request_like(
                "desktop.submit_foreground",
                {"action": "send"},
                source=source,
                planning_reason=planning_reason,
            )
        )
    if "desktop.ui_elements" in allowed:
        requests.append(
            _request_like(
                "desktop.ui_elements",
                {},
                source=source,
                planning_reason=planning_reason,
            )
        )
    return requests


def _model_followup_communication_prepare_requests(
    app_name: str,
    mode: str,
    channel: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    action = _model_followup_communication_focus_action(channel)
    if mode == "open" and "app.open_and_safe_shortcut" in allowed:
        return [
            _request_like(
                "app.open_and_safe_shortcut",
                {"app_name": app_name, "action": action},
                source=source,
                planning_reason=planning_reason,
            )
        ]
    if "app.focus_and_safe_shortcut" in allowed:
        return [
            _request_like(
                "app.focus_and_safe_shortcut",
                {"app_name": app_name, "action": action},
                source=source,
                planning_reason=planning_reason,
            )
        ]
    if "app.open_and_safe_shortcut" in allowed:
        return [
            _request_like(
                "app.open_and_safe_shortcut",
                {"app_name": app_name, "action": action},
                source=source,
                planning_reason=planning_reason,
            )
        ]
    focus_tool = "app.open" if mode == "open" and "app.open" in allowed else ""
    if not focus_tool:
        focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if focus_tool and "desktop.safe_shortcut" in allowed:
        return [
            _request_like(
                focus_tool,
                {"app_name": app_name},
                source=source,
                planning_reason=planning_reason,
            ),
            _request_like(
                "desktop.safe_shortcut",
                {"action": action},
                source=source,
                planning_reason=planning_reason,
            ),
        ]
    return []


def _model_followup_container_requests(
    app_name: str,
    container_action: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    if not container_action:
        return []
    if "app.focus_and_safe_shortcut" in allowed:
        return [
            _request_like(
                "app.focus_and_safe_shortcut",
                {"app_name": app_name, "action": container_action},
                source=source,
                planning_reason=planning_reason,
            )
        ]
    if "app.open_and_safe_shortcut" in allowed:
        return [
            _request_like(
                "app.open_and_safe_shortcut",
                {"app_name": app_name, "action": container_action},
                source=source,
                planning_reason=planning_reason,
            )
        ]
    focus_tool = "app.focus" if "app.focus" in allowed else ("app.open" if "app.open" in allowed else "")
    if focus_tool and "desktop.safe_shortcut" in allowed:
        return [
            _request_like(
                focus_tool,
                {"app_name": app_name},
                source=source,
                planning_reason=planning_reason,
            ),
            _request_like(
                "desktop.safe_shortcut",
                {"action": container_action},
                source=source,
                planning_reason=planning_reason,
            ),
        ]
    return []


def _request_like(
    tool_name: str,
    payload: dict[str, Any],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    return {
        "protocol": "json_fallback",
        "tool": tool_name,
        "input": payload,
        "source": source,
        "planning_reason": planning_reason,
    }


def _followup_content_snapshot_message(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    text = str(value.get("text") or "").strip()
    if text:
        label = (
            "Desktop content snapshot"
            if str(value.get("source_tool") or "").startswith(("desktop.", "screen."))
            else "Observed content snapshot"
        )
        return f"\n\n{label}:\n{text}\n\n"
    if value.get("ok") is False:
        summary = str(value.get("summary") or value.get("error") or "").strip()
        if summary:
            return f"\n\nObservation status: {summary}\n\n"
    return ""


def _followup_content_snapshots_message(payload: dict[str, Any]) -> str:
    raw_snapshots = payload.get("content_snapshots")
    snapshots = [
        item
        for item in raw_snapshots
        if isinstance(item, dict)
    ] if isinstance(raw_snapshots, list) else []
    if not snapshots:
        return _followup_content_snapshot_message(payload.get("content_snapshot"))
    if len(snapshots) == 1:
        return _followup_content_snapshot_message(snapshots[0])
    sections: list[str] = []
    for index, snapshot in enumerate(snapshots, start=1):
        body = _followup_content_snapshot_body(snapshot)
        if not body:
            continue
        source_tool = str(snapshot.get("source_tool") or f"snapshot-{index}").strip()
        sections.append(f"[{index}] {source_tool}\n{body}")
    if not sections:
        return ""
    return "\n\nObserved context snapshots:\n\n" + "\n\n".join(sections) + "\n\n"


def _followup_content_snapshot_body(value: dict[str, Any]) -> str:
    text = str(value.get("text") or "").strip()
    if text:
        return text
    if value.get("ok") is False:
        return str(value.get("summary") or value.get("error") or "").strip()
    return ""


def _auto_data_analysis_request_from_captured_content(
    planned_tool_requests: list[dict[str, Any]],
    selection_payload: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any] | None:
    observation_tools = _ordered_text_list(
        [
            str(request.get("tool") or "").strip()
            for request in planned_tool_requests
            if isinstance(request, dict)
            and bool(request.get("continue_to_model"))
            and str(request.get("tool") or "").strip()
        ]
    )
    snapshots = followup_content_snapshots(timeline, observation_tools)
    snapshot = snapshots[-1] if snapshots else latest_followup_content_snapshot(timeline, observation_tools)
    if not snapshot or snapshot.get("ok") is False:
        return None
    source_tool = str(snapshot.get("source_tool") or "").strip()
    if source_tool == "data.analyze":
        return None
    content = str(snapshot.get("text") or "").strip()
    if not content:
        return None
    artifact_paths = _string_list(selection_payload.get("artifacts_expected"))
    if not artifact_paths:
        artifact_paths = ["analysis-report.md"]
    artifact_path = artifact_paths[0]
    input_payload: dict[str, Any] = {
        "content": content,
        "display_path": _captured_data_display_path(snapshot),
        "artifact_path": artifact_path,
        "source_kind": _captured_data_source_kind(content),
        "requested_outputs": _requested_outputs_from_artifact_paths(artifact_paths),
        "artifact_manifest": _artifact_manifest_from_paths(artifact_paths),
    }
    if len(artifact_paths) > 1:
        input_payload["artifact_paths"] = artifact_paths
    return {
        "protocol": "json_fallback",
        "tool": "data.analyze",
        "input": input_payload,
        "source": "runtime_planner",
        "planning_reason": "planner_builtin_data_analysis",
    }


def _captured_data_display_path(snapshot: dict[str, Any]) -> str:
    for key in ("path", "url", "title", "app_name", "source_tool"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            if key == "source_tool":
                return f"captured:{value}"
            return value
    return "captured:data"


def _captured_data_source_kind(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "text_table"
    if text.startswith("[") or text.startswith("{"):
        return "json"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and all(line.startswith("{") and line.endswith("}") for line in lines[:5]):
        return "jsonl"
    sample = "\n".join(lines[:5])
    if "\t" in sample:
        return "tsv"
    if "|" in sample:
        return "text_table"
    if "," in sample:
        return "csv"
    return "text_table"


def _requested_outputs_from_artifact_paths(paths: list[str]) -> list[str]:
    outputs: list[str] = []
    for path in paths:
        suffix = _artifact_path_suffix(path)
        output = {
            ".md": "report",
            ".markdown": "report",
            ".csv": "table",
            ".tsv": "table",
            ".html": "report",
            ".png": "chart",
        }.get(suffix)
        if output and output not in outputs:
            outputs.append(output)
    return outputs or ["report"]


def _artifact_manifest_from_paths(paths: list[str]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for path in paths:
        kind = {
            ".md": "markdown",
            ".markdown": "markdown",
            ".csv": "csv",
            ".tsv": "csv",
            ".html": "html",
            ".png": "chart",
        }.get(_artifact_path_suffix(path), "artifact")
        manifest.append({"path": path, "kind": kind})
    return manifest


def _artifact_path_suffix(path: str) -> str:
    clean = str(path or "").strip().lower()
    index = clean.rfind(".")
    return clean[index:] if index >= 0 else ""


def _visible_daily_desktop_completed_steps(
    completed_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_indexes = [
        index
        for index, step in enumerate(completed_steps)
        if not _is_daily_desktop_discovery_completed_step(step)
        and str(step.get("tool") or "") not in _DAILY_DESKTOP_VERIFY_TOOLS
    ]
    if not primary_indexes:
        visible_steps = list(completed_steps)
        while (
            len(visible_steps) > 1
            and _is_daily_desktop_discovery_prefix_completed_step(visible_steps[0])
        ):
            visible_steps = visible_steps[1:]
        return visible_steps
    first_primary = primary_indexes[0]
    last_primary = primary_indexes[-1]
    visible_steps: list[dict[str, Any]] = []
    for index, step in enumerate(completed_steps):
        tool_name = str(step.get("tool") or "")
        if (
            _is_daily_desktop_discovery_completed_step(step)
            and (index < first_primary or index > last_primary)
        ):
            continue
        if (
            tool_name in _DAILY_DESKTOP_VERIFY_TOOLS
            and index > last_primary
            and not _is_requested_ui_readback(completed_steps, index, first_primary, last_primary)
            and not _is_preserved_active_window_verification(completed_steps, index)
            and not _is_preserved_runtime_planner_verification(
                completed_steps,
                index,
                last_primary,
            )
        ):
            continue
        visible_steps.append(step)
    return visible_steps or completed_steps


def _is_daily_desktop_discovery_completed_step(step: dict[str, Any]) -> bool:
    tool_name = str(step.get("tool") or "")
    if tool_name in _DAILY_DESKTOP_DISCOVERY_TOOLS:
        return True
    return tool_name == "desktop.inspect_app" and isinstance(step.get("result"), dict)


def _is_daily_desktop_discovery_prefix_completed_step(step: dict[str, Any]) -> bool:
    tool_name = str(step.get("tool") or "")
    if tool_name in _DAILY_DESKTOP_DISCOVERY_PREFIX_TOOLS:
        return True
    return tool_name == "desktop.inspect_app" and isinstance(step.get("result"), dict)


def _drop_trailing_daily_desktop_verify_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(requests) <= 1:
        return requests
    if any(bool(request.get("continue_to_model")) for request in requests if isinstance(request, dict)):
        return requests
    if _direct_action_with_active_window_verification(requests):
        return requests
    last_primary = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if (
            tool_name not in _DAILY_DESKTOP_DISCOVERY_TOOLS
            and tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS
        ):
            last_primary = index
    if last_primary < 0:
        return requests
    return [
        request
        for index, request in enumerate(requests)
        if index <= last_primary
        or str(request.get("tool") or "").strip() not in _DAILY_DESKTOP_VERIFY_TOOLS
        or _is_preserved_runtime_planner_verification(requests, index, last_primary)
    ]


def _is_preserved_runtime_planner_verification(
    requests: list[dict[str, Any]],
    index: int,
    last_primary: int,
) -> bool:
    if index <= last_primary:
        return False
    request = requests[index]
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS:
        return False
    planning_reason = str(request.get("planning_reason") or "").strip()
    if planning_reason != "planner_desktop_operation":
        return False
    previous_primary = str(requests[last_primary].get("tool") or "").strip()
    return previous_primary.startswith(("app.", "desktop."))


def _direct_action_with_active_window_verification(
    requests: list[dict[str, Any]],
) -> bool:
    tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]
    if "desktop.active_window" not in tools:
        return False
    primary_tools = [
        tool
        for tool in tools
        if tool not in _DAILY_DESKTOP_DISCOVERY_TOOLS
        and tool not in _DAILY_DESKTOP_VERIFY_TOOLS
    ]
    return bool(primary_tools) and set(primary_tools) <= {
        "app.open",
        "app.focus",
        "desktop.close_window",
        "desktop.minimize_window",
        "desktop.quit_app",
    }


def _planned_daily_desktop_tools(
    planned_tool_requests: list[dict[str, Any]],
) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in planned_tool_requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]


def _is_preserved_active_window_verification(
    completed_steps: list[dict[str, Any]],
    index: int,
) -> bool:
    if str(completed_steps[index].get("tool") or "") != "desktop.active_window":
        return False
    return _direct_action_with_active_window_verification(completed_steps)


def _daily_desktop_sequence_summary_steps(
    visible_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not visible_steps:
        return []
    if (
        str(visible_steps[-1].get("tool") or "") == "desktop.active_window"
        and _direct_action_with_active_window_verification(visible_steps)
    ):
        primary_steps = [
            step
            for step in visible_steps
            if str(step.get("tool") or "") != "desktop.active_window"
        ]
        return primary_steps or visible_steps
    return visible_steps


def _is_requested_ui_readback(
    completed_steps: list[dict[str, Any]],
    index: int,
    first_primary: int,
    last_primary: int,
) -> bool:
    if str(completed_steps[index].get("tool") or "") != "desktop.ui_elements":
        return False
    primary_tools = {
        str(step.get("tool") or "")
        for step in completed_steps[first_primary : last_primary + 1]
        if isinstance(step, dict)
    }
    return bool(primary_tools) and primary_tools.issubset(
        {
            "app.open",
            "app.focus",
            "system.settings_open",
        }
    )


def _latest_workspace_list_event(timeline: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        if str(event.get("detail") or event.get("tool") or "").strip() in {
            "workspace.list",
            "fs.find_files",
            "file.search",
        }:
            return event
    return None


def _data_analysis_file_kind(path: str) -> str:
    lowered = str(path or "").strip().lower()
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".tsv"):
        return "tsv"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".jsonl"):
        return "jsonl"
    if lowered.endswith(".xlsx"):
        return "xlsx"
    return ""


def _join_workspace_list_path(base_path: str, name: str) -> str:
    clean_name = str(name or "").strip().strip("/")
    clean_base = str(base_path or "").strip().strip("/")
    if not clean_base or clean_base == ".":
        return clean_name
    return posixpath.normpath(posixpath.join(clean_base, clean_name))


def _display_target_name(value: str, suffix: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0].isascii():
        return f" {text} {suffix}".rstrip()
    return f"{text}{suffix}"


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
        "open_command": "确认当前运行环境可以调用 macOS open 命令，且目标 App 名称正确。",
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


def _ordered_text_list(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
