"""Compatibility hotkey parsing hints for planner desktop input."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.hotkeys import normalize_hotkey_token, parse_hotkey_combo


def legacy_parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    return parse_hotkey_combo(value)


def legacy_normalize_hotkey_token(value: str) -> str:
    return normalize_hotkey_token(value)
