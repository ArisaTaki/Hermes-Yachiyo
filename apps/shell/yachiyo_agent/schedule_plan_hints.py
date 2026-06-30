"""Shared schedule intent hints for runtime planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

from .capture_plan_hints import context_source_hint


_LOCAL_ISO_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
_CHINESE_DAY_MARKER_RE = (
    r"今天|今日|今晚|明天|明日|明晚|后天|"
    r"下周[一二三四五六日天]|下星期[一二三四五六日天]"
)
_ENGLISH_RELATIVE_NUMBER_RE = (
    r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty"
)
_RELATIVE_DELAY_TEXT_RE = (
    r"(?:半|半个)\s*(?:小时|钟头)\s*(?:后|之后|以后)|"
    r"(?:\d+|[零〇一二两三四五六七八九十]{1,4})\s*"
    r"(?:分钟|分|小时|个小时|钟头|天|日)\s*(?:后|之后|以后)|"
    rf"\b(?:in|after)\s+(?:{_ENGLISH_RELATIVE_NUMBER_RE})\s*"
    r"(?:minutes?|mins?|hours?|hrs?|days?)\b"
)
_DEFAULT_REMINDER_TITLE = "提醒"


def schedule_tool_preview(
    text: str,
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    allowed = _allowed_tool_set(allowed_tools)
    scheduled_runnable = scheduled_runnable_payload(text)
    if scheduled_runnable:
        tool_name = _first_allowed(("future_task.schedule",), allowed)
        if tool_name:
            return tool_name, scheduled_runnable
        return None, scheduled_runnable
    if _looks_like_calendar_event(text):
        payload = calendar_event_payload(text)
        if payload:
            tool_name = _first_allowed(("calendar.create_event",), allowed)
            if tool_name:
                return tool_name, payload
            return _future_task_schedule_preview(text, payload, allowed)
    payload = reminder_payload(text)
    if payload:
        tool_name = _first_allowed(("reminders.create",), allowed)
        if tool_name:
            return tool_name, payload
        return _future_task_schedule_preview(text, payload, allowed)
    return None, {}


def scheduled_runnable_payload(text: str) -> dict[str, Any]:
    value = _clean(text)
    if not value:
        return {}
    runnable = _scheduled_runnable_target(value)
    if not runnable:
        return {}
    scheduled_at = _extract_schedule_datetime(value) or _extract_relative_delay_datetime(value)
    if scheduled_at is None:
        scheduled_at = _extract_reminder_date_only_datetime(value)
    if scheduled_at is None:
        return {}
    scheduled_epoch = _local_iso_to_epoch(_local_datetime_text(scheduled_at))
    if scheduled_epoch is None:
        return {}
    runnable_name = str(runnable.get("runnable_name") or "").strip()
    runnable_kind = str(runnable.get("runnable_kind") or "").strip()
    prompt = _scheduled_runnable_prompt(value, runnable_name, runnable_kind)
    title = _scheduled_runnable_title(runnable_name, runnable_kind)
    payload: dict[str, Any] = {
        "title": title,
        "prompt": prompt,
        "scheduled_at_epoch": scheduled_epoch,
    }
    if runnable_name:
        payload["runnable_name"] = runnable_name
    return payload


def reminder_payload(text: str) -> dict[str, Any]:
    if _dynamic_schedule_source_request(text):
        return {}
    body = _reminder_body(text)
    if not body:
        return {}
    iso_due_at = _local_iso_hint(text)
    if iso_due_at:
        title = _strip_schedule_prefix(re.sub(rf"\b{_LOCAL_ISO_RE}\b", "", body).strip())
        return {"title": title or _DEFAULT_REMINDER_TITLE, "due_at": iso_due_at}
    scheduled = _extract_schedule_datetime_and_title(body)
    if scheduled:
        due_at, title = scheduled
        return {"title": title, "due_at": _local_datetime_text(due_at)} if title else {}
    scheduled_without_title = _extract_schedule_datetime(body)
    if scheduled_without_title:
        return {
            "title": _DEFAULT_REMINDER_TITLE,
            "due_at": _local_datetime_text(scheduled_without_title),
        }
    relative = _extract_relative_delay_datetime_and_title(body)
    if relative:
        due_at, title = relative
        return {"title": title, "due_at": _local_datetime_text(due_at)} if title else {}
    relative_without_title = _extract_relative_delay_datetime(body)
    if relative_without_title:
        return {
            "title": _DEFAULT_REMINDER_TITLE,
            "due_at": _local_datetime_text(relative_without_title),
        }
    date_only = _extract_reminder_date_only_datetime_and_title(body)
    if date_only:
        due_at, title = date_only
        return {"title": title, "due_at": _local_datetime_text(due_at)} if title else {}
    date_only_without_title = _extract_reminder_date_only_datetime(body)
    if date_only_without_title:
        return {
            "title": _DEFAULT_REMINDER_TITLE,
            "due_at": _local_datetime_text(date_only_without_title),
        }
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
        scheduled = _extract_relative_delay_datetime_and_title(body)
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


def _future_task_schedule_preview(
    text: str,
    schedule_payload: dict[str, Any],
    allowed: set[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    tool_name = _first_allowed(("future_task.schedule",), allowed)
    if not tool_name:
        return None, schedule_payload
    title = str(schedule_payload.get("title") or "").strip()
    scheduled_at = str(
        schedule_payload.get("due_at") or schedule_payload.get("start_at") or ""
    ).strip()
    if not title or not scheduled_at:
        return None, {}
    scheduled_epoch = _local_iso_to_epoch(scheduled_at)
    if scheduled_epoch is None:
        return None, {}
    return tool_name, {
        "title": title,
        "prompt": _future_task_prompt(title, text),
        "scheduled_at_epoch": scheduled_epoch,
    }


def schedule_context_source_hint(text: str) -> str:
    if not _looks_like_schedule_target(text):
        return ""
    return context_source_hint(text)


def _looks_like_calendar_event(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in ("calendar", "event", "meeting", "日历", "日程", "会议")) or (
        "安排" in str(text or "") and _has_explicit_schedule_time(text)
    )


def _dynamic_schedule_source_request(text: str) -> bool:
    return bool(schedule_context_source_hint(text))


def _looks_like_schedule_target(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
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


def _reminder_body(text: str) -> str:
    value = _clean(text)
    value = re.sub(rf"\b{_LOCAL_ISO_RE}\b", "", value).strip()
    patterns = (
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<body_time_first>[^。！？!?]+?)\s*提醒我\s*(?P<body_time_after>[^。！？!?]+)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<body_time_first_plain>[^。！？!?]+?)\s*提醒(?!事项)\s*(?P<body_time_after_plain>[^。！？!?]+)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:创建|新建|添加|新增)?\s*(?:一个|一条|一项)?\s*(?:提醒事项|提醒)\s*[:：]?\s*(?P<title>.+)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:创建|新建|添加|新增)\s*(?:个|一个|一条|一项|新的?)?\s*"
        r"(?P<body_create>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:设置|设|定|订)\s*(?:个|一个|一条|一项|新的?)?\s*"
        r"(?P<body_set>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒)$",
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<body_time_only>[^。！？!?]+?)\s*提醒(?!事项)\s*$",
        r"^(?:please\s+)?(?:create|add|make)?\s*(?:a\s+)?(?:new\s+)?reminder\s*(?:called|named|for|to)?\s*(?P<title_en>.+)$",
        r"^(?:please\s+)?(?:set)\s+(?:a\s+)?(?:new\s+)?reminder\s*(?:called|named|for|to)?\s*(?P<body_set_en>[^.!?]+)$",
        r"^(?:please\s+)?(?P<body_time_first_en>(?:in|after)\s+"
        r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
        r"thirty|forty|fifty|sixty)\s*(?:minutes?|mins?|hours?|hrs?|days?))\s+"
        r"remind\s+me\s+(?:to\s+)?(?P<body_time_after_en>[^.!?]+)$",
        r"^(?:please\s+)?remind\s+me\s+(?P<body_time_mid_en>(?:in|after)\s+"
        r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
        r"thirty|forty|fifty|sixty)\s*(?:minutes?|mins?|hours?|hrs?|days?))\s+"
        r"(?:to\s+)?(?P<body_after_mid_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("body_time_first") and groups.get("body_time_after"):
            return _strip_schedule_prefix(f"{groups['body_time_first']} {groups['body_time_after']}")
        if groups.get("body_time_first_plain") and groups.get("body_time_after_plain"):
            return _strip_schedule_prefix(
                f"{groups['body_time_first_plain']} {groups['body_time_after_plain']}"
            )
        if groups.get("body_time_only"):
            return _strip_schedule_prefix(groups["body_time_only"])
        if groups.get("body_time_first_en") and groups.get("body_time_after_en"):
            return _strip_schedule_prefix(
                f"{groups['body_time_first_en']} {groups['body_time_after_en']}"
            )
        if groups.get("body_time_mid_en") and groups.get("body_after_mid_en"):
            return _strip_schedule_prefix(
                f"{groups['body_time_mid_en']} {groups['body_after_mid_en']}"
            )
        body = _strip_schedule_prefix(
            groups.get("body")
            or groups.get("title")
            or groups.get("body_create")
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
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?P<relative_time_first>{_RELATIVE_DELAY_TEXT_RE})\s*(?:帮我)?\s*"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<title_after_relative_time>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?P<time_first>(?:(?:{_CHINESE_DAY_MARKER_RE})\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?:\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*点"
        r"(?:(?:半)|(?:\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*分?)?)"
        r"\s*(?:帮我)?\s*"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<title_after_time>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_action_first>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_target_after>[^。！？!?]+?)\s*"
        r"(?:的)?(?:日历事件|日历日程|日程|事件|会议)$",
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
        rf"^(?:please\s+)?(?P<relative_time_first_en>{_RELATIVE_DELAY_TEXT_RE})\s+"
        r"(?:schedule|add|create|make)\s+(?:a\s+)?"
        r"(?:(?:calendar\s+)?(?:event|meeting)\s*(?:with|for)?\s*)?"
        r"(?P<title_after_relative_time_en>[^.!?]+)$",
        r"^(?:please\s+)?schedule\s+(?P<body_scheduled_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("relative_time_first") and groups.get("title_after_relative_time"):
            return _strip_schedule_prefix(
                f"{groups['relative_time_first']} "
                f"{_strip_calendar_target_suffix(groups['title_after_relative_time'])}"
            )
        if groups.get("relative_time_first_en") and groups.get("title_after_relative_time_en"):
            return _strip_schedule_prefix(
                f"{groups['relative_time_first_en']} {groups['title_after_relative_time_en']}"
            )
        if groups.get("time_first") and groups.get("title_after_calendar"):
            return _strip_schedule_prefix(f"{groups['time_first']} {groups['title_after_calendar']}")
        if groups.get("time_first") and groups.get("title_after_time"):
            return _strip_schedule_prefix(
                f"{groups['time_first']} {_strip_calendar_target_suffix(groups['title_after_time'])}"
            )
        body = _strip_schedule_prefix(
            groups.get("body")
            or groups.get("body_calendar_short")
            or groups.get("body_target_after")
            or groups.get("body_action_first")
            or groups.get("body_to_calendar_en")
            or groups.get("body_scheduled_en")
            or ""
        )
        if body:
            return body
    return ""


def _has_explicit_schedule_time(text: str) -> bool:
    value = _clean(text)
    if not value:
        return False
    return bool(
        re.search(
            rf"(?:{_CHINESE_DAY_MARKER_RE}|上午|早上|下午|晚上|今晚|中午|凌晨|"
            r"\d{1,2}\s*点|\d{1,2}\s*[:：]\s*\d{1,2}|"
            rf"{_RELATIVE_DELAY_TEXT_RE}|"
            r"\b(?:today|tomorrow|tonight)\b|\bat\s+\d{1,2}(?::\d{2})?\b)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _local_iso_hint(text: str) -> str:
    match = re.search(rf"\b({_LOCAL_ISO_RE})\b", str(text or ""))
    return match.group(1) if match else ""


def _strip_schedule_prefix(value: str) -> str:
    title = _clean(value)
    title = re.sub(r"^(?:的|这个|该)\s*", "", title)
    title = re.sub(r"^(?:在|于|到时候|的时候|时|要|去|做|进行|参加|记得|提醒我)\s*", "", title)
    title = re.sub(r"^(?:to|for|about|that|please)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*(?:的时候|时|在|于)$", "", title).strip()
    title = title.strip(" .，,。")
    if title in {"个", "一个", "一条", "一项", "新的", "我", "提醒", "提醒事项", "日程", "事件", "会议"}:
        return ""
    if title.lower() in {"a", "an", "new", "reminder", "event", "meeting"}:
        return ""
    return title


def _strip_calendar_target_suffix(value: str) -> str:
    return re.sub(
        r"\s*(?:的)?(?:日历事件|日历日程|日程|事件)$",
        "",
        _clean(value),
        flags=re.IGNORECASE,
    ).strip()


_SCHEDULE_TIME_PATTERNS = (
    re.compile(
        r"(?P<full>"
        rf"(?:(?:{_CHINESE_DAY_MARKER_RE})\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*点"
        r"(?:(?P<half>半)|(?P<minute>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*分?)?"
        r")"
    ),
    re.compile(
        r"(?P<full>"
        rf"(?:(?:{_CHINESE_DAY_MARKER_RE})\s*)?"
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


def _extract_schedule_datetime(value: str) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    for pattern in _SCHEDULE_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        scheduled = _datetime_from_schedule_match(match)
        if scheduled is not None:
            return scheduled
    return None


_RELATIVE_DELAY_PATTERNS = (
    re.compile(
        r"(?P<full>"
        r"(?:(?P<half_cn>半|半个)\s*(?:小时|钟头)|"
        r"(?P<amount_cn>\d+|[零〇一二两三四五六七八九十]{1,4})\s*"
        r"(?P<unit_cn>分钟|分|小时|个小时|钟头|天|日))"
        r"\s*(?:后|之后|以后))"
    ),
    re.compile(
        r"(?P<full>\b(?:in|after)\s+"
        rf"(?P<amount_en>{_ENGLISH_RELATIVE_NUMBER_RE})\s*"
        r"(?P<unit_en>minutes?|mins?|hours?|hrs?|days?)\b)",
        flags=re.IGNORECASE,
    ),
)


def _extract_relative_delay_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = _clean(value)
    if not text:
        return None
    for pattern in _RELATIVE_DELAY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        delay = _relative_delay_from_match(match)
        if delay is None:
            continue
        title = _strip_schedule_prefix(f"{text[: match.start()]} {text[match.end() :]}")
        if title:
            return datetime.now() + delay, title
    return None


def _extract_relative_delay_datetime(value: str) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    for pattern in _RELATIVE_DELAY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        delay = _relative_delay_from_match(match)
        if delay is not None:
            return datetime.now() + delay
    return None


def _relative_delay_from_match(match: re.Match[str]) -> timedelta | None:
    groups = match.groupdict()
    if groups.get("half_cn"):
        return timedelta(minutes=30)
    amount = _parse_schedule_number(groups.get("amount_cn"))
    unit = str(groups.get("unit_cn") or "").strip()
    if amount is None:
        amount = _parse_english_schedule_number(groups.get("amount_en"))
        unit = str(groups.get("unit_en") or "").lower()
    if amount is None or amount <= 0:
        return None
    if unit in {"分钟", "分", "minute", "minutes", "min", "mins"}:
        return timedelta(minutes=amount)
    if unit in {"小时", "个小时", "钟头", "hour", "hours", "hr", "hrs"}:
        return timedelta(hours=amount)
    if unit in {"天", "日", "day", "days"}:
        return timedelta(days=amount)
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
    target_date = _target_date_for_chinese_schedule_text(full)
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


def _extract_reminder_date_only_datetime(value: str) -> datetime | None:
    text = _clean(value)
    if re.fullmatch(r"(?:今天|今日|今晚|明天|明日|明晚|后天)", text):
        return _datetime_for_chinese_day_marker(text)
    day = text.lower()
    if day in {"today", "tomorrow", "tonight"}:
        hour = 20 if day == "tonight" else 9
        return _datetime_for_english_day_marker(day, hour, 0)
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


def _target_date_for_chinese_schedule_text(value: str) -> date:
    text = str(value or "")
    weekday_match = re.search(r"(?:下周|下星期)([一二三四五六日天])", text)
    if weekday_match:
        target_weekday = _CHINESE_WEEKDAY_INDEX.get(weekday_match.group(1))
        if target_weekday is not None:
            today = date.today()
            days_until_next_monday = 7 - today.weekday()
            next_monday = today + timedelta(days=days_until_next_monday)
            return next_monday + timedelta(days=target_weekday)
    return date.today() + timedelta(days=_chinese_day_offset(text))


_CHINESE_WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


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


_ENGLISH_SCHEDULE_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
}


def _parse_english_schedule_number(value: str | None) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _ENGLISH_SCHEDULE_NUMBERS.get(text)


def _local_datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def _local_iso_to_epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _future_task_prompt(title: str, text: str) -> str:
    clean_title = _clean(title)
    clean_text = _clean(text)
    if clean_text:
        return f"提醒用户：{clean_title}。原始请求：{clean_text}"
    return f"提醒用户：{clean_title}"


def _scheduled_runnable_target(text: str) -> dict[str, str]:
    value = _strip_schedule_time_text(_clean(text))
    if not _scheduled_runnable_action_requested(value):
        return {}
    workflow_patterns = (
        r"(?:workflow|flow)\s+(?P<name>[A-Za-z0-9 ._-]{1,80})$",
        r"(?:工作流|流程)\s*(?P<name>[^。！？!?，,]{1,80})$",
        r"(?P<name>[\w .·-]{1,80}?)\s*(?:workflow|flow|工作流|流程)",
    )
    group_patterns = (
        r"(?P<name>[\w .·-]{1,80}?)\s*(?:agent\s*group|group|群组|小组)",
        r"(?:agent\s*group|group|群组|小组)\s+(?P<name>[A-Za-z0-9 ._-]{1,80})$",
        r"(?:群组|小组)\s*(?P<name>[^。！？!?，,]{1,80})$",
    )
    agent_patterns = (
        r"(?P<name>[\w .·-]{1,80}?)\s*(?:agent|智能体|代理)",
        r"(?:agent|智能体|代理)\s*(?P<name>[^。！？!?，,]{1,80})$",
    )
    pattern_groups = (
        (
            "workflow",
            workflow_patterns,
        ),
        (
            "group",
            group_patterns,
        ),
        (
            "agent",
            agent_patterns,
        ),
    )
    for runnable_kind, patterns in pattern_groups:
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if not match:
                continue
            runnable_name = _clean_scheduled_runnable_name(match.group("name"))
            if runnable_name:
                return {
                    "runnable_kind": runnable_kind,
                    "runnable_name": runnable_name,
                }
    return {}


def _scheduled_runnable_action_requested(text: str) -> bool:
    return bool(
        re.search(
            r"(?:运行|启动|执行|跑|安排|调度|定时|"
            r"\brun\b|\bstart\b|\bexecute\b|\bschedule\b)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _clean_scheduled_runnable_name(value: str) -> str:
    name = re.sub(
        rf"(?:{_RELATIVE_DELAY_TEXT_RE}|{_CHINESE_DAY_MARKER_RE})",
        " ",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    for pattern in _SCHEDULE_TIME_PATTERNS:
        name = pattern.sub(" ", name)
    previous = None
    while previous != name:
        previous = name
        name = re.sub(
            r"^\s*(?:帮我|给我|请|麻烦|能否|能不能|可以|直接)\s*",
            " ",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(
            r"^\s*(?:安排|调度|定时|运行|启动|执行|跑)\s*",
            " ",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(
            r"^\s*(?:please|can\s+you|could\s+you|would\s+you|"
            r"run|start|execute|schedule)\s+",
            " ",
            name,
            flags=re.IGNORECASE,
        )
    return _clean(name).strip(" .，,。")


def _scheduled_runnable_prompt(text: str, runnable_name: str, runnable_kind: str) -> str:
    label = {
        "workflow": "workflow",
        "group": "group",
        "agent": "agent",
    }.get(runnable_kind, "runnable")
    prompt = _strip_schedule_time_text(text)
    prompt = re.sub(
        r"^(?:帮我|给我|请|麻烦|能否|能不能|可以|直接)\s*",
        "",
        prompt,
        flags=re.IGNORECASE,
    )
    prompt = re.sub(
        r"^(?:please|can\s+you|could\s+you|would\s+you)\s+",
        "",
        prompt,
        flags=re.IGNORECASE,
    )
    prompt = _clean(prompt).strip(" .，,。")
    return prompt or f"运行 {runnable_name} {label}".strip()


def _scheduled_runnable_title(runnable_name: str, runnable_kind: str) -> str:
    label = {
        "workflow": "workflow",
        "group": "group",
        "agent": "agent",
    }.get(runnable_kind, "runnable")
    return f"运行 {runnable_name} {label}".strip()


def _strip_schedule_time_text(text: str) -> str:
    value = _clean(text)
    value = re.sub(
        rf"(?:{_RELATIVE_DELAY_TEXT_RE}|{_CHINESE_DAY_MARKER_RE})",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    for pattern in _SCHEDULE_TIME_PATTERNS:
        value = pattern.sub(" ", value)
    return _clean(value)


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
