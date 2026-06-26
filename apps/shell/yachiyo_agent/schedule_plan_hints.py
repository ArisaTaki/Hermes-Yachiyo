"""Shared schedule intent hints for runtime planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


_LOCAL_ISO_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"


def schedule_tool_preview(
    text: str,
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    allowed = _allowed_tool_set(allowed_tools)
    if _looks_like_calendar_event(text):
        payload = calendar_event_payload(text)
        if payload:
            return _first_allowed(("calendar.create_event",), allowed), payload
    payload = reminder_payload(text)
    if payload:
        return _first_allowed(("reminders.create",), allowed), payload
    return None, {}


def reminder_payload(text: str) -> dict[str, Any]:
    title = _reminder_title(text)
    if not title:
        return {}
    payload: dict[str, Any] = {"title": title}
    due_at = _local_iso_hint(text)
    if due_at:
        payload["due_at"] = due_at
    return payload


def calendar_event_payload(text: str) -> dict[str, Any]:
    start_at = _local_iso_hint(text)
    if not start_at:
        return {}
    title = _calendar_title(text, start_at)
    if not title:
        return {}
    return {
        "title": title,
        "start_at": start_at,
    }


def _looks_like_calendar_event(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in ("calendar", "event", "meeting", "日历", "日程", "会议"))


def _reminder_title(text: str) -> str:
    value = _clean(text)
    value = re.sub(rf"\b{_LOCAL_ISO_RE}\b", "", value).strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:创建|新建|添加|新增)?\s*(?:一个|一条|一项)?\s*(?:提醒事项|提醒)\s*[:：]?\s*(?P<title>.+)$",
        r"^(?:please\s+)?(?:create|add|make)?\s*(?:a\s+)?(?:new\s+)?reminder\s*(?:called|named|for|to)?\s*(?P<title_en>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        title = _strip_schedule_prefix(match.groupdict().get("title") or match.groupdict().get("title_en") or "")
        if title:
            return title
    return ""


def _calendar_title(text: str, start_at: str) -> str:
    value = _clean(text).replace(start_at, " ")
    patterns = (
        r"^(?:帮我|请|麻烦)?(?:创建|新建|添加|新增|安排)?\s*(?:一个|一条|一项)?\s*(?:日历事件|日程|会议)\s*[:：]?\s*(?P<title>.+)$",
        r"^(?:please\s+)?(?:create|add|schedule)?\s*(?:a\s+)?(?:calendar\s+)?(?:event|meeting)\s*(?:called|named|for)?\s*(?P<title_en>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        title = _strip_schedule_prefix(match.groupdict().get("title") or match.groupdict().get("title_en") or "")
        if title:
            return title
    return ""


def _local_iso_hint(text: str) -> str:
    match = re.search(rf"\b({_LOCAL_ISO_RE})\b", str(text or ""))
    return match.group(1) if match else ""


def _strip_schedule_prefix(value: str) -> str:
    title = _clean(value)
    title = re.sub(r"^(?:在|于|到时候|的时候|时|要|去|做|进行|参加|记得|提醒我)\s*", "", title)
    title = re.sub(r"^(?:to|for|about|that|please)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*(?:的时候|时|在|于)$", "", title).strip()
    return title.strip(" .，,。")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _first_allowed(tools: Iterable[str], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None


def _allowed_tool_set(allowed_tools: Iterable[str] | None) -> set[str] | None:
    if allowed_tools is None:
        return None
    return {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
