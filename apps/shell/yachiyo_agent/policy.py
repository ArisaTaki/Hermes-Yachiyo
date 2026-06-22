"""Product-level helpers for approval-aware surfaces."""

from __future__ import annotations

import platform
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    DesktopExecutionCapabilitySnapshot,
    DesktopExecutionRisk,
)

DESKTOP_EXECUTION_CAPABILITY_IDS = (
    "desktop_execution",
    "screen_capture",
    "active_window",
    "app_control",
    "media_control",
    "foreground_input",
    "browser_control",
)

LOW_RISK_DESKTOP_TOOLS = frozenset(
    {
        "screen.capture",
        "desktop.active_window",
        "app.open",
        "app.focus",
        "media.apple_music_play",
    }
)
MEDIUM_RISK_DESKTOP_TOOLS = frozenset({"desktop.hotkey", "desktop.type_text"})
HIGH_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "delete_or_overwrite_user_file",
        "send_external_message",
        "payment_or_purchase",
        "system_settings_change",
        "raw_shell",
        "credential_access",
    }
)

DESKTOP_TOOL_RISK_LEVELS: dict[str, DesktopExecutionRisk] = {
    **{tool: "low" for tool in LOW_RISK_DESKTOP_TOOLS},
    **{tool: "medium" for tool in MEDIUM_RISK_DESKTOP_TOOLS},
}

DESKTOP_CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "desktop_execution": (
        "screen.capture",
        "desktop.active_window",
        "app.open",
        "app.focus",
        "media.apple_music_play",
        "desktop.hotkey",
        "desktop.type_text",
        "browser.open_url",
        "browser.current_page",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    ),
    "screen_capture": ("screen.capture",),
    "active_window": ("desktop.active_window",),
    "app_control": ("app.open", "app.focus"),
    "media_control": ("media.apple_music_play",),
    "foreground_input": ("desktop.hotkey", "desktop.type_text"),
    "browser_control": (
        "browser.open_url",
        "browser.current_page",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    ),
}

DESKTOP_CAPABILITY_RISK_DEFAULTS: dict[str, DesktopExecutionRisk] = {
    "desktop_execution": "low",
    "screen_capture": "low",
    "active_window": "low",
    "app_control": "low",
    "media_control": "low",
    "foreground_input": "medium",
    "browser_control": "medium",
}

DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES: dict[str, str | None] = {
    "desktop_execution": "/yachiyo/readiness",
    "screen_capture": "/screen/current",
    "active_window": "/system/active-window",
    "app_control": "/ui/native-agent/diagnostics/cache",
    "media_control": "/ui/native-agent/diagnostics/cache",
    "foreground_input": "/ui/native-agent/diagnostics/cache",
    "browser_control": "/ui/native-agent/diagnostics/cache",
}


def approval_is_pending(approval: ApprovalCardSnapshot) -> bool:
    return approval.status == "pending"


def task_requires_user_action(task: AgentTaskSnapshot) -> bool:
    return task.needs_user_action or any(
        approval_is_pending(item) for item in task.pending_approvals
    )


def desktop_tool_risk_level(tool_name: str) -> DesktopExecutionRisk | None:
    return DESKTOP_TOOL_RISK_LEVELS.get(str(tool_name or "").strip())


def is_high_risk_desktop_action(action_name: str) -> bool:
    return str(action_name or "").strip() in HIGH_RISK_DESKTOP_ACTIONS


def desktop_execution_capability_snapshots(
    *,
    registered_tools: Iterable[str] | None = None,
    platform_name: str | None = None,
    missing_permissions: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return public readiness entries for desktop execution capabilities."""

    platform_id = _desktop_platform(platform_name)
    supported = platform_id == "macos"
    registered = {str(tool or "").strip() for tool in registered_tools or []}
    missing_by_capability = missing_permissions or {}
    capability_models: dict[str, DesktopExecutionCapabilitySnapshot] = {}
    child_availability: dict[str, bool] = {}

    for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS:
        if capability_id == "desktop_execution":
            continue
        tools = list(DESKTOP_CAPABILITY_TOOLS[capability_id])
        missing = _missing_permissions(missing_by_capability, capability_id)
        available = supported and bool(tools) and all(tool in registered for tool in tools)
        available = available and not missing
        child_availability[capability_id] = available
        capability_models[capability_id] = DesktopExecutionCapabilitySnapshot(
            available=available,
            platform=platform_id,
            missing_permissions=missing,
            tools=tools,
            risk_default=DESKTOP_CAPABILITY_RISK_DEFAULTS[capability_id],
            diagnostic_route=DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES[capability_id],
        )

    root_missing = _missing_permissions(missing_by_capability, "desktop_execution")
    capability_models["desktop_execution"] = DesktopExecutionCapabilitySnapshot(
        available=supported and any(child_availability.values()) and not root_missing,
        platform=platform_id,
        missing_permissions=root_missing,
        tools=list(DESKTOP_CAPABILITY_TOOLS["desktop_execution"]),
        risk_default=DESKTOP_CAPABILITY_RISK_DEFAULTS["desktop_execution"],
        diagnostic_route=DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES["desktop_execution"],
    )

    return {
        capability_id: capability_models[capability_id].model_dump(mode="json")
        for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS
    }


def _desktop_platform(platform_name: str | None = None) -> str:
    raw = str(platform_name or platform.system() or "").strip().lower()
    if raw in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if raw.startswith("win"):
        return "windows"
    if raw == "linux":
        return "linux"
    return raw or "unknown"


def _missing_permissions(
    missing_permissions: Mapping[str, Iterable[str]],
    capability_id: str,
) -> list[str]:
    values = missing_permissions.get(capability_id, [])
    return [str(value or "").strip() for value in values if str(value or "").strip()]
