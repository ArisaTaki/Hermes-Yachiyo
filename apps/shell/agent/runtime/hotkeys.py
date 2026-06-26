"""Shared hotkey parsing for agent desktop entrypoints."""

from __future__ import annotations

import re
from typing import Any


MODIFIER_ALIASES: dict[str, str] = {
    "alt": "option",
    "cmd": "command",
    "command": "command",
    "control": "control",
    "ctrl": "control",
    "option": "option",
    "opt": "option",
    "shift": "shift",
    "⌃": "control",
    "⌘": "command",
    "⌥": "option",
    "⇧": "shift",
}

KEY_ALIASES: dict[str, str] = {
    "backspace": "backspace",
    "delete": "delete",
    "down": "down",
    "enter": "return",
    "esc": "escape",
    "escape": "escape",
    "left": "left",
    "return": "return",
    "right": "right",
    "space": "space",
    "tab": "tab",
    "up": "up",
    "上箭头": "up",
    "下箭头": "down",
    "删除": "delete",
    "右箭头": "right",
    "回车": "return",
    "左箭头": "left",
    "换行": "return",
    "确定": "return",
    "确认": "return",
    "空格": "space",
    "退出": "escape",
    "退格": "backspace",
}


def parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    parts = [
        part.strip()
        for part in re.split(r"(?:\s*\+\s*|\s*-\s*|\s+)", str(value or "").strip())
        if part.strip()
    ]
    if not parts:
        return None
    modifiers: list[str] = []
    key = ""
    for raw_part in parts:
        normalized = normalize_hotkey_token(raw_part)
        if not normalized:
            if str(raw_part or "").strip().lower() == "fn":
                continue
            return None
        if normalized in {"command", "control", "option", "shift"}:
            if normalized not in modifiers:
                modifiers.append(normalized)
            continue
        key = normalized
    if not key:
        return None
    return {"key": key, "modifiers": modifiers}


def normalize_hotkey_token(value: str) -> str:
    token = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    token = token.strip(" .，,。?？!！")
    token = re.sub(r"键$", "", token)
    modifier = MODIFIER_ALIASES.get(token)
    if modifier:
        return modifier
    key = KEY_ALIASES.get(token)
    if key:
        return key
    return token if re.fullmatch(r"[a-z0-9]", token) else ""
