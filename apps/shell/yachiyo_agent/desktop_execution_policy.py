"""Shared desktop execution policies for daily and Studio entrypoints."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from apps.shell.agent.runtime.controlled_desktop_provider import (
    CONTROLLED_DESKTOP_PROVIDER_TOOLS,
)
from apps.shell.agent.runtime.desktop_execution_providers import (
    desktop_execution_provider_status_from_env,
    local_desktop_execution_provider_status,
)
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    virtual_desktop_provider_contract_evidence,
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
    "desktop_session_kind": "",
    "desktop_session_isolated": None,
    "foreground_takeover_required": None,
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
        "desktop_session_kind": "headless_read_only",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "requires_real_sandbox_for": ["click", "type", "shortcut", "focus"],
        "isolated_provider": {
            "provider_id": "local-isolated-desktop",
            "provider_kind": "sandbox_desktop",
            "execution_mode": "isolated_desktop",
            "command": [
                "python",
                "scripts/run_isolated_desktop_provider.py",
                "--host",
                "127.0.0.1",
                "--port",
                "19093",
            ],
            "smoke_command": ["python", "scripts/smoke_isolated_desktop_provider.py"],
            "env": {
                "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19093",
                "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "local-isolated-desktop",
                "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": ",".join(
                    CONTROLLED_DESKTOP_PROVIDER_TOOLS
                ),
                "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED": "true",
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": "isolated_desktop",
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": "true",
                "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": "false",
            },
            "supported_tools": list(CONTROLLED_DESKTOP_PROVIDER_TOOLS),
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "requires_runtime_approval": True,
        },
        "controlled_provider": {
            "provider_id": "local-controlled-desktop",
            "provider_kind": "sandbox_desktop",
            "execution_mode": "controlled_desktop",
            "command": [
                "python",
                "scripts/run_controlled_desktop_provider.py",
                "--host",
                "127.0.0.1",
                "--port",
                "19092",
            ],
            "smoke_command": [
                "python",
                "scripts/run_controlled_desktop_provider.py",
                "--manifest",
            ],
            "env": {
                "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19092",
                "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "local-controlled-desktop",
                "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED": "true",
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": "user_foreground",
                "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": "false",
                "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": "true",
            },
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "user_foreground",
            "desktop_session_isolated": False,
            "foreground_takeover_required": True,
            "requires_runtime_approval": True,
        },
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
        "desktop.inspect_app",
        "desktop.verify",
        "app.status",
    }
)

_KEYBOARD_MOUSE_CAPTURE_TOOLS = frozenset(
    {
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.search_submit",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.shortcut",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_text",
        "desktop.click",
    }
)

_USER_FOREGROUND_TAKEOVER_TOOLS = frozenset(
    {
        *_KEYBOARD_MOUSE_CAPTURE_TOOLS,
        "app.open",
        "app.focus",
        "app.show",
        "app.focus_window",
        "desktop.open_app",
        "desktop.focus_app",
        "media.music_app_open_and_play",
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
    """Default Chat/Bubble/Live2D policy: execute tools, but avoid user foreground takeover."""

    clean_surface = str(surface or "chat").strip() or "chat"
    return {
        "mode": "preview_input",
        "prefer_isolated_desktop": True,
        "avoid_user_foreground_takeover": True,
        "require_sandbox_for_keyboard_mouse": True,
        "allow_media_control": True,
        "source": f"daily_{clean_surface}",
        "reason": (
            "Daily entrypoints should execute through structured tools and isolated "
            "desktop providers instead of taking over the user's keyboard/mouse."
        ),
    }


def desktop_provider_session_auto_start_default() -> bool:
    value = os.environ.get("OHA_YACHIYO_DESKTOP_PROVIDER_AUTO_START", "")
    raw = value.strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return any(
        str(os.environ.get(key) or "").strip()
        for key in (
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
            "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL",
            "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
            "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL",
            "OHA_YACHIYO_DESKTOP_PROVIDER_START_COMMAND",
            "OHA_YACHIYO_DESKTOP_PROVIDER_MANIFEST",
        )
    )


_LOW_RISK_CREATION_SHORTCUT_ACTIONS = frozenset(
    {"new_document", "new_note", "new_task"}
)

_APPROVAL_FIRST_KEYBOARD_MOUSE_TOOLS = frozenset(
    {
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.safe_click",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.click",
    }
)


def desktop_provider_session_auto_start_recommended_for_requests(
    requests: Any,
) -> bool:
    """Return true when daily entrypoint requests should prefer an isolated session.

    Daily app-open, focus, media, and input actions should execute without taking
    over the user's foreground desktop; approval-first UI actions still wait for
    explicit user approval before starting a provider session.
    """

    if isinstance(requests, Mapping):
        candidates = [requests]
    else:
        try:
            candidates = list(requests or [])
        except TypeError:
            candidates = []
    for request in candidates:
        if not isinstance(request, Mapping):
            continue
        if bool(request.get("approval_required")):
            continue
        tool_name = _request_tool_name(request)
        if not tool_name:
            continue
        if tool_name in _APPROVAL_FIRST_KEYBOARD_MOUSE_TOOLS:
            continue
        if _low_risk_creation_shortcut_request(tool_name, request):
            continue
        if tool_name in _USER_FOREGROUND_TAKEOVER_TOOLS:
            return True
    return False


def _request_tool_name(request: Mapping[str, Any]) -> str:
    return str(request.get("tool") or request.get("tool_name") or "").strip()


def _low_risk_creation_shortcut_request(
    tool_name: str,
    request: Mapping[str, Any],
) -> bool:
    if tool_name not in {
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "desktop.safe_shortcut",
    }:
        return False
    payload = request.get("input")
    if not isinstance(payload, Mapping):
        payload = request.get("input_preview")
    if not isinstance(payload, Mapping):
        return False
    action = str(payload.get("action") or "").strip()
    return action in _LOW_RISK_CREATION_SHORTCUT_ACTIONS


def agent_studio_desktop_execution_policy() -> dict[str, Any]:
    """Studio is the explicit supervised execution surface."""

    return {
        "mode": "supervised_live",
        "allow_live_foreground": True,
        "prefer_isolated_desktop": True,
        "avoid_user_foreground_takeover": True,
        "require_sandbox_for_keyboard_mouse": True,
        "source": "agent_studio",
        "reason": (
            "Agent Studio is the supervised desktop execution and debugging surface; "
            "keyboard/mouse actions prefer an isolated desktop provider."
        ),
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
        payload["provider_contract"] = _provider_contract_payload(payload)
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
    decision_context = _route_policy_metadata_context(policy_payload, metadata)
    sandbox_provider = sandbox_desktop_provider_status(metadata)
    readonly_provider_requested = (
        desktop_readonly_provider_route_requested(metadata)
        or _metadata_truthy(
            policy_payload,
            "prefer_isolated_desktop",
            "desktop_provider_route_readonly",
            "provider_route_readonly",
        )
    )
    foreground_provider_requested = (
        desktop_foreground_provider_route_requested(metadata)
        or _metadata_truthy(
            policy_payload,
            "prefer_isolated_desktop",
            "avoid_user_foreground_takeover",
            "require_sandbox_for_keyboard_mouse",
            "desktop_provider_route_foreground",
            "provider_route_foreground",
        )
    )
    foreground_control = bool(mode_payload.get("foreground_control"))
    keyboard_mouse_capture = bool(mode_payload.get("keyboard_mouse_capture"))
    foreground_required = foreground_control or keyboard_mouse_capture
    sandbox_required = bool(mode_payload.get("sandbox_recommended")) or (
        str(policy_payload.get("mode") or "").strip().lower().replace("-", "_")
        == "sandbox_preferred"
    )
    isolated_desktop_preferred = _metadata_truthy(
        decision_context,
        "prefer_isolated_desktop",
        "avoid_user_foreground_takeover",
        "require_sandbox_for_keyboard_mouse",
    )
    foreground_takeover_allowed = user_foreground_takeover_allowed(decision_context)
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
        "isolated_desktop_preferred": isolated_desktop_preferred,
        "foreground_takeover_allowed": foreground_takeover_allowed,
        "desktop_execution_session_policy": (
            "explicit_user_foreground"
            if foreground_takeover_allowed
            else (
                "isolated_preferred"
                if isolated_desktop_preferred
                else "structured_runtime"
            )
        ),
        "user_foreground_takeover_risk": False,
        "requires_user_foreground_session": False,
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
        foreground_provider_requested
        and foreground_required
        and not bool(sandbox_provider.get("available"))
    ):
        return _sandbox_route_decision(route, sandbox_provider, clean_tool)
    if (
        readonly_provider_requested
        and is_readonly_desktop_provider_tool(clean_tool)
        and sandbox_desktop_provider_can_execute_tool(sandbox_provider, clean_tool)
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "reason": _readonly_desktop_provider_route_reason(sandbox_provider),
        }
    if (
        foreground_provider_requested
        and (foreground_required or execution_mode_name == "supervised_live")
        and _sandbox_provider_requires_keyboard_mouse_sandbox(
            sandbox_provider,
            clean_tool,
        )
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "reason": (
                "Keyboard and mouse foreground actions require the controlled "
                "desktop provider so the agent does not take over the user's session."
            ),
        }
    if (
        foreground_provider_requested
        and (foreground_required or execution_mode_name == "supervised_live")
        and _sandbox_provider_requires_isolated_keyboard_mouse_session(
            sandbox_provider,
            clean_tool,
            decision_context,
        )
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "status": "sandbox_desktop_session_required",
            "can_execute": False,
            "can_auto_start": False,
            "sandbox_required": True,
            "fallback_mode": "supervised_live",
            "reason": (
                "Keyboard and mouse foreground actions must run inside an isolated "
                "desktop session unless the user explicitly allows foreground takeover."
            ),
            "blocking_conditions": ["sandbox_desktop_session_required"],
        }
    if (
        foreground_provider_requested
        and (foreground_required or execution_mode_name == "supervised_live")
        and sandbox_desktop_provider_can_execute_tool(sandbox_provider, clean_tool)
    ):
        sandbox_route = _sandbox_route_decision(route, sandbox_provider, clean_tool)
        return {
            **sandbox_route,
            "reason": _foreground_desktop_provider_route_reason(sandbox_provider),
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


def is_user_foreground_takeover_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in _USER_FOREGROUND_TAKEOVER_TOOLS


def user_foreground_takeover_allowed(metadata: Mapping[str, Any] | None) -> bool:
    return _metadata_truthy(
        metadata,
        "allow_user_foreground_takeover",
        "desktop_allow_user_foreground_takeover",
        "allow_nonisolated_desktop_provider",
    )


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
    if user_foreground_takeover_allowed(payload):
        payload.setdefault("desktop_provider_local_native", True)
        payload["desktop_execution_policy"] = {
            **daily_entrypoint_desktop_execution_policy(surface=surface),
            "mode": "allow",
            "allow_live_foreground": True,
            "prefer_isolated_desktop": False,
            "avoid_user_foreground_takeover": False,
            "require_sandbox_for_keyboard_mouse": False,
            "reason": (
                "Daily entrypoint is explicitly allowed to use the user's foreground "
                "desktop session for this request."
            ),
        }
        return payload
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
    provider_session = _sandbox_provider_payload_from_desktop_provider_session(metadata)
    if provider_session:
        return provider_session
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and nested_metadata is not metadata:
        return _sandbox_provider_payload(nested_metadata)
    return {}


def _sandbox_provider_payload_from_desktop_provider_session(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    session = metadata.get("desktop_provider_session")
    if not isinstance(session, Mapping):
        return {}
    running = bool(session.get("running"))
    provider_id = str(session.get("provider_id") or "").strip()
    url = str(session.get("url") or "").strip()
    tool_names = _string_list(session.get("tool_names")) or _string_list(
        session.get("supported_tools")
    )
    blockers = [] if running else ["sandbox_desktop_provider_required"]
    return {
        "available": running,
        "provider_id": provider_id,
        "provider_kind": "sandbox_desktop",
        "status": "available" if running else "provider_required",
        "adapter_ready": running and bool(url),
        "reason": str(
            session.get("reason")
            or (
                "Isolated desktop provider session is running."
                if running
                else "Isolated desktop provider session is required."
            )
        ),
        "blocking_conditions": blockers,
        "supported_tools": tool_names,
        "recommended_for": ["foreground_control", "keyboard_mouse_capture"],
        "source": "desktop_provider_session",
        "desktop_session_kind": str(
            session.get("desktop_session_kind") or "isolated_desktop"
        ),
        "desktop_session_isolated": _optional_bool_value(
            session.get("desktop_session_isolated")
        )
        if "desktop_session_isolated" in session
        else True,
        "foreground_takeover_required": _optional_bool_value(
            session.get("foreground_takeover_required")
        )
        if "foreground_takeover_required" in session
        else False,
        "desktop_backend_kind": str(session.get("desktop_backend_kind") or ""),
        "desktop_backend_is_loopback": _optional_bool_value(
            session.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool_value(
            session.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": _optional_bool_value(
            session.get("requires_real_virtual_desktop_backend")
        ),
        "keyboard_mouse_capture_supported": _optional_bool_value(
            session.get("keyboard_mouse_capture_supported")
        )
        if "keyboard_mouse_capture_supported" in session
        else True,
    }


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


def _route_policy_metadata_context(
    policy_payload: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = dict(policy_payload)
    if isinstance(metadata, Mapping):
        context.update(metadata)
    return context


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
        "foreground_mutation_supported",
        "keyboard_mouse_capture_supported",
        "desktop_session_kind",
        "desktop_session_isolated",
        "foreground_takeover_required",
        "desktop_backend_kind",
        "desktop_backend_is_loopback",
        "desktop_backend_ready_for_public_release",
        "requires_real_virtual_desktop_backend",
        "provider_contract",
        "requires_real_sandbox_for",
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
        "desktop_session_kind": str(
            provider_status.get("desktop_session_kind") or ""
        ),
        "desktop_session_isolated": _optional_bool_value(
            provider_status.get("desktop_session_isolated")
        ),
        "foreground_takeover_required": _optional_bool_value(
            provider_status.get("foreground_takeover_required")
        ),
        "desktop_backend_kind": str(provider_status.get("desktop_backend_kind") or ""),
        "desktop_backend_is_loopback": _optional_bool_value(
            provider_status.get("desktop_backend_is_loopback")
        ),
        "desktop_backend_ready_for_public_release": _optional_bool_value(
            provider_status.get("desktop_backend_ready_for_public_release")
        ),
        "requires_real_virtual_desktop_backend": _optional_bool_value(
            provider_status.get("requires_real_virtual_desktop_backend")
        ),
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
    provider_context = _desktop_provider_route_context(sandbox_provider, tool_name)
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
            **provider_context,
        }
    supported_tools = _string_list(sandbox_provider.get("supported_tools"))
    if _sandbox_provider_requires_keyboard_mouse_sandbox(sandbox_provider, tool_name):
        return {
            **dict(route),
            "selected_provider_kind": provider_kind,
            "selected_provider_id": provider_id,
            "status": "sandbox_keyboard_mouse_provider_required",
            "can_execute": False,
            "can_auto_start": False,
            "sandbox_required": True,
            "fallback_mode": "supervised_live",
            "reason": (
                "Current desktop provider can open or focus apps, but keyboard and "
                "mouse capture must run through a real sandbox/control provider."
            ),
            "blocking_conditions": ["sandbox_keyboard_mouse_provider_required"],
            **provider_context,
        }
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
            **provider_context,
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
            **provider_context,
        }
    ready_status = _desktop_provider_ready_status(sandbox_provider)
    sandbox_required = ready_status == "sandbox_ready"
    return {
        **dict(route),
        "selected_provider_kind": provider_kind,
        "selected_provider_id": provider_id,
        "status": ready_status,
        "can_execute": True,
        "can_auto_start": True,
        "provider_execution_required": True,
        "sandbox_required": sandbox_required,
        "fallback_mode": "",
        "reason": _desktop_provider_ready_reason(sandbox_provider),
        "blocking_conditions": [],
        **provider_context,
    }


def _desktop_provider_route_context(
    sandbox_provider: Mapping[str, Any],
    tool_name: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "foreground_mutation_supported",
        "keyboard_mouse_capture_supported",
        "desktop_session_isolated",
        "foreground_takeover_required",
    ):
        if key in sandbox_provider:
            payload[key] = _optional_bool_value(sandbox_provider.get(key))
    session_kind = str(sandbox_provider.get("desktop_session_kind") or "").strip()
    if session_kind:
        payload["desktop_session_kind"] = session_kind
    takeover_required = (
        _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True
    )
    isolated_session = (
        _optional_bool_value(sandbox_provider.get("desktop_session_isolated")) is True
        or session_kind in {"isolated_desktop", "sandbox_desktop", "virtual_desktop"}
    )
    requires_user_session = takeover_required or session_kind == "user_foreground"
    payload["requires_user_foreground_session"] = requires_user_session and not isolated_session
    payload["user_foreground_takeover_risk"] = bool(
        payload["requires_user_foreground_session"]
        and str(tool_name or "").strip() in _USER_FOREGROUND_TAKEOVER_TOOLS
    )
    return payload


def _desktop_provider_ready_status(sandbox_provider: Mapping[str, Any]) -> str:
    provider_kind = str(sandbox_provider.get("provider_kind") or "").strip()
    if provider_kind != "sandbox_desktop":
        return "provider_ready"
    if _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True:
        return "provider_ready"
    return "sandbox_ready"


def _desktop_provider_ready_reason(sandbox_provider: Mapping[str, Any]) -> str:
    if _desktop_provider_ready_status(sandbox_provider) == "sandbox_ready":
        return "Foreground desktop action can be routed through the sandbox provider."
    provider_kind = str(sandbox_provider.get("provider_kind") or "desktop provider").strip()
    if _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True:
        return (
            f"Desktop action can be routed through the {provider_kind} provider, "
            "but that provider uses the user's foreground desktop session."
        )
    return f"Desktop action can be routed through the {provider_kind} provider."


def _readonly_desktop_provider_route_reason(
    sandbox_provider: Mapping[str, Any],
) -> str:
    if _desktop_provider_ready_status(sandbox_provider) == "sandbox_ready":
        return (
            "Read-only desktop discovery can be routed through the sandbox "
            "desktop provider without taking over foreground input."
        )
    provider_kind = str(sandbox_provider.get("provider_kind") or "desktop provider").strip()
    if _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True:
        return (
            f"Read-only desktop discovery can be routed through the {provider_kind} "
            "provider. It does not request keyboard or mouse capture, but it "
            "observes the user's desktop session."
        )
    return f"Read-only desktop discovery can be routed through the {provider_kind} provider."


def _foreground_desktop_provider_route_reason(
    sandbox_provider: Mapping[str, Any],
) -> str:
    if _desktop_provider_ready_status(sandbox_provider) == "sandbox_ready":
        return (
            "Foreground desktop action can be routed through the sandbox "
            "desktop provider instead of the user's foreground session."
        )
    provider_kind = str(sandbox_provider.get("provider_kind") or "desktop provider").strip()
    if _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True:
        return (
            f"Foreground desktop action can be routed through the {provider_kind} "
            "provider, but that provider may use the user's foreground desktop "
            "session."
        )
    return f"Foreground desktop action can be routed through the {provider_kind} provider."


def _sandbox_provider_requires_keyboard_mouse_sandbox(
    sandbox_provider: Mapping[str, Any],
    tool_name: str,
) -> bool:
    clean_tool = str(tool_name or "").strip()
    if clean_tool not in _KEYBOARD_MOUSE_CAPTURE_TOOLS:
        return False
    if "keyboard_mouse_capture_supported" not in sandbox_provider:
        return False
    raw_capture_supported = sandbox_provider.get("keyboard_mouse_capture_supported")
    if (
        raw_capture_supported is not False
        and str(raw_capture_supported).strip().lower()
        not in {"0", "false", "no", "off"}
    ):
        return False
    required = _string_list(sandbox_provider.get("requires_real_sandbox_for"))
    return not required or clean_tool in required or "keyboard_mouse_capture" in required


def _sandbox_provider_requires_isolated_keyboard_mouse_session(
    sandbox_provider: Mapping[str, Any],
    tool_name: str,
    metadata: Mapping[str, Any] | None,
) -> bool:
    clean_tool = str(tool_name or "").strip()
    if clean_tool not in _KEYBOARD_MOUSE_CAPTURE_TOOLS:
        return False
    if _metadata_truthy(
        metadata,
        "allow_user_foreground_takeover",
        "desktop_allow_user_foreground_takeover",
        "allow_nonisolated_desktop_provider",
    ):
        return False
    if _optional_bool_value(sandbox_provider.get("foreground_takeover_required")) is True:
        return True
    if _optional_bool_value(sandbox_provider.get("desktop_session_isolated")) is True:
        return False
    session_kind = str(sandbox_provider.get("desktop_session_kind") or "").strip()
    if session_kind in {"isolated_desktop", "sandbox_desktop", "virtual_desktop"}:
        return False
    if _optional_bool_value(sandbox_provider.get("desktop_session_isolated")) is False:
        return True
    return _optional_bool_value(
        sandbox_provider.get("keyboard_mouse_capture_supported")
    ) is True and str(sandbox_provider.get("provider_kind") or "") != "sandbox_desktop"


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
    if "foreground_mutation_supported" in payload:
        payload["foreground_mutation_supported"] = _optional_bool_value(
            payload.get("foreground_mutation_supported")
        )
    if "keyboard_mouse_capture_supported" in payload:
        payload["keyboard_mouse_capture_supported"] = _optional_bool_value(
            payload.get("keyboard_mouse_capture_supported")
        )
    payload["desktop_session_kind"] = str(payload.get("desktop_session_kind") or "")
    if "desktop_session_isolated" in payload:
        payload["desktop_session_isolated"] = _optional_bool_value(
            payload.get("desktop_session_isolated")
        )
    if "foreground_takeover_required" in payload:
        payload["foreground_takeover_required"] = _optional_bool_value(
            payload.get("foreground_takeover_required")
        )
    payload["desktop_backend_kind"] = str(payload.get("desktop_backend_kind") or "")
    if "desktop_backend_is_loopback" in payload:
        payload["desktop_backend_is_loopback"] = _optional_bool_value(
            payload.get("desktop_backend_is_loopback")
        )
    if "desktop_backend_ready_for_public_release" in payload:
        payload["desktop_backend_ready_for_public_release"] = _optional_bool_value(
            payload.get("desktop_backend_ready_for_public_release")
        )
    if "requires_real_virtual_desktop_backend" in payload:
        payload["requires_real_virtual_desktop_backend"] = _optional_bool_value(
            payload.get("requires_real_virtual_desktop_backend")
        )
    payload["requires_real_sandbox_for"] = _string_list(
        payload.get("requires_real_sandbox_for")
    )
    return payload


def _provider_contract_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    status = dict(payload)
    status.setdefault(
        "configured",
        bool(status.get("provider_id")) or bool(status.get("available")),
    )
    return virtual_desktop_provider_contract_evidence(
        status,
        required_tools=OHA_DESKTOP_AGENT_RELEASE_PROVIDER_TOOLS,
    )


def _optional_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "on", "supported", "ready"}:
            return True
        if clean in {"0", "false", "no", "off", "unsupported", "blocked"}:
            return False
    return None


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
