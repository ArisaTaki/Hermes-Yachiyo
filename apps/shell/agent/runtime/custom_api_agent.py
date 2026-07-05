"""Custom API Agent model/tool loop."""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from apps.shell.agent.runtime.approval_tool_sets import (
    APPROVAL_PLAN_TOOLS as _DAILY_DESKTOP_APPROVAL_PLAN_TOOLS,
)
from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_metadata_tool_request,
    daily_desktop_intent_candidates,
    daily_desktop_intent_tool_requests,
)
from apps.shell.agent.runtime.desktop_tool_labels import (
    DAILY_DESKTOP_TOOL_LABELS as _DAILY_DESKTOP_TOOL_LABELS,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.event_scopes import (
    runtime_event_payload as _runtime_task_progress_event_payload,
    runtime_planner_base_event_type as _runtime_planner_base_event_type,
    runtime_planner_event_payload as _runtime_planner_event_payload,
    runtime_planner_event_type as _runtime_planner_event_type,
    runtime_planner_timeline_event as _runtime_planner_timeline_event,
    runtime_progress_base_event_type as _runtime_progress_base_event_type,
    runtime_progress_event_payload as _runtime_progress_event_payload,
    runtime_progress_event_type as _runtime_progress_event_type,
    runtime_replan_base_event_type as _runtime_replan_event_type,
    runtime_replan_request_event_payload as _runtime_replan_request_event_payload,
    runtime_replan_request_event_type as _runtime_replan_request_event_type,
    runtime_scope_context as _runtime_planner_scope_context,
)
from apps.shell.agent.runtime.followup_content_snapshot import (
    followup_content_snapshot_for_tool_call,
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
from apps.shell.yachiyo_agent.app_name_hints import compact_app_name_hint
from apps.shell.yachiyo_agent.desktop_plan_hints import (
    click_target_hint,
    type_into_ui_hint,
)
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    DirectToolSelection,
    planner_first_direct_tool_selection,
)
from apps.shell.yachiyo_agent.capability_registry import capability_snapshots
from apps.shell.yachiyo_agent.planner_execution import (
    planner_execution_tool_requests,
    planner_tool_requests,
    runtime_execution_verified_tool_requests,
)
from apps.shell.yachiyo_agent.planner_projection import (
    planner_selection_payload,
    runtime_planner_decision,
)
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_payload,
    runtime_execution_requests_from_envelope_payload,
)
from apps.shell.yachiyo_agent.runtime_doctrine import YACHIYO_RUNTIME_OPERATING_MANUAL

_DIRECT_DAILY_DESKTOP_TOOLS = {
    *DAILY_DESKTOP_TOOL_NAMES,
    "artifact.write",
    "data.analyze",
    "terminal.run",
}

_RUNTIME_REPLAN_ACTION_AUTO_SAFE_TOOLS = {
    "app.focus",
    "app.open",
    "browser.current_page",
    "browser.screenshot",
    "desktop.active_window",
    "desktop.focus_app",
    "desktop.list_apps",
    "desktop.open_app",
    "desktop.read_ui",
    "desktop.running_apps",
    "desktop.ui_elements",
    "desktop.windows",
    "file.read",
    "fs.read_file",
    "screen.capture",
    "workspace.read",
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

_DISCOVERED_APP_SELECTION_SOURCES = {
    "desktop.list_apps",
    "desktop.running_apps",
}

_DISCOVERED_APP_PLACEHOLDERS = {
    "desktop.list_apps": "<selected app from desktop.list_apps>",
    "desktop.running_apps": "<selected app from desktop.running_apps>",
}

_DAILY_DESKTOP_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.list_windows",
    "desktop.read_ui",
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

_OPEN_PATH_WITH_APP_TOOLS = {"desktop.open_path_with_app", "app.open_path_with_app"}

_DISCOVERED_APP_DIRECT_COMPLETION_TOOLS = {
    "app.open",
    "desktop.open_app",
    "app.focus",
    "desktop.focus_app",
    *_OPEN_PATH_WITH_APP_TOOLS,
}

_DISCOVERED_APP_DIRECT_VERIFICATION_TOOLS = {
    *_DAILY_DESKTOP_VERIFY_TOOLS,
    "screen.capture",
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
        runtime_planner_decision = None
        planned_tool_requests: list[dict[str, Any]] = []
        direct_tool_selection_payload: dict[str, Any] = {}
        if not default_messages:
            resumed_result = self._direct_existing_daily_desktop_result(
                agent,
                timeline,
                run_id=run_id,
            )
            if resumed_result:
                return resumed_result
            if start_iteration > 0:
                replan_recovery_result = self._run_pending_runtime_replan_recovery(
                    allowed_tools,
                    broker,
                    messages,
                    timeline,
                    artifacts,
                    agent=agent,
                    run_id=run_id,
                    budget=budget,
                    next_iteration=start_iteration,
                )
                if replan_recovery_result:
                    return replan_recovery_result
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
            planner_replan_only = False
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
                    daily_unavailable_candidates = daily_desktop_intent_candidates(
                        planning_context
                    )
                    planner_unavailable_payloads = []
                    if not daily_unavailable_candidates:
                        planner_unavailable_payloads = (
                            _runtime_planner_unavailable_failure_payloads(
                                runtime_planner_decision
                            )
                            if runtime_planner_decision is not None
                            else []
                        )
                    if planner_unavailable_payloads:
                        self._record_runtime_planner_events(
                            runtime_planner_decision,
                            timeline=timeline,
                            run_id=run_id,
                            scope_context=_runtime_planner_scope_context(
                                direct_tool_selection_payload,
                                timeline=timeline,
                            ),
                        )
                        self._record_direct_tool_selection_event(
                            direct_tool_selection_payload,
                            timeline=timeline,
                            run_id=run_id,
                            scope_context=_runtime_planner_scope_context(
                                direct_tool_selection_payload,
                                timeline=timeline,
                            ),
                        )
                        replan_payloads = self._record_runtime_planner_replan_events(
                            runtime_planner_decision,
                            timeline=timeline,
                            tool_timeline_start=len(timeline),
                            run_id=run_id,
                        )
                        if replan_payloads:
                            self._append_replan_followup_context(
                                replan_payloads,
                                allowed_tools=allowed_tools,
                                messages=messages,
                                timeline=timeline,
                                run_id=run_id,
                            )
                        planner_replan_only = True
            if planned_tool_requests:
                if runtime_planner_decision is not None:
                    planner_scope_context = _runtime_planner_scope_context(
                        planned_tool_requests,
                        direct_tool_selection_payload,
                        timeline=timeline,
                    )
                    self._record_runtime_planner_events(
                        runtime_planner_decision,
                        timeline=timeline,
                        run_id=run_id,
                        scope_context=planner_scope_context,
                    )
                else:
                    planner_scope_context = _runtime_planner_scope_context(
                        planned_tool_requests,
                        direct_tool_selection_payload,
                        timeline=timeline,
                    )
                self._record_direct_tool_selection_event(
                    direct_tool_selection_payload,
                    timeline=timeline,
                    run_id=run_id,
                    scope_context=planner_scope_context,
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
                    for key in (
                        "step_id",
                        "capability_id",
                        "replan_request_id",
                        "replan_trigger",
                    ):
                        value = str(planned_tool_request.get(key) or "").strip()
                        if value:
                            planned_payload[key] = value
                    planned_payload.update(
                        _request_observability_metadata(planned_tool_request)
                    )
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
                execution_tool_requests = _split_model_materialization_tool_requests(
                    execution_tool_requests
                )[0]
                execution_tool_requests = _split_combined_foreground_app_requests(
                    execution_tool_requests,
                    allowed_tools,
                )
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
                explicit_model_followup_requested = any(
                    bool(request.get("continue_to_model"))
                    for request in planned_tool_requests
                    if isinstance(request, dict)
                )
                tool_timeline_start = len(timeline)
                try:
                    if execution_tool_requests:
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
                    self._record_runtime_planner_task_progress_events(
                        runtime_planner_decision,
                        timeline=timeline,
                        tool_timeline_start=tool_timeline_start,
                        run_id=run_id,
                    )
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
                        planned_request=approval_request,
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
                if replan_payloads and _timeline_has_permission_recovery_signal(
                    timeline,
                    tool_timeline_start,
                ):
                    replan_payloads = []
                self._record_runtime_planner_task_progress_events(
                    runtime_planner_decision,
                    timeline=timeline,
                    tool_timeline_start=tool_timeline_start,
                    run_id=run_id,
                )
                explicit_model_followup = explicit_model_followup_requested
                auto_permission_recovery_requests = _auto_direct_permission_recovery_requests(
                    execution_tool_requests,
                    allowed_tools,
                    timeline,
                    tool_timeline_start=tool_timeline_start,
                )
                if auto_permission_recovery_requests:
                    recovery_timeline_start = self._run_auto_runtime_planner_requests(
                        auto_permission_recovery_requests,
                        allowed_tools,
                        broker,
                        messages,
                        timeline,
                        artifacts,
                        agent=agent,
                        runtime_planner_decision=runtime_planner_decision,
                        run_id=run_id,
                        budget=budget,
                        next_iteration=start_iteration,
                    )
                    auto_permission_retry_requests = _auto_direct_permission_retry_requests(
                        auto_permission_recovery_requests,
                        allowed_tools,
                        timeline,
                        tool_timeline_start=recovery_timeline_start,
                    )
                    retry_timeline_start = len(timeline)
                    if auto_permission_retry_requests:
                        retry_timeline_start = self._run_auto_runtime_planner_requests(
                            auto_permission_retry_requests,
                            allowed_tools,
                            broker,
                            messages,
                            timeline,
                            artifacts,
                            agent=agent,
                            runtime_planner_decision=runtime_planner_decision,
                            run_id=run_id,
                            budget=budget,
                            next_iteration=start_iteration,
                        )
                    planned_tool_requests = [
                        *planned_tool_requests,
                        *auto_permission_recovery_requests,
                        *auto_permission_retry_requests,
                    ]
                    explicit_model_followup = (
                        explicit_model_followup_requested
                        if auto_permission_retry_requests
                        and _auto_direct_permission_retry_completed(
                            auto_permission_retry_requests,
                            timeline,
                            tool_timeline_start=retry_timeline_start,
                        )
                        else True
                    )
                if (
                    explicit_model_followup
                    and not replan_payloads
                    and not _selection_payload_has_model_followup_target(
                        direct_tool_selection_payload
                    )
                    and _runtime_planner_completed_discovered_app_direct_action(
                        execution_tool_requests,
                        direct_tool_selection_payload,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                ):
                    explicit_model_followup = False
                if (
                    explicit_model_followup
                    and not replan_payloads
                    and _runtime_planner_followup_requests_are_only_verification(
                        planned_tool_requests
                    )
                    and _runtime_planner_completed_direct_requests_with_successful_verification(
                        execution_tool_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                ):
                    explicit_model_followup = False
                if (
                    replan_payloads
                    and not explicit_model_followup
                    and _runtime_planner_completed_direct_requests_with_unavailable_replan(
                        execution_tool_requests,
                        replan_payloads,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                ):
                    replan_payloads = []
                if (
                    replan_payloads
                    and not explicit_model_followup
                    and _runtime_planner_completed_direct_requests_with_verification_replan(
                        execution_tool_requests,
                        replan_payloads,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                ):
                    replan_payloads = []
                continue_to_model = bool(replan_payloads) or explicit_model_followup
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
                    auto_replan_recovery_requests = (
                        _auto_replan_recovery_requests_with_task_context(
                            replan_payloads,
                            allowed_tools,
                            timeline,
                        )
                    )
                    if auto_replan_recovery_requests:
                        self._record_auto_model_followup_app_write_plan(
                            auto_replan_recovery_requests,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_permission_preflight(
                            auto_replan_recovery_requests,
                            broker,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_tool_policy_decisions(
                            auto_replan_recovery_requests,
                            allowed_tools=allowed_tools,
                            agent=agent,
                            run_id=run_id,
                        )
                        auto_tool_timeline_start = len(timeline)
                        auto_replan_approval_requests = auto_replan_recovery_requests
                        try:
                            self._run_tool_requests(
                                auto_replan_recovery_requests,
                                allowed_tools,
                                broker,
                                messages,
                                timeline,
                                artifacts,
                                next_iteration=start_iteration,
                                run_id=run_id,
                                budget=budget,
                            )
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            auto_replan_continuation_requests = (
                                _auto_replan_discovered_app_continuation_requests(
                                    replan_payloads,
                                    execution_tool_requests,
                                    allowed_tools,
                                    timeline,
                                )
                            )
                            if auto_replan_continuation_requests:
                                auto_replan_approval_requests = [
                                    *auto_replan_recovery_requests,
                                    *auto_replan_continuation_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_replan_continuation_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_replan_continuation_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_replan_continuation_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                continuation_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_replan_continuation_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=continuation_timeline_start,
                                    run_id=run_id,
                                )
                                auto_replan_recovery_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_replan_recovery_requests
                                    ),
                                    *auto_replan_continuation_requests,
                                ]
                            auto_replan_verification_continuation_requests = (
                                _auto_replan_verification_continuation_requests(
                                    replan_payloads,
                                    execution_tool_requests,
                                    allowed_tools,
                                    timeline,
                                    tool_timeline_start=tool_timeline_start,
                                    planning_reason=(
                                        "planner_replan_verification_continuation"
                                    ),
                                )
                            )
                            if auto_replan_verification_continuation_requests:
                                auto_replan_approval_requests = [
                                    *auto_replan_approval_requests,
                                    *auto_replan_verification_continuation_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_replan_verification_continuation_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_replan_verification_continuation_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_replan_verification_continuation_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                verification_continuation_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_replan_verification_continuation_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=(
                                        verification_continuation_timeline_start
                                    ),
                                    run_id=run_id,
                                )
                                auto_replan_recovery_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_replan_recovery_requests
                                    ),
                                    *auto_replan_verification_continuation_requests,
                                ]
                            auto_replan_verification_observed_action_requests = (
                                _auto_replan_verification_observed_action_requests(
                                    replan_payloads,
                                    execution_tool_requests,
                                    allowed_tools,
                                    timeline,
                                    planning_reason=(
                                        "planner_replan_verification_observed_action"
                                    ),
                                )
                            )
                            if auto_replan_verification_observed_action_requests:
                                auto_replan_approval_requests = [
                                    *auto_replan_approval_requests,
                                    *auto_replan_verification_observed_action_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_replan_verification_observed_action_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_replan_verification_observed_action_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_replan_verification_observed_action_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                verification_observed_action_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_replan_verification_observed_action_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=(
                                        verification_observed_action_timeline_start
                                    ),
                                    run_id=run_id,
                                )
                                auto_replan_recovery_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_replan_recovery_requests
                                    ),
                                    *auto_replan_verification_observed_action_requests,
                                ]
                            auto_replan_ui_observed_action_requests = (
                                _auto_replan_ui_observed_action_requests(
                                    replan_payloads,
                                    allowed_tools,
                                    timeline,
                                    planning_reason="planner_replan_ui_observed_action",
                                )
                            )
                            if auto_replan_ui_observed_action_requests:
                                auto_replan_approval_requests = [
                                    *auto_replan_approval_requests,
                                    *auto_replan_ui_observed_action_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_replan_ui_observed_action_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_replan_ui_observed_action_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_replan_ui_observed_action_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                observed_ui_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_replan_ui_observed_action_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=observed_ui_timeline_start,
                                    run_id=run_id,
                                )
                                auto_replan_recovery_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_replan_recovery_requests
                                    ),
                                    *auto_replan_ui_observed_action_requests,
                                ]
                                auto_replan_ui_continuation_requests = (
                                    _auto_replan_ui_continuation_requests(
                                        replan_payloads,
                                        execution_tool_requests,
                                        allowed_tools,
                                        timeline,
                                        tool_timeline_start=tool_timeline_start,
                                        planning_reason="planner_replan_ui_continuation",
                                    )
                                )
                                if auto_replan_ui_continuation_requests:
                                    auto_replan_approval_requests = [
                                        *auto_replan_approval_requests,
                                        *auto_replan_ui_continuation_requests,
                                    ]
                                    self._record_auto_model_followup_app_write_plan(
                                        auto_replan_ui_continuation_requests,
                                        timeline=timeline,
                                        run_id=run_id,
                                    )
                                    self._record_desktop_permission_preflight(
                                        auto_replan_ui_continuation_requests,
                                        broker,
                                        timeline=timeline,
                                        run_id=run_id,
                                    )
                                    self._record_desktop_tool_policy_decisions(
                                        auto_replan_ui_continuation_requests,
                                        allowed_tools=allowed_tools,
                                        agent=agent,
                                        run_id=run_id,
                                    )
                                    ui_continuation_timeline_start = len(timeline)
                                    self._run_tool_requests(
                                        auto_replan_ui_continuation_requests,
                                        allowed_tools,
                                        broker,
                                        messages,
                                        timeline,
                                        artifacts,
                                        next_iteration=start_iteration,
                                        run_id=run_id,
                                        budget=budget,
                                    )
                                    self._record_runtime_planner_task_progress_events(
                                        runtime_planner_decision,
                                        timeline=timeline,
                                        tool_timeline_start=ui_continuation_timeline_start,
                                        run_id=run_id,
                                    )
                                    auto_replan_recovery_requests = [
                                        *auto_replan_recovery_requests,
                                        *auto_replan_ui_continuation_requests,
                                    ]
                                auto_replan_ui_observed_result_requests = (
                                    _auto_replan_ui_search_observed_result_requests(
                                        replan_payloads,
                                        execution_tool_requests,
                                        allowed_tools,
                                        timeline,
                                        planning_reason=(
                                            "planner_replan_ui_search_observed_result"
                                        ),
                                    )
                                )
                                if auto_replan_ui_observed_result_requests:
                                    auto_replan_approval_requests = [
                                        *auto_replan_approval_requests,
                                        *auto_replan_ui_observed_result_requests,
                                    ]
                                    self._record_auto_model_followup_app_write_plan(
                                        auto_replan_ui_observed_result_requests,
                                        timeline=timeline,
                                        run_id=run_id,
                                    )
                                    self._record_desktop_permission_preflight(
                                        auto_replan_ui_observed_result_requests,
                                        broker,
                                        timeline=timeline,
                                        run_id=run_id,
                                    )
                                    self._record_desktop_tool_policy_decisions(
                                        auto_replan_ui_observed_result_requests,
                                        allowed_tools=allowed_tools,
                                        agent=agent,
                                        run_id=run_id,
                                    )
                                    ui_observed_result_timeline_start = len(timeline)
                                    self._run_tool_requests(
                                        auto_replan_ui_observed_result_requests,
                                        allowed_tools,
                                        broker,
                                        messages,
                                        timeline,
                                        artifacts,
                                        next_iteration=start_iteration,
                                        run_id=run_id,
                                        budget=budget,
                                    )
                                    self._record_runtime_planner_task_progress_events(
                                        runtime_planner_decision,
                                        timeline=timeline,
                                        tool_timeline_start=(
                                            ui_observed_result_timeline_start
                                        ),
                                        run_id=run_id,
                                    )
                                    auto_replan_recovery_requests = [
                                        *auto_replan_recovery_requests,
                                        *auto_replan_ui_observed_result_requests,
                                    ]
                            else:
                                auto_replan_ui_observed_result_requests = []
                            auto_replan_observed_result_requests = []
                            if not auto_replan_ui_observed_result_requests:
                                auto_replan_observed_result_requests = (
                                    _auto_replan_app_search_observed_result_requests(
                                        replan_payloads,
                                        followup_selection_payload,
                                        allowed_tools,
                                        timeline,
                                        planning_reason=(
                                            "planner_replan_app_search_observed_result"
                                        ),
                                    )
                                )
                            if auto_replan_observed_result_requests:
                                auto_replan_approval_requests = [
                                    *auto_replan_approval_requests,
                                    *auto_replan_observed_result_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_replan_observed_result_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_replan_observed_result_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_replan_observed_result_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                observed_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_replan_observed_result_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=observed_timeline_start,
                                    run_id=run_id,
                                )
                                auto_replan_recovery_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_replan_recovery_requests
                                    ),
                                    *auto_replan_observed_result_requests,
                                ]
                        except AgentApprovalRequired as exc:
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            pending_approval = (
                                exc.pending_approval
                                if isinstance(exc.pending_approval, dict)
                                else {}
                            )
                            planned_tool = str(
                                pending_approval.get("tool")
                                or auto_replan_approval_requests[0].get("tool")
                                or ""
                            )
                            approval_request = self._planned_request_for_tool(
                                auto_replan_approval_requests,
                                planned_tool,
                            )
                            planned_input = self._pending_approval_input_preview(
                                pending_approval,
                                approval_request,
                                (
                                    auto_replan_approval_requests[0]
                                    if auto_replan_approval_requests
                                    else {}
                                ),
                            )
                            self._record_desktop_intent_approval_required(
                                planned_tool,
                                planned_input,
                                pending_approval=exc.pending_approval,
                                timeline=timeline,
                                run_id=run_id,
                                planned_request=approval_request,
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
                        planned_tool_requests = [
                            *planned_tool_requests,
                            *auto_replan_recovery_requests,
                        ]
                        if not _replan_recovery_requests_need_model_followup(
                            auto_replan_recovery_requests
                        ):
                            direct_result = self._direct_daily_desktop_sequence_result(
                                auto_replan_recovery_requests,
                                timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            if direct_result:
                                return direct_result
                    if replan_payloads and not _auto_deferred_observed_ui_can_complete_without_model(
                        planned_tool_requests,
                        allowed_tools,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    ):
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
                        for key in (
                            "step_id",
                            "capability_id",
                            "replan_request_id",
                            "replan_trigger",
                        ):
                            value = str(auto_followup_request.get(key) or "").strip()
                            if value:
                                auto_payload[key] = value
                        auto_payload.update(
                            _request_observability_metadata(auto_followup_request)
                        )
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
                        auto_tool_timeline_start = len(timeline)
                        try:
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
                        finally:
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
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
                    auto_deferred_observed_ui_requests = (
                        _auto_deferred_observed_ui_followup_requests(
                            planned_tool_requests,
                            allowed_tools,
                            timeline,
                        )
                    )
                    auto_deferred_observed_ui_requests = _drop_completed_auto_followup_prefix(
                        auto_deferred_observed_ui_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                    if auto_deferred_observed_ui_requests:
                        self._record_auto_model_followup_app_write_plan(
                            auto_deferred_observed_ui_requests,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_permission_preflight(
                            auto_deferred_observed_ui_requests,
                            broker,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_tool_policy_decisions(
                            auto_deferred_observed_ui_requests,
                            allowed_tools=allowed_tools,
                            agent=agent,
                            run_id=run_id,
                        )
                        auto_tool_timeline_start = len(timeline)
                        try:
                            self._run_tool_requests(
                                auto_deferred_observed_ui_requests,
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
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            pending_approval = (
                                exc.pending_approval
                                if isinstance(exc.pending_approval, dict)
                                else {}
                            )
                            planned_tool = str(
                                pending_approval.get("tool")
                                or auto_deferred_observed_ui_requests[0].get("tool")
                                or ""
                            )
                            approval_request = self._planned_request_for_tool(
                                auto_deferred_observed_ui_requests,
                                planned_tool,
                            )
                            planned_input = self._pending_approval_input_preview(
                                pending_approval,
                                approval_request,
                                (
                                    auto_deferred_observed_ui_requests[0]
                                    if auto_deferred_observed_ui_requests
                                    else {}
                                ),
                            )
                            self._record_desktop_intent_approval_required(
                                planned_tool,
                                planned_input,
                                pending_approval=exc.pending_approval,
                                timeline=timeline,
                                run_id=run_id,
                                planned_request=approval_request,
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
                        self._record_runtime_planner_task_progress_events(
                            runtime_planner_decision,
                            timeline=timeline,
                            tool_timeline_start=auto_tool_timeline_start,
                            run_id=run_id,
                        )
                        deferred_direct_result = (
                            self._run_deferred_observed_ui_replan_recovery(
                                runtime_planner_decision,
                                auto_deferred_observed_ui_requests,
                                allowed_tools,
                                broker,
                                messages,
                                timeline,
                                artifacts,
                                agent=agent,
                                run_id=run_id,
                                budget=budget,
                                next_iteration=start_iteration,
                                tool_timeline_start=auto_tool_timeline_start,
                            )
                        )
                        if deferred_direct_result:
                            return deferred_direct_result
                        nested_deferred_observed_ui_requests = (
                            _auto_deferred_observed_ui_followup_requests(
                                auto_deferred_observed_ui_requests,
                                allowed_tools,
                                timeline,
                            )
                        )
                        nested_deferred_observed_ui_requests = _drop_completed_auto_followup_prefix(
                            nested_deferred_observed_ui_requests,
                            timeline,
                            tool_timeline_start=auto_tool_timeline_start,
                        )
                        if nested_deferred_observed_ui_requests:
                            self._record_auto_model_followup_app_write_plan(
                                nested_deferred_observed_ui_requests,
                                timeline=timeline,
                                run_id=run_id,
                            )
                            self._record_desktop_permission_preflight(
                                nested_deferred_observed_ui_requests,
                                broker,
                                timeline=timeline,
                                run_id=run_id,
                            )
                            self._record_desktop_tool_policy_decisions(
                                nested_deferred_observed_ui_requests,
                                allowed_tools=allowed_tools,
                                agent=agent,
                                run_id=run_id,
                            )
                            nested_tool_timeline_start = len(timeline)
                            try:
                                self._run_tool_requests(
                                    nested_deferred_observed_ui_requests,
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
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=nested_tool_timeline_start,
                                    run_id=run_id,
                                )
                                pending_approval = (
                                    exc.pending_approval
                                    if isinstance(exc.pending_approval, dict)
                                    else {}
                                )
                                planned_tool = str(
                                    pending_approval.get("tool")
                                    or nested_deferred_observed_ui_requests[0].get("tool")
                                    or ""
                                )
                                approval_request = self._planned_request_for_tool(
                                    nested_deferred_observed_ui_requests,
                                    planned_tool,
                                )
                                planned_input = self._pending_approval_input_preview(
                                    pending_approval,
                                    approval_request,
                                    (
                                        nested_deferred_observed_ui_requests[0]
                                        if nested_deferred_observed_ui_requests
                                        else {}
                                    ),
                                )
                                self._record_desktop_intent_approval_required(
                                    planned_tool,
                                    planned_input,
                                    pending_approval=exc.pending_approval,
                                    timeline=timeline,
                                    run_id=run_id,
                                    planned_request=approval_request,
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
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=nested_tool_timeline_start,
                                run_id=run_id,
                            )
                            nested_deferred_direct_result = (
                                self._run_deferred_observed_ui_replan_recovery(
                                    runtime_planner_decision,
                                    nested_deferred_observed_ui_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    agent=agent,
                                    run_id=run_id,
                                    budget=budget,
                                    next_iteration=start_iteration,
                                    tool_timeline_start=nested_tool_timeline_start,
                                )
                            )
                            if nested_deferred_direct_result:
                                return nested_deferred_direct_result
                            direct_result = self._direct_daily_desktop_sequence_result(
                                nested_deferred_observed_ui_requests,
                                timeline,
                                tool_timeline_start=nested_tool_timeline_start,
                                run_id=run_id,
                            )
                            if direct_result:
                                return direct_result
                        direct_result = self._direct_daily_desktop_sequence_result(
                            auto_deferred_observed_ui_requests,
                            timeline,
                            tool_timeline_start=auto_tool_timeline_start,
                            run_id=run_id,
                        )
                        if direct_result:
                            return direct_result
                    auto_discovered_app_requests = _auto_discovered_followup_requests(
                        followup_selection_payload,
                        allowed_tools,
                        timeline,
                    )
                    auto_discovered_app_requests = _drop_completed_auto_followup_prefix(
                        auto_discovered_app_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
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
                        auto_discovered_app_approval_requests = auto_discovered_app_requests
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
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            auto_observed_result_requests = (
                                _auto_discovered_app_search_observed_result_requests(
                                    followup_selection_payload,
                                    allowed_tools,
                                    timeline,
                                )
                            )
                            if auto_observed_result_requests:
                                auto_discovered_app_approval_requests = [
                                    *auto_discovered_app_requests,
                                    *auto_observed_result_requests,
                                ]
                                self._record_auto_model_followup_app_write_plan(
                                    auto_observed_result_requests,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_permission_preflight(
                                    auto_observed_result_requests,
                                    broker,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                self._record_desktop_tool_policy_decisions(
                                    auto_observed_result_requests,
                                    allowed_tools=allowed_tools,
                                    agent=agent,
                                    run_id=run_id,
                                )
                                observed_tool_timeline_start = len(timeline)
                                self._run_tool_requests(
                                    auto_observed_result_requests,
                                    allowed_tools,
                                    broker,
                                    messages,
                                    timeline,
                                    artifacts,
                                    next_iteration=start_iteration,
                                    run_id=run_id,
                                    budget=budget,
                                )
                                self._record_runtime_planner_task_progress_events(
                                    runtime_planner_decision,
                                    timeline=timeline,
                                    tool_timeline_start=observed_tool_timeline_start,
                                    run_id=run_id,
                                )
                                auto_discovered_app_requests = [
                                    *_tool_requests_without_model_followup(
                                        auto_discovered_app_requests
                                    ),
                                    *auto_observed_result_requests,
                                ]
                        except AgentApprovalRequired as exc:
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=auto_tool_timeline_start,
                                run_id=run_id,
                            )
                            pending_approval = (
                                exc.pending_approval
                                if isinstance(exc.pending_approval, dict)
                                else {}
                            )
                            planned_tool = str(
                                pending_approval.get("tool")
                                or auto_discovered_app_approval_requests[0].get("tool")
                                or ""
                            )
                            approval_request = self._planned_request_for_tool(
                                auto_discovered_app_approval_requests,
                                planned_tool,
                            )
                            planned_input = self._pending_approval_input_preview(
                                pending_approval,
                                approval_request,
                                (
                                    auto_discovered_app_approval_requests[0]
                                    if auto_discovered_app_approval_requests
                                    else {}
                                ),
                            )
                            self._record_desktop_intent_approval_required(
                                planned_tool,
                                planned_input,
                                pending_approval=exc.pending_approval,
                                timeline=timeline,
                                run_id=run_id,
                                planned_request=approval_request,
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
                    auto_code_context_requests = _auto_code_context_read_requests(
                        followup_selection_payload,
                        allowed_tools,
                        timeline,
                    )
                    auto_code_context_requests = _drop_completed_auto_followup_prefix(
                        auto_code_context_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                    if auto_code_context_requests:
                        auto_tool_timeline_start = len(timeline)
                        self._run_tool_requests(
                            auto_code_context_requests,
                            allowed_tools,
                            broker,
                            messages,
                            timeline,
                            artifacts,
                            next_iteration=start_iteration,
                            run_id=run_id,
                            budget=budget,
                        )
                        self._record_runtime_planner_task_progress_events(
                            runtime_planner_decision,
                            timeline=timeline,
                            tool_timeline_start=auto_tool_timeline_start,
                            run_id=run_id,
                        )
                        planned_tool_requests = [
                            *planned_tool_requests,
                            *auto_code_context_requests,
                        ]
                    if not replan_payloads:
                        self._append_model_followup_context(
                            planned_tool_requests,
                            followup_selection_payload,
                            allowed_tools=allowed_tools,
                            messages=messages,
                            timeline=timeline,
                            run_id=run_id,
                        )
                    direct_result = ""
                elif len(_tool_requests_without_model_followup(execution_tool_requests)) == 1:
                    completed_execution_tool_requests = _tool_requests_without_model_followup(
                        execution_tool_requests
                    )
                    planned_tool = str(completed_execution_tool_requests[0].get("tool") or "")
                    planned_input = completed_execution_tool_requests[0].get("input") or {}
                    presentation = str(
                        completed_execution_tool_requests[0].get("presentation") or ""
                    ).strip()
                    direct_result = self._direct_daily_desktop_result(
                        agent,
                        planned_tool,
                        planned_input,
                        timeline,
                        run_id=run_id,
                        presentation=presentation,
                        source=str(
                            completed_execution_tool_requests[0].get("source")
                            or "daily_desktop_intent"
                        ),
                        planning_reason=str(
                            completed_execution_tool_requests[0].get("planning_reason") or ""
                        ),
                    )
                else:
                    completed_execution_tool_requests = _tool_requests_without_model_followup(
                        execution_tool_requests
                    )
                    direct_result = self._direct_daily_desktop_sequence_result(
                        completed_execution_tool_requests,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                        run_id=run_id,
                    )
                if (
                    not direct_result
                    and _tool_requests_have_unresolved_discovered_app(
                        execution_tool_requests
                    )
                    and not _timeline_has_model_followup_context(
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                ):
                    self._append_model_followup_context(
                        planned_tool_requests,
                        _selection_payload_with_timeline_fallback(
                            direct_tool_selection_payload,
                            timeline,
                        ),
                        allowed_tools=allowed_tools,
                        messages=messages,
                        timeline=timeline,
                        run_id=run_id,
                    )
                if direct_result:
                    return direct_result
            elif not planner_replan_only:
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
        if (
            planned_tool_requests
            and _tool_requests_have_unresolved_discovered_app(planned_tool_requests)
            and not _latest_message_is_model_followup_context(messages)
        ):
            self._append_model_followup_context(
                planned_tool_requests,
                _selection_payload_with_timeline_fallback(
                    direct_tool_selection_payload,
                    timeline,
                ),
                allowed_tools=allowed_tools,
                messages=messages,
                timeline=timeline,
                run_id=run_id,
            )
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
            tool_requests = _tool_requests_with_pending_plan_metadata(
                tool_requests,
                timeline,
            )
            tool_requests = runtime_execution_verified_tool_requests(
                tool_requests,
                allowed_tools,
                include_model_app_foreground=not (
                    _model_tool_requests_are_verification_recovery_actions(
                        tool_requests
                    )
                ),
            )
            detail = content[:500] if content else ", ".join(
                request["tool"] for request in tool_requests
            )[:500]
            timeline.append(self._timeline("agent.model.response", detail))
            if not tool_requests:
                if not content.strip():
                    raise self._error_type("Native Agent 模型返回了空回复")
                followup_context = _latest_model_followup_context(
                    timeline,
                    include_pending_execution_only=True,
                )
                followup_target = _model_followup_context_target(followup_context)
                auto_app_write_requests = _model_followup_app_write_requests(
                    content,
                    followup_target,
                    allowed_tools,
                    followup_context=followup_context,
                )
                auto_app_write_requests = (
                    _model_followup_requests_with_pending_plan_metadata(
                        auto_app_write_requests,
                        followup_context,
                    )
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
                        discovered_app_write_requests = (
                            _model_followup_requests_with_pending_plan_metadata(
                                discovered_app_write_requests,
                                followup_context,
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
                            planned_request=approval_request,
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
                else:
                    auto_pending_plan_requests = _model_followup_pending_plan_requests(
                        followup_context,
                        allowed_tools,
                        generated_content=content,
                        timeline=timeline,
                    )
                    if auto_pending_plan_requests:
                        messages.append({"role": "assistant", "content": content})
                        self._record_auto_model_followup_app_write_plan(
                            auto_pending_plan_requests,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_permission_preflight(
                            auto_pending_plan_requests,
                            broker,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        self._record_desktop_tool_policy_decisions(
                            auto_pending_plan_requests,
                            allowed_tools=allowed_tools,
                            agent=agent,
                            run_id=run_id,
                        )
                        tool_timeline_start = len(timeline)
                        try:
                            self._run_tool_requests(
                                auto_pending_plan_requests,
                                allowed_tools,
                                broker,
                                messages,
                                timeline,
                                artifacts,
                                next_iteration=iteration + 1,
                                run_id=run_id,
                                budget=budget,
                            )
                        except AgentApprovalRequired as exc:
                            self._record_runtime_planner_task_progress_events(
                                runtime_planner_decision,
                                timeline=timeline,
                                tool_timeline_start=tool_timeline_start,
                                run_id=run_id,
                            )
                            pending_approval = (
                                exc.pending_approval if isinstance(exc.pending_approval, dict) else {}
                            )
                            planned_tool = str(
                                pending_approval.get("tool")
                                or auto_pending_plan_requests[0].get("tool")
                                or ""
                            )
                            approval_request = self._planned_request_for_tool(
                                auto_pending_plan_requests,
                                planned_tool,
                            )
                            planned_input = self._pending_approval_input_preview(
                                pending_approval,
                                approval_request,
                                (
                                    auto_pending_plan_requests[0]
                                    if auto_pending_plan_requests
                                    else {}
                                ),
                            )
                            self._record_desktop_intent_approval_required(
                                planned_tool,
                                planned_input,
                                pending_approval=exc.pending_approval,
                                timeline=timeline,
                                run_id=run_id,
                                planned_request=approval_request,
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
                        self._record_runtime_planner_task_progress_events(
                            runtime_planner_decision,
                            timeline=timeline,
                            tool_timeline_start=tool_timeline_start,
                            run_id=run_id,
                        )
                        if runtime_planner_decision is None:
                            self._record_model_followup_pending_plan_progress_events(
                                followup_context,
                                auto_pending_plan_requests,
                                timeline=timeline,
                                tool_timeline_start=tool_timeline_start,
                                run_id=run_id,
                            )
                            replan_payloads = (
                                self._record_model_followup_pending_plan_replan_events(
                                    followup_context,
                                    auto_pending_plan_requests,
                                    timeline=timeline,
                                    tool_timeline_start=tool_timeline_start,
                                    run_id=run_id,
                                )
                            )
                            if replan_payloads:
                                self._append_replan_followup_context(
                                    replan_payloads,
                                    allowed_tools=allowed_tools,
                                    messages=messages,
                                    timeline=timeline,
                                    run_id=run_id,
                                )
                                continue
                        direct_result = self._direct_daily_desktop_sequence_result(
                            auto_pending_plan_requests,
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
            followup_context = _latest_model_followup_context(timeline)
            tool_timeline_start = len(timeline)
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
            if followup_context:
                self._record_model_followup_pending_plan_progress_events(
                    followup_context,
                    tool_requests,
                    timeline=timeline,
                    tool_timeline_start=tool_timeline_start,
                    run_id=run_id,
                )
                replan_payloads = self._record_model_followup_pending_plan_replan_events(
                    followup_context,
                    tool_requests,
                    timeline=timeline,
                    tool_timeline_start=tool_timeline_start,
                    run_id=run_id,
                )
                if replan_payloads:
                    self._append_replan_followup_context(
                        replan_payloads,
                        allowed_tools=allowed_tools,
                        messages=messages,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    continue
                auto_pending_continuation_requests = (
                    _model_followup_pending_plan_continuation_requests(
                        followup_context,
                        tool_requests,
                        allowed_tools,
                        timeline,
                        tool_timeline_start=tool_timeline_start,
                    )
                )
                if auto_pending_continuation_requests:
                    self._record_auto_model_followup_app_write_plan(
                        auto_pending_continuation_requests,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    self._record_desktop_permission_preflight(
                        auto_pending_continuation_requests,
                        broker,
                        timeline=timeline,
                        run_id=run_id,
                    )
                    self._record_desktop_tool_policy_decisions(
                        auto_pending_continuation_requests,
                        allowed_tools=allowed_tools,
                        agent=agent,
                        run_id=run_id,
                    )
                    continuation_timeline_start = len(timeline)
                    try:
                        self._run_tool_requests(
                            auto_pending_continuation_requests,
                            allowed_tools,
                            broker,
                            messages,
                            timeline,
                            artifacts,
                            next_iteration=iteration + 1,
                            run_id=run_id,
                            budget=budget,
                        )
                    except AgentApprovalRequired as exc:
                        self._record_model_followup_pending_plan_progress_events(
                            followup_context,
                            auto_pending_continuation_requests,
                            timeline=timeline,
                            tool_timeline_start=continuation_timeline_start,
                            run_id=run_id,
                        )
                        pending_approval = (
                            exc.pending_approval if isinstance(exc.pending_approval, dict) else {}
                        )
                        planned_tool = str(
                            pending_approval.get("tool")
                            or auto_pending_continuation_requests[0].get("tool")
                            or ""
                        )
                        approval_request = self._planned_request_for_tool(
                            auto_pending_continuation_requests,
                            planned_tool,
                        )
                        planned_input = self._pending_approval_input_preview(
                            pending_approval,
                            approval_request,
                            (
                                auto_pending_continuation_requests[0]
                                if auto_pending_continuation_requests
                                else {}
                            ),
                        )
                        self._record_desktop_intent_approval_required(
                            planned_tool,
                            planned_input,
                            pending_approval=exc.pending_approval,
                            timeline=timeline,
                            run_id=run_id,
                            planned_request=approval_request,
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
                    self._record_model_followup_pending_plan_progress_events(
                        followup_context,
                        auto_pending_continuation_requests,
                        timeline=timeline,
                        tool_timeline_start=continuation_timeline_start,
                        run_id=run_id,
                    )
                    continuation_replan_payloads = (
                        self._record_model_followup_pending_plan_replan_events(
                            followup_context,
                            auto_pending_continuation_requests,
                            timeline=timeline,
                            tool_timeline_start=continuation_timeline_start,
                            run_id=run_id,
                        )
                    )
                    if continuation_replan_payloads:
                        self._append_replan_followup_context(
                            continuation_replan_payloads,
                            allowed_tools=allowed_tools,
                            messages=messages,
                            timeline=timeline,
                            run_id=run_id,
                        )
                        continue
                    direct_result = self._direct_daily_desktop_sequence_result(
                        auto_pending_continuation_requests,
                        timeline,
                        tool_timeline_start=continuation_timeline_start,
                        run_id=run_id,
                    )
                    if direct_result:
                        return direct_result
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
        if _preserve_direct_daily_desktop_tool_requests(cleaned):
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
        prefetch_tools = {
            str(request.get("tool") or "").strip()
            for request in planned_tool_requests
            if isinstance(request, dict) and bool(request.get("continue_to_model"))
        }
        if "workspace.list" in prefetch_tools:
            latest_list = _latest_workspace_list_event(timeline)
            if latest_list is None:
                return None
            result = latest_list.get("result") if isinstance(latest_list.get("result"), dict) else {}
            entries = result.get("entries")
            data_entries: list[Mapping[str, Any]] = []
            if isinstance(entries, list):
                data_entries = [
                    entry
                    for entry in entries
                    if isinstance(entry, dict)
                    and str(entry.get("type") or "").strip() == "file"
                    and _data_analysis_file_kind(
                        str(entry.get("name") or entry.get("path") or "")
                    )
                    != ""
                ]
            if result.get("ok") is not True or not data_entries:
                return None
            list_input = (
                latest_list.get("input_preview")
                if isinstance(latest_list.get("input_preview"), dict)
                else {}
            )
            base_path = str(list_input.get("path") or result.get("path") or "").strip()
            artifact_paths = _string_list(selection_payload.get("artifacts_expected"))
            if not artifact_paths:
                artifact_paths = ["analysis-report.md"]
            selection = str(list_input.get("selection") or "").strip().lower()
            input_payload = _data_analysis_input_from_workspace_entries(
                base_path,
                data_entries,
                selection,
                artifact_paths,
            )
            if not input_payload:
                return None
            if len(artifact_paths) > 1:
                input_payload["artifact_paths"] = artifact_paths
            return _first_annotated_auto_followup_request(
                {
                    "protocol": "json_fallback",
                    "tool": "data.analyze",
                    "input": input_payload,
                    "source": "runtime_planner",
                    "planning_reason": "planner_builtin_data_analysis",
                },
                selection_payload,
            )
        return _auto_data_analysis_request_from_captured_content(
            planned_tool_requests,
            selection_payload,
            timeline,
        )

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
            if request.get("continue_to_model"):
                payload["continue_to_model"] = True
            for key in ("step_id", "capability_id", "replan_request_id", "replan_trigger"):
                value = str(request.get(key) or "").strip()
                if value:
                    payload[key] = value
            payload.update(_request_observability_metadata(request))
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
                preview = dict(candidate)
                if isinstance(planned_request, Mapping):
                    for key, value in _request_observability_metadata(
                        planned_request
                    ).items():
                        preview.setdefault(key, value)
                return preview
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

    def _runtime_planner_tool_requests(
        self,
        planning_context: str,
        allowed_tools: list[str],
    ) -> tuple[Any | None, list[dict[str, Any]], dict[str, Any]]:
        try:
            selection: DirectToolSelection = planner_first_direct_tool_selection(
                planning_context,
                allowed_tools,
                metadata={"runtime_planner_execution_context": True},
            )
            if selection.selected_source == "runtime_planner" and selection.decision is not None:
                runtime_trace_metadata = _runtime_planner_request_trace_metadata(
                    selection.decision
                )
                full_plan_requests = _runtime_planner_full_plan_tool_requests(
                    selection.decision,
                    allowed_tools,
                ) or planner_tool_requests(
                    planning_context,
                    allowed_tools,
                    metadata=runtime_trace_metadata,
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
                execution_requests = _discovered_app_resolution_probe_requests(
                    execution_requests,
                    selection.event_payload,
                )
                execution_requests = _dedupe_runtime_planner_full_plan_requests(
                    execution_requests
                )
                execution_requests = _runtime_planner_execution_requests_with_selection_inputs(
                    execution_requests,
                    selection.requests,
                )
                has_approval_plan_tool = self._has_approval_plan_tool(execution_requests)
                if execution_requests and (
                    not has_approval_plan_tool
                    or _direct_action_with_active_window_verification(execution_requests)
                    or runtime_trace_metadata is not None
                ):
                    selection_payload = planner_selection_payload(
                        decision=selection.decision,
                        planner_requests=full_plan_requests,
                        legacy_requests=[],
                        selected_requests=execution_requests,
                        selected_source="runtime_planner",
                        selected_reason="runtime_planner_full_plan_execution",
                        metadata=runtime_trace_metadata,
                    )
                    selection_payload = _selection_payload_with_runtime_execution_envelope(
                        selection_payload,
                        selection.decision,
                        allowed_tools,
                        full_plan=True,
                        execution_requests=execution_requests,
                    )
                    return (
                        selection.decision,
                        execution_requests,
                        selection_payload,
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
            execution_requests = _discovered_app_resolution_probe_requests(
                execution_requests,
                selection.event_payload,
            )
            if not execution_requests and not selection.requests:
                unavailable_decision = runtime_planner_decision(
                    planning_context,
                    allowed_tools=allowed_tools,
                )
                if (
                    unavailable_decision is not None
                    and _runtime_planner_unavailable_failure_payloads(unavailable_decision)
                ):
                    return (
                        unavailable_decision,
                        [],
                        planner_selection_payload(
                            decision=unavailable_decision,
                            planner_requests=[],
                            legacy_requests=[],
                            selected_requests=[],
                            selected_source="runtime_planner",
                            selected_reason="runtime_planner_unavailable_plan",
                        ),
                    )
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
            if (
                selection.selected_source == "runtime_planner"
                and selection.decision is not None
                and _tool_requests_include_model_followup(execution_requests)
            ):
                event_payload = _selection_payload_with_runtime_execution_envelope(
                    event_payload,
                    selection.decision,
                    allowed_tools,
                    full_plan=True,
                )
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
        scope_context: Mapping[str, Any] | None = None,
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
            timeline.append(_runtime_planner_timeline_event(event, scope_context))
        if run_id and self._append_run_event is not None:
            for event_type, payload in planner_run_event_payloads(decision):
                scoped_event_type = _runtime_planner_event_type(event_type, scope_context)
                event_payload = _runtime_planner_event_payload(
                    payload,
                    event_type,
                    scoped_event_type,
                    scope_context,
                )
                self._append_run_event(run_id, scoped_event_type, event_payload)
        self._record_runtime_planner_initial_task_events(
            decision,
            timeline=timeline,
            run_id=run_id,
            scope_context=scope_context,
        )

    def _record_runtime_planner_initial_task_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
        scope_context: Mapping[str, Any] | None = None,
    ) -> None:
        for event_type, detail, payload in _runtime_planner_initial_task_updates(decision):
            event_payload = {**dict(scope_context or {}), **dict(payload)}
            if _runtime_task_update_exists(timeline, event_type, event_payload):
                continue
            _append_runtime_task_progress_event(
                event_type,
                detail,
                event_payload,
                timeline=timeline,
                timeline_factory=self._timeline,
                append_run_event=self._append_run_event,
                run_id=run_id,
            )

    def _record_direct_tool_selection_event(
        self,
        payload: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        run_id: str = "",
        scope_context: Mapping[str, Any] | None = None,
    ) -> None:
        if not payload:
            return
        event_payload = {**dict(scope_context or {}), **dict(payload)}
        detail = str(
            event_payload.get("selection_source")
            or event_payload.get("selection_reason")
            or "direct_tool_selection"
        )
        event_type = "agent.plan.selection"
        scoped_event_type = _runtime_planner_event_type(event_type, event_payload)
        event_payload = _runtime_planner_event_payload(
            event_payload,
            event_type,
            scoped_event_type,
            event_payload,
        )
        timeline.append(
            self._timeline(
                scoped_event_type,
                detail,
                **event_payload,
            )
        )
        if run_id and self._append_run_event is not None:
            self._append_run_event(run_id, scoped_event_type, event_payload)

    def _run_auto_runtime_planner_requests(
        self,
        requests: list[dict[str, Any]],
        allowed_tools: Iterable[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        agent: dict[str, Any],
        runtime_planner_decision: Any,
        run_id: str,
        budget: Any,
        next_iteration: int,
    ) -> int:
        if not requests:
            return len(timeline)
        self._record_auto_model_followup_app_write_plan(
            requests,
            timeline=timeline,
            run_id=run_id,
        )
        self._record_desktop_permission_preflight(
            requests,
            broker,
            timeline=timeline,
            run_id=run_id,
        )
        self._record_desktop_tool_policy_decisions(
            requests,
            allowed_tools=allowed_tools,
            agent=agent,
            run_id=run_id,
        )
        tool_timeline_start = len(timeline)
        try:
            self._run_tool_requests(
                requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                next_iteration=next_iteration,
                run_id=run_id,
                budget=budget,
            )
            continuation_requests = _auto_replan_recovery_deferred_continuation_requests(
                requests,
                allowed_tools,
                timeline,
                tool_timeline_start=tool_timeline_start,
            )
            if continuation_requests:
                self._record_auto_model_followup_app_write_plan(
                    continuation_requests,
                    timeline=timeline,
                    run_id=run_id,
                )
                self._record_desktop_permission_preflight(
                    continuation_requests,
                    broker,
                    timeline=timeline,
                    run_id=run_id,
                )
                self._record_desktop_tool_policy_decisions(
                    continuation_requests,
                    allowed_tools=allowed_tools,
                    agent=agent,
                    run_id=run_id,
                )
                self._run_tool_requests(
                    continuation_requests,
                    allowed_tools,
                    broker,
                    messages,
                    timeline,
                    artifacts,
                    next_iteration=next_iteration,
                    run_id=run_id,
                    budget=budget,
                )
        except AgentApprovalRequired as exc:
            self._record_runtime_planner_task_progress_events(
                runtime_planner_decision,
                timeline=timeline,
                tool_timeline_start=tool_timeline_start,
                run_id=run_id,
            )
            pending_approval = (
                exc.pending_approval if isinstance(exc.pending_approval, dict) else {}
            )
            planned_tool = str(
                pending_approval.get("tool") or requests[0].get("tool") or ""
            )
            approval_request = self._planned_request_for_tool(requests, planned_tool)
            planned_input = self._pending_approval_input_preview(
                pending_approval,
                approval_request,
                requests[0] if requests else {},
            )
            self._record_desktop_intent_approval_required(
                planned_tool,
                planned_input,
                pending_approval=exc.pending_approval,
                timeline=timeline,
                run_id=run_id,
                planned_request=approval_request,
                source=self._approval_event_source(approval_request, planned_tool),
                planning_reason=self._approval_event_planning_reason(
                    approval_request,
                    planned_tool,
                ),
            )
            raise
        self._record_runtime_planner_task_progress_events(
            runtime_planner_decision,
            timeline=timeline,
            tool_timeline_start=tool_timeline_start,
            run_id=run_id,
        )
        return tool_timeline_start

    def _run_pending_runtime_replan_recovery(
        self,
        allowed_tools: Iterable[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        agent: dict[str, Any],
        run_id: str,
        budget: Any,
        next_iteration: int,
    ) -> str:
        replan_payloads = _pending_runtime_replan_payloads(timeline)
        if not replan_payloads:
            return ""
        allowed_tool_list = list(allowed_tools)
        recovery_requests = _auto_replan_recovery_requests_with_task_context(
            replan_payloads,
            allowed_tool_list,
            timeline,
        )
        if not recovery_requests:
            if not _timeline_has_replan_followup_context(timeline, replan_payloads):
                self._append_replan_followup_context(
                    replan_payloads,
                    allowed_tools=allowed_tool_list,
                    messages=messages,
                    timeline=timeline,
                    run_id=run_id,
                )
            return ""

        recovery_timeline_start = self._run_auto_runtime_planner_requests(
            recovery_requests,
            allowed_tool_list,
            broker,
            messages,
            timeline,
            artifacts,
            agent=agent,
            runtime_planner_decision=None,
            run_id=run_id,
            budget=budget,
            next_iteration=next_iteration,
        )
        if not _replan_recovery_requests_need_model_followup(recovery_requests):
            direct_result = self._direct_daily_desktop_sequence_result(
                _tool_requests_without_model_followup(recovery_requests),
                timeline,
                tool_timeline_start=recovery_timeline_start,
                run_id=run_id,
            )
            if direct_result:
                return direct_result
        if not _timeline_has_replan_followup_context(timeline, replan_payloads):
            self._append_replan_followup_context(
                replan_payloads,
                allowed_tools=allowed_tool_list,
                messages=messages,
                timeline=timeline,
                run_id=run_id,
            )
        return ""

    def _run_deferred_observed_ui_replan_recovery(
        self,
        runtime_planner_decision: Any,
        planned_tool_requests: list[dict[str, Any]],
        allowed_tools: Iterable[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        agent: dict[str, Any],
        run_id: str,
        budget: Any,
        next_iteration: int,
        tool_timeline_start: int,
    ) -> str:
        replan_payloads = self._record_runtime_planner_replan_events(
            runtime_planner_decision,
            timeline=timeline,
            tool_timeline_start=tool_timeline_start,
            run_id=run_id,
        )
        if replan_payloads and _timeline_has_permission_recovery_signal(
            timeline,
            tool_timeline_start,
        ):
            replan_payloads = []
        if not replan_payloads:
            return ""

        recovery_requests: list[dict[str, Any]] = []
        recovery_timeline_start = len(timeline)
        observation_requests = _auto_replan_ui_observation_recovery_requests(
            replan_payloads,
            allowed_tools,
        )
        if observation_requests:
            self._run_auto_runtime_planner_requests(
                observation_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                agent=agent,
                runtime_planner_decision=runtime_planner_decision,
                run_id=run_id,
                budget=budget,
                next_iteration=next_iteration,
            )
            recovery_requests.extend(observation_requests)

        continuation_requests = _auto_replan_ui_continuation_requests(
            replan_payloads,
            planned_tool_requests,
            allowed_tools,
            timeline,
            tool_timeline_start=tool_timeline_start,
            planning_reason="planner_replan_ui_continuation",
        )
        if continuation_requests:
            self._run_auto_runtime_planner_requests(
                continuation_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                agent=agent,
                runtime_planner_decision=runtime_planner_decision,
                run_id=run_id,
                budget=budget,
                next_iteration=next_iteration,
            )
            recovery_requests.extend(continuation_requests)

        observed_action_requests = (
            []
            if continuation_requests
            else _auto_replan_ui_observed_action_requests(
                replan_payloads,
                allowed_tools,
                timeline,
                planning_reason="planner_replan_ui_observed_action",
            )
        )
        if observed_action_requests:
            self._run_auto_runtime_planner_requests(
                observed_action_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                agent=agent,
                runtime_planner_decision=runtime_planner_decision,
                run_id=run_id,
                budget=budget,
                next_iteration=next_iteration,
            )
            recovery_requests.extend(observed_action_requests)

            continuation_requests = _auto_replan_ui_continuation_requests(
                replan_payloads,
                planned_tool_requests,
                allowed_tools,
                timeline,
                tool_timeline_start=tool_timeline_start,
                planning_reason="planner_replan_ui_continuation",
            )
            if continuation_requests:
                self._run_auto_runtime_planner_requests(
                    continuation_requests,
                    allowed_tools,
                    broker,
                    messages,
                    timeline,
                    artifacts,
                    agent=agent,
                    runtime_planner_decision=runtime_planner_decision,
                    run_id=run_id,
                    budget=budget,
                    next_iteration=next_iteration,
                )
                recovery_requests.extend(continuation_requests)

            observed_result_requests = _auto_replan_ui_search_observed_result_requests(
                replan_payloads,
                planned_tool_requests,
                allowed_tools,
                timeline,
                planning_reason="planner_replan_ui_search_observed_result",
            )
            if observed_result_requests:
                self._run_auto_runtime_planner_requests(
                    observed_result_requests,
                    allowed_tools,
                    broker,
                    messages,
                    timeline,
                    artifacts,
                    agent=agent,
                    runtime_planner_decision=runtime_planner_decision,
                    run_id=run_id,
                    budget=budget,
                    next_iteration=next_iteration,
                )
                recovery_requests.extend(observed_result_requests)

        if not recovery_requests:
            return ""
        return self._direct_daily_desktop_sequence_result(
            _tool_requests_without_model_followup(recovery_requests),
            timeline,
            tool_timeline_start=recovery_timeline_start,
            run_id=run_id,
        )

    def _record_runtime_planner_replan_events(
        self,
        decision: Any,
        *,
        timeline: list[dict[str, Any]],
        tool_timeline_start: int,
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        existing_payloads = _timeline_replan_request_payloads(
            timeline,
            start=tool_timeline_start,
        )
        if decision is None:
            return existing_payloads
        try:
            from apps.shell.yachiyo_agent.planner_projection import (
                planner_replan_timeline_event,
            )
        except Exception:
            return existing_payloads
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
            and _runtime_replan_event_type(
                str(event.get("event") or event.get("event_type") or "").strip()
            )
            == "agent.replan.requested"
        }
        existing_payload_by_key = {
            key: index
            for index, payload in enumerate(existing_payloads)
            for key in [_replan_payload_dedupe_key(payload)]
            if key
        }
        tool_events = [
            event
            for event in list(timeline[tool_timeline_start:])
            if isinstance(event, dict)
            and str(event.get("event") or "").strip()
            in {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
        ]
        step_payloads = _runtime_planner_tool_event_step_payloads(decision, tool_events)
        failure_payloads: list[dict[str, Any]] = []
        for event_index, event in enumerate(tool_events):
            result = event.get("result") if isinstance(event.get("result"), dict) else {}
            if event.get("verification_failed") is True:
                result = {**result, "verification_failed": True}
            if not _tool_result_requests_replan(result):
                continue
            tool_name = str(event.get("detail") or "").strip()
            step_payload = step_payloads.get(event_index, {})
            step_metadata = (
                step_payload.get("metadata")
                if isinstance(step_payload.get("metadata"), Mapping)
                else {}
            )
            input_preview = (
                event.get("input_preview")
                if isinstance(event.get("input_preview"), dict)
                else {}
            )
            failure_payload = {
                "event_type": str(event.get("event") or "agent.tool.call").strip(),
                "tool_name": tool_name,
                "input_preview": input_preview,
                "result": result,
                **{
                    key: value
                    for key, value in step_payload.items()
                    if key != "metadata"
                },
            }
            if result.get("verification_failed") is True:
                failure_payload["trigger"] = "verification_failed"
                failure_payload["status"] = "verification_failed"
            event_trace_metadata = _runtime_trace_metadata_from_mapping(event)
            recovery_metadata = _runtime_replan_failure_metadata(result)
            if step_metadata or input_preview or event_trace_metadata or recovery_metadata:
                metadata = {
                    **dict(step_metadata),
                    **event_trace_metadata,
                    **recovery_metadata,
                }
                if input_preview:
                    metadata.setdefault("input_preview", dict(input_preview))
                failure_payload["metadata"] = metadata
            failure_payloads.append(failure_payload)
        failure_payloads.extend(
            _runtime_planner_verification_failure_payloads(
                decision,
                list(timeline[tool_timeline_start:]),
            )
        )
        if not failure_payloads:
            failure_payloads.extend(_runtime_planner_unavailable_failure_payloads(decision))
        payloads: list[dict[str, Any]] = list(existing_payloads)
        for failure_payload in failure_payloads:
            replan_metadata = (
                failure_payload.get("metadata")
                if isinstance(failure_payload.get("metadata"), Mapping)
                else {}
            )
            replan_event = planner_replan_timeline_event(
                decision,
                failure_payload,
                run_id=run_id,
                metadata=replan_metadata,
            )
            if not replan_event:
                continue
            payload = (
                replan_event.get("payload")
                if isinstance(replan_event.get("payload"), dict)
                else {}
            )
            payload_dict = dict(payload)
            dedupe_key = _replan_payload_dedupe_key(payload_dict)
            if dedupe_key and dedupe_key in existing_payload_by_key:
                payloads[existing_payload_by_key[dedupe_key]] = payload_dict
                continue
            request_id = str(payload.get("request_id") or "").strip()
            if request_id and request_id in existing_request_ids:
                continue
            if request_id:
                existing_request_ids.add(request_id)
            timeline.append(replan_event)
            payloads.append(payload_dict)
            if run_id and self._append_run_event is not None:
                self._append_run_event(run_id, "agent.replan.requested", payload_dict)
        return payloads

    def _record_model_followup_pending_plan_replan_events(
        self,
        followup_context: Mapping[str, Any],
        planned_tool_requests: list[dict[str, Any]],
        *,
        timeline: list[dict[str, Any]],
        tool_timeline_start: int,
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        payloads = _model_followup_pending_plan_replan_payloads(
            followup_context,
            planned_tool_requests,
            timeline,
            tool_timeline_start=tool_timeline_start,
            run_id=run_id,
        )
        if not payloads:
            return []
        existing_request_ids = {
            str(
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), Mapping)
                    else {}
                ).get("request_id")
                or event.get("request_id")
                or ""
            ).strip()
            for event in timeline
            if isinstance(event, Mapping)
            and _runtime_replan_event_type(
                str(event.get("event") or event.get("event_type") or "").strip()
            )
            == "agent.replan.requested"
        }
        existing_keys = {
            key
            for event in timeline
            if isinstance(event, Mapping)
            and _runtime_replan_event_type(
                str(event.get("event") or event.get("event_type") or "").strip()
            )
            == "agent.replan.requested"
            for payload in [
                (
                    event.get("payload")
                    if isinstance(event.get("payload"), Mapping)
                    else event
                )
            ]
            for key in [_replan_payload_dedupe_key(payload)]
            if key
        }
        recorded: list[dict[str, Any]] = []
        for payload in payloads:
            request_id = str(payload.get("request_id") or "").strip()
            if request_id and request_id in existing_request_ids:
                continue
            dedupe_key = _replan_payload_dedupe_key(payload)
            if dedupe_key and dedupe_key in existing_keys:
                continue
            if request_id:
                existing_request_ids.add(request_id)
            if dedupe_key:
                existing_keys.add(dedupe_key)
            event_type = _runtime_replan_request_event_type(payload)
            event_payload = _runtime_replan_request_event_payload(payload, event_type)
            detail = str(
                payload.get("reason")
                or payload.get("failure_detail")
                or payload.get("trigger")
                or "Runtime requested a replan."
            ).strip()
            event_fields = {
                "status": str(payload.get("status") or "requested"),
                "source": str(payload.get("source") or "runtime_planner"),
                "decision_id": str(payload.get("decision_id") or ""),
                "plan_id": str(payload.get("plan_id") or ""),
                "payload": event_payload,
            }
            for key in (
                "task_id",
                "run_id",
                "core_id",
                "group_run_id",
                "run_group_id",
                "group_id",
                "workflow_run_id",
                "workflow_id",
                "workflow_node_id",
                "workflow_node_label",
            ):
                value = str(event_payload.get(key) or payload.get(key) or "").strip()
                if value:
                    event_fields[key] = value
            timeline.append(self._timeline(event_type, detail, **event_fields))
            recorded.append(dict(payload))
            if run_id and self._append_run_event is not None:
                self._append_run_event(run_id, event_type, event_payload)
        return recorded

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
        workspace = getattr(task_core, "workspace", None)
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
        workspace_items_by_step: dict[str, list[Any]] = {}
        for item in list(getattr(workspace, "items", []) if workspace is not None else []):
            step_id = str(getattr(item, "source_step_id", "") or "").strip()
            if not step_id:
                continue
            workspace_items_by_step.setdefault(step_id, []).append(item)
        tool_events = [
            event
            for event in timeline[tool_timeline_start:]
            if isinstance(event, dict)
            and str(event.get("event") or "").strip()
            in {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
        ]
        event_index = 0
        core_id = str(getattr(task_core, "core_id", "") or "").strip()
        workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
        plan_id = str(getattr(plan, "plan_id", "") or "").strip()
        decision_id = str(getattr(decision, "decision_id", "") or "").strip()
        for step in steps:
            tool_name = str(getattr(step, "tool_name", "") or "").strip()
            step_id = str(getattr(step, "step_id", "") or "").strip()
            if not tool_name or not step_id:
                continue
            tool_event: dict[str, Any] | None = None
            scan_index = event_index
            while scan_index < len(tool_events):
                candidate = tool_events[scan_index]
                candidate_step_id = str(
                    candidate.get("step_id") or candidate.get("planner_step_id") or ""
                ).strip()
                if (
                    candidate_step_id == step_id
                    or (
                        not candidate_step_id
                        and str(candidate.get("detail") or "").strip() == tool_name
                    )
                ):
                    tool_event = candidate
                    event_index = scan_index + 1
                    break
                scan_index += 1
            if tool_event is None:
                continue
            result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
            todo_status = _task_todo_status_for_tool_result(
                str(tool_event.get("event") or ""),
                result,
            )
            checkpoint_status = _task_checkpoint_status_for_todo_status(todo_status, result)
            skip_statuses = {todo_status}
            if todo_status != "completed":
                skip_statuses.add("completed")
            if _runtime_planner_step_has_status(
                timeline,
                decision_id=decision_id,
                step_id=step_id,
                statuses=skip_statuses,
            ):
                continue
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
            base_payload.update(
                _runtime_task_progress_scope_context(
                    timeline,
                    tool_event,
                    decision_id=decision_id,
                    plan_id=plan_id,
                )
            )
            for workspace_item in workspace_items_by_step.get(step_id, []):
                item_payload = _snapshot_payload(workspace_item)
                item_payload["status"] = todo_status
                payload = {
                    **base_payload,
                    "workspace_item_id": str(
                        getattr(workspace_item, "item_id", "") or ""
                    ).strip(),
                    "status": todo_status,
                    "previous_status": str(
                        getattr(workspace_item, "status", "") or "planned"
                    ),
                    "workspace_item": item_payload,
                }
                _append_runtime_task_progress_event(
                    "agent.task.workspace_item.updated",
                    str(getattr(workspace_item, "title", "") or step_id),
                    payload,
                    timeline=timeline,
                    timeline_factory=self._timeline,
                    append_run_event=self._append_run_event,
                    run_id=run_id,
                )
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
                _append_runtime_task_progress_event(
                    "agent.task.todo.updated",
                    str(getattr(todo, "title", "") or step_id),
                    payload,
                    timeline=timeline,
                    timeline_factory=self._timeline,
                    append_run_event=self._append_run_event,
                    run_id=run_id,
                )
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
                _append_runtime_task_progress_event(
                    "agent.task.checkpoint.updated",
                    str(getattr(checkpoint, "title", "") or step_id),
                    payload,
                    timeline=timeline,
                    timeline_factory=self._timeline,
                    append_run_event=self._append_run_event,
                    run_id=run_id,
                )

    def _record_model_followup_pending_plan_progress_events(
        self,
        followup_context: Mapping[str, Any],
        planned_tool_requests: list[dict[str, Any]],
        *,
        timeline: list[dict[str, Any]],
        tool_timeline_start: int,
        run_id: str = "",
    ) -> None:
        task_core = (
            followup_context.get("task_core")
            if isinstance(followup_context.get("task_core"), Mapping)
            else {}
        )
        if not task_core:
            return
        workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
        workspace_items = (
            workspace.get("items")
            if isinstance(workspace.get("items"), list)
            else []
        )
        workspace_items_by_step: dict[str, list[Mapping[str, Any]]] = {}
        for item in workspace_items:
            if not isinstance(item, Mapping):
                continue
            step_id = str(item.get("source_step_id") or "").strip()
            if step_id:
                workspace_items_by_step.setdefault(step_id, []).append(item)
        todos_by_step = {
            str(todo.get("step_id") or "").strip(): todo
            for todo in task_core.get("todos", [])
            if isinstance(todo, Mapping) and str(todo.get("step_id") or "").strip()
        }
        checkpoints_by_step: dict[str, list[Mapping[str, Any]]] = {}
        for checkpoint in task_core.get("checkpoints", []):
            if not isinstance(checkpoint, Mapping):
                continue
            step_id = str(checkpoint.get("after_step_id") or "").strip()
            if step_id:
                checkpoints_by_step.setdefault(step_id, []).append(checkpoint)
        tool_events = [
            event
            for event in timeline[tool_timeline_start:]
            if isinstance(event, dict)
            and str(event.get("event") or "").strip()
            in {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
        ]
        if not tool_events:
            return
        core_id = str(task_core.get("core_id") or "").strip()
        workspace_id = str(workspace.get("workspace_id") or "").strip()
        decision_id = str(followup_context.get("decision_id") or "").strip()
        plan_id = str(followup_context.get("plan_id") or "").strip()
        event_index = 0
        for request in planned_tool_requests:
            if not isinstance(request, Mapping):
                continue
            step_id = str(request.get("step_id") or "").strip()
            tool_name = str(request.get("tool") or "").strip()
            if not step_id or not tool_name:
                continue
            tool_event: dict[str, Any] | None = None
            scan_index = event_index
            while scan_index < len(tool_events):
                candidate = tool_events[scan_index]
                candidate_step_id = str(
                    candidate.get("step_id") or candidate.get("planner_step_id") or ""
                ).strip()
                if (
                    candidate_step_id == step_id
                    or (
                        not candidate_step_id
                        and str(candidate.get("detail") or "").strip() == tool_name
                    )
                ):
                    tool_event = candidate
                    event_index = scan_index + 1
                    break
                scan_index += 1
            if tool_event is None:
                continue
            result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
            todo_status = _task_todo_status_for_tool_result(
                str(tool_event.get("event") or ""),
                result,
            )
            checkpoint_status = _task_checkpoint_status_for_todo_status(todo_status, result)
            skip_statuses = {todo_status}
            if todo_status != "completed":
                skip_statuses.add("completed")
            if _runtime_planner_step_has_status(
                timeline,
                decision_id=decision_id,
                step_id=step_id,
                statuses=skip_statuses,
            ):
                continue
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
            base_payload.update(
                _runtime_task_progress_scope_context(
                    timeline,
                    tool_event,
                    decision_id=decision_id,
                    plan_id=plan_id,
                )
            )
            for workspace_item in workspace_items_by_step.get(step_id, []):
                item_payload = dict(workspace_item)
                item_payload["status"] = todo_status
                payload = {
                    **base_payload,
                    "workspace_item_id": str(workspace_item.get("item_id") or "").strip(),
                    "status": todo_status,
                    "previous_status": str(workspace_item.get("status") or "planned"),
                    "workspace_item": item_payload,
                }
                if _runtime_task_update_exists(
                    timeline,
                    "agent.task.workspace_item.updated",
                    payload,
                ):
                    continue
                _append_runtime_task_progress_event(
                    "agent.task.workspace_item.updated",
                    str(workspace_item.get("title") or step_id),
                    payload,
                    timeline=timeline,
                    timeline_factory=self._timeline,
                    append_run_event=self._append_run_event,
                    run_id=run_id,
                )
            todo = todos_by_step.get(step_id)
            if todo is not None:
                todo_payload = dict(todo)
                todo_payload["status"] = todo_status
                payload = {
                    **base_payload,
                    "todo_id": str(todo.get("todo_id") or "").strip(),
                    "status": todo_status,
                    "previous_status": str(todo.get("status") or "pending"),
                    "todo": todo_payload,
                }
                if not _runtime_task_update_exists(
                    timeline,
                    "agent.task.todo.updated",
                    payload,
                ):
                    _append_runtime_task_progress_event(
                        "agent.task.todo.updated",
                        str(todo.get("title") or step_id),
                        payload,
                        timeline=timeline,
                        timeline_factory=self._timeline,
                        append_run_event=self._append_run_event,
                        run_id=run_id,
                    )
            for checkpoint in checkpoints_by_step.get(step_id, []):
                checkpoint_payload = dict(checkpoint)
                checkpoint_payload["status"] = checkpoint_status
                payload = {
                    **base_payload,
                    "checkpoint_id": str(checkpoint.get("checkpoint_id") or "").strip(),
                    "status": checkpoint_status,
                    "previous_status": str(checkpoint.get("status") or "planned"),
                    "checkpoint": checkpoint_payload,
                }
                if _runtime_task_update_exists(
                    timeline,
                    "agent.task.checkpoint.updated",
                    payload,
                ):
                    continue
                _append_runtime_task_progress_event(
                    "agent.task.checkpoint.updated",
                    str(checkpoint.get("title") or step_id),
                    payload,
                    timeline=timeline,
                    timeline_factory=self._timeline,
                    append_run_event=self._append_run_event,
                    run_id=run_id,
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
            payload.update(_request_observability_metadata(request))
            self._append_run_event(run_id, "agent.tool.policy_decision", payload)

    def _record_desktop_intent_approval_required(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        pending_approval: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str,
        planned_request: dict[str, Any] | None = None,
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
        event_payload.update(
            _approval_required_planner_trace_payload(
                pending_approval,
                planned_request or {},
            )
        )
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
        planned_tool_requests = _direct_sequence_requests_with_safe_deferred_continuations(
            planned_tool_requests
        )
        if any(
            bool(request.get("continue_to_model"))
            for request in planned_tool_requests
            if isinstance(request, dict)
        ):
            return ""
        event_index = 0
        completed_steps: list[dict[str, Any]] = []
        stopped_after_recovery = False
        for request_index, planned_tool_request in enumerate(planned_tool_requests):
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
                candidate_tool = str(candidate.get("detail") or "")
                if candidate_tool == planned_tool or _followup_plan_tools_match(
                    candidate_tool,
                    planned_tool,
                ):
                    candidate_result = (
                        candidate.get("result") if isinstance(candidate.get("result"), dict) else {}
                    )
                    if candidate_result.get("approval_required"):
                        continue
                    tool_event = candidate
                    break
            if tool_event is None:
                remaining_requests = planned_tool_requests[request_index:]
                if completed_steps and _all_noncritical_daily_desktop_observations(
                    remaining_requests
                ):
                    break
                return ""
            result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else {}
            if result.get("approval_required"):
                return ""
            if planned_tool_request.get("replan_request_id") and (
                result.get("ok") is False or result.get("verification_failed") is True
            ):
                return ""
            result = _with_retry_recovery_action(planned_tool, planned_input, result)
            tool_event["result"] = result
            executed_input = (
                tool_event.get("input_preview")
                if isinstance(tool_event.get("input_preview"), dict)
                else planned_input
            )
            if _daily_desktop_step_has_placeholder_app(
                planned_input,
                executed_input,
                result,
            ):
                return ""
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
            completed_step.update(_request_observability_metadata(planned_tool_request))
            if presentation:
                completed_step["presentation"] = presentation
            completed_steps.append(completed_step)
            if result.get("ok") is False and _has_permission_recovery_signal(result):
                stopped_after_recovery = True
                break
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
        last_step = summary_steps[-1] if summary_steps else visible_steps[-1]
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
            "tools": (
                [str(step.get("tool") or "") for step in completed_tools_steps]
                if stopped_after_recovery
                else _planned_daily_desktop_tools(planned_tool_requests)
                or [str(step.get("tool") or "") for step in completed_tools_steps]
            ),
            "input_preview": (
                last_step.get("input_preview") if isinstance(last_step.get("input_preview"), dict) else {}
            ),
            "result": last_step.get("result") if isinstance(last_step.get("result"), dict) else {},
            "source": clean_source,
            "steps": completed_steps,
            "summary": summary,
        }
        verification_evidence = _desktop_intent_verification_evidence(completed_steps)
        if verification_evidence:
            event_payload.update(verification_evidence)
            event_payload["verification_evidence"] = verification_evidence
        if len(planning_reasons) == 1:
            event_payload["planning_reason"] = next(iter(planning_reasons))
        event_payload.update(_step_observability_metadata(last_step))
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
        for step in summary_steps:
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
            if tool_name in {"desktop.windows", "desktop.list_windows"}:
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
            if tool_name in _OPEN_PATH_WITH_APP_TOOLS:
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
            if tool_name in {"desktop.hotkey", "desktop.shortcut"}:
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
        sequence = self._latest_uncompleted_daily_desktop_sequence(timeline)
        if sequence is not None and any(
            bool(request.get("continue_to_model"))
            for request in sequence.get("requests", [])
            if isinstance(request, dict)
        ):
            return ""
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
        requests = _drop_resolved_deferred_observation_requests(requests)
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
            if bool(event.get("continue_to_model")):
                request["continue_to_model"] = True
            for key in ("step_id", "capability_id", "replan_request_id", "replan_trigger"):
                value = str(event.get(key) or "").strip()
                if value:
                    request[key] = value
            request.update(_request_observability_metadata(event))
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
        task_workspace_guidance = _runtime_planner_task_workspace_guidance(decision)
        return (
            "Runtime planner guidance: "
            f"selected intent={decision.selected_intent.kind}; "
            f"expected outputs={outputs}; "
            f"planned tool path={' -> '.join(tool_path)}; "
            f"missing required capabilities={missing}; "
            f"artifact expected={artifacts}; "
            f"route to Studio={route_to_studio}. "
            f"Plan steps: {steps_text}. "
            f"{task_workspace_guidance}"
            f"{studio_handoff_guidance}"
            "Follow the planned tool path in order when the named tools are allowed; do not replace app-scoped "
            "app.*_and_* foreground tools with a looser app.open/app.focus plus desktop.* sequence unless the "
            "app-scoped tool is unavailable. "
            "Use available tools to execute the request when the plan names an allowed tool; do not provide "
            "only manual instructions unless required capabilities are missing, user constraints forbid tools, "
            "or policy blocks execution. If a required step is unavailable, explain the missing capability "
            "instead of fabricating execution. Existing tool policy and approval gates still apply. "
        )


def _runtime_planner_task_workspace_guidance(decision: Any) -> str:
    task_core = getattr(getattr(decision, "plan", None), "task_core", None)
    if task_core is None:
        return ""
    if not hasattr(task_core, "model_dump"):
        return ""
    try:
        task_core_payload = task_core.model_dump(mode="json")
    except Exception:
        return ""
    if not isinstance(task_core_payload, Mapping):
        return ""
    lines = _runtime_replan_task_core_message_lines(task_core_payload)
    if not lines:
        return ""
    return " ".join(lines[:4]) + " "


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


def _timeline_has_permission_recovery_signal(
    timeline: list[dict[str, Any]],
    start_index: int,
) -> bool:
    for event in timeline[start_index:]:
        if event.get("event") not in {"agent.tool.call", "agent.tool.skipped"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if result.get("blocked_by_app_resolution") or str(
            result.get("error") or ""
        ).strip() == "app_resolution_failed":
            continue
        if result and _has_permission_recovery_signal(result):
            return True
    return False


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


def _preserve_direct_daily_desktop_tool_requests(
    requests: list[dict[str, Any]],
) -> bool:
    if not requests:
        return False
    tools = {
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    if not tools or tools & _DAILY_DESKTOP_DISCOVERY_PREFIX_TOOLS:
        return False
    app_ui_approval_tools = {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    }
    app_shortcut_tools = {
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    }
    if tools & app_ui_approval_tools:
        return True
    return "desktop.submit_foreground" in tools and bool(tools & app_shortcut_tools)


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
            "planning_reason",
            "action_kind",
            "recovery_action_kind",
            "runtime_stage",
            "runtime_role",
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
            "action_target",
            "desktop_loop",
            "metadata",
            "observation_evidence",
            "observation_retry",
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
        for list_key in ("verification_targets",):
            value = raw_action.get(list_key)
            if isinstance(value, list):
                normalized_targets = [
                    dict(item) for item in value if isinstance(item, dict) and item
                ]
                if normalized_targets:
                    action[list_key] = normalized_targets
        if raw_action.get("desktop_permission_retry") is True:
            action["desktop_permission_retry"] = True
        if raw_action.get("approval_required") is True:
            action["approval_required"] = True
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
        content_requests = _model_followup_context_requests_from_selection_target(
            planned_tool_requests,
            selection_payload,
        )
    if not content_requests:
        return {}
    context_only_followup = any(
        bool(request.get("_context_only_followup"))
        for request in content_requests
        if isinstance(request, Mapping)
    )
    observation_content_requests = [
        request
        for request in content_requests
        if not _tool_request_requires_model_materialization(request)
    ]
    materialization_content_requests = [
        request
        for request in content_requests
        if _tool_request_requires_model_materialization(request)
    ]
    allowed = {
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    }
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
            for request in observation_content_requests
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
    pending_plan_steps = (
        []
        if context_only_followup
        else _model_followup_pending_plan_steps(
            selection_payload,
            observation_content_requests,
        )
    )
    if pending_plan_steps:
        payload["pending_plan_steps"] = pending_plan_steps
    pending_execution_requests = (
        []
        if context_only_followup
        else _model_followup_pending_execution_requests(
            selection_payload,
            observation_content_requests,
            allowed,
        )
    )
    materialization_execution_requests = (
        []
        if context_only_followup
        else _model_followup_materialization_execution_requests(
            selection_payload,
            materialization_content_requests,
            allowed,
        )
    )
    if materialization_execution_requests:
        pending_execution_requests = _merged_pending_execution_requests(
            pending_execution_requests,
            materialization_execution_requests,
        )
    deferred_execution_requests = (
        []
        if context_only_followup
        else _model_followup_deferred_execution_requests(
            content_requests,
            allowed,
        )
    )
    if deferred_execution_requests:
        pending_execution_requests = _merged_pending_execution_requests(
            pending_execution_requests,
            deferred_execution_requests,
        )
    if pending_execution_requests:
        payload["pending_execution_requests"] = pending_execution_requests
    task_core_payload = _model_followup_task_core_payload(selection_payload)
    if task_core_payload:
        payload["task_core"] = task_core_payload
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


def _model_followup_context_requests_from_selection_target(
    planned_tool_requests: list[dict[str, Any]],
    selection_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not _selection_payload_has_model_followup_target(selection_payload):
        return []
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    post_action_observation = (
        target.get("post_action_observation")
        if isinstance(target.get("post_action_observation"), Mapping)
        else {}
    )
    preferred_tools = _ordered_text_list(
        [
            str(post_action_observation.get("tool") or "").strip(),
            "desktop.ui_elements",
            "desktop.read_ui",
            "screen.capture",
        ]
    )
    for request in reversed(planned_tool_requests):
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or "").strip()
        if preferred_tools and tool_name not in preferred_tools:
            continue
        return [{**request, "continue_to_model": True, "_context_only_followup": True}]
    return []


def _model_followup_task_core_payload(selection_payload: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("task_core", "yachiyo_task_core"):
        value = selection_payload.get(key)
        if isinstance(value, Mapping) and value:
            return dict(value)
    runtime_plan = (
        selection_payload.get("runtime_plan")
        if isinstance(selection_payload.get("runtime_plan"), Mapping)
        else {}
    )
    value = runtime_plan.get("task_core") if isinstance(runtime_plan, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) and value else {}


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
    task_core = _model_followup_task_core_payload(selection_payload)
    for step in steps[start_index:]:
        step_payload = _model_followup_plan_step_payload(step)
        if not step_payload:
            continue
        step_payload.update(
            _model_followup_task_core_step_runtime_trace(
                task_core,
                str(step_payload.get("step_id") or ""),
            )
        )
        pending_steps.append(step_payload)
        if len(pending_steps) >= 5:
            break
    return pending_steps


def _model_followup_pending_execution_requests(
    selection_payload: Mapping[str, Any],
    content_requests: list[dict[str, Any]],
    allowed: set[str],
) -> list[dict[str, Any]]:
    requests = _selection_execution_envelope_requests(selection_payload)
    observation_tools = [
        str(request.get("tool") or "").strip()
        for request in content_requests
        if str(request.get("tool") or "").strip()
    ]
    if not requests or not observation_tools:
        return []

    start_index = _pending_execution_request_start_index(requests, observation_tools)
    if start_index <= 0:
        return []

    pending_requests: list[dict[str, Any]] = []
    for request in requests[start_index:]:
        request_payload = _model_followup_execution_request_payload(request, allowed)
        if not request_payload:
            continue
        pending_requests.append(request_payload)
        if len(pending_requests) >= 5:
            break
    return pending_requests


def _model_followup_materialization_execution_requests(
    selection_payload: Mapping[str, Any],
    content_requests: Iterable[Mapping[str, Any]],
    allowed: set[str],
) -> list[dict[str, Any]]:
    materialization_requests = [
        request
        for request in content_requests
        if isinstance(request, Mapping)
        and _tool_request_requires_model_materialization(request)
    ]
    if not materialization_requests:
        return []
    envelope_requests = _selection_execution_envelope_requests(selection_payload)
    start_indexes = [
        index
        for request in materialization_requests
        for index in [
            _matching_execution_envelope_request_index(envelope_requests, request)
        ]
        if index >= 0
    ]
    raw_pending_requests: Iterable[Mapping[str, Any]]
    if start_indexes:
        raw_pending_requests = envelope_requests[min(start_indexes) :]
    else:
        raw_pending_requests = materialization_requests

    pending: list[dict[str, Any]] = []
    for request in raw_pending_requests:
        if not isinstance(request, Mapping):
            continue
        request_payload = _model_followup_execution_request_payload(request, allowed)
        if request_payload:
            pending.append(request_payload)
    return pending


def _matching_execution_envelope_request_index(
    envelope_requests: list[Mapping[str, Any]],
    request: Mapping[str, Any],
) -> int:
    if not envelope_requests:
        return -1
    request_id = str(request.get("request_id") or "").strip()
    step_id = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
    for index, candidate in enumerate(envelope_requests):
        candidate_request_id = str(candidate.get("request_id") or "").strip()
        if request_id and candidate_request_id == request_id:
            return index
        candidate_step_id = str(candidate.get("step_id") or "").strip()
        if step_id and candidate_step_id == step_id:
            return index
    request_tool = str(request.get("tool") or request.get("tool_name") or "").strip()
    request_input = (
        request.get("input")
        if isinstance(request.get("input"), Mapping)
        else request.get("input_preview")
        if isinstance(request.get("input_preview"), Mapping)
        else {}
    )
    for index, candidate in enumerate(envelope_requests):
        candidate_tool = str(
            candidate.get("tool_name") or candidate.get("tool") or ""
        ).strip()
        if candidate_tool != request_tool:
            continue
        candidate_input = (
            candidate.get("input") if isinstance(candidate.get("input"), Mapping) else {}
        )
        if _model_materialization_inputs_match(candidate_input, request_input):
            return index
    return -1


def _model_materialization_inputs_match(
    candidate_input: Mapping[str, Any],
    request_input: Mapping[str, Any],
) -> bool:
    for key in (
        "app_name",
        "path",
        "target_path",
        "body_source",
        "selection_source",
        "app_selection_source",
        "action",
    ):
        request_value = request_input.get(key)
        if request_value in (None, "", [], {}):
            continue
        if candidate_input.get(key) != request_value:
            return False
    return True


def _model_followup_deferred_execution_requests(
    content_requests: list[dict[str, Any]],
    allowed: set[str],
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for index, request in enumerate(content_requests, start=1):
        if not isinstance(request, Mapping):
            continue
        tool_name = str(request.get("deferred_tool") or "").strip()
        if not tool_name or (allowed and tool_name not in allowed):
            continue
        raw_input = (
            dict(request.get("deferred_input"))
            if isinstance(request.get("deferred_input"), Mapping)
            else {}
        )
        if not raw_input:
            continue
        pending.append(
            {
                "request_id": _deferred_execution_request_id(
                    request,
                    tool_name=tool_name,
                    index=index,
                ),
                "tool_name": tool_name,
                "capability_id": "desktop.ui_operation",
                "input_preview": raw_input,
                "planning_reason": str(
                    request.get("planning_reason") or "planner_followup_deferred_ui_action"
                ).strip(),
                "status": "planned",
                "runtime_doctrine": str(
                    request.get("runtime_doctrine") or "discover_operate_verify"
                ).strip(),
                "runtime_stage": "operate",
                "runtime_role": _deferred_ui_runtime_role(tool_name),
                "approval_required": _deferred_ui_tool_requires_approval(tool_name),
                "requires_post_action_verification": True,
                "source": str(request.get("source") or "runtime_planner").strip(),
            }
        )
    return pending


def _auto_deferred_observed_ui_followup_requests(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    for index, request in enumerate(planned_tool_requests, start=1):
        if not isinstance(request, Mapping) or not bool(request.get("continue_to_model")):
            continue
        target = _deferred_observed_ui_target_from_request(request)
        if not target:
            continue
        target = _deferred_observed_ui_target_with_timeline_context(
            target,
            request,
            timeline,
        )
        tool_name = str(request.get("deferred_tool") or "").strip()
        scoped_allowed = _deferred_observed_ui_scoped_allowed_tools(
            tool_name,
            target,
            allowed,
        )
        if not scoped_allowed:
            continue
        target_label = str(target.get("target") or "").strip()
        role_filter = str(target.get("role_filter") or "").strip()
        if not _latest_desktop_observation_has_target_match(
            timeline,
            target_label,
            role_filter,
        ):
            retry_request = _deferred_observed_ui_observation_retry_request(
                request,
                target,
                allowed,
                timeline,
            )
            if retry_request:
                return [retry_request]
            continue
        observation_source = _latest_desktop_observation_tool(timeline)
        if observation_source:
            target["observation_source"] = observation_source
        requests = _auto_desktop_observed_action_followup_requests(
            {"followup_target": target},
            scoped_allowed,
            timeline,
            planning_reason=_deferred_observed_ui_planning_reason(request),
        )
        if requests:
            annotated = _annotate_deferred_observed_ui_followup_requests(
                requests,
                request,
                tool_name=tool_name,
                index=index,
            )
            continuation = _deferred_observed_ui_continuation_requests(request, allowed)
            if not continuation:
                continuation = _deferred_media_playback_continuation_requests(
                    request,
                    target,
                    allowed,
                    planning_reason=_deferred_observed_ui_planning_reason(request),
                )
            return [*annotated, *continuation]
    return []


def _auto_deferred_observed_ui_can_complete_without_model(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    requests = _auto_deferred_observed_ui_followup_requests(
        planned_tool_requests,
        allowed_tools,
        timeline,
    )
    requests = _drop_completed_auto_followup_prefix(
        requests,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )
    return bool(requests) and not _replan_recovery_requests_need_model_followup(requests)


def _deferred_observed_ui_planning_reason(request: Mapping[str, Any]) -> str:
    if _string_list(request.get("replan_triggers")) or _string_list(
        request.get("replan_signal_ids")
    ):
        return "planner_replan_app_search_observed_result"
    return str(
        request.get("planning_reason") or "planner_followup_deferred_ui_action"
    ).strip() or "planner_followup_deferred_ui_action"


def _deferred_observed_ui_scoped_allowed_tools(
    tool_name: str,
    target: Mapping[str, Any],
    allowed: set[str],
) -> list[str]:
    clean_tool = str(tool_name or "").strip()
    if not clean_tool:
        return []
    observation_tools = (
        "desktop.read_ui",
        "desktop.ui_elements",
        "desktop.active_window",
    )
    app_name = _observed_action_app_name(target)
    tools: list[str] = []
    if clean_tool in {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "desktop.click_ui_element",
        "desktop.safe_click",
        "desktop.click",
    }:
        if clean_tool in allowed:
            tools.append(clean_tool)
        if app_name:
            tools.extend(
                tool
                for tool in (
                    "app.focus_and_click_ui_element",
                    "app.open_and_click_ui_element",
                )
                if tool in allowed
            )
        tools.extend(
            tool
            for tool in (
                "desktop.click_ui_element",
                "desktop.safe_click",
                "desktop.click",
            )
            if tool in allowed
        )
    elif clean_tool in {
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.type_into_ui_element",
        "desktop.safe_type_text",
        "desktop.type_text",
        "desktop.type",
    }:
        if clean_tool in allowed:
            tools.append(clean_tool)
        if app_name:
            tools.extend(
                tool
                for tool in (
                    "app.focus_and_type_into_ui_element",
                    "app.open_and_type_into_ui_element",
                    "app.focus_and_click_ui_element",
                    "app.open_and_click_ui_element",
                )
                if tool in allowed
            )
        tools.extend(
            tool
            for tool in (
                "desktop.type_into_ui_element",
                "desktop.click_ui_element",
                "desktop.safe_click",
                "desktop.click",
                "desktop.safe_type_text",
                "desktop.type_text",
                "desktop.type",
            )
            if tool in allowed
        )
    else:
        return []
    tools.extend(tool for tool in observation_tools if tool in allowed)
    return _ordered_text_list(tools)


def _deferred_observed_ui_continuation_requests(
    request: Mapping[str, Any],
    allowed: set[str],
) -> list[dict[str, Any]]:
    raw_continuation = request.get("deferred_continuation")
    if not isinstance(raw_continuation, list):
        return []
    continuation: list[dict[str, Any]] = []
    for item in raw_continuation:
        if not isinstance(item, Mapping):
            continue
        next_request = dict(item)
        tool_name = str(next_request.get("tool") or "").strip()
        if not tool_name or (allowed and tool_name not in allowed):
            continue
        continuation.append(next_request)
    return continuation


def _deferred_media_playback_continuation_requests(
    request: Mapping[str, Any],
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    if str(request.get("intent_kind") or "").strip() != "media_playback":
        return []
    if str(target.get("target_action") or "").strip() != "type_text":
        return []
    app_name = _observed_action_app_name(target)
    if not app_name:
        return []
    source = str(request.get("source") or "runtime_planner").strip() or "runtime_planner"
    submit_request = _media_search_submit_request(
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if not submit_request:
        return []
    result_selection = {
        "target": "first result",
        "role_filter": "",
        "limit": 80,
        "click_count": 1,
    }
    result_observation = _discovered_media_result_observation_request(
        app_name,
        {"result_selection": result_selection},
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if not result_observation:
        return [submit_request]
    return [submit_request, result_observation]


def _deferred_observed_ui_observation_retry_request(
    request: Mapping[str, Any],
    target: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    if "desktop.read_ui" not in allowed:
        return {}
    if str(request.get("tool") or "").strip() == "desktop.read_ui":
        return {}
    latest_observation = _latest_desktop_observation_event(timeline)
    if str(latest_observation.get("tool") or "").strip() != "desktop.ui_elements":
        return {}
    payload = {
        key: value
        for key, value in {
            "app_name": target.get("app_name"),
            "role_filter": target.get("role_filter"),
            "limit": target.get("limit"),
        }.items()
        if value not in (None, "", [], {})
    }
    if "limit" not in payload:
        payload["limit"] = 80
    retry = _request_like(
        "desktop.read_ui",
        payload,
        source=str(request.get("source") or "runtime_planner").strip(),
        planning_reason=str(
            request.get("planning_reason") or "planner_retry_deferred_ui_observation"
        ).strip()
        or "planner_retry_deferred_ui_observation",
    )
    retry["continue_to_model"] = True
    retry["deferred_tool"] = str(request.get("deferred_tool") or "").strip()
    raw_input = request.get("deferred_input")
    if isinstance(raw_input, Mapping):
        retry["deferred_input"] = dict(raw_input)
    raw_context = request.get("deferred_context")
    if isinstance(raw_context, Mapping):
        retry["deferred_context"] = dict(raw_context)
    raw_continuation = request.get("deferred_continuation")
    if isinstance(raw_continuation, list):
        retry["deferred_continuation"] = [
            dict(item) for item in raw_continuation if isinstance(item, Mapping)
        ]
    for key, value in _request_observability_metadata(request).items():
        retry.setdefault(key, value)
    request_id = str(request.get("request_id") or "").strip()
    if request_id:
        retry["request_id"] = f"{request_id}:retry:desktop.read_ui"
    retry["observation_retry"] = {
        "from_tool": "desktop.ui_elements",
        "reason": "target_not_found",
        "target": str(target.get("target") or "").strip(),
    }
    return retry


def _deferred_observed_ui_target_from_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = str(request.get("deferred_tool") or "").strip()
    raw_input = (
        request.get("deferred_input")
        if isinstance(request.get("deferred_input"), Mapping)
        else {}
    )
    if not tool_name or not raw_input:
        return {}
    click_tools = {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "desktop.click_ui_element",
        "desktop.safe_click",
        "desktop.click",
    }
    type_tools = {
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.type_into_ui_element",
        "desktop.safe_type_text",
        "desktop.type_text",
        "desktop.type",
    }
    if tool_name in click_tools:
        target_action = "click"
    elif tool_name in type_tools:
        target_action = "type_text"
    else:
        return {}
    target_label = str(raw_input.get("target") or "").strip()
    if not target_label:
        return {}
    target: dict[str, Any] = {
        "kind": "desktop_observed_action",
        "target_action": target_action,
        "target": target_label,
        "role_filter": str(raw_input.get("role_filter") or "").strip(),
        "limit": _clean_model_followup_int(raw_input.get("limit"), default=80),
    }
    app_name = str(raw_input.get("app_name") or request.get("target_app_name") or "").strip()
    if app_name:
        target["app_name"] = app_name
    app_query = str(
        raw_input.get("app_query")
        or request.get("target_app_query")
        or request.get("app_query")
        or ""
    ).strip()
    if app_query:
        target["app_query"] = app_query
    if target_action == "click":
        target["click_count"] = _clean_model_followup_int(
            raw_input.get("click_count"),
            default=1,
        )
    else:
        text = str(raw_input.get("text") or "")
        if not text:
            return {}
        target["text"] = text
        submit_action = str(raw_input.get("submit_action") or "").strip()
        if submit_action:
            target["submit_action"] = submit_action
    return {key: value for key, value in target.items() if value not in ("", None, [], {})}


def _deferred_observed_ui_target_with_timeline_context(
    target: Mapping[str, Any],
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    resolved = dict(target)
    deferred_input = (
        request.get("deferred_input")
        if isinstance(request.get("deferred_input"), Mapping)
        else {}
    )
    app_query = str(
        resolved.get("app_query")
        or resolved.get("target_app_query")
        or deferred_input.get("query")
        or deferred_input.get("app_query")
        or request.get("target_app_query")
        or ""
    ).strip()
    if app_query:
        resolved["app_query"] = app_query
        resolved["target_app_query"] = app_query
    app_name = str(resolved.get("app_name") or resolved.get("target_app_name") or "").strip()
    if app_name and not _runtime_planner_placeholder_app_name(app_name):
        return resolved
    discovered = _discovered_app_name_for_query(timeline, app_query) if app_query else ""
    if not discovered:
        discovered = _latest_replan_context_app_name(timeline, request_id="")
    if discovered and not _runtime_planner_placeholder_app_name(discovered):
        resolved["app_name"] = discovered
        resolved["target_app_name"] = discovered
    return resolved


def _annotate_deferred_observed_ui_followup_requests(
    requests: list[dict[str, Any]],
    source_request: Mapping[str, Any],
    *,
    tool_name: str,
    index: int,
) -> list[dict[str, Any]]:
    request_id = _deferred_execution_request_id(
        source_request,
        tool_name=tool_name,
        index=index,
    )
    deferred_context = (
        source_request.get("deferred_context")
        if isinstance(source_request.get("deferred_context"), Mapping)
        else {}
    )
    annotated: list[dict[str, Any]] = []
    for request_index, request in enumerate(requests):
        item = dict(request)
        if request_id:
            item["request_id"] = (
                request_id if request_index == 0 else f"{request_id}:verify:{request_index}"
            )
        for key in (
            "decision_id",
            "plan_id",
            "tool_plan_id",
            "intent_kind",
            "core_id",
            "workspace_id",
            "task_id",
            "run_id",
            "runtime_doctrine",
            "requires_post_action_verification",
            "replan_signal_ids",
            "replan_triggers",
        ):
            value = source_request.get(key)
            if value in (None, "", [], {}) or key in item:
                continue
            item[key] = value
        for key in (
            "step_id",
            "planner_step_id",
            "capability_id",
            "task_todo",
            "task_checkpoints",
            "task_workspace_items",
        ):
            value = deferred_context.get(key)
            if value in (None, "", [], {}) or key in item:
                continue
            item[key] = value
        if item.get("step_id") and not item.get("planner_step_id"):
            item["planner_step_id"] = str(item.get("step_id") or "").strip()
        item.setdefault("runtime_stage", "operate" if request_index == 0 else "verify")
        item.setdefault("runtime_role", _deferred_ui_runtime_role(tool_name))
        annotated.append(item)
    return annotated


def _deferred_execution_request_id(
    request: Mapping[str, Any],
    *,
    tool_name: str,
    index: int,
) -> str:
    request_id = str(request.get("request_id") or "").strip()
    if request_id:
        return f"{request_id}:deferred:{tool_name}"
    plan_id = str(request.get("plan_id") or "").strip()
    if plan_id:
        return f"{plan_id}:deferred:{index}:{tool_name}"
    return f"deferred:{index}:{tool_name}"


def _deferred_ui_runtime_role(tool_name: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if clean_tool.endswith("_type_into_ui_element") or clean_tool in {
        "desktop.type_into_ui_element",
        "desktop.safe_type_text",
        "desktop.type_text",
        "desktop.type",
    }:
        return "type_ui"
    if clean_tool.endswith("_click_ui_element") or clean_tool in {
        "desktop.click_ui_element",
        "desktop.safe_click",
        "desktop.click",
    }:
        return "click_ui"
    return "operate_ui"


def _deferred_ui_tool_requires_approval(tool_name: str) -> bool:
    clean_tool = str(tool_name or "").strip()
    return clean_tool in {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.safe_click",
        "desktop.click",
        "desktop.safe_type_text",
        "desktop.type_text",
        "desktop.type",
    }


def _merged_pending_execution_requests(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for request in [*first, *second]:
        tool_name = str(request.get("tool_name") or request.get("tool") or "").strip()
        input_preview = (
            request.get("input_preview")
            if isinstance(request.get("input_preview"), Mapping)
            else request.get("input")
            if isinstance(request.get("input"), Mapping)
            else {}
        )
        key = (tool_name, repr(sorted(dict(input_preview).items())))
        if key in seen:
            continue
        seen.add(key)
        merged.append(request)
    return merged


def _selection_execution_envelope_requests(
    selection_payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    for key in (
        "yachiyo_execution_envelope",
        "execution_envelope",
        "runtime_execution_envelope",
    ):
        envelope = selection_payload.get(key)
        if not isinstance(envelope, Mapping):
            continue
        requests = envelope.get("requests")
        if not isinstance(requests, list):
            continue
        return [request for request in requests if isinstance(request, Mapping)]
    return []


def _pending_execution_request_start_index(
    requests: list[Mapping[str, Any]],
    observation_tools: list[str],
) -> int:
    cursor = 0
    last_match = -1
    for observed_tool in observation_tools:
        for index in range(cursor, len(requests)):
            tool_name = str(
                requests[index].get("tool_name")
                or requests[index].get("tool")
                or ""
            ).strip()
            if tool_name != observed_tool:
                continue
            last_match = index
            cursor = index + 1
            break
    return last_match + 1 if last_match >= 0 else 0


def _model_followup_execution_request_payload(
    request: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    status = str(request.get("status") or "planned").strip()
    if status not in {"", "planned"}:
        return {}
    tool_name = str(request.get("tool_name") or request.get("tool") or "").strip()
    if not tool_name or (allowed and tool_name not in allowed):
        return {}
    payload: dict[str, Any] = {
        "request_id": str(request.get("request_id") or "").strip(),
        "step_id": str(request.get("step_id") or "").strip(),
        "tool_name": tool_name,
        "capability_id": str(request.get("capability_id") or "").strip(),
        "input_preview": (
            dict(request.get("input"))
            if isinstance(request.get("input"), Mapping)
            else {}
        ),
        "planning_reason": str(request.get("planning_reason") or "").strip(),
        "status": status or "planned",
    }
    for key in (
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "source",
        *_RUNTIME_ORCHESTRATION_SCOPE_KEYS,
    ):
        value = str(request.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in (
        "approval_required",
        "continue_to_model",
        "requires_observation",
        "requires_post_action_verification",
    ):
        if bool(request.get(key)):
            payload[key] = True
    for key in (
        "depends_on",
        "fallback_tools",
        "replan_triggers",
        "replan_signal_ids",
    ):
        values = _string_list(request.get(key))
        if values:
            payload[key] = values
    task_todo = request.get("task_todo")
    if isinstance(task_todo, Mapping) and task_todo:
        payload["task_todo"] = dict(task_todo)
    for key in (
        "task_checkpoints",
        "task_workspace_items",
        "task_verification_targets",
    ):
        items = [
            dict(item)
            for item in request.get(key, [])
            if isinstance(item, Mapping)
        ]
        if items:
            payload[key] = items
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


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
    for key in (
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "requires_observation",
        "requires_post_action_verification",
    ):
        value = step.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    return {key: value for key, value in payload.items() if value not in ("", [], {})}


def _model_followup_task_core_step_runtime_trace(
    task_core: Mapping[str, Any],
    step_id: str,
) -> dict[str, Any]:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id or not isinstance(task_core, Mapping):
        return {}
    for todo in _mapping_list(task_core.get("todos")):
        if str(todo.get("step_id") or "").strip() != clean_step_id:
            continue
        metadata = todo.get("metadata") if isinstance(todo.get("metadata"), Mapping) else {}
        trace = _runtime_trace_metadata_from_mapping(metadata)
        if trace:
            return trace
    for checkpoint in _mapping_list(task_core.get("checkpoints")):
        if str(checkpoint.get("after_step_id") or "").strip() != clean_step_id:
            continue
        payload = checkpoint.get("payload") if isinstance(checkpoint.get("payload"), Mapping) else {}
        trace = _runtime_trace_metadata_from_mapping(payload)
        if trace:
            return trace
    return {}


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
    triggers: list[str] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        metadata = (
            dict(payload.get("metadata"))
            if isinstance(payload.get("metadata"), Mapping)
            else {}
        )
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
            "recovery_actions": _mapping_list(metadata.get("recovery_actions")),
            "recommended_tools": _string_list(metadata.get("recommended_tools")),
            "replan_prompt": str(payload.get("replan_prompt") or "").strip(),
            "metadata": metadata,
            **_replan_recovery_target(payload),
        }
        requests.append(request)
        failed_tools.append(request["source_tool_name"])
        fallback_candidates.extend(request["fallback_tools"])
        triggers.append(request["trigger"])
    if not requests:
        return {}
    fallback_candidates = _ordered_text_list(fallback_candidates)
    allowed_fallback_tools = [
        tool for tool in fallback_candidates if not allowed or tool in allowed
    ]
    triggers = _ordered_text_list(triggers)
    first = requests[0]
    payload = {
        "source": "runtime_planner",
        "status": "ready",
        "planning_reason": _runtime_replan_planning_reason(triggers),
        "replan_request_count": len(requests),
        "replan_requests": requests,
        "fallback_tools": allowed_fallback_tools,
        "fallback_tool_candidates": fallback_candidates,
        "failed_tools": _ordered_text_list(failed_tools),
        "triggers": triggers,
        "trigger": first.get("trigger", ""),
        "failure_detail": first.get("failure_detail", ""),
        "source_tool_name": first.get("source_tool_name", ""),
        "target_capability_id": first.get("target_capability_id", ""),
    }
    recovery_targets = _runtime_replan_recovery_targets(requests)
    if recovery_targets:
        payload["recovery_targets"] = recovery_targets
        for key in ("target_app_name", "target_app_query", "target_search_text"):
            value = str(recovery_targets[0].get(key) or "").strip()
            if value:
                payload[key] = value
    recovery_observations = _runtime_replan_recovery_observations(
        requests,
        timeline or [],
    )
    if recovery_observations:
        payload["recovery_observations"] = recovery_observations
        payload["content_snapshots"] = recovery_observations
        payload["content_snapshot"] = recovery_observations[-1]
        payload["recovery_observation_tools"] = _ordered_text_list(
            [
                str(observation.get("source_tool") or "").strip()
                for observation in recovery_observations
                if str(observation.get("source_tool") or "").strip()
            ]
        )
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
    task_core = _runtime_replan_task_core_payload(replan_payloads, timeline or [])
    if task_core:
        payload["task_core"] = task_core
        followup_target = _model_followup_target_from_task_core_context(payload)
        if followup_target:
            normalized_target = _model_followup_target_payload(
                {"followup_target": followup_target},
                allowed,
            )
            payload["followup_target"] = normalized_target or followup_target
    capability_recovery = _runtime_replan_capability_recovery(
        requests,
        allowed_tools=allowed_tools,
    )
    if capability_recovery:
        payload["capability_recovery"] = capability_recovery
    recovery_actions = _runtime_replan_recovery_actions(
        requests,
        allowed_tools=allowed_tools,
    )
    if recovery_actions:
        payload["recovery_actions"] = recovery_actions
    return payload


def _timeline_replan_request_payloads(
    timeline: list[dict[str, Any]],
    *,
    start: int = 0,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for event in list(timeline[max(0, int(start or 0)):]):
        if not isinstance(event, Mapping):
            continue
        if (
            _runtime_replan_event_type(
                str(event.get("event") or event.get("event_type") or "").strip()
            )
            != "agent.replan.requested"
        ):
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            if str(payload.get("source") or "").strip() != "runtime_tool_request_runner":
                continue
            payloads.append(dict(payload))
    return payloads


def _pending_runtime_replan_payloads(
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    handled = _handled_runtime_replan_request_identities(timeline)
    payloads: list[dict[str, Any]] = []
    for payload in _timeline_replan_request_payloads(timeline):
        identity = _runtime_replan_payload_identity(payload)
        if identity and identity in handled:
            continue
        payloads.append(payload)
    return payloads


def _handled_runtime_replan_request_identities(
    timeline: list[dict[str, Any]],
) -> set[str]:
    handled: set[str] = set()
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() != "agent.replan.recovery.updated":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        identity = str(
            event.get("request_id")
            or payload.get("request_id")
            or event.get("replan_request_id")
            or payload.get("replan_request_id")
            or ""
        ).strip()
        if identity:
            handled.add(identity)
    return handled


def _timeline_has_replan_followup_context(
    timeline: list[dict[str, Any]],
    replan_payloads: list[dict[str, Any]],
) -> bool:
    target = {
        identity
        for identity in (
            _runtime_replan_payload_identity(payload)
            for payload in replan_payloads
            if isinstance(payload, Mapping)
        )
        if identity
    }
    if not target:
        return False
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() != "agent.model.followup_context":
            continue
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        requests = event.get("replan_requests")
        if not isinstance(requests, list):
            requests = event_payload.get("replan_requests")
        if not isinstance(requests, list):
            continue
        existing = {
            identity
            for identity in (
                _runtime_replan_payload_identity(request)
                for request in requests
                if isinstance(request, Mapping)
            )
            if identity
        }
        if target.issubset(existing):
            return True
    return False


def _runtime_replan_payload_identity(payload: Mapping[str, Any]) -> str:
    request_id = str(payload.get("request_id") or "").strip()
    if request_id:
        return request_id
    dedupe_key = _replan_payload_dedupe_key(payload)
    if not dedupe_key:
        return ""
    return "|".join(dedupe_key)


def _replan_payload_dedupe_key(payload: Mapping[str, Any]) -> tuple[str, str, str] | None:
    step_id = str(
        payload.get("source_step_id") or payload.get("planner_step_id") or ""
    ).strip()
    tool_name = str(
        payload.get("source_tool_name") or payload.get("tool_name") or ""
    ).strip()
    trigger = str(payload.get("trigger") or payload.get("replan_trigger") or "").strip()
    if not step_id and not tool_name:
        return None
    return (step_id, tool_name, trigger)


def _runtime_replan_planning_reason(triggers: list[str]) -> str:
    clean = {str(trigger or "").strip() for trigger in triggers if str(trigger or "").strip()}
    if clean == {"verification_failed"}:
        return "planner_replan_after_verification_failed"
    if clean == {"tool_unavailable"}:
        return "planner_replan_after_tool_unavailable"
    if "verification_failed" in clean:
        return "planner_replan_after_mixed_runtime_failure"
    return "planner_replan_after_tool_failure"


def _runtime_replan_capability_recovery(
    requests: list[dict[str, Any]],
    *,
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    capability_ids = _ordered_text_list(
        [
            str(request.get("target_capability_id") or "").strip()
            for request in requests
            if str(request.get("trigger") or "").strip() == "tool_unavailable"
            and str(request.get("target_capability_id") or "").strip()
        ]
    )
    if not capability_ids:
        return []
    snapshots = {
        str(snapshot.capability_id or "").strip(): snapshot
        for snapshot in capability_snapshots(
            allowed_tools=allowed_tools,
            capability_ids=capability_ids,
        )
    }
    recoveries: dict[str, dict[str, Any]] = {}
    for request in requests:
        if str(request.get("trigger") or "").strip() != "tool_unavailable":
            continue
        capability_id = str(request.get("target_capability_id") or "").strip()
        if not capability_id:
            continue
        snapshot = snapshots.get(capability_id)
        recovery = recoveries.setdefault(
            capability_id,
            {
                "capability_id": capability_id,
                "title": str(getattr(snapshot, "title", "") or "").strip(),
                "category": str(getattr(snapshot, "category", "") or "").strip(),
                "description": str(getattr(snapshot, "description", "") or "").strip(),
                "risk_level": str(getattr(snapshot, "risk_level", "") or "").strip(),
                "approval_required": bool(getattr(snapshot, "approval_required", False)),
                "tools": list(getattr(snapshot, "tools", []) or []),
                "available_tools": list(getattr(snapshot, "available_tools", []) or []),
                "missing_tools": list(getattr(snapshot, "missing_tools", []) or []),
                "fallback_tools": [],
                "source_step_ids": [],
                "missing_permissions": [],
                "blocking_conditions": [],
            },
        )
        step_id = str(request.get("source_step_id") or "").strip()
        if step_id and step_id not in recovery["source_step_ids"]:
            recovery["source_step_ids"].append(step_id)
        for key in ("fallback_tools",):
            recovery[key] = _ordered_text_list(
                [*recovery.get(key, []), *_string_list(request.get(key))]
            )
        metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
        for key in ("missing_permissions", "blocking_conditions"):
            recovery[key] = _ordered_text_list(
                [*recovery.get(key, []), *_string_list(metadata.get(key))]
            )
    result: list[dict[str, Any]] = []
    for capability_id in capability_ids:
        recovery = recoveries.get(capability_id)
        if not recovery:
            continue
        missing_tools = _string_list(recovery.get("missing_tools"))
        missing_permissions = _string_list(recovery.get("missing_permissions"))
        blocking_conditions = _string_list(recovery.get("blocking_conditions"))
        if missing_permissions:
            suggested_action = "resolve_permissions"
        elif blocking_conditions:
            suggested_action = "clear_runtime_blockers"
        elif missing_tools:
            suggested_action = "enable_tools"
        else:
            suggested_action = "inspect_capability"
        recovery["suggested_action"] = suggested_action
        recovery["recommended_enable_tools"] = missing_tools[:6]
        result.append(
            {key: value for key, value in recovery.items() if value not in ("", [], {})}
        )
    return result


def _runtime_replan_recovery_actions(
    requests: Iterable[Mapping[str, Any]],
    *,
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        for action in _mapping_list(request.get("recovery_actions")):
            tool_name = str(action.get("tool") or "").strip()
            if allowed and tool_name not in allowed:
                continue
            action_input = (
                action.get("input")
                if isinstance(action.get("input"), Mapping)
                else {}
            )
            signature = (tool_name, repr(sorted(dict(action_input).items())))
            if not tool_name or signature in seen:
                continue
            seen.add(signature)
            actions.append(dict(action))
    return actions


def _runtime_replan_recovery_targets(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        target = {
            key: str(request.get(key) or "").strip()
            for key in ("target_app_name", "target_app_query", "target_search_text")
        }
        signature = (
            target["target_app_name"],
            target["target_app_query"],
            target["target_search_text"],
        )
        if not any(signature) or signature in seen:
            continue
        seen.add(signature)
        targets.append({key: value for key, value in target.items() if value})
    return targets


def _runtime_replan_recovery_observations(
    requests: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    request_ids = {
        str(request.get("request_id") or "").strip()
        for request in requests
        if isinstance(request, Mapping) and str(request.get("request_id") or "").strip()
    }
    if not request_ids or not timeline:
        return []
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in timeline:
        if not _runtime_replan_recovery_tool_event(event, request_ids):
            continue
        tool_name = str(event.get("detail") or event.get("tool") or "").strip()
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), dict)
            else {}
        )
        snapshot = followup_content_snapshot_for_tool_call(
            tool_name,
            result,
            input_preview,
        )
        if not snapshot:
            continue
        _attach_replan_observation_trace(snapshot, event)
        signature = (
            str(snapshot.get("source_tool") or "").strip(),
            str(snapshot.get("replan_request_id") or "").strip(),
            str(snapshot.get("text") or snapshot.get("summary") or snapshot.get("path") or "").strip(),
        )
        if signature in seen:
            continue
        seen.add(signature)
        observations.append(snapshot)
    return observations[-6:]


def _runtime_replan_recovery_tool_event(
    event: Mapping[str, Any],
    request_ids: set[str],
) -> bool:
    if not isinstance(event, Mapping):
        return False
    if str(event.get("event") or "").strip() != "agent.tool.call":
        return False
    replan_request_id = str(event.get("replan_request_id") or "").strip()
    if replan_request_id:
        return replan_request_id in request_ids
    return str(event.get("planning_reason") or "").strip() == (
        "planner_verification_recovery_observation"
    )


def _attach_replan_observation_trace(
    snapshot: dict[str, Any],
    event: Mapping[str, Any],
) -> None:
    for key in (
        "replan_request_id",
        "replan_trigger",
        "target_app_name",
        "target_app_query",
        "target_search_text",
        "runtime_stage",
        "runtime_role",
    ):
        value = str(event.get(key) or "").strip()
        if value:
            snapshot[key] = value
    for key in ("replan_triggers", "replan_signal_ids"):
        values = _string_list(event.get(key))
        if values:
            snapshot[key] = values


def _model_replan_followup_context_message(payload: dict[str, Any]) -> str:
    requests = [
        request
        for request in payload.get("replan_requests", [])
        if isinstance(request, dict)
    ]
    fallback_tools = _string_list(payload.get("fallback_tools"))
    failed_tools = _string_list(payload.get("failed_tools"))
    planning_reason = str(payload.get("planning_reason") or "").strip()
    lines = _runtime_replan_message_preamble(planning_reason)
    followup_target = (
        payload.get("followup_target")
        if isinstance(payload.get("followup_target"), Mapping)
        else {}
    )
    target_instruction = _model_followup_target_instruction(followup_target)
    if target_instruction:
        lines.append(target_instruction.strip())
    if failed_tools:
        lines.append(f"Failed tools: {', '.join(failed_tools)}.")
    if fallback_tools:
        lines.append(f"Preferred fallback tools: {', '.join(fallback_tools)}.")
    recovery_actions = [
        item
        for item in payload.get("recovery_actions", [])
        if isinstance(item, dict)
    ]
    if recovery_actions:
        lines.append("Runtime recovery actions:")
        for item in recovery_actions[:5]:
            tool_name = str(item.get("tool") or "").strip()
            label = str(item.get("label") or tool_name).strip()
            action_input = (
                item.get("input")
                if isinstance(item.get("input"), dict)
                else {}
            )
            parts = [part for part in (label, tool_name) if part]
            if action_input:
                parts.append(f"input={_model_followup_input_preview_text(action_input)}")
            if parts:
                lines.append(f"- {'; '.join(parts)}")
    recovery_targets = [
        item
        for item in payload.get("recovery_targets", [])
        if isinstance(item, dict)
    ]
    if recovery_targets:
        lines.append("Recovery targets:")
        for item in recovery_targets[:3]:
            parts = [
                part
                for part in (
                    _runtime_replan_target_part("app", item.get("target_app_name")),
                    _runtime_replan_target_part("query", item.get("target_app_query")),
                    _runtime_replan_target_part("text", item.get("target_search_text")),
                )
                if part
            ]
            if parts:
                lines.append(f"- {'; '.join(parts)}")
    snapshot_text = _followup_content_snapshots_message(payload)
    if snapshot_text:
        lines.append(snapshot_text.strip())
    capability_recovery = [
        item
        for item in payload.get("capability_recovery", [])
        if isinstance(item, dict)
    ]
    if capability_recovery:
        lines.append("Capability recovery:")
        for item in capability_recovery[:5]:
            capability_id = str(item.get("capability_id") or "").strip()
            missing_tools = _string_list(item.get("missing_tools"))
            available_tools = _string_list(item.get("available_tools"))
            missing_permissions = _string_list(item.get("missing_permissions"))
            blocking_conditions = _string_list(item.get("blocking_conditions"))
            parts = [capability_id] if capability_id else []
            if missing_tools:
                parts.append(f"enable_tools={', '.join(missing_tools[:6])}")
            if available_tools:
                parts.append(f"available_tools={', '.join(available_tools[:6])}")
            if missing_permissions:
                parts.append(f"permissions={', '.join(missing_permissions[:6])}")
            if blocking_conditions:
                parts.append(f"blockers={', '.join(blocking_conditions[:6])}")
            if parts:
                lines.append(f"- {'; '.join(parts)}")
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
    task_core = payload.get("task_core") if isinstance(payload.get("task_core"), dict) else {}
    if task_core:
        lines.extend(_runtime_replan_task_core_message_lines(task_core))
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


def _runtime_replan_target_part(label: str, value: Any) -> str:
    clean = str(value or "").strip()
    return f"{label}={clean}" if clean else ""


def _runtime_replan_task_core_message_lines(task_core: Mapping[str, Any]) -> list[str]:
    lines = ["Task workspace:"]
    workspace = (
        task_core.get("workspace")
        if isinstance(task_core.get("workspace"), Mapping)
        else {}
    )
    workspace_title = str(
        workspace.get("title") or workspace.get("workspace_id") or ""
    ).strip()
    if workspace_title:
        lines.append(f"- workspace: {workspace_title}")
    workspace_items = [
        item
        for item in workspace.get("items", [])
        if isinstance(item, Mapping)
    ]
    if workspace_items:
        rendered = []
        for item in workspace_items[:8]:
            kind = str(item.get("kind") or "").strip()
            status = str(item.get("status") or "planned").strip()
            path = str(item.get("path") or item.get("title") or "").strip()
            source_step_id = str(item.get("source_step_id") or "").strip()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            pattern = str(metadata.get("pattern") or "").strip()
            parts = [part for part in (kind, status, path, source_step_id, pattern) if part]
            if parts:
                rendered.append(" · ".join(parts))
        if rendered:
            lines.append(f"- workspace_items: {'; '.join(rendered)}")
    todos = [todo for todo in task_core.get("todos", []) if isinstance(todo, Mapping)]
    if todos:
        rendered = []
        for todo in todos[:8]:
            step_id = str(todo.get("step_id") or todo.get("todo_id") or "").strip()
            status = str(todo.get("status") or "planned").strip()
            tool = str(todo.get("tool_name") or "").strip()
            parts = [part for part in (step_id, status, tool) if part]
            if parts:
                rendered.append(" · ".join(parts))
        if rendered:
            lines.append(f"- todos: {'; '.join(rendered)}")
    checkpoints = [
        checkpoint
        for checkpoint in task_core.get("checkpoints", [])
        if isinstance(checkpoint, Mapping)
    ]
    if checkpoints:
        rendered = []
        for checkpoint in checkpoints[:5]:
            step_id = str(
                checkpoint.get("after_step_id") or checkpoint.get("step_id") or ""
            ).strip()
            status = str(checkpoint.get("status") or "planned").strip()
            title = str(checkpoint.get("title") or checkpoint.get("checkpoint_id") or "").strip()
            parts = [part for part in (step_id, status, title) if part]
            if parts:
                rendered.append(" · ".join(parts))
        if rendered:
            lines.append(f"- checkpoints: {'; '.join(rendered)}")
    return lines


def _runtime_replan_message_preamble(planning_reason: str) -> list[str]:
    if planning_reason == "planner_replan_after_verification_failed":
        return [
            (
                "Runtime replan context: post-action verification did not confirm "
                "the requested desktop state."
            ),
            (
                "Continue the existing task workspace. Do not ask the user to perform "
                "the desktop-capable action manually."
            ),
            (
                "Rediscover or inspect the visible app/window state, choose the next "
                "safe observable action, and keep all approval and policy gates."
            ),
        ]
    if planning_reason == "planner_replan_after_tool_unavailable":
        return [
            "Runtime replan context: a planned tool is unavailable.",
            (
                "Continue the existing task workspace. Select another available "
                "capability or ask only for the missing permission/tool."
            ),
            "Keep all approval and policy gates.",
        ]
    return [
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
    workspace_items_by_id: dict[str, dict[str, Any]] = {}
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        task_context = (
            metadata.get("task_core_context")
            if isinstance(metadata.get("task_core_context"), Mapping)
            else {}
        )
        if not task_context:
            continue
        workspace_items_by_id.update(
            {
                _runtime_workspace_item_key(item): item
                for item in _runtime_workspace_item_summaries(
                    task_context.get("workspace_items")
                )
                if _runtime_workspace_item_key(item)
            }
        )
        for todo in task_context.get("todos", []):
            if not isinstance(todo, Mapping):
                continue
            step_id = str(todo.get("step_id") or "").strip()
            if not step_id:
                continue
            todos_by_step[step_id] = {
                "step_id": step_id,
                "title": str(todo.get("title") or step_id).strip(),
                "status": str(todo.get("status") or "").strip(),
                "tool": str(todo.get("tool_name") or "").strip(),
                "approval_required": bool(todo.get("approval_required")),
            }
        for checkpoint in task_context.get("checkpoints", []):
            if not isinstance(checkpoint, Mapping):
                continue
            step_id = str(
                checkpoint.get("after_step_id") or checkpoint.get("step_id") or ""
            ).strip()
            if not step_id:
                continue
            checkpoints_by_step[step_id] = {
                "step_id": step_id,
                "title": str(checkpoint.get("title") or step_id).strip(),
                "status": str(checkpoint.get("status") or "").strip(),
                "checkpoint_id": str(checkpoint.get("checkpoint_id") or "").strip(),
            }
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        event_name = str(event.get("event") or "").strip()
        base_event_name = _runtime_progress_base_event_type(event_name)
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        core_id = str(event.get("core_id") or event_payload.get("core_id") or "").strip()
        plan_id = str(event.get("plan_id") or event_payload.get("plan_id") or "").strip()
        if core_ids and core_id and core_id not in core_ids:
            continue
        if plan_ids and plan_id and plan_id not in plan_ids:
            continue
        if _runtime_planner_base_event_type(event_name) == "agent.task_core.created":
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
            workspace_items_by_id = {
                _runtime_workspace_item_key(item): item
                for item in _runtime_workspace_item_summaries(workspace.get("items"))
                if _runtime_workspace_item_key(item)
            }
            continue
        if base_event_name == "agent.task.workspace_item.updated":
            item = (
                event.get("workspace_item")
                if isinstance(event.get("workspace_item"), Mapping)
                else {}
            )
            summaries = _runtime_workspace_item_summaries([item])
            if summaries:
                summary = {
                    **summaries[0],
                    "status": str(
                        event.get("status") or summaries[0].get("status") or ""
                    ).strip(),
                }
                key = _runtime_workspace_item_key(summary)
                if key:
                    workspace_items_by_id[key] = summary
            continue
        if base_event_name == "agent.task.todo.updated":
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
        if base_event_name == "agent.task.checkpoint.updated":
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
    workspace_items = list(workspace_items_by_id.values())
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


def _runtime_replan_task_core_payload(
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
    task_core_event = _runtime_replan_latest_task_core_event(
        timeline,
        core_ids=core_ids,
        plan_ids=plan_ids,
    )
    if not task_core_event:
        return {}
    event_payload = (
        task_core_event.get("payload")
        if isinstance(task_core_event.get("payload"), Mapping)
        else {}
    )
    task_core = (
        event_payload.get("task_core")
        if isinstance(event_payload.get("task_core"), Mapping)
        else {}
    )
    if not task_core:
        return {}
    replay_events = _runtime_replan_task_core_replay_events(
        timeline,
        core_ids=core_ids,
        plan_ids=plan_ids,
    )
    replayed = _runtime_replan_replayed_task_core_payload(
        task_core,
        replay_events,
    )
    if replayed:
        return replayed
    return dict(task_core)


def _runtime_replan_latest_task_core_event(
    timeline: list[dict[str, Any]],
    *,
    core_ids: set[str],
    plan_ids: set[str],
) -> Mapping[str, Any]:
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        event_name = str(event.get("event") or "").strip()
        if not event_name.endswith(".task_core.created"):
            continue
        if not _runtime_replan_event_matches_ids(event, core_ids, plan_ids):
            continue
        return event
    return {}


def _runtime_replan_task_core_replay_events(
    timeline: list[dict[str, Any]],
    *,
    core_ids: set[str],
    plan_ids: set[str],
) -> list[Mapping[str, Any]]:
    events: list[Mapping[str, Any]] = []
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        event_name = str(event.get("event") or "").strip()
        if not (
            event_name.endswith(".task_core.created")
            or event_name.endswith(".task.workspace_item.updated")
            or event_name.endswith(".task.todo.updated")
            or event_name.endswith(".task.checkpoint.updated")
        ):
            continue
        if not _runtime_replan_event_matches_ids(event, core_ids, plan_ids):
            continue
        events.append(event)
    return events


def _runtime_replan_event_matches_ids(
    event: Mapping[str, Any],
    core_ids: set[str],
    plan_ids: set[str],
) -> bool:
    event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    core_id = str(event.get("core_id") or event_payload.get("core_id") or "").strip()
    plan_id = str(event.get("plan_id") or event_payload.get("plan_id") or "").strip()
    if core_ids:
        return bool(core_id and core_id in core_ids)
    if plan_ids:
        return bool(plan_id and plan_id in plan_ids)
    return True


def _runtime_replan_replayed_task_core_payload(
    task_core: Mapping[str, Any],
    replay_events: list[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        from apps.shell.yachiyo_agent.events import (
            public_run_event_from_payload,
            run_event_parent_context,
        )
        from apps.shell.yachiyo_agent.task_core_snapshots import (
            task_core_snapshot_from_payload,
        )
    except Exception:
        return {}
    normalized_task_core = _runtime_replan_normalized_task_core_payload(task_core)
    context = run_event_parent_context({"task_core": normalized_task_core})
    public_events = [
        public_run_event_from_payload(event, sequence=index + 1, context=context)
        for index, event in enumerate(replay_events)
    ]
    snapshot = task_core_snapshot_from_payload(
        {"task_core": normalized_task_core},
        events=public_events,
    )
    if snapshot is None:
        return {}
    return snapshot.model_dump(mode="json")


def _runtime_replan_normalized_task_core_payload(
    task_core: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(task_core)
    workspace = (
        dict(normalized.get("workspace"))
        if isinstance(normalized.get("workspace"), Mapping)
        else {}
    )
    if workspace:
        workspace.setdefault(
            "title",
            str(workspace.get("workspace_id") or "Task Workspace").strip(),
        )
        workspace["items"] = [
            _runtime_replan_normalized_workspace_item(item)
            for item in workspace.get("items", [])
            if isinstance(item, Mapping)
        ]
        normalized["workspace"] = workspace
    normalized["todos"] = [
        _runtime_replan_normalized_todo_item(todo)
        for todo in normalized.get("todos", [])
        if isinstance(todo, Mapping)
    ]
    normalized["checkpoints"] = [
        _runtime_replan_normalized_checkpoint(checkpoint)
        for checkpoint in normalized.get("checkpoints", [])
        if isinstance(checkpoint, Mapping)
    ]
    return normalized


def _runtime_replan_normalized_workspace_item(item: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    title = str(
        normalized.get("title")
        or normalized.get("path")
        or normalized.get("item_id")
        or "workspace item"
    ).strip()
    normalized["title"] = title
    return normalized


def _runtime_replan_normalized_todo_item(todo: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(todo)
    title = str(
        normalized.get("title")
        or normalized.get("step_id")
        or normalized.get("tool_name")
        or normalized.get("todo_id")
        or "task todo"
    ).strip()
    normalized["title"] = title
    return normalized


def _runtime_replan_normalized_checkpoint(
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(checkpoint)
    title = str(
        normalized.get("title")
        or normalized.get("after_step_id")
        or normalized.get("checkpoint_id")
        or "task checkpoint"
    ).strip()
    normalized["title"] = title
    return normalized


def _runtime_workspace_item_summaries(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summary = {
            "item_id": str(item.get("item_id") or "").strip(),
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


def _runtime_workspace_item_key(item: Mapping[str, Any]) -> str:
    for key in ("item_id", "path", "title"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


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
        if (
            _runtime_planner_base_event_type(str(event.get("event") or "").strip())
            != "agent.plan.selection"
        ):
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
    if result.get("approval_required") or result.get("blocked_by_user_goal"):
        return False
    if result.get("verification_failed") is True:
        return True
    if result.get("ok") is True:
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


def _runtime_planner_completed_direct_requests_with_unavailable_replan(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    replan_payloads: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    if not _runtime_planner_replan_payloads_only_tool_unavailable(replan_payloads):
        return False
    requests = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    primary_requests: list[Mapping[str, Any]] = []
    last_primary_index = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name or tool_name not in _DIRECT_DAILY_DESKTOP_TOOLS:
            continue
        if tool_name in _DAILY_DESKTOP_DISCOVERY_TOOLS or tool_name in _DAILY_DESKTOP_VERIFY_TOOLS:
            continue
        primary_requests.append(request)
        last_primary_index = index
    if not primary_requests:
        return False
    if not all(
        _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for request in primary_requests
    ):
        return False
    trailing_observation_tools = {
        str(request.get("tool") or "").strip()
        for request in requests[last_primary_index + 1 :]
        if str(request.get("tool") or "").strip() in {
            *_DAILY_DESKTOP_DISCOVERY_TOOLS,
            *_DAILY_DESKTOP_VERIFY_TOOLS,
        }
    }
    payloads = [payload for payload in replan_payloads if isinstance(payload, Mapping)]
    if not trailing_observation_tools:
        return bool(payloads) and all(
            _runtime_replan_payload_is_missing_desktop_observation(payload)
            and not _runtime_replan_payload_requires_continuation(payload)
            for payload in payloads
        )
    if not payloads:
        return False
    return all(
        any(tool in trailing_observation_tools for tool in _runtime_replan_payload_tool_candidates(payload))
        for payload in payloads
    )


def _runtime_replan_payload_is_missing_desktop_observation(payload: Mapping[str, Any]) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    capability_id = str(
        payload.get("target_capability_id")
        or payload.get("capability_id")
        or metadata.get("target_capability_id")
        or metadata.get("capability_id")
        or ""
    ).strip()
    if capability_id == "desktop.app_discovery":
        return True
    return any(
        tool in _DAILY_DESKTOP_DISCOVERY_TOOLS or tool in _DAILY_DESKTOP_VERIFY_TOOLS
        for tool in _runtime_replan_payload_tool_candidates(payload)
    )


def _runtime_planner_completed_direct_requests_with_verification_replan(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    replan_payloads: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    payloads: list[Mapping[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        nested_requests = (
            payload.get("replan_requests")
            if isinstance(payload.get("replan_requests"), list)
            else []
        )
        payloads.extend(item for item in nested_requests if isinstance(item, Mapping))
        if _runtime_replan_payload_tool_candidates(payload):
            payloads.append(payload)
    if not payloads:
        return False
    requests = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if any(bool(request.get("continue_to_model")) for request in requests):
        return False
    primary_requests: list[Mapping[str, Any]] = []
    last_primary_index = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name or tool_name not in _DIRECT_DAILY_DESKTOP_TOOLS:
            continue
        if tool_name in _DAILY_DESKTOP_DISCOVERY_TOOLS or tool_name in _DAILY_DESKTOP_VERIFY_TOOLS:
            continue
        primary_requests.append(request)
        last_primary_index = index
    if last_primary_index < 0:
        return False
    if not any(
        _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for request in primary_requests
    ):
        return False

    trailing_verification_tools = {
        str(request.get("tool") or "").strip()
        for request in requests[last_primary_index + 1 :]
        if str(request.get("tool") or "").strip() in _DAILY_DESKTOP_VERIFY_TOOLS
    }
    if not trailing_verification_tools:
        return False
    if all(
        _runtime_replan_payload_is_trailing_verification_failure(
            payload,
            trailing_verification_tools,
        )
        for payload in payloads
    ):
        return True
    if any(_runtime_replan_payload_requires_continuation(payload) for payload in payloads):
        return False
    return False


def _runtime_planner_followup_requests_are_only_verification(
    planned_tool_requests: Iterable[Mapping[str, Any]],
) -> bool:
    followup_requests = [
        request
        for request in planned_tool_requests
        if isinstance(request, Mapping) and bool(request.get("continue_to_model"))
    ]
    if not followup_requests:
        return False
    for request in followup_requests:
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        if tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS:
            return False
        if str(request.get("deferred_tool") or "").strip():
            return False
        if isinstance(request.get("deferred_input"), Mapping) and request.get(
            "deferred_input"
        ):
            return False
        if _mapping_list(request.get("deferred_continuation")):
            return False
        if _tool_request_requires_model_materialization(request):
            return False
    return True


def _runtime_planner_completed_direct_requests_with_successful_verification(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    requests = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not requests:
        return False
    primary_indexes = [
        index
        for index, request in enumerate(requests)
        if (
            str(request.get("tool") or "").strip() in _DIRECT_DAILY_DESKTOP_TOOLS
            and str(request.get("tool") or "").strip() not in _DAILY_DESKTOP_DISCOVERY_TOOLS
            and str(request.get("tool") or "").strip() not in _DAILY_DESKTOP_VERIFY_TOOLS
        )
    ]
    if not primary_indexes:
        return False
    last_primary_index = primary_indexes[-1]
    if not all(
        _runtime_planner_tool_request_completed(
            requests[index],
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for index in primary_indexes
    ):
        return False
    verification_requests = [
        request
        for request in requests[last_primary_index + 1 :]
        if str(request.get("tool") or "").strip() in _DAILY_DESKTOP_VERIFY_TOOLS
    ]
    if not verification_requests:
        return False
    return all(
        _runtime_planner_direct_verification_request_succeeded(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for request in verification_requests
    )


def _runtime_planner_direct_verification_request_succeeded(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS:
        return False
    for event_index, event in enumerate(timeline[tool_timeline_start:]):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        event_tool = str(event.get("detail") or "").strip()
        if event_tool != tool_name and not _followup_plan_tools_match(event_tool, tool_name):
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True or result.get("approval_required"):
            return False
        if tool_name not in {"desktop.ui_elements", "desktop.read_ui"}:
            return True
        prior_tool_events = [
            item
            for item in timeline[tool_timeline_start : tool_timeline_start + event_index]
            if isinstance(item, dict)
            and str(item.get("event") or "").strip() == "agent.tool.call"
        ]
        context = _runtime_planner_verification_context(prior_tool_events, event)
        return not _tool_result_verification_weak(
            tool_name,
            result,
        ) and not _tool_result_verification_target_missing(
            tool_name,
            result,
            target_text=str(context.get("target_search_text") or ""),
            role_filter=str(context.get("ui_role_filter") or ""),
        )
    return False


def _runtime_replan_payload_requires_continuation(payload: Mapping[str, Any]) -> bool:
    if _replan_payload_is_focus_mismatch(payload):
        return True
    if _replan_ui_observed_action_target(payload):
        return True
    if isinstance(payload.get("followup_target"), Mapping):
        return True
    if isinstance(payload.get("action_target"), Mapping):
        return True
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    trigger = str(payload.get("trigger") or metadata.get("signal_trigger") or "").strip()
    if trigger == "verification_failed" and any(
        str(payload.get(key) or metadata.get(key) or "").strip()
        for key in (
            "target_app_name",
            "target_app_query",
            "target_search_text",
            "recovery_observation_goal",
        )
    ):
        return True
    return isinstance(metadata.get("followup_target"), Mapping) or isinstance(
        metadata.get("action_target"),
        Mapping,
    )


def _runtime_replan_payload_is_trailing_verification_failure(
    payload: Mapping[str, Any],
    trailing_verification_tools: set[str],
) -> bool:
    source_tool_candidates = _runtime_replan_payload_tool_candidates(payload)
    source_tool = next(
        (tool for tool in source_tool_candidates if tool in trailing_verification_tools),
        source_tool_candidates[0] if source_tool_candidates else "",
    )
    if source_tool not in trailing_verification_tools:
        return False
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    trigger = str(payload.get("trigger") or metadata.get("signal_trigger") or "").strip()
    if trigger and trigger not in {"tool_failure", "verification_failed"}:
        return False
    source_step = str(payload.get("source_step_id") or metadata.get("step_id") or "").strip()
    if source_step and "verify" not in source_step and trigger != "verification_failed":
        return False
    return True


def _runtime_replan_payload_tool_candidates(payload: Mapping[str, Any]) -> list[str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    action_target = (
        payload.get("action_target") if isinstance(payload.get("action_target"), Mapping) else {}
    )
    observation_retry = (
        payload.get("observation_retry")
        if isinstance(payload.get("observation_retry"), Mapping)
        else {}
    )
    return [
        str(value or "").strip()
        for value in (
            payload.get("source_tool_name"),
            payload.get("tool_name"),
            payload.get("tool"),
            metadata.get("source_tool_name"),
            metadata.get("tool_name"),
            metadata.get("tool"),
            action_target.get("verification_tool"),
            action_target.get("tool_name"),
            observation_retry.get("tool"),
        )
        if str(value or "").strip()
    ]


def _runtime_planner_completed_discovered_app_direct_action(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    selection_payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return False
    if str(target.get("target_action") or "").strip() not in {
        "open_app",
        "open",
        "focus_app",
        "focus",
        "open_path_with_app",
        "open_path_with_selected_app",
    }:
        return False
    if _discovered_app_target_requires_model_followup(target):
        return False

    requests = [
        request
        for request in planned_tool_requests
        if isinstance(request, Mapping)
    ]
    followup_requests = [
        request
        for request in requests
        if bool(request.get("continue_to_model"))
    ]
    if not followup_requests:
        return False
    if any(
        str(request.get("tool") or "").strip() not in _DISCOVERED_APP_SELECTION_SOURCES
        for request in followup_requests
    ):
        return False

    indexed_action_requests = [
        (index, request)
        for index, request in enumerate(requests)
        if str(request.get("tool") or "").strip() in _DISCOVERED_APP_DIRECT_COMPLETION_TOOLS
        and _request_uses_discovered_app_resolution(request)
    ]
    completed_action_indexes = [
        index
        for index, request in indexed_action_requests
        if _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
    ]
    if not completed_action_indexes:
        return False
    first_completed_action_index = min(completed_action_indexes)
    completed_action_request = next(
        request
        for index, request in indexed_action_requests
        if index == first_completed_action_index
    )
    expected_app_name = _expected_app_name_for_discovered_app_direct_action(
        completed_action_request,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )
    verification_requests = [
        request
        for index, request in enumerate(requests)
        if index > first_completed_action_index
        and str(request.get("tool") or "").strip()
        in _DISCOVERED_APP_DIRECT_VERIFICATION_TOOLS
    ]
    if not verification_requests:
        return True
    return all(
        _runtime_planner_verification_request_completed(
            request,
            expected_app_name,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for request in verification_requests
    )


def _discovered_app_target_requires_model_followup(target: Mapping[str, Any]) -> bool:
    if isinstance(target.get("post_action_observation"), Mapping):
        return True
    if isinstance(target.get("creative_canvas"), Mapping):
        return True
    if isinstance(target.get("communication_compose"), Mapping):
        return True
    if isinstance(target.get("app_search"), Mapping):
        return True
    if str(target.get("compose_text") or "").strip():
        return True
    if str(target.get("pending_user_action") or "").strip():
        return True
    return str(target.get("body_source") or "").strip() == "model_generated_content"


def _discovered_app_selection_source(value: Any) -> str:
    clean = str(value or "").strip()
    if clean in _DISCOVERED_APP_SELECTION_SOURCES:
        return clean
    return ""


def _discovered_app_placeholder_source(value: Any) -> str:
    clean = str(value or "").strip()
    for source, placeholder in _DISCOVERED_APP_PLACEHOLDERS.items():
        if clean == placeholder:
            return source
    return ""


def _request_uses_discovered_app_resolution(request: Mapping[str, Any]) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    resolution = (
        request.get("input_resolution")
        if isinstance(request.get("input_resolution"), Mapping)
        else {}
    )
    return (
        bool(_discovered_app_placeholder_source(payload.get("app_name")))
        or bool(_discovered_app_selection_source(payload.get("selection_source")))
        or bool(_discovered_app_selection_source(resolution.get("source_tool")))
    )


def _runtime_planner_tool_request_completed(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return False
    for event in timeline[tool_timeline_start:]:
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        event_tool = str(event.get("detail") or "").strip()
        if event_tool != tool_name and not _followup_plan_tools_match(
            event_tool,
            tool_name,
        ):
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is True and not result.get("approval_required"):
            return True
    return False


def _expected_app_name_for_discovered_app_direct_action(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> str:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    resolution = (
        request.get("input_resolution")
        if isinstance(request.get("input_resolution"), Mapping)
        else {}
    )
    resolved_app = str(resolution.get("resolved_app_name") or "").strip()
    if resolved_app:
        return resolved_app
    raw_app = str(payload.get("app_name") or "").strip()
    selection_source = (
        _discovered_app_selection_source(payload.get("selection_source"))
        or _discovered_app_placeholder_source(raw_app)
    )
    query = str(payload.get("query") or "").strip()
    if selection_source and query:
        discovered = _discovered_app_name_for_query(
            timeline[tool_timeline_start:],
            query,
            source_tool=selection_source,
        )
        if discovered:
            return discovered
    if raw_app and not _discovered_app_placeholder_source(raw_app):
        return raw_app
    tool_name = str(request.get("tool") or "").strip()
    for event in timeline[tool_timeline_start:]:
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        if str(event.get("detail") or "").strip() != tool_name:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        event_app = str(data.get("app_name") or "").strip()
        if event_app:
            return event_app
    return ""


def _runtime_planner_verification_request_completed(
    request: Mapping[str, Any],
    expected_app_name: str,
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name != "desktop.active_window" or not str(expected_app_name or "").strip():
        return _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
    expected_compact = compact_app_name_hint(expected_app_name)
    if not expected_compact:
        return _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
    for event in timeline[tool_timeline_start:]:
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        if str(event.get("detail") or "").strip() != tool_name:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True or result.get("approval_required"):
            continue
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        active_app = str(data.get("app_name") or "").strip()
        if active_app and compact_app_name_hint(active_app) == expected_compact:
            return True
    return False


def _runtime_planner_replan_payloads_only_tool_unavailable(
    replan_payloads: Iterable[Mapping[str, Any]],
) -> bool:
    payloads = [payload for payload in replan_payloads if isinstance(payload, Mapping)]
    if not payloads:
        return False
    return all(str(payload.get("trigger") or "").strip() == "tool_unavailable" for payload in payloads)


def _runtime_replan_failure_metadata(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    result_dict = dict(result)
    metadata: dict[str, Any] = {}
    recovery_actions = _recovery_actions(result_dict)
    if recovery_actions:
        metadata["recovery_actions"] = recovery_actions
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    for key in (
        "recommended_tools",
        "blocking_conditions",
        "permission_targets",
        "missing_permissions",
    ):
        values = _string_list(result.get(key)) or _string_list(data.get(key))
        if values:
            metadata[key] = values
    blocking_condition = str(
        result.get("blocking_condition") or data.get("blocking_condition") or ""
    ).strip()
    if blocking_condition:
        blocking_conditions = _string_list(metadata.get("blocking_conditions"))
        if blocking_condition not in blocking_conditions:
            blocking_conditions.append(blocking_condition)
        metadata["blocking_conditions"] = blocking_conditions
    expected_app_name = str(
        result.get("expected_app_name") or data.get("expected_app_name") or ""
    ).strip()
    if expected_app_name:
        metadata["expected_app_name"] = expected_app_name
        metadata.setdefault("target_app_name", expected_app_name)
    active_app_name = str(
        result.get("active_app_name") or data.get("active_app_name") or ""
    ).strip()
    if active_app_name:
        metadata["active_app_name"] = active_app_name
    return metadata


def _runtime_planner_tool_event_step_payloads(
    decision: Any,
    tool_events: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = list(getattr(tool_plan, "steps", []) or [])
    if not steps or not tool_events:
        return {}
    by_event_index: dict[int, dict[str, Any]] = {}
    step_cursor = 0
    for event_index, event in enumerate(tool_events):
        tool_name = str(event.get("detail") or "").strip()
        if not tool_name:
            continue
        explicit_step_id = str(event.get("step_id") or event.get("planner_step_id") or "").strip()
        match_index, step = _runtime_planner_matching_tool_event_step(
            steps,
            tool_name=tool_name,
            step_cursor=step_cursor,
            explicit_step_id=explicit_step_id,
        )
        if step is None:
            continue
        if match_index >= step_cursor:
            step_cursor = match_index + 1
        by_event_index[event_index] = _runtime_planner_step_failure_trace_payload(step)
    return by_event_index


def _runtime_planner_matching_tool_event_step(
    steps: list[Any],
    *,
    tool_name: str,
    step_cursor: int,
    explicit_step_id: str = "",
) -> tuple[int, Any | None]:
    if explicit_step_id:
        for index, step in enumerate(steps):
            if str(getattr(step, "step_id", "") or "").strip() == explicit_step_id:
                return index, step
    for index in range(max(0, step_cursor), len(steps)):
        step = steps[index]
        if str(getattr(step, "tool_name", "") or "").strip() == tool_name:
            return index, step
    for index, step in enumerate(steps):
        if index >= step_cursor:
            continue
        if str(getattr(step, "tool_name", "") or "").strip() == tool_name:
            return index, step
    return -1, None


def _runtime_planner_step_failure_trace_payload(step: Any) -> dict[str, Any]:
    step_id = str(getattr(step, "step_id", "") or "").strip()
    capability_id = str(getattr(step, "capability_id", "") or "").strip()
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    payload: dict[str, Any] = {}
    if step_id:
        payload["source_step_id"] = step_id
        payload["planner_step_id"] = step_id
    if tool_name:
        payload["planned_tool_name"] = tool_name
    if capability_id:
        payload["capability_id"] = capability_id
    metadata = {
        key: value
        for key, value in {
            "step_id": step_id,
            "capability_id": capability_id,
            "planned_tool_name": tool_name,
            "step_title": str(getattr(step, "title", "") or "").strip(),
            "step_action": str(getattr(step, "action", "") or "").strip(),
            "risk_level": str(getattr(step, "risk_level", "") or "").strip(),
            "approval_required": bool(getattr(step, "approval_required", False)),
        }.items()
        if value not in ("", None)
    }
    fallback_tools = [
        str(tool or "").strip()
        for tool in list(getattr(step, "fallback_tools", []) or [])
        if str(tool or "").strip()
    ]
    if fallback_tools:
        metadata["fallback_tools"] = fallback_tools
    if metadata:
        payload["metadata"] = metadata
    return payload


def _runtime_planner_verification_failure_payloads(
    decision: Any,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = list(getattr(tool_plan, "steps", []) or [])
    if not steps:
        return []
    tool_events = [
        event
        for event in events
        if isinstance(event, dict)
        and str(event.get("event") or "").strip() == "agent.tool.call"
    ]
    event_index = 0
    payloads: list[dict[str, Any]] = []
    for step in steps:
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        step_id = str(getattr(step, "step_id", "") or "").strip()
        if not tool_name or not step_id:
            continue
        tool_event: dict[str, Any] | None = None
        scan_index = event_index
        while scan_index < len(tool_events):
            candidate = tool_events[scan_index]
            if str(candidate.get("detail") or "").strip() == tool_name:
                tool_event = candidate
                event_index = scan_index + 1
                break
            scan_index += 1
        if tool_event is None:
            continue
        if not _runtime_planner_step_is_ui_verification(step_id, tool_name):
            continue
        result = (
            tool_event.get("result")
            if isinstance(tool_event.get("result"), Mapping)
            else {}
        )
        verification_context = _runtime_planner_verification_context(
            tool_events[: max(0, event_index - 1)],
            tool_event,
        )
        target_missing = _tool_result_verification_target_missing(
            tool_name,
            result,
            target_text=str(verification_context.get("target_search_text") or ""),
            role_filter=str(verification_context.get("ui_role_filter") or ""),
        )
        weak_observation = _tool_result_verification_weak(tool_name, result)
        if not weak_observation and not target_missing:
            continue
        metadata = {
            **_runtime_trace_metadata_from_mapping(tool_event),
            **verification_context,
            **_ui_verification_failure_metadata(
                tool_name,
                result,
                target_text=str(verification_context.get("target_search_text") or ""),
                role_filter=str(verification_context.get("ui_role_filter") or ""),
                target_missing=target_missing,
            ),
        }
        detail = "verification observation returned no UI elements or readable text"
        if target_missing:
            detail = (
                "verification observation did not include target UI element"
                f": {verification_context.get('target_search_text')}"
            )
        payloads.append(
            {
                "event_type": "agent.tool.call",
                "trigger": "verification_failed",
                "status": "verification_failed",
                "source_step_id": step_id,
                "planner_step_id": step_id,
                "tool_name": tool_name,
                "input_preview": (
                    tool_event.get("input_preview")
                    if isinstance(tool_event.get("input_preview"), Mapping)
                    else {}
                ),
                "detail": detail,
                "result": result,
                **verification_context,
                **({"metadata": metadata} if metadata else {}),
            }
        )
    return payloads


def _runtime_planner_verification_context(
    events: list[dict[str, Any]],
    current_event: Mapping[str, Any],
) -> dict[str, Any]:
    app_name = _runtime_planner_verification_app_name(events, current_event)
    app_query = _runtime_planner_verification_app_query(events)
    search_text = _runtime_planner_verification_target_text(events, current_event)
    role_filter = _runtime_planner_verification_role_filter(events, current_event)
    context = {
        "target_app_name": app_name,
        "target_app_query": app_query,
        "target_search_text": search_text,
        "ui_role_filter": role_filter,
        "recovery_observation_goal": "inspect_current_target_after_verification_gap",
    }
    return {key: value for key, value in context.items() if value not in ("", [], {})}


def _runtime_planner_verification_app_name(
    events: list[dict[str, Any]],
    current_event: Mapping[str, Any],
) -> str:
    candidates: list[str] = []
    for event in [current_event, *reversed(events)]:
        if not isinstance(event, Mapping):
            continue
        candidates.extend(_runtime_planner_event_app_name_candidates(event))
    for candidate in candidates:
        if candidate and not _runtime_planner_placeholder_app_name(candidate):
            return candidate
    return candidates[0] if candidates else ""


def _runtime_planner_event_app_name_candidates(event: Mapping[str, Any]) -> list[str]:
    result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    input_preview = (
        event.get("input_preview") if isinstance(event.get("input_preview"), Mapping) else {}
    )
    candidates = _runtime_planner_text_candidates(
        (
            "app_name",
            "resolved_app_name",
            "discovered_app_name",
            "requested_app_name",
            "active_app",
            "bundle_name",
        ),
        input_preview,
        data,
        result,
    )
    detail = str(event.get("detail") or "").strip()
    if detail in {"desktop.list_apps", "desktop.running_apps"}:
        candidates.extend(_runtime_planner_list_apps_result_candidates(result, data))
    return candidates


def _runtime_planner_list_apps_result_candidates(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
) -> list[str]:
    candidates: list[str] = []
    for source in (data, result):
        best_match = source.get("best_match")
        if isinstance(best_match, Mapping):
            candidates.extend(
                _runtime_planner_text_candidates(
                    ("name", "app_name", "resolved_app_name"),
                    best_match,
                )
            )
        apps = source.get("apps")
        if isinstance(apps, list):
            for item in apps[:3]:
                if isinstance(item, Mapping):
                    candidates.extend(
                        _runtime_planner_text_candidates(
                            ("name", "app_name", "display_name"),
                            item,
                        )
                    )
    return candidates


def _runtime_planner_verification_app_query(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if str(event.get("detail") or "").strip() != "desktop.list_apps":
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        query = str(input_preview.get("query") or "").strip()
        if query:
            return query
    return ""


def _runtime_planner_verification_search_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {
            "desktop.safe_type_text",
            "desktop.type",
            "desktop.type_into_ui_element",
            "app.open_and_safe_type_text",
            "app.focus_and_safe_type_text",
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
        }:
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        text = str(input_preview.get("text") or input_preview.get("value") or "").strip()
        if text:
            return text
    return ""


def _runtime_planner_verification_target_text(
    events: list[dict[str, Any]],
    current_event: Mapping[str, Any],
) -> str:
    current_input = (
        current_event.get("input_preview")
        if isinstance(current_event.get("input_preview"), Mapping)
        else {}
    )
    current_target = _first_runtime_planner_event_text(
        current_input,
        keys=("target_search_text", "target", "text", "value"),
    )
    if current_target:
        return current_target
    for event in reversed(events):
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        }:
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        if tool_name in {
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        }:
            target = _first_runtime_planner_event_text(
                input_preview,
                data,
                result,
                keys=("text", "value", "target_search_text", "matched_label", "target"),
            )
            if target:
                return target
            continue
    return _runtime_planner_verification_search_text(events)


def _runtime_planner_verification_role_filter(
    events: list[dict[str, Any]],
    current_event: Mapping[str, Any],
) -> str:
    current_input = (
        current_event.get("input_preview")
        if isinstance(current_event.get("input_preview"), Mapping)
        else {}
    )
    role_filter = _first_runtime_planner_event_text(
        current_input,
        keys=("role_filter", "role"),
    )
    if role_filter:
        return role_filter
    for event in reversed(events):
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {
            "app.open_and_click_ui_element",
            "app.focus_and_click_ui_element",
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
        }:
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        role_filter = _first_runtime_planner_event_text(
            input_preview,
            keys=("role_filter", "role"),
        )
        if role_filter:
            return role_filter
    return ""


def _first_runtime_planner_event_text(
    *sources: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _runtime_planner_text_candidates(
    keys: tuple[str, ...],
    *sources: Mapping[str, Any],
) -> list[str]:
    candidates: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                candidates.append(value)
    return candidates


def _runtime_planner_placeholder_app_name(value: str) -> bool:
    clean = str(value or "").strip().lower()
    return clean.startswith("<") and "selected app" in clean


def _runtime_planner_unavailable_failure_payloads(decision: Any) -> list[dict[str, Any]]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = list(getattr(tool_plan, "steps", []) or [])
    payloads: list[dict[str, Any]] = []
    for step in steps:
        status = str(getattr(step, "status", "") or "").strip()
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if status != "unavailable" and (tool_name or status not in {"", "planned"}):
            continue
        step_id = str(getattr(step, "step_id", "") or "").strip()
        capability_id = str(getattr(step, "capability_id", "") or "").strip()
        if not step_id and not capability_id:
            continue
        reason = str(getattr(step, "reason", "") or "").strip()
        title = str(getattr(step, "title", "") or "").strip()
        input_preview = (
            dict(getattr(step, "input_preview", {}) or {})
            if isinstance(getattr(step, "input_preview", {}), Mapping)
            else {}
        )
        metadata = {
            "capability_id": capability_id,
            "planned_tool_name": tool_name,
            "step_title": title,
            "step_status": status or "unavailable",
            "input_preview": input_preview,
        }
        missing_permissions = _string_list(input_preview.get("missing_permissions"))
        if missing_permissions:
            metadata["missing_permissions"] = missing_permissions
        blocking_conditions = _string_list(input_preview.get("blocking_conditions"))
        if blocking_conditions:
            metadata["blocking_conditions"] = blocking_conditions
        detail_parts = [
            "planned tool is missing or unavailable",
            f"step={step_id}" if step_id else "",
            f"capability={capability_id}" if capability_id else "",
            reason,
        ]
        payloads.append(
            {
                "event_type": "agent.plan.step",
                "trigger": "tool_unavailable",
                "status": "tool_unavailable",
                "source_step_id": step_id,
                "planner_step_id": step_id,
                "tool_name": tool_name,
                "capability_id": capability_id,
                "title": title,
                "input_preview": input_preview,
                "detail": "; ".join(part for part in detail_parts if part),
                "result": {
                    "ok": False,
                    "error": "planned tool is missing or unavailable",
                    "step_status": status or "unavailable",
                    "capability_id": capability_id,
                },
                "metadata": metadata,
            }
        )
    return payloads


def _runtime_planner_step_is_ui_verification(step_id: str, tool_name: str) -> bool:
    return (
        str(step_id or "").strip()
        in {"verify-desktop-result", "observe-selected-discovered-app"}
        and str(tool_name or "").strip() in {"desktop.ui_elements", "desktop.read_ui"}
    )


def _tool_result_verification_weak(tool_name: str, result: Mapping[str, Any]) -> bool:
    if str(tool_name or "").strip() not in {"desktop.ui_elements", "desktop.read_ui"}:
        return False
    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is not True:
        return False
    if result.get("approval_required") or result.get("blocked_by_user_goal"):
        return False
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    elements = _ui_elements_from_result(result, data)
    if _ui_element_count(result, data, elements) > 0:
        return False
    return not _ui_observation_has_readable_text(result, data, elements)


def _tool_result_verification_target_missing(
    tool_name: str,
    result: Mapping[str, Any],
    *,
    target_text: str,
    role_filter: str = "",
) -> bool:
    if str(tool_name or "").strip() not in {"desktop.ui_elements", "desktop.read_ui"}:
        return False
    if not str(target_text or "").strip():
        return False
    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is not True:
        return False
    if result.get("approval_required") or result.get("blocked_by_user_goal"):
        return False
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    elements = _ui_elements_from_result(result, data)
    if not elements and not _ui_observation_has_readable_text(result, data, elements):
        return False
    if _ui_observation_text_matches_target(result, data, target_text):
        return False
    return not _ui_observation_target_matches(elements, target_text, role_filter)


def _ui_verification_failure_metadata(
    tool_name: str,
    result: Mapping[str, Any],
    *,
    target_text: str,
    role_filter: str,
    target_missing: bool,
) -> dict[str, Any]:
    if str(tool_name or "").strip() not in {"desktop.ui_elements", "desktop.read_ui"}:
        return {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    elements = _ui_elements_from_result(result, data)
    metadata: dict[str, Any] = {
        "ui_element_count": _ui_element_count(result, data, elements),
    }
    if target_text:
        metadata["target_search_text"] = str(target_text).strip()
        metadata["ui_target"] = str(target_text).strip()
    if role_filter:
        metadata["ui_role_filter"] = str(role_filter).strip()
    if target_missing and target_text:
        metadata["ui_target_found"] = False
        metadata["ui_match_count"] = 0
        metadata["blocking_conditions"] = ["ui_target_not_found"]
    return {key: value for key, value in metadata.items() if value not in ("", [], {})}


def _ui_elements_from_result(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
) -> list[Any]:
    for source in (data, result):
        elements = source.get("elements")
        if isinstance(elements, list):
            return list(elements)
    return []


def _ui_element_count(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
    elements: list[Any],
) -> int:
    counts: list[int] = []
    for source in (data, result):
        for key in ("element_count", "text_item_count", "count"):
            count = _non_negative_int(source.get(key))
            if count is not None:
                counts.append(count)
    if elements:
        counts.append(len(elements))
    return max(counts) if counts else 0


def _ui_observation_has_readable_text(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
    elements: list[Any],
) -> bool:
    for source in (data, result):
        for key in (
            "text",
            "content",
            "ocr_text",
            "selected_text",
            "value",
            "title",
            "window_title",
            "active_app",
            "app_name",
        ):
            if str(source.get(key) or "").strip():
                return True
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        for key in ("name", "value", "title", "label", "description", "text"):
            if str(element.get(key) or "").strip():
                return True
    return False


def _ui_observation_target_matches(
    elements: list[Any],
    target_text: str,
    role_filter: str = "",
) -> list[dict[str, Any]]:
    normalized_target = _normalize_observed_desktop_text(target_text)
    if not normalized_target:
        return []
    ordinal = _observed_desktop_target_ordinal(target_text)
    if ordinal:
        return _ordinal_observed_desktop_elements(elements, ordinal, role_filter)
    normalized_filter = _normalize_observed_desktop_text(role_filter)
    matches: list[dict[str, Any]] = []
    for raw_element in elements:
        if not isinstance(raw_element, Mapping):
            continue
        element = dict(raw_element)
        if element.get("enabled") is False:
            continue
        searchable = _normalize_observed_desktop_text(
            " ".join(
                str(element.get(key) or "")
                for key in ("role", "subrole", "name", "description", "value", "label")
            )
        )
        if normalized_filter and not _observed_desktop_text_matches(
            searchable,
            normalized_filter,
        ):
            continue
        if _observed_desktop_element_match_score(
            element,
            normalized_target,
            role_filter,
        ) > 0:
            matches.append(element)
    return matches


def _ui_observation_text_matches_target(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
    target_text: str,
) -> bool:
    normalized_target = _normalize_observed_desktop_text(target_text)
    if not normalized_target:
        return False
    for source in (data, result):
        for key in (
            "text",
            "content",
            "ocr_text",
            "selected_text",
            "value",
            "title",
            "window_title",
        ):
            searchable = _normalize_observed_desktop_text(source.get(key))
            if searchable and _observed_desktop_text_matches(
                searchable,
                normalized_target,
            ):
                return True
    return False


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


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

    for item in list(getattr(workspace, "items", []) if workspace is not None else []):
        step_id = str(getattr(item, "source_step_id", "") or "").strip()
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        status = str(getattr(item, "status", "") or "planned").strip()
        item_payload = _snapshot_payload(item)
        item_payload["status"] = status
        payload = {
            "source": "runtime_planner",
            "core_id": core_id,
            "workspace_id": workspace_id,
            "decision_id": decision_id,
            "plan_id": plan_id,
            "step_id": step_id,
            "tool": tool_name,
            "workspace_item_id": str(getattr(item, "item_id", "") or "").strip(),
            "status": status,
            "previous_status": "",
            "source_event": source_event,
            "result_preview": {},
            "workspace_item": item_payload,
        }
        events.append(
            (
                "agent.task.workspace_item.updated",
                str(getattr(item, "title", "") or step_id or "workspace item"),
                payload,
            )
        )

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


def _append_runtime_task_progress_event(
    event_type: str,
    detail: str,
    payload: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if _runtime_task_update_exists(timeline, event_type, payload):
        return
    scoped_event_type = _runtime_progress_event_type(event_type, payload)
    event_payload = _runtime_progress_event_payload(payload, event_type, scoped_event_type)
    timeline.append(timeline_factory(scoped_event_type, detail, **event_payload))
    if run_id and append_run_event is not None:
        append_run_event(run_id, scoped_event_type, event_payload)


def _runtime_task_progress_scope_context(
    timeline: list[dict[str, Any]],
    tool_event: Mapping[str, Any],
    *,
    decision_id: str,
    plan_id: str,
) -> dict[str, str]:
    context = _runtime_task_progress_context_from_mapping(tool_event)
    if context:
        return context
    clean_decision_id = str(decision_id or "").strip()
    clean_plan_id = str(plan_id or "").strip()
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if event_type not in {
            "agent.task_core.created",
            "group.run.task_core.created",
            "workflow.task_core.created",
            "workflow.run.task_core.created",
        }:
            continue
        payload = _runtime_task_progress_event_payload(event)
        event_decision_id = str(payload.get("decision_id") or "").strip()
        event_plan_id = str(payload.get("plan_id") or "").strip()
        if clean_decision_id and event_decision_id and event_decision_id != clean_decision_id:
            continue
        if clean_plan_id and event_plan_id and event_plan_id != clean_plan_id:
            continue
        context = _runtime_task_progress_context_from_mapping(payload)
        if context:
            return context
    return {}


def _runtime_task_progress_context_from_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    payload = _runtime_task_progress_event_payload(value)
    context: dict[str, str] = {}
    for key in (
        "task_id",
        "run_group_id",
        "group_run_id",
        "group_id",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        clean_value = str(payload.get(key) or "").strip()
        if clean_value:
            context[key] = clean_value
    return context


def _runtime_task_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    identity_key = (
        "todo_id"
        if event_type == "agent.task.todo.updated"
        else "workspace_item_id"
        if event_type == "agent.task.workspace_item.updated"
        else "checkpoint_id"
        if event_type == "agent.task.checkpoint.updated"
        else ""
    )
    identity = str(payload.get(identity_key) or "").strip() if identity_key else ""
    status = str(payload.get("status") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    return any(
        isinstance(event, dict)
        and _runtime_progress_base_event_type(str(event.get("event") or "").strip())
        == event_type
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


def _runtime_planner_step_has_status(
    timeline: list[dict[str, Any]],
    *,
    decision_id: str,
    step_id: str,
    statuses: set[str],
) -> bool:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id:
        return False
    clean_decision_id = str(decision_id or "").strip()
    expected_statuses = {
        str(status or "").strip()
        for status in statuses
        if str(status or "").strip()
    }
    if not expected_statuses:
        return False
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        if (
            _runtime_progress_base_event_type(str(event.get("event") or "").strip())
            != "agent.task.todo.updated"
        ):
            continue
        if str(event.get("step_id") or "").strip() != clean_step_id:
            continue
        if clean_decision_id and str(event.get("decision_id") or "").strip() != clean_decision_id:
            continue
        if str(event.get("status") or "").strip() in expected_statuses:
            return True
    return False


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
        pending_suffix = f"{pending_plan_instruction} " if pending_plan_instruction else ""
        artifact_instruction = (
            f"{_model_followup_chained_artifact_instruction(followup_target)}"
            f"{target_instruction}"
            f"{pending_suffix}"
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
    execution_instruction = _model_followup_pending_execution_request_instruction(payload)
    if execution_instruction:
        return execution_instruction
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
    patch_instruction = ""
    if any(
        str(step.get("tool_name") or "").strip() == "workspace.write_patch"
        or (
            str(step.get("capability_id") or "").strip() == "file.workspace_write"
            and str(step.get("action") or "").strip() == "apply_patch"
        )
        for step in normalized_steps
    ):
        patch_instruction = (
            " For workspace.write_patch steps, generate a concrete single-file UTF-8 "
            "unified diff from the observed workspace and diagnostic results, then call "
            "workspace.write_patch with path and patch. The tool remains approval-gated; "
            "do not replace this pending patch step with a prose-only summary."
        )
    return (
        "Continue the pending Runtime Plan steps in order before giving a final answer: "
        + "; ".join(items)
        + ". If a pending terminal.execution step only has an abstract operation, synthesize a concrete, "
        "safe command from the observed files and request approval through the normal tool/policy gate. "
        "Do not skip directly to final prose while an available tool step is still pending."
        + patch_instruction
    )


def _model_followup_pending_execution_request_instruction(
    payload: Mapping[str, Any],
) -> str:
    requests = payload.get("pending_execution_requests")
    if not isinstance(requests, list):
        return ""
    normalized_requests = [
        request
        for request in requests
        if isinstance(request, Mapping)
        and (
            str(request.get("request_id") or "").strip()
            or str(request.get("step_id") or "").strip()
            or str(request.get("tool_name") or "").strip()
        )
    ]
    if not normalized_requests:
        return ""
    items = []
    for index, request in enumerate(normalized_requests, start=1):
        request_id = str(request.get("request_id") or "").strip() or f"request-{index}"
        tool_name = str(request.get("tool_name") or "").strip() or "available tool"
        step_id = str(request.get("step_id") or "").strip()
        stage = str(request.get("runtime_stage") or "").strip()
        role = str(request.get("runtime_role") or "").strip()
        approval = " approval required" if bool(request.get("approval_required")) else ""
        preview = (
            request.get("input_preview")
            if isinstance(request.get("input_preview"), Mapping)
            else {}
        )
        preview_text = _model_followup_input_preview_text(preview)
        detail = f"[{index}] {request_id} via {tool_name}"
        if step_id:
            detail = f"{detail} step={step_id!r}"
        if stage or role or approval:
            stage_text = stage or "planned"
            role_text = f" role={role}" if role else ""
            detail = f"{detail} ({stage_text}{role_text}{approval})"
        if preview_text:
            detail = f"{detail} input_preview={preview_text}"
        items.append(detail)
    patch_instruction = ""
    if any(
        str(request.get("tool_name") or "").strip() == "workspace.write_patch"
        or str(request.get("capability_id") or "").strip() == "file.workspace_write"
        for request in normalized_requests
    ):
        patch_instruction = (
            " For workspace.write_patch requests, generate a concrete single-file UTF-8 "
            "unified diff from the observed workspace and diagnostic results, then call "
            "workspace.write_patch with path and patch."
        )
    return (
        "Continue the pending Runtime execution requests in order before giving a final answer: "
        + "; ".join(items)
        + ". Respect approval_required through the normal tool/policy gate. If a pending "
        "terminal.run request only has an abstract operation, synthesize a concrete, safe command "
        "from the observed files and request approval through the normal gate. Do not skip directly "
        "to final prose while an available execution request is still pending."
        + patch_instruction
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
    if kind == "desktop_observed_action":
        return _model_followup_desktop_observed_action_target_payload(target, allowed)
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


def _model_followup_desktop_observed_action_target_payload(
    target: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    target_action = str(target.get("target_action") or "").strip()
    if target_action not in {"click", "type_text"}:
        return {}
    target_label = str(target.get("target") or "").strip()
    if not target_label:
        return {}
    recommended_tools = _model_followup_desktop_observed_action_tools(
        target_action,
        allowed,
        app_scoped=bool(_observed_action_app_name(target)),
    )
    verify_tools = [
        tool
        for tool in (
            "desktop.ui_elements",
            "desktop.read_ui",
            "desktop.active_window",
            "screen.capture",
        )
        if tool in allowed
    ]
    payload: dict[str, Any] = {
        "kind": "desktop_observed_action",
        "target_action": target_action,
        "target": target_label,
        "role_filter": str(target.get("role_filter") or "").strip(),
        "limit": _clean_model_followup_int(target.get("limit"), default=80),
        "action_allowed": bool(recommended_tools),
        "recommended_tools": recommended_tools,
        "verify_tools": verify_tools,
        "observation_source": str(
            target.get("observation_source") or "desktop.read_ui"
        ).strip(),
    }
    app_name = _observed_action_app_name(target)
    if app_name:
        payload["app_name"] = app_name
    app_query = _observed_action_app_query(target)
    if app_query:
        payload["app_query"] = app_query
    if target_action == "click":
        payload["click_count"] = _clean_model_followup_int(
            target.get("click_count"),
            default=1,
        )
    else:
        text = str(target.get("text") or "")
        if not text:
            return {}
        payload["text"] = text
        payload["body_source"] = str(target.get("body_source") or "explicit_user_text").strip()
    return payload


def _model_followup_desktop_observed_action_tools(
    target_action: str,
    allowed: set[str],
    *,
    app_scoped: bool = False,
) -> list[str]:
    app_candidates = (
        (
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
        )
        if target_action == "click"
        else (
            "app.focus_and_type_into_ui_element",
            "app.open_and_type_into_ui_element",
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
        )
    )
    candidates = (
        (
            "desktop.click_ui_element",
            "desktop.click",
        )
        if target_action == "click"
        else (
            "desktop.type_into_ui_element",
            "desktop.click_ui_element",
            "desktop.click",
            "desktop.type_text",
            "desktop.type",
        )
    )
    if app_scoped:
        candidates = (*app_candidates, *candidates)
    return [tool for tool in candidates if tool in allowed]


def _clean_model_followup_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
            "app.open_path_with_app",
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
    context_source = str(target.get("context_source") or "").strip()
    if context_source:
        payload["context_source"] = context_source
    source_action = str(target.get("source_action") or "").strip()
    if source_action:
        payload["source_action"] = source_action
    dynamic_context_transfer = (
        target.get("dynamic_context_transfer")
        if isinstance(target.get("dynamic_context_transfer"), Mapping)
        else {}
    )
    if dynamic_context_transfer:
        payload["dynamic_context_transfer"] = dict(dynamic_context_transfer)
    app_search = _discovered_app_search_payload(target)
    if app_search:
        payload["app_search"] = app_search
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
    post_action_observation = (
        target.get("post_action_observation")
        if isinstance(target.get("post_action_observation"), Mapping)
        else {}
    )
    if post_action_observation:
        payload["post_action_observation"] = dict(post_action_observation)
    pending_user_action = str(target.get("pending_user_action") or "").strip()
    if pending_user_action:
        payload["pending_user_action"] = pending_user_action
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
            "desktop.safe_click",
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
    payload = {
        "kind": "desktop_discovered_media_playback",
        "app_query": app_query,
        "app_name_source": str(target.get("app_name_source") or "desktop.list_apps").strip(),
        "target_action": str(target.get("target_action") or "safe_shortcut").strip(),
        "safe_shortcut_action": str(target.get("safe_shortcut_action") or "find").strip(),
        "media_playback_query": media_query,
        "recommended_tools": recommended_tools,
        "verify_tools": verify_tools,
    }
    app_name = str(target.get("app_name") or target.get("target_app_name") or "").strip()
    if app_name:
        payload["app_name"] = app_name
    return payload


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
    if kind == "desktop_observed_action":
        return bool(str(target.get("target") or "").strip())
    if kind == "desktop_discovered_app_action":
        return bool(str(target.get("app_query") or "").strip())
    if kind == "desktop_discovered_media_playback":
        return bool(str(target.get("app_query") or "").strip())
    return False


def _selection_payload_has_discovered_media_playback_target(
    selection_payload: Mapping[str, Any],
) -> bool:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    return str(target.get("kind") or "").strip() == "desktop_discovered_media_playback"


def _auto_discovered_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for factory in (
        _auto_desktop_observed_action_followup_requests,
        _auto_communication_message_followup_requests,
        _auto_discovered_app_search_observed_result_requests,
        _auto_discovered_app_observed_pending_action_requests,
        _auto_discovered_app_followup_requests,
        _auto_discovered_media_playback_followup_requests,
    ):
        requests = factory(selection_payload, allowed_tools, timeline)
        if requests:
            return requests
    return []


_CODE_CONTEXT_READ_EXTENSIONS = {
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".svelte",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}

_CODE_CONTEXT_CONFIG_FILES = {
    "package.json",
    "pyproject.toml",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
}

_CODE_CONTEXT_SKIP_PARTS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}


def _auto_code_context_read_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    max_files: int = 3,
) -> list[dict[str, Any]]:
    if str(selection_payload.get("intent_kind") or "").strip() != "code_task":
        return []
    allowed = {
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    }
    read_tool = _first_allowed_tool(
        ("workspace.read", "file.read", "fs.read_file"),
        allowed,
    )
    if not read_tool:
        return []
    already_read = _code_context_already_read_paths(timeline)
    selected_paths = _select_code_context_candidate_paths(
        timeline,
        already_read=already_read,
        max_files=max_files,
    )
    requests: list[dict[str, Any]] = []
    for index, path in enumerate(selected_paths, start=1):
        request = _request_like(
            read_tool,
            {"path": path},
            source="runtime_planner",
            planning_reason="planner_auto_code_context_read",
        )
        request["step_id"] = f"read-code-context-candidate-{index}"
        request["capability_id"] = "file.workspace_read"
        request["intent_kind"] = "code_task"
        request["runtime_doctrine"] = "discover_operate_verify"
        request["runtime_stage"] = "discover"
        request["runtime_role"] = "inspect_workspace"
        request["requires_observation"] = True
        request["requires_post_action_verification"] = False
        _attach_selection_trace_fields(request, selection_payload)
        requests.append(request)
    if requests:
        requests[-1]["continue_to_model"] = True
    return requests


def _attach_selection_trace_fields(
    request: dict[str, Any],
    selection_payload: Mapping[str, Any],
) -> None:
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "core_id",
        "workspace_id",
        "task_id",
    ):
        value = str(selection_payload.get(key) or "").strip()
        if value:
            request[key] = value


def _select_code_context_candidate_paths(
    timeline: list[dict[str, Any]],
    *,
    already_read: set[str],
    max_files: int,
) -> list[str]:
    candidates: dict[str, tuple[int, int]] = {}
    order = 0
    for event in timeline:
        if not _code_context_search_event(event):
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if result.get("ok") is not True:
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), dict)
            else {}
        )
        base_path = str(result.get("path") or input_preview.get("path") or "").strip()
        pattern = str(
            input_preview.get("pattern")
            or (result.get("filter") if isinstance(result.get("filter"), dict) else {}).get("pattern")
            or ""
        ).strip()
        entries = result.get("entries") if isinstance(result.get("entries"), list) else []
        for entry in entries:
            path = _code_context_entry_path(entry, base_path)
            if not path or path in already_read or not _code_context_readable_path(path):
                continue
            score = _code_context_candidate_score(path, pattern)
            if score <= 0:
                continue
            order += 1
            previous = candidates.get(path)
            value = (score, -order)
            if previous is None or value > previous:
                candidates[path] = value
    ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    clean_max = max(1, int(max_files or 3))
    return [path for path, _score in ranked[:clean_max]]


def _code_context_search_event(event: Mapping[str, Any]) -> bool:
    if event.get("event") != "agent.tool.call":
        return False
    tool_name = str(event.get("detail") or event.get("tool") or "").strip()
    if tool_name not in {"workspace.list", "file.search", "fs.find_files"}:
        return False
    planning_reason = str(event.get("planning_reason") or "").strip()
    if planning_reason:
        return planning_reason == "planner_prefetch_code_context"
    step_id = str(event.get("step_id") or "").strip()
    return step_id == "inspect-workspace" or step_id.startswith("inspect-code-area-")


def _code_context_already_read_paths(timeline: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for event in timeline:
        if event.get("event") != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or event.get("tool") or "").strip()
        if tool_name not in {"workspace.read", "file.read", "fs.read_file"}:
            continue
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), dict)
            else {}
        )
        path = str(input_preview.get("path") or "").strip()
        if path:
            paths.add(path)
    return paths


def _code_context_entry_path(entry: Any, base_path: str) -> str:
    if isinstance(entry, str):
        return _join_workspace_list_path(base_path, entry)
    if not isinstance(entry, Mapping):
        return ""
    entry_type = str(entry.get("type") or entry.get("kind") or "").strip()
    if entry_type and entry_type != "file":
        return ""
    path = str(entry.get("path") or "").strip()
    if path:
        return path.strip("/")
    name = str(entry.get("name") or "").strip()
    if not name:
        return ""
    return _join_workspace_list_path(base_path, name)


def _code_context_readable_path(path: str) -> bool:
    clean = str(path or "").strip().strip("/")
    if not clean:
        return False
    parts = {part for part in clean.split("/") if part}
    if parts & _CODE_CONTEXT_SKIP_PARTS:
        return False
    name = posixpath.basename(clean)
    if name in _CODE_CONTEXT_CONFIG_FILES:
        return True
    extension = _code_context_extension(name)
    return extension in _CODE_CONTEXT_READ_EXTENSIONS


def _code_context_candidate_score(path: str, pattern: str) -> int:
    clean = str(path or "").strip()
    name = posixpath.basename(clean).lower()
    extension = _code_context_extension(name)
    score = 0
    if name in _CODE_CONTEXT_CONFIG_FILES:
        score += 45
    if extension in {".ts", ".tsx", ".py", ".js", ".jsx"}:
        score += 70
    elif extension in _CODE_CONTEXT_READ_EXTENSIONS:
        score += 35
    lowered = clean.lower()
    if "/test" in lowered or "test_" in name or name.endswith((".test.ts", ".test.tsx")):
        score += 20
    for term in re.findall(r"[a-zA-Z0-9_]+", str(pattern or "").lower()):
        if len(term) >= 3 and term in lowered:
            score += 30
    return score


def _code_context_extension(name: str) -> str:
    lowered = str(name or "").lower()
    if lowered.endswith(".d.ts"):
        return ".ts"
    return posixpath.splitext(lowered)[1]


def _auto_communication_message_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_followup_communication_observed_compose",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "communication_message":
        return []
    if not _latest_desktop_observation_succeeded(timeline):
        return []
    app_name = str(target.get("app_name") or "").strip()
    recipient = str(target.get("recipient") or "").strip()
    body = str(target.get("body") or "").strip()
    if not app_name or not recipient or not body:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    channel = str(target.get("channel") or "").strip()
    recipient_target = {
        "kind": "desktop_observed_action",
        "target_action": "type_text",
        "target": _discovered_communication_recipient_target(channel),
        "text": recipient,
        "role_filter": "text",
        "limit": 80,
        "app_name": app_name,
        "submit_action": "confirm",
    }
    observation_source = _latest_desktop_observation_tool(timeline)
    if observation_source:
        recipient_target["observation_source"] = observation_source
    recipient_requests = _auto_desktop_observed_action_followup_requests(
        {"followup_target": recipient_target},
        allowed,
        timeline,
        planning_reason=planning_reason,
    )
    if not recipient_requests:
        return []
    body_observation = _communication_message_body_observation_request(
        app_name,
        body,
        target,
        allowed,
        source="runtime_planner",
        planning_reason=planning_reason,
    )
    if body_observation:
        recipient_requests.append(body_observation)
    return recipient_requests


def _communication_message_body_observation_request(
    app_name: str,
    body: str,
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    type_tool = _communication_observed_deferred_type_tool(allowed)
    observe_tool = _first_allowed_tool(
        ("desktop.ui_elements", "desktop.read_ui"),
        allowed,
    )
    if not type_tool or not observe_tool:
        return {}
    channel = str(target.get("channel") or "").strip()
    deferred_input = {
        "app_name": app_name,
        "target": _discovered_communication_body_target(channel),
        "text": body,
        "role_filter": "text",
        "limit": 80,
    }
    request = _request_like(
        observe_tool,
        {"app_name": app_name, "role_filter": "text", "limit": 80},
        source=source,
        planning_reason=planning_reason,
    )
    request["continue_to_model"] = True
    request["deferred_tool"] = type_tool
    request["deferred_input"] = deferred_input
    send_action = str(target.get("send_action") or "send").strip() or "send"
    if send_action == "send" and "desktop.submit_foreground" in allowed:
        send_request = _request_like(
            "desktop.submit_foreground",
            {"action": "send"},
            source=source,
            planning_reason=planning_reason,
        )
        send_request["approval_required"] = True
        send_request["risk_level"] = "high"
        request["deferred_continuation"] = [send_request]
    return request


def _communication_observed_deferred_type_tool(allowed: set[str]) -> str:
    return _first_allowed_tool(
        (
            "app.focus_and_type_into_ui_element",
            "app.open_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        ),
        allowed,
    ) or (
        "desktop.type_into_ui_element"
        if _first_allowed_tool(
            ("desktop.safe_type_text", "desktop.type_text", "desktop.type"),
            allowed,
        )
        and _first_allowed_tool(
            (
                "app.focus_and_click_ui_element",
                "app.open_and_click_ui_element",
                "desktop.click_ui_element",
                "desktop.safe_click",
                "desktop.click",
            ),
            allowed,
        )
        else ""
    )


def _auto_discovered_app_observed_pending_action_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_followup_discovered_app_observed_action",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    pending_action = str(target.get("pending_user_action") or "").strip()
    if not pending_action or not _latest_desktop_observation_succeeded(timeline):
        return []
    observed_target = _observed_action_target_from_discovered_pending_action(
        pending_action,
    )
    if not observed_target:
        return []
    _attach_discovered_app_context_to_observed_target(
        observed_target,
        target,
        timeline,
    )
    observation_source = _latest_desktop_observation_tool(timeline)
    if observation_source:
        observed_target["observation_source"] = observation_source
    target_label = str(observed_target.get("target") or "").strip()
    role_filter = str(observed_target.get("role_filter") or "").strip()
    if not _latest_desktop_observation_has_target_match(
        timeline,
        target_label,
        role_filter,
    ):
        retry_request = _discovered_app_observed_pending_observation_retry_request(
            target,
            observed_target,
            {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()},
            timeline,
            planning_reason=planning_reason,
        )
        if retry_request:
            return _annotate_auto_followup_requests_from_tool_plan(
                [retry_request],
                selection_payload,
            )
        return []
    requests = _auto_desktop_observed_action_followup_requests(
        {"followup_target": observed_target},
        allowed_tools,
        timeline,
        planning_reason=planning_reason,
    )
    return _annotate_auto_followup_requests_from_tool_plan(requests, selection_payload)


def _discovered_app_observed_pending_observation_retry_request(
    discovered_target: Mapping[str, Any],
    observed_target: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> dict[str, Any]:
    latest_tool = _latest_desktop_observation_tool(timeline)
    if latest_tool != "desktop.ui_elements" or "desktop.read_ui" not in allowed:
        return {}
    target_label = str(observed_target.get("target") or "").strip()
    if not target_label:
        return {}
    input_payload = {
        "role_filter": str(observed_target.get("role_filter") or "").strip(),
        "limit": _clean_model_followup_int(observed_target.get("limit"), default=80),
    }
    request = _request_like(
        "desktop.read_ui",
        input_payload,
        source="runtime_planner",
        planning_reason=planning_reason,
    )
    request["continue_to_model"] = True
    request["observation_retry"] = {
        "from_tool": latest_tool,
        "reason": "target_not_found",
        "target": target_label,
    }
    request["followup_target"] = _compact_observed_action_target(observed_target)
    app_name = _observed_action_app_name(observed_target)
    if app_name:
        request["target_app_name"] = app_name
    app_query = (
        _observed_action_app_query(observed_target)
        or str(discovered_target.get("app_query") or "").strip()
    )
    if app_query:
        request["target_app_query"] = app_query
    return request


def _observed_action_target_from_discovered_pending_action(
    pending_action: str,
) -> dict[str, Any]:
    type_target = type_into_ui_hint(pending_action)
    if isinstance(type_target, Mapping) and type_target:
        target_label = str(type_target.get("target") or "").strip()
        text = str(type_target.get("text") or "").strip()
        if target_label and text:
            return {
                "kind": "desktop_observed_action",
                "target_action": "type_text",
                "target": target_label,
                "text": text,
                "role_filter": str(type_target.get("role_filter") or "text").strip(),
                "limit": _clean_model_followup_int(type_target.get("limit"), default=80),
                "body_source": "explicit_user_text",
            }
    click_target = click_target_hint(pending_action)
    if isinstance(click_target, Mapping) and click_target:
        target_label = str(click_target.get("target") or "").strip()
        if target_label:
            return {
                "kind": "desktop_observed_action",
                "target_action": "click",
                "target": target_label,
                "role_filter": str(click_target.get("role_filter") or "").strip(),
                "click_count": _clean_model_followup_int(
                    click_target.get("click_count"),
                    default=1,
                ),
                "limit": _clean_model_followup_int(click_target.get("limit"), default=80),
            }
    return {}


def _auto_discovered_app_search_observed_result_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_followup_app_search_observed_result",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    if str(target.get("target_action") or "").strip() != "app_search":
        return []
    if not _latest_desktop_observation_succeeded(timeline):
        return []
    if not _latest_desktop_observation_follows_search_submission(timeline):
        return []
    app_search = _discovered_app_search_payload(target)
    result_selection = _discovered_app_search_result_selection(app_search)
    if str(result_selection.get("action") or "").strip() != "click":
        return []
    observed_target = _observed_action_target_from_app_search_result_selection(
        result_selection,
    )
    if not observed_target:
        return []
    _attach_discovered_app_context_to_observed_target(observed_target, target, timeline)
    latest_observation_tool = _latest_desktop_observation_tool(timeline)
    if latest_observation_tool == "desktop.inspect_app":
        observed_target["observation_source"] = latest_observation_tool
    requests = _auto_desktop_observed_action_followup_requests(
        {"followup_target": observed_target},
        allowed_tools,
        timeline,
        planning_reason=planning_reason,
    )
    return _annotate_auto_followup_requests_from_tool_plan(requests, selection_payload)


def _auto_replan_app_search_observed_result_requests(
    replan_payloads: Iterable[Mapping[str, Any]],
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    payloads = [
        dict(payload) for payload in replan_payloads if isinstance(payload, Mapping)
    ]
    requests = _auto_discovered_app_search_observed_result_requests(
        selection_payload,
        allowed_tools,
        timeline,
        planning_reason=planning_reason,
    )
    if requests:
        return _replan_recovery_requests_with_task_context(requests, payloads, timeline)
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return []
    if str(target.get("target_action") or "").strip() != "app_search":
        return []
    if not _replan_payloads_include_blocked_step(
        payloads,
        "select-app-search-result",
    ):
        return []
    if not _latest_desktop_observation_succeeded(timeline):
        return []
    if not _latest_desktop_observation_follows_search_submission(timeline):
        return []
    observed_target = {
        "kind": "desktop_observed_action",
        "target_action": "click",
        "target": "第一个结果",
        "role_filter": "",
        "click_count": 1,
        "limit": 80,
    }
    _attach_discovered_app_context_to_observed_target(
        observed_target,
        target,
        timeline,
        replan_payloads=payloads,
    )
    latest_observation_tool = _latest_desktop_observation_tool(timeline)
    if latest_observation_tool:
        observed_target["observation_source"] = latest_observation_tool
    requests = _auto_desktop_observed_action_followup_requests(
        {"followup_target": observed_target},
        allowed_tools,
        timeline,
        planning_reason=planning_reason,
    )
    requests = _annotate_auto_followup_requests_from_tool_plan(
        requests,
        selection_payload,
    )
    return _replan_recovery_requests_with_task_context(requests, payloads, timeline)


def _replan_payloads_include_blocked_step(
    replan_payloads: Iterable[Mapping[str, Any]],
    step_id: str,
) -> bool:
    expected_step = str(step_id or "").strip()
    if not expected_step:
        return False
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        task_context = (
            metadata.get("task_core_context")
            if isinstance(metadata.get("task_core_context"), Mapping)
            else {}
        )
        todos = task_context.get("todos") if isinstance(task_context.get("todos"), list) else []
        for todo in todos:
            if not isinstance(todo, Mapping):
                continue
            if str(todo.get("step_id") or "").strip() != expected_step:
                continue
            return str(todo.get("status") or "").strip() == "blocked"
    return False


def _observed_action_target_from_app_search_result_selection(
    result_selection: Mapping[str, Any],
) -> dict[str, Any]:
    raw_input = (
        result_selection.get("input")
        if isinstance(result_selection.get("input"), Mapping)
        else {}
    )
    target_label = str(
        raw_input.get("target")
        or result_selection.get("target")
        or "first result"
    ).strip()
    if not target_label:
        return {}
    role_filter = str(
        raw_input.get("role_filter")
        or result_selection.get("role_filter")
        or ""
    ).strip()
    return {
        "kind": "desktop_observed_action",
        "target_action": "click",
        "target": target_label,
        "role_filter": role_filter,
        "click_count": _clean_model_followup_int(
            raw_input.get("click_count", result_selection.get("click_count")),
            default=1,
        ),
        "limit": _clean_model_followup_int(
            raw_input.get("limit", result_selection.get("limit")),
            default=80,
        ),
        "observation_source": "desktop.read_ui",
    }


def _attach_discovered_app_context_to_observed_target(
    observed_target: dict[str, Any],
    source_target: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    replan_payloads: Iterable[Mapping[str, Any]] = (),
) -> None:
    app_name = _discovered_app_context_app_name(
        source_target,
        timeline,
        replan_payloads=replan_payloads,
    )
    if app_name:
        observed_target["app_name"] = app_name
    app_query = str(
        source_target.get("app_query") or source_target.get("target_app_query") or ""
    ).strip()
    if app_query:
        observed_target["app_query"] = app_query


def _discovered_app_context_app_name(
    target: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    replan_payloads: Iterable[Mapping[str, Any]] = (),
) -> str:
    for value in (
        target.get("app_name"),
        target.get("target_app_name"),
        target.get("resolved_app_name"),
        target.get("discovered_app_name"),
    ):
        app_name = str(value or "").strip()
        if app_name and not _runtime_planner_placeholder_app_name(app_name):
            return app_name
    app_query = str(target.get("app_query") or target.get("target_app_query") or "").strip()
    if app_query:
        discovered = _discovered_app_name_for_query(timeline, app_query)
        if discovered:
            return discovered
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        replan_target = _replan_recovery_target(payload)
        app_name = str(replan_target.get("target_app_name") or "").strip()
        if app_name and not _runtime_planner_placeholder_app_name(app_name):
            return app_name
        app_query = str(replan_target.get("target_app_query") or "").strip()
        if app_query:
            discovered = _discovered_app_name_for_query(timeline, app_query)
            if discovered:
                return discovered
    return ""


def _auto_desktop_observed_action_followup_requests(
    selection_payload: Mapping[str, Any],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str = "planner_followup_desktop_observed_action",
) -> list[dict[str, Any]]:
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_observed_action":
        return []
    if not _latest_desktop_observation_succeeded(timeline):
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    target_action = str(target.get("target_action") or "").strip()
    if target_action == "click":
        return _auto_desktop_observed_click_requests(
            target,
            allowed,
            timeline,
            planning_reason=planning_reason,
        )
    if target_action == "type_text":
        return _auto_desktop_observed_type_requests(
            target,
            allowed,
            timeline,
            planning_reason=planning_reason,
        )
    return []


def _auto_desktop_observed_click_requests(
    target: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    target_label = str(target.get("target") or "").strip()
    if not target_label:
        return []
    role_filter = str(target.get("role_filter") or "").strip()
    click_count = _clean_model_followup_int(target.get("click_count"), default=1)
    limit = _clean_model_followup_int(target.get("limit"), default=80)
    app_name = _observed_action_app_name(target)
    app_scoped_tool = (
        _first_allowed_tool(
            ("app.focus_and_click_ui_element", "app.open_and_click_ui_element"),
            allowed,
        )
        if app_name
        else ""
    )
    if app_scoped_tool:
        request = _with_observed_action_metadata(
            _with_observed_action_app_resolution(
                _request_like(
                    app_scoped_tool,
                    {
                        "app_name": app_name,
                        "target": target_label,
                        "role_filter": role_filter,
                        "click_count": click_count,
                        "limit": limit,
                    },
                    source="runtime_planner",
                    planning_reason=planning_reason,
                ),
                target,
                app_name,
            ),
            target,
            action="click",
            target_label=target_label,
            role_filter=role_filter,
            evidence={"strategy": "app_scoped_semantic_ui_tool"},
        )
        return _with_observed_action_verification(
            [request],
            target,
            allowed,
            target_label=target_label,
            role_filter=role_filter,
            planning_reason=planning_reason,
        )
    if "desktop.click_ui_element" in allowed:
        request = _with_observed_action_metadata(
            _request_like(
                "desktop.click_ui_element",
                {
                    "target": target_label,
                    "role_filter": role_filter,
                    "click_count": click_count,
                    "limit": limit,
                },
                source="runtime_planner",
                planning_reason=planning_reason,
            ),
            target,
            action="click",
            target_label=target_label,
            role_filter=role_filter,
            evidence={"strategy": "semantic_ui_tool"},
        )
        return _with_observed_action_verification(
            [request],
            target,
            allowed,
            target_label=target_label,
            role_filter=role_filter,
            planning_reason=planning_reason,
        )
    low_level_tool = _first_allowed_tool(("desktop.safe_click", "desktop.click"), allowed)
    if not low_level_tool:
        return []
    center = _latest_desktop_observation_match_center(
        timeline,
        target_label,
        role_filter,
    )
    if not center:
        return []
    request = _with_observed_action_metadata(
        _request_like(
            low_level_tool,
            _observed_click_input(low_level_tool, center, click_count),
            source="runtime_planner",
            planning_reason=planning_reason,
        ),
        target,
        action="click",
        target_label=target_label,
        role_filter=role_filter,
        evidence={"strategy": "observed_center", "center": center},
    )
    return _with_observed_action_verification(
        [request],
        target,
        allowed,
        target_label=target_label,
        role_filter=role_filter,
        planning_reason=planning_reason,
    )


def _with_observed_action_verification(
    requests: list[dict[str, Any]],
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    target_label: str,
    role_filter: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    verification = _observed_action_verification_request(
        target,
        allowed,
        target_label=target_label,
        role_filter=role_filter,
        planning_reason=planning_reason,
    )
    return [*requests, *([verification] if verification else [])]


def _observed_action_verification_request(
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    target_label: str,
    role_filter: str,
    planning_reason: str,
) -> dict[str, Any]:
    tool_name = _first_allowed_tool(
        ("desktop.read_ui", "desktop.ui_elements", "desktop.active_window"),
        allowed,
    )
    if not tool_name:
        return {}
    input_payload: dict[str, Any] = {}
    if tool_name in {"desktop.read_ui", "desktop.ui_elements"}:
        input_payload = {
            "role_filter": str(role_filter or "").strip(),
            "limit": _clean_model_followup_int(target.get("limit"), default=80),
        }
    return _with_observed_action_metadata(
        _request_like(
            tool_name,
            input_payload,
            source="runtime_planner",
            planning_reason=planning_reason,
        ),
        target,
        action="verify_after_action",
        target_label=target_label,
        role_filter=role_filter,
        evidence={"strategy": "post_action_observation"},
    )


def _auto_desktop_observed_type_requests(
    target: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    target_label = str(target.get("target") or "").strip()
    text = str(target.get("text") or "")
    if not target_label or not text:
        return []
    role_filter = str(target.get("role_filter") or "").strip()
    execution_target = _desktop_observed_action_execution_target(
        target_label,
        role_filter,
    )
    app_name = _observed_action_app_name(target)
    base_input = {
        "target": execution_target,
        "text": text,
        "role_filter": role_filter,
        "limit": _clean_model_followup_int(target.get("limit"), default=80),
    }
    app_scoped_type_tool = (
        _first_allowed_tool(
            ("app.focus_and_type_into_ui_element", "app.open_and_type_into_ui_element"),
            allowed,
        )
        if app_name
        else ""
    )
    if app_scoped_type_tool:
        request = _with_observed_action_metadata(
            _with_observed_action_app_resolution(
                _request_like(
                    app_scoped_type_tool,
                    {"app_name": app_name, **base_input},
                    source="runtime_planner",
                    planning_reason=planning_reason,
                ),
                target,
                app_name,
            ),
            target,
            action="type_text",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "app_scoped_semantic_ui_tool"},
        )
        return _with_observed_action_verification(
            [request],
            target,
            allowed,
            target_label=execution_target,
            role_filter=role_filter,
            planning_reason=planning_reason,
        )
    if "desktop.type_into_ui_element" in allowed:
        request = _with_observed_action_metadata(
            _request_like(
                "desktop.type_into_ui_element",
                base_input,
                source="runtime_planner",
                planning_reason=planning_reason,
            ),
            target,
            action="type_text",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "semantic_ui_tool"},
        )
        return _with_observed_action_verification(
            [request],
            target,
            allowed,
            target_label=execution_target,
            role_filter=role_filter,
            planning_reason=planning_reason,
        )
    type_tool = _first_allowed_tool(
        ("desktop.safe_type_text", "desktop.type_text", "desktop.type"),
        allowed,
    )
    if not type_tool:
        return []
    app_scoped_focus_tool = (
        _first_allowed_tool(
            ("app.focus_and_click_ui_element", "app.open_and_click_ui_element"),
            allowed,
        )
        if app_name
        else ""
    )
    if app_scoped_focus_tool:
        click_request = _with_observed_action_metadata(
            _with_observed_action_app_resolution(
                _request_like(
                    app_scoped_focus_tool,
                    {
                        "app_name": app_name,
                        "target": execution_target,
                        "role_filter": role_filter,
                        "click_count": 1,
                        "limit": _clean_model_followup_int(target.get("limit"), default=80),
                    },
                    source="runtime_planner",
                    planning_reason=planning_reason,
                ),
                target,
                app_name,
            ),
            target,
            action="focus_for_type",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "app_scoped_semantic_ui_tool"},
        )
    elif "desktop.click_ui_element" in allowed:
        click_request = _with_observed_action_metadata(
            _request_like(
                "desktop.click_ui_element",
                {
                    "target": execution_target,
                    "role_filter": role_filter,
                    "click_count": 1,
                    "limit": _clean_model_followup_int(target.get("limit"), default=80),
                },
                source="runtime_planner",
                planning_reason=planning_reason,
            ),
            target,
            action="focus_for_type",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "semantic_ui_tool"},
        )
    else:
        low_level_tool = _first_allowed_tool(("desktop.safe_click", "desktop.click"), allowed)
        if not low_level_tool:
            return []
        center = _latest_desktop_observation_match_center(
            timeline,
            execution_target,
            role_filter,
        )
        if not center:
            return []
        click_request = _with_observed_action_metadata(
            _request_like(
                low_level_tool,
                _observed_click_input(low_level_tool, center, 1),
                source="runtime_planner",
                planning_reason=planning_reason,
            ),
            target,
            action="focus_for_type",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "observed_center", "center": center},
        )
    requests = [
        click_request,
        _with_observed_action_metadata(
            _request_like(
                type_tool,
                {"text": text},
                source="runtime_planner",
                planning_reason=planning_reason,
            ),
            target,
            action="type_text",
            target_label=execution_target,
            role_filter=role_filter,
            evidence={"strategy": "focused_after_observed_target"},
        ),
    ]
    submit_request = _observed_type_submit_request(
        target,
        allowed,
        target_label=execution_target,
        role_filter=role_filter,
        planning_reason=planning_reason,
    )
    if submit_request:
        requests.append(submit_request)
    return _with_observed_action_verification(
        requests,
        target,
        allowed,
        target_label=execution_target,
        role_filter=role_filter,
        planning_reason=planning_reason,
    )


def _observed_type_submit_request(
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    target_label: str,
    role_filter: str,
    planning_reason: str,
) -> dict[str, Any]:
    submit_action = str(target.get("submit_action") or "").strip()
    if not submit_action:
        return {}
    submit_tool = _first_allowed_tool(("desktop.submit_foreground",), allowed)
    if not submit_tool:
        return {}
    request = _request_like(
        submit_tool,
        {"action": submit_action},
        source="runtime_planner",
        planning_reason=planning_reason,
    )
    if (
        _observed_submit_action_risk_level(
            submit_action,
            target,
            planning_reason=planning_reason,
        )
        == "high"
    ):
        request["approval_required"] = True
        request["risk_level"] = "high"
    return _with_observed_action_metadata(
        request,
        target,
        action="submit_after_type",
        target_label=target_label,
        role_filter=role_filter,
        evidence={"strategy": "focused_after_observed_target"},
    )


def _observed_submit_action_risk_level(
    action: str,
    target: Mapping[str, Any] | None = None,
    *,
    planning_reason: str = "",
) -> str:
    normalized = str(action or "").strip().lower().replace("-", "_")
    target_kind = str((target or {}).get("kind") or "").strip()
    if normalized == "confirm" and (
        target_kind == "communication_message"
        or str(planning_reason or "").strip()
        == "planner_followup_communication_observed_compose"
    ):
        return "low"
    if normalized in {"search", "select", "choose", "continue"}:
        return "low"
    return "high"


def _observed_click_input(
    tool_name: str,
    center: Mapping[str, Any],
    click_count: int,
) -> dict[str, Any]:
    payload = {"x": center["x"], "y": center["y"]}
    if str(tool_name or "").strip() == "desktop.click":
        payload["click_count"] = click_count
    return payload


def _observed_action_app_name(target: Mapping[str, Any]) -> str:
    return str(target.get("app_name") or target.get("target_app_name") or "").strip()


def _observed_action_app_query(target: Mapping[str, Any]) -> str:
    return str(target.get("app_query") or target.get("target_app_query") or "").strip()


def _with_observed_action_app_resolution(
    request: dict[str, Any],
    target: Mapping[str, Any],
    app_name: str,
) -> dict[str, Any]:
    app_query = _observed_action_app_query(target)
    if not app_query or not app_name:
        return request
    return _with_discovered_app_resolution(request, app_query, app_name)


def _latest_desktop_observation_succeeded(timeline: list[dict[str, Any]]) -> bool:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {"desktop.read_ui", "desktop.ui_elements", "desktop.inspect_app"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        return result.get("ok") is True
    return False


def _latest_desktop_observation_tool(timeline: list[dict[str, Any]]) -> str:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {"desktop.read_ui", "desktop.ui_elements", "desktop.inspect_app"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True:
            return tool_name
        if _desktop_observation_result_elements(tool_name, result):
            return tool_name
    return ""


def _latest_desktop_observation_event(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name in {"desktop.read_ui", "desktop.ui_elements", "desktop.inspect_app"}:
            return {**dict(event), "tool": tool_name}
    return {}


def _latest_desktop_observation_follows_search_submission(
    timeline: list[dict[str, Any]],
) -> bool:
    latest_observation_index = -1
    for index in range(len(timeline) - 1, -1, -1):
        event = timeline[index]
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {"desktop.read_ui", "desktop.ui_elements", "desktop.inspect_app"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is True:
            latest_observation_index = index
        break
    if latest_observation_index <= 0:
        return False
    for event in reversed(timeline[:latest_observation_index]):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name in {"desktop.search_submit", "desktop.submit_foreground"}:
            result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
            return result.get("ok") is not False
        if tool_name in {"desktop.list_apps", "desktop.running_apps"}:
            return False
    return False


def _with_observed_action_metadata(
    request: dict[str, Any],
    target: Mapping[str, Any],
    *,
    action: str,
    target_label: str,
    role_filter: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    app_name = _observed_action_app_name(target)
    request["capability_id"] = "desktop.ui_operation"
    if app_name:
        request.setdefault("target_app_name", app_name)
    app_query = _observed_action_app_query(target)
    if app_query:
        request.setdefault("target_app_query", app_query)
    request["followup_target"] = _compact_observed_action_target(target)
    request["action_target"] = {
        "kind": "desktop_observed_action",
        "action": str(action or "").strip(),
        "target": str(target_label or "").strip(),
        "role_filter": str(role_filter or "").strip(),
    }
    if app_name:
        request["action_target"]["app_name"] = app_name
    request["observation_evidence"] = {
        "source_tool": str(target.get("observation_source") or "desktop.read_ui").strip(),
        **{
            str(key): value
            for key, value in evidence.items()
            if str(key) and value not in (None, "", [], {})
        },
    }
    return request


def _compact_observed_action_target(target: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "desktop_observed_action",
        "target_action": str(target.get("target_action") or "").strip(),
        "target": str(target.get("target") or "").strip(),
        "role_filter": str(target.get("role_filter") or "").strip(),
        "observation_source": str(target.get("observation_source") or "desktop.read_ui").strip(),
    }
    app_name = _observed_action_app_name(target)
    if app_name:
        payload["app_name"] = app_name
    app_query = _observed_action_app_query(target)
    if app_query:
        payload["app_query"] = app_query
    text = str(target.get("text") or "")
    if text:
        payload["text"] = text
    submit_action = str(target.get("submit_action") or "").strip()
    if submit_action:
        payload["submit_action"] = submit_action
    click_count = target.get("click_count")
    if click_count not in (None, ""):
        payload["click_count"] = _clean_model_followup_int(click_count, default=1)
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _request_observability_metadata(request: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "step_id",
        "planner_step_id",
        "capability_id",
        "core_id",
        "workspace_id",
        "task_id",
        "run_id",
        "replan_request_id",
        "replan_trigger",
        "recovery_action_label",
        "recovery_action_tool",
        "recovery_source_tool",
        "recovery_source_event_type",
        "deferred_tool",
        "permission_target",
        "risk_level",
        "target_app_name",
        "target_app_query",
        "target_search_text",
    ):
        value = str(request.get(key) or "").strip()
        if value:
            payload[key] = value
    if payload.get("step_id") and not payload.get("planner_step_id"):
        payload["planner_step_id"] = payload["step_id"]
    deferred_context = (
        request.get("deferred_context")
        if isinstance(request.get("deferred_context"), Mapping)
        else {}
    )
    if deferred_context:
        for key in ("step_id", "planner_step_id", "capability_id"):
            value = str(deferred_context.get(key) or "").strip()
            if value and not payload.get(key):
                payload[key] = value
        if payload.get("step_id") and not payload.get("planner_step_id"):
            payload["planner_step_id"] = payload["step_id"]
        task_todo = (
            deferred_context.get("task_todo")
            if isinstance(deferred_context.get("task_todo"), Mapping)
            else {}
        )
        task_metadata = (
            task_todo.get("metadata")
            if isinstance(task_todo.get("metadata"), Mapping)
            else {}
        )
        for key in ("runtime_doctrine", "runtime_stage", "runtime_role"):
            value = str(task_metadata.get(key) or "").strip()
            if value and not payload.get(key):
                payload[key] = value
        for key in (
            "approval_required",
            "requires_observation",
            "requires_post_action_verification",
        ):
            if key not in payload and isinstance(task_metadata.get(key), bool):
                payload[key] = bool(task_metadata.get(key))
        if (
            "approval_required" not in payload
            and isinstance(task_todo.get("approval_required"), bool)
        ):
            payload["approval_required"] = bool(task_todo.get("approval_required"))
    for key in (
        "permission_recovery_retry",
        "approval_required",
        "requires_observation",
        "requires_post_action_verification",
    ):
        if isinstance(request.get(key), bool):
            payload[key] = bool(request.get(key))
    for key in ("replan_triggers", "replan_signal_ids"):
        values = [
            str(item or "").strip()
            for item in request.get(key, [])
            if str(item or "").strip()
        ] if isinstance(request.get(key), list) else []
        if values:
            payload[key] = values
    payload.update(_runtime_trace_metadata_from_mapping(request))
    for key in (
        "followup_target",
        "action_target",
        "observation_evidence",
        "observation_retry",
        "verification_target",
        "deferred_input",
        "deferred_context",
    ):
        value = request.get(key)
        if isinstance(value, Mapping) and value:
            payload[key] = dict(value)
    deferred_continuation = request.get("deferred_continuation")
    if isinstance(deferred_continuation, list):
        items = [dict(item) for item in deferred_continuation if isinstance(item, Mapping)]
        if items:
            payload["deferred_continuation"] = items
    return payload


def _runtime_planner_request_trace_metadata(
    decision: Any | None,
) -> dict[str, bool] | None:
    if not _runtime_planner_should_trace_tool_requests(decision):
        return None
    return {"runtime_planner_request_trace": True}


def _runtime_planner_full_plan_tool_requests(
    decision: Any | None,
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    if _runtime_planner_full_plan_should_defer_to_context_prefetch(decision):
        return []
    intent_kind = str(
        getattr(getattr(decision, "selected_intent", None), "kind", "") or ""
    ).strip()
    if intent_kind not in _CHAT_FULL_PLAN_EXECUTION_INTENTS:
        return []
    envelope = runtime_execution_envelope_payload(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )
    if not envelope:
        return []
    return _dedupe_runtime_planner_full_plan_requests(
        runtime_execution_requests_from_envelope_payload(
            envelope,
            allowed_tools=allowed_tools,
        )
    )


def _runtime_planner_full_plan_should_defer_to_context_prefetch(
    decision: Any | None,
) -> bool:
    selected_intent = getattr(decision, "selected_intent", None)
    if str(getattr(selected_intent, "kind", "") or "").strip() != "communication":
        return False
    inputs = getattr(selected_intent, "inputs", None)
    if not isinstance(inputs, Mapping):
        return False
    direct_hint = (
        inputs.get("direct_message_hint")
        if isinstance(inputs.get("direct_message_hint"), Mapping)
        else {}
    )
    body_source = str(
        direct_hint.get("body_source") or inputs.get("context_source") or ""
    ).strip()
    transform = str(
        direct_hint.get("content_transform_hint")
        or inputs.get("content_transform_hint")
        or ""
    ).strip()
    if transform and body_source:
        return True
    return body_source in {
        "app_search_result",
        "current_page_content",
        "file",
        "screen_capture",
        "selection",
        "visible_text",
    }


def _split_combined_foreground_app_requests(
    requests: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    split_requests: list[dict[str, Any]] = []
    changed = False
    for request in requests:
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if tool_name in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}:
            action = str(payload.get("action") or "").strip()
            replacement = _split_combined_app_prefix_requests(
                request,
                app_name=app_name,
                starts_open=tool_name.startswith("app.open"),
                allowed=allowed,
            )
            if replacement and action and "desktop.safe_shortcut" in allowed:
                replacement.append(
                    _derived_foreground_request(
                        request,
                        "desktop.safe_shortcut",
                        {"action": action},
                    )
                )
                split_requests.extend(replacement)
                changed = True
                continue
        if tool_name in {"app.open_and_safe_type_text", "app.focus_and_safe_type_text"}:
            text = str(payload.get("text") or "").strip()
            replacement = _split_combined_app_prefix_requests(
                request,
                app_name=app_name,
                starts_open=tool_name.startswith("app.open"),
                allowed=allowed,
            )
            if replacement and text and "desktop.safe_type_text" in allowed:
                replacement.append(
                    _derived_foreground_request(
                        request,
                        "desktop.safe_type_text",
                        {"text": text},
                    )
                )
                split_requests.extend(replacement)
                changed = True
                continue
        split_requests.append(request)
    return split_requests if changed else requests


def _split_combined_app_prefix_requests(
    request: Mapping[str, Any],
    *,
    app_name: str,
    starts_open: bool,
    allowed: set[str],
) -> list[dict[str, Any]]:
    if not app_name:
        return []
    prefix: list[dict[str, Any]] = []
    selection = _app_selection_input(request, app_name)
    if starts_open:
        if "app.open" not in allowed:
            return []
        prefix.append(_derived_foreground_request(request, "app.open", selection))
    if "app.focus" not in allowed:
        return []
    prefix.append(_derived_foreground_request(request, "app.focus", selection))
    return prefix


def _app_selection_input(request: Mapping[str, Any], app_name: str) -> dict[str, Any]:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    result = {"app_name": app_name}
    for key in ("selection_source", "query"):
        value = str(payload.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def _derived_foreground_request(
    source_request: Mapping[str, Any],
    tool_name: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    derived = dict(source_request)
    derived["tool"] = tool_name
    derived.pop("tool_name", None)
    derived["input"] = dict(payload)
    return derived


def _dedupe_runtime_planner_full_plan_requests(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        item = dict(request)
        item = _runtime_planner_request_without_resolved_selection_hints(item)
        key = (
            str(item.get("tool") or item.get("tool_name") or "").strip(),
            _freeze_request_value(item.get("input")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _runtime_planner_execution_requests_with_selection_inputs(
    execution_requests: list[dict[str, Any]],
    selection_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not execution_requests or len(execution_requests) != len(selection_requests):
        return execution_requests
    execution_tools = [
        str(request.get("tool") or request.get("tool_name") or "").strip()
        for request in execution_requests
    ]
    selection_tools = [
        str(request.get("tool") or request.get("tool_name") or "").strip()
        for request in selection_requests
    ]
    if execution_tools != selection_tools:
        return execution_requests
    if any(tool in _DAILY_DESKTOP_DISCOVERY_TOOLS or tool in _DAILY_DESKTOP_VERIFY_TOOLS for tool in execution_tools):
        return execution_requests
    if any(bool(request.get("continue_to_model")) for request in execution_requests):
        return execution_requests
    updated: list[dict[str, Any]] = []
    changed = False
    for execution_request, selection_request in zip(execution_requests, selection_requests):
        selection_input = (
            selection_request.get("input")
            if isinstance(selection_request.get("input"), Mapping)
            else {}
        )
        if not selection_input:
            updated.append(execution_request)
            continue
        execution_input = (
            execution_request.get("input")
            if isinstance(execution_request.get("input"), Mapping)
            else {}
        )
        if dict(selection_input) == dict(execution_input):
            updated.append(execution_request)
            continue
        merged = dict(execution_request)
        merged["input"] = dict(selection_input)
        updated.append(merged)
        changed = True
    return updated if changed else execution_requests


def _runtime_planner_request_without_resolved_selection_hints(
    request: dict[str, Any],
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    if tool_name in _DISCOVERED_APP_SELECTION_SOURCES:
        return request
    changed = False
    resolved = dict(request)
    for key in ("input", "deferred_input"):
        cleaned = _runtime_planner_input_without_resolved_selection_hints(
            resolved.get(key),
        )
        if cleaned is not None:
            resolved[key] = cleaned
            changed = True
    continuation = resolved.get("deferred_continuation")
    if isinstance(continuation, list):
        cleaned_items: list[Any] = []
        for item in continuation:
            if not isinstance(item, Mapping):
                cleaned_items.append(item)
                continue
            next_item = dict(item)
            cleaned = _runtime_planner_input_without_resolved_selection_hints(
                next_item.get("input"),
            )
            if cleaned is not None:
                next_item["input"] = cleaned
                changed = True
            cleaned_items.append(next_item)
        if changed:
            resolved["deferred_continuation"] = cleaned_items
    return resolved if changed else request


def _runtime_planner_input_without_resolved_selection_hints(
    value: Any,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name or _runtime_planner_placeholder_app_name(app_name):
        return None
    cleaned = dict(payload)
    for key in ("selection_source", "app_selection_source", "query"):
        cleaned.pop(key, None)
    return cleaned if cleaned != payload else None


def _freeze_request_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _freeze_request_value(item)) for key, item in value.items())
        )
    if isinstance(value, list):
        return tuple(_freeze_request_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_request_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_request_value(item) for item in value))
    return value


_CHAT_FULL_PLAN_EXECUTION_INTENTS = frozenset(
    {
        "clipboard_operation",
        "communication",
        "desktop_operation",
        "file_access",
        "file_operation",
        "media_playback",
        "schedule",
        "system_control",
    }
)


def _selection_payload_with_runtime_execution_envelope(
    payload: Mapping[str, Any],
    decision: Any | None,
    allowed_tools: Iterable[str],
    *,
    full_plan: bool = False,
    execution_requests: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    enriched = dict(payload)
    envelope = runtime_execution_envelope_payload(
        decision,
        allowed_tools=allowed_tools,
        full_plan=full_plan,
    )
    if not envelope:
        return enriched
    requests = envelope.get("requests") if isinstance(envelope.get("requests"), list) else []
    plan_tool_names = [
        str(request.get("tool_name") or "").strip()
        for request in requests
        if isinstance(request, Mapping) and str(request.get("tool_name") or "").strip()
    ]
    execution_tool_names = _tool_names_from_requests(execution_requests)
    tool_names = execution_tool_names or plan_tool_names
    enriched["yachiyo_execution_envelope"] = envelope
    enriched["yachiyo_execution_request_count"] = len(tool_names)
    if tool_names:
        enriched["yachiyo_execution_requests"] = tool_names
    if execution_tool_names and plan_tool_names and execution_tool_names != plan_tool_names:
        enriched["yachiyo_execution_plan_requests"] = plan_tool_names
        enriched["yachiyo_execution_normalized"] = True
    if full_plan:
        enriched["yachiyo_execution_projection"] = "full_plan"
    return enriched


def _tool_names_from_requests(
    requests: Iterable[Mapping[str, Any]] | None,
) -> list[str]:
    if requests is None:
        return []
    return [
        str(request.get("tool") or request.get("tool_name") or "").strip()
        for request in requests
        if isinstance(request, Mapping)
        and str(request.get("tool") or request.get("tool_name") or "").strip()
    ]


def _tool_requests_include_model_followup(requests: Iterable[Mapping[str, Any]]) -> bool:
    return any(
        bool(request.get("continue_to_model"))
        for request in requests
        if isinstance(request, Mapping)
    )


def _tool_requests_have_unresolved_discovered_app(
    requests: Iterable[Mapping[str, Any]],
) -> bool:
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if app_name and _runtime_planner_placeholder_app_name(app_name):
            return True
        if _discovered_app_selection_source(payload.get("selection_source")):
            return True
        resolution = (
            request.get("input_resolution")
            if isinstance(request.get("input_resolution"), Mapping)
            else {}
        )
        if (
            _discovered_app_selection_source(resolution.get("source_tool"))
            and not str(resolution.get("resolved_app_name") or "").strip()
        ):
            return True
    return False


def _timeline_has_model_followup_context(
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    return any(
        str(event.get("event") or "").strip() == "agent.model.followup_context"
        for event in timeline[tool_timeline_start:]
        if isinstance(event, Mapping)
    )


def _latest_message_is_model_followup_context(messages: list[dict[str, Any]]) -> bool:
    if not messages:
        return False
    content = str(messages[-1].get("content") or "")
    return content.startswith("Runtime follow-up context:")


def _discovered_app_resolution_probe_requests(
    requests: list[dict[str, Any]],
    selection_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not requests:
        return requests
    target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), Mapping)
        else {}
    )
    if str(target.get("kind") or "").strip() != "desktop_discovered_app_action":
        return requests
    communication_compose = (
        target.get("communication_compose")
        if isinstance(target.get("communication_compose"), Mapping)
        else {}
    )
    if not communication_compose:
        return requests
    app_query = str(target.get("app_query") or "").strip()
    if not app_query:
        return requests
    discovery_index = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in _DISCOVERED_APP_SELECTION_SOURCES:
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if (
            tool_name == "desktop.running_apps"
            or str(payload.get("query") or "").strip() == app_query
        ):
            discovery_index = index
            break
    if discovery_index < 0:
        return requests
    if not any(
        _request_uses_selected_desktop_app_result(request, app_query)
        for request in requests[discovery_index + 1 :]
    ):
        return requests
    probe_requests = [dict(request) for request in requests[: discovery_index + 1]]
    probe_requests[-1]["continue_to_model"] = True
    return probe_requests


def _request_uses_selected_desktop_app_result(
    request: Mapping[str, Any],
    app_query: str,
) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    selection_source = _discovered_app_selection_source(
        payload.get("selection_source")
        or payload.get("app_selection_source")
    )
    if not selection_source:
        return False
    if str(payload.get("query") or "").strip() != str(app_query or "").strip():
        return False
    return _discovered_app_placeholder_source(payload.get("app_name")) == selection_source


def _tool_requests_without_model_followup(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        item = dict(request)
        item.pop("continue_to_model", None)
        cleaned.append(item)
    return cleaned


def _direct_sequence_requests_with_safe_deferred_continuations(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    allowed = {str(tool or "").strip() for tool in _DIRECT_DAILY_DESKTOP_TOOLS}
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        item = dict(request)
        expanded.append(item)
        if bool(item.get("continue_to_model")):
            continue
        for continuation in _mapping_list(item.get("deferred_continuation")):
            next_request = _runtime_replan_safe_deferred_continuation_request(
                continuation,
                allowed,
            )
            if not next_request:
                continue
            for key, value in _runtime_replan_deferred_inherited_metadata(item).items():
                next_request.setdefault(key, value)
            next_request.setdefault(
                "source",
                str(item.get("source") or "runtime_planner").strip(),
            )
            next_request.setdefault(
                "planning_reason",
                "planner_replan_deferred_continuation",
            )
            expanded.append(next_request)
    return expanded


def _desktop_intent_verification_evidence(
    completed_steps: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    for step in reversed([item for item in completed_steps if isinstance(item, Mapping)]):
        tool_name = str(step.get("tool") or "").strip()
        if tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS:
            continue
        result = step.get("result") if isinstance(step.get("result"), Mapping) else {}
        if not result:
            continue
        status = _desktop_verification_status(result)
        if not status:
            continue
        evidence: dict[str, Any] = {
            "verification_status": status,
            "verification_tool": tool_name,
            "verification_result": _desktop_verification_result_preview(result),
        }
        for key in (
            "step_id",
            "planner_step_id",
            "replan_request_id",
            "replan_trigger",
            "target_app_name",
            "target_app_query",
            "target_search_text",
        ):
            value = step.get(key)
            if value not in (None, "", [], {}):
                evidence[key] = value
        verification_target = (
            step.get("verification_target")
            if isinstance(step.get("verification_target"), Mapping)
            else {}
        )
        if verification_target:
            evidence["verification_target"] = dict(verification_target)
        if tool_name == "desktop.active_window":
            evidence.update(
                _active_window_verification_evidence(
                    step,
                    result,
                    verification_target=verification_target,
                )
            )
        if tool_name in {"desktop.read_ui", "desktop.ui_elements"}:
            evidence.update(
                _ui_observation_verification_evidence(
                    step,
                    result,
                    tool_name=tool_name,
                    verification_target=verification_target,
                )
            )
        return {key: value for key, value in evidence.items() if value not in ("", [], {})}
    return {}


def _desktop_verification_status(result: Mapping[str, Any]) -> str:
    if result.get("approval_required"):
        return "waiting_approval"
    if result.get("verification_failed") is True:
        return "verification_failed"
    if result.get("ok") is True:
        return "verified"
    if result.get("ok") is False:
        return "verification_failed"
    return ""


def _desktop_verification_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "action",
        "summary",
        "error",
        "hint",
        "verification_failed",
        "blocking_condition",
        "expected_app_name",
        "active_app_name",
    ):
        value = result.get(key)
        if value not in (None, "", [], {}):
            preview[key] = value
    for key in ("app_name", "title", "frontmost_app", "frontmost_app_name"):
        value = data.get(key)
        if value not in (None, "", [], {}):
            preview[key] = value
    return preview


def _active_window_verification_evidence(
    step: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    verification_target: Mapping[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    expected_app_name = _first_nonempty_text(
        verification_target.get("app_name"),
        verification_target.get("target_app_name"),
        verification_target.get("expected_app_name"),
        step.get("target_app_name"),
        result.get("expected_app_name"),
        data.get("expected_app_name"),
    )
    active_app_name = _first_nonempty_text(
        result.get("active_app_name"),
        data.get("active_app_name"),
        data.get("app_name"),
        result.get("app_name"),
        data.get("frontmost_app"),
        data.get("frontmost_app_name"),
    )
    evidence = {
        "expected_app_name": expected_app_name,
        "active_app_name": active_app_name,
        "active_window_title": _first_nonempty_text(data.get("title"), result.get("title")),
    }
    if expected_app_name and active_app_name:
        evidence["focus_verified"] = _replan_app_names_match(
            expected_app_name,
            active_app_name,
        )
    return {key: value for key, value in evidence.items() if value not in ("", [], {})}


def _ui_observation_verification_evidence(
    step: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    tool_name: str,
    verification_target: Mapping[str, Any],
) -> dict[str, Any]:
    target = _ui_observation_verification_target(step, verification_target)
    target_text = _first_nonempty_text(
        target.get("target"),
        target.get("target_search_text"),
        target.get("target_label"),
        target.get("ui_target"),
        target.get("element_name"),
        target.get("name"),
    )
    role_filter = _first_nonempty_text(target.get("role_filter"), target.get("role"))
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    app_name = _first_nonempty_text(
        _observed_action_app_name(target),
        step.get("target_app_name"),
        data.get("app_name"),
    )
    elements = _desktop_observation_result_elements(tool_name, result)
    evidence: dict[str, Any] = {
        "ui_element_count": len(elements),
    }
    if app_name:
        evidence["ui_app_name"] = app_name
    if target_text:
        evidence["ui_target"] = target_text
    if role_filter:
        evidence["ui_role_filter"] = role_filter
    if target_text:
        matches = _ui_observation_target_matches(elements, target_text, role_filter)
        evidence["ui_target_found"] = bool(matches)
        evidence["ui_match_count"] = len(matches)
        if matches:
            evidence["ui_matches"] = [
                _compact_ui_observation_match(match)
                for match in matches[:3]
            ]
    return {key: value for key, value in evidence.items() if value not in ("", [], {})}


def _ui_observation_verification_target(
    step: Mapping[str, Any],
    verification_target: Mapping[str, Any],
) -> dict[str, Any]:
    target: dict[str, Any] = {}
    for source in (
        step.get("followup_target"),
        step.get("action_target"),
        step.get("input_preview"),
        verification_target,
    ):
        if not isinstance(source, Mapping):
            continue
        for key in (
            "kind",
            "target",
            "target_search_text",
            "target_label",
            "ui_target",
            "element_name",
            "name",
            "role_filter",
            "role",
            "app_name",
            "target_app_name",
            "app_query",
            "target_app_query",
        ):
            value = source.get(key)
            if value not in (None, "", [], {}) and key not in target:
                target[key] = value
    return target


def _compact_ui_observation_match(element: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("role", "subrole", "name", "description", "value", "label"):
        value = _compact_ui_observation_text(element.get(key))
        if value:
            payload[key] = value
    center = element.get("center") if isinstance(element.get("center"), Mapping) else {}
    if center.get("x") is not None and center.get("y") is not None:
        payload["center"] = {"x": center.get("x"), "y": center.get("y")}
    if isinstance(element.get("enabled"), bool):
        payload["enabled"] = bool(element.get("enabled"))
    return payload


def _compact_ui_observation_text(value: Any, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _split_model_materialization_tool_requests(
    requests: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    immediate: list[dict[str, Any]] = []
    materialization: list[dict[str, Any]] = []
    defer_remaining = False
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        item = dict(request)
        if defer_remaining or _tool_request_requires_model_materialization(item):
            defer_remaining = True
            materialization.append(item)
        else:
            immediate.append(item)
    return immediate, materialization


def _tool_request_requires_model_materialization(request: Mapping[str, Any]) -> bool:
    if not isinstance(request, Mapping) or not bool(request.get("continue_to_model")):
        return False
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    request_input = (
        request.get("input") if isinstance(request.get("input"), Mapping) else {}
    )
    body_source = str(request_input.get("body_source") or "").strip()
    if tool_name == "notes.create":
        return bool(body_source) and not str(request_input.get("body") or "").strip()
    if tool_name == "artifact.write":
        if str(request_input.get("content") or "").strip():
            return False
        return bool(
            body_source
            or str(request_input.get("path") or "").strip()
            or request_input.get("paths")
        )
    if tool_name == "clipboard.write":
        return bool(body_source) and not str(request_input.get("text") or "").strip()
    if tool_name in _MODEL_FOLLOWUP_TEXT_ENTRY_TOOLS:
        return bool(body_source) and not str(request_input.get("text") or "").strip()
    return False


def _runtime_planner_should_trace_tool_requests(decision: Any | None) -> bool:
    steps = getattr(
        getattr(getattr(decision, "plan", None), "tool_plan", None),
        "steps",
        None,
    )
    if not isinstance(steps, Iterable) or isinstance(steps, (str, bytes)):
        return False
    observable_steps = [
        step
        for step in steps
        if str(getattr(step, "tool_name", "") or "").strip()
        and str(getattr(step, "step_id", "") or "").strip()
    ]
    if any(bool(getattr(step, "approval_required", False)) for step in observable_steps):
        return True
    return len(observable_steps) > 1


def _approval_required_planner_trace_payload(
    pending_approval: Mapping[str, Any],
    planned_request: Mapping[str, Any],
) -> dict[str, Any]:
    tool_request = (
        pending_approval.get("tool_request")
        if isinstance(pending_approval.get("tool_request"), Mapping)
        else {}
    )
    payload: dict[str, Any] = {}
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "step_id",
        "planner_step_id",
        "capability_id",
        "replan_request_id",
        "replan_trigger",
    ):
        value = str(tool_request.get(key) or planned_request.get(key) or "").strip()
        if value:
            payload[key] = value
    if payload.get("step_id") and not payload.get("planner_step_id"):
        payload["planner_step_id"] = payload["step_id"]
    payload.update(
        {
            **_runtime_trace_metadata_from_mapping(planned_request),
            **_runtime_trace_metadata_from_mapping(tool_request),
        }
    )
    return payload


def _step_observability_metadata(step: Mapping[str, Any]) -> dict[str, Any]:
    return _request_observability_metadata(step)


def _desktop_observed_action_execution_target(target: str, role_filter: str) -> str:
    clean_target = str(target or "").strip()
    normalized_target = _normalize_observed_desktop_text(clean_target)
    normalized_filter = _normalize_observed_desktop_text(role_filter)
    if normalized_target in {"text input", "input"} and normalized_filter in {
        "text field",
        "textfield",
        "axtextfield",
    }:
        return "text field"
    return clean_target


def _latest_desktop_observation_match_center(
    timeline: list[dict[str, Any]],
    target: str,
    role_filter: str,
) -> dict[str, Any]:
    elements = _latest_desktop_observation_elements(timeline)
    if not elements:
        return {}
    ordinal = _observed_desktop_target_ordinal(target)
    if ordinal:
        matches = _ordinal_observed_desktop_elements(elements, ordinal, role_filter)
        if matches:
            center = (
                matches[0].get("center")
                if isinstance(matches[0].get("center"), Mapping)
                else {}
            )
            x = center.get("x")
            y = center.get("y")
            if x is not None and y is not None:
                return {"x": x, "y": y}
    matches = _matching_observed_desktop_elements(elements, target, role_filter)
    if not matches:
        return {}
    center = (
        matches[0].get("center")
        if isinstance(matches[0].get("center"), Mapping)
        else {}
    )
    x = center.get("x")
    y = center.get("y")
    if x is None or y is None:
        return {}
    return {"x": x, "y": y}


def _latest_desktop_observation_has_target_match(
    timeline: list[dict[str, Any]],
    target: str,
    role_filter: str,
) -> bool:
    elements = _latest_desktop_observation_elements(timeline)
    if not elements:
        return False
    target_text = _normalize_observed_desktop_text(target)
    if not target_text:
        return False
    ordinal = _observed_desktop_target_ordinal(target)
    if ordinal:
        return bool(_ordinal_observed_desktop_elements(elements, ordinal, role_filter))
    normalized_filter = _normalize_observed_desktop_text(role_filter)
    for raw_element in elements:
        if not isinstance(raw_element, Mapping):
            continue
        element = dict(raw_element)
        if element.get("enabled") is False:
            continue
        searchable = _normalize_observed_desktop_text(
            " ".join(
                str(element.get(key) or "")
                for key in ("role", "subrole", "name", "description", "value", "label")
            )
        )
        if normalized_filter and not _observed_desktop_text_matches(
            searchable,
            normalized_filter,
        ):
            continue
        if _observed_desktop_element_match_score(element, target_text, role_filter) > 0:
            return True
    return False


def _latest_desktop_observation_elements(timeline: list[dict[str, Any]]) -> list[Any]:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or "").strip()
        if tool_name not in {"desktop.read_ui", "desktop.ui_elements", "desktop.inspect_app"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True:
            return []
        elements = _desktop_observation_result_elements(tool_name, result)
        if elements:
            return elements
    return []


def _desktop_observation_result_elements(tool_name: str, result: Mapping[str, Any]) -> list[Any]:
    if str(tool_name or "").strip() == "desktop.inspect_app":
        return _inspect_app_observation_elements(result)
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    elements = data.get("elements")
    if isinstance(elements, list):
        return elements
    elements = result.get("elements")
    return elements if isinstance(elements, list) else []


def _inspect_app_observation_elements(result: Mapping[str, Any]) -> list[Any]:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    ui_result = data.get("ui_elements") if isinstance(data.get("ui_elements"), Mapping) else {}
    ui_data = ui_result.get("data") if isinstance(ui_result.get("data"), Mapping) else {}
    elements = ui_data.get("elements")
    if isinstance(elements, list):
        return elements
    elements = ui_result.get("elements")
    if isinstance(elements, list):
        return elements
    elements = data.get("elements")
    return elements if isinstance(elements, list) else []


def _observed_desktop_target_ordinal(target: str) -> int:
    normalized = _normalize_observed_desktop_text(target)
    if normalized in {
        "first result",
        "first item",
        "top result",
        "第一个结果",
        "第1个结果",
        "第一项",
        "第一个",
        "首个结果",
    }:
        return 1
    match = re.fullmatch(r"(?:result|item)\s*(\d+)", normalized)
    if match:
        return max(1, int(match.group(1)))
    match = re.fullmatch(r"第\s*(\d+)\s*(?:个)?(?:结果|项目|项)?", normalized)
    if match:
        return max(1, int(match.group(1)))
    return 0


def _ordinal_observed_desktop_elements(
    elements: list[Any],
    ordinal: int,
    role_filter: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    normalized_filter = _normalize_observed_desktop_text(role_filter)
    for raw_element in elements:
        if not isinstance(raw_element, Mapping):
            continue
        element = dict(raw_element)
        if element.get("enabled") is False:
            continue
        center = element.get("center") if isinstance(element.get("center"), Mapping) else {}
        if center.get("x") is None or center.get("y") is None:
            continue
        searchable = _normalize_observed_desktop_text(
            " ".join(
                str(element.get(key) or "")
                for key in ("role", "subrole", "name", "description", "value", "label")
            )
        )
        if normalized_filter:
            if not _observed_desktop_text_matches(searchable, normalized_filter):
                continue
        elif not _observed_desktop_element_looks_actionable_result(element, searchable):
            continue
        candidates.append(element)
    index = max(0, ordinal - 1)
    return candidates[index : index + 1]


def _observed_desktop_element_looks_actionable_result(
    element: Mapping[str, Any],
    searchable: str,
) -> bool:
    if not searchable:
        return False
    if any(
        token in searchable
        for token in (
            "text field",
            "search field",
            "toolbar",
            "menu bar",
            "window",
        )
    ):
        return False
    if any(
        token in searchable
        for token in (
            "button",
            "link",
            "row",
            "cell",
            "group",
            "static text",
            "image",
        )
    ):
        return True
    label = str(
        element.get("name")
        or element.get("description")
        or element.get("label")
        or ""
    ).strip()
    return bool(label)


def _matching_observed_desktop_elements(
    elements: list[Any],
    target: str,
    role_filter: str,
) -> list[dict[str, Any]]:
    target_text = _normalize_observed_desktop_text(target)
    if not target_text:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, raw_element in enumerate(elements):
        if not isinstance(raw_element, Mapping):
            continue
        element = dict(raw_element)
        if element.get("enabled") is False:
            continue
        center = element.get("center") if isinstance(element.get("center"), Mapping) else {}
        if center.get("x") is None or center.get("y") is None:
            continue
        score = _observed_desktop_element_match_score(element, target_text, role_filter)
        if score <= 0:
            continue
        depth = element.get("depth") if isinstance(element.get("depth"), int) else 0
        scored.append((score - depth, -index, element))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [element for _, _, element in scored]


def _observed_desktop_element_match_score(
    element: Mapping[str, Any],
    normalized_target: str,
    role_filter: str,
) -> int:
    label_texts = [
        _normalize_observed_desktop_text(element.get(key))
        for key in ("name", "description", "value", "label")
    ]
    label_texts = [text for text in label_texts if text]
    searchable = _normalize_observed_desktop_text(
        " ".join(
            str(element.get(key) or "")
            for key in ("role", "subrole", "name", "description", "value", "label")
        )
    )
    if not searchable:
        return 0
    score = 0
    for target in _observed_desktop_text_candidates(normalized_target):
        if target in label_texts:
            score = max(score, 100)
        elif any(target in text for text in label_texts):
            score = max(score, 85)
        elif any(text in target for text in label_texts if len(text) >= 2):
            score = max(score, 70)
        elif target in searchable:
            score = max(score, 55)
    if not score:
        return 0
    normalized_filter = _normalize_observed_desktop_text(role_filter)
    if normalized_filter and _observed_desktop_text_matches(searchable, normalized_filter):
        score += 10
    if str(element.get("role") or "").strip():
        score += 2
    return score


def _normalize_observed_desktop_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"\baxtextfield\b", "text field", text)
    text = re.sub(r"\baxbutton\b", "button", text)
    text = re.sub(r"\baxlink\b", "link", text)
    return re.sub(r"\s+", " ", text)


_OBSERVED_DESKTOP_TEXT_EQUIVALENTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("搜索框", "搜尋框", "查找框", "搜索栏", "搜尋欄"), ("search", "search field", "search box")),
    (("搜索", "搜尋", "查找", "查詢", "查询"), ("search", "find")),
    (("输入框", "輸入框", "文本框", "文字框"), ("text field", "input", "input field", "text input")),
    (("输入", "輸入", "填写", "填寫"), ("type", "input")),
    (("按钮", "按鈕"), ("button",)),
    (("链接", "連結", "联结"), ("link",)),
)


def _observed_desktop_text_candidates(normalized_text: str) -> list[str]:
    clean_text = _normalize_observed_desktop_text(normalized_text)
    if not clean_text:
        return []
    candidates = [clean_text]
    for sources, aliases in _OBSERVED_DESKTOP_TEXT_EQUIVALENTS:
        for source in sources:
            if source not in clean_text:
                continue
            for alias in aliases:
                clean_alias = _normalize_observed_desktop_text(alias)
                if not clean_alias:
                    continue
                candidates.append(clean_alias)
                candidates.append(clean_text.replace(source, clean_alias))
    return _ordered_text_list(candidates)


def _observed_desktop_text_matches(searchable: str, normalized_query: str) -> bool:
    clean_searchable = _normalize_observed_desktop_text(searchable)
    if not clean_searchable:
        return False
    return any(
        candidate and candidate in clean_searchable
        for candidate in _observed_desktop_text_candidates(normalized_query)
    )


def _drop_completed_auto_followup_prefix(
    requests: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[dict[str, Any]]:
    remaining = list(requests)
    while remaining and _auto_followup_request_completed(
        remaining[0],
        timeline,
        tool_timeline_start=tool_timeline_start,
    ):
        remaining = remaining[1:]
    return remaining


def _auto_followup_request_completed(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    if (
        request.get("deferred_tool")
        or request.get("deferred_input")
        or request.get("deferred_continuation")
    ):
        return False
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return False
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    for event in timeline[tool_timeline_start:]:
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        if str(event.get("detail") or "").strip() != tool_name:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True or result.get("approval_required"):
            continue
        event_input = event.get("input_preview") if isinstance(event.get("input_preview"), Mapping) else {}
        if _auto_followup_input_matches_event(request_input, event_input):
            return True
    return False


def _auto_followup_input_matches_event(
    request_input: Mapping[str, Any],
    event_input: Mapping[str, Any],
) -> bool:
    comparable = {
        str(key): value
        for key, value in request_input.items()
        if str(key) not in {"selection_source", "query"}
    }
    if not comparable:
        return True
    return all(
        str(event_input.get(key) or "") == str(value or "")
        for key, value in comparable.items()
    )


def _auto_replan_verification_recovery_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    verification_payloads = [
        payload
        for payload in replan_payloads
        if isinstance(payload, Mapping)
        and str(payload.get("trigger") or "").strip() == "verification_failed"
        and not _replan_payload_is_focus_mismatch(payload)
        and str(payload.get("source_step_id") or "").strip()
        in {"verify-desktop-result", "observe-selected-discovered-app"}
    ]
    if not verification_payloads:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    first = verification_payloads[0]
    request_id = str(first.get("request_id") or "").strip()
    source = "runtime_planner"
    planning_reason = "planner_verification_recovery_observation"
    target = _replan_recovery_target(first)
    explicit_recovery_tools = _runtime_recovery_action_tools_for_payload(first)
    requests: list[dict[str, Any]] = []
    for tool_name in _verification_recovery_tool_order(allowed):
        if tool_name in explicit_recovery_tools:
            continue
        request_input = _verification_recovery_tool_input(tool_name, target)
        if request_input is None:
            continue
        request = _request_like(
            tool_name,
            request_input,
            source=source,
            planning_reason=planning_reason,
        )
        if request_id:
            request["replan_request_id"] = request_id
        request["replan_trigger"] = "verification_failed"
        request["continue_to_model"] = True
        for key, value in target.items():
            if value:
                request[key] = value
        _attach_replan_payload_trace_metadata(request, first)
        _attach_replan_active_window_verification_target(request, target)
        requests.append(request)
    return requests


def _runtime_recovery_action_tools_for_payload(payload: Mapping[str, Any]) -> set[str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return {
        str(action.get("tool") or "").strip()
        for action in _mapping_list(metadata.get("recovery_actions"))
        if str(action.get("tool") or "").strip()
    }


def _auto_replan_ui_observation_recovery_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "tool_failure":
            continue
        target = _replan_ui_observed_action_target(payload)
        if not target:
            continue
        tool_name = _replan_ui_observation_tool(target, allowed)
        if not tool_name:
            continue
        request = _request_like(
            tool_name,
            _replan_ui_observation_input(tool_name, target),
            source="runtime_planner",
            planning_reason="planner_replan_ui_observation_recovery",
        )
        request_id = str(payload.get("request_id") or "").strip()
        if request_id:
            request["replan_request_id"] = request_id
        request["replan_trigger"] = "tool_failure"
        request["continue_to_model"] = True
        for key in ("target_app_name", "target_app_query", "target_search_text"):
            value = str(target.get(key) or "").strip()
            if value:
                request[key] = value
        _attach_replan_payload_trace_metadata(request, payload)
        requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _auto_replan_verification_observed_action_requests(
    replan_payloads: list[dict[str, Any]],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not allowed or not planned or not _latest_desktop_observation_succeeded(timeline):
        return []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "verification_failed":
            continue
        if not _replan_payload_has_missing_ui_target(payload):
            continue
        source_request = _replan_verification_source_ui_action_request(planned, payload)
        if not source_request:
            continue
        action_payload = _replan_verification_observed_action_payload(
            payload,
            source_request,
        )
        target = _replan_ui_observed_action_target(action_payload)
        if not target:
            continue
        target = _replan_ui_observed_action_target_with_timeline_context(
            target,
            action_payload,
            timeline,
        )
        target_label = str(target.get("target") or "").strip()
        role_filter = str(target.get("role_filter") or "").strip()
        if not _latest_desktop_observation_has_target_match(
            timeline,
            target_label,
            role_filter,
        ):
            continue
        observation_source = _latest_desktop_observation_tool(timeline)
        if observation_source:
            target["observation_source"] = observation_source
        source_tool = _replan_source_tool_name(action_payload)
        scoped_allowed = _replan_ui_observed_action_scoped_allowed_tools(
            source_tool,
            target,
            allowed,
            timeline,
        )
        if not scoped_allowed:
            continue
        requests = _auto_desktop_observed_action_followup_requests(
            {"followup_target": target},
            scoped_allowed,
            timeline,
            planning_reason=planning_reason,
        )
        if not requests:
            continue
        requests = _annotate_replan_ui_observed_action_requests(requests, action_payload)
        return _replan_recovery_requests_with_task_context(
            requests,
            [action_payload],
            timeline,
        )
    return []


def _replan_payload_has_missing_ui_target(payload: Mapping[str, Any]) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    if metadata.get("ui_target_found") is False:
        return True
    blocking_conditions = {
        str(item or "").strip()
        for item in _string_list(metadata.get("blocking_conditions"))
    }
    return "ui_target_not_found" in blocking_conditions


def _replan_verification_source_ui_action_request(
    planned_tool_requests: list[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    source_index = _replan_source_request_index(planned_tool_requests, payload)
    candidates = (
        planned_tool_requests[:source_index]
        if source_index >= 0
        else planned_tool_requests
    )
    target_text = str(_replan_recovery_target(payload).get("target_search_text") or "").strip()
    for request in reversed(candidates):
        if not isinstance(request, Mapping):
            continue
        tool_name = str(request.get("tool") or "").strip()
        if _replan_ui_target_action(tool_name) != "click":
            continue
        if not _replan_ui_action_request_matches_target(request, target_text):
            continue
        return dict(request)
    return {}


def _replan_ui_action_request_matches_target(
    request: Mapping[str, Any],
    target_text: str,
) -> bool:
    clean_target = _normalize_observed_desktop_text(target_text)
    if not clean_target:
        return True
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    request_target = _normalize_observed_desktop_text(
        request_input.get("target")
        or request_input.get("target_search_text")
        or request_input.get("text")
        or request_input.get("value")
        or ""
    )
    if not request_target:
        return False
    return (
        _observed_desktop_text_matches(request_target, clean_target)
        or _observed_desktop_text_matches(clean_target, request_target)
    )


def _replan_verification_observed_action_payload(
    payload: Mapping[str, Any],
    source_request: Mapping[str, Any],
) -> dict[str, Any]:
    request_input = (
        dict(source_request.get("input"))
        if isinstance(source_request.get("input"), Mapping)
        else {}
    )
    action_payload = dict(payload)
    metadata = (
        dict(payload.get("metadata"))
        if isinstance(payload.get("metadata"), Mapping)
        else {}
    )
    metadata["verification_source_step_id"] = str(
        payload.get("source_step_id") or payload.get("planner_step_id") or ""
    ).strip()
    metadata["verification_source_tool_name"] = str(
        payload.get("source_tool_name") or payload.get("tool_name") or ""
    ).strip()
    metadata["input_preview"] = request_input
    action_payload["metadata"] = {
        key: value for key, value in metadata.items() if value not in (None, "", [], {})
    }
    action_payload["input_preview"] = request_input
    step_id = str(
        source_request.get("step_id") or source_request.get("planner_step_id") or ""
    ).strip()
    if step_id:
        action_payload["source_step_id"] = step_id
        action_payload["planner_step_id"] = step_id
    tool_name = str(source_request.get("tool") or "").strip()
    if tool_name:
        action_payload["source_tool_name"] = tool_name
    capability_id = str(source_request.get("capability_id") or "").strip()
    if capability_id:
        action_payload["target_capability_id"] = capability_id
    return action_payload


def _auto_replan_ui_observed_action_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed or not _latest_desktop_observation_succeeded(timeline):
        return []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "tool_failure":
            continue
        target = _replan_ui_observed_action_target(payload)
        if not target:
            continue
        target = _replan_ui_observed_action_target_with_timeline_context(
            target,
            payload,
            timeline,
        )
        if _replan_ui_observed_action_retry_succeeded(payload, timeline):
            continue
        target_label = str(target.get("target") or "").strip()
        role_filter = str(target.get("role_filter") or "").strip()
        if not _latest_desktop_observation_has_target_match(
            timeline,
            target_label,
            role_filter,
        ):
            continue
        observation_source = _latest_desktop_observation_tool(timeline)
        if observation_source:
            target["observation_source"] = observation_source
        source_tool = _replan_source_tool_name(payload)
        scoped_allowed = _replan_ui_observed_action_scoped_allowed_tools(
            source_tool,
            target,
            allowed,
            timeline,
        )
        if not scoped_allowed:
            continue
        requests = _auto_desktop_observed_action_followup_requests(
            {"followup_target": target},
            scoped_allowed,
            timeline,
            planning_reason=planning_reason,
        )
        if not requests:
            continue
        requests = _annotate_replan_ui_observed_action_requests(requests, payload)
        return _replan_recovery_requests_with_task_context(
            requests,
            [dict(payload)],
            timeline,
        )
    return []


def _replan_ui_observed_action_scoped_allowed_tools(
    source_tool: str,
    target: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
) -> list[str]:
    observation_tools = (
        "desktop.read_ui",
        "desktop.ui_elements",
        "desktop.active_window",
        "screen.capture",
    )
    target_action = str(target.get("target_action") or "").strip()
    if (
        target_action == "click"
        and source_tool in {
            "app.open_and_click_ui_element",
            "app.focus_and_click_ui_element",
            "desktop.click_ui_element",
        }
    ):
        target_label = str(target.get("target") or "").strip()
        role_filter = str(target.get("role_filter") or "").strip()
        if _latest_desktop_observation_match_center(timeline, target_label, role_filter):
            low_level_tools = [
                tool for tool in ("desktop.safe_click", "desktop.click") if tool in allowed
            ]
            if low_level_tools:
                return [
                    *low_level_tools,
                    *[tool for tool in observation_tools if tool in allowed],
                ]
    if (
        target_action == "type_text"
        and source_tool in {
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        }
    ):
        role_filter = str(target.get("role_filter") or "").strip()
        target_label = _desktop_observed_action_execution_target(
            str(target.get("target") or "").strip(),
            role_filter,
        )
        if _latest_desktop_observation_match_center(timeline, target_label, role_filter):
            focus_tools = [
                tool for tool in ("desktop.safe_click", "desktop.click") if tool in allowed
            ]
            type_tools = [
                tool
                for tool in ("desktop.safe_type_text", "desktop.type_text", "desktop.type")
                if tool in allowed
            ]
            if focus_tools and type_tools:
                return [
                    *focus_tools,
                    *type_tools,
                    *[tool for tool in observation_tools if tool in allowed],
                ]
    return [
        tool
        for tool in (
            source_tool,
            *observation_tools,
        )
        if tool and tool in allowed
    ]


def _replan_ui_observed_action_target(payload: Mapping[str, Any]) -> dict[str, Any]:
    source_tool = _replan_source_tool_name(payload)
    target_action = _replan_ui_target_action(source_tool)
    if not target_action:
        return {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    input_preview = (
        payload.get("input_preview")
        if isinstance(payload.get("input_preview"), Mapping)
        else {}
    )
    metadata_input = (
        metadata.get("input_preview")
        if isinstance(metadata.get("input_preview"), Mapping)
        else {}
    )
    source_input = {**dict(metadata_input), **dict(input_preview)}
    target_label = str(source_input.get("target") or "").strip()
    if not target_label:
        return {}
    target: dict[str, Any] = {
        "kind": "desktop_observed_action",
        "target_action": target_action,
        "target": target_label,
        "role_filter": str(source_input.get("role_filter") or "").strip(),
        "limit": _clean_model_followup_int(source_input.get("limit"), default=80),
    }
    recovery_target = _replan_recovery_target(payload)
    app_name = str(
        recovery_target.get("target_app_name")
        or source_input.get("app_name")
        or ""
    ).strip()
    if app_name:
        target["app_name"] = app_name
        target["target_app_name"] = app_name
    app_query = str(
        recovery_target.get("target_app_query")
        or source_input.get("query")
        or source_input.get("app_query")
        or ""
    ).strip()
    if app_query:
        target["app_query"] = app_query
        target["target_app_query"] = app_query
    search_text = str(
        recovery_target.get("target_search_text")
        or source_input.get("text")
        or source_input.get("value")
        or ""
    ).strip()
    if search_text:
        target["target_search_text"] = search_text
    if target_action == "click":
        target["click_count"] = _clean_model_followup_int(
            source_input.get("click_count"),
            default=1,
        )
    else:
        text = str(source_input.get("text") or "")
        if not text:
            return {}
        target["text"] = text
    return {key: value for key, value in target.items() if value not in ("", None, [], {})}


def _replan_ui_observed_action_target_with_timeline_context(
    target: Mapping[str, Any],
    payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    resolved = dict(target)
    app_query = str(
        resolved.get("app_query")
        or resolved.get("target_app_query")
        or _replan_recovery_target(payload).get("target_app_query")
        or ""
    ).strip()
    if app_query:
        resolved["app_query"] = app_query
        resolved["target_app_query"] = app_query

    app_name = str(resolved.get("app_name") or resolved.get("target_app_name") or "").strip()
    if app_name and not _runtime_planner_placeholder_app_name(app_name):
        return resolved

    discovered = _discovered_app_context_app_name(
        resolved,
        timeline,
        replan_payloads=[payload],
    )
    if not discovered:
        request_id = str(payload.get("request_id") or "").strip()
        discovered = _latest_replan_context_app_name(timeline, request_id=request_id)
    if discovered and not _runtime_planner_placeholder_app_name(discovered):
        resolved["app_name"] = discovered
        resolved["target_app_name"] = discovered
    return resolved


def _latest_replan_context_app_name(
    timeline: list[dict[str, Any]],
    *,
    request_id: str,
) -> str:
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        event_request_id = str(event.get("replan_request_id") or "").strip()
        if request_id and event_request_id and event_request_id != request_id:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        input_preview = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        for source in (event, data, result, input_preview):
            for key in (
                "target_app_name",
                "app_name",
                "active_app_name",
                "frontmost_app",
                "resolved_app_name",
                "discovered_app_name",
            ):
                app_name = str(source.get(key) or "").strip()
                if app_name and not _runtime_planner_placeholder_app_name(app_name):
                    return app_name
    return ""


def _replan_source_tool_name(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return str(
        payload.get("source_tool_name")
        or payload.get("tool_name")
        or payload.get("planned_tool_name")
        or metadata.get("planned_tool_name")
        or ""
    ).strip()


def _replan_ui_target_action(tool_name: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if clean_tool in {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "desktop.click_ui_element",
    }:
        return "click"
    if clean_tool in {
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.type_into_ui_element",
    }:
        return "type_text"
    return ""


def _replan_ui_observation_tool(target: Mapping[str, Any], allowed: set[str]) -> str:
    app_name = _observed_action_app_name(target)
    if app_name and "desktop.inspect_app" in allowed:
        return "desktop.inspect_app"
    return _first_allowed_tool(
        ("desktop.ui_elements", "desktop.read_ui", "screen.capture"),
        allowed,
    )


def _replan_ui_observation_input(
    tool_name: str,
    target: Mapping[str, Any],
) -> dict[str, Any]:
    clean_tool = str(tool_name or "").strip()
    app_name = _observed_action_app_name(target)
    role_filter = str(target.get("role_filter") or "").strip()
    limit = _clean_model_followup_int(target.get("limit"), default=80)
    if clean_tool == "desktop.inspect_app":
        payload: dict[str, Any] = {
            "app_name": app_name,
            "open_if_needed": True,
            "focus": True,
            "limit": limit,
        }
        if role_filter:
            payload["role_filter"] = role_filter
        return payload
    if clean_tool in {"desktop.ui_elements", "desktop.read_ui"}:
        payload = {"limit": limit}
        if app_name:
            payload["app_name"] = app_name
        if role_filter:
            payload["role_filter"] = role_filter
        return payload
    if clean_tool == "screen.capture":
        target_label = str(target.get("target") or "").strip()
        if app_name and target_label:
            return {"reason": f"inspect {app_name} UI target {target_label}"}
        if app_name:
            return {"reason": f"inspect {app_name} UI after failed action"}
        return {"reason": "inspect desktop UI after failed action"}
    return {}


def _annotate_replan_ui_observed_action_requests(
    requests: list[dict[str, Any]],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    request_id = str(payload.get("request_id") or "").strip()
    trigger = str(payload.get("trigger") or "tool_failure").strip() or "tool_failure"
    for request in requests:
        item = dict(request)
        if request_id:
            item["replan_request_id"] = request_id
        item["replan_trigger"] = trigger
        _attach_replan_payload_trace_metadata(item, payload)
        annotated.append(item)
    return annotated


def _auto_replan_ui_continuation_requests(
    replan_payloads: list[dict[str, Any]],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
    planning_reason: str,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not planned:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "tool_failure":
            continue
        if not _replan_ui_observed_action_target(payload):
            continue
        if not _replan_ui_observed_action_retry_succeeded(payload, timeline):
            continue
        source_index = _replan_source_request_index(planned, payload)
        if source_index < 0:
            continue
        continuation = _replan_ui_continuation_slice(
            planned[source_index + 1 :],
            payload,
            allowed,
            timeline,
            planning_reason=planning_reason,
        )
        continuation = _drop_completed_auto_followup_prefix(
            continuation,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        requests.extend(continuation)
    requests = _dedupe_replan_recovery_requests(requests)
    return _replan_recovery_requests_with_task_context(
        requests,
        replan_payloads,
        timeline,
    )


def _auto_replan_verification_continuation_requests(
    replan_payloads: list[dict[str, Any]],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
    planning_reason: str,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not planned:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "verification_failed":
            continue
        if not _replan_payload_is_focus_mismatch(payload):
            continue
        if not _replan_focus_recovery_succeeded(payload, timeline):
            continue
        source_index = _replan_source_request_index(planned, payload)
        if source_index < 0:
            continue
        continuation = _replan_ui_continuation_slice(
            planned[source_index + 1 :],
            payload,
            allowed,
            timeline,
            planning_reason=planning_reason,
        )
        continuation = _drop_completed_auto_followup_prefix(
            continuation,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        requests.extend(continuation)
    requests = _dedupe_replan_recovery_requests(requests)
    return _replan_recovery_requests_with_task_context(
        requests,
        replan_payloads,
        timeline,
    )


def _replan_focus_recovery_succeeded(
    payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> bool:
    target_app_name = _replan_focus_recovery_app_name(payload)
    if not target_app_name:
        return False
    request_id = str(payload.get("request_id") or "").strip()
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        if str(event.get("detail") or "").strip() != "desktop.active_window":
            continue
        event_request_id = str(event.get("replan_request_id") or "").strip()
        planning_reason = str(event.get("planning_reason") or "").strip()
        if request_id:
            if event_request_id != request_id:
                continue
        elif planning_reason != "planner_replan_focus_recovery":
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True or result.get("approval_required"):
            continue
        active_app_name = _replan_active_window_app_name(event, result)
        if _replan_app_names_match(target_app_name, active_app_name):
            return True
    return False


def _replan_active_window_app_name(
    event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    for key in (
        "app_name",
        "active_app_name",
        "frontmost_app",
        "frontmost_app_name",
        "observed_app_name",
    ):
        value = str(data.get(key) or result.get(key) or event.get(key) or "").strip()
        if value:
            return value
    return ""


def _replan_app_names_match(expected: str, observed: str) -> bool:
    expected_compact = compact_app_name_hint(expected)
    observed_compact = compact_app_name_hint(observed)
    if not expected_compact or not observed_compact:
        return False
    return (
        expected_compact == observed_compact
        or expected_compact in observed_compact
        or observed_compact in expected_compact
    )


def _replan_ui_observed_action_retry_succeeded(
    payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> bool:
    source_tool = _replan_source_tool_name(payload)
    if not source_tool:
        return False
    target = _replan_ui_observed_action_target(payload)
    target_action = str(target.get("target_action") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    for event in reversed(timeline):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True:
            continue
        tool_name = str(event.get("detail") or "").strip()
        event_request_id = str(event.get("replan_request_id") or "").strip()
        planning_reason = str(event.get("planning_reason") or "").strip()
        if (
            (tool_name == source_tool or _followup_plan_tools_match(tool_name, source_tool))
            and (
            (request_id and event_request_id == request_id)
            or planning_reason == "planner_replan_ui_observed_action"
            )
        ):
            return True
        if not (request_id and event_request_id == request_id):
            continue
        if not _replan_ui_observed_action_fallback_succeeded(
            source_tool,
            tool_name,
            target_action,
            event,
        ):
            continue
        return True
    return False


def _replan_ui_observed_action_fallback_succeeded(
    source_tool: str,
    tool_name: str,
    target_action: str,
    event: Mapping[str, Any],
) -> bool:
    if target_action == "click":
        if source_tool not in {
            "app.open_and_click_ui_element",
            "app.focus_and_click_ui_element",
            "desktop.click_ui_element",
        }:
            return False
        if tool_name not in {"desktop.safe_click", "desktop.click"}:
            return False
    elif target_action == "type_text":
        if source_tool not in {
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        }:
            return False
        if tool_name not in {"desktop.safe_type_text", "desktop.type_text", "desktop.type"}:
            return False
    else:
        return False
    action_target = (
        event.get("action_target") if isinstance(event.get("action_target"), Mapping) else {}
    )
    return str(action_target.get("action") or "").strip() == target_action


def _replan_ui_continuation_slice(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any],
    allowed: set[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    requests: list[dict[str, Any]] = []
    for index, request in enumerate(planned):
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        if tool_name not in allowed:
            break
        if tool_name not in _DIRECT_DAILY_DESKTOP_TOOLS:
            break
        item = dict(request)
        item.pop("continue_to_model", None)
        item["source"] = str(item.get("source") or "runtime_planner")
        item["planning_reason"] = planning_reason
        trigger = str(payload.get("trigger") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if trigger:
            item["replan_trigger"] = trigger
        if request_id:
            item["replan_request_id"] = request_id
        _attach_replan_payload_trace_metadata(item, payload)
        item = _replan_continuation_request_with_resolved_app(
            item,
            payload,
            timeline,
        )
        _attach_replan_active_window_verification_target(
            item,
            _replan_recovery_target(payload),
        )
        requests.append(item)
        if tool_name == "desktop.search_submit" and _replan_ui_next_result_click_request(
            planned[index + 1 :]
        ):
            observation = _replan_ui_search_result_observation_request(
                _replan_ui_next_result_click_request(planned[index + 1 :]),
                payload,
                allowed,
                planning_reason=planning_reason,
            )
            if observation:
                requests.append(observation)
            break
        if len(requests) >= _MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS:
            break
    return requests


def _replan_continuation_request_with_resolved_app(
    request: dict[str, Any],
    payload: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or "").strip()
    request_input = (
        dict(request.get("input"))
        if isinstance(request.get("input"), Mapping)
        else {}
    )
    raw_app_name = str(
        request_input.get("app_name") or request.get("target_app_name") or ""
    ).strip()
    if raw_app_name and not _runtime_planner_placeholder_app_name(raw_app_name):
        return request

    recovery_target = _replan_recovery_target(payload)
    app_query = str(
        request_input.get("query")
        or request_input.get("app_query")
        or request.get("target_app_query")
        or recovery_target.get("target_app_query")
        or ""
    ).strip()
    discovered = _discovered_app_name_for_query(timeline, app_query) if app_query else ""
    if not discovered:
        discovered = _latest_replan_context_app_name(
            timeline,
            request_id=str(payload.get("request_id") or "").strip(),
        )
    if not discovered or _runtime_planner_placeholder_app_name(discovered):
        return request

    resolved = dict(request)
    if tool_name.startswith("app.") or raw_app_name:
        request_input["app_name"] = discovered
    for key in ("selection_source", "app_selection_source", "query", "app_query"):
        request_input.pop(key, None)
    resolved["input"] = request_input
    resolved["target_app_name"] = discovered
    if app_query:
        resolved["target_app_query"] = app_query
    for key in ("followup_target", "action_target"):
        nested = resolved.get(key) if isinstance(resolved.get(key), Mapping) else {}
        if not nested:
            continue
        item = dict(nested)
        nested_app_name = str(item.get("app_name") or item.get("target_app_name") or "").strip()
        if not nested_app_name or _runtime_planner_placeholder_app_name(nested_app_name):
            item["app_name"] = discovered
            if "target_app_name" in item:
                item["target_app_name"] = discovered
        if app_query:
            if key == "followup_target" or "app_query" in item:
                item["app_query"] = app_query
            if "target_app_query" in item:
                item["target_app_query"] = app_query
        resolved[key] = item
    if app_query and (tool_name.startswith("app.") or raw_app_name):
        resolved = _with_discovered_app_resolution(resolved, app_query, discovered)
    return resolved


def _auto_replan_ui_search_observed_result_requests(
    replan_payloads: list[dict[str, Any]],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    planning_reason: str,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if (
        not allowed
        or not _latest_desktop_observation_succeeded(timeline)
        or not _latest_desktop_observation_follows_search_submission(timeline)
    ):
        return []
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not planned:
        return []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if str(payload.get("trigger") or "").strip() != "tool_failure":
            continue
        if not _replan_ui_observed_action_target(payload):
            continue
        if not _replan_ui_observed_action_retry_succeeded(payload, timeline):
            continue
        source_index = _replan_source_request_index(planned, payload)
        if source_index < 0:
            continue
        result_request = _replan_ui_next_result_click_request(planned[source_index + 1 :])
        if not result_request:
            continue
        observed_target = _observed_action_target_from_replan_ui_result_request(
            result_request,
            payload,
        )
        if not observed_target:
            continue
        observed_target = _replan_ui_observed_action_target_with_timeline_context(
            observed_target,
            payload,
            timeline,
        )
        observation_source = _latest_desktop_observation_tool(timeline)
        if observation_source:
            observed_target["observation_source"] = observation_source
        requests = _auto_desktop_observed_action_followup_requests(
            {"followup_target": observed_target},
            allowed,
            timeline,
            planning_reason=planning_reason,
        )
        if not requests:
            continue
        requests = _annotate_replan_ui_search_observed_result_requests(
            requests,
            payload,
            result_request,
        )
        return _replan_recovery_requests_with_task_context(
            requests,
            [dict(payload)],
            timeline,
        )
    return []


def _replan_ui_next_result_click_request(
    planned_tool_requests: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    for request in planned_tool_requests:
        if not isinstance(request, Mapping):
            continue
        deferred_click = _replan_ui_deferred_result_click_request(request)
        if deferred_click:
            return deferred_click
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in {
            "app.open_and_click_ui_element",
            "app.focus_and_click_ui_element",
            "desktop.click_ui_element",
        }:
            if tool_name in _DIRECT_DAILY_DESKTOP_TOOLS:
                continue
            return {}
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        target = str(payload.get("target") or "").strip()
        if not target:
            return {}
        if _observed_desktop_target_ordinal(target) or "result" in target.casefold():
            return dict(request)
        return {}
    return {}


def _replan_ui_deferred_result_click_request(request: Mapping[str, Any]) -> dict[str, Any]:
    tool_name = str(request.get("deferred_tool") or "").strip()
    if tool_name not in {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "desktop.click_ui_element",
    }:
        return {}
    payload = (
        request.get("deferred_input")
        if isinstance(request.get("deferred_input"), Mapping)
        else {}
    )
    target = str(payload.get("target") or "").strip()
    if not target:
        return {}
    if not (_observed_desktop_target_ordinal(target) or "result" in target.casefold()):
        return {}
    item = {
        key: value
        for key, value in request.items()
        if key
        not in {
            "tool",
            "input",
            "deferred_tool",
            "deferred_input",
            "deferred_context",
            "continue_to_model",
        }
    }
    item["tool"] = tool_name
    item["input"] = dict(payload)
    deferred_context = (
        request.get("deferred_context")
        if isinstance(request.get("deferred_context"), Mapping)
        else {}
    )
    for key, value in deferred_context.items():
        if value not in (None, "", [], {}):
            item[key] = value
    return item


def _replan_ui_search_result_observation_request(
    result_request: Mapping[str, Any],
    payload: Mapping[str, Any],
    allowed: set[str],
    *,
    planning_reason: str,
) -> dict[str, Any]:
    if not result_request:
        return {}
    result_input = (
        result_request.get("input")
        if isinstance(result_request.get("input"), Mapping)
        else {}
    )
    app_name = str(result_input.get("app_name") or "").strip()
    if not app_name:
        app_name = str(_replan_recovery_target(payload).get("target_app_name") or "").strip()
    role_filter = str(result_input.get("role_filter") or "").strip()
    limit = _clean_model_followup_int(result_input.get("limit"), default=80)
    tool_name = _first_allowed_tool(
        ("desktop.ui_elements", "desktop.read_ui", "desktop.inspect_app", "screen.capture"),
        allowed,
    )
    if not tool_name:
        return {}
    if tool_name == "desktop.inspect_app":
        request_input: dict[str, Any] = {
            "app_name": app_name,
            "open_if_needed": False,
            "focus": True,
            "limit": limit,
        }
        if role_filter:
            request_input["role_filter"] = role_filter
    elif tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
        request_input = {"limit": limit}
        if app_name:
            request_input["app_name"] = app_name
        if role_filter:
            request_input["role_filter"] = role_filter
    else:
        request_input = {"reason": "inspect search results after submit"}
    request = _request_like(
        tool_name,
        request_input,
        source="runtime_planner",
        planning_reason=planning_reason,
    )
    request_id = str(payload.get("request_id") or "").strip()
    if request_id:
        request["replan_request_id"] = request_id
    trigger = str(payload.get("trigger") or "").strip()
    if trigger:
        request["replan_trigger"] = trigger
    return request


def _observed_action_target_from_replan_ui_result_request(
    result_request: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result_input = (
        result_request.get("input")
        if isinstance(result_request.get("input"), Mapping)
        else {}
    )
    target_label = str(result_input.get("target") or "first result").strip()
    if not target_label:
        return {}
    app_name = str(result_input.get("app_name") or "").strip()
    if not app_name:
        app_name = str(_replan_recovery_target(payload).get("target_app_name") or "").strip()
    observed_target = {
        "kind": "desktop_observed_action",
        "target_action": "click",
        "target": target_label,
        "role_filter": str(result_input.get("role_filter") or "").strip(),
        "click_count": _clean_model_followup_int(
            result_input.get("click_count"),
            default=1,
        ),
        "limit": _clean_model_followup_int(result_input.get("limit"), default=80),
    }
    if app_name:
        observed_target["app_name"] = app_name
        observed_target["target_app_name"] = app_name
    app_query = str(result_input.get("query") or result_input.get("app_query") or "").strip()
    if app_query:
        observed_target["app_query"] = app_query
        observed_target["target_app_query"] = app_query
    return {
        key: value
        for key, value in observed_target.items()
        if value not in ("", None, [], {})
    }


def _annotate_replan_ui_search_observed_result_requests(
    requests: list[dict[str, Any]],
    payload: Mapping[str, Any],
    result_request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for request in requests:
        item = dict(request)
        for key in (
            "decision_id",
            "plan_id",
            "tool_plan_id",
            "intent_kind",
            "step_id",
            "planner_step_id",
            "capability_id",
            "core_id",
            "workspace_id",
            "task_id",
            "task_todo",
            "task_checkpoints",
            "task_workspace_items",
        ):
            value = result_request.get(key)
            if value not in (None, "", [], {}):
                item[key] = value
        _attach_replan_payload_trace_metadata(item, payload)
        annotated.append(item)
    return annotated


def _auto_replan_focus_recovery_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    focus_tool = _replan_focus_recovery_tool(allowed)
    if not focus_tool:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if not _replan_payload_is_focus_mismatch(payload):
            continue
        app_name = _replan_focus_recovery_app_name(payload)
        if not app_name:
            continue
        request_id = str(payload.get("request_id") or "").strip()
        target = {
            **_replan_recovery_target(payload),
            "target_app_name": app_name,
        }
        for tool_name, request_input in (
            (focus_tool, {"app_name": app_name}),
            ("desktop.active_window", {}),
        ):
            if tool_name not in allowed:
                continue
            request = _request_like(
                tool_name,
                request_input,
                source="runtime_planner",
                planning_reason="planner_replan_focus_recovery",
            )
            if request_id:
                request["replan_request_id"] = request_id
            request["replan_trigger"] = "verification_failed"
            for key, value in target.items():
                if value:
                    request[key] = value
            _attach_replan_payload_trace_metadata(request, payload)
            _attach_replan_active_window_verification_target(request, target)
            requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _replan_focus_recovery_tool(allowed: set[str]) -> str:
    for tool_name in (
        "app.focus",
        "desktop.focus_app",
        "app.open",
        "desktop.open_app",
    ):
        if tool_name in allowed:
            return tool_name
    return ""


def _replan_payload_is_focus_mismatch(payload: Mapping[str, Any]) -> bool:
    if str(payload.get("trigger") or "").strip() != "verification_failed":
        return False
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    tokens = [
        str(payload.get("failure_detail") or ""),
        str(payload.get("condition") or ""),
        str(payload.get("reason") or ""),
        *_string_list(payload.get("blocking_conditions")),
        *_string_list(metadata.get("blocking_conditions")),
    ]
    return any("foreground_focus_unverified" in token for token in tokens)


def _replan_focus_recovery_app_name(payload: Mapping[str, Any]) -> str:
    target = _replan_recovery_target(payload)
    app_name = str(target.get("target_app_name") or "").strip()
    if app_name and not _runtime_planner_placeholder_app_name(app_name):
        return app_name
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    app_name = _first_replan_recovery_text(
        (
            "expected_app_name",
            "target_app_name",
            "resolved_app_name",
            "discovered_app_name",
            "requested_app_name",
            "app_name",
        ),
        metadata,
        data,
        result,
        payload,
    )
    if app_name and not _runtime_planner_placeholder_app_name(app_name):
        return app_name
    return ""


def _replan_recovery_target(payload: Mapping[str, Any]) -> dict[str, str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    input_preview = (
        payload.get("input_preview")
        if isinstance(payload.get("input_preview"), Mapping)
        else {}
    )
    app_name = _first_replan_recovery_text(
        (
            "target_app_name",
            "app_name",
            "expected_app_name",
            "resolved_app_name",
            "discovered_app_name",
            "requested_app_name",
        ),
        metadata,
        input_preview,
        payload,
    )
    app_query = _first_replan_recovery_text(
        ("target_app_query", "app_query", "query"),
        metadata,
        input_preview,
        payload,
    )
    search_text = _first_replan_recovery_text(
        ("target_search_text", "search_text", "text", "value"),
        metadata,
        input_preview,
        payload,
    )
    role_filter = _first_replan_recovery_text(
        ("ui_role_filter", "role_filter", "role"),
        metadata,
        input_preview,
        payload,
    )
    return {
        key: value
        for key, value in {
            "target_app_name": app_name,
            "target_app_query": app_query,
            "target_search_text": search_text,
            "ui_role_filter": role_filter,
        }.items()
        if value
    }


def _verification_recovery_tool_input(
    tool_name: str,
    target: Mapping[str, str],
) -> dict[str, Any] | None:
    clean_tool = str(tool_name or "").strip()
    app_name = str(target.get("target_app_name") or "").strip()
    search_text = str(target.get("target_search_text") or "").strip()
    role_filter = str(target.get("ui_role_filter") or "").strip()
    if clean_tool == "desktop.inspect_app":
        if not app_name:
            return None
        payload: dict[str, Any] = {
            "app_name": app_name,
            "open_if_needed": True,
            "focus": True,
            "limit": 80,
        }
        if role_filter:
            payload["role_filter"] = role_filter
        return payload
    if clean_tool in {"desktop.list_windows", "desktop.windows"}:
        return {"app_name": app_name} if app_name else {}
    if clean_tool in {"desktop.read_ui", "desktop.ui_elements"}:
        payload = {"app_name": app_name, "limit": 80} if app_name else {"limit": 80}
        if role_filter:
            payload["role_filter"] = role_filter
        return payload
    if clean_tool == "screen.capture":
        reason = "runtime verification recovery"
        if app_name and search_text:
            reason = f"verify {app_name} after action involving {search_text}"
        elif app_name:
            reason = f"verify {app_name} after desktop action"
        elif search_text:
            reason = f"verify desktop after action involving {search_text}"
        return {"reason": reason}
    return {}


def _attach_replan_active_window_verification_target(
    request: dict[str, Any],
    target: Mapping[str, Any],
) -> None:
    if str(request.get("tool") or "").strip() != "desktop.active_window":
        return
    if isinstance(request.get("verification_target"), Mapping):
        return
    app_name = str(
        target.get("target_app_name")
        or target.get("app_name")
        or request.get("target_app_name")
        or ""
    ).strip()
    if not app_name:
        return
    request["verification_target"] = {"app_name": app_name}


def _first_replan_recovery_text(
    keys: tuple[str, ...],
    *sources: Mapping[str, Any],
) -> str:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _attach_replan_payload_trace_metadata(
    request: dict[str, Any],
    payload: Mapping[str, Any],
) -> None:
    for key in (
        "decision_id",
        "plan_id",
        "core_id",
        "workspace_id",
        "task_id",
        "run_id",
        "run_group_id",
        "group_run_id",
        "group_id",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        value = str(request.get(key) or payload.get(key) or "").strip()
        if value:
            request[key] = value
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    intent_kind = str(
        request.get("intent_kind")
        or payload.get("intent_kind")
        or metadata.get("original_intent_kind")
        or ""
    ).strip()
    if intent_kind:
        request["intent_kind"] = intent_kind
    request_id = str(payload.get("request_id") or "").strip()
    if request_id and not str(request.get("replan_request_id") or "").strip():
        request["replan_request_id"] = request_id
    trigger = str(payload.get("trigger") or "").strip()
    if trigger and not str(request.get("replan_trigger") or "").strip():
        request["replan_trigger"] = trigger
    step_id = str(
        request.get("step_id")
        or payload.get("source_step_id")
        or payload.get("planner_step_id")
        or ""
    ).strip()
    if step_id:
        request["step_id"] = step_id
        request.setdefault("planner_step_id", step_id)
    capability_id = str(
        request.get("capability_id")
        or payload.get("target_capability_id")
        or payload.get("capability_id")
        or ""
    ).strip()
    if capability_id:
        request["capability_id"] = capability_id
    request.update(_runtime_trace_metadata_from_replan_payload(payload))
    _attach_replan_payload_recovery_metadata(request, payload)


def _attach_replan_payload_recovery_metadata(
    request: dict[str, Any],
    payload: Mapping[str, Any],
) -> None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    for key in ("action_target", "observation_evidence", "observation_retry"):
        if isinstance(request.get(key), Mapping) and request.get(key):
            continue
        value = payload.get(key)
        if not isinstance(value, Mapping):
            value = metadata.get(key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    if _mapping_list(request.get("verification_targets")):
        return
    verification_targets = _mapping_list(payload.get("verification_targets"))
    if not verification_targets:
        verification_targets = _mapping_list(metadata.get("verification_targets"))
    if verification_targets:
        request["verification_targets"] = [
            dict(target) for target in verification_targets
        ]


_RUNTIME_TRACE_TEXT_KEYS = (
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
)

_RUNTIME_TRACE_BOOL_KEYS = (
    "requires_observation",
    "requires_post_action_verification",
)

_RUNTIME_TRACE_LIST_KEYS = (
    "replan_triggers",
    "replan_signal_ids",
)


def _runtime_trace_metadata_from_replan_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    trace = {
        **_runtime_trace_metadata_from_mapping(metadata),
        **_runtime_trace_metadata_from_mapping(payload),
    }
    trigger = str(payload.get("trigger") or "").strip()
    if trigger:
        triggers = _string_list(trace.get("replan_triggers"))
        if trigger not in triggers:
            triggers.append(trigger)
        trace["replan_triggers"] = triggers
    return trace


def _runtime_trace_metadata_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    for key in _RUNTIME_TRACE_TEXT_KEYS:
        item = str(value.get(key) or "").strip()
        if item:
            trace[key] = item
    for key in _RUNTIME_TRACE_BOOL_KEYS:
        item = value.get(key)
        if isinstance(item, bool):
            trace[key] = item
    for key in _RUNTIME_TRACE_LIST_KEYS:
        items = _string_list(value.get(key))
        if items:
            trace[key] = items
    return trace


def _replan_recovery_requests_need_model_followup(
    requests: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        bool(request.get("continue_to_model"))
        for request in requests
        if isinstance(request, Mapping)
    )


def _auto_direct_permission_recovery_requests(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    planned_signatures = _tool_request_signatures(planned_tool_requests)
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in timeline[max(0, int(tool_timeline_start or 0)):]:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() not in {"agent.tool.call", "agent.tool.skipped"}:
            continue
        source_tool = str(event.get("detail") or event.get("tool") or "").strip()
        if not source_tool:
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if not result or result.get("approval_required"):
            continue
        input_preview = (
            event.get("input_preview") if isinstance(event.get("input_preview"), Mapping) else {}
        )
        enriched_result = _with_retry_recovery_action(
            source_tool,
            dict(input_preview),
            dict(result),
        )
        if not _has_permission_recovery_signal(enriched_result):
            continue
        for action in _recovery_actions(enriched_result):
            tool_name = str(action.get("tool") or "").strip()
            if not tool_name or tool_name not in allowed:
                continue
            risk_level = str(action.get("risk_level") or "low").strip().lower()
            if risk_level and risk_level != "low":
                continue
            action_input = (
                dict(action.get("input"))
                if isinstance(action.get("input"), Mapping)
                else {}
            )
            signature = _tool_request_signature(tool_name, action_input)
            if signature in planned_signatures or signature in seen:
                continue
            seen.add(signature)
            request = _request_like(
                tool_name,
                action_input,
                source="runtime_planner",
                planning_reason="planner_direct_permission_recovery_action",
            )
            request["continue_to_model"] = True
            request["permission_recovery"] = True
            request["recovery_source_tool"] = source_tool
            request["recovery_source_event_type"] = str(event.get("event") or "").strip()
            label = str(action.get("label") or "").strip()
            if label:
                request["recovery_action_label"] = label
            permission_target = str(action.get("permission_target") or "").strip()
            if permission_target:
                request["permission_target"] = permission_target
            if risk_level:
                request["risk_level"] = risk_level
            for key in (
                "action_kind",
                "recovery_action_kind",
                "retry_tool",
                "recovery_retry_tool",
                "retry_prompt",
                "recovery_retry_prompt",
            ):
                value = str(action.get(key) or "").strip()
                if value:
                    request[key] = value
            for key in (
                "retry_input",
                "recovery_retry_input",
                "action_target",
                "observation_evidence",
                "observation_retry",
            ):
                value = action.get(key)
                if isinstance(value, Mapping) and value:
                    request[key] = dict(value)
            verification_targets = _mapping_list(action.get("verification_targets"))
            if verification_targets:
                request["verification_targets"] = [
                    dict(target) for target in verification_targets
                ]
            requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _auto_direct_permission_retry_requests(
    recovery_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for recovery_request in recovery_requests:
        if not isinstance(recovery_request, Mapping):
            continue
        recovery_tool = str(recovery_request.get("tool") or "").strip()
        if not _direct_permission_recovery_tool_supports_retry(recovery_tool):
            continue
        if not _auto_followup_request_completed(
            recovery_request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        ):
            continue
        retry_tool = str(
            recovery_request.get("recovery_retry_tool")
            or recovery_request.get("retry_tool")
            or ""
        ).strip()
        if (
            not retry_tool
            or retry_tool not in allowed
            or retry_tool not in _DIRECT_DAILY_DESKTOP_TOOLS
        ):
            continue
        retry_input = (
            recovery_request.get("recovery_retry_input")
            if isinstance(recovery_request.get("recovery_retry_input"), Mapping)
            else recovery_request.get("retry_input")
            if isinstance(recovery_request.get("retry_input"), Mapping)
            else {}
        )
        signature = _tool_request_signature(retry_tool, retry_input)
        if signature in seen:
            continue
        seen.add(signature)
        retry_request = _request_like(
            retry_tool,
            dict(retry_input),
            source="runtime_planner",
            planning_reason="planner_direct_permission_recovery_retry",
        )
        retry_request["permission_recovery_retry"] = True
        retry_request["recovery_source_tool"] = str(
            recovery_request.get("recovery_source_tool") or ""
        ).strip()
        retry_request["recovery_action_tool"] = recovery_tool
        label = str(recovery_request.get("recovery_action_label") or "").strip()
        if label:
            retry_request["recovery_action_label"] = label
        permission_target = str(recovery_request.get("permission_target") or "").strip()
        if permission_target:
            retry_request["permission_target"] = permission_target
        risk_level = str(recovery_request.get("risk_level") or "").strip()
        if risk_level:
            retry_request["risk_level"] = risk_level
        retry_prompt = str(
            recovery_request.get("recovery_retry_prompt")
            or recovery_request.get("retry_prompt")
            or ""
        ).strip()
        if retry_prompt:
            retry_request["recovery_retry_prompt"] = retry_prompt
        requests.append(retry_request)
    return _dedupe_replan_recovery_requests(requests)


def _direct_permission_recovery_tool_supports_retry(tool_name: str) -> bool:
    return str(tool_name or "").strip() in {
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
    }


def _auto_direct_permission_retry_completed(
    retry_requests: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    requests = [request for request in retry_requests if isinstance(request, Mapping)]
    return bool(requests) and all(
        _auto_followup_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        )
        for request in requests
    )


def _tool_request_signatures(
    requests: Iterable[Mapping[str, Any]],
) -> set[tuple[str, str]]:
    return {
        _tool_request_signature(
            str(request.get("tool") or "").strip(),
            request.get("input") if isinstance(request.get("input"), Mapping) else {},
        )
        for request in requests
        if isinstance(request, Mapping) and str(request.get("tool") or "").strip()
    }


def _tool_request_signature(
    tool_name: str,
    request_input: Mapping[str, Any],
) -> tuple[str, str]:
    return (
        str(tool_name or "").strip(),
        repr(sorted(dict(request_input).items())),
    )


def _auto_replan_recovery_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    return _dedupe_replan_recovery_requests(
        [
            *_auto_replan_focus_recovery_requests(
                replan_payloads,
                allowed_tools,
            ),
            *_auto_replan_verification_recovery_requests(
                replan_payloads,
                allowed_tools,
            ),
            *_auto_replan_ui_observation_recovery_requests(
                replan_payloads,
                allowed_tools,
            ),
            *_auto_replan_fallback_recovery_requests(
                replan_payloads,
                allowed_tools,
            ),
            *_auto_replan_runtime_recovery_action_requests(
                replan_payloads,
                allowed_tools,
            ),
        ]
    )


def _auto_replan_recovery_requests_with_task_context(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests = _auto_replan_recovery_requests(replan_payloads, allowed_tools)
    return _replan_recovery_requests_with_task_context(
        requests,
        replan_payloads,
        timeline,
    )


def _replan_recovery_requests_with_task_context(
    requests: list[dict[str, Any]],
    replan_payloads: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requests:
        return []
    task_core = _runtime_replan_task_core_payload(replan_payloads, timeline)
    if not task_core:
        return requests
    return [
        _replan_recovery_request_with_task_context(request, task_core)
        for request in requests
    ]


def _auto_replan_discovered_app_continuation_requests(
    replan_payloads: list[dict[str, Any]],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planned = [request for request in planned_tool_requests if isinstance(request, Mapping)]
    if not planned:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        if not _replan_payload_is_app_resolution_failure(payload):
            continue
        source_index = _replan_source_request_index(planned, payload)
        if source_index < 0:
            continue
        source_request = planned[source_index]
        app_query = _replan_discovered_app_query(source_request, payload)
        if not app_query or not _discovered_app_name_for_query(timeline, app_query):
            continue
        requests.extend(
            _replan_discovered_app_continuation_slice(
                planned[source_index:],
                payload,
                allowed,
            )
        )
    requests = _dedupe_replan_recovery_requests(requests)
    return _replan_recovery_requests_with_task_context(
        requests,
        replan_payloads,
        timeline,
    )


def _replan_payload_is_app_resolution_failure(payload: Mapping[str, Any]) -> bool:
    source_tool = str(payload.get("source_tool_name") or payload.get("tool") or "").strip()
    if source_tool not in _DISCOVERED_APP_DIRECT_COMPLETION_TOOLS:
        return False
    failure_detail = str(payload.get("failure_detail") or "").strip()
    if "app_resolution_failed" in failure_detail:
        return True
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    for action in _mapping_list(metadata.get("recovery_actions")):
        if str(action.get("tool") or "").strip() == "desktop.list_apps":
            return True
    return False


def _replan_source_request_index(
    planned_tool_requests: list[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> int:
    source_step_id = str(
        payload.get("source_step_id") or payload.get("planner_step_id") or ""
    ).strip()
    source_tool = str(payload.get("source_tool_name") or payload.get("tool") or "").strip()
    for index, request in enumerate(planned_tool_requests):
        tool_name = str(request.get("tool") or "").strip()
        step_id = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
        if source_step_id and step_id == source_step_id:
            if not source_tool or tool_name == source_tool:
                return index
        if not source_step_id and source_tool and tool_name == source_tool:
            if _request_uses_discovered_app_resolution(request):
                return index
    return -1


def _replan_discovered_app_query(
    source_request: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    request_input = (
        source_request.get("input") if isinstance(source_request.get("input"), Mapping) else {}
    )
    query = str(request_input.get("query") or "").strip()
    if query:
        return query
    app_name = str(request_input.get("app_name") or "").strip()
    if app_name and app_name != "<selected app from desktop.list_apps>":
        return app_name
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    for action in _mapping_list(metadata.get("recovery_actions")):
        action_input = action.get("input") if isinstance(action.get("input"), Mapping) else {}
        query = str(action_input.get("query") or "").strip()
        if query:
            return query
    return str(payload.get("target_app_query") or payload.get("target_app_name") or "").strip()


def _replan_discovered_app_continuation_slice(
    planned_tool_requests: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any],
    allowed: set[str],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for request in planned_tool_requests:
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            break
        if tool_name == "desktop.list_apps":
            continue
        if tool_name not in _DIRECT_DAILY_DESKTOP_TOOLS:
            break
        item = dict(request)
        item.pop("continue_to_model", None)
        item["source"] = str(item.get("source") or "runtime_planner")
        item["planning_reason"] = "planner_replan_discovered_app_continuation"
        trigger = str(payload.get("trigger") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        if trigger:
            item["replan_trigger"] = trigger
        if request_id:
            item["replan_request_id"] = request_id
        _attach_replan_payload_trace_metadata(item, payload)
        requests.append(item)
        if len(requests) >= _MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS:
            break
    return requests


def _replan_recovery_request_with_task_context(
    request: dict[str, Any],
    task_core: Mapping[str, Any],
) -> dict[str, Any]:
    step_id = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
    if not step_id:
        return request
    enriched = dict(request)
    core_id = str(task_core.get("core_id") or "").strip()
    if core_id:
        enriched.setdefault("core_id", core_id)
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    workspace_id = str(workspace.get("workspace_id") or "").strip()
    if workspace_id:
        enriched.setdefault("workspace_id", workspace_id)
    todo = _task_core_todo_for_step(task_core, step_id)
    if todo and "task_todo" not in enriched:
        enriched["task_todo"] = todo
    checkpoints = _task_core_checkpoints_for_step(task_core, step_id)
    if checkpoints and "task_checkpoints" not in enriched:
        enriched["task_checkpoints"] = checkpoints
    workspace_items = _task_core_workspace_items_for_step(task_core, step_id)
    if workspace_items and "task_workspace_items" not in enriched:
        enriched["task_workspace_items"] = workspace_items
    return enriched


def _task_core_todo_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> dict[str, Any]:
    for todo in _mapping_list(task_core.get("todos")):
        if str(todo.get("step_id") or "").strip() == step_id:
            return dict(todo)
    return {}


def _task_core_checkpoints_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(checkpoint)
        for checkpoint in _mapping_list(task_core.get("checkpoints"))
        if str(checkpoint.get("after_step_id") or "").strip() == step_id
    ]


def _task_core_workspace_items_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    return [
        dict(item)
        for item in _mapping_list(workspace.get("items"))
        if str(item.get("source_step_id") or "").strip() == step_id
    ]


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _auto_replan_fallback_recovery_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        trigger = str(payload.get("trigger") or "").strip()
        if trigger not in {"tool_failure", "tool_unavailable"}:
            continue
        request_id = str(payload.get("request_id") or "").strip()
        step_id = str(payload.get("source_step_id") or payload.get("planner_step_id") or "").strip()
        capability_id = str(payload.get("target_capability_id") or payload.get("capability_id") or "").strip()
        for tool_name in _string_list(payload.get("fallback_tools")):
            if tool_name not in allowed:
                continue
            request_input = _replan_fallback_tool_input(tool_name, payload)
            if request_input is None:
                continue
            request = _request_like(
                tool_name,
                request_input,
                source="runtime_planner",
                planning_reason="planner_replan_fallback_recovery",
            )
            if request_id:
                request["replan_request_id"] = request_id
            request["replan_trigger"] = trigger
            if step_id:
                request["step_id"] = step_id
            if capability_id:
                request["capability_id"] = capability_id
            if _replan_fallback_request_needs_model_followup(tool_name, payload):
                request["continue_to_model"] = True
            _attach_replan_payload_trace_metadata(request, payload)
            requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _auto_replan_runtime_recovery_action_requests(
    replan_payloads: list[dict[str, Any]],
    allowed_tools: Iterable[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    requests: list[dict[str, Any]] = []
    for payload in replan_payloads:
        if not isinstance(payload, Mapping):
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        trigger = str(payload.get("trigger") or "").strip()
        if trigger not in {"tool_failure", "tool_unavailable", "verification_failed"}:
            continue
        request_id = str(payload.get("request_id") or "").strip()
        step_id = str(payload.get("source_step_id") or payload.get("planner_step_id") or "").strip()
        capability_id = str(payload.get("target_capability_id") or payload.get("capability_id") or "").strip()
        for action in _mapping_list(metadata.get("recovery_actions")):
            tool_name = str(action.get("tool") or "").strip()
            if not tool_name or tool_name not in allowed:
                continue
            if _runtime_replan_action_auto_start_blocked(action):
                continue
            request_input = (
                dict(action.get("input"))
                if isinstance(action.get("input"), Mapping)
                else {}
            )
            request = _request_like(
                tool_name,
                request_input,
                source="runtime_planner",
                planning_reason=(
                    str(action.get("planning_reason") or "").strip()
                    or "planner_replan_runtime_recovery_action"
                ),
            )
            if request_id:
                request["replan_request_id"] = request_id
            if trigger:
                request["replan_trigger"] = trigger
            if step_id:
                request["step_id"] = step_id
            if capability_id:
                request["capability_id"] = capability_id
            label = str(action.get("label") or "").strip()
            if label:
                request["recovery_action_label"] = label
            request["recovery_action_tool"] = tool_name
            risk_level = str(action.get("risk_level") or "").strip()
            if risk_level:
                request["risk_level"] = risk_level
            permission_target = str(action.get("permission_target") or "").strip()
            if permission_target:
                request["permission_target"] = permission_target
            if bool(action.get("approval_required")):
                request["approval_required"] = True
            action_id = str(action.get("action_id") or action.get("id") or "").strip()
            if action_id:
                request["action_id"] = action_id
                request["replan_recovery_action_id"] = action_id
            action_metadata = (
                action.get("metadata") if isinstance(action.get("metadata"), Mapping) else {}
            )
            desktop_loop = action_metadata.get("desktop_loop")
            if not isinstance(desktop_loop, Mapping):
                desktop_loop = metadata.get("desktop_loop")
            if isinstance(desktop_loop, Mapping) and desktop_loop:
                request["desktop_loop"] = dict(desktop_loop)
            for key in ("runtime_stage", "runtime_role"):
                value = str(action_metadata.get(key) or metadata.get(key) or "").strip()
                if value:
                    request[key] = value
            for key in ("action_target", "observation_evidence", "observation_retry"):
                value = action.get(key)
                if not isinstance(value, Mapping):
                    value = metadata.get(key)
                if not isinstance(value, Mapping):
                    value = payload.get(key)
                if isinstance(value, Mapping) and value:
                    request[key] = dict(value)
            verification_targets = _mapping_list(action.get("verification_targets"))
            if not verification_targets:
                verification_targets = _mapping_list(metadata.get("verification_targets"))
            if not verification_targets:
                verification_targets = _mapping_list(payload.get("verification_targets"))
            if verification_targets:
                request["verification_targets"] = [dict(target) for target in verification_targets]
            deferred_continuation = _runtime_replan_action_deferred_continuation_requests(
                action,
                payload,
                allowed,
            )
            if deferred_continuation:
                request["deferred_continuation"] = deferred_continuation
            if _runtime_replan_action_needs_model_followup(
                action,
                deferred_continuation=deferred_continuation,
            ):
                request["continue_to_model"] = True
            _attach_replan_payload_trace_metadata(request, payload)
            requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _runtime_replan_action_auto_start_blocked(action: Mapping[str, Any]) -> bool:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), Mapping) else {}
    explicit = metadata.get("runtime_replan_auto_start_eligible")
    if isinstance(explicit, bool):
        return not explicit
    explicit = metadata.get("auto_start_eligible")
    if isinstance(explicit, bool):
        return not explicit
    blockers = metadata.get("runtime_replan_auto_start_blockers")
    if isinstance(blockers, list) and blockers:
        return True
    blockers = metadata.get("auto_start_blockers")
    if isinstance(blockers, list) and blockers:
        return True

    tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
    risk_level = str(action.get("risk_level") or "").strip().lower()
    approval_required = bool(action.get("approval_required")) or str(
        action.get("approval_status") or ""
    ).strip().lower() in {
        "pending",
        "required",
        "approval_required",
        "waiting_approval",
    }
    return bool(
        not tool_name
        or approval_required
        or risk_level in {"high", "critical"}
        or tool_name not in _RUNTIME_REPLAN_ACTION_AUTO_SAFE_TOOLS
    )


def _runtime_replan_action_needs_model_followup(
    action: Mapping[str, Any],
    *,
    deferred_continuation: list[dict[str, Any]],
) -> bool:
    metadata = action.get("metadata") if isinstance(action.get("metadata"), Mapping) else {}
    explicit = action.get("continue_to_model")
    if isinstance(explicit, bool):
        return explicit
    explicit = metadata.get("continue_to_model")
    if isinstance(explicit, bool):
        return explicit
    if deferred_continuation:
        return False
    return True


def _runtime_replan_action_deferred_continuation_requests(
    action: Mapping[str, Any],
    payload: Mapping[str, Any],
    allowed: set[str],
) -> list[dict[str, Any]]:
    continuation = _mapping_list(action.get("deferred_continuation"))
    if not continuation:
        return []
    requests: list[dict[str, Any]] = []
    request_id = str(payload.get("request_id") or "").strip()
    trigger = str(payload.get("trigger") or "").strip()
    action_id = str(action.get("action_id") or action.get("id") or "").strip()
    for item in continuation:
        request = _runtime_replan_safe_deferred_continuation_request(
            item,
            allowed,
        )
        if not request:
            continue
        if request_id:
            request.setdefault("replan_request_id", request_id)
        if trigger:
            request.setdefault("replan_trigger", trigger)
        if action_id:
            request.setdefault("action_id", action_id)
            request.setdefault("replan_recovery_action_id", action_id)
        request.setdefault("source", "runtime_planner")
        request.setdefault("planning_reason", "planner_replan_deferred_continuation")
        for key in (
            "source_step_id",
            "source_tool_name",
            "target_capability_id",
            "capability_id",
            "target_app_name",
            "target_app_query",
            "target_search_text",
        ):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                request.setdefault(key, value)
        _attach_replan_payload_trace_metadata(request, payload)
        requests.append(request)
    return _dedupe_replan_recovery_requests(requests)


def _auto_replan_recovery_deferred_continuation_requests(
    recovery_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    requests: list[dict[str, Any]] = []
    for source_request in recovery_requests:
        if not isinstance(source_request, Mapping):
            continue
        if not _runtime_replan_source_request_completed(
            source_request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        ):
            continue
        for item in _mapping_list(source_request.get("deferred_continuation")):
            request = _runtime_replan_safe_deferred_continuation_request(item, allowed)
            if not request:
                continue
            for key, value in _runtime_replan_deferred_inherited_metadata(
                source_request
            ).items():
                request.setdefault(key, value)
            request.setdefault(
                "source",
                str(source_request.get("source") or "runtime_planner").strip(),
            )
            request.setdefault(
                "planning_reason",
                "planner_replan_deferred_continuation",
            )
            requests.append(request)
    requests = _dedupe_replan_recovery_requests(requests)
    return _drop_completed_auto_followup_prefix(
        requests,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )


def _runtime_replan_source_request_completed(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    comparable = {
        key: value
        for key, value in dict(request).items()
        if key
        not in {
            "continue_to_model",
            "deferred_tool",
            "deferred_input",
            "deferred_context",
            "deferred_continuation",
        }
    }
    return _auto_followup_request_completed(
        comparable,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )


def _runtime_replan_safe_deferred_continuation_request(
    item: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    tool_name = str(item.get("tool") or item.get("tool_name") or "").strip()
    if not tool_name or tool_name not in allowed:
        return {}
    if tool_name not in _RUNTIME_REPLAN_ACTION_AUTO_SAFE_TOOLS:
        return {}
    risk_level = str(item.get("risk_level") or "").strip().lower()
    if risk_level in {"high", "critical"}:
        return {}
    if bool(item.get("approval_required")):
        return {}
    request = dict(item)
    request["tool"] = tool_name
    raw_input = item.get("input") if isinstance(item.get("input"), Mapping) else {}
    request["input"] = dict(raw_input)
    request.pop("tool_name", None)
    request.pop("continue_to_model", None)
    return request


def _runtime_replan_deferred_inherited_metadata(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in _request_observability_metadata(request).items()
        if key
        not in {
            "continue_to_model",
            "deferred_tool",
            "deferred_input",
            "deferred_context",
            "deferred_continuation",
        }
    }
    for key in (
        "action_id",
        "replan_recovery_action_id",
        "source_step_id",
        "source_tool_name",
        "target_capability_id",
        "task_todo",
        "task_checkpoints",
        "task_workspace_items",
        "task_verification_targets",
        "verification_targets",
    ):
        value = request.get(key)
        if value not in (None, "", [], {}):
            metadata[key] = value
    return metadata


def _replan_fallback_request_needs_model_followup(
    tool_name: str,
    payload: Mapping[str, Any],
) -> bool:
    clean_tool = str(tool_name or "").strip()
    if clean_tool in {"terminal.run", "python.run"} and _replan_payload_is_data_analysis_fallback(payload):
        return False
    return True


def _replan_payload_is_data_analysis_fallback(payload: Mapping[str, Any]) -> bool:
    capability_id = str(
        payload.get("target_capability_id") or payload.get("capability_id") or ""
    ).strip()
    source_tool = str(
        payload.get("source_tool_name") or payload.get("tool_name") or ""
    ).strip()
    step_id = str(
        payload.get("source_step_id") or payload.get("planner_step_id") or ""
    ).strip()
    return (
        capability_id == "data.analysis"
        or source_tool == "data.analyze"
        or "analysis" in step_id
    )


def _replan_fallback_tool_input(
    tool_name: str,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    clean_tool = str(tool_name or "").strip()
    input_preview = payload.get("input_preview") if isinstance(payload.get("input_preview"), Mapping) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    metadata_input = (
        metadata.get("input_preview")
        if isinstance(metadata.get("input_preview"), Mapping)
        else {}
    )
    source_input = {
        **dict(metadata_input),
        **dict(input_preview),
    }
    if clean_tool in {"browser.current_page", "desktop.active_window"}:
        return {}
    if clean_tool == "desktop.list_apps":
        query = _first_replan_fallback_app_query(source_input, payload, metadata)
        request: dict[str, Any] = {"limit": 20}
        if query:
            request["query"] = query
        return request
    if clean_tool == "desktop.running_apps":
        return {}
    if clean_tool in {"app.open", "desktop.open_app", "app.focus", "desktop.focus_app"}:
        app_name = _first_replan_fallback_app_name(source_input, payload, metadata)
        return {"app_name": app_name} if app_name else None
    if clean_tool in {"desktop.ui_elements", "desktop.read_ui"}:
        request = {"limit": source_input.get("limit", 80)}
        app_name = _first_replan_fallback_app_name(source_input, payload, metadata)
        if app_name:
            request["app_name"] = app_name
        role_filter = str(source_input.get("role_filter") or "").strip()
        if role_filter:
            request["role_filter"] = role_filter
        return request
    if clean_tool == "screen.capture":
        reason = str(
            payload.get("failure_detail")
            or metadata.get("failure_detail")
            or "recover failed runtime step"
        ).strip()
        return {"reason": reason} if reason else {}
    if clean_tool in {"desktop.open_path", "workspace.read", "fs.read_file", "file.read"}:
        path = _first_replan_fallback_path(source_input, payload, metadata)
        if not path:
            return None
        return {"path": path}
    if clean_tool in {"terminal.run", "python.run"}:
        return _terminal_data_analysis_replan_input(source_input, payload, metadata)
    return None


def _terminal_data_analysis_replan_input(
    source_input: Mapping[str, Any],
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    capability_id = str(
        payload.get("target_capability_id") or payload.get("capability_id") or ""
    ).strip()
    source_tool = str(
        payload.get("source_tool_name") or payload.get("tool_name") or ""
    ).strip()
    step_id = str(
        payload.get("source_step_id") or payload.get("planner_step_id") or ""
    ).strip()
    if not _replan_payload_is_data_analysis_fallback(
        {
            **dict(payload),
            "target_capability_id": capability_id,
            "source_tool_name": source_tool,
            "source_step_id": step_id,
        }
    ):
        return None
    path = _first_replan_fallback_path(source_input, payload, metadata)
    if not path:
        return None
    artifact_paths = _string_list(source_input.get("artifact_paths"))
    artifact_path = (
        str(source_input.get("artifact_path") or "").strip()
        or (artifact_paths[0] if artifact_paths else "")
        or "analysis-report.md"
    )
    command = _terminal_data_analysis_replan_command(
        path,
        artifact_path=artifact_path,
        source_kind=str(source_input.get("source_kind") or "").strip(),
    )
    return {"command": command, "shell": True, "timeout_seconds": 60}


def _terminal_data_analysis_replan_command(
    path: str,
    *,
    artifact_path: str,
    source_kind: str = "",
) -> str:
    source_literal = repr(str(path or "").strip())
    artifact_literal = repr(str(artifact_path or "analysis-report.md").strip())
    kind_literal = repr(str(source_kind or "").strip())
    return f"""python3 - <<'PY'
from pathlib import Path
import csv
import json

source = Path({source_literal})
artifact_path = Path({artifact_literal})
source_kind = {kind_literal}

def text_preview(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [], [], [f"read_error: {{exc}}"]
    lines = text.splitlines()
    return [], lines[:20], [f"line_count: {{len(lines)}}", f"char_count: {{len(text)}}"]

def tabular_preview(path):
    delimiter = "\\t" if path.suffix.lower() == ".tsv" or source_kind == "tsv" else ","
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=delimiter))
    except Exception as exc:
        return [], [], [f"csv_error: {{exc}}"]
    headers = rows[0] if rows else []
    data_rows = rows[1:] if headers else rows
    return headers, data_rows[:10], [f"row_count: {{len(data_rows)}}", f"column_count: {{len(headers)}}"]

def json_preview(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".jsonl" or source_kind == "jsonl":
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
            rows = data if isinstance(data, list) else [data]
    except Exception as exc:
        return [], [], [f"json_error: {{exc}}"]
    headers = sorted({{key for row in rows[:50] if isinstance(row, dict) for key in row.keys()}})
    sample = rows[:10]
    return headers, sample, [f"row_count: {{len(rows)}}", f"field_count: {{len(headers)}}"]

suffix = source.suffix.lower()
if suffix in {{".csv", ".tsv"}} or source_kind in {{"csv", "tsv"}}:
    headers, sample, notes = tabular_preview(source)
elif suffix in {{".json", ".jsonl"}} or source_kind in {{"json", "jsonl"}}:
    headers, sample, notes = json_preview(source)
else:
    headers, sample, notes = text_preview(source)

report = [
    "# Analysis fallback report",
    "",
    f"- source: {{source}}",
    *[f"- {{note}}" for note in notes],
]
if headers:
    report.extend(["", "## Columns", ", ".join(str(item) for item in headers)])
if sample:
    report.extend(["", "## Sample", "```"])
    for row in sample[:10]:
        report.append(json.dumps(row, ensure_ascii=False) if not isinstance(row, str) else row)
    report.append("```")

artifact_path.parent.mkdir(parents=True, exist_ok=True)
artifact_path.write_text("\\n".join(report) + "\\n", encoding="utf-8")
print("\\n".join(report))
print(f"\\n[artifact_written] {{artifact_path}}")
PY"""


def _first_replan_fallback_path(
    *sources: Mapping[str, Any],
) -> str:
    for source in sources:
        for key in (
            "path",
            "file_path",
            "data_source_hint",
            "source_path",
            "display_path",
        ):
            value = str(source.get(key) or "").strip()
            if value and not value.startswith("captured:"):
                return value
    return ""


def _first_replan_fallback_app_query(
    *sources: Mapping[str, Any],
) -> str:
    for source in sources:
        for key in (
            "target_app_query",
            "app_query",
            "query",
            "target_app_name",
            "app_name",
        ):
            value = str(source.get(key) or "").strip()
            if value and value != "<selected app from desktop.list_apps>":
                return value
    return ""


def _first_replan_fallback_app_name(
    *sources: Mapping[str, Any],
) -> str:
    for source in sources:
        for key in ("target_app_name", "app_name", "target_app_query", "app_query", "query"):
            value = str(source.get(key) or "").strip()
            if value and value != "<selected app from desktop.list_apps>":
                return value
    return ""


def _dedupe_replan_recovery_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for request in requests:
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or "").strip()
        request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        request_id = str(request.get("replan_request_id") or "").strip()
        signature = (
            tool_name,
            tuple(sorted((str(key), str(value)) for key, value in request_input.items())),
            request_id,
        )
        if not tool_name or signature in seen:
            continue
        seen.add(signature)
        result.append(request)
    return result


def _verification_recovery_tool_order(allowed: set[str]) -> list[str]:
    tools: list[str] = []
    for tool_name in (
        "desktop.active_window",
        "desktop.inspect_app",
        _first_allowed_tool(("desktop.list_windows", "desktop.windows"), allowed),
        _first_allowed_tool(("desktop.read_ui", "desktop.ui_elements"), allowed),
        "screen.capture",
    ):
        if tool_name and tool_name in allowed and tool_name not in tools:
            tools.append(tool_name)
    return tools


def _first_allowed_tool(candidates: tuple[str, ...], allowed: set[str]) -> str:
    for candidate in candidates:
        if candidate in allowed:
            return candidate
    return ""


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
    elif target_action == "app_search":
        app_search = _discovered_app_search_payload(target)
        search_query = str(app_search.get("query") or "").strip()
        if not search_query:
            return []
        requests.extend(
            _discovered_app_search_focus_requests(
                app_query,
                app_name,
                app_search,
                safe_shortcut_action,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
        )
        if not requests:
            return []
        type_request = _discovered_app_type_text_request(
            app_query,
            app_name,
            search_query,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if not type_request:
            return []
        requests.append(type_request)
        if _discovered_app_search_submit_requested(app_search):
            submit_request = _media_search_submit_request(
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
            if not submit_request:
                return []
            requests.append(_with_discovered_app_resolution(submit_request, app_query, app_name))
        result_requests = _discovered_app_search_result_requests(
            app_query,
            app_name,
            app_search,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if result_requests:
            requests.extend(result_requests)
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
    observation_request = _discovered_app_observation_request(
        target,
        allowed,
        app_query=app_query,
        app_name=app_name,
        source=source,
        planning_reason=planning_reason,
    )
    if observation_request:
        requests.append(observation_request)
    elif _discovered_app_post_action_continue_requested(target) and requests:
        requests[-1]["continue_to_model"] = True
    if (
        str(target.get("body_source") or "").strip() == "model_generated_content"
        and requests
    ):
        requests[-1]["continue_to_model"] = True
    if resolution_evidence:
        requests = [
            _with_discovered_app_resolution_evidence(request, resolution_evidence)
            for request in requests
        ]
    return _annotate_auto_followup_requests_from_tool_plan(requests, selection_payload)


def _annotate_auto_followup_requests_from_tool_plan(
    requests: list[dict[str, Any]],
    selection_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    steps = _selection_tool_plan_steps(selection_payload)
    if not requests or not steps:
        return requests
    trace_base = _auto_followup_selection_trace_base(selection_payload)
    annotated: list[dict[str, Any]] = []
    step_cursor = 0
    for request in requests:
        if not isinstance(request, dict):
            continue
        item = {**trace_base, **request}
        step_index, step = _next_matching_followup_plan_step(
            item,
            steps,
            start_index=step_cursor,
        )
        if step_index >= 0 and step:
            step_cursor = step_index + 1
            for key, value in _auto_followup_plan_step_trace(step).items():
                item.setdefault(key, value)
            for key, value in _auto_followup_task_context_for_step(
                selection_payload,
                str(item.get("step_id") or "").strip(),
            ).items():
                item.setdefault(key, value)
        if str(item.get("step_id") or "").strip() and not str(
            item.get("planner_step_id") or ""
        ).strip():
            item["planner_step_id"] = str(item.get("step_id") or "").strip()
        annotated.append(item)
    return annotated


def _first_annotated_auto_followup_request(
    request: dict[str, Any],
    selection_payload: Mapping[str, Any],
) -> dict[str, Any]:
    annotated = _annotate_auto_followup_requests_from_tool_plan(
        [request],
        selection_payload,
    )
    return annotated[0] if annotated else request


def _auto_followup_selection_trace_base(selection_payload: Mapping[str, Any]) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    for key in ("decision_id", "plan_id", "intent_kind"):
        value = str(selection_payload.get(key) or "").strip()
        if value:
            trace[key] = value
    tool_plan = (
        selection_payload.get("tool_plan")
        if isinstance(selection_payload.get("tool_plan"), Mapping)
        else {}
    )
    tool_plan_id = str(tool_plan.get("plan_id") or "").strip()
    if tool_plan_id:
        trace["tool_plan_id"] = tool_plan_id
    trace.update(_auto_followup_task_core_trace(selection_payload))
    return trace


def _auto_followup_task_core_trace(selection_payload: Mapping[str, Any]) -> dict[str, Any]:
    task_core = _model_followup_task_core_payload(selection_payload)
    if not task_core:
        return {}
    workspace = (
        task_core.get("workspace")
        if isinstance(task_core.get("workspace"), Mapping)
        else {}
    )
    trace: dict[str, Any] = {}
    core_id = str(task_core.get("core_id") or "").strip()
    if core_id:
        trace["core_id"] = core_id
    workspace_id = str(workspace.get("workspace_id") or "").strip()
    if workspace_id:
        trace["workspace_id"] = workspace_id
    return trace


def _auto_followup_task_context_for_step(
    selection_payload: Mapping[str, Any],
    step_id: str,
) -> dict[str, Any]:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id:
        return {}
    task_core = _model_followup_task_core_payload(selection_payload)
    if not isinstance(task_core, Mapping):
        return {}
    payload: dict[str, Any] = {}
    todos = task_core.get("todos")
    if isinstance(todos, list):
        for todo in todos:
            if not isinstance(todo, Mapping):
                continue
            if str(todo.get("step_id") or "").strip() == clean_step_id:
                payload["task_todo"] = dict(todo)
                break
    checkpoints = task_core.get("checkpoints")
    if isinstance(checkpoints, list):
        checkpoint_items = [
            dict(checkpoint)
            for checkpoint in checkpoints
            if isinstance(checkpoint, Mapping)
            and str(checkpoint.get("after_step_id") or "").strip() == clean_step_id
        ]
        if checkpoint_items:
            payload["task_checkpoints"] = checkpoint_items
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    workspace_items = workspace.get("items") if isinstance(workspace, Mapping) else []
    if isinstance(workspace_items, list):
        item_payloads = [
            dict(item)
            for item in workspace_items
            if isinstance(item, Mapping)
            and str(item.get("source_step_id") or "").strip() == clean_step_id
        ]
        if item_payloads:
            payload["task_workspace_items"] = item_payloads
    replan_signals = task_core.get("replan_signals")
    if isinstance(replan_signals, list):
        signal_ids: list[str] = []
        triggers: list[str] = []
        for signal in replan_signals:
            if not isinstance(signal, Mapping):
                continue
            if str(signal.get("source_step_id") or "").strip() != clean_step_id:
                continue
            signal_id = str(signal.get("signal_id") or "").strip()
            trigger = str(signal.get("trigger") or "").strip()
            if signal_id and signal_id not in signal_ids:
                signal_ids.append(signal_id)
            if trigger and trigger not in triggers:
                triggers.append(trigger)
        if signal_ids:
            payload["replan_signal_ids"] = signal_ids
        if triggers:
            payload["replan_triggers"] = triggers
    return payload

def _next_matching_followup_plan_step(
    request: Mapping[str, Any],
    steps: list[Mapping[str, Any]],
    *,
    start_index: int,
) -> tuple[int, Mapping[str, Any] | None]:
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return -1, None
    for index in range(max(0, start_index), len(steps)):
        step = steps[index]
        if str(step.get("status") or "planned").strip() not in {"", "planned"}:
            continue
        if not _followup_plan_tools_match(
            tool_name,
            str(step.get("tool_name") or "").strip(),
        ):
            continue
        return index, step
    return -1, None


_FOLLOWUP_PLAN_TOOL_EQUIVALENCE_GROUPS = (
    {
        "desktop.click_ui_element",
        "desktop.safe_click",
        "desktop.click",
        "app.focus_and_click_ui_element",
        "app.open_and_click_ui_element",
    },
    {
        "desktop.type_into_ui_element",
        "desktop.safe_type_text",
        "desktop.type_text",
        "desktop.type",
        "app.focus_and_type_into_ui_element",
        "app.open_and_type_into_ui_element",
    },
)


def _followup_plan_tools_match(request_tool: str, plan_tool: str) -> bool:
    clean_request_tool = str(request_tool or "").strip()
    clean_plan_tool = str(plan_tool or "").strip()
    if not clean_request_tool or not clean_plan_tool:
        return False
    if clean_request_tool == clean_plan_tool:
        return True
    return any(
        clean_request_tool in group and clean_plan_tool in group
        for group in _FOLLOWUP_PLAN_TOOL_EQUIVALENCE_GROUPS
    )


def _auto_followup_plan_step_trace(step: Mapping[str, Any]) -> dict[str, str]:
    trace: dict[str, str] = {}
    for source_key, target_key in (
        ("step_id", "step_id"),
        ("capability_id", "capability_id"),
    ):
        value = str(step.get(source_key) or "").strip()
        if value:
            trace[target_key] = value
    return trace


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
    if not app_query:
        return []
    app_name = str(target.get("app_name") or target.get("target_app_name") or "").strip()
    if not app_name:
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
    if not media_query:
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
        if str(playback_request.get("tool") or "").strip() != "media.music_app_open_and_play":
            open_request = _discovered_app_open_request(
                app_query,
                app_name,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
            if open_request:
                requests.append(open_request)
        requests.append(playback_request)
        observation_request = _discovered_app_observation_request(
            target,
            allowed,
            app_query=app_query,
            app_name=app_name,
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
        return _annotate_auto_followup_requests_from_tool_plan(requests, selection_payload)
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
        if not requests:
            requests = _discovered_media_observed_search_requests(
                app_query,
                app_name,
                media_query,
                target,
                allowed,
                source=source,
                planning_reason=planning_reason,
            )
            if not requests:
                return []
            if resolution_evidence:
                requests = [
                    _with_discovered_app_resolution_evidence(request, resolution_evidence)
                    for request in requests
                ]
            return _annotate_auto_followup_requests_from_tool_plan(
                requests,
                selection_payload,
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
        app_query=app_query,
        app_name=app_name,
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
    return _annotate_auto_followup_requests_from_tool_plan(requests, selection_payload)


def _discovered_media_observed_search_requests(
    app_query: str,
    app_name: str,
    media_query: str,
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    type_tool = _discovered_media_search_deferred_type_tool(allowed)
    if not type_tool:
        return []
    observation_tool = _first_allowed_tool(("desktop.ui_elements", "desktop.read_ui"), allowed)
    if not observation_tool:
        return []
    open_request = _discovered_app_open_request(
        app_query,
        app_name,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    result_observation = _discovered_media_result_observation_request(
        app_name,
        target,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )
    if not result_observation:
        return []
    deferred_input: dict[str, Any] = {
        "app_name": app_name,
        "app_query": app_query,
        "target": "search 搜索",
        "text": media_query,
        "role_filter": "text",
        "limit": 80,
    }
    continuation: list[dict[str, Any]] = []
    if "desktop.submit_foreground" in allowed:
        deferred_input["submit_action"] = "confirm"
    else:
        submit_request = _media_search_submit_request(
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if not submit_request:
            return []
        continuation.append(submit_request)
    continuation.append(result_observation)
    observation_input = {"app_name": app_name, "role_filter": "text", "limit": 80}
    observation_request = _with_discovered_app_resolution(
        _request_like(
            observation_tool,
            observation_input,
            source=source,
            planning_reason=planning_reason,
        ),
        app_query,
        app_name,
    )
    observation_request["continue_to_model"] = True
    observation_request["deferred_tool"] = type_tool
    observation_request["deferred_input"] = deferred_input
    observation_request["deferred_continuation"] = continuation
    return [*([open_request] if open_request else []), observation_request]


def _discovered_media_search_deferred_type_tool(allowed: set[str]) -> str:
    return _first_allowed_tool(
        (
            "app.focus_and_type_into_ui_element",
            "app.open_and_type_into_ui_element",
            "desktop.type_into_ui_element",
        ),
        allowed,
    ) or (
        "desktop.type_into_ui_element"
        if _first_allowed_tool(
            ("desktop.safe_type_text", "desktop.type_text", "desktop.type"),
            allowed,
        )
        and _first_allowed_tool(
            (
                "app.focus_and_click_ui_element",
                "app.open_and_click_ui_element",
                "desktop.click_ui_element",
                "desktop.safe_click",
                "desktop.click",
            ),
            allowed,
        )
        else ""
    )


def _discovered_media_result_observation_request(
    app_name: str,
    target: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    click_tool = _discovered_media_result_deferred_click_tool(allowed)
    if not click_tool:
        return {}
    observation_tool = _first_allowed_tool(("desktop.ui_elements", "desktop.read_ui"), allowed)
    if not observation_tool:
        return {}
    result_selection = (
        target.get("result_selection")
        if isinstance(target.get("result_selection"), Mapping)
        else {}
    )
    result_input = {
        "app_name": app_name,
        "target": str(result_selection.get("target") or "first result").strip(),
        "role_filter": str(result_selection.get("role_filter") or "").strip(),
        "limit": _positive_int(result_selection.get("limit"), default=80),
        "click_count": _positive_int(result_selection.get("click_count"), default=1),
    }
    request = _request_like(
        observation_tool,
        {
            "app_name": app_name,
            "role_filter": result_input["role_filter"],
            "limit": result_input["limit"],
        },
        source=source,
        planning_reason=planning_reason,
    )
    request["continue_to_model"] = True
    request["deferred_tool"] = click_tool
    request["deferred_input"] = result_input
    request["deferred_context"] = {
        "step_id": "play-media-search-result",
        "planner_step_id": "play-media-search-result",
        "capability_id": "media.playback",
    }
    return request


def _discovered_media_result_deferred_click_tool(allowed: set[str]) -> str:
    return _first_allowed_tool(
        (
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
            "desktop.click_ui_element",
        ),
        allowed,
    ) or (
        "desktop.click_ui_element"
        if _first_allowed_tool(("desktop.safe_click", "desktop.click"), allowed)
        else ""
    )


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
    focus_tool = _first_allowed_tool(
        ("app.open", "desktop.open_app", "app.focus", "desktop.focus_app"),
        allowed,
    )
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
    tool_name = _first_allowed_open_path_with_app_tool(allowed)
    if not tool_name:
        return {}
    return _with_discovered_app_resolution(
        _request_like(
            tool_name,
            {"app_name": app_name, "path": path},
            source=source,
            planning_reason=planning_reason,
        ),
        app_query,
        app_name,
    )


def _first_allowed_open_path_with_app_tool(allowed: set[str]) -> str:
    for tool_name in ("desktop.open_path_with_app", "app.open_path_with_app"):
        if tool_name in allowed:
            return tool_name
    return ""


def _discovered_app_open_request(
    app_query: str,
    app_name: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    tool_name = _first_allowed_tool(
        ("app.open", "desktop.open_app", "app.focus", "desktop.focus_app"),
        allowed,
    )
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
        return _with_discovered_app_resolution(
            _request_like(
                "desktop.safe_type_text",
                {"text": text},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
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


def _discovered_app_search_payload(target: Mapping[str, Any]) -> dict[str, Any]:
    raw = target.get("app_search") if isinstance(target.get("app_search"), Mapping) else {}
    query = str(raw.get("query") or target.get("app_search_query") or "").strip()
    if not query:
        return {}
    payload: dict[str, Any] = {"query": query}
    for key in ("target", "scope", "submit_action", "select_result"):
        value = str(raw.get(key) or target.get(f"app_search_{key}") or "").strip()
        if value:
            payload[key] = value
    focus = raw.get("focus") if isinstance(raw.get("focus"), Mapping) else {}
    if focus:
        tool_name = str(focus.get("tool") or "").strip()
        raw_input = focus.get("input") if isinstance(focus.get("input"), Mapping) else {}
        if tool_name:
            payload["focus"] = {
                "tool": tool_name,
                "input": dict(raw_input),
            }
    result_selection = (
        raw.get("result_selection")
        if isinstance(raw.get("result_selection"), Mapping)
        else {}
    )
    if result_selection:
        payload["result_selection"] = dict(result_selection)
    submit = raw.get("submit", target.get("app_search_submit"))
    if isinstance(submit, bool):
        payload["submit"] = submit
    elif str(submit or "").strip().lower() in {"1", "true", "yes", "y"}:
        payload["submit"] = True
    verify = raw.get("verify", target.get("app_search_verify"))
    if isinstance(verify, bool):
        payload["verify"] = verify
    elif str(verify or "").strip().lower() in {"1", "true", "yes", "y"}:
        payload["verify"] = True
    return payload


def _discovered_app_search_submit_requested(app_search: Mapping[str, Any]) -> bool:
    result_selection = _discovered_app_search_result_selection(app_search)
    if str(result_selection.get("action") or "").strip() == "key_confirm":
        return False
    if str(app_search.get("submit_action") or "").strip() == "confirm":
        return False
    submit = app_search.get("submit")
    if isinstance(submit, bool):
        return submit
    if str(submit or "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    return bool(str(app_search.get("submit_action") or "").strip())


def _discovered_app_search_result_selection(app_search: Mapping[str, Any]) -> dict[str, Any]:
    raw = (
        app_search.get("result_selection")
        if isinstance(app_search.get("result_selection"), Mapping)
        else {}
    )
    if raw:
        return dict(raw)
    if str(app_search.get("select_result") or "").strip() == "arrow_down":
        return {"action": "key_confirm"}
    return {}


def _discovered_app_search_result_requests(
    app_query: str,
    app_name: str,
    app_search: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    result_selection = _discovered_app_search_result_selection(app_search)
    action = str(result_selection.get("action") or "").strip()
    if action == "click":
        request = _discovered_app_search_result_click_request(
            app_query,
            app_name,
            result_selection,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        return [request] if request else []
    if action == "key_confirm":
        return _discovered_app_search_result_key_confirm_requests(
            app_query,
            app_name,
            result_selection,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
    return []


def _discovered_app_search_result_click_request(
    app_query: str,
    app_name: str,
    result_selection: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> dict[str, Any]:
    tool_name = str(result_selection.get("tool") or "").strip()
    raw_input = (
        result_selection.get("input")
        if isinstance(result_selection.get("input"), Mapping)
        else {}
    )
    input_payload = dict(raw_input)
    for key in ("selection_source", "app_selection_source", "query"):
        input_payload.pop(key, None)
    if not tool_name:
        tool_name = (
            "app.focus_and_click_ui_element"
            if "app.focus_and_click_ui_element" in allowed
            else "desktop.click_ui_element"
        )
    if tool_name not in allowed:
        return {}
    if tool_name.startswith("app."):
        input_payload.setdefault("app_name", app_name)
    return _with_discovered_app_resolution(
        _request_like(
            tool_name,
            input_payload,
            source=source,
            planning_reason=planning_reason,
        ),
        app_query,
        app_name,
    )


def _discovered_app_search_result_key_confirm_requests(
    app_query: str,
    app_name: str,
    result_selection: Mapping[str, Any],
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    key = result_selection.get("key") if isinstance(result_selection.get("key"), Mapping) else {}
    confirm = (
        result_selection.get("confirm")
        if isinstance(result_selection.get("confirm"), Mapping)
        else {}
    )
    key_tool = str(key.get("tool") or "desktop.safe_key").strip()
    confirm_tool = str(confirm.get("tool") or "desktop.submit_foreground").strip()
    if key_tool not in allowed or confirm_tool not in allowed:
        return []
    key_input = key.get("input") if isinstance(key.get("input"), Mapping) else {}
    confirm_input = (
        confirm.get("input") if isinstance(confirm.get("input"), Mapping) else {}
    )
    return [
        _with_discovered_app_resolution(
            _request_like(
                key_tool,
                dict(key_input) or {"action": "arrow_down", "repeat_count": 1},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        ),
        _with_discovered_app_resolution(
            _request_like(
                confirm_tool,
                dict(confirm_input) or {"action": "confirm"},
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        ),
    ]


def _discovered_app_search_focus_requests(
    app_query: str,
    app_name: str,
    app_search: Mapping[str, Any],
    safe_shortcut_action: str,
    allowed: set[str],
    *,
    source: str,
    planning_reason: str,
) -> list[dict[str, Any]]:
    focus = app_search.get("focus") if isinstance(app_search.get("focus"), Mapping) else {}
    focus_tool = str(focus.get("tool") or "").strip()
    focus_input = focus.get("input") if isinstance(focus.get("input"), Mapping) else {}
    if focus_tool == "desktop.click_ui_element" and focus_tool in allowed:
        open_request = _discovered_app_open_request(
            app_query,
            app_name,
            allowed,
            source=source,
            planning_reason=planning_reason,
        )
        if not open_request:
            return []
        click_request = _with_discovered_app_resolution(
            _request_like(
                focus_tool,
                dict(focus_input),
                source=source,
                planning_reason=planning_reason,
            ),
            app_query,
            app_name,
        )
        return [open_request, click_request]
    action = str(focus_input.get("action") or safe_shortcut_action or "find").strip()
    if not action:
        return []
    return _discovered_app_safe_shortcut_requests(
        app_query,
        app_name,
        action,
        allowed,
        source=source,
        planning_reason=planning_reason,
    )


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
    app_query: str = "",
    app_name: str = "",
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
        alias_tool = _discovered_app_observation_alias_tool(tool_name)
        fallback_tool = _discovered_app_observation_fallback_tool(tool_name, allowed)
        if not fallback_tool:
            return {}
        tool_name = fallback_tool
        if fallback_tool != alias_tool:
            raw_input = {}
    request = _request_like(
        tool_name,
        dict(raw_input),
        source=source,
        planning_reason=planning_reason,
    )
    if (
        isinstance(target.get("creative_canvas"), Mapping)
        or _discovered_app_post_action_continue_requested(target)
    ):
        request["continue_to_model"] = True
    if app_query and app_name and _tool_accepts_discovered_app_context(tool_name):
        request = _with_discovered_app_resolution(request, app_query, app_name)
    return request


def _tool_accepts_discovered_app_context(tool_name: str) -> bool:
    return str(tool_name or "").strip() in {
        "desktop.inspect_app",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.verify",
        "desktop.windows",
        "desktop.list_windows",
    }


def _discovered_app_post_action_continue_requested(
    target: Mapping[str, Any],
) -> bool:
    post_action_observation = (
        target.get("post_action_observation")
        if isinstance(target.get("post_action_observation"), Mapping)
        else {}
    )
    value = post_action_observation.get("continue_to_model")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _discovered_app_observation_fallback_tool(
    requested_tool: str,
    allowed: set[str],
) -> str:
    alias = _discovered_app_observation_alias_tool(requested_tool)
    if alias and alias in allowed:
        return alias
    if "desktop.ui_elements" in allowed:
        return "desktop.ui_elements"
    if "desktop.read_ui" in allowed:
        return "desktop.read_ui"
    return ""


def _discovered_app_observation_alias_tool(requested_tool: str) -> str:
    return {
        "desktop.ui_elements": "desktop.read_ui",
        "desktop.windows": "desktop.list_windows",
    }.get(str(requested_tool or "").strip(), "")


def _with_discovered_app_resolution(
    request: dict[str, Any],
    app_query: str,
    app_name: str,
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or "").strip()
    payload = dict(request)
    request_input = (
        dict(payload.get("input"))
        if isinstance(payload.get("input"), Mapping)
        else {}
    )
    raw_app_name = str(request_input.get("app_name") or "").strip()
    if app_name and (
        not raw_app_name
        or _runtime_planner_placeholder_app_name(raw_app_name)
        or raw_app_name == app_query
    ) and (tool_name.startswith("app.") or raw_app_name):
        request_input["app_name"] = app_name
        payload["input"] = request_input
    return {
        **request,
        **payload,
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
    if kind == "desktop_observed_action":
        return _model_followup_desktop_observed_action_instruction(target)
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


def _model_followup_desktop_observed_action_instruction(target: Mapping[str, Any]) -> str:
    target_action = str(target.get("target_action") or "").strip()
    target_label = str(target.get("target") or "").strip()
    if target_action not in {"click", "type_text"} or not target_label:
        return ""
    if not bool(target.get("action_allowed")):
        return (
            f"The user requested a foreground desktop {target_action} on {target_label!r}, "
            "but no allowed desktop action tool can complete it after the UI observation. "
            "Explain the missing capability instead of claiming the action was performed."
        )
    tools = _string_list(target.get("recommended_tools"))
    verify_tools = _string_list(target.get("verify_tools"))
    tool_text = ", ".join(tools) or "the allowed desktop action tools"
    verify_text = (
        f" Verify with {', '.join(verify_tools)} after the action."
        if verify_tools
        else ""
    )
    role_filter = str(target.get("role_filter") or "").strip()
    role_text = f" with role/filter {role_filter!r}" if role_filter else ""
    if target_action == "click":
        click_count = _clean_model_followup_int(target.get("click_count"), default=1)
        return (
            "The user requested a foreground UI click after the runtime observed the current "
            f"page/window. Use the latest observed UI snapshot to find {target_label!r}"
            f"{role_text}, then call a desktop action tool next instead of only replying inline. "
            f"Prefer {tool_text}; use click_count={click_count}. If only coordinate clicking is "
            "available, infer coordinates from the observed element or screenshot before calling "
            f"desktop.click; do not ask the user to click manually.{verify_text} "
        )
    text = str(target.get("text") or "")
    return (
        "The user requested foreground UI typing after the runtime observed the current "
        f"page/window. Use the latest observed UI snapshot to find {target_label!r}"
        f"{role_text}, then call a desktop action tool next instead of only replying inline. "
        f"Prefer {tool_text}; type the explicit user text {text!r}. If only low-level tools "
        "are available, focus the matching field with desktop.click when needed and then call "
        f"desktop.type_text or desktop.type. Do not ask the user to type manually.{verify_text} "
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
    app_search = _discovered_app_search_payload(target)
    if app_search:
        search_query = str(app_search.get("query") or "").strip()
        submit_text = (
            " submit the search with desktop.search_submit,"
            if _discovered_app_search_submit_requested(app_search)
            else ""
        )
        result_text = _model_followup_app_search_result_instruction(app_search)
        return (
            f"The runtime discovered an app for {app_query!r}. Continue by using desktop "
            "tools to focus the discovered app's search field, type the explicit user "
            f"search query {search_query!r},{submit_text} and then continue from the observed "
            f"result.{result_text} Prefer {tool_text}.{verify_text} If search-field focus "
            "or text input tools are unavailable, explain the missing capability instead "
            "of claiming the app search was completed. "
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
    target_action = str(target.get("target_action") or "").strip()
    safe_shortcut_action = str(target.get("safe_shortcut_action") or "").strip()
    body_source = str(
        target.get("body_source")
        or target.get("context_source")
        or ""
    ).strip()
    if (
        target_action == "safe_shortcut"
        and safe_shortcut_action == "paste"
        and body_source
        in {"clipboard", "selection", "current_page_link", "current_page_content"}
    ):
        source_text = {
            "clipboard": "the existing clipboard contents",
            "selection": "the runtime-captured selected text",
            "current_page_link": "the runtime-captured current page link",
            "current_page_content": "the runtime-captured current page content",
        }[body_source]
        source_action = str(target.get("source_action") or "").strip()
        source_action_text = (
            f" If that context has not been captured yet, first run the source shortcut "
            f"{source_action!r}."
            if source_action and source_action != "use_existing_clipboard"
            else ""
        )
        return (
            f"The user requested transferring {source_text} into an app matching "
            f"{app_query!r}.{source_action_text} Continue by selecting the best discovered "
            "app, opening or focusing it, then paste with the allowed desktop shortcut "
            f"tools. Prefer {tool_text}.{verify_text} Do not ask the user to copy or paste "
            "manually, and do not replace the captured context with newly generated content. "
            "If app discovery or paste tools are unavailable, explain the missing capability "
            "instead of claiming the app was updated. "
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
        pending_action = str(target.get("pending_user_action") or "").strip()
        pending_text = (
            f" The remaining user action is: {pending_action!r}; continue toward that "
            "action after the canvas is available."
            if pending_action
            else ""
        )
        return (
            f"The runtime already discovered and attempted to open the best app for {app_query!r}. "
            f"Use the latest UI observation to create or configure the requested{size_text} canvas. "
            f"{pending_text} Call desktop UI tools next instead of replying inline. Prefer {tool_text}."
            f"{verify_text} If the required fields are not visible, inspect the UI again before "
            "claiming completion. "
        )
    if _discovered_app_post_action_continue_requested(target):
        pending_action = str(target.get("pending_user_action") or "").strip()
        pending_text = (
            f" The remaining user action is: {pending_action!r}."
            if pending_action
            else ""
        )
        return (
            f"The runtime discovered and opened an app for {app_query!r}, then requested "
            "a UI observation because the user asked for more than simply opening it."
            f"{pending_text} Use the latest observed UI to continue with desktop tools next; "
            f"prefer {tool_text}.{verify_text} If the required controls are not visible, "
            "inspect the app again or explain the missing desktop UI capability instead of "
            "claiming the task is complete. "
        )
    return (
        f"The runtime discovered an app for {app_query!r}. Continue the requested desktop action "
        f"with safe app or foreground tools next. Prefer {tool_text}.{verify_text} "
    )


def _model_followup_app_search_result_instruction(app_search: Mapping[str, Any]) -> str:
    result_selection = _discovered_app_search_result_selection(app_search)
    action = str(result_selection.get("action") or "").strip()
    if action == "click":
        tool_name = str(result_selection.get("tool") or "desktop.click_ui_element").strip()
        raw_input = (
            result_selection.get("input")
            if isinstance(result_selection.get("input"), Mapping)
            else {}
        )
        target = str(raw_input.get("target") or "the requested result").strip()
        return (
            f" Then select the requested app-search result {target!r} with {tool_name}; "
            "if that click tool requires approval, pause for approval instead of claiming "
            "the result was opened. "
        )
    if action == "key_confirm":
        return (
            " Then use desktop.safe_key for the requested navigation key and request the "
            "approval-gated desktop.submit_foreground confirm action; do not claim the "
            "result was opened until the approval-gated confirm tool has executed. "
        )
    return " "


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
    return _model_followup_context_target(_latest_model_followup_context(timeline))


def _latest_model_followup_context(
    timeline: list[dict[str, Any]],
    *,
    include_pending_execution_only: bool = False,
) -> dict[str, Any]:
    for event in reversed(timeline):
        if not isinstance(event, dict):
            continue
        if str(event.get("event") or "").strip() != "agent.model.followup_context":
            continue
        context = {
            str(key): value
            for key, value in event.items()
            if key not in {"timestamp"}
        }
        if (
            not _followup_event_has_readable_source(event)
            and not (
                include_pending_execution_only
                and _followup_event_has_pending_execution(event)
            )
            and not _model_followup_target_from_task_core_context(context)
        ):
            return {}
        return context
    return {}


def _model_followup_context_target(context: Mapping[str, Any]) -> dict[str, Any]:
    target = context.get("followup_target") if isinstance(context, Mapping) else {}
    if isinstance(target, dict):
        return dict(target)
    return _model_followup_target_from_task_core_context(context)


def _model_followup_target_from_task_core_context(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        return {}
    task_core = context.get("task_core") if isinstance(context.get("task_core"), Mapping) else {}
    if not task_core:
        return {}
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    workspace_items = workspace.get("items") if isinstance(workspace.get("items"), list) else []
    for item in workspace_items:
        if not isinstance(item, Mapping):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        tool_name = str(metadata.get("tool_name") or "").strip()
        if tool_name not in _MODEL_FOLLOWUP_TEXT_ENTRY_TOOLS:
            continue
        raw_input = (
            metadata.get("input_preview")
            if isinstance(metadata.get("input_preview"), Mapping)
            else {}
        )
        app_name = str(raw_input.get("app_name") or "").strip()
        if not app_name:
            app_name = _model_followup_task_core_input_value(task_core, "target_app_hint")
        if not app_name:
            continue
        payload: dict[str, Any] = {
            "kind": "app_write",
            "app_name": app_name,
            "target_action": str(
                raw_input.get("target_action")
                or _model_followup_task_core_input_value(task_core, "target_action_hint")
                or "app_paste"
            ).strip(),
            "body_source": str(raw_input.get("body_source") or "model_generated_content").strip(),
        }
        container_action = str(
            raw_input.get("container_action")
            or _model_followup_task_core_input_value(
                task_core,
                "target_container_action_hint",
            )
            or ""
        ).strip()
        if container_action:
            payload["container_action"] = container_action
        artifact_path = str(raw_input.get("artifact_path") or "").strip()
        if artifact_path:
            payload["artifact_write"] = {
                "path": artifact_path,
                "body_source": payload["body_source"],
                "tool": "artifact.write",
            }
        return payload
    return {}


def _model_followup_task_core_input_value(
    task_core: Mapping[str, Any],
    key: str,
) -> str:
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    workspace_items = workspace.get("items") if isinstance(workspace.get("items"), list) else []
    expected = str(key or "").strip()
    if not expected:
        return ""
    for item in workspace_items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("title") or "").strip() != expected:
            continue
        return str(item.get("description") or "").strip()
    return ""


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


def _followup_event_has_pending_execution(event: Mapping[str, Any]) -> bool:
    pending_requests = event.get("pending_execution_requests")
    if not isinstance(pending_requests, list):
        return False
    return any(
        isinstance(request, Mapping)
        and str(request.get("tool_name") or request.get("tool") or "").strip()
        for request in pending_requests
    )


_MODEL_FOLLOWUP_AUTO_PENDING_TOOLS = {
    "app.open",
    "artifact.write",
    "data.analyze",
    "app.focus",
    "app.focus_and_click_ui_element",
    "app.focus_and_hotkey",
    "app.focus_and_safe_click",
    "app.focus_and_safe_key",
    "app.focus_and_safe_scroll",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.open_and_click_ui_element",
    "app.open_and_hotkey",
    "app.open_and_safe_click",
    "app.open_and_safe_key",
    "app.open_and_safe_scroll",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_shortcut",
    "app.focus_and_type_into_ui_element",
    "app.open_and_type_into_ui_element",
    "desktop.active_window",
    "desktop.click_ui_element",
    "desktop.hotkey",
    "desktop.open_path_with_app",
    "app.open_path_with_app",
    "desktop.read_ui",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.shortcut",
    "desktop.submit_foreground",
    "desktop.type_text",
    "desktop.type_into_ui_element",
    "desktop.ui_elements",
    "clipboard.write",
    "screen.capture",
    "terminal.run",
}

_MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS = 6

_RUNTIME_ORCHESTRATION_SCOPE_KEYS = (
    "group_run_id",
    "run_group_id",
    "group_id",
    "workflow_run_id",
    "workflow_id",
    "workflow_node_id",
    "workflow_node_label",
    "workflow_node_kind",
)


def _model_followup_pending_plan_requests(
    followup_context: Mapping[str, Any] | None,
    allowed_tools: Iterable[str],
    *,
    generated_content: str = "",
    timeline: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(followup_context, Mapping):
        return []
    raw_steps = _model_followup_pending_trace_items(followup_context)
    if not raw_steps:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planning_reason = str(
        followup_context.get("planning_reason") or "planner_followup_pending_plan"
    ).strip()
    requests: list[dict[str, Any]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, Mapping):
            continue
        request = _model_followup_pending_plan_request(
            raw_step,
            allowed,
            planning_reason=planning_reason,
            generated_content=generated_content,
            followup_context=followup_context,
        )
        if not request:
            break
        _attach_model_followup_pending_plan_trace_metadata(
            request,
            raw_step,
            followup_context,
        )
        request = _pending_plan_request_with_timeline_resolved_app(
            request,
            raw_step,
            followup_context,
            timeline or [],
        )
        requests.append(request)
        if len(requests) >= _MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS:
            break
    return requests


def _model_followup_pending_plan_continuation_requests(
    followup_context: Mapping[str, Any] | None,
    completed_tool_requests: Iterable[Mapping[str, Any]],
    allowed_tools: Iterable[str],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[dict[str, Any]]:
    if not isinstance(followup_context, Mapping):
        return []
    steps = [
        step
        for step in _model_followup_pending_trace_items(followup_context)
        if isinstance(step, Mapping)
    ]
    if not steps:
        return []
    completed_requests = [
        request for request in completed_tool_requests if isinstance(request, Mapping)
    ]
    if not completed_requests:
        return []
    completed_step_ids = _model_followup_completed_step_ids(
        completed_requests,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )
    if not completed_step_ids:
        return []
    last_completed_index = _model_followup_last_completed_step_index(
        completed_requests,
        steps,
        timeline,
        tool_timeline_start=tool_timeline_start,
    )
    if last_completed_index < 0:
        return []
    for step in steps[: last_completed_index + 1]:
        step_id = str(step.get("step_id") or "").strip()
        if step_id:
            completed_step_ids.add(step_id)
    completed_step_ids.update(
        _model_followup_completed_step_ids_from_timeline(
            timeline,
            steps,
        )
    )
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    planning_reason = str(
        followup_context.get("planning_reason") or "planner_followup_pending_plan"
    ).strip()
    requests: list[dict[str, Any]] = []
    for step in steps[last_completed_index + 1 :]:
        step_id = str(step.get("step_id") or "").strip()
        if step_id and step_id in completed_step_ids:
            continue
        dependencies = _string_list(step.get("depends_on"))
        if any(dependency not in completed_step_ids for dependency in dependencies):
            break
        request = _model_followup_pending_plan_request(
            step,
            allowed,
            planning_reason=planning_reason,
            followup_context=followup_context,
        )
        if not request:
            break
        _attach_model_followup_pending_plan_trace_metadata(
            request,
            step,
            followup_context,
        )
        request = _pending_plan_request_with_timeline_resolved_app(
            request,
            step,
            followup_context,
            timeline,
        )
        requests.append(request)
        if len(requests) >= _MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS:
            break
    return requests


def _model_followup_pending_plan_replan_payloads(
    followup_context: Mapping[str, Any],
    planned_tool_requests: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
    run_id: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(followup_context, Mapping):
        return []
    steps = [
        step
        for step in _model_followup_pending_trace_items(followup_context)
        if isinstance(step, Mapping)
    ]
    requests = [
        request for request in planned_tool_requests if isinstance(request, Mapping)
    ]
    if not steps or not requests:
        return []
    tool_events = [
        event
        for event in timeline[tool_timeline_start:]
        if isinstance(event, Mapping)
        and str(event.get("event") or "").strip()
        in {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
    ]
    if not tool_events:
        return []
    payloads: list[dict[str, Any]] = []
    step_cursor = 0
    event_cursor = 0
    for request in requests:
        step_index, step = _next_matching_model_followup_pending_step(
            request,
            steps,
            start_index=step_cursor,
        )
        if step_index >= 0:
            step_cursor = step_index + 1
        else:
            step = None
        event_index, tool_event = _next_matching_model_followup_tool_event(
            request,
            tool_events,
            start_index=event_cursor,
        )
        if event_index >= 0:
            event_cursor = event_index + 1
        if not tool_event:
            continue
        result = (
            dict(tool_event.get("result"))
            if isinstance(tool_event.get("result"), Mapping)
            else {}
        )
        if tool_event.get("verification_failed") is True:
            result["verification_failed"] = True
        if not _tool_result_requests_replan(result):
            continue
        step_mapping = step if isinstance(step, Mapping) else {}
        source_step_id = str(
            request.get("step_id")
            or request.get("planner_step_id")
            or step_mapping.get("step_id")
            or ""
        ).strip()
        source_tool_name = str(
            request.get("tool")
            or request.get("tool_name")
            or step_mapping.get("tool_name")
            or tool_event.get("detail")
            or ""
        ).strip()
        trigger = _model_followup_pending_plan_replan_trigger(
            request,
            step_mapping,
            tool_event,
            result,
        )
        target_capability_id = str(
            request.get("capability_id") or step_mapping.get("capability_id") or ""
        ).strip()
        failure_event_type = str(tool_event.get("event") or "agent.tool.call").strip()
        failure_detail = _model_followup_pending_plan_failure_detail(
            tool_event,
            result,
        )
        fallback_tools = (
            _string_list(step_mapping.get("fallback_tools"))
            or _string_list(request.get("fallback_tools"))
            or _model_followup_default_replan_fallback_tools(
                source_tool_name,
                trigger=trigger,
                capability_id=target_capability_id,
            )
        )
        task_context = _model_followup_task_core_replan_context(
            followup_context,
            source_step_id,
            matched_step_id=str(step_mapping.get("step_id") or source_step_id).strip(),
        )
        metadata = {
            **_runtime_trace_metadata_from_mapping(followup_context),
            **_runtime_trace_metadata_from_mapping(request),
            **_runtime_trace_metadata_from_mapping(tool_event),
            **_runtime_replan_failure_metadata(result),
            "original_intent_kind": str(
                request.get("intent_kind")
                or followup_context.get("intent_kind")
                or ""
            ).strip(),
            "input_preview": _model_followup_request_input_preview(request, tool_event),
            "result_preview": _task_progress_result_preview(result),
        }
        if task_context:
            metadata["task_core_context"] = task_context
        metadata = {
            key: value
            for key, value in metadata.items()
            if value not in (None, "", [], {})
        }
        payload: dict[str, Any] = {
            "request_id": _model_followup_replan_stable_id(
                "replan-request",
                followup_context.get("decision_id"),
                followup_context.get("plan_id"),
                source_step_id,
                source_tool_name,
                trigger,
                failure_detail,
            ),
            "trigger": trigger,
            "status": "requested",
            "source": "runtime_planner",
            "run_id": str(run_id or request.get("run_id") or followup_context.get("run_id") or "").strip(),
            "task_id": str(request.get("task_id") or followup_context.get("task_id") or "").strip(),
            "decision_id": str(
                request.get("decision_id") or followup_context.get("decision_id") or ""
            ).strip(),
            "plan_id": str(request.get("plan_id") or followup_context.get("plan_id") or "").strip(),
            "core_id": str(request.get("core_id") or followup_context.get("core_id") or "").strip(),
            "source_step_id": source_step_id,
            "source_tool_name": source_tool_name,
            "target_capability_id": target_capability_id,
            "condition": _model_followup_pending_plan_replan_condition(trigger),
            "reason": _model_followup_pending_plan_replan_reason(
                trigger,
                source_step_id=source_step_id,
                source_tool_name=source_tool_name,
            ),
            "failure_event_type": failure_event_type,
            "failure_detail": failure_detail,
            "fallback_tools": fallback_tools,
            "metadata": metadata,
        }
        for key in _RUNTIME_ORCHESTRATION_SCOPE_KEYS:
            value = str(request.get(key) or followup_context.get(key) or "").strip()
            if value:
                payload[key] = value
        prompt = _model_followup_pending_plan_replan_prompt(payload, task_context)
        if prompt:
            payload["replan_prompt"] = prompt
        payloads.append(
            {key: value for key, value in payload.items() if value not in ("", [], {})}
        )
    return payloads


def _next_matching_model_followup_tool_event(
    request: Mapping[str, Any],
    tool_events: list[Mapping[str, Any]],
    *,
    start_index: int = 0,
) -> tuple[int, Mapping[str, Any] | None]:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    step_id = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
    for index in range(max(0, start_index), len(tool_events)):
        event = tool_events[index]
        event_tool = str(event.get("detail") or event.get("tool") or "").strip()
        event_step_id = str(
            event.get("step_id") or event.get("planner_step_id") or ""
        ).strip()
        if step_id and event_step_id and step_id != event_step_id:
            continue
        if tool_name and event_tool and tool_name != event_tool:
            continue
        if step_id or tool_name:
            return index, event
    return -1, None


def _model_followup_pending_plan_replan_trigger(
    request: Mapping[str, Any],
    step: Mapping[str, Any],
    event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    runtime_stage = str(
        request.get("runtime_stage") or step.get("runtime_stage") or ""
    ).strip()
    runtime_role = str(
        request.get("runtime_role") or step.get("runtime_role") or ""
    ).strip()
    if (
        result.get("verification_failed") is True
        or runtime_stage == "verify"
        or runtime_role == "verify_result"
    ):
        return "verification_failed"
    haystack = " ".join(
        [
            str(event.get("event") or ""),
            str(event.get("detail") or ""),
            str(result.get("error") or ""),
            str(result.get("hint") or ""),
            str(result.get("summary") or ""),
            str(result.get("stderr") or ""),
        ]
    ).lower()
    if any(
        marker in haystack
        for marker in (
            "unavailable",
            "not available",
            "not allowed",
            "not enabled",
            "missing permission",
            "missing tool",
        )
    ):
        return "tool_unavailable"
    return "tool_failure"


def _model_followup_pending_plan_failure_detail(
    event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    parts = [
        str(result.get("error") or "").strip(),
        str(result.get("hint") or "").strip(),
        str(result.get("summary") or "").strip(),
        str(result.get("stderr") or "").strip()[:500],
        str(result.get("stdout") or "").strip()[:500],
    ]
    for part in parts:
        if part:
            return part
    exit_code = result.get("exit_code", result.get("returncode"))
    if exit_code not in (None, "", 0, "0"):
        return f"{str(event.get('detail') or 'tool').strip()} exited with {exit_code}"
    return str(event.get("detail") or event.get("event") or "tool failure").strip()


def _model_followup_request_input_preview(
    request: Mapping[str, Any],
    event: Mapping[str, Any],
) -> dict[str, Any]:
    input_preview = (
        event.get("input_preview")
        if isinstance(event.get("input_preview"), Mapping)
        else {}
    )
    if input_preview:
        return dict(input_preview)
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    return dict(request_input)


def _model_followup_pending_plan_replan_condition(trigger: str) -> str:
    if trigger == "verification_failed":
        return "Pending verification step failed."
    if trigger == "tool_unavailable":
        return "Pending plan tool was unavailable or blocked by missing capability."
    return "Pending plan tool failed."


def _model_followup_pending_plan_replan_reason(
    trigger: str,
    *,
    source_step_id: str,
    source_tool_name: str,
) -> str:
    target = source_step_id or source_tool_name or "pending step"
    if trigger == "verification_failed":
        return f"Runtime requested a replan after verification failed for {target}."
    if trigger == "tool_unavailable":
        return f"Runtime requested a replan because a required tool was unavailable for {target}."
    return f"Runtime requested a replan after a failed pending step: {target}."


def _model_followup_default_replan_fallback_tools(
    tool_name: str,
    *,
    trigger: str,
    capability_id: str,
) -> list[str]:
    if trigger == "verification_failed" or tool_name == "terminal.run":
        return ["workspace.read", "workspace.write_patch", "terminal.run"]
    if tool_name.startswith("app.") or tool_name.startswith("desktop."):
        return ["screen.capture", "desktop.read_ui", "desktop.active_window"]
    if capability_id.startswith("data."):
        return ["workspace.read", "data.analyze", "artifact.write"]
    return []


def _model_followup_task_core_replan_context(
    followup_context: Mapping[str, Any],
    source_step_id: str,
    *,
    matched_step_id: str = "",
) -> dict[str, Any]:
    task_core = (
        followup_context.get("task_core")
        if isinstance(followup_context.get("task_core"), Mapping)
        else {}
    )
    if not task_core:
        return {}
    workspace = (
        task_core.get("workspace")
        if isinstance(task_core.get("workspace"), Mapping)
        else {}
    )
    plan_step = str(matched_step_id or source_step_id or "").strip()
    context: dict[str, Any] = {
        "core_id": str(task_core.get("core_id") or "").strip(),
        "workspace_id": str(workspace.get("workspace_id") or "").strip(),
        "workspace_title": str(workspace.get("title") or "").strip(),
        "source_step_id": str(source_step_id or "").strip(),
        "planner_step_id": plan_step,
    }
    workspace_items = _model_followup_task_core_context_rows(
        workspace.get("items") if isinstance(workspace.get("items"), list) else [],
        step_key="source_step_id",
        step_id=plan_step,
        keys=("item_id", "title", "kind", "path", "status", "source_step_id"),
        limit=8,
    )
    todos = _model_followup_task_core_context_rows(
        task_core.get("todos") if isinstance(task_core.get("todos"), list) else [],
        step_key="step_id",
        step_id=plan_step,
        keys=(
            "todo_id",
            "title",
            "status",
            "step_id",
            "tool_name",
            "capability_id",
            "approval_required",
        ),
        limit=8,
    )
    checkpoints = _model_followup_task_core_context_rows(
        task_core.get("checkpoints")
        if isinstance(task_core.get("checkpoints"), list)
        else [],
        step_key="after_step_id",
        step_id=plan_step,
        keys=("checkpoint_id", "title", "status", "after_step_id", "verifies"),
        limit=5,
    )
    replan_signals = _model_followup_task_core_context_rows(
        task_core.get("replan_signals")
        if isinstance(task_core.get("replan_signals"), list)
        else [],
        step_key="source_step_id",
        step_id=plan_step,
        keys=("signal_id", "trigger", "source_step_id", "target", "fallback_tools"),
        limit=5,
    )
    if workspace_items:
        context["workspace_items"] = workspace_items
    if todos:
        context["todos"] = todos
    if checkpoints:
        context["checkpoints"] = checkpoints
    if replan_signals:
        context["replan_signals"] = replan_signals
    return {key: value for key, value in context.items() if value not in ("", [], {})}


def _model_followup_task_core_context_rows(
    values: Iterable[Any],
    *,
    step_key: str,
    step_id: str,
    keys: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        if step_id and str(value.get(step_key) or value.get("step_id") or "").strip() != step_id:
            continue
        row = {
            key: value.get(key)
            for key in keys
            if value.get(key) not in (None, "", [], {})
        }
        if row:
            rows.append(dict(row))
        if len(rows) >= limit:
            break
    return rows


def _model_followup_pending_plan_replan_prompt(
    payload: Mapping[str, Any],
    task_context: Mapping[str, Any],
) -> str:
    parts = [
        "Runtime replan request:",
        f"- trigger: {payload.get('trigger')}",
    ]
    for label, key in (
        ("failed_step", "source_step_id"),
        ("failed_tool", "source_tool_name"),
        ("target_capability", "target_capability_id"),
        ("failure_detail", "failure_detail"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            parts.append(f"- {label}: {value}")
    fallback_tools = _string_list(payload.get("fallback_tools"))
    if fallback_tools:
        parts.append(f"- preferred_fallback_tools: {', '.join(fallback_tools)}")
    if task_context:
        parts.append("- task_workspace: continue from existing task_core_context")
    parts.append(
        "Continue from the existing task workspace; do not restart completed steps."
    )
    return "\n".join(parts)


def _model_followup_replan_stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _model_followup_completed_step_ids(
    completed_tool_requests: Iterable[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> set[str]:
    completed: set[str] = set()
    for request in completed_tool_requests:
        if not isinstance(request, Mapping):
            continue
        if not _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        ):
            continue
        step_id = str(
            request.get("step_id") or request.get("planner_step_id") or ""
        ).strip()
        if step_id:
            completed.add(step_id)
    return completed


def _model_followup_last_completed_step_index(
    completed_tool_requests: Iterable[Mapping[str, Any]],
    steps: list[Mapping[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> int:
    last_index = -1
    for request in completed_tool_requests:
        if not isinstance(request, Mapping):
            continue
        if not _runtime_planner_tool_request_completed(
            request,
            timeline,
            tool_timeline_start=tool_timeline_start,
        ):
            continue
        step_index, _step = _next_matching_model_followup_pending_step(
            request,
            steps,
            start_index=0,
        )
        if step_index >= 0:
            last_index = max(last_index, step_index)
    return last_index


def _model_followup_completed_step_ids_from_timeline(
    timeline: list[dict[str, Any]],
    steps: list[Mapping[str, Any]],
) -> set[str]:
    known_steps = {
        str(step.get("step_id") or "").strip()
        for step in steps
        if str(step.get("step_id") or "").strip()
    }
    if not known_steps:
        return set()
    completed: set[str] = set()
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        step_id = str(event.get("step_id") or event.get("planner_step_id") or "").strip()
        if not step_id or step_id not in known_steps:
            continue
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if event_type in {
            "agent.task.todo.updated",
            "agent.task.checkpoint.updated",
            "agent.task.workspace_item.updated",
        } and str(event.get("status") or "").strip() == "completed":
            completed.add(step_id)
            continue
        if event_type != "agent.tool.call":
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is True and not result.get("approval_required"):
            completed.add(step_id)
    return completed


def _attach_model_followup_pending_plan_trace_metadata(
    request: dict[str, Any],
    step: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> None:
    for key in (
        "request_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "core_id",
        "workspace_id",
        "task_id",
        "run_id",
        "replan_request_id",
        "replan_trigger",
    ):
        value = str(
            request.get(key)
            or step.get(key)
            or followup_context.get(key)
            or ""
        ).strip()
        if value:
            request[key] = value
    if str(request.get("step_id") or "").strip() and not str(
        request.get("planner_step_id") or ""
    ).strip():
        request["planner_step_id"] = str(request.get("step_id") or "").strip()
    for key in _RUNTIME_ORCHESTRATION_SCOPE_KEYS:
        if key in request:
            continue
        value = str(step.get(key) or followup_context.get(key) or "").strip()
        if value:
            request[key] = value
    for key in (
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "requires_observation",
        "requires_post_action_verification",
    ):
        if key in request:
            continue
        value = step.get(key)
        if value not in (None, "", [], {}):
            request[key] = value
    for key in (
        "task_todo",
        "task_checkpoints",
        "task_workspace_items",
        "task_verification_targets",
    ):
        if key in request:
            continue
        value = step.get(key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
        elif isinstance(value, list) and value:
            request[key] = [dict(item) for item in value if isinstance(item, Mapping)]


def _pending_plan_request_with_timeline_resolved_app(
    request: dict[str, Any],
    step: Mapping[str, Any],
    followup_context: Mapping[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    request_input = (
        dict(request.get("input"))
        if isinstance(request.get("input"), Mapping)
        else {}
    )
    step_input = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    raw_app_name = str(
        request_input.get("app_name")
        or step_input.get("app_name")
        or request.get("target_app_name")
        or ""
    ).strip()
    if raw_app_name and not _runtime_planner_placeholder_app_name(raw_app_name):
        return request
    if not raw_app_name and "app_name" not in request_input and "app_name" not in step_input:
        return request

    followup_target = (
        followup_context.get("followup_target")
        if isinstance(followup_context.get("followup_target"), Mapping)
        else {}
    )
    app_query = str(
        request_input.get("query")
        or request_input.get("app_query")
        or step_input.get("query")
        or step_input.get("app_query")
        or request.get("target_app_query")
        or followup_target.get("app_query")
        or followup_target.get("target_app_query")
        or ""
    ).strip()
    discovered = _discovered_app_name_for_query(timeline, app_query) if app_query else ""
    if not discovered:
        discovered = _latest_replan_context_app_name(
            timeline,
            request_id=str(request.get("replan_request_id") or "").strip(),
        )
    if not discovered or _runtime_planner_placeholder_app_name(discovered):
        return request

    resolved = dict(request)
    tool_name = str(resolved.get("tool") or resolved.get("tool_name") or "").strip()
    if tool_name.startswith("app.") or raw_app_name:
        request_input["app_name"] = discovered
    for key in ("selection_source", "app_selection_source", "query", "app_query"):
        request_input.pop(key, None)
    resolved["input"] = request_input
    resolved["target_app_name"] = discovered
    if app_query:
        resolved["target_app_query"] = app_query
    for key in ("followup_target", "action_target"):
        nested = resolved.get(key) if isinstance(resolved.get(key), Mapping) else {}
        if not nested:
            continue
        item = dict(nested)
        nested_app_name = str(item.get("app_name") or item.get("target_app_name") or "").strip()
        if not nested_app_name or _runtime_planner_placeholder_app_name(nested_app_name):
            item["app_name"] = discovered
            if "target_app_name" in item:
                item["target_app_name"] = discovered
        if app_query:
            if key == "followup_target" or "app_query" in item:
                item["app_query"] = app_query
            if "target_app_query" in item:
                item["target_app_query"] = app_query
        resolved[key] = item
    if app_query and (tool_name.startswith("app.") or raw_app_name):
        resolved = _with_discovered_app_resolution(resolved, app_query, discovered)
    return resolved


def _model_followup_requests_with_pending_plan_metadata(
    requests: list[dict[str, Any]],
    followup_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not requests or not isinstance(followup_context, Mapping):
        return requests
    raw_steps = _model_followup_pending_trace_items(followup_context)
    if not raw_steps:
        return requests
    steps = [step for step in raw_steps if isinstance(step, Mapping)]
    if not steps:
        return requests
    annotated: list[dict[str, Any]] = []
    cursor = 0
    for request in requests:
        if not isinstance(request, dict):
            continue
        item = dict(request)
        step_index, step = _next_matching_model_followup_pending_step(
            item,
            steps,
            start_index=cursor,
        )
        if step_index >= 0 and step:
            cursor = step_index + 1
            _attach_model_followup_pending_plan_trace_metadata(
                item,
                step,
                followup_context,
            )
            if not str(item.get("step_id") or "").strip():
                step_id = str(step.get("step_id") or "").strip()
                if step_id:
                    item["step_id"] = step_id
            if not str(item.get("capability_id") or "").strip():
                capability_id = str(step.get("capability_id") or "").strip()
                if capability_id:
                    item["capability_id"] = capability_id
            if str(item.get("step_id") or "").strip() and not str(
                item.get("planner_step_id") or ""
            ).strip():
                item["planner_step_id"] = str(item.get("step_id") or "").strip()
            item = _resolve_dynamic_pending_plan_request_input(
                item,
                step,
                followup_context,
            )
        annotated.append(item)
    return annotated


def _model_followup_pending_trace_items(
    followup_context: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    pending_execution_requests = followup_context.get("pending_execution_requests")
    if isinstance(pending_execution_requests, list):
        return [
            request
            for request in pending_execution_requests
            if isinstance(request, Mapping)
        ]
    pending_plan_steps = followup_context.get("pending_plan_steps")
    if isinstance(pending_plan_steps, list):
        return [step for step in pending_plan_steps if isinstance(step, Mapping)]
    return _model_followup_task_core_pending_trace_items(followup_context)


def _model_followup_task_core_pending_trace_items(
    followup_context: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    task_core = (
        followup_context.get("task_core")
        if isinstance(followup_context.get("task_core"), Mapping)
        else {}
    )
    if not task_core:
        return []
    workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
    workspace_id = str(workspace.get("workspace_id") or "").strip()
    workspace_items = workspace.get("items") if isinstance(workspace.get("items"), list) else []
    items_by_step: dict[str, list[Mapping[str, Any]]] = {}
    for item in workspace_items:
        if not isinstance(item, Mapping):
            continue
        step_id = str(item.get("source_step_id") or "").strip()
        if step_id:
            items_by_step.setdefault(step_id, []).append(item)
    checkpoints_by_step: dict[str, list[Mapping[str, Any]]] = {}
    for checkpoint in task_core.get("checkpoints", []):
        if not isinstance(checkpoint, Mapping):
            continue
        step_id = str(checkpoint.get("after_step_id") or checkpoint.get("step_id") or "").strip()
        if step_id:
            checkpoints_by_step.setdefault(step_id, []).append(checkpoint)
    items: list[Mapping[str, Any]] = []
    for todo in task_core.get("todos", []):
        if not isinstance(todo, Mapping):
            continue
        status = str(todo.get("status") or "").strip()
        if status not in {"", "pending", "planned", "waiting_approval"}:
            continue
        step_id = str(todo.get("step_id") or "").strip()
        if not step_id:
            continue
        workspace_step_items = items_by_step.get(step_id, [])
        metadata = _model_followup_task_core_step_metadata(todo, workspace_step_items)
        tool_name = str(todo.get("tool_name") or metadata.get("tool_name") or "").strip()
        if not tool_name:
            continue
        input_preview = (
            metadata.get("input_preview")
            if isinstance(metadata.get("input_preview"), Mapping)
            else {}
        )
        payload: dict[str, Any] = {
            "step_id": step_id,
            "tool_name": tool_name,
            "capability_id": str(
                todo.get("capability_id") or metadata.get("capability_id") or ""
            ).strip(),
            "input_preview": dict(input_preview),
            "status": status or "pending",
            "task_todo": dict(todo),
        }
        for key in (
            "runtime_doctrine",
            "runtime_stage",
            "runtime_role",
            "requires_observation",
            "requires_post_action_verification",
        ):
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                payload[key] = value
        if bool(todo.get("approval_required")) or bool(metadata.get("approval_required")):
            payload["approval_required"] = True
        if workspace_step_items:
            payload["task_workspace_items"] = [dict(item) for item in workspace_step_items]
        checkpoints = checkpoints_by_step.get(step_id, [])
        if checkpoints:
            payload["task_checkpoints"] = [dict(item) for item in checkpoints]
        if workspace_id:
            payload["workspace_id"] = workspace_id
        core_id = str(task_core.get("core_id") or "").strip()
        if core_id:
            payload["core_id"] = core_id
        for key in _RUNTIME_ORCHESTRATION_SCOPE_KEYS:
            value = str(followup_context.get(key) or "").strip()
            if value:
                payload[key] = value
        items.append(payload)
        if len(items) >= _MODEL_FOLLOWUP_MAX_AUTO_PENDING_REQUESTS:
            break
    return items


def _model_followup_task_core_step_metadata(
    todo: Mapping[str, Any],
    workspace_items: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any]:
    todo_metadata = todo.get("metadata") if isinstance(todo.get("metadata"), Mapping) else {}
    for item in workspace_items:
        if not isinstance(item, Mapping):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        if metadata:
            return {**dict(todo_metadata), **dict(metadata)}
    return dict(todo_metadata)


def _next_matching_model_followup_pending_step(
    request: Mapping[str, Any],
    steps: list[Mapping[str, Any]],
    *,
    start_index: int = 0,
) -> tuple[int, Mapping[str, Any] | None]:
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return -1, None
    for index in range(max(0, start_index), len(steps)):
        step = steps[index]
        if str(step.get("tool_name") or "").strip() != tool_name:
            continue
        if not _model_followup_request_matches_pending_step(request, step):
            continue
        return index, step
    return -1, None


def _model_followup_request_matches_pending_step(
    request: Mapping[str, Any],
    step: Mapping[str, Any],
) -> bool:
    step_input = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    step_path = str(
        step_input.get("path")
        or step_input.get("artifact_path")
        or step_input.get("target_path")
        or ""
    ).strip()
    request_path = str(
        request_input.get("path")
        or request_input.get("artifact_path")
        or request_input.get("target_path")
        or ""
    ).strip()
    if step_path and request_path and step_path != request_path:
        return False
    return True


def _model_followup_pending_plan_request(
    step: Mapping[str, Any],
    allowed: set[str],
    *,
    planning_reason: str,
    generated_content: str = "",
    followup_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tool_name = str(step.get("tool_name") or "").strip()
    if (
        not tool_name
        or tool_name not in allowed
        or tool_name not in _MODEL_FOLLOWUP_AUTO_PENDING_TOOLS
    ):
        return {}
    raw_input = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    input_resolution: dict[str, Any] = {}
    if tool_name == "terminal.run":
        input_payload = _model_followup_terminal_pending_input(
            raw_input,
            generated_content,
        )
        if not input_payload:
            return {}
        if input_resolution:
            input_resolution["tool"] = tool_name
    elif tool_name in _OPEN_PATH_WITH_APP_TOOLS:
        input_payload, input_resolution = _model_followup_open_path_with_app_pending_input(
            raw_input,
            followup_context or {},
        )
        if not input_payload:
            return {}
    elif tool_name == "artifact.write":
        input_payload = _model_followup_artifact_pending_input(
            raw_input,
            generated_content,
            followup_context or {},
        )
        if not input_payload:
            return {}
    elif tool_name == "clipboard.write":
        input_payload = _model_followup_clipboard_pending_input(
            raw_input,
            generated_content,
        )
        if not input_payload:
            return {}
    elif tool_name == "data.analyze":
        input_payload = _model_followup_data_analyze_pending_input(
            raw_input,
            followup_context or {},
        )
        if not input_payload:
            return {}
    elif tool_name in _MODEL_FOLLOWUP_TEXT_ENTRY_TOOLS:
        input_payload, input_resolution = _model_followup_text_entry_pending_input(
            tool_name,
            raw_input,
            generated_content,
            followup_context or {},
        )
        if not input_payload:
            return {}
    else:
        if not raw_input and tool_name not in {
            "desktop.active_window",
            "desktop.read_ui",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
            "screen.capture",
        }:
            return {}
        input_payload = dict(raw_input)
        input_payload, input_resolution = _model_followup_resolved_app_input(
            tool_name,
            input_payload,
            raw_input,
            followup_context or {},
        )
    request = _request_like(
        tool_name,
        input_payload,
        source="runtime_planner",
        planning_reason=planning_reason or "planner_followup_pending_plan",
    )
    step_id = str(step.get("step_id") or "").strip()
    if step_id:
        request["step_id"] = step_id
    capability_id = str(step.get("capability_id") or "").strip()
    if capability_id:
        request["capability_id"] = capability_id
    if input_resolution:
        input_resolution["tool"] = tool_name
        request["input_resolution"] = input_resolution
    return request


def _model_followup_open_path_with_app_pending_input(
    raw_input: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw_input, Mapping):
        raw_input = {}
    app_name = str(raw_input.get("app_name") or "").strip()
    path = str(raw_input.get("path") or raw_input.get("target_path") or "").strip()
    app_resolution: dict[str, Any] = {}
    if _pending_plan_placeholder_value(path, "workspace.list"):
        path = _resolved_followup_workspace_path(followup_context, raw_input)
    if _pending_plan_placeholder_value(app_name, "desktop.list_apps"):
        app_name, app_resolution = _resolved_followup_desktop_app_name(
            followup_context,
            raw_input,
        )
    if (
        not path
        or not app_name
        or _pending_plan_placeholder_value(path, "workspace.list")
        or _pending_plan_placeholder_value(app_name, "desktop.list_apps")
    ):
        return {}, {}
    return {"path": path, "app_name": app_name}, app_resolution


def _pending_plan_placeholder_value(value: Any, source: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return (
        (text.startswith("<") and text.endswith(">"))
        or source.lower() in lowered
    )


_MODEL_FOLLOWUP_TEXT_ENTRY_TOOLS = {
    "app.focus_and_safe_type_text",
    "app.open_and_safe_type_text",
    "desktop.safe_type_text",
    "desktop.type",
    "desktop.type_text",
}

_MODEL_FOLLOWUP_SNAPSHOT_BODY_SOURCES = {
    "analysis_artifact",
    "analysis_result",
    "artifact",
    "artifact_content",
    "data_analysis",
    "report_artifact",
}

_MODEL_FOLLOWUP_SNAPSHOT_BODY_SOURCE_TOOLS = {
    "artifact.write",
    "data.analyze",
}


def _model_followup_text_entry_pending_input(
    tool_name: str,
    raw_input: Mapping[str, Any],
    generated_content: str,
    followup_context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw_input, Mapping):
        raw_input = {}
    content = _model_followup_resolved_body_content(
        generated_content,
        raw_input,
        followup_context,
    )
    if not content:
        return {}, {}
    payload: dict[str, Any] = {"text": content}
    input_resolution: dict[str, Any] = {}
    if tool_name in {"app.focus_and_safe_type_text", "app.open_and_safe_type_text"}:
        app_name = str(raw_input.get("app_name") or "").strip()
        if not app_name or _pending_plan_placeholder_value(app_name, "desktop.list_apps"):
            payload, input_resolution = _model_followup_resolved_app_input(
                tool_name,
                payload,
                raw_input,
                followup_context,
            )
            app_name = str(payload.get("app_name") or "").strip()
        if not app_name or _pending_plan_placeholder_value(app_name, "desktop.list_apps"):
            return {}, {}
        payload["app_name"] = app_name
    return payload, input_resolution


def _model_followup_resolved_app_input(
    tool_name: str,
    input_payload: Mapping[str, Any],
    raw_input: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(input_payload) if isinstance(input_payload, Mapping) else {}
    source = dict(raw_input) if isinstance(raw_input, Mapping) else {}
    if "app_name" not in payload and "app_name" not in source:
        return payload, {}
    app_name = str(payload.get("app_name") or source.get("app_name") or "").strip()
    if not _pending_plan_placeholder_value(app_name, "desktop.list_apps"):
        return payload, {}
    resolved_app_name, input_resolution = _resolved_followup_desktop_app_name(
        followup_context,
        {**source, **payload},
    )
    if not resolved_app_name:
        return payload, {}
    payload["app_name"] = resolved_app_name
    if input_resolution:
        input_resolution["tool"] = str(tool_name or "").strip()
    return payload, input_resolution


def _model_followup_resolved_body_content(
    generated_content: str,
    source: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> str:
    if not isinstance(source, Mapping):
        source = {}
    direct = str(source.get("content") or source.get("text") or "").strip()
    if direct and not _pending_plan_placeholder_value(direct, "captured"):
        return direct
    body_source = str(source.get("body_source") or "").strip()
    snapshot_content = _model_followup_snapshot_body_content(
        followup_context,
        body_source,
    )
    if snapshot_content and body_source in _MODEL_FOLLOWUP_SNAPSHOT_BODY_SOURCES:
        return snapshot_content
    content = str(generated_content or "").strip()
    if content:
        return content
    return snapshot_content


def _model_followup_snapshot_body_content(
    followup_context: Mapping[str, Any],
    body_source: str,
) -> str:
    source = str(body_source or "").strip()
    if source not in _MODEL_FOLLOWUP_SNAPSHOT_BODY_SOURCES:
        return ""
    snapshots = _model_followup_readable_content_snapshots(followup_context)
    for snapshot in reversed(snapshots):
        source_tool = str(snapshot.get("source_tool") or "").strip()
        if source_tool not in _MODEL_FOLLOWUP_SNAPSHOT_BODY_SOURCE_TOOLS:
            continue
        text = str(snapshot.get("text") or "").strip()
        if text:
            return text
    return ""


def _model_followup_readable_content_snapshots(
    followup_context: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    if not isinstance(followup_context, Mapping):
        return []
    snapshots: list[Mapping[str, Any]] = []
    raw_snapshots = followup_context.get("content_snapshots")
    if isinstance(raw_snapshots, list):
        snapshots.extend(snapshot for snapshot in raw_snapshots if isinstance(snapshot, Mapping))
    raw_snapshot = followup_context.get("content_snapshot")
    if isinstance(raw_snapshot, Mapping):
        snapshots.append(raw_snapshot)
    return [
        snapshot
        for snapshot in snapshots
        if snapshot.get("ok") is not False and str(snapshot.get("text") or "").strip()
    ]


def _resolved_followup_workspace_path(
    followup_context: Mapping[str, Any],
    raw_input: Mapping[str, Any],
) -> str:
    for snapshot in reversed(_followup_snapshots_for_tool(followup_context, "workspace.list")):
        entries = snapshot.get("entries")
        if not isinstance(entries, list) or not entries:
            continue
        entry = _select_followup_workspace_entry(entries, raw_input)
        if not entry:
            continue
        path = str(entry.get("path") or "").strip()
        if path:
            return path
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        return _join_followup_workspace_path(str(snapshot.get("path") or ""), name)
    return ""


def _resolved_followup_desktop_app_name(
    followup_context: Mapping[str, Any],
    raw_input: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    for snapshot in reversed(_followup_snapshots_for_tool(followup_context, "desktop.list_apps")):
        apps = snapshot.get("apps")
        if not isinstance(apps, list) or not apps:
            continue
        app = _select_followup_desktop_app(apps)
        app_name = str(app.get("name") or "").strip()
        if not app_name:
            continue
        query = str(
            raw_input.get("query")
            or raw_input.get("app_query")
            or snapshot.get("query")
            or ""
        ).strip()
        resolution: dict[str, Any] = {
            "tool": "desktop.open_path_with_app",
            "field": "app_name",
            "requested_app_name": query or str(raw_input.get("app_name") or "").strip(),
            "resolved_app_name": app_name,
            "source_tool": "desktop.list_apps",
        }
        app_path = str(app.get("path") or "").strip()
        if app_path:
            resolution["resolved_app_path"] = app_path
        score = app.get("match_score") if app.get("match_score") not in (None, "") else app.get("score")
        if score not in (None, ""):
            resolution["app_resolution_score"] = str(score)
        return app_name, {
            key: value
            for key, value in resolution.items()
            if value not in ("", None)
        }
    return "", {}


def _followup_snapshots_for_tool(
    followup_context: Mapping[str, Any],
    source_tool: str,
) -> list[Mapping[str, Any]]:
    snapshots: list[Mapping[str, Any]] = []
    raw_snapshots = followup_context.get("content_snapshots")
    if isinstance(raw_snapshots, list):
        snapshots.extend(snapshot for snapshot in raw_snapshots if isinstance(snapshot, Mapping))
    raw_snapshot = followup_context.get("content_snapshot")
    if isinstance(raw_snapshot, Mapping):
        snapshots.append(raw_snapshot)
    return [
        snapshot
        for snapshot in snapshots
        if str(snapshot.get("source_tool") or "").strip() == source_tool
    ]


def _select_followup_workspace_entry(
    entries: list[Any],
    raw_input: Mapping[str, Any],
) -> Mapping[str, Any]:
    candidates = [entry for entry in entries if isinstance(entry, Mapping)]
    if not candidates:
        return {}
    selection = str(raw_input.get("selection") or "").strip().lower()
    if any(marker in selection for marker in ("largest", "biggest", "最大")):
        return max(
            candidates,
            key=lambda entry: _workspace_entry_size_score(entry, candidates.index(entry)),
        )
    if any(marker in selection for marker in ("last", "最后", "末尾")):
        return candidates[-1]
    if any(
        marker in selection
        for marker in ("recent", "latest", "newest", "最近", "最新", "刚刚")
    ):
        return max(
            candidates,
            key=lambda entry: _workspace_entry_recency_score(entry, candidates.index(entry)),
        )
    return candidates[0]


def _workspace_entry_recency_score(entry: Mapping[str, Any], index: int) -> tuple[float, int, int]:
    numeric_score = 0.0
    for key in ("mtime_ns", "mtime", "modified_at", "score"):
        value = entry.get(key)
        try:
            numeric_score = max(numeric_score, float(value))
        except (TypeError, ValueError):
            pass
    name = str(entry.get("name") or entry.get("path") or "").lower()
    name_score = 0
    for marker, score in (
        ("latest", 30),
        ("newest", 25),
        ("recent", 20),
        ("final", 10),
        ("最新", 30),
        ("最近", 20),
    ):
        if marker in name:
            name_score = max(name_score, score)
    return numeric_score, name_score, -index


def _workspace_entry_size_score(entry: Mapping[str, Any], index: int) -> tuple[float, int]:
    numeric_score = 0.0
    for key in ("size_bytes", "size", "bytes", "file_size"):
        value = entry.get(key)
        try:
            numeric_score = max(numeric_score, float(value))
        except (TypeError, ValueError):
            pass
    return numeric_score, -index


def _select_followup_desktop_app(apps: list[Any]) -> Mapping[str, Any]:
    candidates = [app for app in apps if isinstance(app, Mapping)]
    if not candidates:
        return {}
    return max(candidates, key=_desktop_app_candidate_score)


def _desktop_app_candidate_score(app: Mapping[str, Any]) -> float:
    for key in ("match_score", "score", "confidence"):
        value = app.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _join_followup_workspace_path(base_path: str, name: str) -> str:
    clean_name = str(name or "").strip().strip("/")
    clean_base = str(base_path or "").strip()
    if not clean_name:
        return clean_base
    if not clean_base or clean_base == ".":
        return clean_name
    return posixpath.normpath(posixpath.join(clean_base.rstrip("/"), clean_name))


def _tool_requests_with_pending_plan_metadata(
    tool_requests: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not tool_requests:
        return tool_requests
    followup_context = _latest_model_followup_context(timeline)
    if not followup_context:
        return tool_requests
    tool_requests = _model_followup_requests_with_pending_plan_metadata(
        tool_requests,
        followup_context,
    )
    tool_requests = [
        _explicit_model_tool_request_without_auto_verification(request)
        for request in tool_requests
    ]
    return _model_followup_requests_with_context_trace_metadata(
        tool_requests,
        followup_context,
    )


def _explicit_model_tool_request_without_auto_verification(
    request: dict[str, Any],
) -> dict[str, Any]:
    item = dict(request)
    item.pop("requires_post_action_verification", None)
    return item


def _model_tool_requests_are_verification_recovery_actions(
    requests: Iterable[Mapping[str, Any]],
) -> bool:
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        trigger = str(request.get("replan_trigger") or "").strip()
        triggers = _string_list(request.get("replan_triggers"))
        if trigger == "verification_failed" or "verification_failed" in triggers:
            return True
    return False


def _model_followup_requests_with_context_trace_metadata(
    requests: list[dict[str, Any]],
    followup_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not requests or not isinstance(followup_context, Mapping):
        return requests
    trace = _model_followup_context_trace_metadata(followup_context)
    if not trace:
        return requests
    planning_reason = str(followup_context.get("planning_reason") or "").strip()
    annotated: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        item = dict(request)
        for key, value in trace.items():
            if key in {"replan_triggers", "replan_signal_ids"}:
                values = _ordered_text_list(
                    [*_string_list(item.get(key)), *_string_list(value)]
                )
                if values:
                    item[key] = values
                continue
            if not str(item.get(key) or "").strip():
                item[key] = value
        if planning_reason and not str(item.get("planning_reason") or "").strip():
            item["planning_reason"] = planning_reason
        annotated.append(item)
    return annotated


def _model_followup_context_trace_metadata(
    followup_context: Mapping[str, Any],
) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    replan_request = _first_model_followup_replan_request(followup_context)
    task_core = (
        followup_context.get("task_core")
        if isinstance(followup_context.get("task_core"), Mapping)
        else {}
    )
    workspace = (
        task_core.get("workspace")
        if isinstance(task_core, Mapping) and isinstance(task_core.get("workspace"), Mapping)
        else {}
    )
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "core_id",
        "workspace_id",
        "task_id",
        "run_id",
        "target_app_name",
        "target_app_query",
        "target_search_text",
    ):
        value = str(
            followup_context.get(key)
            or replan_request.get(key)
            or task_core.get(key)
            or workspace.get(key)
            or ""
        ).strip()
        if value:
            trace[key] = value

    request_id = str(
        followup_context.get("replan_request_id")
        or followup_context.get("request_id")
        or replan_request.get("replan_request_id")
        or replan_request.get("request_id")
        or ""
    ).strip()
    if request_id:
        trace["replan_request_id"] = request_id

    trigger = str(
        followup_context.get("replan_trigger")
        or followup_context.get("trigger")
        or replan_request.get("replan_trigger")
        or replan_request.get("trigger")
        or ""
    ).strip()
    if trigger:
        trace["replan_trigger"] = trigger
        trace["replan_triggers"] = _ordered_text_list(
            [*_string_list(followup_context.get("triggers")), trigger]
        )

    target_capability_id = str(
        followup_context.get("capability_id")
        or followup_context.get("target_capability_id")
        or replan_request.get("capability_id")
        or replan_request.get("target_capability_id")
        or ""
    ).strip()
    if target_capability_id:
        trace["capability_id"] = target_capability_id

    if not any(trace.get(key) for key in ("target_app_name", "target_app_query", "target_search_text")):
        recovery_target = _first_model_followup_recovery_target(followup_context)
        for key in ("target_app_name", "target_app_query", "target_search_text"):
            value = str(recovery_target.get(key) or "").strip()
            if value:
                trace[key] = value

    signal_ids = _model_followup_context_replan_signal_ids(followup_context)
    if signal_ids:
        trace["replan_signal_ids"] = signal_ids
    return trace


def _first_model_followup_replan_request(
    followup_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    requests = followup_context.get("replan_requests")
    if not isinstance(requests, list):
        return {}
    for request in requests:
        if isinstance(request, Mapping):
            return request
    return {}


def _first_model_followup_recovery_target(
    followup_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    targets = followup_context.get("recovery_targets")
    if not isinstance(targets, list):
        return {}
    for target in targets:
        if isinstance(target, Mapping):
            return target
    return {}


def _model_followup_context_replan_signal_ids(
    followup_context: Mapping[str, Any],
) -> list[str]:
    signal_ids: list[str] = []
    for key in ("content_snapshots", "recovery_observations"):
        snapshots = followup_context.get(key)
        if not isinstance(snapshots, list):
            continue
        for snapshot in snapshots:
            if isinstance(snapshot, Mapping):
                signal_ids.extend(_string_list(snapshot.get("replan_signal_ids")))
    snapshot = followup_context.get("content_snapshot")
    if isinstance(snapshot, Mapping):
        signal_ids.extend(_string_list(snapshot.get("replan_signal_ids")))
    return _ordered_text_list(signal_ids)

def _resolve_dynamic_pending_plan_request_input(
    request: dict[str, Any],
    step: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    step_input = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    merged_input = {**dict(step_input), **dict(request_input)}
    if tool_name not in _OPEN_PATH_WITH_APP_TOOLS:
        resolved_input, input_resolution = _model_followup_resolved_app_input(
            tool_name,
            request_input,
            merged_input,
            followup_context,
        )
        if not input_resolution:
            return request
        resolved_request = {**request, "input": resolved_input}
        if not isinstance(resolved_request.get("input_resolution"), Mapping):
            resolved_request["input_resolution"] = input_resolution
        return resolved_request
    resolved_input, input_resolution = _model_followup_open_path_with_app_pending_input(
        merged_input,
        followup_context,
    )
    if not resolved_input:
        return request
    resolved_request = {**request, "input": resolved_input}
    if input_resolution:
        input_resolution["tool"] = str(request.get("tool") or "").strip()
    if input_resolution and not isinstance(resolved_request.get("input_resolution"), Mapping):
        resolved_request["input_resolution"] = input_resolution
    return resolved_request


def _model_followup_clipboard_pending_input(
    raw_input: Mapping[str, Any],
    generated_content: str,
) -> dict[str, Any]:
    if not isinstance(raw_input, Mapping):
        raw_input = {}
    text = str(
        raw_input.get("text")
        or raw_input.get("content")
        or generated_content
        or ""
    ).strip()
    if not text:
        return {}
    return {"text": text}


def _model_followup_artifact_pending_input(
    raw_input: Mapping[str, Any],
    generated_content: str,
    followup_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_input, Mapping):
        return {}
    path = str(raw_input.get("path") or "").strip()
    if not path:
        return {}
    content = _model_followup_resolved_body_content(
        generated_content,
        raw_input,
        followup_context or {},
    )
    if not content:
        return {}
    return {"path": path, "content": content}


def _model_followup_data_analyze_pending_input(
    raw_input: Mapping[str, Any],
    followup_context: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_input, Mapping):
        raw_input = {}
    path = str(raw_input.get("path") or "").strip()
    if path and not _pending_plan_placeholder_value(path, "captured"):
        return _data_analyze_pending_input_with_manifest(dict(raw_input), path=path)

    content = str(raw_input.get("content") or "").strip()
    snapshot: Mapping[str, Any] = {}
    if not content or _pending_plan_placeholder_value(content, "captured"):
        snapshot = _latest_data_analysis_followup_snapshot(followup_context)
        content = str(snapshot.get("text") or "").strip()
    if not content:
        return {}

    display_path = str(raw_input.get("display_path") or "").strip()
    if not display_path or _pending_plan_placeholder_value(display_path, "captured"):
        display_path = _captured_data_display_path(dict(snapshot))
    source_kind = str(raw_input.get("source_kind") or "").strip()
    if not source_kind or source_kind == "unknown":
        source_kind = _captured_data_source_kind(content)

    payload = _data_analyze_pending_input_with_manifest(
        dict(raw_input),
        content=content,
        display_path=display_path,
        source_kind=source_kind,
    )
    return payload


def _latest_data_analysis_followup_snapshot(
    followup_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    snapshots: list[Mapping[str, Any]] = []
    raw_snapshots = followup_context.get("content_snapshots")
    if isinstance(raw_snapshots, list):
        snapshots.extend(snapshot for snapshot in raw_snapshots if isinstance(snapshot, Mapping))
    raw_snapshot = followup_context.get("content_snapshot")
    if isinstance(raw_snapshot, Mapping):
        snapshots.append(raw_snapshot)
    for snapshot in reversed(snapshots):
        if str(snapshot.get("source_tool") or "").strip() == "data.analyze":
            continue
        if str(snapshot.get("text") or "").strip():
            return snapshot
    return {}


def _data_analyze_pending_input_with_manifest(
    raw_input: dict[str, Any],
    *,
    path: str = "",
    content: str = "",
    display_path: str = "",
    source_kind: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if path:
        payload["path"] = path
    if content:
        payload["content"] = content
    if display_path:
        payload["display_path"] = display_path
    if source_kind:
        payload["source_kind"] = source_kind

    for key in ("artifact_path",):
        value = str(raw_input.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in ("requested_outputs", "artifact_paths"):
        values = _string_list(raw_input.get(key))
        if values:
            payload[key] = values
    artifact_manifest = raw_input.get("artifact_manifest")
    if isinstance(artifact_manifest, list):
        manifest = [dict(item) for item in artifact_manifest if isinstance(item, Mapping)]
        if manifest:
            payload["artifact_manifest"] = manifest
    max_rows = raw_input.get("max_rows")
    if isinstance(max_rows, int) and not isinstance(max_rows, bool) and max_rows > 0:
        payload["max_rows"] = max_rows
    return payload


def _model_followup_terminal_pending_input(
    raw_input: Mapping[str, Any],
    generated_content: str,
) -> dict[str, Any]:
    if isinstance(raw_input, Mapping):
        command = str(raw_input.get("command") or "").strip()
        if command:
            return _terminal_run_input_payload(raw_input, command)
    command = _terminal_command_from_model_followup_content(generated_content)
    if not command:
        return {}
    payload: dict[str, Any] = {"command": command, "shell": True}
    timeout = raw_input.get("timeout_seconds") if isinstance(raw_input, Mapping) else None
    if isinstance(timeout, int) and not isinstance(timeout, bool) and 1 <= timeout <= 120:
        payload["timeout_seconds"] = timeout
    else:
        payload["timeout_seconds"] = 60
    return payload


def _terminal_run_input_payload(
    raw_input: Mapping[str, Any],
    command: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"command": command}
    timeout = raw_input.get("timeout_seconds")
    if isinstance(timeout, int) and not isinstance(timeout, bool) and 1 <= timeout <= 120:
        payload["timeout_seconds"] = timeout
    shell = raw_input.get("shell")
    if isinstance(shell, bool):
        payload["shell"] = shell
    return payload


_MODEL_FOLLOWUP_TERMINAL_LANGS = {
    "bash",
    "console",
    "fish",
    "sh",
    "shell",
    "shell-session",
    "terminal",
    "zsh",
}


def _terminal_command_from_model_followup_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    for match in re.finditer(r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```", text, flags=re.DOTALL):
        lang = str(match.group("lang") or "").strip().lower()
        lang = re.split(r"\s+", lang, maxsplit=1)[0] if lang else ""
        if lang not in _MODEL_FOLLOWUP_TERMINAL_LANGS:
            continue
        command = _clean_terminal_command_block(match.group("body") or "")
        if _terminal_followup_command_allowed(command):
            return command
    for line in text.splitlines():
        prompt_match = re.match(r"^\s*(?:\$|%)\s+(?P<command>.+?)\s*$", line)
        if not prompt_match:
            continue
        command = str(prompt_match.group("command") or "").strip()
        if _terminal_followup_command_allowed(command):
            return command
    inline_match = re.search(
        r"(?:command|cmd|run|execute|执行|运行|命令)\s*[:：]?\s*`(?P<command>[^`\n]{1,800})`",
        text,
        flags=re.IGNORECASE,
    )
    if inline_match:
        command = str(inline_match.group("command") or "").strip()
        if _terminal_followup_command_allowed(command):
            return command
    return ""


def _clean_terminal_command_block(body: str) -> str:
    lines = str(body or "").strip().splitlines()
    prompt_lines: list[str] = []
    plain_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        prompt_match = re.match(r"^(?:\$|%)\s+(?P<command>.+?)\s*$", stripped)
        if prompt_match:
            prompt_lines.append(str(prompt_match.group("command") or "").strip())
            continue
        if prompt_lines:
            continue
        plain_lines.append(line.rstrip())
    return "\n".join(prompt_lines or plain_lines).strip()


def _terminal_followup_command_allowed(command: str) -> bool:
    clean = str(command or "").strip()
    if not clean or len(clean) > 4000 or "\x00" in clean or "```" in clean:
        return False
    unsafe_patterns = (
        r"(^|[\s;&|])sudo(\s|$)",
        r"(^|[\s;&|])su(\s|$)",
        r"\brm\s+-[^\n]*[rf]",
        r"\brm\s+[^\n]*(?:/\s*$|/\s|~|\*)",
        r"\bdd\s+",
        r"\bmkfs(?:\.|[\s])",
        r"\bdiskutil\s+erase",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bkillall\b",
        r"\bcurl\b[^\n|]*\|\s*(?:sh|bash|zsh)\b",
        r"\bwget\b[^\n|]*\|\s*(?:sh|bash|zsh)\b",
    )
    return not any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in unsafe_patterns)


def _model_followup_app_write_requests(
    generated_content: str,
    target: Mapping[str, Any] | None,
    allowed_tools: Iterable[str],
    *,
    followup_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(target, Mapping):
        return []
    content = _model_followup_resolved_body_content(
        generated_content,
        target,
        followup_context or {},
    )
    if not content:
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
    summary = str(value.get("summary") or "").strip()
    if summary:
        return f"\n\nObserved context summary:\n{summary}\n\n"
    if value.get("ok") is False:
        error_summary = str(value.get("error") or "").strip()
        if error_summary:
            return f"\n\nObservation status: {error_summary}\n\n"
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
    summary = str(value.get("summary") or "").strip()
    if summary:
        return summary
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
    return _first_annotated_auto_followup_request(
        {
            "protocol": "json_fallback",
            "tool": "data.analyze",
            "input": input_payload,
            "source": "runtime_planner",
            "planning_reason": "planner_builtin_data_analysis",
        },
        selection_payload,
    )


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
            and not _is_deferred_observed_ui_request(step)
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


def _daily_desktop_step_has_placeholder_app(
    planned_input: Mapping[str, Any],
    executed_input: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    for source in (executed_input, data):
        value = str(source.get("app_name") or source.get("discovered_app_name") or "").strip()
        if value and not _runtime_planner_placeholder_app_name(value):
            return False
    for source in (planned_input, executed_input, data):
        value = str(source.get("app_name") or source.get("discovered_app_name") or "").strip()
        if value and _runtime_planner_placeholder_app_name(value):
            return True
    return False


def _is_deferred_observed_ui_request(step: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(step, Mapping)
        and str(step.get("deferred_tool") or "").strip()
        and isinstance(step.get("deferred_input"), Mapping)
    )


def _drop_resolved_deferred_observation_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deferred_observations = {
        (
            str(request.get("deferred_tool") or "").strip(),
            _daily_desktop_request_step_id(request),
        )
        for request in requests
        if _is_deferred_observed_ui_request(request)
    }
    if not deferred_observations:
        return requests

    resolved_deferred_steps = {
        (
            str(request.get("tool") or "").strip(),
            _daily_desktop_request_step_id(request),
        )
        for request in requests
        if (
            str(request.get("tool") or "").strip(),
            _daily_desktop_request_step_id(request),
        )
        in deferred_observations
    }
    if not resolved_deferred_steps:
        return requests

    filtered = [
        request
        for request in requests
        if not (
            _is_deferred_observed_ui_request(request)
            and (
                str(request.get("deferred_tool") or "").strip(),
                _daily_desktop_request_step_id(request),
            )
            in resolved_deferred_steps
        )
    ]
    return filtered or requests


def _daily_desktop_request_step_id(request: Mapping[str, Any]) -> str:
    step_id = str(
        request.get("step_id")
        or request.get("planner_step_id")
        or ""
    ).strip()
    if step_id:
        return step_id
    deferred_context = (
        request.get("deferred_context")
        if isinstance(request.get("deferred_context"), Mapping)
        else {}
    )
    return str(
        deferred_context.get("step_id")
        or deferred_context.get("planner_step_id")
        or ""
    ).strip()


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


def _all_noncritical_daily_desktop_observations(
    requests: list[dict[str, Any]],
) -> bool:
    if not requests:
        return False
    for request in requests:
        if not isinstance(request, dict):
            return False
        tool_name = str(request.get("tool") or "").strip()
        if (
            tool_name not in _DAILY_DESKTOP_DISCOVERY_TOOLS
            and tool_name not in _DAILY_DESKTOP_VERIFY_TOOLS
        ):
            return False
    return True


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
    if planning_reason not in {
        "planner_desktop_operation",
        "planner_full_plan_desktop_operation",
    }:
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
    visible_steps = _coalesced_open_focus_find_summary_steps(visible_steps)
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


def _coalesced_open_focus_find_summary_steps(
    visible_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(visible_steps) < 3:
        return visible_steps
    coalesced: list[dict[str, Any]] = []
    index = 0
    while index < len(visible_steps):
        if index + 2 >= len(visible_steps):
            coalesced.append(visible_steps[index])
            index += 1
            continue
        open_step = visible_steps[index]
        focus_step = visible_steps[index + 1]
        shortcut_step = visible_steps[index + 2]
        app_name = _summary_step_app_name(open_step)
        shortcut_action = _summary_step_shortcut_action(shortcut_step)
        shortcut_summary = {
            "find": "打开查找",
            "new_document": "新建文档",
        }.get(shortcut_action, "")
        if (
            str(open_step.get("tool") or "") in {"app.open", "desktop.open_app"}
            and str(focus_step.get("tool") or "") in {"app.focus", "desktop.focus_app"}
            and str(shortcut_step.get("tool") or "") == "desktop.safe_shortcut"
            and app_name
            and _summary_step_app_name(focus_step) == app_name
            and shortcut_summary
        ):
            coalesced.append(
                {
                    **shortcut_step,
                    "tool": "app.open_and_safe_shortcut",
                    "input_preview": {"app_name": app_name, "action": shortcut_action},
                    "summary": f"已打开{_display_target_name(app_name, f'并{shortcut_summary}')}。",
                }
            )
            index += 3
            continue
        coalesced.append(open_step)
        index += 1
    return coalesced


def _summary_step_app_name(step: Mapping[str, Any]) -> str:
    input_preview = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    result = step.get("result") if isinstance(step.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    return str(
        input_preview.get("app_name")
        or data.get("app_name")
        or ""
    ).strip()


def _summary_step_shortcut_action(step: Mapping[str, Any]) -> str:
    input_preview = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    result = step.get("result") if isinstance(step.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    return str(
        input_preview.get("action")
        or data.get("shortcut_action")
        or ""
    ).strip()


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


def _data_analysis_input_from_workspace_entries(
    base_path: str,
    entries: list[Mapping[str, Any]],
    selection: str,
    artifact_paths: list[str],
) -> dict[str, Any]:
    clean_entries = [entry for entry in entries if isinstance(entry, Mapping)]
    if not clean_entries:
        return {}
    if selection in {"all", "multiple"}:
        paths = [
            path
            for entry in clean_entries
            for path in [_workspace_data_entry_path(base_path, entry)]
            if path
        ]
        if not paths or len(paths) > 100:
            return {}
        payload = _data_analysis_base_input_payload(artifact_paths)
        payload["paths"] = paths
        payload["display_path"] = str(base_path or "workspace.list").strip()
        source_kind = _common_data_analysis_file_kind(paths)
        if source_kind:
            payload["source_kind"] = source_kind
        return payload

    selected_entry: Mapping[str, Any] = {}
    if len(clean_entries) == 1:
        selected_entry = clean_entries[0]
    elif selection:
        selected_entry = _select_followup_workspace_entry(
            clean_entries,
            {"selection": selection},
        )
    if not selected_entry:
        return {}
    path = _workspace_data_entry_path(base_path, selected_entry)
    if not path:
        return {}
    payload = _data_analysis_base_input_payload(artifact_paths)
    payload["path"] = path
    source_kind = _data_analysis_file_kind(path) or _data_analysis_file_kind(
        str(selected_entry.get("name") or "")
    )
    if source_kind:
        payload["source_kind"] = source_kind
    return payload


def _data_analysis_base_input_payload(artifact_paths: list[str]) -> dict[str, Any]:
    return {
        "artifact_path": artifact_paths[0],
        "requested_outputs": _requested_outputs_from_artifact_paths(artifact_paths),
        "artifact_manifest": _artifact_manifest_from_paths(artifact_paths),
    }


def _workspace_data_entry_path(base_path: str, entry: Mapping[str, Any]) -> str:
    path = str(entry.get("path") or "").strip()
    if path:
        return path
    name = str(entry.get("name") or "").strip()
    if not name:
        return ""
    return _join_workspace_list_path(base_path, name)


def _common_data_analysis_file_kind(paths: list[str]) -> str:
    kinds = {
        kind
        for path in paths
        for kind in [_data_analysis_file_kind(path)]
        if kind
    }
    if len(kinds) == 1:
        return next(iter(kinds))
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
