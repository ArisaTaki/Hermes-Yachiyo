"""Shared schedule intent hints for runtime planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
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
    if _dynamic_schedule_source_request(text):
        return {}
    body = _reminder_body(text)
    if not body:
        return {}
    iso_due_at = _local_iso_hint(text)
    if iso_due_at:
        title = _strip_schedule_prefix(re.sub(rf"\b{_LOCAL_ISO_RE}\b", "", body).strip())
        return {"title": title, "due_at": iso_due_at} if title else {}
    scheduled = _extract_schedule_datetime_and_title(body)
    if scheduled:
        due_at, title = scheduled
        return {"title": title, "due_at": _local_datetime_text(due_at)} if title else {}
    date_only = _extract_reminder_date_only_datetime_and_title(body)
    if date_only:
        due_at, title = date_only
        return {"title": title, "due_at": _local_datetime_text(due_at)} if title else {}
    title = _strip_schedule_prefix(body)
    if not title:
        return {}
    return {"title": title}


def calendar_event_payload(text: str) -> dict[str, Any]:
    if _dynamic_schedule_source_request(text):
        return {}
    start_at = _local_iso_hint(text)
    if start_at:
        title = _calendar_title(text, start_at)
        if not title:
            return {}
        return {
            "title": title,
            "start_at": start_at,
        }
    body = _calendar_body(text)
    if not body:
        return {}
    scheduled = _extract_schedule_datetime_and_title(body)
    if not scheduled:
        return {}
    start, title = scheduled
    if not title:
        return {}
    end = start + timedelta(hours=1)
    return {
        "title": title,
        "start_at": _local_datetime_text(start),
        "end_at": _local_datetime_text(end),
    }


def _looks_like_calendar_event(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in ("calendar", "event", "meeting", "日历", "日程", "会议"))


def _dynamic_schedule_source_request(text: str) -> bool:
    lowered = str(text or "").lower()
    has_dynamic_source = any(
        term in lowered
        for term in (
            "selected text",
            "highlighted text",
            "selection",
            "clipboard",
            "current page",
            "current window",
            "current url",
            "选中",
            "选取",
            "高亮",
            "剪贴板",
            "粘贴板",
            "当前网页",
            "当前页面",
            "当前窗口",
            "当前链接",
        )
    )
    has_schedule_target = any(
        term in lowered
        for term in (
            "reminder",
            "reminders",
            "calendar",
            "event",
            "提醒",
            "提醒事项",
            "日历",
            "日程",
            "事件",
        )
    )
    return has_dynamic_source and has_schedule_target


def _reminder_body(text: str) -> str:
    value = _clean(text)
    value = re.sub(rf"\b{_LOCAL_ISO_RE}\b", "", value).strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<body_time_first>[^。！？!?]+?)\s*提醒我\s*(?P<body_time_after>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:创建|新建|添加|新增)?\s*(?:一个|一条|一项)?\s*(?:提醒事项|提醒)\s*[:：]?\s*(?P<title>.+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:设|设置|定|订)\s*(?:个|一个|一条|一项|新的?)?\s*"
        r"(?P<body_set>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒)$",
        r"^(?:please\s+)?(?:create|add|make)?\s*(?:a\s+)?(?:new\s+)?reminder\s*(?:called|named|for|to)?\s*(?P<title_en>.+)$",
        r"^(?:please\s+)?(?:set)\s+(?:a\s+)?(?:new\s+)?reminder\s*(?:called|named|for|to)?\s*(?P<body_set_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("body_time_first") and groups.get("body_time_after"):
            return _strip_schedule_prefix(f"{groups['body_time_first']} {groups['body_time_after']}")
        body = _strip_schedule_prefix(
            groups.get("body")
            or groups.get("title")
            or groups.get("body_set")
            or groups.get("title_en")
            or groups.get("body_set_en")
            or ""
        )
        if body:
            return body
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


def _calendar_body(text: str) -> str:
    value = _clean(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历事件|日程|日历日程|calendar event)\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历|calendar)\s+(?P<body_calendar_short>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<time_first>[^。！？!?]+?)\s*(?:帮我)?\s*(?:在)?\s*"
        r"(?:日历|calendar)\s*(?:上|里|中|内)?\s*"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日程|事件|event)?\s*(?P<title_after_calendar>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)?\s*(?:日历|calendar)\s*"
        r"(?:上|里|中|内)?\s*(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日程|事件|event)?\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?calendar event\s+"
        r"(?:called|named|for)?\s*(?P<body>[^.!?]+)$",
        r"^(?:please\s+)?(?:schedule|add|create|make)\s+(?P<body_to_calendar_en>[^.!?]+?)\s+"
        r"(?:to|on|in)\s+(?:the\s+)?calendar$",
        r"^(?:please\s+)?schedule\s+(?P<body_scheduled_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("time_first") and groups.get("title_after_calendar"):
            return _strip_schedule_prefix(f"{groups['time_first']} {groups['title_after_calendar']}")
        body = _strip_schedule_prefix(
            groups.get("body")
            or groups.get("body_calendar_short")
            or groups.get("body_to_calendar_en")
            or groups.get("body_scheduled_en")
            or ""
        )
        if body:
            return body
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


_SCHEDULE_TIME_PATTERNS = (
    re.compile(
        r"(?P<full>"
        r"(?:(?:今天|今日|今晚|明天|明日|明晚|后天)\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*点"
        r"(?:(?P<half>半)|(?P<minute>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*分?)?"
        r")"
    ),
    re.compile(
        r"(?P<full>"
        r"(?:(?:今天|今日|今晚|明天|明日|明晚|后天)\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{1,2})"
        r")"
    ),
    re.compile(
        r"(?P<full>\b(?P<day_en>today|tomorrow|tonight)\b\s*(?:at\s*)?"
        r"(?P<hour_en>\d{1,2})(?:[:.](?P<minute_en>\d{2}))?\s*"
        r"(?P<ampm_en>a\.?m\.?|p\.?m\.?)?\b)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<full>\b(?:at\s*)?(?P<hour_en>\d{1,2})(?:[:.](?P<minute_en>\d{2}))?\s*"
        r"(?P<ampm_en>a\.?m\.?|p\.?m\.?)\s*"
        r"(?P<day_en>today|tomorrow|tonight)\b)",
        flags=re.IGNORECASE,
    ),
)


def _extract_schedule_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = _clean(value)
    if not text:
        return None
    for pattern in _SCHEDULE_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        scheduled = _datetime_from_schedule_match(match)
        if scheduled is None:
            continue
        title = _strip_schedule_prefix(f"{text[: match.start()]} {text[match.end() :]}")
        if title:
            return scheduled, title
    return None


def _datetime_from_schedule_match(match: re.Match[str]) -> datetime | None:
    groups = match.groupdict()
    if groups.get("hour_en"):
        hour = _parse_schedule_number(groups.get("hour_en"))
        minute = _parse_schedule_number(groups.get("minute_en") or "0")
        if hour is None or minute is None or hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        ampm = str(groups.get("ampm_en") or "").replace(".", "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        day = str(groups.get("day_en") or "").lower()
        if day == "tonight" and not ampm and hour < 12:
            hour += 12
        return _datetime_for_english_day_marker(day, hour, minute)

    full = str(match.group("full") or "")
    hour = _parse_schedule_number(match.group("hour"))
    minute = 30 if groups.get("half") else _parse_schedule_number(groups.get("minute") or "0")
    if hour is None or minute is None or hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    if any(marker in full for marker in ("下午", "晚上", "今晚", "明晚")) and hour < 12:
        hour += 12
    if "中午" in full and hour < 11:
        hour += 12
    if any(marker in full for marker in ("上午", "早上", "凌晨")) and hour == 12:
        hour = 0
    target_date = date.today() + timedelta(days=_chinese_day_offset(full))
    return datetime.combine(target_date, time(hour=hour, minute=minute))


def _extract_reminder_date_only_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = _clean(value)
    patterns = (
        r"^(?P<day_cn>今天|今日|今晚|明天|明日|明晚|后天)\s*"
        r"(?:要|去|做|进行|参加|记得|提醒我)?\s*(?P<title_after_cn>[^。！？!?]+)$",
        r"^(?P<title_before_cn>[^。！？!?]+?)\s*(?P<day_cn_tail>今天|今日|今晚|明天|明日|明晚|后天)$",
        r"^(?P<day>today|tomorrow|tonight)\b\s*(?:to\s+)?(?P<title_after>[^.!?]+)$",
        r"^(?P<title_before>[^.!?]+?)\s+\b(?P<day>today|tomorrow|tonight)\b$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        title = _strip_schedule_prefix(
            groups.get("title_after_cn")
            or groups.get("title_before_cn")
            or groups.get("title_after")
            or groups.get("title_before")
            or ""
        )
        if not title:
            continue
        day_cn = groups.get("day_cn") or groups.get("day_cn_tail")
        if day_cn:
            return _datetime_for_chinese_day_marker(day_cn), title
        day = str(groups.get("day") or "").lower()
        hour = 20 if day == "tonight" else 9
        return _datetime_for_english_day_marker(day, hour, 0), title
    return None


def _datetime_for_chinese_day_marker(day: str) -> datetime:
    marker = str(day or "")
    target_date = date.today() + timedelta(days=_chinese_day_offset(marker))
    hour = 20 if marker in {"今晚", "明晚"} else 9
    return datetime.combine(target_date, time(hour=hour, minute=0))


def _datetime_for_english_day_marker(day: str, hour: int, minute: int) -> datetime:
    marker = str(day or "").lower()
    day_offset = 1 if marker == "tomorrow" else 0
    target_date = date.today() + timedelta(days=day_offset)
    return datetime.combine(target_date, time(hour=hour, minute=minute))


def _chinese_day_offset(value: str) -> int:
    if "后天" in value:
        return 2
    if any(marker in value for marker in ("明天", "明日", "明晚")):
        return 1
    return 0


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_schedule_number(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[text]
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + _CHINESE_DIGITS.get(text[1:], 0)
    if "十" in text:
        head, _, tail = text.partition("十")
        head_value = _CHINESE_DIGITS.get(head)
        if head_value is None:
            return None
        return head_value * 10 + (_CHINESE_DIGITS.get(tail, 0) if tail else 0)
    return None


def _local_datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


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
