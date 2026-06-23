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

    allowed = {str(tool or "").strip() for tool in allowed_tools}
    for request in daily_desktop_intent_candidates(context):
        if str(request.get("tool") or "") in allowed:
            return request
    return None


def daily_desktop_intent_candidates(context: str) -> list[dict[str, Any]]:
    """Return ordered desktop tool candidates before policy filtering."""

    text = _clean_text(context)
    if not text or _looks_like_explanation_request(text) or _looks_like_negative_request(text):
        return []

    candidates: list[dict[str, Any]] = []
    url = _browser_open_url(text)
    if url:
        candidates.append(_request("browser.open_url", {"url": url}))

    if _is_browser_extract_text_request(text):
        candidates.append(_request("browser.extract_text", {}))

    if _is_browser_screenshot_request(text):
        candidates.append(
            _request("browser.screenshot", {"reason": "user asked to capture the browser page"})
        )

    if _is_browser_current_page_request(text):
        candidates.append(_request("browser.current_page", {}))

    music = _music_query(text)
    if music:
        candidates.append(_request("media.apple_music_play", {"query": music}))

    app_focus_name = _app_focus_name(text)
    if app_focus_name:
        candidates.append(_request("app.focus", {"app_name": app_focus_name}))

    app_name = _app_open_name(text)
    if app_name:
        candidates.append(_request("app.open", {"app_name": app_name}))

    hotkey = _desktop_hotkey(text)
    if hotkey:
        candidates.append(_request("desktop.hotkey", hotkey))

    type_text = _desktop_type_text(text)
    if type_text:
        candidates.append(_request("desktop.type_text", {"text": type_text}))

    click = _desktop_click(text)
    if click:
        candidates.append(_request("desktop.click", click))

    if _is_screen_capture_request(text):
        candidates.append(_request("screen.capture", {"reason": "user asked to capture the screen"}))

    if _is_active_window_request(text):
        candidates.append(_request("desktop.active_window", {}))

    return candidates


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
            r"(?:执行|操作|调用|真的|实际|播放|截图|截屏|读取|查看|"
            r"输入|打字|点击|按键|快捷键|网页)",
            text,
        )
        or re.search(
            r"(?:do not|don't|without|no need to).{0,24}"
            r"(?:execute|perform|call|play|capture|inspect|type|click|press|hotkey|"
            r"screenshot|read)",
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


def _is_browser_extract_text_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:读取|读一下|提取|抓取|获取).{0,10}"
            r"(?:当前|现在|前台)?(?:网页|网站|页面|浏览器).{0,10}(?:正文|文字|文本|内容)",
            text,
        )
        or "extract text from the current page" in lowered
        or "read the current page" in lowered
        or "read current page" in lowered
    )


def _is_browser_screenshot_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台)?(?:网页|网站|页面|浏览器).{0,8}"
            r"(?:截图|截屏|屏幕截图|抓屏)",
            text,
        )
        or re.search(
            r"(?:截取|截图|截屏|抓屏).{0,8}(?:当前|现在|前台)?(?:网页|网站|页面|浏览器)",
            text,
        )
        or "browser screenshot" in lowered
        or "page screenshot" in lowered
        or "screenshot the current page" in lowered
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
        r"(?:play)\s+(?P<query>[^.!?]+?)\s+(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?",
        r"(?:帮我|请|麻烦)?(?:直接)?播放[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?放[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:play)\s+(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_music_query_context(match.group("query"))
        if query and _is_specific_music_query(query):
            return query
    return ""


def _strip_music_query_context(value: str) -> str:
    query = _strip_query(value)
    query = re.sub(
        r"\s*(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:在|用|通过)\s*(?:apple\s*music|music|音乐)(?:里|中|上|内)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"^apple\s*music(?:里|中|上|内)?(?:的)?\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(?:music|音乐)(?:里|中|上|内)(?:的)?\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(?:里|中|上|内|里面)(?:的)?\s*", "", query)
    return _strip_query(query)


def _is_specific_music_query(query: str) -> bool:
    normalized = re.sub(r"[\s._-]+", "", query.lower())
    return normalized not in {"音乐", "music", "song", "歌曲", "applemusic"}


def _desktop_hotkey(text: str) -> dict[str, Any] | None:
    hotkey_part = (
        r"(?:command|cmd|shift|option|alt|control|ctrl|⌘|⇧|⌥|⌃|fn|"
        r"回车|换行|空格|退出|删除|退格|上箭头|下箭头|左箭头|右箭头|"
        r"enter|return|escape|esc|tab|space|delete|backspace|up|down|left|right|"
        r"[A-Za-z0-9])"
    )
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:按下|按|发送|触发|快捷键|热键|组合键|按键)\s*"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})+)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按下|按|发送|触发)\s*"
        rf"(?P<combo>{hotkey_part})",
        rf"(?:press|send|trigger)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_hotkey_combo(match.group("combo"))
        if parsed:
            return parsed
    return None


def _parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    parts = [
        part.strip()
        for part in re.split(r"(?:\s*\+\s*|\s*-\s*|\s+)", str(value or "").strip())
        if part.strip()
    ]
    if not parts:
        return None
    modifier_aliases = {
        "command": "command",
        "cmd": "command",
        "⌘": "command",
        "shift": "shift",
        "⇧": "shift",
        "option": "option",
        "alt": "option",
        "⌥": "option",
        "control": "control",
        "ctrl": "control",
        "⌃": "control",
    }
    key_aliases = {
        "enter": "return",
        "return": "return",
        "回车": "return",
        "换行": "return",
        "escape": "escape",
        "esc": "escape",
        "退出": "escape",
        "tab": "tab",
        "space": "space",
        "空格": "space",
        "delete": "delete",
        "删除": "delete",
        "backspace": "backspace",
        "退格": "backspace",
        "up": "up",
        "上箭头": "up",
        "down": "down",
        "下箭头": "down",
        "left": "left",
        "左箭头": "left",
        "right": "right",
        "右箭头": "right",
    }
    modifiers: list[str] = []
    key = ""
    for raw_part in parts:
        part = raw_part.lower()
        modifier = modifier_aliases.get(part)
        if modifier:
            if modifier not in modifiers:
                modifiers.append(modifier)
            continue
        if part == "fn":
            continue
        candidate = key_aliases.get(part, part)
        if re.fullmatch(r"[a-z0-9]", candidate) or candidate in key_aliases.values():
            key = candidate
        else:
            return None
    if not key:
        return None
    return {"key": key, "modifiers": modifiers}


def _desktop_type_text(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在前台|向前台|给当前窗口)?"
        r"(?:输入|打字|键入)\s*(?P<text>.+)$",
        r"(?:type|enter text)\s+(?P<text>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _strip_typed_text(match.group("text"))
        if typed_text:
            return typed_text
    return ""


def _strip_typed_text(value: str) -> str:
    text = _strip_query(value)
    text = re.sub(r"\s*(?:进去|到当前窗口|到前台|然后回车|并回车)$", "", text)
    return _strip_query(text)


def _desktop_click(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|click)\s*"
        r"(?:坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    payload: dict[str, Any] = {
        "x": _number_value(match.group("x")),
        "y": _number_value(match.group("y")),
        "click_count": 2 if match.group("double") else 1,
    }
    return payload


def _number_value(value: str) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


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


__all__ = ["daily_desktop_intent_candidates", "daily_desktop_intent_tool_request"]
