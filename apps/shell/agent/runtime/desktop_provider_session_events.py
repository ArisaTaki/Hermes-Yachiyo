"""Shared timeline projection for desktop provider session lifecycle events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


def desktop_provider_session_public_event(
    session: Mapping[str, Any],
    *,
    run_id: str = "",
    payload_context: Mapping[str, Any] | None = None,
    redact: Callable[[Any], str] = str,
) -> dict[str, Any] | None:
    if not desktop_provider_session_is_observable(session):
        return None
    event_type, detail = desktop_provider_session_event_name(session)
    payload = {
        key: value
        for key, value in (payload_context or {}).items()
        if key != "runtime_execution_envelope" and value not in (None, "", [], {})
    }
    payload["desktop_provider_session"] = desktop_provider_session_event_payload(
        session,
        redact=redact,
    )
    event = {
        "event_type": event_type,
        "detail": detail,
        "payload": payload,
    }
    if run_id:
        event["run_id"] = run_id
    return event


def desktop_provider_session_timeline_events(
    start_payload: Mapping[str, Any],
    *,
    redact: Callable[[Any], str] = str,
) -> list[dict[str, Any]]:
    envelope = start_payload.get("runtime_execution_envelope")
    if not isinstance(envelope, Mapping):
        return []
    session = envelope.get("desktop_provider_session")
    if not isinstance(session, Mapping):
        return []
    event = desktop_provider_session_public_event(
        session,
        payload_context={
            "task_id": str(start_payload.get("task_id") or ""),
            "session_id": str(start_payload.get("session_id") or ""),
        },
        redact=redact,
    )
    if event is None:
        return []
    return [
        {
            "event": event["event_type"],
            "detail": event["detail"],
            "payload": event["payload"],
        }
    ]


def desktop_provider_session_is_observable(session: Mapping[str, Any]) -> bool:
    return any(
        bool(session.get(key))
        for key in ("needed", "started", "running", "error", "reason")
    )


def desktop_provider_session_event_name(
    session: Mapping[str, Any],
) -> tuple[str, str]:
    if session.get("ok") is False or str(session.get("status") or "") == "start_failed":
        return (
            "desktop.provider_session.failed",
            "Isolated desktop provider failed to start",
        )
    if bool(session.get("started")):
        return (
            "desktop.provider_session.started",
            "Isolated desktop provider started",
        )
    if bool(session.get("running")):
        return (
            "desktop.provider_session.ready",
            "Isolated desktop provider is ready",
        )
    return (
        "desktop.provider_session.required",
        "Isolated desktop provider is required",
    )


def desktop_provider_session_event_payload(
    session: Mapping[str, Any],
    *,
    redact: Callable[[Any], str] = str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    session_mode = desktop_provider_session_mode(session)
    for key in (
        "ok",
        "status",
        "running",
        "started",
        "needed",
        "auto_start",
        "provider_id",
        "url",
        "pid",
        "reason",
        "request_ids",
        "tool_names",
        "error",
        "source",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "keyboard_mouse_capture_supported",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
        "blocking_conditions",
        "supported_tools",
        "provider_manifest_evidence",
        "provider_conformance",
    ):
        value = session.get(key)
        if value not in (None, "", [], {}):
            if key == "error":
                value = redact(value)
            payload[key] = value
    if session_mode:
        payload["desktop_execution_session_mode"] = session_mode
        payload["desktop_execution_session_label"] = desktop_provider_session_mode_label(
            session_mode
        )
    return payload


def desktop_provider_session_mode(session: Mapping[str, Any]) -> str:
    status = str(session.get("status") or "").strip().lower()
    if session.get("ok") is False or status in {"start_failed", "failed"}:
        return "provider_failed"
    kind = str(session.get("desktop_session_kind") or "").strip().lower()
    if kind:
        return kind
    if session.get("desktop_session_isolated") is True:
        return "isolated_desktop"
    if session.get("foreground_takeover_required") is True:
        return "user_foreground"
    if session.get("needed") and not session.get("running"):
        return "provider_required"
    return ""


def desktop_provider_session_mode_label(mode: str) -> str:
    return {
        "headless_read_only": "headless read-only desktop provider",
        "isolated_desktop": "isolated desktop provider",
        "provider_failed": "desktop provider failed",
        "provider_required": "desktop provider required",
        "provider_routed": "desktop provider routed",
        "sandbox_desktop": "sandbox desktop provider",
        "user_foreground": "real desktop foreground",
    }.get(mode, mode.replace("_", " "))
