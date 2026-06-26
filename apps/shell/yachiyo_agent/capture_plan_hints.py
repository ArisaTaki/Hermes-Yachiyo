"""Information capture intent hints for runtime planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


def capture_note_hint(prompt: str) -> dict[str, Any]:
    text = _clean(prompt)
    if not text or not _looks_like_note_request(text):
        return {}
    source = context_source_hint(text)
    if source:
        return {"action": "create_note_from_context", "source": source}
    body = note_body(text)
    if body:
        return {"action": "create_note", "body": body}
    if _looks_like_empty_note_request(text):
        return {"action": "create_note", "body": ""}
    return {}


def capture_tool_preview(
    inputs: Mapping[str, Any],
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    if str(inputs.get("action") or "").strip() != "create_note":
        return None, {}
    body = str(inputs.get("body") or "").strip()
    if not body:
        return None, {}
    return _first_allowed(("notes.create",), allowed_tools), {"body": body}


def note_body(text: str) -> str:
    value = _clean(text)
    patterns = (
        r"^(?:帮我|请|麻烦)?(?:新建|创建|添加|新增|写|记录|保存)?\s*(?:一个|一条|一份)?\s*"
        r"(?:备忘录|笔记)\s*(?:写|写下|记录|记一下|记下|内容(?:是|为)|正文(?:是|为))?\s*[:：]?\s*(?P<body>.+)$",
        r"^(?:帮我|请|麻烦)?(?:记一下|记录一下|记下)\s*(?P<body>.+)$",
        r"^(?:在)?(?:备忘录|笔记)(?:里|中)?\s*(?:新建|创建|添加|写|记录|记下)\s*"
        r"(?:一条|一个)?\s*(?:备忘录|笔记)?\s*[:：]?\s*(?P<body>.+)$",
        r"^(?:please\s+)?(?:add|make|create|write)\s+(?:a\s+)?(?:new\s+)?note\s*"
        r"(?:to|called|named|saying|with|about)?\s*(?P<body_en>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        body = _normalize_body(match.groupdict().get("body") or match.groupdict().get("body_en") or "")
        if body and not context_source_hint(body):
            return body
    return ""


def context_source_hint(text: str) -> str:
    lowered = text.lower()
    if _contains_any(lowered, ("clipboard", "剪贴板", "粘贴板")):
        return "clipboard"
    if _contains_any(
        lowered,
        (
            "selected text",
            "highlighted text",
            "selection",
            "选中文字",
            "选中文本",
            "选中的文字",
            "选中的文本",
            "选中的内容",
            "选中内容",
            "选取文字",
            "选取文本",
            "选取内容",
            "高亮文字",
            "高亮文本",
            "高亮内容",
        ),
    ):
        return "selection"
    if _contains_any(lowered, ("current page link", "current url", "当前网页链接", "当前页面链接", "当前链接")):
        return "current_page_link"
    if _contains_any(
        lowered,
        (
            "current page content",
            "current page text",
            "current window content",
            "当前网页内容",
            "当前页面内容",
            "当前网页正文",
            "当前页面正文",
            "当前窗口内容",
            "当前应用内容",
        ),
    ):
        return "current_page_content"
    if _contains_any(lowered, ("current screen", "visible text", "当前屏幕", "当前界面", "屏幕内容")):
        return "visible_text"
    return ""


def _looks_like_note_request(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(lowered, ("note", "notes", "备忘录", "笔记", "记一下", "记录一下", "记下"))


def _looks_like_empty_note_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.fullmatch(r"(?:帮我|请|麻烦)?(?:新建|创建|打开|添加)?\s*(?:一个|一条)?\s*(?:备忘录|笔记)", text)
        or re.fullmatch(r"(?:create|make|add|open)\s+(?:a\s+)?(?:new\s+)?note", lowered)
    )


def _normalize_body(value: str) -> str:
    body = _clean(value).strip("「」\"'“”‘’ .，,。")
    body = re.sub(r"^(?:to|for|about|that)\s+", "", body, flags=re.IGNORECASE)
    return body.strip()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _first_allowed(tools: Iterable[str], allowed_tools: Iterable[str] | None) -> str | None:
    allowed = None
    if allowed_tools is not None:
        allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None
