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
    "foreground_activation",
    "foreground_input",
    "browser_control",
)

LOW_RISK_DESKTOP_TOOLS = frozenset(
    {
        "screen.capture",
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.list_apps",
        "desktop.windows",
        "desktop.ui_elements",
        "app.status",
        "app.open",
        "app.focus",
        "app.focus_window",
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.show",
        "app.hide",
        "app.minimize",
        "desktop.reveal_path",
        "desktop.open_path",
        "media.apple_music_play",
        "media.apple_music_status",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "media.music_app_control",
        "media.system_control",
        "system.settings_open",
        "system.volume",
        "system.brightness",
        "system.display_sleep",
        "system.screen_saver_start",
        "clipboard.write",
        "clipboard.read",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.hide_app",
        "desktop.show_all_apps",
        "desktop.minimize_window",
    }
)
MEDIUM_RISK_DESKTOP_TOOLS = frozenset(
    {
        "app.quit",
        "desktop.quit_app",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "desktop.close_window",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.hotkey",
        "desktop.type_text",
        "desktop.click",
    }
)
HIGH_RISK_DESKTOP_TOOLS = frozenset({"desktop.submit_foreground"})
LOW_RISK_BROWSER_TOOLS = frozenset(
    {
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
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
        "discover_apps",
        "read_windows",
        "read_ui_elements",
        "read_app_status",
        "open_app",
        "focus_app",
        "focus_app_window",
        "show_app",
        "hide_app",
        "minimize_app",
        "reveal_path",
        "open_path",
        "play_or_pause_media",
        "control_system_volume",
        "control_system_brightness",
        "control_display_sleep",
        "control_screen_saver",
        "write_clipboard",
        "create_note",
        "create_reminder",
        "create_calendar_event",
        "foreground_safe_shortcut",
        "foreground_safe_key",
        "foreground_safe_type_text",
        "foreground_safe_click",
        "foreground_safe_scroll",
        "foreground_hide_app",
        "foreground_minimize_window",
    }
)
MEDIUM_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "foreground_click",
        "foreground_click_ui_element",
        "foreground_type_into_ui_element",
        "foreground_close_window",
        "foreground_type_text",
        "foreground_hotkey",
        "quit_app",
    }
)
HIGH_RISK_DESKTOP_ACTIONS = frozenset(
    {
        "foreground_submit",
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
    "discover_apps",
    "read_windows",
    "read_ui_elements",
    "read_app_status",
    "open_app",
    "focus_app",
    "focus_app_window",
    "show_app",
    "hide_app",
    "minimize_app",
    "quit_app",
    "reveal_path",
    "open_path",
    "play_or_pause_media",
    "control_system_volume",
    "control_system_brightness",
    "control_display_sleep",
    "control_screen_saver",
    "write_clipboard",
    "create_note",
    "create_reminder",
    "create_calendar_event",
    "foreground_safe_shortcut",
    "foreground_safe_key",
    "foreground_safe_type_text",
    "foreground_safe_click",
    "foreground_safe_scroll",
    "foreground_hide_app",
    "foreground_minimize_window",
    "foreground_click_ui_element",
    "foreground_type_into_ui_element",
    "foreground_click",
    "foreground_close_window",
    "foreground_type_text",
    "foreground_hotkey",
    "foreground_submit",
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
    "discover_apps": ("desktop.list_apps",),
    "read_windows": ("desktop.windows",),
    "read_ui_elements": ("desktop.ui_elements",),
    "read_app_status": ("app.status",),
    "open_app": ("app.open",),
    "focus_app": ("app.focus",),
    "focus_app_window": ("app.focus_window",),
    "show_app": ("app.show",),
    "hide_app": ("app.hide",),
    "minimize_app": ("app.minimize",),
    "quit_app": ("app.quit", "desktop.quit_app"),
    "reveal_path": ("desktop.reveal_path",),
    "open_path": ("desktop.open_path",),
    "play_or_pause_media": (
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "media.music_app_control",
        "media.system_control",
    ),
    "system_settings": ("system.settings_open",),
    "control_system_volume": ("system.volume",),
    "control_system_brightness": ("system.brightness",),
    "control_display_sleep": ("system.display_sleep",),
    "control_screen_saver": ("system.screen_saver_start",),
    "write_clipboard": ("clipboard.write",),
    "read_clipboard": ("clipboard.read",),
    "create_note": ("notes.create",),
    "create_reminder": ("reminders.create",),
    "create_calendar_event": ("calendar.create_event",),
    "foreground_safe_shortcut": ("desktop.safe_shortcut",),
    "foreground_safe_key": ("desktop.safe_key",),
    "foreground_safe_type_text": ("desktop.safe_type_text",),
    "foreground_safe_click": ("desktop.safe_click",),
    "foreground_safe_scroll": ("desktop.safe_scroll",),
    "foreground_hide_app": ("desktop.hide_app",),
    "foreground_show_all_apps": ("desktop.show_all_apps",),
    "foreground_minimize_window": ("desktop.minimize_window",),
    "foreground_click_ui_element": (
        "desktop.click_ui_element",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
    ),
    "foreground_type_into_ui_element": (
        "desktop.type_into_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    ),
    "foreground_click": ("desktop.click", "browser.click"),
    "foreground_close_window": ("desktop.close_window",),
    "foreground_type_text": ("desktop.type_text", "browser.type_text"),
    "foreground_hotkey": ("desktop.hotkey",),
    "foreground_submit": ("desktop.submit_foreground",),
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
    "discover_apps": "Discover installed apps",
    "read_ui_elements": "Read UI elements",
    "open_app": "Open app",
    "focus_app": "Focus app",
    "focus_app_window": "Focus app window",
    "show_app": "Show app",
    "hide_app": "Hide app",
    "minimize_app": "Minimize app",
    "quit_app": "Quit app",
    "open_path": "Open local path",
    "play_or_pause_media": "Play or pause media",
    "control_system_volume": "Control system volume",
    "control_system_brightness": "Control screen brightness",
    "control_display_sleep": "Sleep display",
    "control_screen_saver": "Start screen saver",
    "write_clipboard": "Write clipboard",
    "read_clipboard": "Read clipboard",
    "create_note": "Create note",
    "create_reminder": "Create reminder",
    "create_calendar_event": "Create calendar event",
    "foreground_safe_shortcut": "Run safe foreground shortcut",
    "foreground_safe_key": "Press safe foreground key",
    "foreground_safe_type_text": "Type explicit foreground text",
    "foreground_safe_click": "Click explicit foreground coordinate",
    "foreground_safe_scroll": "Scroll foreground UI",
    "foreground_hide_app": "Hide foreground app",
    "foreground_minimize_window": "Minimize foreground window",
    "foreground_click_ui_element": "Click named foreground control",
    "foreground_type_into_ui_element": "Type into named foreground input",
    "foreground_click": "Click foreground UI",
    "foreground_close_window": "Close foreground window",
    "foreground_type_text": "Type into foreground UI",
    "foreground_hotkey": "Send foreground hotkey",
    "foreground_submit": "Send or submit foreground content",
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
    "discover_apps": "Discover installed macOS application bundles before opening an app.",
    "read_ui_elements": "Read visible controls from the foreground window for later desktop actions.",
    "open_app": "Launch a local desktop application.",
    "focus_app": "Bring a local desktop application to the foreground.",
    "focus_app_window": "Bring a matching window of a local desktop application to the foreground.",
    "show_app": "Show, unhide, restore minimized windows, and activate a local desktop application.",
    "hide_app": "Hide a running local desktop application without quitting it.",
    "minimize_app": "Minimize windows for a running local desktop application without quitting it.",
    "quit_app": "Quit a local desktop application after approval.",
    "open_path": "Open a safe local file or folder with the system default app.",
    "play_or_pause_media": "Control local media playback such as Apple Music or a named music app.",
    "system_settings": "Open macOS System Settings panes or privacy permission pages.",
    "control_system_volume": "Read or adjust local system output volume.",
    "control_system_brightness": "Adjust local display brightness up or down.",
    "control_display_sleep": "Put the local display to sleep without shutting down or sleeping the whole Mac.",
    "control_screen_saver": "Start the local screen saver without changing screen saver settings.",
    "write_clipboard": "Write explicit user-provided text to the system clipboard.",
    "read_clipboard": "Read a bounded preview of the system clipboard when explicitly requested.",
    "create_note": "Create a local Notes note from explicit user-provided content.",
    "create_reminder": "Create a local Reminders item from an explicit user request.",
    "create_calendar_event": "Create a local Calendar event from an explicit user request.",
    "foreground_safe_shortcut": "Run a whitelisted foreground shortcut such as copy, paste, copy current page link, select all, undo, redo, find, focus address bar, new tab, new private window, bookmark, history, DevTools, page zoom, or refresh.",
    "foreground_safe_key": "Press a whitelisted foreground navigation key such as Escape, Tab, arrows, Home, End, Page Up, or Page Down.",
    "foreground_safe_type_text": "Type text explicitly provided by the user into the current foreground target.",
    "foreground_safe_click": "Single-click a screen coordinate explicitly provided by the user.",
    "foreground_safe_scroll": "Scroll the current foreground app up or down by explicit pages.",
    "foreground_hide_app": "Hide the current foreground app.",
    "foreground_minimize_window": "Minimize the current foreground window.",
    "foreground_click_ui_element": "Click a visible foreground control matched by Accessibility label after approval.",
    "foreground_type_into_ui_element": "Focus a visible foreground text input matched by Accessibility label and type user-provided text after approval.",
    "foreground_click": "Click in the foreground application or browser page.",
    "foreground_close_window": "Close the current foreground window after approval.",
    "foreground_type_text": "Enter text into the current foreground target.",
    "foreground_hotkey": "Send a keyboard shortcut to the foreground target.",
    "foreground_submit": "Send, submit, or confirm the current foreground input after approval.",
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
    **{tool: "high" for tool in HIGH_RISK_DESKTOP_TOOLS},
    **{tool: "low" for tool in LOW_RISK_BROWSER_TOOLS},
    **{tool: "medium" for tool in MEDIUM_RISK_BROWSER_TOOLS},
}

DESKTOP_CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "desktop_execution": (
        "screen.capture",
        "desktop.permissions",
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.list_apps",
        "desktop.windows",
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "app.status",
        "app.open",
        "app.focus",
        "app.focus_window",
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
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "desktop.quit_app",
        "desktop.reveal_path",
        "desktop.open_path",
        "media.apple_music_play",
        "media.apple_music_status",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "media.music_app_control",
        "media.system_control",
        "system.settings_open",
        "system.volume",
        "system.brightness",
        "system.display_sleep",
        "system.screen_saver_start",
        "clipboard.write",
        "clipboard.read",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.hide_app",
        "desktop.show_all_apps",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type_text",
        "desktop.click",
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.current_page",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    ),
    "screen_capture": ("screen.capture",),
    "active_window": (
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "desktop.ui_elements",
    ),
    "app_control": (
        "app.status",
        "app.open",
        "system.settings_open",
        "app.focus",
        "app.focus_window",
        "app.show",
        "app.hide",
        "app.minimize",
        "app.quit",
        "desktop.quit_app",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
    ),
    "media_control": (
        "media.apple_music_play",
        "media.apple_music_status",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "media.music_app_control",
        "media.system_control",
    ),
    "foreground_input": (
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
        "desktop.hide_app",
        "desktop.show_all_apps",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type_text",
        "desktop.click",
    ),
    "foreground_activation": (
        "app.focus",
        "app.focus_window",
        "app.show",
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
        "media.music_app_open_and_play",
        "media.music_app_control",
    ),
    "browser_control": (
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
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
    "foreground_activation": "low",
    "foreground_input": "medium",
    "browser_control": "medium",
}

DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES: dict[str, str | None] = {
    "desktop_execution": "/yachiyo/readiness",
    "screen_capture": "/screen/current",
    "active_window": "/system/active-window",
    "app_control": "/ui/native-agent/diagnostics/cache",
    "media_control": "/ui/native-agent/diagnostics/cache",
    "foreground_activation": "/ui/native-agent/diagnostics/cache",
    "foreground_input": "/ui/native-agent/diagnostics/cache",
    "browser_control": "/ui/native-agent/diagnostics/cache",
}

DEGRADED_DESKTOP_TOOL_PERMISSION_FALLBACKS: dict[str, tuple[str, ...]] = {
    "browser.open_url": ("chrome_cdp",),
    "browser.open_url_and_extract_text": ("chrome_cdp",),
    "browser.open_url_and_screenshot": ("chrome_cdp",),
    "browser.screenshot": ("chrome_cdp",),
    "browser.click": ("chrome_cdp",),
    "browser.type_text": ("chrome_cdp",),
    "media.apple_music_play": ("automation",),
    "media.apple_music_open_and_play": ("automation",),
    "media.apple_music_control": ("automation",),
    "media.music_app_open_and_play": ("accessibility",),
    "media.music_app_control": ("accessibility",),
    "media.system_control": ("accessibility",),
    "system.brightness": ("accessibility",),
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
    "foreground_activation": DESKTOP_CAPABILITY_TOOLS["foreground_activation"],
    "focus": DESKTOP_CAPABILITY_TOOLS["foreground_activation"],
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
        if tool in MEDIUM_RISK_DESKTOP_TOOLS
        or tool in HIGH_RISK_DESKTOP_TOOLS
        or tool in MEDIUM_RISK_BROWSER_TOOLS
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
    app_control_missing = _missing_permissions(missing_by_capability, "app_control")
    foreground_activation_missing = _missing_permissions(
        missing_by_capability,
        "foreground_activation",
    )
    foreground_input_missing = _missing_permissions(missing_by_capability, "foreground_input")
    if tool == "app.open":
        values.extend(value for value in capability_missing if value == "open_command")
    elif tool == "system.settings_open":
        values.extend(value for value in capability_missing if value == "open_command")
    elif tool == "app.focus":
        values.extend(value for value in app_control_missing if value != "open_command")
        values.extend(foreground_activation_missing)
    elif tool in {"app.focus_window", "app.show"}:
        values.extend(value for value in app_control_missing if value != "open_command")
        values.extend(foreground_activation_missing)
        values.extend(foreground_input_missing)
    elif tool in {
        "app.open_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.open_and_hotkey",
        "app.open_and_safe_scroll",
        "app.open_and_safe_click",
        "app.open_and_click_ui_element",
        "app.open_and_type_into_ui_element",
    }:
        values.extend(foreground_input_missing)
        values.extend(foreground_activation_missing)
        values.extend(value for value in app_control_missing if value == "open_command")
    elif tool in {
        "app.focus_and_safe_type_text",
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_key",
        "app.focus_and_hotkey",
        "app.focus_and_safe_scroll",
        "app.focus_and_safe_click",
        "app.focus_and_click_ui_element",
        "app.focus_and_type_into_ui_element",
    }:
        values.extend(foreground_input_missing)
        values.extend(foreground_activation_missing)
        values.extend(value for value in app_control_missing if value != "open_command")
    elif tool in {"app.hide", "app.minimize"}:
        values.extend(foreground_input_missing)
    elif tool in {"media.music_app_open_and_play", "media.music_app_control"}:
        values.extend(foreground_input_missing)
        values.extend(foreground_activation_missing)
        if tool == "media.music_app_open_and_play":
            values.extend(value for value in app_control_missing if value == "open_command")
    elif tool == "media.system_control":
        values.extend(foreground_input_missing)
    else:
        values.extend(capability_missing)
    if tool in {"browser.screenshot", "browser.open_url_and_screenshot"}:
        values.extend(_missing_permissions(missing_by_capability, "screen_capture"))
    if tool in {"browser.click", "browser.type_text"}:
        values.extend(_missing_permissions(missing_by_capability, "foreground_input"))
    if tool in {
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    }:
        values.extend(
            value
            for value in _missing_permissions(missing_by_capability, "app_control")
            if value == "open_command"
        )
    return _ordered_unique(values)


def desktop_tool_missing_permissions(
    tool: str,
    *,
    capability_id: str,
    missing_permissions: Mapping[str, Iterable[str]],
) -> list[str]:
    return _tool_missing_permissions(
        tool,
        capability_id=capability_id,
        missing_by_capability=missing_permissions,
    )


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
    if tool in {"browser.screenshot", "browser.open_url_and_screenshot"}:
        return not _missing_permissions(missing_by_capability, "screen_capture")
    if tool in {"browser.click", "browser.type_text"}:
        return not _missing_permissions(missing_by_capability, "foreground_input")
    if tool in {
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    }:
        return "open_command" not in _missing_permissions(missing_by_capability, "app_control")
    return True


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
