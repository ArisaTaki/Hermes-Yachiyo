"""Public run event mapping helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .contracts import PublicRunEvent, RunEventPageSnapshot

_SECRET_EVENT_PAYLOAD = {"redacted": True, "reason": "secret_event"}


def public_run_event_from_payload(
    payload: Mapping[str, Any] | PublicRunEvent,
    *,
    run_id: str = "",
    sequence: int = 0,
) -> PublicRunEvent:
    if isinstance(payload, PublicRunEvent):
        return _redacted_public_run_event(payload)

    raw_payload = _mapping(payload.get("payload"))
    event_type = _text(payload.get("event_type") or payload.get("event"))
    event_run_id = _text(payload.get("run_id") or run_id)
    event_sequence = _int(payload.get("sequence"), default=sequence)
    detail = payload.get("detail")
    title = payload.get("title")
    visibility = "internal" if _text(payload.get("visibility")) == "internal" else "user"
    sensitivity = "secret" if _text(payload.get("sensitivity")) == "secret" else "public"

    timeline_payload = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "event_id",
            "run_id",
            "sequence",
            "schema_version",
            "event_type",
            "event",
            "title",
            "detail",
            "actor",
            "visibility",
            "sensitivity",
            "payload",
            "created_at",
        }
    }
    if timeline_payload:
        raw_payload = {**timeline_payload, **raw_payload}

    return PublicRunEvent(
        event_id=_optional_text(payload.get("event_id")),
        run_id=event_run_id,
        sequence=event_sequence,
        schema_version=_int(payload.get("schema_version"), default=1),
        event_type=event_type or "run.event",
        parent_run_id=_event_context_text(payload, raw_payload, "parent_run_id"),
        source_run_id=_event_context_text(payload, raw_payload, "source_run_id"),
        source_runnable_id=_event_context_text_any(
            payload,
            raw_payload,
            "source_runnable_id",
            "source_agent_id",
            "member_agent_id",
            "agent_id",
        ),
        source_runnable_name=_event_context_text_any(
            payload,
            raw_payload,
            "source_runnable_name",
            "source_agent_name",
            "member_agent_name",
            "agent_name",
        ),
        workflow_id=_event_context_text(payload, raw_payload, "workflow_id"),
        workflow_run_id=_event_context_text(payload, raw_payload, "workflow_run_id"),
        workflow_node_id=_event_context_text(payload, raw_payload, "workflow_node_id"),
        workflow_node_label=_event_context_text(
            payload,
            raw_payload,
            "workflow_node_label",
        ),
        group_id=_event_context_text(payload, raw_payload, "group_id"),
        group_run_id=_event_context_text_any(
            payload,
            raw_payload,
            "group_run_id",
            "run_group_id",
        ),
        run_group_id=_event_context_text_any(
            payload,
            raw_payload,
            "run_group_id",
            "group_run_id",
        ),
        agent_id=_event_context_text_any(
            payload,
            raw_payload,
            "agent_id",
            "member_agent_id",
        ),
        agent_name=_event_context_text_any(
            payload,
            raw_payload,
            "agent_name",
            "member_agent_name",
        ),
        member_agent_id=_event_context_text_any(
            payload,
            raw_payload,
            "member_agent_id",
            "agent_id",
        ),
        member_agent_name=_event_context_text_any(
            payload,
            raw_payload,
            "member_agent_name",
            "agent_name",
        ),
        title=_public_event_title(title, sensitivity),
        detail=_public_event_detail(detail, sensitivity),
        actor=_optional_text(payload.get("actor")),
        visibility=visibility,
        sensitivity=sensitivity,
        payload=_public_event_payload(raw_payload, sensitivity),
        created_at=_text(payload.get("created_at")),
    )


def public_run_event_page_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> RunEventPageSnapshot:
    events = [
        public_run_event_from_payload(
            event,
            run_id=run_id,
            sequence=after_sequence + index + 1,
        )
        for index, event in enumerate(_payload_items(payload, "events"))
    ]
    next_after_sequence = _optional_int(payload.get("next_after_sequence"))
    if next_after_sequence is None:
        next_after_sequence = max(
            [int(event.sequence or 0) for event in events] or [after_sequence]
        )
    return RunEventPageSnapshot(
        run_id=_text(payload.get("run_id") or run_id),
        after_sequence=_int(payload.get("after_sequence"), default=after_sequence),
        limit=_int(payload.get("limit"), default=limit),
        next_after_sequence=next_after_sequence,
        has_more=bool(payload.get("has_more", False)),
        events=events,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _redacted_public_run_event(event: PublicRunEvent) -> PublicRunEvent:
    return event.model_copy(
        update={
            "title": _public_event_title(event.title, event.sensitivity),
            "detail": _public_event_detail(event.detail, event.sensitivity),
            "payload": _public_event_payload(event.payload, event.sensitivity),
        }
    )


def _public_event_payload(payload: Mapping[str, Any], sensitivity: str) -> dict[str, Any]:
    if sensitivity == "secret":
        return dict(_SECRET_EVENT_PAYLOAD)
    redacted = redact_run_event_payload(dict(payload))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _public_event_title(value: Any, sensitivity: str) -> str | None:
    if sensitivity == "secret":
        return "Secret event"
    return _optional_text(redact_secrets(value)) if value is not None else None


def _public_event_detail(value: Any, sensitivity: str) -> str | None:
    if sensitivity == "secret":
        return None
    return _optional_text(redact_secrets(value)) if value is not None else None


def _event_context_text(
    payload: Mapping[str, Any],
    raw_payload: Mapping[str, Any],
    key: str,
) -> str | None:
    return _optional_text(payload.get(key)) or _optional_text(raw_payload.get(key))


def _event_context_text_any(
    payload: Mapping[str, Any],
    raw_payload: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = _event_context_text(payload, raw_payload, key)
        if value:
            return value
    return None


def _payload_items(payload: Any, key: str) -> list[dict[str, Any]]:
    items = payload.get(key) if isinstance(payload, Mapping) else payload
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
