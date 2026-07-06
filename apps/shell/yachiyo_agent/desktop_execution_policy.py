"""Shared desktop execution policies for daily and Studio entrypoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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


def _has_desktop_execution_policy(payload: Mapping[str, Any]) -> bool:
    return any(
        isinstance(payload.get(key), (Mapping, str))
        and payload.get(key) not in (None, "", {})
        for key in (
            "desktop_execution_policy",
            "yachiyo_desktop_execution_policy",
            "desktop_interaction_policy",
        )
    )
