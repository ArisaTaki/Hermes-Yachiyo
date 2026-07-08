"""Legacy runtime RunEvent replay and pagination helpers."""

from __future__ import annotations

import json
from typing import Any

from .event_page_windows import (
    FIRST_PAGE_DESKTOP_PROVIDER_SESSION_EVENT_TYPES,
    FIRST_PAGE_LEGACY_KEY_EVENT_TYPES,
    FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES,
)


def run_with_replay_events(run: dict[str, Any], runtime: Any) -> dict[str, Any]:
    run_id = str(run.get("run_id") or "").strip()
    list_run_events = getattr(runtime, "list_run_events", None)
    if not run_id or not callable(list_run_events):
        return run
    try:
        events_payload = list_run_events(run_id, limit=500)
    except TypeError:
        try:
            events_payload = list_run_events(run_id)
        except Exception:
            return run
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
            "agent.artifact.",
            "agent.deferred_continuation.",
            "agent.desktop.",
            "agent.intent.",
            "agent.plan.",
            "agent.replan.",
            "agent.run.",
            "agent.task.",
            "agent.task_core.",
            "agent.tool.",
            "desktop.provider_session.",
            "group.artifact.",
            "group.member.",
            "group.run.",
            "group.shared_artifact.",
            "approval.",
            "artifact.",
            "memory.",
            "skill.",
            "tool.",
            "workflow.desktop.",
            "workflow.intent.",
            "workflow.node.",
            "workflow.plan.",
            "workflow.replan.",
            "workflow.run.",
            "workflow.task.",
            "workflow.task_core.",
        )
    ) or event_type in {
        "agent.cancelled",
        "agent.completed",
        "agent.failed",
        "agent.started",
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
    if clean_after_sequence == 0 and len(events) > clean_limit:
        page = events_with_first_page_key_event_window(page, events, next_after_sequence)
        next_after_sequence = max([event_sequence(event) for event in page] or [next_after_sequence])
    return {
        "run_id": payload.get("run_id") or run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "next_after_sequence": next_after_sequence,
        "has_more": len(events) > clean_limit,
        "events": page,
    }


def events_with_first_page_key_event_window(
    page: list[dict[str, Any]],
    events: list[dict[str, Any]],
    next_after_sequence: int,
) -> list[dict[str, Any]]:
    ordered_events = sorted(events, key=event_sequence)
    key_event_sequence = _first_page_key_event_sequence(
        ordered_events,
        next_after_sequence,
    )
    if key_event_sequence <= next_after_sequence:
        return page
    existing_sequences = {event_sequence(event) for event in page}
    enriched = list(page)
    for event in ordered_events:
        sequence = event_sequence(event)
        if sequence <= next_after_sequence:
            continue
        if sequence > key_event_sequence:
            break
        if sequence not in existing_sequences:
            enriched.append(event)
            existing_sequences.add(sequence)
    return enriched


def _first_page_key_event_sequence(
    events: list[dict[str, Any]],
    next_after_sequence: int,
) -> int:
    preferred_event_types = (
        FIRST_PAGE_LEGACY_KEY_EVENT_TYPES
        - FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES
        - FIRST_PAGE_DESKTOP_PROVIDER_SESSION_EVENT_TYPES
    )
    sequence = _first_event_sequence(
        events,
        next_after_sequence,
        preferred_event_types,
    )
    if sequence > next_after_sequence:
        return sequence

    sequence = _first_event_sequence(
        events,
        next_after_sequence,
        FIRST_PAGE_DESKTOP_PROVIDER_SESSION_EVENT_TYPES,
    )
    if sequence > next_after_sequence:
        return sequence

    return _last_contiguous_state_event_sequence(events, next_after_sequence)


def _first_event_sequence(
    events: list[dict[str, Any]],
    next_after_sequence: int,
    event_types: set[str],
) -> int:
    for event in events:
        sequence = event_sequence(event)
        if sequence <= next_after_sequence:
            continue
        if _event_type(event) in event_types:
            return sequence
    return 0


def _last_contiguous_state_event_sequence(
    events: list[dict[str, Any]],
    next_after_sequence: int,
) -> int:
    state_sequence = 0
    capturing_state_block = False
    for event in events:
        sequence = event_sequence(event)
        if sequence <= next_after_sequence:
            continue
        if _event_type(event) in FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES:
            state_sequence = sequence
            capturing_state_block = True
            continue
        if capturing_state_block:
            break
    return state_sequence


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("event") or "").strip()


def event_sequence(event: dict[str, Any]) -> int:
    try:
        return int(event.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0
