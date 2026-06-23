"""Product-level helpers for approval-aware surfaces."""

from __future__ import annotations

import platform
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    DesktopActionRiskSnapshot,
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
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "app.status",
        "app.open",
        "app.focus",
        "desktop.reveal_path",
        "desktop.open_path",
        "media.apple_music_play",
        "media.apple_music_control",
        "system.volume",
        "clipboard.write",
        "desktop.minimize_window",
    }
)
MEDIUM_RISK_DESKTOP_TOOLS = frozenset(
    {"app.quit", "desktop.close_window", "desktop.hotkey", "desktop.type_text", "desktop.click"}
)
LOW_RISK_BROWSER_TOOLS = frozenset(
    {
        "browser.open_url",
        "browser.current_page",
        "browser.extract_text",
        "browser.screenshot",
    }
)
MEDIUM_RISK_BROWSER_TOOLS = frozenset({"browser.click", "browser.type_text"})
LOW_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "read_screen",
        "diagnose_permissions",
        "read_active_window",
        "read_running_apps",
        "read_windows",
        "read_app_status",
        "open_app",
        "focus_app",
        "reveal_path",
        "open_path",
        "play_or_pause_media",
        "control_system_volume",
        "write_clipboard",
        "foreground_minimize_window",
    }
)
MEDIUM_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "foreground_click",
        "foreground_close_window",
        "foreground_type_text",
        "foreground_hotkey",
        "quit_app",
    }
)
HIGH_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "delete_or_overwrite_user_file",
        "delete_user_file",
        "overwrite_user_file",
        "send_external_message",
        "send_message",
        "payment_or_purchase",
        "payment",
        "system_settings_change",
        "system_settings",
        "raw_shell",
        "terminal_shell",
        "credential_access",
    }
)

DESKTOP_ACTION_RISK_LEVELS: dict[str, DesktopExecutionRisk] = {
    **{action: "low" for action in LOW_RISK_DESKTOP_ACTIONS},
    **{action: "medium" for action in MEDIUM_RISK_DESKTOP_ACTIONS},
    **{action: "high" for action in HIGH_RISK_DESKTOP_ACTIONS},
}
DESKTOP_ACTION_RISK_ORDER = (
    "read_screen",
    "diagnose_permissions",
    "read_active_window",
    "read_running_apps",
    "read_windows",
    "read_app_status",
    "open_app",
    "focus_app",
    "quit_app",
    "reveal_path",
    "open_path",
    "play_or_pause_media",
    "control_system_volume",
    "write_clipboard",
    "foreground_minimize_window",
    "foreground_click",
    "foreground_close_window",
    "foreground_type_text",
    "foreground_hotkey",
    "delete_or_overwrite_user_file",
    "delete_user_file",
    "overwrite_user_file",
    "send_external_message",
    "send_message",
    "payment_or_purchase",
    "payment",
    "system_settings_change",
    "system_settings",
    "raw_shell",
    "terminal_shell",
    "credential_access",
)

DESKTOP_ACTION_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "read_screen": ("screen.capture",),
    "diagnose_permissions": ("desktop.permissions",),
    "read_active_window": ("desktop.active_window",),
    "read_running_apps": ("desktop.running_apps",),
    "read_windows": ("desktop.windows",),
    "read_app_status": ("app.status",),
    "open_app": ("app.open",),
    "focus_app": ("app.focus",),
    "quit_app": ("app.quit",),
    "reveal_path": ("desktop.reveal_path",),
    "open_path": ("desktop.open_path",),
    "play_or_pause_media": ("media.apple_music_play", "media.apple_music_control"),
    "control_system_volume": ("system.volume",),
    "write_clipboard": ("clipboard.write",),
    "foreground_minimize_window": ("desktop.minimize_window",),
    "foreground_click": ("desktop.click", "browser.click"),
    "foreground_close_window": ("desktop.close_window",),
    "foreground_type_text": ("desktop.type_text", "browser.type_text"),
    "foreground_hotkey": ("desktop.hotkey",),
    "delete_or_overwrite_user_file": ("workspace.write_patch",),
    "delete_user_file": ("workspace.write_patch",),
    "overwrite_user_file": ("workspace.write_patch",),
    "raw_shell": ("terminal.run",),
    "terminal_shell": ("terminal.run",),
}

