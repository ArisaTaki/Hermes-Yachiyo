"""Safe desktop provider context previews for task progress and replan events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def desktop_provider_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    provider = _mapping(result.get("desktop_execution_provider"))
    route = _mapping(result.get("desktop_execution_route"))
    sandbox_provider = _mapping(result.get("sandbox_provider"))
    session = _mapping(result.get("desktop_provider_session"))
    routed = result.get("desktop_execution_provider_routed") is True
    blocked = result.get("blocked_by_desktop_execution_provider") is True
    if not any((provider, route, sandbox_provider, session, routed, blocked)):
        return {}
    preview: dict[str, Any] = {
        "routed": routed,
        "blocked": blocked,
    }
    if provider:
        preview["provider"] = _safe_mapping_preview(
            provider,
            (
                "provider_kind",
                "provider_id",
                "adapter_registered",
                "route_id",
            ),
        )
    if route:
        preview["route"] = _safe_mapping_preview(
            route,
            (
                "status",
                "selected_provider_kind",
                "selected_provider_id",
                "can_execute",
                "sandbox_required",
                "desktop_session_kind",
                "desktop_session_isolated",
            ),
        )
    if sandbox_provider:
        preview["sandbox_provider"] = _safe_mapping_preview(
            sandbox_provider,
            (
                "provider_kind",
                "provider_id",
                "status",
                "available",
                "adapter_ready",
                "desktop_session_kind",
                "desktop_session_isolated",
                "foreground_takeover_required",
                "keyboard_mouse_capture_supported",
            ),
        )
    if session:
        preview["desktop_provider_session"] = _safe_mapping_preview(
            session,
            (
                "status",
                "running",
                "started",
                "needed",
                "provider_id",
                "desktop_session_kind",
                "desktop_session_isolated",
                "foreground_takeover_required",
                "keyboard_mouse_capture_supported",
            ),
        )
    return preview


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if str(key).strip() and item not in (None, "", [], {})
    }


def _safe_mapping_preview(
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        key: source.get(key)
        for key in keys
        if source.get(key) not in (None, "", [], {})
    }
