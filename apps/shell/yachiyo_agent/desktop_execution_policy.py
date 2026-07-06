"""Shared desktop execution policies for daily and Studio entrypoints."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_status_from_env,
    local_desktop_execution_provider_status,
)


_SANDBOX_DESKTOP_PROVIDER_DEFAULT: dict[str, Any] = {
    "available": False,
    "provider_id": "",
    "provider_kind": "sandbox_desktop",
    "status": "provider_required",
    "adapter_ready": False,
    "reason": (
        "No sandbox desktop provider is configured for this runtime yet; "
        "foreground input must stay supervised or use user handoff."
    ),
    "blocking_conditions": ["sandbox_desktop_provider_required"],
    "supported_tools": [],
    "recommended_for": ["foreground_control", "keyboard_mouse_capture"],
    "diagnostic_route": "/yachiyo/studio/tools",
    "source": "runtime",
    "health": {
        "ok": False,
        "checked": False,
        "status": "not_configured",
        "blocking_conditions": ["sandbox_desktop_provider_required"],
        "supported_tools": [],
        "capabilities": [],
    },
    "launch_hint": {
        "provider_id": "local-headless-desktop",
        "provider_kind": "sandbox_desktop",
        "execution_mode": "headless_read_only",
        "command": [
            "python",
            "scripts/run_headless_desktop_provider.py",
            "--host",
            "127.0.0.1",
            "--port",
            "19091",
        ],
        "env": {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19091",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "local-headless-desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": (
                "desktop.permissions,desktop.permission_preflight,"
                "desktop.active_window,desktop.running_apps,desktop.list_apps,"
                "desktop.windows,desktop.list_windows,desktop.ui_elements,"
                "desktop.read_ui,desktop.verify,app.status"
            ),
        },
        "smoke_command": ["python", "scripts/smoke_headless_desktop_provider.py"],
        "foreground_mutation_supported": False,
        "requires_real_sandbox_for": ["click", "type", "shortcut", "focus"],
    },
}

_READ_ONLY_DESKTOP_PROVIDER_ROUTE_KEYS = (
    "desktop_provider_route_readonly",
    "desktop_provider_readonly_route",
    "route_readonly_desktop_provider",
)

_FOREGROUND_DESKTOP_PROVIDER_ROUTE_KEYS = (
    "desktop_provider_route_foreground",
    "desktop_provider_foreground_route",
    "route_foreground_desktop_provider",
)

_LOCAL_DESKTOP_PROVIDER_KEYS = (
    "desktop_provider_local_native",
    "desktop_provider_local",
    "local_desktop_provider",
)

_READ_ONLY_DESKTOP_PROVIDER_TOOLS = frozenset(
    {
        "desktop.permissions",
        "desktop.permission_preflight",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.list_apps",
        "desktop.windows",
        "desktop.list_windows",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.verify",
        "app.status",
    }
)


def desktop_execution_policy_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        return {"mode": value.strip()}
    return {}


def daily_entrypoint_desktop_execution_policy(
    *,
    surface: str = "chat",
) -> dict[str, Any]:
    """Default Chat/Bubble/Live2D policy: execute tools, but preview raw foreground input."""

    clean_surface = str(surface or "chat").strip() or "chat"
    return {
        "mode": "preview_input",
        "allow_media_control": True,
        "source": f"daily_{clean_surface}",
        "reason": (
            "Daily entrypoints should avoid taking over keyboard/mouse input; "
            "Agent Studio can opt into supervised live desktop execution."
        ),
    }


def agent_studio_desktop_execution_policy() -> dict[str, Any]:
    """Studio is the explicit supervised execution surface."""

    return {
        "mode": "supervised_live",
        "allow_live_foreground": True,
        "source": "agent_studio",
        "reason": "Agent Studio is the supervised desktop execution and debugging surface.",
    }


def sandbox_desktop_provider_status(
    metadata: Mapping[str, Any] | None = None,
    *,
    probe_health: bool = False,
) -> dict[str, Any]:
    """Return the runtime-visible sandbox desktop provider status."""

    should_probe_health = probe_health or _metadata_truthy(
        metadata,
        "desktop_provider_health_probe",
        "probe_desktop_provider_health",
        "sandbox_provider_health_probe",
    )
    provider = _sandbox_provider_payload(metadata) or _sandbox_provider_payload_from_env(
        probe_health=should_probe_health,
    ) or _local_desktop_provider_payload(metadata)
    if provider:
        payload = {**_SANDBOX_DESKTOP_PROVIDER_DEFAULT, **provider}
        payload["available"] = bool(payload.get("available"))
        payload["adapter_ready"] = bool(payload.get("adapter_ready"))
        if payload["available"]:
            if str(payload.get("status") or "").strip() == "provider_required":
                payload["status"] = "available"
            payload["blocking_conditions"] = _string_list(provider.get("blocking_conditions"))
        else:
            blockers = _string_list(payload.get("blocking_conditions"))
            payload["blocking_conditions"] = blockers or ["sandbox_desktop_provider_required"]
        payload["supported_tools"] = _string_list(payload.get("supported_tools"))
        payload["recommended_for"] = _string_list(payload.get("recommended_for"))
        payload["health"] = _health_payload(provider.get("health"))
        return _sandbox_provider_public_payload(payload)
    return dict(_SANDBOX_DESKTOP_PROVIDER_DEFAULT)


def desktop_execution_policy_mode(policy: Mapping[str, Any] | str | None) -> str:
    payload = desktop_execution_policy_payload(policy)
    if not payload:
        return "allow"
    if payload.get("allow_live_foreground") is True:
        return "allow"
    if payload.get("allow_live_foreground") is False:
        return "preview"
    raw = str(
        payload.get("mode")
        or payload.get("live_foreground")
        or payload.get("foreground_input")
        or ""
    ).strip().lower().replace("-", "_")
    if raw in {
        "allow",
        "allowed",
        "live",
        "supervised_live",
        "foreground",
        "live_foreground",
    }:
        return "allow"
    if raw in {
        "handoff",
        "handoff_required",
        "user_handoff",
        "user_handoff_required",
    }:
        return "handoff"
    if raw in {
        "preview_input",
        "input_preview",
        "foreground_input_preview",
    }:
        return "preview_input"
    if raw in {
        "preview",
        "dry_run",
        "dryrun",
        "observe_only",
        "observation_only",
        "read_only",
        "no_live_foreground",
        "sandbox_preferred",
    }:
        return "preview"
    return "allow"


def desktop_execution_route_decision(
    tool_name: str,
    *,
    policy: Mapping[str, Any] | str | None = None,
    execution_mode: Mapping[str, Any] | Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    clean_tool = str(tool_name or "").strip()
    policy_payload = desktop_execution_policy_payload(policy)
    policy_mode = desktop_execution_policy_mode(policy_payload)
    mode_payload = _execution_mode_payload(execution_mode)
    sandbox_provider = sandbox_desktop_provider_status(metadata)
    foreground_control = bool(mode_payload.get("foreground_control"))
    keyboard_mouse_capture = bool(mode_payload.get("keyboard_mouse_capture"))
    foreground_required = foreground_control or keyboard_mouse_capture
    sandbox_required = bool(mode_payload.get("sandbox_recommended")) or (
        str(policy_payload.get("mode") or "").strip().lower().replace("-", "_")
        == "sandbox_preferred"
    )
    isolation = str(mode_payload.get("isolation") or "none").strip() or "none"
    execution_mode_name = str(mode_payload.get("mode") or "tool_native").strip()
    route = {
        "route_id": f"desktop-route:{clean_tool or 'tool'}",
        "tool_name": clean_tool,
        "requested_mode": str(policy_payload.get("mode") or policy_mode or "allow"),
        "selected_provider_kind": isolation,
        "selected_provider_id": _provider_id_for_isolation(isolation),
        "status": "ready",
        "can_execute": True,
        "can_auto_start": True,
        "sandbox_required": False,
        "fallback_mode": "",
        "reason": "Tool can run through its structured runtime provider.",
        "blocking_conditions": [],
        "source": "runtime",
    }
    if not clean_tool:
        return {
            **route,
            "status": "missing_tool",
            "can_execute": False,
            "can_auto_start": False,
            "reason": "No executable tool was selected.",
            "blocking_conditions": ["missing_tool"],
        }
    if (
        desktop_readonly_provider_route_requested(metadata)
        and is_readonly_desktop_provider_tool(clean_tool)
        and sandbox_desktop_provider_can_execute_tool(sandbox_provider, clean_tool)
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "reason": (
                "Read-only desktop discovery can be routed through the sandbox "
                "desktop provider without taking over foreground input."
            ),
        }
    if (
        desktop_foreground_provider_route_requested(metadata)
        and (foreground_required or execution_mode_name == "supervised_live")
        and sandbox_desktop_provider_can_execute_tool(sandbox_provider, clean_tool)
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "reason": (
                "Foreground desktop action can be routed through the sandbox "
                "desktop provider instead of the user's foreground session."
            ),
        }
    if not foreground_required and execution_mode_name != "supervised_live":
        return route
    if policy_mode == "allow":
        return {
            **route,
            "selected_provider_kind": "none",
            "selected_provider_id": "",
            "status": "supervised_live",
            "reason": "Foreground desktop execution is allowed by the current policy.",
            "fallback_mode": "supervised_live",
        }
    if policy_mode == "handoff":
        return {
            **route,
            "status": "handoff_required",
            "can_execute": False,
            "can_auto_start": False,
            "fallback_mode": "user_handoff",
            "reason": "The current policy requires the user to perform foreground desktop input.",
            "blocking_conditions": ["desktop_execution_handoff_required"],
        }
    if sandbox_required:
        return _sandbox_route_decision(route, sandbox_provider, clean_tool)
    return {
        **route,
        "status": "preview_required",
        "can_execute": False,
        "can_auto_start": False,
        "fallback_mode": "supervised_live",
        "reason": "Foreground desktop execution is blocked by preview policy.",
        "blocking_conditions": ["desktop_execution_preview_required"],
    }


def with_agent_studio_desktop_execution_policy(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, Mapping) else {}
    payload.setdefault("desktop_provider_health_probe", True)
    payload.setdefault("desktop_provider_route_readonly", True)
    payload.setdefault("desktop_provider_route_foreground", True)
    payload.setdefault("desktop_provider_local_native", True)
    if _has_desktop_execution_policy(payload):
        return payload
    payload["desktop_execution_policy"] = agent_studio_desktop_execution_policy()
    return payload


def desktop_readonly_provider_route_requested(
    metadata: Mapping[str, Any] | None,
) -> bool:
    return _metadata_truthy(metadata, *_READ_ONLY_DESKTOP_PROVIDER_ROUTE_KEYS)


def desktop_foreground_provider_route_requested(
    metadata: Mapping[str, Any] | None,
) -> bool:
    return _metadata_truthy(metadata, *_FOREGROUND_DESKTOP_PROVIDER_ROUTE_KEYS)


def is_readonly_desktop_provider_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in _READ_ONLY_DESKTOP_PROVIDER_TOOLS


def sandbox_desktop_provider_can_execute_tool(
    sandbox_provider: Mapping[str, Any],
    tool_name: str,
) -> bool:
    if not bool(sandbox_provider.get("available")):
        return False
    if not bool(sandbox_provider.get("adapter_ready")):
        return False
    supported_tools = _string_list(sandbox_provider.get("supported_tools"))
    return not supported_tools or str(tool_name or "").strip() in supported_tools


def with_daily_entrypoint_desktop_execution_policy(
    metadata: Mapping[str, Any] | None,
    *,
    surface: str = "chat",
) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, Mapping) else {}
    payload.setdefault("desktop_provider_health_probe", True)
    payload.setdefault("desktop_provider_route_readonly", True)
    payload.setdefault("desktop_provider_route_foreground", True)
    payload.setdefault("desktop_provider_local_native", True)
    if _has_desktop_execution_policy(payload):
        return payload
    payload["desktop_execution_policy"] = daily_entrypoint_desktop_execution_policy(
        surface=surface,
    )
    return payload


def runtime_execution_envelope_with_desktop_execution_policy(
    envelope: Mapping[str, Any],
    policy: Mapping[str, Any] | str,
) -> dict[str, Any]:
    payload = dict(envelope)
    clean_policy = desktop_execution_policy_payload(policy)
    if not clean_policy:
        return payload
    _ensure_canonical_desktop_execution_policy(payload, clean_policy)
    requests = payload.get("requests")
    if isinstance(requests, list):
        payload["requests"] = [
            _runtime_execution_request_with_desktop_execution_policy(request, clean_policy)
            if isinstance(request, Mapping)
            else request
            for request in requests
        ]
    return payload


def _has_desktop_execution_policy(payload: Mapping[str, Any]) -> bool:
    return any(
        bool(desktop_execution_policy_payload(payload.get(key)))
        for key in (
            "desktop_execution_policy",
            "yachiyo_desktop_execution_policy",
            "desktop_interaction_policy",
        )
    )


def _runtime_execution_request_with_desktop_execution_policy(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(request)
    _ensure_canonical_desktop_execution_policy(payload, policy)
    return payload


def _ensure_canonical_desktop_execution_policy(
    payload: dict[str, Any],
    fallback_policy: Mapping[str, Any],
) -> None:
    if desktop_execution_policy_payload(payload.get("desktop_execution_policy")):
        return
    for key in ("yachiyo_desktop_execution_policy", "desktop_interaction_policy"):
        policy = desktop_execution_policy_payload(payload.get(key))
        if policy:
            payload["desktop_execution_policy"] = policy
            return
    payload["desktop_execution_policy"] = dict(fallback_policy)


def _sandbox_provider_payload(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    for key in (
        "sandbox_desktop_provider",
        "sandbox_provider",
        "desktop_sandbox_provider",
    ):
        value = metadata.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and nested_metadata is not metadata:
        return _sandbox_provider_payload(nested_metadata)
    return {}


def _metadata_truthy(
    metadata: Mapping[str, Any] | None,
    *keys: str,
) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    for key in keys:
        value = metadata.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and nested_metadata is not metadata:
        return _metadata_truthy(nested_metadata, *keys)
    return False


def _sandbox_provider_public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "available",
        "provider_id",
        "provider_kind",
        "status",
        "adapter_ready",
        "reason",
        "blocking_conditions",
        "supported_tools",
        "recommended_for",
        "diagnostic_route",
        "source",
        "health",
        "launch_hint",
    }
    return {
        key: payload[key]
        for key in allowed_keys
        if key in payload
    }


def _sandbox_provider_payload_from_env(
    *,
    probe_health: bool = False,
) -> dict[str, Any]:
    provider_url = _first_env_value(
        (
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
            "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL",
            "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
            "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL",
        )
    )
    if not provider_url:
        return {}
    provider_status = desktop_execution_provider_status_from_env(
        probe_health=probe_health,
    )
    if str(provider_status.get("provider_kind") or "") != "sandbox_desktop":
        return {}
    if not _truthy_env_value(
        "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE"
    ) and not _is_loopback_url(provider_url):
        return {
            **provider_status,
            "provider_kind": "sandbox_desktop",
            "recommended_for": ["foreground_control", "keyboard_mouse_capture"],
            "diagnostic_route": "/yachiyo/studio/tools",
        }
    provider_kind = (
        _first_env_value(("OHA_YACHIYO_DESKTOP_PROVIDER_KIND",))
        or "sandbox_desktop"
    )
    if provider_kind.strip().lower().replace("-", "_") != "sandbox_desktop":
        return {}
    supported_tools = _string_list(
        _first_env_value(("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",))
    )
    return {
        **provider_status,
        "available": bool(provider_status.get("available")),
        "provider_id": str(provider_status.get("provider_id") or ""),
        "provider_kind": "sandbox_desktop",
        "status": str(provider_status.get("status") or "available"),
        "adapter_ready": bool(provider_status.get("adapter_ready")),
        "reason": str(
            provider_status.get("reason")
            or "Sandbox desktop provider is configured through runtime environment."
        ),
        "blocking_conditions": _string_list(provider_status.get("blocking_conditions")),
        "supported_tools": _string_list(provider_status.get("supported_tools"))
        or supported_tools,
        "recommended_for": ["foreground_control", "keyboard_mouse_capture"],
        "diagnostic_route": "/yachiyo/studio/tools",
        "source": "runtime_env",
    }


def _local_desktop_provider_payload(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not _metadata_truthy(metadata, *_LOCAL_DESKTOP_PROVIDER_KEYS):
        return {}
    return local_desktop_execution_provider_status()


def _sandbox_route_decision(
    route: Mapping[str, Any],
    sandbox_provider: Mapping[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    blockers = _string_list(sandbox_provider.get("blocking_conditions")) or [
        "sandbox_desktop_provider_required"
    ]
    provider_kind = str(sandbox_provider.get("provider_kind") or "sandbox_desktop")
    provider_id = str(sandbox_provider.get("provider_id") or "")
    if not bool(sandbox_provider.get("available")):
        return {
            **dict(route),
            "selected_provider_kind": provider_kind,
            "selected_provider_id": provider_id,
            "status": "provider_required",
            "can_execute": False,
            "can_auto_start": False,
            "sandbox_required": True,
            "fallback_mode": "supervised_live",
            "reason": str(sandbox_provider.get("reason") or ""),
            "blocking_conditions": blockers,
        }
    supported_tools = _string_list(sandbox_provider.get("supported_tools"))
    if supported_tools and tool_name not in supported_tools:
        return {
            **dict(route),
            "selected_provider_kind": provider_kind,
            "selected_provider_id": provider_id,
            "status": "sandbox_tool_not_supported",
            "can_execute": False,
            "can_auto_start": False,
            "sandbox_required": True,
            "fallback_mode": "supervised_live",
            "reason": "Sandbox provider is available but does not support this tool.",
            "blocking_conditions": ["sandbox_tool_not_supported"],
        }
    if not bool(sandbox_provider.get("adapter_ready")):
        return {
            **dict(route),
            "selected_provider_kind": provider_kind,
            "selected_provider_id": provider_id,
            "status": "sandbox_adapter_required",
            "can_execute": False,
            "can_auto_start": False,
            "sandbox_required": True,
            "fallback_mode": "supervised_live",
            "reason": "Sandbox provider is available but no executable adapter is registered yet.",
            "blocking_conditions": ["sandbox_desktop_adapter_required"],
        }
    return {
        **dict(route),
        "selected_provider_kind": provider_kind,
        "selected_provider_id": provider_id,
        "status": "sandbox_ready",
        "can_execute": True,
        "can_auto_start": True,
        "sandbox_required": True,
        "fallback_mode": "",
        "reason": "Foreground desktop action can be routed through the sandbox provider.",
        "blocking_conditions": [],
    }


def _execution_mode_payload(value: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _provider_id_for_isolation(isolation: str) -> str:
    if isolation in {"process", "browser_profile", "headless"}:
        return isolation
    return ""


def _first_env_value(keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(os.getenv(key, "") or "").strip()
        if value:
            return value
    return ""


def _truthy_env_value(key: str) -> bool:
    return str(os.getenv(key, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def _health_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "ok": False,
            "checked": False,
            "status": "not_checked",
            "blocking_conditions": [],
            "supported_tools": [],
            "capabilities": [],
        }
    payload = dict(value)
    payload["ok"] = bool(payload.get("ok"))
    payload["checked"] = bool(payload.get("checked"))
    payload["status"] = str(payload.get("status") or "")
    payload["blocking_conditions"] = _string_list(payload.get("blocking_conditions"))
    payload["supported_tools"] = _string_list(payload.get("supported_tools"))
    payload["capabilities"] = _string_list(payload.get("capabilities"))
    return payload


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items
