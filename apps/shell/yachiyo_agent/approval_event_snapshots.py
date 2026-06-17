"""Approval public snapshots derived from replayable RunEvents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .approvals import approval_card_from_payload
from .contracts import ApprovalCardSnapshot, PublicRunEvent

_AMBIGUOUS_APPROVAL_INDEX = -1


def approval_snapshots_from_events(
    events: list[PublicRunEvent],
    *,
    group_run_id: str = "",
) -> list[ApprovalCardSnapshot]:
    approvals: list[ApprovalCardSnapshot] = []
    active_by_strong_key: dict[str, int] = {}
    active_by_weak_key: dict[str, int] = {}
    active_keys_by_index: dict[int, tuple[list[str], str]] = {}
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        approval_payload = approval_payload_from_event(event)
        if not approval_payload:
            continue
        if group_run_id:
            merge_trace_context_into_approval(
                approval_payload,
                {"group_run_id": group_run_id},
            )
        approval = approval_card_from_payload(
            approval_payload,
            run_id=event.run_id,
            group_run_id=group_run_id or _group_run_id(event.payload),
        )
        strong_keys, weak_key = _approval_correlation_keys(approval_payload, approval)
        active_index = _active_approval_index(
            strong_keys,
            weak_key,
            active_by_strong_key,
            active_by_weak_key,
            allow_weak=approval.status != "pending",
        )
        if active_index is None:
            active_index = len(approvals)
            approvals.append(approval)
        else:
            approvals[active_index] = merge_approval_snapshots(
                approvals[active_index],
                approval,
            )
        if approval.status == "pending":
            _register_active_approval(
                active_index,
                strong_keys,
                weak_key,
                active_by_strong_key,
                active_by_weak_key,
                active_keys_by_index,
            )
        else:
            _unregister_active_approval(
                active_index,
                active_by_strong_key,
                active_by_weak_key,
                active_keys_by_index,
            )
    return approvals


def approval_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    if event.event_type in {
        "agent.tool.approval_required",
        "approval.required",
        "group.approval_required",
        "group.member.approval_required",
        "tool.approval_required",
        "workflow.node.approval_required",
        "workflow.run.approval_required",
    }:
        return _approval_required_payload_from_event(event)
    if event.event_type in {
        "agent.tool.approval_approved",
        "agent.tool.approval_rejected",
        "agent.tool.approval_timeout",
        "agent.tool.approval_cancelled",
        "approval.approved",
        "approval.cancelled",
        "approval.rejected",
        "approval.timeout",
        "tool.approved",
        "tool.approval_cancelled",
        "tool.rejected",
        "workflow.node.approval_approved",
        "workflow.node.approval_cancelled",
        "workflow.node.approval_rejected",
        "workflow.node.approval_timeout",
    }:
        return _approval_resolution_payload_from_event(event)
    return {}


def merge_trace_context_into_approval(source: dict[str, Any], payload: dict[str, Any]) -> None:
    context = {
        key: payload.get(key)
        for key in (
            "group_id",
            "group_run_id",
            "run_group_id",
            "member_agent_id",
            "member_agent_name",
            "workflow_id",
            "workflow_run_id",
            "workflow_node_id",
            "workflow_node_label",
        )
        if payload.get(key)
    }
    if not context:
        return
    for key, value in context.items():
        source.setdefault(key, value)
    input_preview = source.get("input_preview")
    preview = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    for key, value in context.items():
        preview.setdefault(key, value)
    if preview:
        source["input_preview"] = preview


def merge_approval_snapshots(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> ApprovalCardSnapshot:
    return ApprovalCardSnapshot(
        approval_id=current.approval_id or next_approval.approval_id,
        run_id=current.run_id or next_approval.run_id,
        source_run_id=current.source_run_id or next_approval.source_run_id,
        source_runnable_id=current.source_runnable_id or next_approval.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_approval.source_runnable_name,
        workflow_id=current.workflow_id or next_approval.workflow_id,
        workflow_run_id=current.workflow_run_id or next_approval.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_approval.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_approval.workflow_node_label,
        group_id=current.group_id or next_approval.group_id,
        group_run_id=current.group_run_id or next_approval.group_run_id,
        title=current.title or next_approval.title,
        description=next_approval.description or current.description,
        status=next_approval.status or current.status,
        tool_name=current.tool_name or next_approval.tool_name,
        risk_level=current.risk_level or next_approval.risk_level,
        input_preview={**current.input_preview, **next_approval.input_preview},
        policy_reason=current.policy_reason or next_approval.policy_reason,
        requested_at=current.requested_at or next_approval.requested_at,
        resolved_at=next_approval.resolved_at or current.resolved_at,
        open_in_studio_url=current.open_in_studio_url or next_approval.open_in_studio_url,
    )


def _approval_required_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    pending = payload.get("pending_approval") or payload.get("approval")
    source = dict(pending) if isinstance(pending, Mapping) else payload
    if not source and event.detail:
        source = {"tool": event.detail}
    if not source:
        return {}
    _normalize_approval_payload_for_event(source, event, payload)
    source.setdefault("approval_id", f"{event.run_id}:{event.event_type}:{event.sequence}")
    source.setdefault("status", "pending")
    source.setdefault("created_at", event.created_at)
    source.setdefault("run_id", event.run_id)
    return source


def _approval_resolution_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    pending = payload.get("pending_approval") or payload.get("approval")
    source = dict(pending) if isinstance(pending, Mapping) else payload
    if not source and event.detail:
        source = {"tool": event.detail}
    if not source:
        return {}
    _normalize_approval_payload_for_event(source, event, payload)
    source["status"] = _approval_status_from_event_type(event.event_type)
    source.setdefault("resolved_at", event.created_at)
    source.setdefault("run_id", event.run_id)
    if payload.get("reason") and not source.get("reason") and not source.get("description"):
        source["reason"] = payload.get("reason")
    if not source.get("approval_id"):
        source["approval_id"] = f"{event.run_id}:{event.event_type}:{event.sequence}"
    return source


def _normalize_approval_payload_for_event(
    source: dict[str, Any],
    event: PublicRunEvent,
    payload: dict[str, Any],
) -> None:
    if event.event_type.startswith("group.") and not source.get("tool"):
        source["tool"] = "group.approval"
    if (
        event.event_type.startswith("workflow.")
        or payload.get("workflow_node_id")
        or payload.get("workflow_run_id")
    ) and not source.get("tool"):
        source["tool"] = "workflow.approval"
    if not source.get("tool") and payload.get("tool"):
        source["tool"] = payload.get("tool")
    if not source.get("tool") and event.detail:
        source["tool"] = event.detail
    if not source.get("title") and payload.get("workflow_node_label"):
        source["title"] = f"Approve {payload['workflow_node_label']}"
    if not source.get("title") and payload.get("member_agent_name"):
        source["title"] = f"Approve {payload['member_agent_name']}"
    merge_trace_context_into_approval(source, payload)


def _approval_status_from_event_type(event_type: str) -> str:
    if event_type.endswith("approval_approved") or event_type in {"approval.approved", "tool.approved"}:
        return "approved"
    if event_type.endswith("approval_rejected") or event_type in {"approval.rejected", "tool.rejected"}:
        return "rejected"
    if event_type.endswith("approval_cancelled") or event_type == "approval.cancelled":
        return "cancelled"
    if event_type.endswith("approval_timeout") or event_type == "approval.timeout":
        return "expired"
    return "pending"


def _approval_correlation_keys(
    payload: Mapping[str, Any],
    approval: ApprovalCardSnapshot,
) -> tuple[list[str], str]:
    run_id = approval.run_id or _text(payload.get("run_id"))
    tool_name = approval.tool_name or _text(payload.get("tool") or payload.get("tool_name"))
    preview = _approval_correlation_preview(approval.input_preview)
    workflow_node_id = _text(
        payload.get("workflow_node_id")
        or approval.workflow_node_id
        or approval.input_preview.get("workflow_node_id")
    )
    group_run_id = _text(
        payload.get("group_run_id")
        or payload.get("run_group_id")
        or approval.group_run_id
        or approval.input_preview.get("group_run_id")
        or approval.input_preview.get("run_group_id")
    )
    source_runnable_id = _text(
        payload.get("source_runnable_id")
        or payload.get("member_agent_id")
        or payload.get("agent_id")
        or approval.source_runnable_id
        or approval.input_preview.get("source_runnable_id")
        or approval.input_preview.get("member_agent_id")
        or approval.input_preview.get("agent_id")
    )

    base_parts = [
        run_id,
        "approval",
        tool_name,
        workflow_node_id,
        group_run_id,
        source_runnable_id,
    ]
    strong_keys = []

    explicit_id = _text(
        payload.get("approval_id")
        or payload.get("id")
        or payload.get("approval_signature")
        or approval.approval_id
    )
    if explicit_id:
        strong_keys.append(f"{run_id}:approval_id:{explicit_id}")
    if tool_name or workflow_node_id or group_run_id or source_runnable_id or preview:
        strong_keys.append(":".join([*base_parts, _stable_json(preview)]))
    weak_key = ":".join(base_parts) if any(base_parts[2:]) else ""
    return list(dict.fromkeys(strong_keys)), weak_key


def _active_approval_index(
    strong_keys: list[str],
    weak_key: str,
    active_by_strong_key: Mapping[str, int],
    active_by_weak_key: Mapping[str, int],
    *,
    allow_weak: bool,
) -> int | None:
    for key in strong_keys:
        if key in active_by_strong_key:
            return active_by_strong_key[key]
    if not allow_weak:
        return None
    weak_index = active_by_weak_key.get(weak_key) if weak_key else None
    if weak_index is not None and weak_index != _AMBIGUOUS_APPROVAL_INDEX:
        return weak_index
    return None


def _register_active_approval(
    index: int,
    strong_keys: list[str],
    weak_key: str,
    active_by_strong_key: dict[str, int],
    active_by_weak_key: dict[str, int],
    active_keys_by_index: dict[int, tuple[list[str], str]],
) -> None:
    for key in strong_keys:
        active_by_strong_key[key] = index
    if weak_key:
        existing = active_by_weak_key.get(weak_key)
        if existing is None:
            active_by_weak_key[weak_key] = index
        elif existing != index:
            active_by_weak_key[weak_key] = _AMBIGUOUS_APPROVAL_INDEX
    active_keys_by_index[index] = (strong_keys, weak_key)


def _unregister_active_approval(
    index: int,
    active_by_strong_key: dict[str, int],
    active_by_weak_key: dict[str, int],
    active_keys_by_index: dict[int, tuple[list[str], str]],
) -> None:
    strong_keys, weak_key = active_keys_by_index.pop(index, ([], ""))
    for key in strong_keys:
        if active_by_strong_key.get(key) == index:
            active_by_strong_key.pop(key, None)
    if weak_key and active_by_weak_key.get(weak_key) == index:
        active_by_weak_key.pop(weak_key, None)


def _approval_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "agent_id",
        "agent_name",
        "approval_id",
        "group_id",
        "group_run_id",
        "member_agent_id",
        "member_agent_name",
        "policy_reason",
        "risk_level",
        "run_id",
        "run_group_id",
        "source_agent_id",
        "source_agent_name",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "source_tool",
        "tool_call_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_kind",
        "workflow_node_label",
        "workflow_run_id",
        "workflow_step_label",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
