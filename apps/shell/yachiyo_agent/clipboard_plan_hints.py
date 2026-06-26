"""Clipboard intent hints for the Yachiyo runtime planner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def clipboard_operation_hint(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    write_text = _clipboard_write_text(text)
    if write_text:
        return {"action": "write", "text": write_text}
    if _selected_text_read_request(text):
        return {"action": "copy_selection_read"}
    if _clipboard_read_request(text):
        return {"action": "read"}
    return {}


def clipboard_tool_preview(
    inputs: Mapping[str, Any],
    allowed: set[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    action = str(inputs.get("action") or "").strip()
    if action == "write":
        text = str(inputs.get("text") or "").strip()
        return _first_allowed(("clipboard.write",), allowed), {"text": text} if text else {}
    if action in {"read", "copy_selection_read"}:
        return _first_allowed(("clipboard.read",), allowed), {}
    return None, {}


def _clipboard_write_text(text: str) -> str:
    patterns = (
        r"(?:把|将)?\s*(?:这段话|这段文字|这段文本|以下内容|下面内容|内容)?\s*"
        r"(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*(?P<text>.+)$",
        r"(?:复制|拷贝)(?:一下|下)?\s*(?:以下|下面)?(?:内容|这段话|这段文字|这段文本)?\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:写入|放入|放进|保存到)\s*(?:系统)?(?:剪贴板|粘贴板|clipboard)\s+(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>.+?)\s*(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板|clipboard)",
        r"\b(?:copy|write|put)\s+(?P<text>.+?)\s+(?:to|into)\s+(?:the\s+)?"
        r"(?:system\s+)?clipboard\b",
        r"\b(?:copy|write)\s+(?:to\s+)?(?:the\s+)?(?:system\s+)?clipboard\s*[:：]\s*"
        r"(?P<text>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        cleaned = _normalize_clipboard_text(match.group("text"))
        if cleaned:
            return cleaned
    return ""


def _clipboard_read_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:读取|读一下|读下|读一读|查看|看看|看一下|看下|显示|告诉我).{0,8}"
            r"(?:系统)?(?:剪贴板|粘贴板|clipboard).{0,8}(?:内容|里|里面|是什么|有啥|有什么|给我)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:系统)?(?:剪贴板|粘贴板|clipboard).{0,8}"
            r"(?:内容|里|里面|是什么|有啥|有什么|读取|读一下|读下|读一读|读给我|查看|看看|看一下|看下|显示)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|show|display|check|tell\s+me)\s+(?:the\s+)?"
            r"(?:(?:system|my)\s+)?clipboard(?:\s+contents?)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:what(?:'s| is)|what)\s+(?:is\s+)?(?:on|in)\s+(?:the\s+|my\s+)?"
            r"(?:system\s+)?clipboard\b",
            lowered,
        )
    )


def _selected_text_read_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:读|读取|查看|看看|看一下|看下|显示|告诉我).{0,12}"
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区)",
            text,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区).{0,12}"
            r"(?:是什么|是啥|有啥|有什么|读|读取|查看|看看|看一下|看下|显示|告诉我)",
            text,
        )
        or re.search(
            r"(?:我|当前|现在)?(?:选中|选取|高亮|选择)(?:了|的)?"
            r"(?:内容|文字|文本|这段|这部分|选区)?\s*(?:是什么|是啥|有啥|有什么)",
            text,
        )
        or re.search(
            r"\b(?:read|show|display|check|tell\s+me)\s+(?:the\s+)?"
            r"(?:selected|highlighted)\s+(?:text|content|selection)\b",
            lowered,
        )
        or re.search(
            r"\bwhat(?:'s| is)\s+(?:the\s+)?"
            r"(?:selected|highlighted)\s+(?:text|content|selection)\b",
            lowered,
        )
    )


def _normalize_clipboard_text(value: str) -> str:
    return str(value or "").strip().strip("「」\"'“”‘’")


def _first_allowed(tools: tuple[str, ...], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None