DESKTOP_ACTION_TITLES: dict[str, str] = {
    "read_screen": "Read screen",
    "diagnose_permissions": "Diagnose desktop permissions",
    "read_active_window": "Read active window",
    "open_app": "Open app",
    "focus_app": "Focus app",
    "quit_app": "Quit app",
    "open_path": "Open local path",
    "play_or_pause_media": "Play or pause media",
    "control_system_volume": "Control system volume",
    "write_clipboard": "Write clipboard",
    "foreground_minimize_window": "Minimize foreground window",
    "foreground_click": "Click foreground UI",
    "foreground_close_window": "Close foreground window",
    "foreground_type_text": "Type into foreground UI",
    "foreground_hotkey": "Send foreground hotkey",
    "delete_or_overwrite_user_file": "Delete or overwrite user file",
    "delete_user_file": "Delete user file",
    "overwrite_user_file": "Overwrite user file",
    "send_external_message": "Send external message",
    "send_message": "Send message",
    "payment_or_purchase": "Payment or purchase",
    "payment": "Payment",
    "system_settings_change": "Change system settings",
    "system_settings": "System settings",
    "raw_shell": "Run raw shell",
    "terminal_shell": "Run terminal shell",
    "credential_access": "Access credentials",
}

DESKTOP_ACTION_DESCRIPTIONS: dict[str, str] = {
    "read_screen": "Capture or inspect visible desktop state.",
    "diagnose_permissions": "Read missing desktop permission targets and affected tools.",
    "read_active_window": "Read the foreground application and window title.",
    "open_app": "Launch a local desktop application.",
    "focus_app": "Bring a local desktop application to the foreground.",
    "quit_app": "Quit a local desktop application after approval.",
    "open_path": "Open a safe local file or folder with the system default app.",
    "play_or_pause_media": "Control local media playback such as Apple Music.",
    "control_system_volume": "Read or adjust local system output volume.",
    "write_clipboard": "Write explicit user-provided text to the system clipboard.",
    "foreground_minimize_window": "Minimize the current foreground window.",
    "foreground_click": "Click in the foreground application or browser page.",
    "foreground_close_window": "Close the current foreground window after approval.",
    "foreground_type_text": "Enter text into the current foreground target.",
    "foreground_hotkey": "Send a keyboard shortcut to the foreground target.",
    "delete_or_overwrite_user_file": "Delete or overwrite user-controlled files.",
    "delete_user_file": "Delete a user-controlled file.",
    "overwrite_user_file": "Overwrite a user-controlled file.",
    "send_external_message": "Send a message or notification to another person or service.",
    "send_message": "Send a message to another person or service.",
    "payment_or_purchase": "Spend money, purchase, subscribe, or transfer value.",
    "payment": "Spend money, purchase, subscribe, or transfer value.",
    "system_settings_change": "Change operating system or application settings.",
    "system_settings": "Change operating system or application settings.",
    "raw_shell": "Run arbitrary shell or terminal commands.",
    "terminal_shell": "Run arbitrary shell or terminal commands.",
    "credential_access": "Read, reveal, export, or use credentials and secrets.",
}

DESKTOP_TOOL_RISK_LEVELS: dict[str, DesktopExecutionRisk] = {
    **{tool: "low" for tool in LOW_RISK_DESKTOP_TOOLS},
    **{tool: "medium" for tool in MEDIUM_RISK_DESKTOP_TOOLS},
    **{tool: "low" for tool in LOW_RISK_BROWSER_TOOLS},
    **{tool: "medium" for tool in MEDIUM_RISK_BROWSER_TOOLS},
}

