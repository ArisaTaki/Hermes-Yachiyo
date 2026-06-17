"""ToolCall public snapshot mapping compatibility exports."""

from __future__ import annotations

from typing import Any

from .contracts import PublicRunEvent, ToolCallSnapshot
from .tool_call_event_snapshots import tool_call_snapshots_from_events
from .tool_call_payload_snapshots import tool_call_snapshot_from_payload


def tool_call_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
    events: list[PublicRunEvent] | None = None,
) -> list[ToolCallSnapshot]:
    if isinstance(payloads, list):
        return [tool_call_snapshot_from_payload(item, run_id=run_id) for item in payloads]
    return tool_call_snapshots_from_events(events or [])
