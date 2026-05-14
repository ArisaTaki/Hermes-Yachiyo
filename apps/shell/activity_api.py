"""Activity log API helpers for dashboard and chat UI."""

from __future__ import annotations

from typing import Any

from apps.core.activity_store import get_activity_store

_STATUS_ORDER = ("running", "completed", "failed", "cancelled")
_STATUS_ALIASES = {
    "pending": "running",
    "progress": "running",
    "running": "running",
    "success": "completed",
    "completed": "completed",
    "error": "failed",
    "failed": "failed",
    "cancelled": "cancelled",
}


def list_activity_events(
    *,
    query: str = "",
    status: str = "",
    tool: str = "",
    phase: str = "",
    session_id: str = "",
    task_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    store = get_activity_store()
    events = store.list_events(
        query=str(query or "").strip(),
        status=str(status or "").strip(),
        tool=str(tool or "").strip(),
        phase=str(phase or "").strip(),
        session_id=str(session_id or "").strip(),
        task_id=str(task_id or "").strip(),
        limit=limit,
        key_only=True,
    )
    items = [_activity_to_dict(event) for event in events]
    tools = sorted({item["tool_name"] for item in items if item.get("tool_name")})
    phases = sorted({item["phase"] for item in items if item.get("phase")})
    statuses = [
        status
        for status in _STATUS_ORDER
        if any(item.get("status") == status for item in items)
    ]
    return {
        "ok": True,
        "events": items,
        "tools": tools,
        "phases": phases,
        "statuses": statuses,
        "total": len(items),
    }


def get_activity_event_detail(event_id: str, *, limit: int = 200) -> dict[str, Any]:
    store = get_activity_store()
    event = store.get_event(str(event_id or "").strip())
    if event is None:
        return {"ok": False, "error": "活动日志不存在", "event": None, "trace": []}

    event_dict = _activity_to_dict(event)
    task_id = str(event_dict.get("task_id") or "")
    session_id = str(event_dict.get("session_id") or "")
    if task_id:
        trace = store.list_events(task_id=task_id, limit=limit, key_only=False)
        scope = "task"
    elif session_id:
        trace = store.list_events(session_id=session_id, limit=limit, key_only=False)
        scope = "session"
    else:
        trace = [event]
        scope = "event"

    return {
        "ok": True,
        "event": event_dict,
        "trace": [_activity_to_dict(item) for item in reversed(trace)],
        "scope": scope,
        "total": len(trace),
    }


def delete_activity_event(event_id: str) -> dict[str, Any]:
    store = get_activity_store()
    deleted = store.delete_event(str(event_id or "").strip())
    if not deleted:
        return {"ok": False, "deleted": False, "error": "活动日志不存在"}
    return {"ok": True, "deleted": True, "event_id": event_id}


def delete_activity_events(event_ids: list[str]) -> dict[str, Any]:
    store = get_activity_store()
    normalized_ids = [str(event_id or "").strip() for event_id in event_ids if event_id]
    deleted_count = store.delete_events(normalized_ids)
    return {
        "ok": True,
        "deleted": deleted_count,
        "requested": len(set(normalized_ids)),
    }


def _activity_to_dict(event: Any) -> dict[str, Any]:
    item = event.to_dict()
    raw_status = str(item.get("status") or "").strip()
    normalized = _normalize_status(raw_status)
    item["status"] = normalized
    if raw_status and raw_status != normalized:
        item["raw_status"] = raw_status
    return item


def _normalize_status(status: str) -> str:
    value = str(status or "").strip()
    return _STATUS_ALIASES.get(value, value)