DESKTOP_CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "desktop_execution": (
        "screen.capture",
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "app.status",
        "app.open",
        "app.focus",
        "app.quit",
        "desktop.reveal_path",
        "desktop.open_path",
        "media.apple_music_play",
        "media.apple_music_control",
        "system.volume",
        "clipboard.write",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.hotkey",
        "desktop.type_text",
        "desktop.click",
        "browser.open_url",
        "browser.current_page",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    ),
    "screen_capture": ("screen.capture",),
    "active_window": ("desktop.active_window", "desktop.running_apps", "desktop.windows"),
    "app_control": ("app.status", "app.open", "app.focus", "app.quit"),
    "media_control": ("media.apple_music_play", "media.apple_music_control"),
    "foreground_input": (
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.hotkey",
        "desktop.type_text",
        "desktop.click",
    ),
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

DEGRADED_DESKTOP_TOOL_PERMISSION_FALLBACKS: dict[str, tuple[str, ...]] = {
    "browser.open_url": ("chrome_cdp",),
    "browser.screenshot": ("chrome_cdp",),
    "browser.click": ("chrome_cdp",),
    "browser.type_text": ("chrome_cdp",),
    "media.apple_music_play": ("automation",),
    "media.apple_music_control": ("automation",),
}

GROUP_TOOL_POLICY_PRESETS: dict[str, tuple[str, ...]] = {
    "desktop_execution": DESKTOP_CAPABILITY_TOOLS["desktop_execution"],
    "desktop": DESKTOP_CAPABILITY_TOOLS["desktop_execution"],
    "daily_desktop": DESKTOP_CAPABILITY_TOOLS["desktop_execution"],
    "desktop_low_medium": DESKTOP_CAPABILITY_TOOLS["desktop_execution"],
    "screen_capture": DESKTOP_CAPABILITY_TOOLS["screen_capture"],
    "screen": DESKTOP_CAPABILITY_TOOLS["screen_capture"],
    "active_window": DESKTOP_CAPABILITY_TOOLS["active_window"],
    "app_control": DESKTOP_CAPABILITY_TOOLS["app_control"],
    "app": DESKTOP_CAPABILITY_TOOLS["app_control"],
    "media_control": DESKTOP_CAPABILITY_TOOLS["media_control"],
    "media": DESKTOP_CAPABILITY_TOOLS["media_control"],
    "foreground_input": DESKTOP_CAPABILITY_TOOLS["foreground_input"],
    "input": DESKTOP_CAPABILITY_TOOLS["foreground_input"],
    "browser_control": DESKTOP_CAPABILITY_TOOLS["browser_control"],
    "browser": DESKTOP_CAPABILITY_TOOLS["browser_control"],
}


def approval_is_pending(approval: ApprovalCardSnapshot) -> bool:
    return approval.status == "pending"


def task_requires_user_action(task: AgentTaskSnapshot) -> bool:
    return task.needs_user_action or any(
        approval_is_pending(item) for item in task.pending_approvals
    )


def desktop_tool_risk_level(tool_name: str) -> DesktopExecutionRisk | None:
    return DESKTOP_TOOL_RISK_LEVELS.get(str(tool_name or "").strip())


def desktop_action_risk_level(action_name: str) -> DesktopExecutionRisk | None:
    return DESKTOP_ACTION_RISK_LEVELS.get(str(action_name or "").strip())


def is_high_risk_desktop_action(action_name: str) -> bool:
    return desktop_action_risk_level(action_name) == "high"


def desktop_action_risk_snapshots() -> list[DesktopActionRiskSnapshot]:
    """Return the product-level desktop action risk catalog."""

    return [
        DesktopActionRiskSnapshot(
            action_id=action_id,
            risk_level=DESKTOP_ACTION_RISK_LEVELS[action_id],
            title=DESKTOP_ACTION_TITLES.get(action_id, action_id.replace("_", " ").title()),
            description=DESKTOP_ACTION_DESCRIPTIONS.get(action_id, ""),
            tools=list(DESKTOP_ACTION_TOOL_HINTS.get(action_id, ())),
            requires_approval=DESKTOP_ACTION_RISK_LEVELS[action_id] == "high",
        )
        for action_id in DESKTOP_ACTION_RISK_ORDER
        if action_id in DESKTOP_ACTION_RISK_LEVELS
    ]


