"""Approval public snapshots derived from replayable RunEvents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .approval_event_correlation import (
    ApprovalEventCorrelationTracker,
    approval_correlation_keys,
)
from .approval_snapshot_merging import (
    merge_approval_snapshot_lists,
    merge_approval_snapshots,
)
from .approvals import approval_card_from_payload
from .contracts import ApprovalCardSnapshot, PublicRunEvent


def approval_snapshots_from_events(
    events: list[PublicRunEvent],
    *,
    group_run_id: str = "",
) -> list[ApprovalCardSnapshot]:
    approvals: list[ApprovalCardSnapshot] = []
    correlation = ApprovalEventCorrelationTracker()
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
        strong_keys, weak_key = approval_correlation_keys(approval_payload, approval)
        active_index = correlation.active_index(
            strong_keys,
            weak_key,
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
            correlation.register_pending(
                active_index,
                strong_keys,
                weak_key,
            )
        else:
            correlation.unregister(active_index)
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


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
