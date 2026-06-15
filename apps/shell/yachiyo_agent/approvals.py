"""Approval public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import ApprovalCardSnapshot


def approval_card_from_payload(
    payload: Mapping[str, Any] | ApprovalCardSnapshot,
    *,
    run_id: str = "",
) -> ApprovalCardSnapshot:
    if isinstance(payload, ApprovalCardSnapshot):
        return payload

    approval_run_id = _optional_text(payload.get("run_id")) or _optional_text(run_id)
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

    return ApprovalCardSnapshot(
        approval_id=approval_id,
        run_id=approval_run_id,
        title=title,
        description=_optional_text(payload.get("description") or payload.get("reason")),
        status=_approval_status(payload.get("status")),
        tool_name=tool_name,
        risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
        input_preview=_mapping(payload.get("input_preview") or payload.get("input")),
        policy_reason=_optional_text(payload.get("policy_reason")),
        requested_at=_text(payload.get("requested_at") or payload.get("created_at")),
        resolved_at=_optional_text(payload.get("resolved_at")),
        open_in_studio_url=_studio_url(approval_run_id),
    )


def approval_cards_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
) -> list[ApprovalCardSnapshot]:
    if isinstance(payloads, Mapping):
        return [approval_card_from_payload(payloads, run_id=run_id)] if payloads else []
    if not isinstance(payloads, list):
        return []
    return [approval_card_from_payload(item, run_id=run_id) for item in payloads]


def _approval_status(value: Any) -> str:
    status = _text(value)
    allowed = {"pending", "approved", "rejected", "cancelled", "expired"}
    return status if status in allowed else "pending"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _studio_url(run_id: str | None) -> str | None:
    return f"#/agents?run_id={run_id}" if run_id else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
