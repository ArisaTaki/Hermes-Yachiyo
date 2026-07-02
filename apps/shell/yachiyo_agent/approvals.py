"""Approval public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import ApprovalCardSnapshot
from .links import studio_run_url


def approval_card_from_payload(
    payload: Mapping[str, Any] | ApprovalCardSnapshot,
    *,
    run_id: str = "",
    group_run_id: str = "",
) -> ApprovalCardSnapshot:
    if isinstance(payload, ApprovalCardSnapshot):
        return payload

    approval_run_id = _optional_text(payload.get("run_id")) or _optional_text(run_id)
    approval_group_run_id = (
        _optional_text(payload.get("group_run_id"))
        or _optional_text(payload.get("run_group_id"))
        or _optional_text(group_run_id)
    )
    approval_id = _text(
        payload.get("approval_id")
        or payload.get("id")
        or payload.get("approval_signature")
        or approval_run_id
    )
    tool_name = _optional_text(payload.get("tool_name") or payload.get("tool"))
    title = _text(payload.get("title"))
    if not title:
        title = f"Approve {tool_name}" if tool_name else "Approval required"
    input_preview = _mapping(payload.get("input_preview") or payload.get("input"))

    return ApprovalCardSnapshot(
        approval_id=approval_id,
        run_id=approval_run_id,
        source_run_id=_optional_text(payload.get("source_run_id") or input_preview.get("source_run_id")),
        source_runnable_id=_optional_text(
            payload.get("source_runnable_id")
            or payload.get("source_agent_id")
            or payload.get("member_agent_id")
            or payload.get("agent_id")
            or input_preview.get("source_runnable_id")
            or input_preview.get("member_agent_id")
            or input_preview.get("agent_id")
        ),
        source_runnable_name=_optional_text(
            payload.get("source_runnable_name")
            or payload.get("source_agent_name")
            or payload.get("member_agent_name")
            or payload.get("agent_name")
            or input_preview.get("source_runnable_name")
            or input_preview.get("member_agent_name")
            or input_preview.get("agent_name")
        ),
        workflow_id=_optional_text(payload.get("workflow_id") or input_preview.get("workflow_id")),
        workflow_run_id=_optional_text(
            payload.get("workflow_run_id") or input_preview.get("workflow_run_id")
        ),
        workflow_node_id=_optional_text(
            payload.get("workflow_node_id") or input_preview.get("workflow_node_id")
        ),
        workflow_node_label=_optional_text(
            payload.get("workflow_node_label") or input_preview.get("workflow_node_label")
        ),
        group_id=_optional_text(payload.get("group_id") or input_preview.get("group_id")),
        group_run_id=approval_group_run_id
        or _optional_text(input_preview.get("group_run_id") or input_preview.get("run_group_id")),
        core_id=_trace_text(payload, input_preview, "core_id"),
        workspace_id=_trace_text(payload, input_preview, "workspace_id"),
        task_id=_trace_text(payload, input_preview, "task_id"),
        source=_trace_text(payload, input_preview, "source"),
        planning_reason=_trace_text(payload, input_preview, "planning_reason"),
        step_id=_trace_text(
            payload,
            input_preview,
            "step_id",
            "planner_step_id",
            "source_step_id",
        ),
        planner_step_id=_trace_text(payload, input_preview, "planner_step_id"),
        capability_id=_trace_text(
            payload,
            input_preview,
            "capability_id",
            "target_capability_id",
        ),
        decision_id=_trace_text(payload, input_preview, "decision_id"),
        plan_id=_trace_text(payload, input_preview, "plan_id", "runtime_plan_id"),
        tool_plan_id=_trace_text(payload, input_preview, "tool_plan_id"),
        intent_kind=_trace_text(payload, input_preview, "intent_kind", "task_intent_kind"),
        replan_request_id=_trace_text(payload, input_preview, "replan_request_id"),
        replan_trigger=_trace_text(payload, input_preview, "replan_trigger"),
        title=title,
        description=_optional_text(payload.get("description") or payload.get("reason")),
        status=_approval_status(payload.get("status")),
        tool_name=tool_name,
        risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
        input_preview=input_preview,
        policy_reason=_optional_text(payload.get("policy_reason")),
        requested_at=_text(payload.get("requested_at") or payload.get("created_at")),
        resolved_at=_optional_text(payload.get("resolved_at")),
        open_in_studio_url=(
            _optional_text(payload.get("open_in_studio_url"))
            or _studio_url(approval_run_id, approval_group_run_id)
        ),
    )


def approval_cards_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
    group_run_id: str = "",
) -> list[ApprovalCardSnapshot]:
    if isinstance(payloads, Mapping):
        return [
            approval_card_from_payload(payloads, run_id=run_id, group_run_id=group_run_id)
        ] if payloads else []
    if not isinstance(payloads, list):
        return []
    return [
        approval_card_from_payload(item, run_id=run_id, group_run_id=group_run_id)
        for item in payloads
    ]


def _approval_status(value: Any) -> str:
    status = _text(value)
    allowed = {"pending", "approved", "rejected", "cancelled", "expired"}
    return status if status in allowed else "pending"


def _mapping(value: Any) -> dict[str, Any]:
    redacted = redact_run_event_payload(dict(value)) if isinstance(value, Mapping) else {}
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _studio_url(run_id: str | None, group_run_id: str | None = None) -> str | None:
    return studio_run_url(run_id, group_run_id=group_run_id)


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _trace_text(
    payload: Mapping[str, Any],
    input_preview: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        text = _optional_text(payload.get(key))
        if text:
            return text
        text = _optional_text(input_preview.get(key))
        if text:
            return text
    return None
