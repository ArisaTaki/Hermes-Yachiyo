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
        r"^(?:帮我|请|麻烦)?(?:把|将)\s*(?:这段文字|这段文本|这段内容|这个想法|这个内容|以下内容|这句话)?\s*"
        r"(?:记到|记录到|保存到|写到|添加到)\s*(?:Apple\s*Notes|Notes|备忘录|笔记)"
        r"\s*[:：]\s*(?P<body_to_app>.+)$",
        r"^(?:帮我|请|麻烦)?(?:把|将)\s*(?P<body_before_app>.+?)\s*"
        r"(?:记到|记录到|保存到|写到|添加到)\s*(?:Apple\s*Notes|Notes|备忘录|笔记)$",
        r"^(?:在|用|通过)\s*(?:Apple\s*Notes|Notes|备忘录|笔记)\s*(?:里|中|上|内)?\s*"
        r"(?:记录一下|记一下|新建|创建|添加|新增|写|记录|保存|记下)\s*(?:一条|一个)?\s*"
        r"(?:备忘录|笔记)?\s*[:：]?\s*(?P<body_app>.+)$",
        r"^(?:in|inside|within|using|with)\s+(?:apple\s+notes|notes|note\s+app)\s+"
        r"(?:add|make|create|write|record)\s+(?:a\s+)?(?:new\s+)?note\s*"
        r"[:：]?\s*(?P<body_app_en>.+)$",
        r"^(?:please\s+)?(?:add|make|create|write|record)\s+(?:a\s+)?(?:new\s+)?note\s+"
        r"(?:in|inside|within|using|with)\s+(?:apple\s+notes|notes|note\s+app)"
        r"\s*[:：]?\s*(?P<body_in_app_en>.+)$",
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
        groups = match.groupdict()
        body = _normalize_body(
            groups.get("body_app")
            or groups.get("body_to_app")
            or groups.get("body_before_app")
            or groups.get("body_app_en")
            or groups.get("body_in_app_en")
            or groups.get("body")
            or groups.get("body_en")
            or ""
        )
        if body and not context_source_hint(body) and not _looks_like_placeholder_note_body(body):
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
            "selected link",
            "selected url",
            "highlighted link",
            "highlighted url",
            "选中文字",
            "选中文本",
            "选中链接",
            "选中网址",
            "选中的文字",
            "选中的文本",
            "选中的内容",
            "选中的数据",
            "选中的表格",
            "选中的链接",
            "选中的网址",
            "选中内容",
            "选中数据",
            "选中表格",
            "当前选中的数据",
            "当前选中的表格",
            "选取文字",
            "选取文本",
            "选取内容",
            "选取数据",
            "选取表格",
            "选取链接",
            "选取网址",
            "高亮文字",
            "高亮文本",
            "高亮内容",
            "高亮链接",
            "高亮网址",
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
            "current window table",
            "visible table",
            "this table",
            "当前网页内容",
            "当前页面内容",
            "当前网页正文",
            "当前页面正文",
            "当前网页里的表格",
            "当前网页的表格",
            "当前页面里的表格",
            "当前页面的表格",
            "当前页里的表格",
            "当前页的表格",
            "当前窗口内容",
            "当前窗口表格",
            "当前窗口里的表格",
            "当前窗口的表格",
            "当前应用内容",
            "当前界面表格",
            "这个表格",
            "这张表格",
            "这份表格",
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
    body = _clean(value).strip("「」\"'“”‘’ .，,。:：")
    body = re.sub(r"^(?:to|for|about|that)\s+", "", body, flags=re.IGNORECASE)
    return body.strip()


def _looks_like_placeholder_note_body(value: str) -> bool:
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return normalized in {
        "这段文字",
        "这段文本",
        "这段内容",
        "这个内容",
        "这个想法",
        "以下内容",
        "这句话",
        "thetext",
        "thistext",
        "thiscontent",
        "selectedtext",
        "selection",
    }


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
