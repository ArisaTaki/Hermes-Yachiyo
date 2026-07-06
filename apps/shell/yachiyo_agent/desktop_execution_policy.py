"""Shared desktop execution policies for daily and Studio entrypoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_SANDBOX_DESKTOP_PROVIDER_DEFAULT: dict[str, Any] = {
    "available": False,
    "provider_id": "",
    "provider_kind": "sandbox_desktop",
    "status": "provider_required",
    "reason": (
        "No sandbox desktop provider is configured for this runtime yet; "
        "foreground input must stay supervised or use user handoff."
    ),
    "blocking_conditions": ["sandbox_desktop_provider_required"],
    "supported_tools": [],
    "recommended_for": ["foreground_control", "keyboard_mouse_capture"],
    "diagnostic_route": "/yachiyo/studio/tools",
    "source": "runtime",
}


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
) -> dict[str, Any]:
    """Return the runtime-visible sandbox desktop provider status."""

    provider = _sandbox_provider_payload(metadata)
    if provider:
        payload = {**_SANDBOX_DESKTOP_PROVIDER_DEFAULT, **provider}
        payload["available"] = bool(payload.get("available"))
        if payload["available"]:
            if str(payload.get("status") or "").strip() == "provider_required":
                payload["status"] = "available"
            payload["blocking_conditions"] = _string_list(provider.get("blocking_conditions"))
        else:
            blockers = _string_list(payload.get("blocking_conditions"))
            payload["blocking_conditions"] = blockers or ["sandbox_desktop_provider_required"]
        payload["supported_tools"] = _string_list(payload.get("supported_tools"))
        payload["recommended_for"] = _string_list(payload.get("recommended_for"))
        return payload
    return dict(_SANDBOX_DESKTOP_PROVIDER_DEFAULT)


def with_agent_studio_desktop_execution_policy(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, Mapping) else {}
    if _has_desktop_execution_policy(payload):
        return payload
    payload["desktop_execution_policy"] = agent_studio_desktop_execution_policy()
    return payload


def with_daily_entrypoint_desktop_execution_policy(
    metadata: Mapping[str, Any] | None,
    *,
    surface: str = "chat",
) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, Mapping) else {}
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
