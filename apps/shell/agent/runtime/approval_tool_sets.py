"""Shared tool sets for direct-plan approval checks."""

from __future__ import annotations

from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    HIGH_RISK_DESKTOP_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
)

APPROVAL_PLAN_TOOLS = {
    *HIGH_RISK_AGENT_TOOLS,
    *HIGH_RISK_DESKTOP_TOOL_NAMES,
    *MEDIUM_RISK_BROWSER_TOOL_NAMES,
    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
}

SAFE_SHORTCUT_APPROVAL_TOOLS = {
    "desktop.safe_shortcut": "desktop.hotkey",
    "app.open_and_safe_shortcut": "app.open_and_hotkey",
    "app.focus_and_safe_shortcut": "app.focus_and_hotkey",
}
