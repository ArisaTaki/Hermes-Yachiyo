"""Memory public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import MemorySnapshot


def memory_snapshot_from_payload(
    payload: Mapping[str, Any] | MemorySnapshot,
) -> MemorySnapshot:
    if isinstance(payload, MemorySnapshot):
        return payload

    return MemorySnapshot(
        memory_id=_text(payload.get("memory_id")),
        scope=_text(payload.get("scope") or "global"),
        kind=_text(payload.get("kind") or "fact"),
        content=_text(payload.get("content")),
        source_session_id=_optional_text(payload.get("source_session_id")),
        source_message_id=_optional_text(payload.get("source_message_id")),
        source_task_id=_optional_text(payload.get("source_task_id")),
        source_run_id=_optional_text(payload.get("source_run_id")),
        confidence=_float(payload.get("confidence")),
        pinned=bool(payload.get("pinned", False)),
        user_confirmed=bool(payload.get("user_confirmed", False)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
        deleted_at=_optional_text(payload.get("deleted_at")),
    )


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
