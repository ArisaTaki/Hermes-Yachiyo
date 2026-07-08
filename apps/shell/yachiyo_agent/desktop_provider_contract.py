"""Shared contract checks for external desktop execution providers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

DESKTOP_PROVIDER_CONTRACT_VERSION = "oha-yachiyo.desktop-provider.v1"

OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS = (
    "desktop.list_apps",
    "app.open",
    "desktop.inspect_app",
    "media.music_app_open_and_play",
    "media.music_app_control",
    "desktop.read_ui",
    "desktop.click_ui_element",
    "desktop.safe_type_text",
    "desktop.safe_shortcut",
    "desktop.verify",
)

_CHECK_BLOCKERS = {
    "provider_configured": "desktop_execution_provider_not_configured",
    "provider_available": "desktop_execution_provider_unavailable",
    "adapter_ready": "desktop_execution_provider_adapter_unavailable",
    "desktop_session_isolated": "desktop_session_not_isolated",
    "foreground_takeover_not_required": "foreground_takeover_required",
    "desktop_backend_declared": "desktop_backend_kind_missing",
    "desktop_backend_not_loopback": "loopback_desktop_backend",
    "desktop_backend_ready_for_public_release": "desktop_backend_not_release_ready",
    "real_virtual_desktop_backend_not_required": "real_virtual_desktop_backend_required",
    "required_tools_supported": "desktop_provider_missing_required_tools",
    "tool_results_present": "desktop_provider_tool_results_missing",
    "all_tools_routed": "desktop_provider_tool_not_routed",
    "all_tool_results_ok": "desktop_provider_tool_result_failed",
    "all_tool_results_isolated": "desktop_provider_tool_result_not_isolated",
    "tool_sequence_covers_required_tools": "desktop_provider_smoke_incomplete",
}


def virtual_desktop_provider_contract_evidence(
    status: Mapping[str, Any] | None,
    *,
    required_tools: Sequence[str] | None = None,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return release-readiness evidence for a Hermes/Hanako-style desktop backend."""

    status_payload = dict(status or {})
    required = _string_list(required_tools)
    supported = _supported_tools(status_payload)
    desktop_backend_kind = str(status_payload.get("desktop_backend_kind") or "").strip()
    checks = {
        "provider_configured": status_payload.get("configured") is True,
        "provider_available": bool(status_payload.get("available")),
        "adapter_ready": bool(status_payload.get("adapter_ready")),
        "desktop_session_isolated": _desktop_session_isolated(status_payload),
        "foreground_takeover_not_required": (
            _optional_bool(status_payload.get("foreground_takeover_required")) is False
        ),
        "desktop_backend_declared": bool(desktop_backend_kind),
        "desktop_backend_not_loopback": (
            _optional_bool(status_payload.get("desktop_backend_is_loopback")) is False
        ),
        "desktop_backend_ready_for_public_release": (
            _optional_bool(
                status_payload.get("desktop_backend_ready_for_public_release")
            )
            is True
        ),
        "real_virtual_desktop_backend_not_required": (
            _optional_bool(status_payload.get("requires_real_virtual_desktop_backend"))
            is False
        ),
        "required_tools_supported": not required or set(required).issubset(supported),
    }
    if tool_results is not None:
        result_list = [dict(item) for item in tool_results if isinstance(item, Mapping)]
        result_tools = {
            str(item.get("tool") or item.get("action") or "").strip()
            for item in result_list
        }
        checks.update(
            {
                "tool_results_present": bool(result_list),
                "all_tools_routed": all(
                    item.get("desktop_execution_provider_routed") is True
                    for item in result_list
                ),
                "all_tool_results_ok": all(
                    item.get("ok") is not False for item in result_list
                ),
                "all_tool_results_isolated": all(
                    _tool_result_reports_isolated_session(item) for item in result_list
                ),
                "tool_sequence_covers_required_tools": (
                    not required or set(required).issubset(result_tools)
                ),
            }
        )
    blockers = [
        _CHECK_BLOCKERS[key]
        for key, passed in checks.items()
        if not passed and key in _CHECK_BLOCKERS
    ]
    missing_tools = sorted(set(required) - supported)
    return {
        "ok": all(checks.values()),
        "contract_version": DESKTOP_PROVIDER_CONTRACT_VERSION,
        "checks": checks,
        "blocking_conditions": blockers,
        "missing_required_tools": missing_tools,
        "required_tools": required,
        "supported_tools": sorted(supported),
        "desktop_session_kind": str(
            status_payload.get("desktop_session_kind") or ""
        ).strip(),
        "desktop_session_isolated": _desktop_session_isolated(status_payload),
        "foreground_takeover_required": _optional_bool(
            status_payload.get("foreground_takeover_required")
        ),
        "keyboard_mouse_capture_supported": _optional_bool(
            status_payload.get("keyboard_mouse_capture_supported")
        ),
        "desktop_backend_kind": desktop_backend_kind,
        "desktop_backend_is_loopback": _optional_bool(
            status_payload.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool(
            status_payload.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": _optional_bool(
            status_payload.get("requires_real_virtual_desktop_backend")
        ),
    }


def _desktop_session_isolated(status: Mapping[str, Any]) -> bool:
    session_isolated = _optional_bool(status.get("desktop_session_isolated"))
    if session_isolated is not None:
        return session_isolated
    return str(status.get("desktop_session_kind") or "").strip() in {
        "isolated_desktop",
        "virtual_desktop",
    }


def _supported_tools(status: Mapping[str, Any]) -> set[str]:
    health = status.get("health")
    health_tools = (
        _string_list(health.get("supported_tools"))
        if isinstance(health, Mapping)
        else []
    )
    return set(_string_list(status.get("supported_tools")) or health_tools)


def _tool_result_reports_isolated_session(item: Mapping[str, Any]) -> bool:
    isolated_provider = item.get("isolated_desktop_provider")
    if (
        isinstance(isolated_provider, Mapping)
        and _optional_bool(isolated_provider.get("desktop_session_isolated")) is True
    ):
        return True
    sandbox_provider = item.get("sandbox_provider")
    return (
        isinstance(sandbox_provider, Mapping)
        and _optional_bool(sandbox_provider.get("desktop_session_isolated")) is True
    )


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw = value
    else:
        raw = []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]
