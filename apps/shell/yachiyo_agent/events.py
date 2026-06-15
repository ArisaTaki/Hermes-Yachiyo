"""Public run event mapping helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import PublicRunEvent


def public_run_event_from_payload(
    payload: Mapping[str, Any] | PublicRunEvent,
    *,
    run_id: str = "",
    sequence: int = 0,
) -> PublicRunEvent:
    if isinstance(payload, PublicRunEvent):
        return payload

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
        title=_optional_text(title),
        detail=_optional_text(detail),
        actor=_optional_text(payload.get("actor")),
        visibility=visibility,
        sensitivity=sensitivity,
        payload=raw_payload,
        created_at=_text(payload.get("created_at")),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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
