"""Runtime event rollups for group and workflow timeline snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.desktop_provider_session_events import (
    desktop_provider_session_public_event,
)
from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent
from .events import public_run_event_from_payload


def runtime_events_with_desktop_provider_session_from_payload(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
    *,
    run_id: str,
    context: Mapping[str, Any] | None = None,
) -> list[PublicRunEvent]:
    event_list = list(events)
    if any(_is_parent_desktop_provider_event(event, run_id=run_id) for event in event_list):
        return event_list
    session = _desktop_provider_session_from_payload(payload)
    if not isinstance(session, Mapping):
        return event_list
    event = desktop_provider_session_public_event(
        session,
        run_id=run_id,
        payload_context={
            **_runtime_context_from_payload(payload),
            **{
                key: value
                for key, value in (context or {}).items()
                if value not in (None, "", [], {})
            },
        },
        redact=redact_secrets,
    )
    if event is None:
        return event_list
    return [
        *event_list,
        public_run_event_from_payload(
            event,
            run_id=run_id,
            sequence=_next_sequence(event_list),
        ),
    ]


def runtime_key_events_from_child_timelines(
    parent_events: Iterable[PublicRunEvent],
    child_runs: Iterable[Any],
    *,
    parent_run_id: str,
    scope: str,
    context: Mapping[str, Any] | None = None,
) -> list[PublicRunEvent]:
    """Roll child runtime state markers into a parent group/workflow timeline."""
    event_list = list(parent_events)
    context_payload = {
        key: value
        for key, value in (context or {}).items()
        if value not in (None, "", [], {})
    }
    existing = {_runtime_rollup_key(event) for event in event_list}
    next_sequence = _next_sequence(event_list)
    projected: list[PublicRunEvent] = []
    for child_run in child_runs:
        child_events = getattr(child_run, "events", []) or []
        for event in child_events:
            event_type = _runtime_rollup_event_type(
                _text(getattr(event, "event_type", "")),
                scope=scope,
            )
            if not event_type:
                continue
            key = _runtime_rollup_key(event)
            if key in existing:
                continue
            existing.add(key)
            projected.append(
                public_run_event_from_payload(
                    _runtime_rollup_payload(
                        event,
                        event_type=event_type,
                        parent_run_id=parent_run_id,
                        scope=scope,
                        context=context_payload,
                    ),
                    run_id=parent_run_id,
                    sequence=next_sequence,
                )
            )
            next_sequence += 1
    if not projected:
        return event_list
    return [*event_list, *projected]


def _runtime_rollup_payload(
    event: PublicRunEvent,
    *,
    event_type: str,
    parent_run_id: str,
    scope: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(event.payload) if isinstance(event.payload, Mapping) else {}
    payload.update(context)
    payload.setdefault("source_run_id", _text(event.source_run_id or event.run_id))
    payload.setdefault("source_sequence", int(event.sequence or 0))
    payload.setdefault("source_event_type", _text(event.event_type))
    if event.event_id:
        payload.setdefault("source_event_id", event.event_id)
    payload["runtime_rollup"] = True
    payload["runtime_rollup_scope"] = scope
    _apply_scoped_runtime_metadata(payload, event_type=event_type, scope=scope)
    return {
        "run_id": parent_run_id,
        "event_type": event_type,
        "title": event.title,
        "detail": event.detail,
        "payload": payload,
        "created_at": event.created_at,
    }


def _apply_scoped_runtime_metadata(
    payload: dict[str, Any],
    *,
    event_type: str,
    scope: str,
) -> None:
    if event_type.endswith(".replan.requested"):
        payload.setdefault("planner_event_type", "agent.replan.requested")
        payload.setdefault("planner_scope", scope)
        return
    if event_type.endswith(".replan.recovery.updated"):
        payload.setdefault("planner_event_type", "agent.replan.recovery.updated")
        payload.setdefault("planner_scope", scope)


def _runtime_rollup_event_type(event_type: str, *, scope: str) -> str:
    clean = _text(event_type)
    if not clean:
        return ""
    if clean.startswith(("desktop.provider_session.", "desktop.provider_execution.")):
        return clean
    prefix = _scope_event_prefix(scope)
    if not prefix:
        return ""
    if clean == "agent.deferred_continuation.enqueued" or clean.endswith(
        ".deferred_continuation.enqueued"
    ):
        return f"{prefix}.deferred_continuation.enqueued"
    if clean == "agent.replan.requested" or clean.endswith(".replan.requested"):
        return f"{prefix}.replan.requested"
    if clean == "agent.replan.recovery.updated" or clean.endswith(
        ".replan.recovery.updated"
    ):
        return f"{prefix}.replan.recovery.updated"
    return ""


def _scope_event_prefix(scope: str) -> str:
    clean = _text(scope)
    if clean in {"group", "group_run", "group.run"}:
        return "group.run"
    if clean in {"workflow", "workflow_run", "workflow.run"}:
        return "workflow.run"
    return ""


def _runtime_rollup_key(event: PublicRunEvent) -> tuple[str, str, str, str]:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    source_event_id = _text(payload.get("source_event_id") or event.event_id)
    source_run_id = _text(payload.get("source_run_id") or event.source_run_id or event.run_id)
    source_sequence = _text(payload.get("source_sequence") or event.sequence)
    source_event_type = _text(payload.get("source_event_type") or event.event_type)
    return (source_event_id, source_run_id, source_sequence, source_event_type)


def _is_parent_desktop_provider_event(event: PublicRunEvent, *, run_id: str) -> bool:
    if not event.event_type.startswith("desktop.provider_session."):
        return False
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    source_run_id = _text(payload.get("source_run_id") or event.source_run_id)
    if source_run_id and source_run_id != run_id:
        return False
    return _text(event.run_id) in {"", run_id}


def _desktop_provider_session_from_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    envelope = payload.get("runtime_execution_envelope")
    if isinstance(envelope, Mapping):
        session = envelope.get("desktop_provider_session")
        if isinstance(session, Mapping):
            return session
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        envelope = metadata.get("yachiyo_execution_envelope")
        if isinstance(envelope, Mapping):
            session = envelope.get("desktop_provider_session")
            if isinstance(session, Mapping):
                return session
    return None


def _runtime_context_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "task_id",
            "session_id",
            "agent_id",
            "workflow_id",
            "workflow_run_id",
            "group_id",
            "group_run_id",
            "run_group_id",
        )
        if payload.get(key) not in (None, "", [], {})
    }


def _next_sequence(events: list[PublicRunEvent]) -> int:
    sequences = [int(event.sequence or 0) for event in events]
    return max([*sequences, len(events)]) + 1


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
