"""ToolCall public snapshot mapping compatibility exports."""

from __future__ import annotations

from typing import Any

from .contracts import PublicRunEvent, ToolCallSnapshot
from .tool_call_event_snapshots import (
    latest_matching_tool_call_index,
    merge_tool_call_snapshots,
    tool_call_snapshots_from_events,
)
from .tool_call_payload_snapshots import tool_call_snapshot_from_payload
from .tool_call_payload_snapshots import tool_call_status_is_terminal


def tool_call_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
    events: list[PublicRunEvent] | None = None,
) -> list[ToolCallSnapshot]:
    if isinstance(payloads, list):
        calls = [tool_call_snapshot_from_payload(item, run_id=run_id) for item in payloads]
        for event_call in tool_call_snapshots_from_events(events or []):
            matching_index = latest_matching_tool_call_index(calls, event_call)
            if matching_index is None:
                calls.append(event_call)
                continue
            calls[matching_index] = merge_tool_call_snapshots(
                calls[matching_index],
                event_call,
            )
        terminal_approval_ids = {
            call.approval_id
            for call in calls
            if call.approval_id and tool_call_status_is_terminal(call.status)
        }
        return [
            call
            for call in calls
            if not (
                call.status == "waiting_approval"
                and call.approval_id in terminal_approval_ids
            )
        ]
    return tool_call_snapshots_from_events(events or [])
