"""Chat-facing task card mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .approvals import approval_cards_from_payloads
from .artifacts import artifact_snapshots_from_payloads
from .contracts import AgentTaskSnapshot
from .events import public_run_event_from_payload


def agent_task_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentTaskSnapshot,
) -> AgentTaskSnapshot:
    if isinstance(payload, AgentTaskSnapshot):
        return payload

    task_id = _text(payload.get("task_id") or payload.get("run_id"))
    run_id = _text(payload.get("run_id") or task_id)
    raw_events = (
        payload.get("recent_events") or payload.get("events") or payload.get("timeline") or []
    )
    recent_events = [
        public_run_event_from_payload(event, run_id=run_id, sequence=index + 1)
        for index, event in enumerate(raw_events if isinstance(raw_events, list) else [])
    ]

    approvals = approval_cards_from_payloads(payload.get("pending_approvals"), run_id=run_id)
    if not approvals:
        approvals = approval_cards_from_payloads(payload.get("pending_approval"), run_id=run_id)

    status = _task_status(payload.get("status"))
    return AgentTaskSnapshot(
        task_id=task_id,
        conversation_id=_optional_text(payload.get("conversation_id") or payload.get("session_id")),
        title=_text(payload.get("title") or payload.get("user_goal") or "Yachiyo task"),
        status=status,
        summary=_optional_text(payload.get("summary") or payload.get("result")),
        current_step=_optional_text(payload.get("current_step")),
        progress_text=_optional_text(payload.get("progress_text")),
        needs_user_action=bool(payload.get("needs_user_action") or approvals),
        pending_approvals=approvals,
        recent_events=recent_events,
        artifacts=artifact_snapshots_from_payloads(payload.get("artifacts"), run_id=run_id),
        open_in_studio_url=_optional_text(payload.get("open_in_studio_url")) or _studio_url(run_id),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def agent_task_snapshots_from_payloads(payloads: Any) -> list[AgentTaskSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [agent_task_snapshot_from_payload(item) for item in payloads]


def _task_status(value: Any) -> str:
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


def _studio_url(run_id: str) -> str | None:
    return f"#/agents?run_id={run_id}" if run_id else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
