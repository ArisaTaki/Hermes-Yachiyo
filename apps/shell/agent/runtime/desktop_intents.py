"""Conservative daily desktop intent planner for Chat entrypoints."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def daily_desktop_intent_tool_request(
    context: str,
    allowed_tools: list[str],
) -> dict[str, Any] | None:
    """Return a structured low-risk desktop tool request for clear daily Chat intents."""

    text = _clean_text(context)
    if not text or _looks_like_explanation_request(text) or _looks_like_negative_request(text):
        return None
    allowed = {str(tool or "").strip() for tool in allowed_tools}

    url = _browser_open_url(text)
    if url and "browser.open_url" in allowed:
        return _request("browser.open_url", {"url": url})

    if _is_browser_current_page_request(text) and "browser.current_page" in allowed:
        return _request("browser.current_page", {})

    app_focus_name = _app_focus_name(text)
    if app_focus_name and "app.focus" in allowed:
        return _request("app.focus", {"app_name": app_focus_name})

    app_name = _app_open_name(text)
    if app_name and "app.open" in allowed:
        return _request("app.open", {"app_name": app_name})

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


def _browser_open_url(text: str) -> str:
    url_token = (
        r"(?:https?://[^\s。！？!?，,]+|www\.[^\s。！？!?，,]+|"
        r"localhost(?::\d+)?(?:/[^\s。！？!?，,]*)?|"
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:/[^\s。！？!?，,]*)?)"
    )
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|访问|浏览|前往|去)\s*(?P<url>{url_token})",
        rf"(?:open|visit|browse|go to)\s+(?P<url>{url_token})",
        rf"^(?P<url>{url_token})$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        url = _normalize_url(match.group("url"))
        if url:
            return url
    return ""


def _normalize_url(value: str) -> str:
    candidate = str(value or "").strip(" 「」『』“”\"'`，,。.!?？！？ ")
    if not candidate:
        return ""
    if re.search(r"\s", candidate):
        return ""
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
        return ""
    if lowered.startswith("www."):
        return f"https://{candidate}"
    if lowered.startswith("localhost"):
        return f"http://{candidate}"
    domain_pattern = (
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
        r"(?::\d{1,5})?(?:/[^\s]*)?"
    )
    if re.fullmatch(domain_pattern, candidate):
        return f"https://{candidate}"
    return ""


def _is_browser_current_page_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:网页|网站|页面|浏览器).{0,8}"
            r"(?:是什么|是啥|哪个|地址|标题|url)?",
            text,
        )
        or "current page" in lowered
        or "current browser tab" in lowered
        or "active browser tab" in lowered
    )


def _app_focus_name(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:切换到|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _normalize_app_name(match.group("app"))
        if app_name:
            return app_name
    return ""


def _app_open_name(text: str) -> str:
    media_app = _media_app_open_name(text)
    if media_app:
        return media_app

    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:open|launch|start)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _normalize_app_name(match.group("app"))
        if app_name:
            return app_name
    return ""


def _media_app_open_name(text: str) -> str:
    lowered = text.lower()
    if not re.search(r"(?:播放|放|打开|启动|运行|open|launch|start|play)", lowered):
        return ""
    if re.search(r"apple\s*music", lowered):
        return "Music"
    if re.search(r"(?:播放|放|打开|启动|运行)\s*(?:一下\s*)?(?:音乐|music)(?:应用|app|软件|程序)?\s*$", lowered):
        return "Music"
    if re.search(r"(?:open|launch|start|play)\s+music(?:\s+app)?\s*$", lowered):
        return "Music"
    return ""


def _normalize_app_name(value: str) -> str:
    app = _strip_app_name(value)
    if not app:
        return ""
    if _normalize_url(app):
        return ""
    lowered = app.lower()
    compact = re.sub(r"[\s._-]+", "", lowered)
    aliases = {
        "applemusic": "Music",
        "music": "Music",
        "音乐": "Music",
        "googlechrome": "Google Chrome",
        "chrome": "Google Chrome",
        "safari": "Safari",
        "finder": "Finder",
        "访达": "Finder",
        "terminal": "Terminal",
        "终端": "Terminal",
        "systemsettings": "System Settings",
        "settings": "System Settings",
        "系统设置": "System Settings",
        "notes": "Notes",
        "备忘录": "Notes",
        "calendar": "Calendar",
        "日历": "Calendar",
        "reminders": "Reminders",
        "提醒事项": "Reminders",
        "mail": "Mail",
        "邮件": "Mail",
        "wechat": "WeChat",
        "微信": "WeChat",
        "qq": "QQ",
        "slack": "Slack",
        "discord": "Discord",
        "notion": "Notion",
        "obsidian": "Obsidian",
        "vscode": "Visual Studio Code",
        "visualstudiocode": "Visual Studio Code",
    }
    return aliases.get(compact, app)


def _strip_app_name(value: str) -> str:
    app = _strip_query(value)
    app = re.sub(r"^(?:一下|下|这个|那个)\s*", "", app)
    app = re.sub(r"\s*(?:应用|app|软件|程序)$", "", app, flags=re.IGNORECASE)
    app = re.sub(r"\s*(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)$", "", app, flags=re.IGNORECASE)
    return app.strip()


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
        if query and _is_specific_music_query(query):
            return query
    return ""


def _is_specific_music_query(query: str) -> bool:
    normalized = re.sub(r"[\s._-]+", "", query.lower())
    return normalized not in {"音乐", "music", "song", "歌曲", "applemusic"}


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
