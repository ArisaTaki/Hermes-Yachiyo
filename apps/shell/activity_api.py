"""Activity log API helpers for dashboard and chat UI."""

from __future__ import annotations

from typing import Any

from apps.core.activity_store import get_activity_store


def list_activity_events(
    *,
    query: str = "",
    status: str = "",
    tool: str = "",
    session_id: str = "",
    task_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    store = get_activity_store()
    events = store.list_events(
        query=str(query or "").strip(),
        status=str(status or "").strip(),
        tool=str(tool or "").strip(),
        session_id=str(session_id or "").strip(),
        task_id=str(task_id or "").strip(),
        limit=limit,
    )
    items = [event.to_dict() for event in events]
    tools = sorted({item["tool_name"] for item in items if item.get("tool_name")})
    return {
        "ok": True,
        "events": items,
        "tools": tools,
        "total": len(items),
    }
