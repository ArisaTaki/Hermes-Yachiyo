"""Conservative daily desktop intent planner for Chat entrypoints."""

from __future__ import annotations

import re
from typing import Any


def daily_desktop_intent_tool_request(
    context: str,
    allowed_tools: list[str],
) -> dict[str, Any] | None:
    """Return a structured low-risk desktop tool request for clear daily Chat intents."""

    text = _clean_text(context)
    if not text or _looks_like_explanation_request(text) or _looks_like_negative_request(text):
        return None
    allowed = {str(tool or "").strip() for tool in allowed_tools}

    music = _music_query(text)
    if music and "media.apple_music_play" in allowed:
        return _request("media.apple_music_play", {"query": music})

    if _is_screen_capture_request(text) and "screen.capture" in allowed:
        return _request("screen.capture", {"reason": "user asked to capture the screen"})

    if _is_active_window_request(text) and "desktop.active_window" in allowed:
        return _request("desktop.active_window", {})

    return None


def _request(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"protocol": "json_fallback", "tool": tool, "input": payload}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _looks_like_explanation_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "怎么",
            "如何",
            "教程",
            "说明",
            "解释",
            "how to",
            "explain",
            "tutorial",
        )
    )


def _looks_like_negative_request(text: str) -> bool:
    return bool(
        re.search(
            r"(?:不要|不用|无需|不需要|别).{0,12}"
            r"(?:执行|操作|调用|真的|实际|播放|截图|截屏|读取|查看)",
            text,
        )
        or re.search(
            r"(?:do not|don't|without|no need to).{0,24}"
            r"(?:execute|perform|call|play|capture|inspect)",
            text.lower(),
        )
    )


def _music_query(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦)?(?:直接)?播放[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?放[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:play)\s+(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_query(match.group("query"))
        if query and query not in {"音乐", "music", "song", "歌曲"}:
            return query
    return ""


def _strip_query(value: str) -> str:
    return str(value or "").strip(" 「」『』“”\"'`，,。.!?？！？ ")


def _is_screen_capture_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"(?:截个?图|截图|截屏|屏幕截图|抓屏|拍屏)", text)
        or "take a screenshot" in lowered
        or "capture the screen" in lowered
        or "screen capture" in lowered
    )


def _is_active_window_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:窗口|应用|app).{0,8}"
            r"(?:是什么|是啥|哪个|名字|标题)?",
            text,
        )
        or "active window" in lowered
        or "foreground window" in lowered
        or "current window" in lowered
    )


__all__ = ["daily_desktop_intent_tool_request"]
