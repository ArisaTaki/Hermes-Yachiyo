"""Shared Runtime debug summary projection for Chat and Agent Studio."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import RuntimeDebugSummarySnapshot

_TERMINAL_RUNTIME_REQUEST_STATUSES = {
    "blocked",
    "cancelled",
    "canceled",
    "completed",
    "denied",
    "expired",
    "failed",
    "rejected",
    "recovered",
    "skipped",
}

_WAITING_RUNTIME_REQUEST_STATUSES = {
    "approval_required",
    "waiting",
    "waiting_approval",
    "waiting_user",
}


def runtime_debug_summary_from_runtime_objects(
    *,
    run_id: str = "",
    task_id: str = "",
    group_id: str = "",
    group_run_id: str = "",
    workflow_id: str = "",
    workflow_run_id: str = "",
    events: Iterable[Any] | None = None,
    tool_calls: Iterable[Any] | None = None,
    approvals: Iterable[Any] | None = None,
    pending_approval: Any | None = None,
    artifacts: Iterable[Any] | None = None,
    memory_traces: Iterable[Any] | None = None,
    skill_traces: Iterable[Any] | None = None,
    children: Iterable[Any] | None = None,
    replan_recoveries: Iterable[Any] | None = None,
    planner_summary: Any | None = None,
    runtime_execution_envelope: Any | None = None,
    task_core: Any | None = None,
    task_progress: Any | None = None,
    needs_user_action: bool = False,
    needs_replan: bool = False,
) -> RuntimeDebugSummarySnapshot:
    event_items = _items(events)
    tool_items = _items(tool_calls)
    approval_items = _approval_items(approvals, pending_approval)
    artifact_items = _items(artifacts)
    memory_items = _items(memory_traces)
    skill_items = _items(skill_traces)
    child_items = _items(children)
    replan_items = _items(replan_recoveries)
    event_planner_summary = _planner_summary_from_events(event_items)

    tool_statuses = [_text(_field(item, "status")) for item in tool_items]
    pending_approvals = [
        item for item in approval_items if _text(_field(item, "status")) == "pending"
    ]
    latest_event = event_items[-1] if event_items else None
    latest_tool = _latest_tool_context(tool_items)
    latest_approval = pending_approvals[-1] if pending_approvals else (
        approval_items[-1] if approval_items else None
    )
    latest_artifact = artifact_items[-1] if artifact_items else None
    request_items = _items(_field(runtime_execution_envelope, "requests"))
    latest_request = request_items[-1] if request_items else None
    latest_replan = replan_items[-1] if replan_items else None
    latest_recovery_actions = _recovery_actions(latest_replan)
    latest_recovery_action = _preferred_recovery_action(latest_recovery_actions)
    effective_task_core = _richer_task_core(
        task_core,
        _field(runtime_execution_envelope, "task_core"),
    )
    effective_task_progress = _richer_task_progress(
        task_progress,
        _field(runtime_execution_envelope, "task_progress"),
    )
    plan_tools = _planner_tools(
        planner_summary,
        runtime_execution_envelope,
        event_planner_summary,
    )
    plan_capabilities = _planner_capabilities(
        planner_summary,
        runtime_execution_envelope,
        event_planner_summary,
    )
    runtime_stage_counts = _runtime_stage_counts(runtime_execution_envelope)
    task_totals = _task_totals(effective_task_core, effective_task_progress)
    current_step_id = _optional_text(_field(effective_task_progress, "current_step_id"))
    current_step_title = _optional_text(_field(effective_task_progress, "current_step_title"))
    current_tool_name = _optional_text(_field(effective_task_progress, "current_tool_name"))
    current_request = _matching_runtime_request(
        request_items,
        step_id=current_step_id,
        tool_name=current_tool_name,
    ) or _active_runtime_request(request_items)
    desktop_provider_session = _desktop_provider_session(
        runtime_execution_envelope,
        request_items,
        event_items,
    )
    desktop_provider_context_items = _desktop_provider_context_items(
        runtime_execution_envelope,
        request_items,
        desktop_provider_session,
    )
    desktop_provider_contract = _desktop_provider_contract(
        desktop_provider_context_items
    )
    desktop_provider_conformance = _desktop_provider_conformance(
        desktop_provider_context_items
    )
    desktop_execution_session_mode = _desktop_execution_session_mode(
        runtime_execution_envelope,
        request_items,
        desktop_provider_session,
    )
    deferred_continuation_events = _deferred_continuation_events(event_items)
    latest_deferred_continuation_tool = _latest_deferred_continuation_tool(
        deferred_continuation_events
    )
    request_statuses = [_text(_field(item, "status")) for item in request_items]
    runtime_context_items = [
        latest_tool,
        latest_approval,
        current_request,
        latest_request,
        runtime_execution_envelope,
    ]

    debug_surfaces = _debug_surfaces(
        event_items=event_items,
        tool_items=tool_items,
        approval_items=approval_items,
        artifact_items=artifact_items,
        memory_items=memory_items,
        skill_items=skill_items,
        child_items=child_items,
        replan_items=replan_items,
        deferred_continuation_items=deferred_continuation_events,
        planner_items=[
            item
            for item in (
                planner_summary,
                runtime_execution_envelope,
                event_planner_summary,
            )
            if item
        ],
        task_items=[item for item in (effective_task_core, effective_task_progress) if item is not None],
        provider_session=desktop_provider_session,
    )
    replan_needed = (
        needs_replan
        or _desktop_provider_session_needs_replan(desktop_provider_session)
        or any(_replan_item_needs_replan(item) for item in replan_items)
        or _events_have_unresolved_replan(event_items)
    )

    return RuntimeDebugSummarySnapshot(
        run_id=_optional_text(run_id),
        task_id=_optional_text(task_id),
        group_id=_optional_text(group_id),
        group_run_id=_optional_text(group_run_id),
        workflow_id=_optional_text(workflow_id),
        workflow_run_id=_optional_text(workflow_run_id),
        planner_decision_id=_optional_text(
            _field(planner_summary, "decision_id")
            or _field(runtime_execution_envelope, "decision_id")
            or _field(event_planner_summary, "decision_id")
        ),
        planner_plan_id=_optional_text(
            _field(planner_summary, "plan_id")
            or _field(runtime_execution_envelope, "plan_id")
            or _field(event_planner_summary, "plan_id")
        ),
        intent_kind=_optional_text(
            _field(planner_summary, "intent_kind")
            or _field(runtime_execution_envelope, "intent_kind")
            or _field(event_planner_summary, "intent_kind")
        ),
        intent_title=_optional_text(
            _field(planner_summary, "intent_title")
            or _field(event_planner_summary, "intent_title")
        ),
        route_to_studio=_optional_bool(
            _field(planner_summary, "route_to_studio"),
            _field(runtime_execution_envelope, "route_to_studio"),
            _field(event_planner_summary, "route_to_studio"),
        ),
        task_status=_optional_text(_field(effective_task_progress, "status")),
        current_step_id=current_step_id,
        current_step_title=current_step_title,
        current_tool_name=current_tool_name,
        total_todos=task_totals["total_todos"],
        completed_todos=task_totals["completed_todos"],
        blocked_todos=task_totals["blocked_todos"],
        total_checkpoints=task_totals["total_checkpoints"],
        completed_checkpoints=task_totals["completed_checkpoints"],
        blocked_checkpoints=task_totals["blocked_checkpoints"],
        runtime_stage_counts=runtime_stage_counts,
        runtime_doctrine=_first_text_from_items(
            [
                runtime_execution_envelope,
                current_request,
                latest_request,
                latest_tool,
                latest_approval,
            ],
            "runtime_doctrine",
        ),
        runtime_stage=_first_text_from_items(
            runtime_context_items,
            "runtime_stage",
        ),
        runtime_role=_first_text_from_items(
            runtime_context_items,
            "runtime_role",
        ),
        plan_tools=plan_tools,
        plan_capabilities=plan_capabilities,
        runtime_request_count=len(request_items),
        pending_runtime_request_count=sum(
            _is_pending_runtime_request(request) for request in request_items
        ),
        completed_runtime_request_count=sum(
            status == "completed" for status in request_statuses
        ),
        recovered_runtime_request_count=sum(
            status == "recovered" for status in request_statuses
        ),
        failed_runtime_request_count=sum(
            status == "failed" for status in request_statuses
        ),
        blocked_runtime_request_count=sum(
            status == "blocked" for status in request_statuses
        ),
        waiting_runtime_request_count=sum(
            _is_waiting_runtime_request(request) for request in request_items
        ),
        current_request_id=_optional_text(_field(current_request, "request_id")),
        current_request_tool_name=_optional_text(_field(current_request, "tool_name")),
        current_request_status=_optional_text(_field(current_request, "status")),
        latest_request_id=_optional_text(_field(latest_request, "request_id")),
        latest_request_tool_name=_optional_text(_field(latest_request, "tool_name")),
        latest_request_status=_optional_text(_field(latest_request, "status")),
        desktop_provider_session_status=_optional_text(
            _field(desktop_provider_session, "status")
        ),
        desktop_provider_session_needed=bool(
            _field(desktop_provider_session, "needed")
        ),
        desktop_provider_session_running=bool(
            _field(desktop_provider_session, "running")
        ),
        desktop_provider_session_started=bool(
            _field(desktop_provider_session, "started")
        ),
        desktop_provider_session_provider_id=_optional_text(
            _field(desktop_provider_session, "provider_id")
        ),
        desktop_provider_session_reason=_optional_text(
            _field(desktop_provider_session, "reason")
        ),
        desktop_provider_session_tool_names=_string_list(
            _field(desktop_provider_session, "tool_names")
        ),
        desktop_provider_session_kind=_optional_text(
            _field(desktop_provider_session, "desktop_session_kind")
        ),
        desktop_provider_session_isolated=_optional_bool(
            _field(desktop_provider_session, "desktop_session_isolated")
        ),
        desktop_provider_session_foreground_takeover_required=_optional_bool(
            _field(desktop_provider_session, "foreground_takeover_required")
        ),
        desktop_provider_session_keyboard_mouse_capture_supported=_optional_bool(
            _field(desktop_provider_session, "keyboard_mouse_capture_supported")
        ),
        desktop_provider_session_supported_tools=_string_list(
            _field(desktop_provider_session, "supported_tools")
        ),
        desktop_provider_backend_kind=_first_text_from_items(
            desktop_provider_context_items,
            "desktop_backend_kind",
            "backend_kind",
        ),
        desktop_provider_backend_is_loopback=_first_bool_from_items(
            desktop_provider_context_items,
            "desktop_backend_is_loopback",
            "backend_is_loopback",
        ),
        desktop_provider_backend_ready_for_public_release=_first_bool_from_items(
            desktop_provider_context_items,
            "desktop_backend_ready_for_public_release",
            "backend_ready_for_public_release",
        ),
        desktop_provider_requires_real_virtual_backend=_first_bool_from_items(
            desktop_provider_context_items,
            "requires_real_virtual_desktop_backend",
            "real_virtual_desktop_backend_required",
        ),
        desktop_provider_contract_ok=_optional_bool(
            _field(desktop_provider_contract, "ok")
        ),
        desktop_provider_contract_version=_optional_text(
            _field(desktop_provider_contract, "contract_version")
        ),
        desktop_provider_contract_blocking_conditions=_string_list(
            _field(desktop_provider_contract, "blocking_conditions")
        ),
        desktop_provider_conformance_ok=_optional_bool(
            _field(desktop_provider_conformance, "ok")
        ),
        desktop_provider_conformance_mode=_optional_text(
            _field(desktop_provider_conformance, "mode")
        ),
        desktop_provider_conformance_smoke_ok=_optional_bool(
            _field(desktop_provider_conformance, "smoke_ok")
        ),
        desktop_provider_conformance_public_release_ready=_optional_bool(
            _field(desktop_provider_conformance, "public_release_ready")
        ),
        desktop_provider_conformance_release_candidate=_optional_bool(
            _field(desktop_provider_conformance, "release_candidate")
        ),
        desktop_provider_conformance_release_blocking_conditions=_string_list(
            _field(desktop_provider_conformance, "release_blocking_conditions")
        ),
        desktop_provider_conformance_missing_required_tools=_string_list(
            _field(desktop_provider_conformance, "missing_required_tools")
        ),
        desktop_provider_conformance_failed_tools=_string_list(
            _field(desktop_provider_conformance, "failed_tools")
        ),
        desktop_execution_session_mode=desktop_execution_session_mode,
        desktop_execution_session_label=_desktop_execution_session_label(
            desktop_execution_session_mode
        ),
        event_count=len(event_items),
        tool_call_count=len(tool_items),
        completed_tool_call_count=sum(status == "completed" for status in tool_statuses),
        failed_tool_call_count=sum(status == "failed" for status in tool_statuses),
        blocked_tool_call_count=sum(status == "blocked" for status in tool_statuses),
        waiting_tool_call_count=sum(
            status in {"approval_required", "waiting_approval"}
            for status in tool_statuses
        ),
        approval_count=len(approval_items),
        pending_approval_count=len(pending_approvals),
        artifact_count=len(artifact_items),
        memory_trace_count=len(memory_items),
        skill_trace_count=len(skill_items),
        child_run_count=len(child_items),
        replan_recovery_count=len(replan_items),
        needs_user_action=bool(
            needs_user_action
            or pending_approvals
            or _desktop_provider_session_needs_user_action(desktop_provider_session)
        ),
        needs_replan=bool(replan_needed),
        latest_event_type=_optional_text(_field(latest_event, "event_type")),
        current_capability_id=_first_text_from_items(
            [
                latest_tool,
                latest_approval,
                current_request,
                latest_request,
                latest_replan,
            ],
            "capability_id",
            "target_capability_id",
        ),
        latest_replan_request_id=(
            _optional_text(_field(latest_replan, "request_id"))
            or _first_text_from_items(
                [latest_tool, latest_approval, latest_request],
                "replan_request_id",
            )
        ),
        latest_replan_trigger=(
            _first_text_from_items(
                [latest_replan, latest_tool, latest_approval, latest_request],
                "trigger",
                "replan_trigger",
            )
            or _first_string_list_value(
                [latest_tool, latest_approval, latest_request],
                "replan_triggers",
            )
        ),
        latest_replan_status=_optional_text(_field(latest_replan, "status")),
        latest_recovery_action_id=_optional_text(
            _field(latest_recovery_action, "action_id")
        ),
        latest_recovery_tool=_optional_text(_field(latest_recovery_action, "tool")),
        latest_recovery_action_label=_optional_text(
            _field(latest_recovery_action, "label")
        ),
        latest_recovery_action_count=len(latest_recovery_actions),
        latest_deferred_tool=(
            _first_text_from_items(
                [latest_tool, latest_approval, latest_request, latest_replan],
                "deferred_tool",
                "selected_tool_name",
            )
            or latest_deferred_continuation_tool
        ),
        deferred_continuation_count=_deferred_continuation_count(
            deferred_continuation_events
        ),
        latest_deferred_continuation_tool=latest_deferred_continuation_tool,
        latest_tool_call_id=_optional_text(_field(latest_tool, "tool_call_id")),
        latest_tool_name=_optional_text(_field(latest_tool, "tool_name")),
        latest_tool_status=_optional_text(_field(latest_tool, "status")),
        latest_approval_id=_optional_text(_field(latest_approval, "approval_id")),
        latest_approval_tool_name=_optional_text(_field(latest_approval, "tool_name")),
        latest_approval_status=_optional_text(_field(latest_approval, "status")),
        latest_artifact_id=_optional_text(_field(latest_artifact, "artifact_id")),
        latest_artifact_kind=_optional_text(_field(latest_artifact, "kind")),
        latest_artifact_path=_optional_text(
            _field(latest_artifact, "path") or _field(latest_artifact, "title")
        ),
        debug_surfaces=debug_surfaces,
    )


def _latest_tool_context(tool_items: list[Any]) -> Any | None:
    for item in reversed(tool_items):
        if (
            _text(_field(item, "runtime_stage"))
            or _text(_field(item, "runtime_role"))
            or _text(_field(item, "runtime_doctrine"))
        ) and _text(_field(item, "status")) not in {"waiting_approval", "approval_required"}:
            return item
    for item in reversed(tool_items):
        if _text(_field(item, "status")) not in {"waiting_approval", "approval_required"}:
            return item
    return tool_items[-1] if tool_items else None


def _approval_items(approvals: Iterable[Any] | None, pending_approval: Any | None) -> list[Any]:
    items = _items(approvals)
    if pending_approval is None:
        return items
    pending_id = _text(_field(pending_approval, "approval_id"))
    if pending_id and any(_text(_field(item, "approval_id")) == pending_id for item in items):
        return items
    return [*items, pending_approval]


def _debug_surfaces(
    *,
    event_items: list[Any],
    tool_items: list[Any],
    approval_items: list[Any],
    artifact_items: list[Any],
    memory_items: list[Any],
    skill_items: list[Any],
    child_items: list[Any],
    replan_items: list[Any],
    deferred_continuation_items: list[Any],
    planner_items: list[Any],
    task_items: list[Any],
    provider_session: Any | None = None,
) -> list[str]:
    surfaces: list[str] = []
    for name, values in (
        ("planner", planner_items),
        ("task", task_items),
        ("timeline", event_items),
        ("tools", tool_items),
        ("approvals", approval_items),
        ("artifacts", artifact_items),
        ("memory", memory_items),
        ("skills", skill_items),
        ("children", child_items),
        ("replan", replan_items),
        ("deferred_continuation", deferred_continuation_items),
        ("desktop_provider", [provider_session] if provider_session is not None else []),
    ):
        if values:
            surfaces.append(name)
    return surfaces


def _planner_tools(
    planner_summary: Any | None,
    envelope: Any | None,
    event_planner_summary: Any | None = None,
) -> list[str]:
    tools = _string_list(_field(planner_summary, "plan_tools"))
    if tools:
        return tools
    selected = _string_list(_field(planner_summary, "selected_tools"))
    if selected:
        return selected
    request_tools = _unique_strings(
        _text(_field(request, "tool_name"))
        for request in _items(_field(envelope, "requests"))
    )
    if request_tools:
        return request_tools
    tools = _string_list(_field(event_planner_summary, "plan_tools"))
    if tools:
        return tools
    return _string_list(_field(event_planner_summary, "selected_tools"))


def _planner_capabilities(
    planner_summary: Any | None,
    envelope: Any | None,
    event_planner_summary: Any | None = None,
) -> list[str]:
    capabilities = _string_list(_field(planner_summary, "plan_capabilities"))
    if capabilities:
        return capabilities
    required = _string_list(_field(planner_summary, "required_capabilities"))
    if required:
        return required
    request_capabilities = _unique_strings(
        _text(_field(request, "capability_id"))
        for request in _items(_field(envelope, "requests"))
    )
    if request_capabilities:
        return request_capabilities
    capabilities = _string_list(_field(event_planner_summary, "plan_capabilities"))
    if capabilities:
        return capabilities
    return _string_list(_field(event_planner_summary, "required_capabilities"))


def _planner_summary_from_events(events: list[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for event in events:
        event_type = _text(_field(event, "event_type"))
        payload = _event_payload(event)
        if not payload:
            continue
        if _is_planner_intent_event(event_type):
            intent = _dict_field(payload, "intent") or _dict_field(payload, "selected_intent")
            _set_if_text(summary, "decision_id", payload.get("decision_id"))
            _set_if_text(summary, "plan_id", payload.get("plan_id"))
            _set_if_text(summary, "intent_kind", intent.get("kind"))
            _set_if_text(summary, "intent_title", intent.get("title"))
            if isinstance(payload.get("route_to_studio"), bool):
                summary["route_to_studio"] = payload.get("route_to_studio")
        elif _is_planner_created_event(event_type):
            plan = _dict_field(payload, "plan") or _dict_field(payload, "runtime_plan")
            tool_plan = _dict_field(plan, "tool_plan") or _dict_field(payload, "tool_plan")
            envelope = _dict_field(payload, "runtime_execution_envelope")
            _set_if_text(summary, "decision_id", payload.get("decision_id"))
            _set_if_text(summary, "plan_id", payload.get("plan_id") or plan.get("plan_id"))
            if isinstance(plan.get("route_to_studio"), bool):
                summary["route_to_studio"] = plan.get("route_to_studio")
            plan_tools = _tool_names_from_tool_plan(tool_plan) or _tool_names_from_envelope(envelope)
            if plan_tools:
                summary["plan_tools"] = plan_tools
            capabilities = _capability_ids_from_payload(payload)
            if capabilities:
                summary["plan_capabilities"] = capabilities
        elif _is_planner_selection_event(event_type):
            _set_if_text(summary, "decision_id", payload.get("decision_id"))
            _set_if_text(summary, "plan_id", payload.get("plan_id"))
            _set_if_text(summary, "intent_kind", payload.get("intent_kind"))
            _set_if_list(summary, "plan_tools", payload.get("plan_tools"))
            _set_if_list(summary, "selected_tools", payload.get("selected_tools"))
            _set_if_list(summary, "plan_capabilities", payload.get("plan_capabilities"))
            _set_if_list(summary, "required_capabilities", payload.get("required_capabilities"))
            if isinstance(payload.get("route_to_studio"), bool):
                summary["route_to_studio"] = payload.get("route_to_studio")
    return summary


def _deferred_continuation_events(events: list[Any]) -> list[Any]:
    return [
        event
        for event in events
        if _event_is_deferred_continuation(_text(_field(event, "event_type")))
    ]


def _event_is_deferred_continuation(event_type: str) -> bool:
    clean = _text(event_type)
    return clean == "agent.deferred_continuation.enqueued" or clean.endswith(
        ".deferred_continuation.enqueued"
    )


def _deferred_continuation_count(events: list[Any]) -> int:
    count = 0
    for event in events:
        payload = _event_payload(event)
        raw_count = _field(payload, "deferred_continuation_count")
        if isinstance(raw_count, int) and raw_count > 0:
            count += raw_count
            continue
        tools = _string_list(payload.get("deferred_tools"))
        count += len(tools) if tools else 1
    return count


def _latest_deferred_continuation_tool(events: list[Any]) -> str | None:
    for event in reversed(events):
        payload = _event_payload(event)
        tools = _string_list(payload.get("deferred_tools"))
        if tools:
            return tools[-1]
        tool = _optional_text(
            payload.get("deferred_tool") or payload.get("tool") or payload.get("source_tool")
        )
        if tool:
            return tool
    return None


def _event_payload(event: Any) -> dict[str, Any]:
    payload = _field(event, "payload")
    return payload if isinstance(payload, dict) else {}


def _dict_field(item: Any, key: str) -> dict[str, Any]:
    value = _field(item, key)
    return value if isinstance(value, dict) else {}


def _is_planner_intent_event(event_type: str) -> bool:
    return event_type == "agent.intent.selected" or event_type.endswith(".intent.selected")


def _is_planner_created_event(event_type: str) -> bool:
    return event_type == "agent.plan.created" or event_type.endswith(".plan.created")


def _is_planner_selection_event(event_type: str) -> bool:
    return event_type == "agent.plan.selection" or event_type.endswith(".plan.selection")


def _tool_names_from_tool_plan(tool_plan: dict[str, Any]) -> list[str]:
    return _unique_strings(
        _text(_field(step, "tool_name"))
        for step in _items(tool_plan.get("steps"))
    )


def _tool_names_from_envelope(envelope: dict[str, Any]) -> list[str]:
    return _unique_strings(
        _text(_field(request, "tool_name") or _field(request, "tool"))
        for request in _items(envelope.get("requests"))
    )


def _capability_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    capabilities = _string_list(payload.get("plan_capabilities"))
    if capabilities:
        return capabilities
    capability_plan = _dict_field(payload, "capability_plan")
    raw_items = capability_plan.get("capabilities") or capability_plan.get("items")
    return _unique_strings(
        _text(_field(item, "capability_id") or _field(item, "id"))
        for item in _items(raw_items)
    )


def _set_if_text(target: dict[str, Any], key: str, value: Any) -> None:
    clean = _text(value)
    if clean:
        target[key] = clean


def _set_if_list(target: dict[str, Any], key: str, value: Any) -> None:
    values = _string_list(value)
    if values:
        target[key] = values


def _runtime_stage_counts(envelope: Any | None) -> dict[str, int]:
    raw_counts = _field(envelope, "runtime_stage_counts")
    if isinstance(raw_counts, dict):
        counts = {
            _text(key): int(value)
            for key, value in raw_counts.items()
            if _text(key) and isinstance(value, int)
        }
        if counts:
            return counts
    counts: dict[str, int] = {}
    for request in _items(_field(envelope, "requests")):
        stage = _text(_field(request, "runtime_stage"))
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def _desktop_provider_session(
    envelope: Any | None,
    requests: list[Any],
    events: list[Any] | None = None,
) -> Any | None:
    session = _field(envelope, "desktop_provider_session")
    if session is not None:
        return session
    for request in requests:
        session = _field(request, "desktop_provider_session")
        if session is not None:
            return session
    for event in reversed(events or []):
        event_type = _text(_field(event, "event_type") or _field(event, "event"))
        if not event_type.startswith("desktop.provider_session."):
            continue
        session = _field(_event_payload(event), "desktop_provider_session")
        if session is not None:
            return session
    return None


def _desktop_provider_context_items(
    envelope: Any | None,
    requests: list[Any],
    session: Any | None,
) -> list[Any]:
    items: list[Any] = []
    for item in (
        session,
        _field(session, "provider_status"),
        _field(session, "health"),
        _field(session, "provider_conformance"),
        _field(session, "sandbox_provider"),
        _field(_field(session, "sandbox_provider"), "health"),
        _field(envelope, "sandbox_provider"),
        _field(_field(envelope, "sandbox_provider"), "health"),
        _field(envelope, "provider_conformance"),
    ):
        if item is not None:
            items.append(item)
    for request in requests:
        provider = _field(request, "sandbox_provider")
        for item in (
            _field(request, "desktop_provider_session"),
            provider,
            _field(provider, "health"),
            _field(provider, "provider_conformance"),
            _field(request, "provider_conformance"),
            _field(request, "desktop_execution_route"),
        ):
            if item is not None:
                items.append(item)
    return items


def _desktop_provider_contract(items: list[Any]) -> Any | None:
    for item in items:
        contract = _field(item, "provider_contract")
        if isinstance(contract, dict):
            return contract
    return None


def _desktop_provider_conformance(items: list[Any]) -> Any | None:
    for item in items:
        conformance = _field(item, "provider_conformance")
        if isinstance(conformance, dict):
            return conformance
        if isinstance(item, dict) and (
            "public_release_ready" in item
            or "release_blocking_conditions" in item
            or "missing_required_tools" in item
        ):
            return item
    return None


def _desktop_provider_session_needs_user_action(session: Any | None) -> bool:
    if session is None:
        return False
    if _field(session, "ok") is False:
        return True
    status = _text(_field(session, "status")).lower()
    if status in {"start_failed", "failed", "required", "provider_required"}:
        return True
    return bool(_field(session, "needed")) and not bool(_field(session, "running"))


def _desktop_provider_session_needs_replan(session: Any | None) -> bool:
    if session is None:
        return False
    if _field(session, "ok") is False:
        return True
    status = _text(_field(session, "status")).lower()
    if status in {"start_failed", "failed", "stopped", "provider_required"}:
        return True
    return bool(_field(session, "needed")) and not bool(_field(session, "running"))


def _desktop_execution_session_mode(
    envelope: Any | None,
    requests: list[Any],
    session: Any | None,
) -> str | None:
    session_mode = _desktop_execution_session_mode_from_session(session)
    if session_mode:
        return session_mode
    for item in [envelope, *requests]:
        route = _field(item, "desktop_execution_route")
        provider = _field(item, "sandbox_provider")
        mode = _desktop_execution_session_mode_from_route_provider(route, provider)
        if mode:
            return mode
    return None


def _desktop_execution_session_mode_from_session(session: Any | None) -> str | None:
    if session is None:
        return None
    status = _text(_field(session, "status")).lower()
    if _field(session, "ok") is False or status in {"start_failed", "failed"}:
        return "provider_failed"
    kind = _text(_field(session, "desktop_session_kind")).lower()
    if kind:
        return kind
    if _optional_bool(_field(session, "desktop_session_isolated")) is True:
        return "isolated_desktop"
    if _optional_bool(_field(session, "foreground_takeover_required")) is True:
        return "user_foreground"
    if bool(_field(session, "needed")) and not bool(_field(session, "running")):
        return "provider_required"
    return None


def _desktop_execution_session_mode_from_route_provider(
    route: Any | None,
    provider: Any | None,
) -> str | None:
    route_status = _text(_field(route, "status")).lower()
    provider_status = _text(_field(provider, "status")).lower()
    route_blockers = set(_string_list(_field(route, "blocking_conditions")))
    provider_blockers = set(_string_list(_field(provider, "blocking_conditions")))
    blockers = route_blockers | provider_blockers
    if (
        route_status in {"provider_required", "sandbox_keyboard_mouse_provider_required"}
        or provider_status in {"provider_required", "not_configured"}
        or any("provider_required" in blocker for blocker in blockers)
    ):
        return "provider_required"
    kind = (
        _text(_field(route, "desktop_session_kind")).lower()
        or _text(_field(provider, "desktop_session_kind")).lower()
    )
    if kind:
        return kind
    if (
        _optional_bool(_field(route, "desktop_session_isolated")) is True
        or _optional_bool(_field(provider, "desktop_session_isolated")) is True
    ):
        return "isolated_desktop"
    if (
        _optional_bool(_field(route, "foreground_takeover_required")) is True
        or _optional_bool(_field(provider, "foreground_takeover_required")) is True
    ):
        return "user_foreground"
    if _optional_bool(_field(provider, "foreground_mutation_supported")) is False:
        return "headless_read_only"
    if route_status or provider_status:
        return "provider_routed"
    return None


def _desktop_execution_session_label(mode: str | None) -> str | None:
    if not mode:
        return None
    return {
        "headless_read_only": "headless read-only desktop provider",
        "isolated_desktop": "isolated desktop provider",
        "provider_failed": "desktop provider failed",
        "provider_required": "desktop provider required",
        "provider_routed": "desktop provider routed",
        "sandbox_desktop": "sandbox desktop provider",
        "user_foreground": "real desktop foreground",
    }.get(mode, mode.replace("_", " "))


def _task_totals(task_core: Any | None, task_progress: Any | None) -> dict[str, int]:
    total_todos = _int_field(task_progress, "total_todos")
    completed_todos = _int_field(task_progress, "completed_todos")
    blocked_todos = _int_field(task_progress, "blocked_todos")
    total_checkpoints = _int_field(task_progress, "total_checkpoints")
    completed_checkpoints = _int_field(task_progress, "completed_checkpoints")
    blocked_checkpoints = _int_field(task_progress, "blocked_checkpoints")

    if task_core is not None:
        todos = _items(_field(task_core, "todos"))
        checkpoints = _items(_field(task_core, "checkpoints"))
        total_todos = total_todos or len(todos)
        completed_todos = completed_todos or _count_status(todos, "completed")
        blocked_todos = blocked_todos or _count_status(todos, "blocked")
        total_checkpoints = total_checkpoints or len(checkpoints)
        completed_checkpoints = completed_checkpoints or _count_status(checkpoints, "completed")
        blocked_checkpoints = blocked_checkpoints or _count_status(checkpoints, "blocked")

    return {
        "total_todos": total_todos,
        "completed_todos": completed_todos,
        "blocked_todos": blocked_todos,
        "total_checkpoints": total_checkpoints,
        "completed_checkpoints": completed_checkpoints,
        "blocked_checkpoints": blocked_checkpoints,
    }


def _richer_task_progress(primary: Any | None, fallback: Any | None) -> Any | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    primary_total = _int_field(primary, "total_todos") + _int_field(
        primary,
        "total_checkpoints",
    )
    fallback_total = _int_field(fallback, "total_todos") + _int_field(
        fallback,
        "total_checkpoints",
    )
    return fallback if fallback_total > primary_total else primary


def _richer_task_core(primary: Any | None, fallback: Any | None) -> Any | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    primary_total = len(_items(_field(primary, "todos"))) + len(
        _items(_field(primary, "checkpoints"))
    )
    fallback_total = len(_items(_field(fallback, "todos"))) + len(
        _items(_field(fallback, "checkpoints"))
    )
    return fallback if fallback_total > primary_total else primary


def _count_status(items: list[Any], status: str) -> int:
    return sum(1 for item in items if _text(_field(item, "status")) == status)


def _int_field(item: Any, key: str) -> int:
    value = _field(item, key)
    return value if isinstance(value, int) and value > 0 else 0


def _optional_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"1", "true", "yes", "on"}:
                return True
            if clean in {"0", "false", "no", "off"}:
                return False
    return None


def _string_list(values: Any) -> list[str]:
    if isinstance(values, str):
        return _unique_strings(values.split(","))
    if not isinstance(values, Iterable) or isinstance(values, (bytes, dict)):
        return []
    return _unique_strings(_text(item) for item in values)


def _unique_strings(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _text(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
    return output


def _first_text_from_items(items: Iterable[Any], *keys: str) -> str | None:
    for item in items:
        for key in keys:
            text = _optional_text(_field(item, key))
            if text:
                return text
    return None


def _first_bool_from_items(items: Iterable[Any], *keys: str) -> bool | None:
    for item in items:
        value = _optional_bool(*(_field(item, key) for key in keys))
        if value is not None:
            return value
    return None


def _first_string_list_value(items: Iterable[Any], key: str) -> str | None:
    for item in items:
        values = _string_list(_field(item, key))
        if values:
            return values[0]
    return None


def _recovery_actions(replan_item: Any | None) -> list[Any]:
    return _items(_field(replan_item, "recovery_actions"))


def _preferred_recovery_action(actions: list[Any]) -> Any | None:
    for action in reversed(actions):
        if _field(action, "selected") is True:
            return action
    return actions[0] if actions else None


def _matching_runtime_request(
    requests: list[Any],
    *,
    step_id: str | None,
    tool_name: str | None,
) -> Any | None:
    if step_id:
        for request in reversed(requests):
            if _text(_field(request, "step_id")) == step_id:
                return request
    if tool_name:
        for request in reversed(requests):
            if _text(_field(request, "tool_name")) == tool_name:
                return request
    return None


def _active_runtime_request(requests: list[Any]) -> Any | None:
    for request in requests:
        if _text(_field(request, "status")) not in _TERMINAL_RUNTIME_REQUEST_STATUSES:
            return request
    return requests[-1] if requests else None


def _is_pending_runtime_request(request: Any) -> bool:
    status = _text(_field(request, "status"))
    if not status:
        return False
    if status in _TERMINAL_RUNTIME_REQUEST_STATUSES:
        return False
    return not _is_waiting_runtime_request(request)


def _is_waiting_runtime_request(request: Any) -> bool:
    status = _text(_field(request, "status"))
    if status in _TERMINAL_RUNTIME_REQUEST_STATUSES:
        return False
    return status in _WAITING_RUNTIME_REQUEST_STATUSES or (
        _field(request, "approval_required") is True
    )


def _items(values: Iterable[Any] | None) -> list[Any]:
    if values is None:
        return []
    return [item for item in values if item is not None]


def _replan_item_needs_replan(item: Any) -> bool:
    status = _text(_field(item, "status")).lower()
    if status in {"completed", "resolved", "cancelled", "canceled"}:
        return False
    if status:
        return True
    tool_status = _text(_field(item, "tool_status")).lower()
    return tool_status not in {"completed", "resolved"}


def _events_have_unresolved_replan(events: list[Any]) -> bool:
    resolved_request_ids: set[str] = set()
    for event in reversed(events):
        event_type = _text(_field(event, "event_type"))
        payload = _field(event, "payload")
        payload = payload if isinstance(payload, dict) else {}
        request_id = _text(payload.get("request_id") or payload.get("replan_request_id"))
        if request_id and not _event_is_replan_request(event_type) and _event_resolves_replan(payload):
            resolved_request_ids.add(request_id)
            continue
        if not _event_is_replan_request(event_type):
            continue
        if request_id and request_id in resolved_request_ids:
            continue
        return True
    return False


def _event_is_replan_request(event_type: str) -> bool:
    clean = _text(event_type)
    return clean == "agent.replan.requested" or clean.endswith(".replan.requested")


def _event_resolves_replan(payload: dict[str, Any]) -> bool:
    return _text(payload.get("status") or payload.get("tool_status")).lower() in {
        "completed",
        "resolved",
    }


def _field(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return str(value or "").strip()
