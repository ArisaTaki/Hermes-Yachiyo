"""Public replan recovery projection from replayable RunEvents."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from apps.shell.agent.runtime.events import redact_json_value

from .contracts import (
    PublicRunEvent,
    ReplanRecoveryActionSnapshot,
    ReplanRecoverySnapshot,
    ToolCallSnapshot,
)
from .tool_call_event_snapshots import is_tool_event, tool_call_payloads_from_event
from .tool_call_payload_snapshots import tool_call_snapshot_from_payload


@dataclass
class _RecoveryRecord:
    request_id: str
    trigger: str = "tool_failure"
    status: str = "requested"
    sequence: int = 0
    run_id: str | None = None
    task_id: str | None = None
    group_run_id: str | None = None
    workflow_run_id: str | None = None
    decision_id: str | None = None
    plan_id: str | None = None
    core_id: str | None = None
    source_step_id: str | None = None
    source_tool_name: str | None = None
    target_capability_id: str = ""
    fallback_tools: list[str] = field(default_factory=list)
    verification_targets: list[dict[str, Any]] = field(default_factory=list)
    selected_tool_name: str | None = None
    selected_step_id: str | None = None
    planning_reason: str = ""
    recovery_actions: list[dict[str, Any]] = field(default_factory=list)
    recovery_action_label: str = ""
    permission_target: str = ""
    risk_level: str = ""
    action_target: dict[str, Any] = field(default_factory=dict)
    observation_evidence: dict[str, Any] = field(default_factory=dict)
    observation_retry: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None
    tool_status: str | None = None
    todo_status: str | None = None
    checkpoint_status: str | None = None
    failure_detail: str = ""
    result_preview: dict[str, Any] = field(default_factory=dict)
    recovery_event_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def replan_recovery_snapshots_from_events(
    events: Iterable[PublicRunEvent],
    *,
    run_id: str = "",
    task_id: str = "",
    group_run_id: str = "",
    workflow_run_id: str = "",
) -> list[ReplanRecoverySnapshot]:
    """Summarize request -> fallback plan -> fallback execution for Studio and Chat."""
    event_list = [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]
    records: dict[str, _RecoveryRecord] = {}
    order: list[str] = []

    for event in event_list:
        if _planner_event_type(event) != "agent.replan.requested":
            continue
        payload = _payload(event)
        request = payload.get("request") if isinstance(payload.get("request"), Mapping) else payload
        request_id = _text(
            request.get("request_id")
            or request.get("signal_id")
            or f"replan:{event.run_id or run_id}:{event.sequence}"
        )
        if not request_id:
            continue
        record = records.get(request_id)
        if record is None:
            record = _RecoveryRecord(request_id=request_id)
            records[request_id] = record
            order.append(request_id)
        _apply_request_event(
            record,
            event,
            request,
            run_id=run_id,
            task_id=task_id,
            group_run_id=group_run_id,
            workflow_run_id=workflow_run_id,
        )

    for event in event_list:
        payload = _payload(event)
        planner_event_type = _planner_event_type(event)
        if planner_event_type == "agent.desktop.intent_planned":
            _apply_planned_event(records, order, event, payload)
            continue
        if planner_event_type == "agent.replan.recovery.updated":
            _apply_recovery_update_event(records, order, event, payload)
            continue
        if _is_runtime_tool_event(event):
            _apply_tool_event(records, order, event)
            continue
        if str(event.event_type or "").strip().endswith(".task.todo.updated"):
            _apply_task_update_event(records, event, payload, kind="todo")
            continue
        if str(event.event_type or "").strip().endswith(".task.checkpoint.updated"):
            _apply_task_update_event(records, event, payload, kind="checkpoint")

    return [
        ReplanRecoverySnapshot(
            request_id=record.request_id,
            trigger=record.trigger,
            status=record.status,
            run_id=record.run_id or None,
            task_id=record.task_id or None,
            group_run_id=record.group_run_id or None,
            workflow_run_id=record.workflow_run_id or None,
            decision_id=record.decision_id or None,
            plan_id=record.plan_id or None,
            core_id=record.core_id or None,
            source_step_id=record.source_step_id or None,
            source_tool_name=record.source_tool_name or None,
            target_capability_id=record.target_capability_id,
            fallback_tools=list(record.fallback_tools),
            verification_targets=list(record.verification_targets),
            selected_tool_name=record.selected_tool_name or None,
            selected_step_id=record.selected_step_id or None,
            planning_reason=record.planning_reason,
            recovery_action_label=record.recovery_action_label,
            recovery_actions=_recovery_action_snapshots(record),
            permission_target=record.permission_target,
            risk_level=record.risk_level,
            action_target=dict(record.action_target),
            observation_evidence=dict(record.observation_evidence),
            observation_retry=dict(record.observation_retry),
            tool_call_id=record.tool_call_id or None,
            tool_status=record.tool_status or None,
            todo_status=record.todo_status or None,
            checkpoint_status=record.checkpoint_status or None,
            failure_detail=record.failure_detail,
            result_preview=dict(record.result_preview),
            recovery_event_ids=list(record.recovery_event_ids),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in (records[request_id] for request_id in order)
    ]


def merge_replan_recovery_snapshot_lists(
    *snapshot_lists: Iterable[ReplanRecoverySnapshot],
) -> list[ReplanRecoverySnapshot]:
    merged: dict[str, ReplanRecoverySnapshot] = {}
    order: list[str] = []
    for snapshots in snapshot_lists:
        for snapshot in snapshots:
            key = _text(snapshot.request_id)
            if not key:
                continue
            if key not in merged:
                merged[key] = snapshot
                order.append(key)
                continue
            merged[key] = _merge_recovery_snapshots(merged[key], snapshot)
    return [merged[key] for key in order]


def _apply_request_event(
    record: _RecoveryRecord,
    event: PublicRunEvent,
    request: Mapping[str, Any],
    *,
    run_id: str,
    task_id: str,
    group_run_id: str,
    workflow_run_id: str,
) -> None:
    record.sequence = int(event.sequence or 0)
    record.trigger = _text(request.get("trigger") or record.trigger or "tool_failure")
    _advance_status(record, _text(request.get("status") or "requested"))
    record.run_id = _first_text(record.run_id, request.get("run_id"), event.run_id, run_id)
    record.task_id = _first_text(record.task_id, request.get("task_id"), task_id)
    record.group_run_id = _first_text(
        record.group_run_id,
        request.get("group_run_id"),
        request.get("run_group_id"),
        event.group_run_id,
        group_run_id,
    )
    record.workflow_run_id = _first_text(
        record.workflow_run_id,
        request.get("workflow_run_id"),
        event.workflow_run_id,
        workflow_run_id,
    )
    record.decision_id = _first_text(record.decision_id, request.get("decision_id"))
    record.plan_id = _first_text(record.plan_id, request.get("plan_id"))
    record.core_id = _first_text(record.core_id, request.get("core_id"))
    record.source_step_id = _first_text(record.source_step_id, request.get("source_step_id"))
    record.source_tool_name = _first_text(
        record.source_tool_name,
        request.get("source_tool_name"),
        request.get("tool_name"),
        request.get("tool"),
    )
    record.target_capability_id = _first_text(
        record.target_capability_id,
        request.get("target_capability_id"),
        request.get("target"),
        request.get("capability_id"),
    )
    _extend_unique(record.fallback_tools, _string_list(request.get("fallback_tools")))
    _apply_verification_target_metadata(record, request)
    _apply_recovery_action_metadata(record, request)
    _apply_observed_action_metadata(record, request)
    record.failure_detail = _first_text(
        record.failure_detail,
        request.get("failure_detail"),
        request.get("condition"),
        request.get("reason"),
    )
    record.created_at = _first_text(record.created_at, event.created_at)
    _mark_event(record, event)


def _apply_planned_event(
    records: dict[str, _RecoveryRecord],
    order: list[str],
    event: PublicRunEvent,
    payload: Mapping[str, Any],
) -> None:
    record = _matching_record(records, order, event, payload, create_if_referenced=True)
    if record is None:
        return
    _advance_status(record, "planned")
    record.run_id = _first_text(record.run_id, payload.get("run_id"), event.run_id)
    record.task_id = _first_text(record.task_id, payload.get("task_id"))
    record.group_run_id = _first_text(
        record.group_run_id,
        payload.get("group_run_id"),
        payload.get("run_group_id"),
        event.group_run_id,
    )
    record.workflow_run_id = _first_text(
        record.workflow_run_id,
        payload.get("workflow_run_id"),
        event.workflow_run_id,
    )
    record.decision_id = _first_text(record.decision_id, payload.get("decision_id"))
    record.plan_id = _first_text(record.plan_id, payload.get("plan_id"))
    record.core_id = _first_text(record.core_id, payload.get("core_id"))
    record.source_step_id = _first_text(
        record.source_step_id,
        payload.get("source_step_id"),
        payload.get("step_id"),
        payload.get("planner_step_id"),
    )
    record.selected_step_id = _first_text(
        record.selected_step_id,
        payload.get("step_id"),
        payload.get("planner_step_id"),
    )
    record.target_capability_id = _first_text(
        record.target_capability_id,
        payload.get("capability_id"),
        payload.get("target_capability_id"),
    )
    selected_tool = _first_text(
        record.selected_tool_name,
        payload.get("tool_name"),
        payload.get("tool"),
    )
    record.selected_tool_name = selected_tool or None
    record.planning_reason = _first_text(
        record.planning_reason,
        payload.get("planning_reason"),
        payload.get("reason"),
    )
    _extend_unique(record.fallback_tools, _string_list(payload.get("fallback_tools")))
    _apply_verification_target_metadata(record, payload)
    _apply_recovery_action_metadata(record, payload, selected_tool=selected_tool)
    _apply_observed_action_metadata(record, payload)
    _mark_event(record, event)


def _apply_tool_event(
    records: dict[str, _RecoveryRecord],
    order: list[str],
    event: PublicRunEvent,
) -> None:
    tool_event = _tool_projection_event(event)
    for payload in tool_call_payloads_from_event(tool_event):
        call = tool_call_snapshot_from_payload(payload, run_id=event.run_id)
        record = _matching_record(
            records,
            order,
            event,
            payload,
            call=call,
            create_if_referenced=True,
        )
        if record is None:
            continue
        _advance_status(record, _recovery_status_from_tool(call.status))
        record.run_id = _first_text(record.run_id, call.run_id, event.run_id)
        record.group_run_id = _first_text(record.group_run_id, call.group_run_id, event.group_run_id)
        record.workflow_run_id = _first_text(
            record.workflow_run_id,
            call.workflow_run_id,
            event.workflow_run_id,
        )
        record.decision_id = _first_text(record.decision_id, call.decision_id)
        record.plan_id = _first_text(record.plan_id, call.plan_id)
        record.source_step_id = _first_text(record.source_step_id, call.step_id, call.planner_step_id)
        record.selected_step_id = _first_text(
            record.selected_step_id,
            call.step_id,
            call.planner_step_id,
        )
        record.target_capability_id = _first_text(record.target_capability_id, call.capability_id)
        record.selected_tool_name = _first_text(record.selected_tool_name, call.tool_name)
        record.tool_call_id = _first_text(record.tool_call_id, call.tool_call_id)
        record.tool_status = _first_text(record.tool_status, call.status)
        record.planning_reason = _first_text(
            payload.get("planning_reason"),
            payload.get("reason"),
            record.planning_reason,
        )
        _apply_verification_target_metadata(record, payload, call=call)
        _apply_recovery_action_metadata(
            record,
            payload,
            selected_tool=record.selected_tool_name or call.tool_name,
        )
        _apply_observed_action_metadata(record, payload, call=call)
        record.result_preview = _mapping(call.output_preview)
        _mark_event(record, event)


def _apply_task_update_event(
    records: dict[str, _RecoveryRecord],
    event: PublicRunEvent,
    payload: Mapping[str, Any],
    *,
    kind: str,
) -> None:
    record = _matching_record(records, [], event, payload, create_if_referenced=False)
    if record is None:
        return
    status = _text(payload.get("status"))
    if kind == "todo":
        nested = payload.get("todo") if isinstance(payload.get("todo"), Mapping) else {}
        record.todo_status = _first_text(record.todo_status, status, nested.get("status"))
    else:
        nested = payload.get("checkpoint") if isinstance(payload.get("checkpoint"), Mapping) else {}
        record.checkpoint_status = _first_text(record.checkpoint_status, status, nested.get("status"))
    _advance_status(
        record,
        _recovery_status_from_task_status(record.checkpoint_status or record.todo_status or status),
    )
    _mark_event(record, event)


def _apply_recovery_update_event(
    records: dict[str, _RecoveryRecord],
    order: list[str],
    event: PublicRunEvent,
    payload: Mapping[str, Any],
) -> None:
    record = _matching_record(records, order, event, payload, create_if_referenced=True)
    if record is None:
        return
    status = _text(payload.get("status"))
    _advance_status(record, status)
    record.run_id = _first_text(record.run_id, payload.get("run_id"), event.run_id)
    record.task_id = _first_text(record.task_id, payload.get("task_id"))
    record.group_run_id = _first_text(
        record.group_run_id,
        payload.get("group_run_id"),
        payload.get("run_group_id"),
        event.group_run_id,
    )
    record.workflow_run_id = _first_text(
        record.workflow_run_id,
        payload.get("workflow_run_id"),
        event.workflow_run_id,
    )
    record.decision_id = _first_text(record.decision_id, payload.get("decision_id"))
    record.plan_id = _first_text(record.plan_id, payload.get("plan_id"))
    record.core_id = _first_text(record.core_id, payload.get("core_id"))
    record.source_step_id = _first_text(
        record.source_step_id,
        payload.get("source_step_id"),
        payload.get("step_id"),
        payload.get("planner_step_id"),
    )
    record.source_tool_name = _first_text(
        record.source_tool_name,
        payload.get("source_tool_name"),
    )
    record.target_capability_id = _first_text(
        record.target_capability_id,
        payload.get("target_capability_id"),
        payload.get("capability_id"),
    )
    record.selected_step_id = _first_text(
        record.selected_step_id,
        payload.get("selected_step_id"),
        payload.get("step_id"),
        payload.get("planner_step_id"),
    )
    selected_tool = _first_text(
        record.selected_tool_name,
        payload.get("selected_tool_name"),
        payload.get("tool_name"),
        payload.get("tool"),
    )
    record.selected_tool_name = selected_tool or None
    record.planning_reason = _first_text(
        payload.get("planning_reason"),
        payload.get("reason"),
        record.planning_reason,
    )
    _extend_unique(record.fallback_tools, _string_list(payload.get("fallback_tools")))
    if selected_tool and selected_tool not in record.fallback_tools:
        record.fallback_tools.append(selected_tool)
    _apply_verification_target_metadata(record, payload)
    record.tool_status = _first_text(payload.get("tool_status"), status, record.tool_status)
    record.todo_status = _first_text(payload.get("todo_status"), record.todo_status)
    record.checkpoint_status = _first_text(
        payload.get("checkpoint_status"),
        record.checkpoint_status,
    )
    result_preview = _mapping(payload.get("result_preview"))
    if result_preview:
        record.result_preview.update(result_preview)
    record.failure_detail = _first_text(
        record.failure_detail,
        payload.get("failure_detail"),
    )
    _apply_recovery_action_metadata(record, payload, selected_tool=selected_tool)
    _apply_observed_action_metadata(record, payload)
    _mark_event(record, event)


def _matching_record(
    records: dict[str, _RecoveryRecord],
    order: list[str],
    event: PublicRunEvent,
    payload: Mapping[str, Any],
    *,
    call: ToolCallSnapshot | None = None,
    create_if_referenced: bool = False,
) -> _RecoveryRecord | None:
    request_id = _text(
        payload.get("replan_request_id")
        or payload.get("request_id")
        or (call.replan_request_id if call else "")
    )
    if request_id:
        record = records.get(request_id)
        if record is None and create_if_referenced:
            record = _RecoveryRecord(
                request_id=request_id,
                trigger=_text(payload.get("replan_trigger") or "tool_failure"),
                sequence=int(event.sequence or 0),
            )
            records[request_id] = record
            order.append(request_id)
        return record

    step_id = _text(
        payload.get("step_id")
        or payload.get("planner_step_id")
        or payload.get("source_step_id")
        or (call.step_id if call else "")
        or (call.planner_step_id if call else "")
    )
    if not step_id:
        return None
    event_sequence = int(event.sequence or 0)
    for record in records.values():
        if _text(record.source_step_id) != step_id:
            continue
        if record.sequence and event_sequence and event_sequence < record.sequence:
            continue
        return record
    return None


def _merge_recovery_snapshots(
    current: ReplanRecoverySnapshot,
    incoming: ReplanRecoverySnapshot,
) -> ReplanRecoverySnapshot:
    result_preview = dict(current.result_preview or {})
    if incoming.result_preview:
        result_preview.update(incoming.result_preview)
    action_target = dict(current.action_target or {})
    if incoming.action_target:
        action_target.update(incoming.action_target)
    observation_evidence = dict(current.observation_evidence or {})
    if incoming.observation_evidence:
        observation_evidence.update(incoming.observation_evidence)
    observation_retry = dict(current.observation_retry or {})
    if incoming.observation_retry:
        observation_retry.update(incoming.observation_retry)
    verification_targets = list(current.verification_targets or [])
    _extend_unique_mappings(verification_targets, incoming.verification_targets)
    recovery_actions = _merged_recovery_action_snapshots(
        current.recovery_actions,
        incoming.recovery_actions,
    )
    event_ids = list(current.recovery_event_ids)
    _extend_unique(event_ids, incoming.recovery_event_ids)
    return current.model_copy(
        update={
            "status": _stronger_status(current.status, incoming.status),
            "run_id": current.run_id or incoming.run_id,
            "task_id": current.task_id or incoming.task_id,
            "group_run_id": current.group_run_id or incoming.group_run_id,
            "workflow_run_id": current.workflow_run_id or incoming.workflow_run_id,
            "decision_id": current.decision_id or incoming.decision_id,
            "plan_id": current.plan_id or incoming.plan_id,
            "core_id": current.core_id or incoming.core_id,
            "source_step_id": current.source_step_id or incoming.source_step_id,
            "source_tool_name": current.source_tool_name or incoming.source_tool_name,
            "target_capability_id": current.target_capability_id or incoming.target_capability_id,
            "fallback_tools": _merged_string_lists(current.fallback_tools, incoming.fallback_tools),
            "verification_targets": verification_targets,
            "selected_tool_name": current.selected_tool_name or incoming.selected_tool_name,
            "selected_step_id": current.selected_step_id or incoming.selected_step_id,
            "planning_reason": current.planning_reason or incoming.planning_reason,
            "recovery_action_label": current.recovery_action_label
            or incoming.recovery_action_label,
            "recovery_actions": recovery_actions,
            "permission_target": current.permission_target or incoming.permission_target,
            "risk_level": current.risk_level or incoming.risk_level,
            "action_target": action_target,
            "observation_evidence": observation_evidence,
            "observation_retry": observation_retry,
            "tool_call_id": current.tool_call_id or incoming.tool_call_id,
            "tool_status": current.tool_status or incoming.tool_status,
            "todo_status": current.todo_status or incoming.todo_status,
            "checkpoint_status": current.checkpoint_status or incoming.checkpoint_status,
            "failure_detail": current.failure_detail or incoming.failure_detail,
            "result_preview": result_preview,
            "recovery_event_ids": event_ids,
            "created_at": current.created_at or incoming.created_at,
            "updated_at": incoming.updated_at or current.updated_at,
        }
    )


def _planner_event_type(event: PublicRunEvent) -> str:
    payload = _payload(event)
    explicit = _text(payload.get("planner_event_type"))
    if explicit:
        return explicit
    event_type = _text(event.event_type)
    if event_type.endswith(".replan.requested"):
        return "agent.replan.requested"
    if event_type.endswith(".replan.recovery.updated"):
        return "agent.replan.recovery.updated"
    if event_type.endswith(".desktop.intent_planned"):
        return "agent.desktop.intent_planned"
    return _SCOPED_PLANNER_EVENT_TYPES.get(event_type, event_type)


def _is_runtime_tool_event(event: PublicRunEvent) -> bool:
    event_type = _text(event.event_type)
    return is_tool_event(event_type) or is_tool_event(_unscoped_tool_event_type(event_type))


def _tool_projection_event(event: PublicRunEvent) -> PublicRunEvent:
    unscoped_event_type = _unscoped_tool_event_type(event.event_type)
    if unscoped_event_type == event.event_type:
        return event
    return event.model_copy(update={"event_type": unscoped_event_type})


def _unscoped_tool_event_type(event_type: str) -> str:
    clean = _text(event_type)
    for prefix in ("group.run.", "workflow.run.", "workflow."):
        if clean.startswith(f"{prefix}tool."):
            return f"agent.tool.{clean.removeprefix(f'{prefix}tool.')}"
        if clean.startswith(f"{prefix}desktop."):
            return f"agent.desktop.{clean.removeprefix(f'{prefix}desktop.')}"
    return clean


def _recovery_status_from_tool(status: str) -> str:
    clean = _text(status).lower()
    if clean in {"completed", "complete", "success", "succeeded", "ok", "approved"}:
        return "completed"
    if clean in {"running", "started", "in_progress", "requested", "resolved"}:
        return "running"
    if clean in {"waiting_approval", "approval_required", "requires_approval"}:
        return "waiting_approval"
    if clean in {
        "failed",
        "failure",
        "error",
        "blocked",
        "denied",
        "rejected",
        "skipped",
        "expired",
        "cancelled",
        "unavailable",
    }:
        return "blocked"
    return "running" if clean else "planned"


def _recovery_status_from_task_status(status: str) -> str:
    clean = _text(status).lower()
    if clean == "completed":
        return "completed"
    if clean in {"blocked", "failed", "waiting_approval"}:
        return "blocked" if clean != "waiting_approval" else "waiting_approval"
    if clean in {"in_progress", "ready", "running"}:
        return "running"
    if clean in {"pending", "planned"}:
        return "planned"
    return ""


def _stronger_status(current: str, candidate: str) -> str:
    clean_current = _text(current) or "requested"
    clean_candidate = _text(candidate) or clean_current
    return (
        clean_candidate
        if _STATUS_RANK.get(clean_candidate, 0) >= _STATUS_RANK.get(clean_current, 0)
        else clean_current
    )


def _advance_status(record: _RecoveryRecord, candidate: str) -> None:
    clean = _text(candidate)
    if not clean:
        return
    if clean in {"waiting_approval", "blocked", "completed"}:
        record.status = clean
        return
    record.status = _stronger_status(record.status, clean)


def _mark_event(record: _RecoveryRecord, event: PublicRunEvent) -> None:
    event_id = _text(event.event_id) or f"{event.sequence}:{event.event_type}"
    if event_id and event_id not in record.recovery_event_ids:
        record.recovery_event_ids.append(event_id)
    record.updated_at = _first_text(event.created_at, record.updated_at)


def _apply_recovery_action_metadata(
    record: _RecoveryRecord,
    payload: Mapping[str, Any],
    *,
    selected_tool: str = "",
) -> None:
    for action in _recovery_action_records(payload):
        _append_unique_mapping(record.recovery_actions, action)

    selected_action = _selected_recovery_action(
        record.recovery_actions,
        _first_text(selected_tool, payload.get("tool_name"), payload.get("tool")),
    )
    record.recovery_action_label = _first_text(
        payload.get("recovery_action_label"),
        payload.get("recovery_label"),
        selected_action.get("label") if selected_action else "",
        selected_action.get("prompt") if selected_action else "",
        selected_action.get("tool") if selected_action else "",
        record.recovery_action_label,
    )
    record.permission_target = _first_text(
        payload.get("permission_target"),
        payload.get("recovery_permission_target"),
        selected_action.get("permission_target") if selected_action else "",
        selected_action.get("permission") if selected_action else "",
        record.permission_target,
    )
    record.risk_level = _first_text(
        payload.get("risk_level"),
        payload.get("recovery_risk_level"),
        selected_action.get("risk_level") if selected_action else "",
        record.risk_level,
    )


def _recovery_action_snapshots(
    record: _RecoveryRecord,
) -> list[ReplanRecoveryActionSnapshot]:
    actions: list[ReplanRecoveryActionSnapshot] = []
    seen: set[str] = set()
    selected_tool = _text(record.selected_tool_name)
    for index, action in enumerate(record.recovery_actions):
        tool = _first_text(action.get("tool"), action.get("tool_name"), action.get("recovery_tool"))
        if not tool:
            continue
        action_input = _mapping(action.get("input") or action.get("recovery_input"))
        signature = _recovery_action_signature(tool, action_input)
        if signature in seen:
            continue
        seen.add(signature)
        selected = bool(action.get("selected")) or bool(selected_tool and tool == selected_tool)
        action_target = _mapping(action.get("action_target"))
        observation_evidence = _mapping(action.get("observation_evidence"))
        observation_retry = _mapping(action.get("observation_retry"))
        verification_targets = _verification_target_records(action)
        if selected:
            if not action_target:
                action_target = dict(record.action_target)
            if not observation_evidence:
                observation_evidence = dict(record.observation_evidence)
            if not observation_retry:
                observation_retry = dict(record.observation_retry)
            _extend_unique_mappings(verification_targets, record.verification_targets)
        action_id = _first_text(
            action.get("action_id"),
            action.get("id"),
            f"{record.request_id}:action:{index + 1}:{tool}",
        )
        actions.append(
            ReplanRecoveryActionSnapshot(
                action_id=action_id,
                label=_first_text(
                    action.get("label"),
                    action.get("title"),
                    action.get("prompt"),
                    tool,
                ),
                tool=tool,
                input=action_input,
                planning_reason=_first_text(
                    action.get("planning_reason"),
                    action.get("reason"),
                    record.planning_reason,
                ),
                permission_target=_first_text(
                    action.get("permission_target"),
                    action.get("permission"),
                    record.permission_target,
                ),
                risk_level=_first_text(action.get("risk_level"), record.risk_level),
                approval_required=bool(
                    action.get("approval_required")
                    or action.get("requires_approval")
                    or action.get("requiresApproval")
                ),
                selected=selected,
                action_target=action_target,
                observation_evidence=observation_evidence,
                observation_retry=observation_retry,
                verification_targets=verification_targets,
                metadata=_recovery_action_metadata(action, index=index),
            )
        )
    return actions


def _merged_recovery_action_snapshots(
    current: list[ReplanRecoveryActionSnapshot],
    incoming: list[ReplanRecoveryActionSnapshot],
) -> list[ReplanRecoveryActionSnapshot]:
    merged = list(current or [])
    seen = {
        _recovery_action_signature(action.tool, action.input)
        for action in merged
        if _text(action.tool)
    }
    for action in incoming or []:
        signature = _recovery_action_signature(action.tool, action.input)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        merged.append(action)
    return merged


def _recovery_action_metadata(action: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    metadata = _mapping(action.get("metadata"))
    recommended_tools = _string_list(action.get("recommended_tools"))
    if recommended_tools:
        metadata["recommended_tools"] = recommended_tools
    metadata.setdefault("source_action_index", index)
    return metadata


def _recovery_action_signature(tool: str, action_input: Mapping[str, Any]) -> str:
    clean_tool = _text(tool)
    if not clean_tool:
        return ""
    try:
        input_signature = repr(sorted(dict(action_input or {}).items()))
    except Exception:
        input_signature = repr(action_input)
    return f"{clean_tool}:{input_signature}"


def _apply_observed_action_metadata(
    record: _RecoveryRecord,
    payload: Mapping[str, Any],
    *,
    call: ToolCallSnapshot | None = None,
) -> None:
    action_target = _observed_mapping(payload, "action_target")
    observation_evidence = _observed_mapping(payload, "observation_evidence")
    observation_retry = _observed_mapping(payload, "observation_retry")
    if call is not None:
        if not action_target:
            action_target = _mapping(call.metadata.get("action_target"))
        if not observation_evidence:
            observation_evidence = _mapping(call.metadata.get("observation_evidence"))
        if not observation_retry:
            observation_retry = _mapping(call.metadata.get("observation_retry"))
    if action_target:
        record.action_target.update(action_target)
    if observation_evidence:
        record.observation_evidence.update(observation_evidence)
    if observation_retry:
        record.observation_retry.update(observation_retry)


def _apply_verification_target_metadata(
    record: _RecoveryRecord,
    payload: Mapping[str, Any],
    *,
    call: ToolCallSnapshot | None = None,
) -> None:
    targets = _verification_target_records(payload)
    if call is not None and not targets:
        targets = _verification_target_records(call.metadata)
    _extend_unique_mappings(record.verification_targets, targets)


def _verification_target_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    _extend_unique_mappings(records, payload.get("verification_targets"))
    _extend_unique_mappings(records, payload.get("task_verification_targets"))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    _extend_unique_mappings(records, metadata.get("verification_targets"))
    _extend_unique_mappings(records, metadata.get("task_verification_targets"))
    return records


def _observed_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = _mapping(payload.get(key))
    if value:
        return value
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return _mapping(metadata.get(key))


def _recovery_action_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    _extend_action_records(records, payload.get("recovery_actions"))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    _extend_action_records(records, metadata.get("recovery_actions"))
    return records


def _extend_action_records(target: list[dict[str, Any]], value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, Mapping):
            _append_unique_mapping(target, item)


def _append_unique_mapping(target: list[dict[str, Any]], value: Mapping[str, Any]) -> None:
    clean = _mapping(value)
    if clean and clean not in target:
        target.append(clean)


def _extend_unique_mappings(target: list[dict[str, Any]], value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, Mapping):
            _append_unique_mapping(target, item)


def _selected_recovery_action(
    actions: list[dict[str, Any]],
    selected_tool: str,
) -> dict[str, Any]:
    if not actions:
        return {}
    clean_tool = _text(selected_tool)
    if clean_tool:
        for action in actions:
            if _text(action.get("tool") or action.get("tool_name")) == clean_tool:
                return action
            recommended_tools = _string_list(action.get("recommended_tools"))
            if clean_tool in recommended_tools:
                return action
    return actions[0]


def _payload(event: PublicRunEvent) -> Mapping[str, Any]:
    return event.payload if isinstance(event.payload, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_json_value(dict(value))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _merged_string_lists(*values: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for value in values:
        _extend_unique(merged, value)
    return merged


def _extend_unique(target: list[str], values: Iterable[Any]) -> None:
    for value in values:
        clean = _text(value)
        if clean and clean not in target:
            target.append(clean)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _first_text(*values: Any) -> str:
    for value in values:
        clean = _text(value)
        if clean:
            return clean
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


_SCOPED_PLANNER_EVENT_TYPES = {
    "group.run.replan.requested": "agent.replan.requested",
    "workflow.replan.requested": "agent.replan.requested",
    "workflow.run.replan.requested": "agent.replan.requested",
    "group.run.replan.recovery.updated": "agent.replan.recovery.updated",
    "workflow.replan.recovery.updated": "agent.replan.recovery.updated",
    "workflow.run.replan.recovery.updated": "agent.replan.recovery.updated",
    "group.run.desktop.intent_planned": "agent.desktop.intent_planned",
    "workflow.desktop.intent_planned": "agent.desktop.intent_planned",
    "workflow.run.desktop.intent_planned": "agent.desktop.intent_planned",
}

_STATUS_RANK = {
    "requested": 0,
    "planned": 1,
    "running": 2,
    "waiting_approval": 3,
    "blocked": 4,
    "completed": 5,
}
