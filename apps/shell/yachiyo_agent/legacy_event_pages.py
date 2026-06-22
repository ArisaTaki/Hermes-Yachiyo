"""Legacy runtime RunEvent replay and pagination helpers."""

from __future__ import annotations

import json
from typing import Any


def run_with_replay_events(run: dict[str, Any], runtime: Any) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "").strip()
    list_run_events = getattr(runtime, "list_run_events", None)
    if not run_id or not callable(list_run_events):
        return run
    try:
        events_payload = list_run_events(run_id, limit=500)
    except Exception:
        return run
    events = events_payload.get("events") if isinstance(events_payload, dict) else None
    if not isinstance(events, list) or not events:
        return run
    replay_events = [dict(event) for event in events if isinstance(event, dict)]
    legacy_events = legacy_run_events(run)
    if not legacy_events:
        return {**run, "events": replay_events}

    enriched_events = list(legacy_events)
    existing_keys = {event_identity(event) for event in enriched_events}
    for event in replay_events:
        if not is_replay_enrichment_event(event):
            continue
        event_key = event_identity(event)
        if event_key in existing_keys:
            continue
        enriched_events.append(event)
        existing_keys.add(event_key)
    if len(enriched_events) == len(legacy_events):
        return run
    return {**run, "events": enriched_events}


def legacy_run_events(run: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = run.get(key)
        if isinstance(value, list) and value:
            return [dict(event) for event in value if isinstance(event, dict)]
    return []


def is_replay_enrichment_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or event.get("event") or "")
    return event_type.startswith(
        (
            "agent.desktop.",
            "agent.tool.",
            "approval.",
            "artifact.",
            "memory.",
            "skill.",
            "tool.",
        )
    ) or event_type in {
        "workflow.node.artifact",
        "workflow.node.approval_required",
        "workflow.node.approval_approved",
        "workflow.node.approval_rejected",
        "workflow.node.approval_timeout",
        "workflow.run.approval_required",
    }


def event_identity(event: dict[str, Any]) -> tuple[str, str]:
    event_type = str(event.get("event_type") or event.get("event") or "")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return (event_type, json.dumps(payload, sort_keys=True, default=str))


def run_event_page_from_legacy_stream(
    payload: dict[str, Any],
    *,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> dict[str, Any]:
    clean_after_sequence = max(0, int(after_sequence or 0))
    clean_limit = max(1, min(500, int(limit or 200)))
    events = [
        dict(event)
        for event in payload.get("events", [])
        if isinstance(event, dict) and event_sequence(event) > clean_after_sequence
    ]
    page = events[:clean_limit]
    next_after_sequence = max([event_sequence(event) for event in page] or [clean_after_sequence])
    return {
        "run_id": payload.get("run_id") or run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "next_after_sequence": next_after_sequence,
        "has_more": len(events) > clean_limit,
        "events": page,
    }


def event_sequence(event: dict[str, Any]) -> int:
    try:
        return int(event.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0
