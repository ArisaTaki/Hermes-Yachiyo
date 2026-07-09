"""Chat-facing AgentTask public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.desktop_tool_labels import (
    TASK_PROGRESS_DESKTOP_TOOL_LABELS as _DESKTOP_TOOL_PROGRESS_LABELS,
)
from apps.shell.agent.runtime.events import redact_json_value, redact_secrets

from .approval_event_snapshots import (
    approval_snapshots_from_events,
    merge_approval_snapshot_lists,
)
from .approvals import approval_cards_from_payloads
from .artifact_event_snapshots import (
    artifact_snapshots_from_events,
    merge_artifact_snapshot_lists,
)
from .artifacts import artifact_snapshots_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    PublicRunEvent,
    RuntimeExecutionEnvelopeSnapshot,
    ToolCallSnapshot,
)
from .events import public_run_event_from_payload, run_event_parent_context
from .links import studio_run_url
from .recovery_actions import RECOVERY_RETRY_CONTEXT_EVENT_TYPE
from .replan_event_projection import (
    run_events_with_replan_requests,
    run_events_with_runtime_execution_replan_requests,
)
from .replan_recovery_snapshots import (
    merge_replan_recovery_snapshot_lists,
    replan_recovery_snapshots_from_events,
    replan_recovery_snapshots_from_runtime_execution_envelope,
)
from .runtime_debug_snapshots import runtime_debug_summary_from_runtime_objects
from .runtime_execution_status import runtime_execution_envelope_with_status_overlay
from .timeline_metadata_snapshots import planner_trace_summary_from_payload
from .tool_call_snapshots import tool_call_snapshots_from_payloads
from .task_core_snapshots import task_core_snapshot_from_payload
from .task_progress_snapshots import task_progress_summary_from_task_core

_ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_approval"}
_PLANNED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_planned"
_UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_unavailable"
_APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_approval_required"
_COMPLETED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_completed"
_PERMISSION_RECOVERY_DESKTOP_EVENT_TYPE = "agent.desktop.permission_recovery"
_READINESS_RECOVERED_DESKTOP_EVENT_TYPE = "agent.desktop.readiness_recovered"
_TOOL_CALL_EVENT_TYPE = "agent.tool.call"
_RECOVERABLE_FOREGROUND_READINESS_CONDITIONS = {
    "app_not_found",
    "app_not_running",
    "foreground_focus_unverified",
    "foreground_not_ready",
    "no_actionable_controls",
    "ui_elements_empty",
}
_DAILY_DESKTOP_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.windows",
    "desktop.permissions",
}
_DAILY_DESKTOP_DISCOVERY_PREFIX_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.permissions",
}
_DAILY_DESKTOP_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.windows",
    "desktop.ui_elements",
    "desktop.inspect_app",
}
_CHAT_TOOL_INPUT_TRACE_KEYS = {
    "approval_id",
    "approval_required",
    "desktop_execution_policy",
    "risk_level",
    "policy_reason",
    "source",
    "planning_reason",
    "source_run_id",
    "source_runnable_id",
    "source_runnable_name",
    "member_agent_id",
    "member_agent_name",
    "agent_id",
    "agent_name",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
    "group_id",
    "group_run_id",
    "run_group_id",
    "core_id",
    "workspace_id",
    "task_id",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "replan_request_id",
    "replan_trigger",
    "replan_signal_ids",
    "replan_triggers",
    "requires_observation",
    "requires_post_action_verification",
    "runtime_doctrine",
    "runtime_role",
    "runtime_stage",
    "deferred_tool",
    "deferred_input",
    "deferred_context",
    "deferred_continuation",
    "selection_source",
    "app_selection_source",
    "app_resolution_source",
    "app_resolution_score",
    "app_resolution_confidence",
    "app_resolution_reason",
    "requested_app_name",
    "resolved_app_name",
    "resolved_app_path",
    "runtime_execution_envelope",
    "runtime_execution_metadata",
    "tool_request",
    "completed_tool_requests",
    "remaining_tool_requests",
    "messages",
    "next_iteration",
    "resume_kind",
    "model_profile_id",
    "tool_policy",
    "workspace_policy",
}
_CHAT_TASK_EVENT_PAYLOAD_TRACE_KEYS = {
    "core_id",
    "workspace_id",
    "task_id",
}


def agent_task_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentTaskSnapshot,
) -> AgentTaskSnapshot:
    if isinstance(payload, AgentTaskSnapshot):
        return payload

    task_id = _text(payload.get("task_id") or payload.get("run_id"))
    run_id = _text(payload.get("run_id") or task_id)
    group_run_id = _group_run_id(payload)
    all_events = run_events_from_payload(
        payload,
        run_id=run_id,
        keys=("recent_events", "events", "timeline"),
    )
    all_events = run_events_with_replan_requests(
        payload,
        all_events,
        run_id=run_id,
        task_id=task_id,
    )
    recent_events = _chat_visible_events(all_events)
    approvals = [
        approval
        for approval in approval_snapshots_from_payload(
            payload,
            run_id=run_id,
            group_run_id=group_run_id,
            keys=("pending_approvals", "pending_approval"),
            events=recent_events,
        )
        if approval.status == "pending"
    ]
    approvals = _chat_sanitized_approvals(approvals)
    status = task_status_from_value(payload.get("status"))
    current_step = _optional_text(payload.get("current_step"))
    progress_text = _optional_text(payload.get("progress_text"))
    derived_progress = _desktop_intent_progress_text(
        recent_events,
        task_status=status,
        has_explicit_progress=bool(current_step or progress_text),
    )
    tool_calls = tool_call_snapshots_from_payloads(
        payload.get("tool_calls"),
        run_id=run_id,
        events=recent_events,
    )
    tool_calls = _chat_task_tool_calls(tool_calls, recent_events)
    tool_calls = _chat_sanitized_tool_calls(tool_calls)
    runtime_execution_envelope = runtime_execution_envelope_from_payload(
        payload,
        events=all_events,
    )
    active_task = status in _ACTIVE_TASK_STATUSES
    recovery_needs_user_action = (
        _has_desktop_recovery_user_action(
            recent_events,
            tool_calls,
            all_events=all_events,
        )
        if active_task
        else _has_completed_desktop_recovery_user_action(recent_events)
    )
    needs_user_action = bool(
        approvals
        or recovery_needs_user_action
        or (
            active_task
            and payload.get("needs_user_action")
        )
    )
    task_core = task_core_snapshot_from_payload(payload, events=all_events)
    if task_core is None and runtime_execution_envelope is not None:
        task_core = runtime_execution_envelope.task_core
    desktop_provider_session = (
        runtime_execution_envelope.desktop_provider_session
        if runtime_execution_envelope is not None
        else {}
    )
    task_progress = task_progress_summary_from_task_core(
        task_core,
        events=all_events,
        needs_user_action=needs_user_action,
        desktop_provider_session=desktop_provider_session,
    )
    runtime_execution_envelope = runtime_execution_envelope_with_status_overlay(
        runtime_execution_envelope,
        tool_calls=tool_calls,
        approvals=approvals,
        events=all_events,
        task_progress=task_progress,
    )
    all_events = run_events_with_runtime_execution_replan_requests(
        all_events,
        runtime_execution_envelope,
        run_id=run_id,
        task_id=task_id,
        group_run_id=group_run_id,
        created_at=_text(payload.get("updated_at") or payload.get("created_at")),
    )
    recent_events = _chat_visible_events(all_events)
    task_progress = task_progress_summary_from_task_core(
        task_core,
        events=all_events,
        needs_user_action=needs_user_action,
        desktop_provider_session=desktop_provider_session,
    )
    runtime_execution_envelope = runtime_execution_envelope_with_status_overlay(
        runtime_execution_envelope,
        tool_calls=tool_calls,
        approvals=approvals,
        events=all_events,
        task_progress=task_progress,
    )
    replan_recoveries = merge_replan_recovery_snapshot_lists(
        replan_recovery_snapshots_from_events(
            all_events,
            run_id=run_id,
            task_id=task_id,
            group_run_id=group_run_id,
        ),
        replan_recovery_snapshots_from_runtime_execution_envelope(
            runtime_execution_envelope,
            run_id=run_id,
            task_id=task_id,
            group_run_id=group_run_id,
            task_progress=task_progress,
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        ),
    )
    runtime_execution_envelope = runtime_execution_envelope_with_status_overlay(
        runtime_execution_envelope,
        tool_calls=tool_calls,
        approvals=approvals,
        replan_recoveries=replan_recoveries,
        events=all_events,
        task_progress=task_progress,
    )
    artifacts = artifact_snapshots_from_task_payload(
        payload,
        run_id=run_id,
        events=recent_events,
    )
    planner_summary = planner_trace_summary_from_payload(
        {
            "planner_summary": payload.get("planner_summary"),
            "events": recent_events,
        }
    )
    public_metadata = _public_task_metadata(payload)

    return AgentTaskSnapshot(
        task_id=task_id,
        conversation_id=_optional_text(payload.get("conversation_id") or payload.get("session_id")),
        title=_text(payload.get("title") or payload.get("user_goal") or "Yachiyo task"),
        status=status,
        summary=_optional_text(payload.get("summary") or payload.get("result")),
        current_step=current_step or derived_progress,
        progress_text=progress_text or derived_progress,
        needs_user_action=needs_user_action,
        pending_approvals=approvals,
        recent_events=recent_events,
        tool_calls=tool_calls,
        artifacts=artifacts,
        metadata=public_metadata,
        planner_summary=planner_summary,
        runtime_debug=runtime_debug_summary_from_runtime_objects(
            run_id=run_id,
            task_id=task_id,
            group_run_id=group_run_id,
            events=recent_events,
            tool_calls=tool_calls,
            approvals=approvals,
            artifacts=artifacts,
            replan_recoveries=replan_recoveries,
            planner_summary=planner_summary,
            runtime_execution_envelope=runtime_execution_envelope,
            runtime_metadata=public_metadata,
            task_core=task_core,
            task_progress=task_progress,
            needs_user_action=needs_user_action,
            needs_replan=bool(task_progress and task_progress.needs_replan),
        ),
        runtime_execution_envelope=runtime_execution_envelope,
        task_core=task_core,
        task_progress=task_progress,
        replan_recoveries=replan_recoveries,
        open_in_studio_url=_optional_text(payload.get("open_in_studio_url"))
        or studio_run_url(run_id, group_run_id=group_run_id),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def agent_task_snapshots_from_payloads(payloads: Any) -> list[AgentTaskSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [agent_task_snapshot_from_payload(item) for item in payloads]


def _public_task_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    redacted = redact_json_value(dict(metadata))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def runtime_execution_envelope_from_payload(
    payload: Mapping[str, Any],
    *,
    events: list[PublicRunEvent],
) -> RuntimeExecutionEnvelopeSnapshot | None:
    for candidate in _runtime_execution_envelope_candidates(payload, events):
        if isinstance(candidate, RuntimeExecutionEnvelopeSnapshot):
            return candidate
        if not isinstance(candidate, Mapping):
            continue
        try:
            return RuntimeExecutionEnvelopeSnapshot.model_validate(candidate)
        except ValueError:
            continue
    return None


def _runtime_execution_envelope_candidates(
    payload: Mapping[str, Any],
    events: list[PublicRunEvent],
) -> list[Any]:
    candidates: list[Any] = [
        payload.get("runtime_execution_envelope"),
        payload.get("yachiyo_execution_envelope"),
        payload.get("execution_envelope"),
    ]
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        candidates.extend([
            metadata.get("runtime_execution_envelope"),
            metadata.get("yachiyo_execution_envelope"),
            metadata.get("execution_envelope"),
        ])
    for event in reversed(events):
        event_payload = event.payload if isinstance(event.payload, Mapping) else {}
        candidates.extend([
            event_payload.get("runtime_execution_envelope"),
            event_payload.get("yachiyo_execution_envelope"),
            event_payload.get("execution_envelope"),
        ])
        event_metadata = event_payload.get("metadata")
        if isinstance(event_metadata, Mapping):
            candidates.extend([
                event_metadata.get("runtime_execution_envelope"),
                event_metadata.get("yachiyo_execution_envelope"),
                event_metadata.get("execution_envelope"),
            ])
    return candidates


def _chat_task_tool_calls(
    tool_calls: list[ToolCallSnapshot],
    events: list[PublicRunEvent],
) -> list[ToolCallSnapshot]:
    completed_events = [
        event
        for event in events
        if event.event_type == _COMPLETED_DESKTOP_INTENT_EVENT_TYPE
    ]
    approval_events = [
        event
        for event in events
        if event.event_type == _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE
    ]
    if not completed_events and approval_events:
        approval_tool_calls = tool_call_snapshots_from_payloads(
            None,
            events=approval_events,
        )
        return _chat_tool_calls_with_pending_approvals(
            tool_calls,
            approval_tool_calls,
        )

    desktop_step_events = [
        *completed_events,
        *approval_events,
    ]
    if not desktop_step_events:
        return tool_calls

    visible_events: list[PublicRunEvent] = []
    for event in desktop_step_events:
        if event.event_type != _COMPLETED_DESKTOP_INTENT_EVENT_TYPE:
            visible_events.append(event)
            continue
        payload = dict(event.payload) if isinstance(event.payload, Mapping) else {}
        steps = _visible_daily_desktop_completed_steps(payload.get("steps"))
        if steps:
            payload["steps"] = steps
        visible_events.append(event.model_copy(update={"payload": payload}))
    visible_tool_calls = tool_call_snapshots_from_payloads(None, events=visible_events)
    return visible_tool_calls or tool_calls


def _chat_tool_calls_with_pending_approvals(
    tool_calls: list[ToolCallSnapshot],
    approval_tool_calls: list[ToolCallSnapshot],
) -> list[ToolCallSnapshot]:
    if not approval_tool_calls:
        return tool_calls
    visible = list(tool_calls)
    for approval in approval_tool_calls:
        visible = [
            call
            for call in visible
            if not _same_chat_tool_call_input(call, approval)
        ]
        visible.append(approval)
    return visible


def _same_chat_tool_call_input(
    current: ToolCallSnapshot,
    approval: ToolCallSnapshot,
) -> bool:
    return (
        current.tool_name == approval.tool_name
        and current.input_preview == approval.input_preview
    )


def _chat_sanitized_tool_calls(
    tool_calls: list[ToolCallSnapshot],
) -> list[ToolCallSnapshot]:
    return _deduped_chat_tool_calls(
        [_chat_sanitized_tool_call(tool_call) for tool_call in tool_calls]
    )


def _deduped_chat_tool_calls(
    tool_calls: list[ToolCallSnapshot],
) -> list[ToolCallSnapshot]:
    visible: list[ToolCallSnapshot] = []
    seen: set[tuple[str, str, str]] = set()
    for tool_call in tool_calls:
        key = (
            tool_call.tool_name,
            tool_call.status,
            repr(redact_json_value(tool_call.input_preview)),
        )
        if key in seen:
            continue
        seen.add(key)
        visible.append(tool_call)
    return visible


def _chat_sanitized_approvals(
    approvals: list[ApprovalCardSnapshot],
) -> list[ApprovalCardSnapshot]:
    return [_chat_sanitized_approval(approval) for approval in approvals]


def _chat_sanitized_approval(approval: ApprovalCardSnapshot) -> ApprovalCardSnapshot:
    clean_input = {
        key: value
        for key, value in approval.input_preview.items()
        if key not in _CHAT_TOOL_INPUT_TRACE_KEYS
    }
    if clean_input == approval.input_preview:
        return approval
    return approval.model_copy(update={"input_preview": clean_input})


def _chat_sanitized_tool_call(tool_call: ToolCallSnapshot) -> ToolCallSnapshot:
    trace_keys = set(_CHAT_TOOL_INPUT_TRACE_KEYS)
    if _chat_tool_input_query_is_trace(tool_call):
        trace_keys.add("query")
    clean_input = {
        key: value
        for key, value in tool_call.input_preview.items()
        if key not in trace_keys
    }
    if clean_input == tool_call.input_preview:
        return tool_call
    return tool_call.model_copy(update={"input_preview": clean_input})


def _chat_tool_input_query_is_trace(tool_call: ToolCallSnapshot) -> bool:
    if tool_call.tool_name == "desktop.list_apps":
        return False
    preview = tool_call.input_preview
    if not isinstance(preview, Mapping):
        return False
    return bool(
        str(preview.get("selection_source") or preview.get("app_selection_source") or "").strip()
        == "desktop.list_apps"
        or str(preview.get("app_resolution_source") or "").strip() == "desktop.list_apps"
    )


def _visible_daily_desktop_completed_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []
    steps = [dict(step) for step in raw_steps if isinstance(step, Mapping)]
    primary_indexes = [
        index
        for index, step in enumerate(steps)
        if _text(step.get("tool") or step.get("tool_name")) not in _DAILY_DESKTOP_DISCOVERY_TOOLS
        and _text(step.get("tool") or step.get("tool_name")) not in _DAILY_DESKTOP_VERIFY_TOOLS
    ]
    if not primary_indexes:
        visible_steps = list(steps)
        while (
            len(visible_steps) > 1
            and _text(visible_steps[0].get("tool") or visible_steps[0].get("tool_name"))
            in _DAILY_DESKTOP_DISCOVERY_PREFIX_TOOLS
        ):
            visible_steps = visible_steps[1:]
        return _coalesced_open_focus_find_steps(visible_steps)

    first_primary = primary_indexes[0]
    last_primary = primary_indexes[-1]
    visible_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        tool_name = _text(step.get("tool") or step.get("tool_name"))
        if tool_name in _DAILY_DESKTOP_DISCOVERY_TOOLS and (
            index < first_primary or index > last_primary
        ):
            continue
        if (
            tool_name in _DAILY_DESKTOP_VERIFY_TOOLS
            and index > last_primary
            and not _is_requested_ui_readback(steps, index, first_primary, last_primary)
        ):
            continue
        visible_steps.append(step)
    return _coalesced_open_focus_find_steps(visible_steps or steps)


def _coalesced_open_focus_find_steps(
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(steps) < 3:
        return steps
    coalesced: list[dict[str, Any]] = []
    index = 0
    while index < len(steps):
        if index + 2 >= len(steps):
            coalesced.append(steps[index])
            index += 1
            continue
        open_step = steps[index]
        focus_step = steps[index + 1]
        shortcut_step = steps[index + 2]
        app_name = _summary_step_app_name(open_step)
        if (
            _text(open_step.get("tool") or open_step.get("tool_name"))
            in {"app.open", "desktop.open_app"}
            and _text(focus_step.get("tool") or focus_step.get("tool_name"))
            in {"app.focus", "desktop.focus_app"}
            and _text(shortcut_step.get("tool") or shortcut_step.get("tool_name"))
            == "desktop.safe_shortcut"
            and app_name
            and _summary_step_app_name(focus_step) == app_name
            and _summary_step_shortcut_action(shortcut_step) == "find"
        ):
            coalesced.append(
                {
                    **shortcut_step,
                    "tool": "app.open_and_safe_shortcut",
                    "tool_name": "app.open_and_safe_shortcut",
                    "input_preview": {"app_name": app_name, "action": "find"},
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
    return _text(input_preview.get("app_name") or data.get("app_name"))


def _summary_step_shortcut_action(step: Mapping[str, Any]) -> str:
    input_preview = step.get("input_preview") if isinstance(step.get("input_preview"), Mapping) else {}
    result = step.get("result") if isinstance(step.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    return _text(input_preview.get("action") or data.get("shortcut_action"))


def _is_requested_ui_readback(
    steps: list[dict[str, Any]],
    index: int,
    first_primary: int,
    last_primary: int,
) -> bool:
    if _text(steps[index].get("tool") or steps[index].get("tool_name")) != "desktop.ui_elements":
        return False
    primary_tools = {
        _text(step.get("tool") or step.get("tool_name"))
        for step in steps[first_primary : last_primary + 1]
        if isinstance(step, Mapping)
    }
    return bool(primary_tools) and primary_tools.issubset(
        {
            "app.open",
            "app.focus",
            "system.settings_open",
        }
    )


def run_events_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    keys: tuple[str, ...],
) -> list[PublicRunEvent]:
    context = run_event_parent_context(payload)
    raw_events = []
    for key in keys:
        value = payload.get(key)
        if value:
            raw_events = value
            break
    return [
        public_run_event_from_payload(
            event,
            run_id=run_id,
            sequence=index + 1,
            context=context,
        )
        for index, event in enumerate(raw_events if isinstance(raw_events, list) else [])
    ]


def approval_snapshots_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    group_run_id: str = "",
    keys: tuple[str, ...],
    events: list[PublicRunEvent] | None = None,
):
    for key in keys:
        approvals = approval_cards_from_payloads(
            payload.get(key),
            run_id=run_id,
            group_run_id=group_run_id,
        )
        if approvals:
            return merge_approval_snapshot_lists(
                approvals,
                approval_snapshots_from_events(events or [], group_run_id=group_run_id),
            )
    return approval_snapshots_from_events(events or [], group_run_id=group_run_id)


def artifact_snapshots_from_task_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    events: list[PublicRunEvent] | None = None,
):
    return merge_artifact_snapshot_lists(
        artifact_snapshots_from_payloads(payload.get("artifacts"), run_id=run_id),
        artifact_snapshots_from_events(events or []),
    )


def task_status_from_value(value: Any) -> str:
    status = _text(value)
    status_map = {
        "approval_required": "waiting_approval",
        "pending_approval": "waiting_approval",
        "processing": "running",
        "success": "completed",
        "succeeded": "completed",
        "done": "completed",
        "error": "failed",
        "canceled": "cancelled",
    }
    normalized = status_map.get(status, status)
    if normalized in {"queued", "running", "waiting_approval", "completed", "failed", "cancelled"}:
        return normalized
    return "running"


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    return [
        _chat_sanitized_recent_event(event)
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]


def _chat_sanitized_recent_event(event: PublicRunEvent) -> PublicRunEvent:
    if not event.event_type.startswith("task."):
        return event
    clean_payload = {
        key: value
        for key, value in event.payload.items()
        if key not in _CHAT_TASK_EVENT_PAYLOAD_TRACE_KEYS
    }
    if clean_payload == event.payload:
        return event
    return event.model_copy(update={"payload": clean_payload})


def _desktop_intent_progress_text(
    events: list[PublicRunEvent],
    *,
    task_status: str,
    has_explicit_progress: bool,
) -> str | None:
    if has_explicit_progress or task_status not in _ACTIVE_TASK_STATUSES:
        return None

    if not _has_desktop_intent_result_event(events):
        planned_progress = _first_planned_desktop_intent_progress_text(events)
        if planned_progress:
            return planned_progress

    for event in reversed(events):
        desktop_event_type = _desktop_intent_event_type(event.event_type)
        if (desktop_event_type or event.event_type) not in {
            _PLANNED_DESKTOP_INTENT_EVENT_TYPE,
            _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE,
            _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE,
            _COMPLETED_DESKTOP_INTENT_EVENT_TYPE,
            _READINESS_RECOVERED_DESKTOP_EVENT_TYPE,
            _TOOL_CALL_EVENT_TYPE,
        }:
            continue
        tool_name = _event_tool_name(event)
        if tool_name not in _DESKTOP_TOOL_PROGRESS_LABELS:
            continue
        label = _DESKTOP_TOOL_PROGRESS_LABELS.get(tool_name, tool_name)
        if event.event_type == _TOOL_CALL_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            return _desktop_tool_result_progress_text(label, result)
        if desktop_event_type == _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE:
            return f"等待批准 · {label}" if label else "等待批准桌面动作"
        if desktop_event_type == _COMPLETED_DESKTOP_INTENT_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            return _desktop_tool_result_progress_text(label, result)
        if desktop_event_type == _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            return _progress_text(
                "无法执行",
                label,
                "无法执行桌面动作",
                detail=_unavailable_desktop_intent_detail(payload),
            )
        if desktop_event_type == _PLANNED_DESKTOP_INTENT_EVENT_TYPE:
            return f"准备执行 · {label}" if label else "准备执行桌面动作"
        if desktop_event_type == _READINESS_RECOVERED_DESKTOP_EVENT_TYPE:
            return f"桌面就绪已恢复 · {label}" if label else "桌面就绪已恢复"
    return None


def _has_desktop_intent_result_event(events: list[PublicRunEvent]) -> bool:
    result_event_types = {
        _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE,
        _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE,
        _COMPLETED_DESKTOP_INTENT_EVENT_TYPE,
        _TOOL_CALL_EVENT_TYPE,
    }
    return any(_desktop_intent_event_type(event.event_type) in result_event_types for event in events)


def _first_planned_desktop_intent_progress_text(events: list[PublicRunEvent]) -> str | None:
    for event in events:
        if _desktop_intent_event_type(event.event_type) != _PLANNED_DESKTOP_INTENT_EVENT_TYPE:
            continue
        tool_name = _event_tool_name(event)
        if tool_name not in _DESKTOP_TOOL_PROGRESS_LABELS:
            continue
        label = _DESKTOP_TOOL_PROGRESS_LABELS.get(tool_name, tool_name)
        return f"准备执行 · {label}" if label else "准备执行桌面动作"
    return None


def _desktop_intent_event_type(event_type: str) -> str:
    event_name = str(event_type or "").strip()
    if event_name in {
        _PLANNED_DESKTOP_INTENT_EVENT_TYPE,
        _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE,
        _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE,
        _COMPLETED_DESKTOP_INTENT_EVENT_TYPE,
        _PERMISSION_RECOVERY_DESKTOP_EVENT_TYPE,
        _READINESS_RECOVERED_DESKTOP_EVENT_TYPE,
    }:
        return event_name
    scoped_prefixes = ("group.run.desktop.", "workflow.desktop.", "workflow.run.desktop.")
    if not event_name.startswith(scoped_prefixes):
        return ""
    suffix_map = {
        "intent_planned": _PLANNED_DESKTOP_INTENT_EVENT_TYPE,
        "intent_unavailable": _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE,
        "intent_approval_required": _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE,
        "intent_completed": _COMPLETED_DESKTOP_INTENT_EVENT_TYPE,
        "permission_recovery": _PERMISSION_RECOVERY_DESKTOP_EVENT_TYPE,
        "readiness_recovered": _READINESS_RECOVERED_DESKTOP_EVENT_TYPE,
    }
    for suffix, normalized in suffix_map.items():
        if event_name.endswith(f".desktop.{suffix}"):
            return normalized
    return ""


def _desktop_tool_result_progress_text(label: str, result: Mapping[str, Any]) -> str:
    if result.get("approval_required"):
        return _progress_text("等待批准", label, "等待批准桌面动作")
    if result.get("foreground_lock_busy"):
        holder = _foreground_lock_holder(result)
        return _progress_text("前台被占用", label, "前台动作被占用", detail=holder)
    permission_targets = _result_text_list(result, "permission_targets", "missing_permissions")
    if result.get("permission_error") or permission_targets:
        return _progress_text(
            "需要权限",
            label,
            "需要桌面权限",
            detail=", ".join(permission_targets),
        )
    if _text(result.get("error_code")) == "app_not_found":
        return _progress_text("应用未找到", label, "应用未找到")
    if result.get("fallback_used"):
        return _progress_text(
            "已回退执行",
            label,
            "已回退执行桌面动作",
            detail=_fallback_detail(result),
        )
    if result.get("ok") is False:
        return _progress_text(
            "执行失败",
            label,
            "桌面动作失败",
            detail=_failure_detail(result),
        )
    return _progress_text("已执行", label, "已执行桌面动作")


def _has_desktop_recovery_user_action(
    events: list[PublicRunEvent],
    tool_calls: list[Any],
    *,
    all_events: list[PublicRunEvent] | None = None,
    count_success_recovery_actions: bool = True,
) -> bool:
    is_recovery_execution = any(
        event.event_type == RECOVERY_RETRY_CONTEXT_EVENT_TYPE
        or _is_structured_recovery_metadata_event(event)
        for event in (all_events or events)
    )
    latest_readiness_recovery_sequence = _latest_readiness_recovery_sequence(events)
    for event in events:
        if (event.sensitivity or "public") == "secret":
            continue
        if event.event_type == RECOVERY_RETRY_CONTEXT_EVENT_TYPE:
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
        desktop_event_type = _desktop_intent_event_type(event.event_type)
        if (
            desktop_event_type == _PERMISSION_RECOVERY_DESKTOP_EVENT_TYPE
            and _has_recovery_signal(
                payload,
                count_success_recovery_actions=count_success_recovery_actions,
            )
            and not _is_recovered_foreground_readiness_signal(
                event,
                payload,
                latest_readiness_recovery_sequence,
            )
        ):
            return True
        if (
            (
                desktop_event_type == _COMPLETED_DESKTOP_INTENT_EVENT_TYPE
                or event.event_type == _TOOL_CALL_EVENT_TYPE
            )
            and _has_recovery_signal(
                result,
                count_success_recovery_actions=(
                    count_success_recovery_actions and not is_recovery_execution
                ),
            )
            and not _is_recovered_foreground_readiness_signal(
                event,
                result,
                latest_readiness_recovery_sequence,
            )
        ):
            return True
    for tool_call in tool_calls:
        output_preview = getattr(tool_call, "output_preview", {})
        if isinstance(output_preview, Mapping) and _has_recovery_signal(
            output_preview,
            count_success_recovery_actions=(
                count_success_recovery_actions and not is_recovery_execution
            ),
        ) and not _is_recovered_foreground_readiness_tool_call(
            output_preview,
            latest_readiness_recovery_sequence,
        ):
            return True
    return False


def _has_completed_desktop_recovery_user_action(events: list[PublicRunEvent]) -> bool:
    latest_readiness_recovery_sequence = _latest_readiness_recovery_sequence(events)
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        desktop_event_type = _desktop_intent_event_type(event.event_type)
        if desktop_event_type == _PERMISSION_RECOVERY_DESKTOP_EVENT_TYPE:
            if _has_recovery_signal(payload) and not _is_recovered_foreground_readiness_signal(
                event,
                payload,
                latest_readiness_recovery_sequence,
            ):
                return True
            continue
        if desktop_event_type != _COMPLETED_DESKTOP_INTENT_EVENT_TYPE:
            continue
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
        return _has_recovery_signal(
            result,
            count_success_recovery_actions=False,
        ) and not _is_recovered_foreground_readiness_signal(
            event,
            result,
            latest_readiness_recovery_sequence,
        )
    return False


def _latest_readiness_recovery_sequence(events: list[PublicRunEvent]) -> int:
    return max(
        [
            int(event.sequence or 0)
            for event in events
            if _desktop_intent_event_type(event.event_type) == _READINESS_RECOVERED_DESKTOP_EVENT_TYPE
        ]
        or [0]
    )


def _is_recovered_foreground_readiness_signal(
    event: PublicRunEvent,
    source: Mapping[str, Any],
    latest_readiness_recovery_sequence: int,
) -> bool:
    if not latest_readiness_recovery_sequence:
        return False
    if int(event.sequence or 0) >= latest_readiness_recovery_sequence:
        return False
    return _has_foreground_readiness_signal(source) and not _has_permission_signal(source)


def _is_recovered_foreground_readiness_tool_call(
    output_preview: Mapping[str, Any],
    latest_readiness_recovery_sequence: int,
) -> bool:
    if not latest_readiness_recovery_sequence:
        return False
    return _has_foreground_readiness_signal(output_preview) and not _has_permission_signal(
        output_preview
    )


def _has_foreground_readiness_signal(source: Mapping[str, Any]) -> bool:
    data = source.get("data") if isinstance(source.get("data"), Mapping) else {}
    conditions = set(
        _result_text_list(source, "blocking_condition", "blocking_conditions")
        + _result_text_list(data, "blocking_condition", "blocking_conditions")
    )
    error = _text(
        source.get("error_code")
        or source.get("error")
        or data.get("error_code")
        or data.get("error")
    )
    return bool(
        source.get("blocked_by_runtime_readiness")
        or data.get("blocked_by_runtime_readiness")
        or data.get("ready_for_foreground_action") is False
        or error == "app_not_found"
        or conditions.intersection(_RECOVERABLE_FOREGROUND_READINESS_CONDITIONS)
    )


def _has_recovery_signal(
    source: Mapping[str, Any],
    *,
    count_success_recovery_actions: bool = True,
) -> bool:
    data = source.get("data") if isinstance(source.get("data"), Mapping) else {}
    if _has_permission_signal(source):
        return True
    has_recovery_actions = _has_recovery_actions(source) or _has_recovery_actions(data)
    if not has_recovery_actions:
        return False
    return bool(
        count_success_recovery_actions
        or source.get("ok") is False
        or data.get("ok") is False
    )


def _has_permission_signal(source: Mapping[str, Any]) -> bool:
    data = source.get("data") if isinstance(source.get("data"), Mapping) else {}
    return bool(
        source.get("permission_error")
        or _result_text_list(source, "permission_targets", "missing_permissions")
        or _result_text_list(data, "permission_targets", "missing_permissions")
    )


def _is_structured_recovery_metadata_event(event: PublicRunEvent) -> bool:
    if event.event_type != _PLANNED_DESKTOP_INTENT_EVENT_TYPE:
        return False
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return (
        _text(payload.get("source")) == "daily_desktop_metadata"
        and _text(payload.get("planning_reason")) == "structured_recovery_metadata"
    )


def _has_recovery_actions(source: Mapping[str, Any]) -> bool:
    actions = source.get("recovery_actions")
    if not isinstance(actions, list):
        return False
    return any(isinstance(action, Mapping) for action in actions)


def _progress_text(
    status: str,
    label: str,
    fallback: str,
    *,
    detail: str = "",
) -> str:
    if not label:
        return fallback
    parts = [status, label]
    clean_detail = _short_detail(detail)
    if clean_detail:
        parts.append(clean_detail)
    return " · ".join(parts)


def _foreground_lock_holder(result: Mapping[str, Any]) -> str:
    holder = _text(result.get("locked_by"))
    if holder:
        return holder
    foreground_lock = result.get("foreground_lock")
    if isinstance(foreground_lock, Mapping):
        return _text(foreground_lock.get("holder") or foreground_lock.get("locked_by"))
    return ""


def _fallback_detail(result: Mapping[str, Any]) -> str:
    fallback = _text(result.get("fallback") or result.get("fallback_tool"))
    fallback_labels = {
        "system_browser": "系统浏览器",
        "desktop.permissions": "权限诊断",
        "desktop.click": "桌面点击",
        "desktop.click_ui_element": "控件点击",
        "desktop.type_into_ui_element": "控件输入",
        "desktop.type_text": "桌面输入",
        "desktop.running_apps": "运行中应用",
        "desktop.list_apps": "已安装应用",
        "desktop.windows": "窗口列表",
        "desktop.ui_elements": "界面控件",
        "desktop.inspect_app": "应用检查",
        "app.status": "应用状态",
        "app.open": "打开应用",
        "app.focus_window": "聚焦应用窗口",
        "app.open_and_safe_type_text": "打开应用并输入文字",
        "app.focus_and_safe_type_text": "聚焦应用并输入文字",
        "app.open_and_safe_shortcut": "打开应用并执行快捷动作",
        "app.focus_and_safe_shortcut": "聚焦应用并执行快捷动作",
        "app.open_and_safe_key": "打开应用并按导航键",
        "app.focus_and_safe_key": "聚焦应用并按导航键",
        "app.open_and_hotkey": "打开应用并发送快捷键",
        "app.focus_and_hotkey": "聚焦应用并发送快捷键",
        "app.open_and_safe_scroll": "打开应用并滚动",
        "app.focus_and_safe_scroll": "聚焦应用并滚动",
        "app.open_and_safe_click": "打开应用并点击",
        "app.focus_and_safe_click": "聚焦应用并点击",
        "app.open_and_click_ui_element": "打开应用并点击控件",
        "app.focus_and_click_ui_element": "聚焦应用并点击控件",
        "app.open_and_type_into_ui_element": "打开应用并填写控件",
        "app.focus_and_type_into_ui_element": "聚焦应用并填写控件",
        "app.show": "显示应用",
        "app.hide": "隐藏应用",
        "app.minimize": "最小化应用",
        "app.quit": "退出应用",
        "desktop.quit_app": "退出当前应用",
        "desktop.reveal_path": "Finder 定位",
        "desktop.open_path": "打开本地路径",
        "desktop.open_path_with_app": "用应用打开本地路径",
        "app.open_path_with_app": "用应用打开本地路径",
        "desktop.safe_shortcut": "执行快捷动作",
        "desktop.safe_key": "前台按键",
        "desktop.safe_type_text": "桌面输入",
        "desktop.safe_click": "桌面点击",
        "desktop.safe_scroll": "桌面滚动",
        "desktop.hide_app": "隐藏当前应用",
        "desktop.show_all_apps": "显示隐藏应用",
        "desktop.minimize_window": "最小化当前窗口",
        "desktop.close_window": "关闭当前窗口",
    }
    if fallback:
        return fallback_labels.get(fallback, fallback)
    fallback_result = result.get("fallback_result")
    if isinstance(fallback_result, Mapping):
        action = _text(fallback_result.get("action"))
        if action:
            return fallback_labels.get(action, action)
    return ""


def _failure_detail(result: Mapping[str, Any]) -> str:
    error_code = _text(result.get("error_code"))
    error_labels = {
        "chrome_cdp_unavailable": "chrome_cdp",
        "app_not_found": "应用未找到",
    }
    if error_code:
        return error_labels.get(error_code, error_code)
    error = _text(result.get("error") or result.get("summary"))
    return error_labels.get(error, error)


def _unavailable_desktop_intent_detail(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("reason")) == "tool_not_allowed":
        return "工具未开启"
    blocked_by = _text(payload.get("blocked_by"))
    if blocked_by:
        return blocked_by
    return _text(payload.get("reason"))


def _result_text_list(result: Mapping[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            items = [_text(item) for item in value]
        elif isinstance(value, tuple):
            items = [_text(item) for item in value]
        else:
            items = [_text(value)] if value is not None else []
        items = [item for item in items if item]
        if items:
            return items
    return []


def _short_detail(value: str, *, limit: int = 80) -> str:
    text = _text(value)
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) > limit:
        return f"{compact[:limit]}..."
    return compact


def _event_tool_name(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("tool") or payload.get("tool_name") or event.detail)


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
