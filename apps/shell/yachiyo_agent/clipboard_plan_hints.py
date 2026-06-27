"""Clipboard intent hints for the Yachiyo runtime planner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def clipboard_operation_hint(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    if _clipboard_context_source_request(text):
        return {}
    write_text = _clipboard_write_text(text)
    if write_text:
        return {"action": "write", "text": write_text}
    if _clipboard_paste_to_foreground_request(text):
        return {}
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


def _clipboard_paste_to_foreground_request(text: str) -> bool:
    return bool(
        re.search(
            r"(?:剪贴板|粘贴板|clipboard).{0,16}(?:粘贴|paste).{0,16}"
            r"(?:当前|前台|输入框|文本框|输入栏|current|foreground|input|field)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:粘贴|paste).{0,16}(?:剪贴板|粘贴板|clipboard).{0,16}"
            r"(?:当前|前台|输入框|文本框|输入栏|current|foreground|input|field)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_write_text(text: str) -> str:
    patterns = (
        r"(?:设置|设定|设为|设成)\s*(?:系统)?(?:剪贴板|粘贴板)\s*(?:为|成|=|：|:)\s*(?P<text>.+)$",
        r"(?:系统)?(?:剪贴板|粘贴板)\s*(?:写入|设置为|设为|设成|=|：|:)\s*(?P<text>.+)$",
        r"(?:把|将)?\s*(?:这段话|这段文字|这段文本|以下内容|下面内容|内容)?\s*"
        r"(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*(?P<text>.+)$",
        r"(?:复制|拷贝)(?:一下|下)?\s*(?:以下|下面)?(?:内容|这段话|这段文字|这段文本)?\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:写入|放入|放进|保存到)\s*(?:系统)?(?:剪贴板|粘贴板|clipboard)\s+(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>.+?)\s*(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板|clipboard)",
        r"\bset\s+(?:the\s+)?(?:system\s+)?clipboard\s+(?:to|as)\s+(?P<text>.+)$",
        r"\b(?:the\s+)?(?:system\s+)?clipboard\s*(?:=|:|to)\s*(?P<text>.+)$",
        r"\b(?:copy|write|put)\s+(?P<text>.+?)\s+(?:to|into)\s+(?:the\s+)?"
        r"(?:system\s+)?clipboard\b",
        r"\b(?:copy|write)\s+(?:to\s+)?(?:the\s+)?(?:system\s+)?clipboard\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>[^。！？!?，,\n]+?)\s*(?:复制|拷贝)(?:一下|下)?\s*(?:吧|给我)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        cleaned = _normalize_clipboard_text(match.group("text"))
        if cleaned and not _looks_like_dynamic_clipboard_source(cleaned):
            return cleaned
    return ""


def _clipboard_context_source_request(text: str) -> bool:
    lowered = text.lower()
    has_clipboard_source = any(term in lowered for term in ("clipboard", "剪贴板", "粘贴板"))
    has_external_target = any(
        term in lowered
        for term in (
            "note",
            "notes",
            "reminder",
            "reminders",
            "calendar",
            "event",
            "search",
            "find",
            "open",
            "paste",
            "insert",
            "put",
            "type",
            "enter",
            "send",
            "message",
            "mail",
            "browser",
            "web",
            "page",
            "url",
            "link",
            "备忘录",
            "笔记",
            "提醒",
            "提醒事项",
            "日历",
            "日程",
            "事件",
            "搜索",
            "查找",
            "检索",
            "打开",
            "粘贴",
            "贴到",
            "输入",
            "输入到",
            "填到",
            "填入",
            "填写",
            "发送",
            "发给",
            "发到",
            "发消息",
            "消息",
            "邮件",
            "访问",
            "浏览器",
            "网页",
            "页面",
            "网址",
            "链接",
        )
    )
    return has_clipboard_source and has_external_target


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
            r"\bcopy\s+(?:the\s+)?(?:selected|highlighted)\s+(?:text|content|selection)"
            r".{0,40}\bread\s+(?:the\s+)?(?:system\s+)?clipboard\b",
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


def _looks_like_dynamic_clipboard_source(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return bool(
        re.search(
            r"(?:当前|这个|该|选中|选取|高亮|选择).{0,8}"
            r"(?:网页|页面|标签页|窗口|屏幕|内容|文字|文本|选区|链接|网址)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:网页|页面|标签页|窗口|屏幕|链接|网址).{0,8}"
            r"(?:内容|链接|网址|地址|当前)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:current|active|selected|highlighted)\s+"
            r"(?:page|tab|window|screen|content|text|selection|link|url)\b",
            text,
        )
        or re.search(r"\bclipboard\s+contents?\b", text)
    )


def _first_allowed(tools: tuple[str, ...], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None