def group_tool_policy_for_id(policy_id: str | None) -> dict[str, Any]:
    """Return the built-in group-level tool policy for a stable policy id."""

    token = _group_policy_token(policy_id)
    tools = GROUP_TOOL_POLICY_PRESETS.get(token, ())
    if not tools:
        return {}
    approval_required = {
        tool: True
        for tool in tools
        if tool in MEDIUM_RISK_DESKTOP_TOOLS or tool in MEDIUM_RISK_BROWSER_TOOLS
    }
    return {"allowed_tools": list(tools), "approval_required": approval_required}


def merge_tool_policies(
    base_policy: Mapping[str, Any] | None,
    inherited_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Union two runtime tool policies without weakening explicit approvals."""

    base = base_policy if isinstance(base_policy, Mapping) else {}
    inherited = inherited_policy if isinstance(inherited_policy, Mapping) else {}
    allowed_tools: list[str] = []
    for policy in (base, inherited):
        raw_allowed = policy.get("allowed_tools")
        if isinstance(raw_allowed, str):
            raw_allowed = [raw_allowed]
        if not isinstance(raw_allowed, Iterable):
            continue
        for tool in raw_allowed:
            clean = str(tool or "").strip()
            if clean and clean not in allowed_tools:
                allowed_tools.append(clean)

    approval_required: dict[str, bool] = {}
    for policy in (base, inherited):
        raw_approval = policy.get("approval_required")
        if not isinstance(raw_approval, Mapping):
            continue
        for tool, required in raw_approval.items():
            clean = str(tool or "").strip()
            if clean and bool(required):
                approval_required[clean] = True
            elif clean and clean not in approval_required:
                approval_required[clean] = False

    return {
        "allowed_tools": allowed_tools,
        "approval_required": approval_required,
    }


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
    child_available_tools: dict[str, list[str]] = {}
    child_degraded_tools: dict[str, list[str]] = {}
    child_unavailable_tools: dict[str, list[str]] = {}

    for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS:
        if capability_id == "desktop_execution":
            continue
        tools = list(DESKTOP_CAPABILITY_TOOLS[capability_id])
        missing = _missing_permissions(missing_by_capability, capability_id)
        available = supported and bool(tools) and all(tool in registered for tool in tools)
        available = available and not missing
        available_tools, degraded_tools, unavailable_tools = _capability_tool_availability(
            capability_id,
            tools,
            registered=registered,
            supported=supported,
            missing_by_capability=missing_by_capability,
        )
        child_availability[capability_id] = available
        child_available_tools[capability_id] = available_tools
        child_degraded_tools[capability_id] = degraded_tools
        child_unavailable_tools[capability_id] = unavailable_tools
        capability_models[capability_id] = DesktopExecutionCapabilitySnapshot(
            available=available,
            platform=platform_id,
            missing_permissions=missing,
            tools=tools,
            available_tools=available_tools,
            degraded_tools=degraded_tools,
            unavailable_tools=unavailable_tools,
            risk_default=DESKTOP_CAPABILITY_RISK_DEFAULTS[capability_id],
            diagnostic_route=DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES[capability_id],
        )

    root_missing = _missing_permissions(missing_by_capability, "desktop_execution")
    root_available_tools = _ordered_unique(
        tool
        for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS
        if capability_id != "desktop_execution"
        for tool in child_available_tools.get(capability_id, [])
    )
    root_degraded_tools = _ordered_unique(
        tool
        for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS
        if capability_id != "desktop_execution"
        for tool in child_degraded_tools.get(capability_id, [])
    )
    child_tools = {
        tool
        for capability_id in DESKTOP_EXECUTION_CAPABILITY_IDS
        if capability_id != "desktop_execution"
        for tool in DESKTOP_CAPABILITY_TOOLS[capability_id]
    }
    root_diagnostic_tools = _ordered_unique(
        tool
        for tool in DESKTOP_CAPABILITY_TOOLS["desktop_execution"]
        if tool not in child_tools and supported and tool in registered
    )
    root_unavailable_tools = _ordered_unique(
        tool
        for tool in DESKTOP_CAPABILITY_TOOLS["desktop_execution"]
        if tool not in root_available_tools
        and tool not in root_degraded_tools
        and tool not in root_diagnostic_tools
    )
    capability_models["desktop_execution"] = DesktopExecutionCapabilitySnapshot(
        available=supported and any(child_availability.values()) and not root_missing,
        platform=platform_id,
        missing_permissions=root_missing,
        tools=list(DESKTOP_CAPABILITY_TOOLS["desktop_execution"]),
        available_tools=[] if root_missing else _ordered_unique([*root_diagnostic_tools, *root_available_tools]),
        degraded_tools=[] if root_missing else root_degraded_tools,
        unavailable_tools=list(DESKTOP_CAPABILITY_TOOLS["desktop_execution"])
        if root_missing
        else root_unavailable_tools,
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


def _group_policy_token(policy_id: str | None) -> str:
    token = str(policy_id or "").strip().lower()
    token = token.replace("-", "_").replace(" ", "_")
    if token.startswith("policy_"):
        token = token.removeprefix("policy_")
    if token.endswith("_v1"):
        token = token.removesuffix("_v1")
    return token


def _missing_permissions(
    missing_permissions: Mapping[str, Iterable[str]],
    capability_id: str,
) -> list[str]:
    values = missing_permissions.get(capability_id, [])
    return [str(value or "").strip() for value in values if str(value or "").strip()]


def _capability_tool_availability(
    capability_id: str,
    tools: Iterable[str],
    *,
    registered: set[str],
    supported: bool,
    missing_by_capability: Mapping[str, Iterable[str]],
) -> tuple[list[str], list[str], list[str]]:
    available_tools: list[str] = []
    degraded_tools: list[str] = []
    unavailable_tools: list[str] = []
    for tool in tools:
        clean_tool = str(tool or "").strip()
        if not clean_tool:
            continue
        missing = _tool_missing_permissions(
            clean_tool,
            capability_id=capability_id,
            missing_by_capability=missing_by_capability,
        )
        if supported and clean_tool in registered and not missing:
            available_tools.append(clean_tool)
        elif supported and clean_tool in registered and _tool_degrades_with_permissions(
            clean_tool,
            missing,
            missing_by_capability=missing_by_capability,
        ):
            degraded_tools.append(clean_tool)
        else:
            unavailable_tools.append(clean_tool)
    return available_tools, degraded_tools, unavailable_tools


def _tool_missing_permissions(
    tool: str,
    *,
    capability_id: str,
    missing_by_capability: Mapping[str, Iterable[str]],
) -> list[str]:
    values = [*_missing_permissions(missing_by_capability, "desktop_execution")]
    capability_missing = _missing_permissions(missing_by_capability, capability_id)
    if tool == "app.open":
        values.extend(value for value in capability_missing if value == "open_command")
    elif tool == "app.focus":
        values.extend(value for value in capability_missing if value != "open_command")
    else:
        values.extend(capability_missing)
    if tool == "browser.screenshot":
        values.extend(_missing_permissions(missing_by_capability, "screen_capture"))
    if tool in {"browser.click", "browser.type_text"}:
        values.extend(_missing_permissions(missing_by_capability, "foreground_input"))
    if tool in {"media.apple_music_play", "media.apple_music_control"}:
        values.extend(
            value
            for value in _missing_permissions(missing_by_capability, "app_control")
            if value == "open_command"
        )
    return _ordered_unique(values)


def _tool_degrades_with_permissions(
    tool: str,
    missing: Iterable[str],
    *,
    missing_by_capability: Mapping[str, Iterable[str]],
) -> bool:
    missing_values = set(_ordered_unique(missing))
    fallback_permissions = set(DEGRADED_DESKTOP_TOOL_PERMISSION_FALLBACKS.get(tool, ()))
    if not missing_values or not fallback_permissions or not missing_values <= fallback_permissions:
        return False
    if tool == "browser.screenshot":
        return not _missing_permissions(missing_by_capability, "screen_capture")
    if tool in {"browser.click", "browser.type_text"}:
        return not _missing_permissions(missing_by_capability, "foreground_input")
    if tool in {"media.apple_music_play", "media.apple_music_control"}:
        return "open_command" not in _missing_permissions(missing_by_capability, "app_control")
    return True


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
