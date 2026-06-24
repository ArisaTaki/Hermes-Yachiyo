"""Conservative daily desktop intent planner for Chat entrypoints."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote_plus, urlparse


_APP_ALIASES = {
    "applemusic": "Music",
    "苹果音乐": "Music",
    "music": "Music",
    "音乐": "Music",
    "qq音乐": "QQ音乐",
    "qqmusic": "QQ音乐",
    "网易云音乐": "网易云音乐",
    "neteasecloudmusic": "网易云音乐",
    "neteasemusic": "网易云音乐",
    "cloudmusic": "网易云音乐",
    "googlechrome": "Google Chrome",
    "chrome": "Google Chrome",
    "chrome浏览器": "Google Chrome",
    "谷歌浏览器": "Google Chrome",
    "浏览器": "Google Chrome",
    "browser": "Google Chrome",
    "safari": "Safari",
    "finder": "Finder",
    "访达": "Finder",
    "terminal": "Terminal",
    "终端": "Terminal",
    "命令行": "Terminal",
    "systemsettings": "System Settings",
    "systempreferences": "System Settings",
    "settings": "System Settings",
    "系统设置": "System Settings",
    "系统偏好": "System Settings",
    "系统偏好设置": "System Settings",
    "设置": "System Settings",
    "蓝牙设置": "System Settings",
    "bluetoothsettings": "System Settings",
    "wifi设置": "System Settings",
    "wi-fi设置": "System Settings",
    "wifisettings": "System Settings",
    "wi-fisettings": "System Settings",
    "无线网络设置": "System Settings",
    "网络设置": "System Settings",
    "声音设置": "System Settings",
    "音量设置": "System Settings",
    "显示器设置": "System Settings",
    "显示设置": "System Settings",
    "文件管理器": "Finder",
    "文件浏览器": "Finder",
    "notes": "Notes",
    "备忘录": "Notes",
    "calendar": "Calendar",
    "日历": "Calendar",
    "reminders": "Reminders",
    "提醒事项": "Reminders",
    "mail": "Mail",
    "邮件": "Mail",
    "邮箱": "Mail",
    "电子邮件": "Mail",
    "messages": "Messages",
    "信息": "Messages",
    "通讯": "Messages",
    "facetime": "FaceTime",
    "contacts": "Contacts",
    "联系人": "Contacts",
    "通讯录": "Contacts",
    "maps": "Maps",
    "地图": "Maps",
    "photos": "Photos",
    "照片": "Photos",
    "preview": "Preview",
    "预览": "Preview",
    "calculator": "Calculator",
    "计算器": "Calculator",
    "appstore": "App Store",
    "应用商店": "App Store",
    "activitymonitor": "Activity Monitor",
    "活动监视器": "Activity Monitor",
    "keychainaccess": "Keychain Access",
    "钥匙串": "Keychain Access",
    "钥匙串访问": "Keychain Access",
    "textedit": "TextEdit",
    "文本编辑": "TextEdit",
    "quicktime": "QuickTime Player",
    "quicktimeplayer": "QuickTime Player",
    "wechat": "WeChat",
    "微信": "WeChat",
    "qq": "QQ",
    "slack": "Slack",
    "discord": "Discord",
    "notion": "Notion",
    "obsidian": "Obsidian",
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "vscode": "Visual Studio Code",
    "vsc": "Visual Studio Code",
    "visualstudiocode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "cursor": "Cursor",
    "arc": "Arc",
    "arc浏览器": "Arc",
    "firefox": "Firefox",
    "火狐": "Firefox",
    "firefox浏览器": "Firefox",
    "火狐浏览器": "Firefox",
    "edge": "Microsoft Edge",
    "edge浏览器": "Microsoft Edge",
    "microsoftedge": "Microsoft Edge",
    "brave": "Brave Browser",
    "brave浏览器": "Brave Browser",
    "spotify": "Spotify",
    "音乐播放器": "Music",
    "播放器": "Music",
    "musicplayer": "Music",
    "shortcuts": "Shortcuts",
    "快捷指令": "Shortcuts",
    "figma": "Figma",
    "zoom": "zoom.us",
    "zoomus": "zoom.us",
    "teams": "Microsoft Teams",
    "microsoftteams": "Microsoft Teams",
    "word": "Microsoft Word",
    "microsoftword": "Microsoft Word",
    "excel": "Microsoft Excel",
    "microsoftexcel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "ppt": "Microsoft PowerPoint",
    "microsoftpowerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "microsoftoutlook": "Microsoft Outlook",
    "telegram": "Telegram",
    "telegramdesktop": "Telegram",
    "whatsapp": "WhatsApp",
    "企业微信": "WeCom",
    "企业微信客户端": "WeCom",
    "wecom": "WeCom",
    "wecomclient": "WeCom",
    "wechatwork": "WeCom",
    "飞书": "飞书",
    "feishu": "Feishu",
    "lark": "Lark",
    "钉钉": "DingTalk",
    "dingtalk": "DingTalk",
    "腾讯会议": "Tencent Meeting",
    "tencentmeeting": "Tencent Meeting",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "warp": "Warp",
    "docker": "Docker",
    "xcode": "Xcode",
    "postman": "Postman",
    "linear": "Linear",
    "raycast": "Raycast",
    "pycharm": "PyCharm",
    "intellij": "IntelliJ IDEA",
    "idea": "IntelliJ IDEA",
    "webstorm": "WebStorm",
    "goland": "GoLand",
}

_BROWSER_APP_NAMES = {
    "Arc",
    "Brave Browser",
    "Firefox",
    "Google Chrome",
    "Microsoft Edge",
    "Safari",
}

_COMMUNICATION_APP_NAMES = {
    "DingTalk",
    "Feishu",
    "Lark",
    "Messages",
    "QQ",
    "Slack",
    "Telegram",
    "WeChat",
    "WhatsApp",
}

_TERMINAL_COMMAND_HEADS = {
    "awk",
    "brew",
    "cat",
    "cargo",
    "curl",
    "date",
    "df",
    "du",
    "echo",
    "find",
    "git",
    "go",
    "grep",
    "ifconfig",
    "ls",
    "make",
    "netstat",
    "node",
    "npm",
    "pnpm",
    "ps",
    "pwd",
    "pytest",
    "python",
    "python3",
    "rg",
    "ruby",
    "sed",
    "sw_vers",
    "uname",
    "uv",
    "whoami",
    "yarn",
}

_COMMON_REVEAL_PATHS = {
    "desktop": "~/Desktop",
    "desktopfolder": "~/Desktop",
    "桌面": "~/Desktop",
    "桌面文件夹": "~/Desktop",
    "桌面目录": "~/Desktop",
    "我的桌面": "~/Desktop",
    "downloads": "~/Downloads",
    "downloadsfolder": "~/Downloads",
    "downloadsdirectory": "~/Downloads",
    "下载": "~/Downloads",
    "下载文件夹": "~/Downloads",
    "下载目录": "~/Downloads",
    "我的下载": "~/Downloads",
    "documents": "~/Documents",
    "documentsfolder": "~/Documents",
    "documentsdirectory": "~/Documents",
    "文档": "~/Documents",
    "文档文件夹": "~/Documents",
    "文档目录": "~/Documents",
    "我的文档": "~/Documents",
    "文稿": "~/Documents",
    "文稿文件夹": "~/Documents",
    "文稿目录": "~/Documents",
    "home": "~",
    "homefolder": "~",
    "主目录": "~",
    "用户文件夹": "~",
    "applications": "/Applications",
    "applicationsfolder": "/Applications",
    "applicationfolder": "/Applications",
    "applicationsdirectory": "/Applications",
    "应用程序": "/Applications",
    "应用程序文件夹": "/Applications",
    "应用程序目录": "/Applications",
}
_MUSIC_APP_COMPACTS = {
    "applemusic",
    "苹果音乐",
    "music",
    "musicapp",
    "musicplayer",
    "音乐",
    "音乐app",
    "音乐应用",
    "音乐软件",
    "音乐播放器",
    "播放器",
    "spotify",
    "qq音乐",
    "qqmusic",
    "网易云音乐",
    "neteasecloudmusic",
    "neteasemusic",
    "cloudmusic",
}

_APP_STATUS_PATTERNS = (
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:开了没|开着没|打开没|打开了没|启动没|启动了没)"
    r"\s*(?:吗|嘛|呢)?$",
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:是否|有没有|是不是)?\s*"
    r"(?:开着|打开着|打开了|开了吗|打开了吗|在运行|正在运行|运行着|启动了|启动着)\s*(?:吗|嘛|呢)?$",
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:是否|有没有|是不是)?\s*"
    r"(?:开着|打开着|打开了|在运行|正在运行|运行着|启动了|启动着)",
    r"(?:is|check if|whether|see if)\s+(?P<app>[^.!?]+?)\s+(?:is\s+)?(?:running|open)",
    r"(?P<app>[^.!?]+?)\s+(?:running|open)\?",
)


def daily_desktop_intent_tool_request(
    context: str,
    allowed_tools: list[str],
) -> dict[str, Any] | None:
    """Return a structured desktop tool request for clear daily Chat intents."""

    requests = daily_desktop_intent_tool_requests(context, allowed_tools)
    return requests[0] if requests else None


def daily_desktop_intent_tool_requests(
    context: str,
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    """Return structured desktop tool requests for clear daily Chat intents."""

    allowed = {str(tool or "").strip() for tool in allowed_tools}
    address_bar_url = _browser_address_bar_url(context)
    if address_bar_url and "browser.open_url" in allowed:
        return [_request("browser.open_url", {"url": address_bar_url})]
    selected_text_read_sequence = _selected_text_read_tool_requests(context)
    if selected_text_read_sequence and all(
        str(request.get("tool") or "") in allowed for request in selected_text_read_sequence
    ):
        return selected_text_read_sequence
    communication_compose_sequence = _communication_compose_tool_requests(context)
    if communication_compose_sequence and all(
        str(request.get("tool") or "") in allowed for request in communication_compose_sequence
    ):
        return communication_compose_sequence
    browser_search_click_sequence = _browser_search_then_click_tool_requests(context)
    if browser_search_click_sequence and all(
        str(request.get("tool") or "") in allowed for request in browser_search_click_sequence
    ):
        return browser_search_click_sequence
    browser_open_request = _browser_open_url_tool_request(context, allowed)
    if browser_open_request:
        return [browser_open_request]
    schedule_create_request = _schedule_create_tool_request(context)
    if schedule_create_request and str(schedule_create_request.get("tool") or "") in allowed:
        return [schedule_create_request]
    notes_create_request = _notes_create_tool_request(context)
    if notes_create_request and str(notes_create_request.get("tool") or "") in allowed:
        return [notes_create_request]
    notes_create_type_sequence = _notes_create_and_type_tool_requests(context)
    if notes_create_type_sequence and all(
        str(request.get("tool") or "") in allowed for request in notes_create_type_sequence
    ):
        return notes_create_type_sequence
    reminders_create_type_sequence = _reminders_create_and_type_tool_requests(context)
    if reminders_create_type_sequence and all(
        str(request.get("tool") or "") in allowed for request in reminders_create_type_sequence
    ):
        return reminders_create_type_sequence
    app_browser_action_sequence = _app_open_or_focus_browser_action_tool_requests(context)
    if app_browser_action_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_browser_action_sequence
    ):
        return app_browser_action_sequence
    app_direct_search_sequence = _app_direct_search_type_tool_requests(context)
    if app_direct_search_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_direct_search_sequence
    ):
        return app_direct_search_sequence
    desktop_path_request = _desktop_path_tool_request(context)
    if desktop_path_request and str(desktop_path_request.get("tool") or "") in allowed:
        return [desktop_path_request]
    foreground_click_search_type_sequence = _foreground_click_search_type_tool_requests(context)
    if foreground_click_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_click_search_type_sequence):
        return foreground_click_search_type_sequence
    app_scoped_search_type_sequence = _app_scoped_search_type_tool_requests(context)
    if app_scoped_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in app_scoped_search_type_sequence):
        return app_scoped_search_type_sequence
    app_search_type_sequence = _app_open_or_focus_search_type_tool_requests(context)
    if app_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in app_search_type_sequence):
        return app_search_type_sequence
    shortcut_type_sequence = _app_open_or_focus_shortcut_type_tool_requests(context)
    if shortcut_type_sequence and all(str(request.get("tool") or "") in allowed for request in shortcut_type_sequence):
        return shortcut_type_sequence
    shortcut_sequence = _app_open_or_focus_safe_shortcut_sequence_tool_requests(context)
    if shortcut_sequence and all(str(request.get("tool") or "") in allowed for request in shortcut_sequence):
        return shortcut_sequence
    foreground_shortcut_sequence = _foreground_safe_shortcut_sequence_tool_requests(context)
    if foreground_shortcut_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_shortcut_sequence):
        return foreground_shortcut_sequence
    app_shortcut = _app_scoped_safe_shortcut_tool_request(context)
    if app_shortcut and str(app_shortcut.get("tool") or "") in allowed:
        return [app_shortcut]
    app_preposed_observe_sequence = _app_preposed_observe_tool_requests(context)
    if app_preposed_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_preposed_observe_sequence):
        return app_preposed_observe_sequence
    app_observe_sequence = _app_open_or_focus_observe_tool_requests(context)
    if app_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_observe_sequence):
        return app_observe_sequence
    app_prefix_observe_sequence = _app_prefix_observe_tool_requests(context)
    if app_prefix_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_prefix_observe_sequence):
        return app_prefix_observe_sequence
    app_ui_elements = _app_scoped_ui_elements_tool_requests(context)
    if app_ui_elements and all(str(request.get("tool") or "") in allowed for request in app_ui_elements):
        return app_ui_elements
    click_type_sequence = _app_open_or_focus_click_type_tool_requests(context)
    if click_type_sequence and all(str(request.get("tool") or "") in allowed for request in click_type_sequence):
        return click_type_sequence
    app_screen_capture_sequence = _app_open_or_focus_screen_capture_tool_requests(context)
    if app_screen_capture_sequence and all(str(request.get("tool") or "") in allowed for request in app_screen_capture_sequence):
        return app_screen_capture_sequence
    foreground_search_type_sequence = _foreground_search_type_tool_requests(context)
    if foreground_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_search_type_sequence):
        return foreground_search_type_sequence
    sequence = daily_desktop_intent_sequence_candidates(context)
    if sequence and all(str(request.get("tool") or "") in allowed for request in sequence):
        return sequence
    app_find_sequence = _app_open_or_focus_find_text_tool_requests(context)
    if app_find_sequence and all(str(request.get("tool") or "") in allowed for request in app_find_sequence):
        return app_find_sequence
    app_safe_key = _app_prefix_safe_key_tool_request(context)
    if app_safe_key and str(app_safe_key.get("tool") or "") in allowed:
        return [app_safe_key]
    app_open_or_focus_safe_key = _app_open_or_focus_safe_key_tool_request(context)
    if app_open_or_focus_safe_key and str(app_open_or_focus_safe_key.get("tool") or "") in allowed:
        return [app_open_or_focus_safe_key]
    app_safe_click = _app_prefix_safe_click_tool_request(context)
    if app_safe_click and str(app_safe_click.get("tool") or "") in allowed:
        return [app_safe_click]
    app_safe_type_text = _app_prefix_safe_type_text_tool_request(context)
    if app_safe_type_text and str(app_safe_type_text.get("tool") or "") in allowed:
        return [app_safe_type_text]
    app_window_management = _app_prefix_window_management_tool_request(context)
    if app_window_management and str(app_window_management.get("tool") or "") in allowed:
        return [app_window_management]
    app_ui_action = _app_scoped_ui_action_tool_request(context)
    if app_ui_action and str(app_ui_action.get("tool") or "") in allowed:
        return [app_ui_action]
    for request in daily_desktop_intent_candidates(context):
        if str(request.get("tool") or "") in allowed:
            return [request]
    return []


def daily_desktop_entrypoint_tool_requests(
    context: str,
    allowed_tools: list[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic desktop requests for Chat/Bubble/Live2D entrypoints."""

    direct_request = daily_desktop_metadata_tool_request(metadata, allowed_tools)
    if direct_request:
        return [direct_request]
    planning_context = daily_desktop_recovery_prompt(metadata) or context
    return daily_desktop_intent_tool_requests(planning_context, allowed_tools)


def daily_desktop_intent_sequence_candidates(context: str) -> list[dict[str, Any]]:
    """Return ordered foreground desktop tool requests for explicit multi-step intents."""

    text = _clean_text(context)
    if (
        not text
        or _looks_like_negative_request(text)
        or _is_desktop_permissions_request(text)
        or _looks_like_explanation_request(text)
    ):
        return []
    clauses = _split_daily_desktop_sequence(text)
    if len(clauses) < 2:
        return []
    requests: list[dict[str, Any]] = []
    for clause in clauses[:5]:
        stripped_clause = _strip_sequence_clause_prefix(clause)
        handled_input_followup, input_followup_requests = _typed_input_followup_requests(
            stripped_clause,
            requests,
        )
        if handled_input_followup:
            requests.extend(input_followup_requests)
            continue
        search_type_requests = (
            _app_direct_search_type_tool_requests(stripped_clause)
            or _app_scoped_search_type_tool_requests(stripped_clause)
            or _app_open_or_focus_search_type_tool_requests(stripped_clause)
            or _foreground_search_type_tool_requests(stripped_clause)
        )
        if search_type_requests:
            requests.extend(search_type_requests)
            continue
        request = _first_daily_desktop_candidate(stripped_clause)
        if request is None:
            find_requests = _app_context_find_text_requests(stripped_clause, requests)
            if find_requests:
                requests.extend(find_requests)
                continue
            click_requests = _app_context_click_ui_element_requests(stripped_clause, requests)
            if not click_requests:
                return []
            requests.extend(click_requests)
            continue
        requests.append(request)
    if len(requests) < 2:
        return []
    requests = _coalesce_app_foreground_sequence(requests)
    if not requests:
        return []
    if not _is_foreground_desktop_sequence(requests):
        return []
    return requests


_DIRECT_DAILY_DESKTOP_METADATA_TOOLS = {
    "app.focus",
    "app.focus_window",
    "app.focus_and_safe_shortcut",
    "app.focus_and_safe_key",
    "app.focus_and_hotkey",
    "app.focus_and_safe_scroll",
    "app.focus_and_safe_click",
    "app.focus_and_click_ui_element",
    "app.focus_and_type_into_ui_element",
    "app.focus_and_safe_type_text",
    "app.hide",
    "app.minimize",
    "app.open",
    "app.open_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.open_and_hotkey",
    "app.open_and_safe_scroll",
    "app.open_and_safe_click",
    "app.open_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.open_and_safe_type_text",
    "app.quit",
    "app.show",
    "app.status",
    "browser.current_page",
    "browser.click",
    "browser.extract_text",
    "browser.open_url",
    "browser.open_url_and_extract_text",
    "browser.open_url_and_screenshot",
    "browser.screenshot",
    "browser.type_text",
    "calendar.create_event",
    "clipboard.write",
    "clipboard.read",
    "notes.create",
    "desktop.active_window",
    "desktop.click",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.close_window",
    "desktop.hide_app",
    "desktop.hotkey",
    "desktop.minimize_window",
    "desktop.open_path",
    "desktop.permissions",
    "desktop.reveal_path",
    "desktop.running_apps",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.submit_foreground",
    "desktop.type_text",
    "desktop.ui_elements",
    "desktop.windows",
    "media.apple_music_control",
    "media.apple_music_open_and_play",
    "media.apple_music_play",
    "notes.create",
    "reminders.create",
    "screen.capture",
    "system.volume",
}

_BROWSER_SEARCH_INPUT_SELECTOR = (
    'input[type="search"], input[name="q"], textarea[name="q"], '
    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
    'input[aria-label*="search" i], input[placeholder*="search" i]'
)

_BROWSER_TEXT_INPUT_SELECTOR = (
    'input:not([type]), input[type="text"], input[type="search"], '
    'textarea, [contenteditable="true"]'
)

_FOREGROUND_SEQUENCE_TOOLS = {
    "app.open",
    "app.focus",
    "app.show",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.focus_and_safe_key",
    "app.open_and_hotkey",
    "app.focus_and_hotkey",
    "app.open_and_safe_scroll",
    "app.focus_and_safe_scroll",
    "app.open_and_safe_click",
    "app.focus_and_safe_click",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.focus_and_type_into_ui_element",
    "desktop.hide_app",
    "desktop.minimize_window",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.click",
    "desktop.close_window",
    "desktop.hotkey",
    "desktop.submit_foreground",
    "desktop.type_text",
    "screen.capture",
}

_APP_SEQUENCE_CONTEXT_TOOLS = {
    "app.open",
    "app.focus",
    "app.show",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.focus_and_safe_key",
    "app.open_and_hotkey",
    "app.focus_and_hotkey",
    "app.open_and_safe_scroll",
    "app.focus_and_safe_scroll",
    "app.open_and_safe_click",
    "app.focus_and_safe_click",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.focus_and_type_into_ui_element",
}

_FOREGROUND_ACTION_TOOLS = {
    "desktop.click",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.close_window",
    "desktop.hotkey",
    "desktop.submit_foreground",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.type_text",
}


def daily_desktop_metadata_tool_request(
    metadata: Mapping[str, Any] | None,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return an exact daily desktop request carried by trusted UI metadata."""

    if not isinstance(metadata, Mapping):
        return None
    if metadata.get("desktop_permission_recovery") is not True:
        return None

    if metadata.get("desktop_permission_retry") is True or metadata.get("recovery_action_kind") == "retry_original":
        tool_name = str(metadata.get("recovery_tool") or metadata.get("recovery_retry_tool") or "").strip()
        raw_input = metadata.get("recovery_input")
        if not isinstance(raw_input, Mapping):
            raw_input = metadata.get("recovery_retry_input")
    else:
        if str(metadata.get("recovery_risk_level") or "").strip().lower() != "low":
            return None
        tool_name = str(metadata.get("recovery_tool") or "").strip()
        raw_input = metadata.get("recovery_input")

    if not tool_name or tool_name not in _DIRECT_DAILY_DESKTOP_METADATA_TOOLS:
        return None
    if allowed_tools is not None:
        allowed = {str(tool or "").strip() for tool in allowed_tools}
        if tool_name not in allowed:
            return None
    if not isinstance(raw_input, Mapping):
        return None
    return {
        **_request(tool_name, dict(raw_input)),
        "source": "daily_desktop_metadata",
        "planning_reason": "structured_recovery_metadata",
    }


def daily_desktop_recovery_prompt(metadata: Mapping[str, Any] | None) -> str:
    """Build a deterministic low-risk prompt from a structured recovery action."""

    if not isinstance(metadata, Mapping):
        return ""
    if metadata.get("desktop_permission_recovery") is not True:
        return ""
    if str(metadata.get("recovery_risk_level") or "").strip().lower() != "low":
        return ""
    if str(metadata.get("recovery_tool") or "").strip() != "app.open":
        return ""
    recovery_input = metadata.get("recovery_input")
    if not isinstance(recovery_input, Mapping):
        return ""
    app_name = str(recovery_input.get("app_name") or "").strip()
    if not app_name:
        return ""
    return f"打开{app_name}"


def _split_daily_desktop_sequence(text: str) -> list[str]:
    coordinate_comma = "__YACHIYO_COORD_COMMA__"
    protected_text = re.sub(
        r"(?P<x>\d+(?:\.\d+)?)\s*[,，]\s*(?P<y>\d+(?:\.\d+)?)",
        lambda match: f"{match.group('x')}{coordinate_comma}{match.group('y')}",
        str(text or "").strip(),
    )
    parts = re.split(
        r"(?:[，,；;。]\s*|\s+(?:and then|then)\s+|"
        r"\s+and\s+(?=(?:press|type|enter|click|scroll|send|submit|confirm|"
        r"paste|copy|search|find|look\s+up)\b)|"
        r"(?:然后|接着|之后|随后|并且|并)\s*)",
        protected_text,
        flags=re.IGNORECASE,
    )
    return [
        _strip_query(part.replace(coordinate_comma, ", "))
        for part in parts
        if _strip_query(part.replace(coordinate_comma, ", "))
    ]


def _strip_sequence_clause_prefix(text: str) -> str:
    return re.sub(
        r"^(?:再|然后|接着|之后|随后|并且|并|and then|then)\s*",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _first_daily_desktop_candidate(text: str) -> dict[str, Any] | None:
    app_shortcut = _app_scoped_safe_shortcut_tool_request(text)
    if app_shortcut and str(app_shortcut.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_shortcut
    app_safe_key = _app_prefix_safe_key_tool_request(text)
    if app_safe_key and str(app_safe_key.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_key
    app_open_or_focus_safe_key = _app_open_or_focus_safe_key_tool_request(text)
    if (
        app_open_or_focus_safe_key
        and str(app_open_or_focus_safe_key.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS
    ):
        return app_open_or_focus_safe_key
    app_safe_click = _app_prefix_safe_click_tool_request(text)
    if app_safe_click and str(app_safe_click.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_click
    app_safe_type_text = _app_prefix_safe_type_text_tool_request(text)
    if app_safe_type_text and str(app_safe_type_text.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_type_text
    app_ui_action = _app_scoped_ui_action_tool_request(text)
    if app_ui_action and str(app_ui_action.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_ui_action
    for request in daily_desktop_intent_candidates(text):
        tool = str(request.get("tool") or "")
        if tool in _FOREGROUND_SEQUENCE_TOOLS:
            return request
    return None


def _desktop_path_tool_request(text: str) -> dict[str, Any] | None:
    open_path = _desktop_open_path(text)
    if open_path:
        return _request("desktop.open_path", {"path": open_path})
    reveal_path = _desktop_reveal_path(text)
    if reveal_path:
        return _request("desktop.reveal_path", {"path": reveal_path})
    return None


def _browser_open_url_tool_request(text: str, allowed: set[str]) -> dict[str, Any] | None:
    if _looks_like_explanation_request(text):
        return None
    browser_summary_request = _is_browser_summary_request(text)
    open_extract_payload = _browser_open_url_and_extract_text_request(text)
    if open_extract_payload and "browser.open_url_and_extract_text" in allowed:
        return _request(
            "browser.open_url_and_extract_text",
            open_extract_payload,
            presentation="summary" if browser_summary_request else "",
        )
    open_screenshot_payload = _browser_open_url_and_screenshot_request(text)
    if open_screenshot_payload and "browser.open_url_and_screenshot" in allowed:
        return _request("browser.open_url_and_screenshot", open_screenshot_payload)
    browser_open_target_url = _browser_open_target_url(text)
    if browser_open_target_url and "browser.open_url" in allowed:
        return _request("browser.open_url", {"url": browser_open_target_url})
    return None


def _coalesce_app_foreground_sequence(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coalesced: list[dict[str, Any]] = []
    index = 0
    while index < len(requests):
        current = requests[index]
        next_request = requests[index + 1] if index + 1 < len(requests) else None
        composite = _app_foreground_sequence_composite(current, next_request)
        if composite:
            coalesced.append(composite)
            index += 2
            continue
        coalesced.append(current)
        index += 1
    return coalesced


def _app_foreground_sequence_composite(
    app_request: dict[str, Any],
    action_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not action_request:
        return None
    app_tool = str(app_request.get("tool") or "")
    if app_tool not in {"app.open", "app.focus"}:
        return None
    action_tool = str(action_request.get("tool") or "")
    app_input = app_request.get("input") if isinstance(app_request.get("input"), dict) else {}
    action_input = action_request.get("input") if isinstance(action_request.get("input"), dict) else {}
    app_name = str(app_input.get("app_name") or "").strip()
    if not app_name:
        return None
    mode = "open" if app_tool == "app.open" else "focus"
    if action_tool == "desktop.safe_type_text":
        text = str(action_input.get("text") or "").strip()
        if text:
            return _request(
                f"app.{mode}_and_safe_type_text",
                {"app_name": app_name, "text": text},
            )
    if action_tool == "desktop.safe_shortcut":
        action = str(action_input.get("action") or "").strip()
        if action:
            return _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": action},
            )
    if action_tool == "desktop.safe_key":
        action = str(action_input.get("action") or "").strip()
        repeat_count = action_input.get("repeat_count", 1)
        if action:
            return _request(
                f"app.{mode}_and_safe_key",
                {"app_name": app_name, "action": action, "repeat_count": repeat_count},
            )
    if action_tool == "desktop.hotkey":
        key = str(action_input.get("key") or "").strip()
        modifiers = action_input.get("modifiers")
        if key:
            return _request(
                f"app.{mode}_and_hotkey",
                {
                    "app_name": app_name,
                    "key": key,
                    "modifiers": modifiers if isinstance(modifiers, list) else [],
                },
            )
    if action_tool == "desktop.safe_scroll":
        direction = str(action_input.get("direction") or "").strip()
        pages = action_input.get("pages", 1)
        if direction:
            return _request(
                f"app.{mode}_and_safe_scroll",
                {"app_name": app_name, "direction": direction, "pages": pages},
            )
    if action_tool == "desktop.safe_click":
        if action_input.get("x") is not None and action_input.get("y") is not None:
            return _request(
                f"app.{mode}_and_safe_click",
                {"app_name": app_name, "x": action_input.get("x"), "y": action_input.get("y")},
            )
    if action_tool == "desktop.click_ui_element":
        target = str(action_input.get("target") or "").strip()
        if target:
            return _request(
                f"app.{mode}_and_click_ui_element",
                {
                    "app_name": app_name,
                    "target": target,
                    "role_filter": action_input.get("role_filter", ""),
                    "limit": action_input.get("limit", 80),
                    "click_count": action_input.get("click_count", 1),
                },
            )
    if action_tool == "desktop.type_into_ui_element":
        target = str(action_input.get("target") or "").strip()
        text = str(action_input.get("text") or "").strip()
        if target and text:
            return _request(
                f"app.{mode}_and_type_into_ui_element",
                {
                    "app_name": app_name,
                    "target": target,
                    "text": text,
                    "role_filter": action_input.get("role_filter", ""),
                    "limit": action_input.get("limit", 80),
                },
            )
    return None


def _is_foreground_desktop_sequence(requests: list[dict[str, Any]]) -> bool:
    tools = [str(request.get("tool") or "") for request in requests]
    if not tools or any(tool not in _FOREGROUND_SEQUENCE_TOOLS for tool in tools):
        return False
    if tools[0] == "screen.capture":
        return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools[1:])
    if tools[0] in _APP_SEQUENCE_CONTEXT_TOOLS:
        return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools[1:])
    return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools)


def _app_context_find_text_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _latest_sequence_app_context_is_browser(previous_requests):
        return []
    if not _latest_sequence_app_context_name(previous_requests):
        return []
    query = _desktop_find_query(text)
    if not query:
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "find"}),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _app_context_click_ui_element_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _latest_sequence_app_context_name(previous_requests):
        return []
    click_payload = _desktop_click_ui_element(text, require_context=False)
    if not click_payload:
        return []
    return [_request("desktop.click_ui_element", click_payload)]


def _typed_input_followup_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    search_text_request = _latest_sequence_search_text_request(previous_requests)
    if search_text_request is not None and _is_input_return_followup(
        text,
        {"input": {"target": "搜索"}},
    ):
        return True, [_request("desktop.search_submit", {})]
    input_request = _latest_sequence_typed_input_request(previous_requests)
    if input_request is None:
        return False, []
    if _is_input_return_followup(text, input_request):
        if _typed_input_request_targets_search(input_request):
            return True, [_request("desktop.search_submit", {})]
        return True, [_request("desktop.hotkey", {"key": "return", "modifiers": []})]
    submit_action = _external_submit_followup_action(text)
    if submit_action:
        return True, [_request("desktop.submit_foreground", {"action": submit_action})]
    return False, []


def _latest_sequence_typed_input_request(
    requests: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for request in reversed(requests):
        tool = str(request.get("tool") or "").strip()
        if tool in {
            "desktop.type_into_ui_element",
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
        }:
            return request
        if tool not in {"app.open", "app.focus"}:
            break
    return None


def _latest_sequence_search_text_request(
    requests: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(requests) < 2:
        return None
    text_request = requests[-1]
    text_tool = str(text_request.get("tool") or "").strip()
    if text_tool != "desktop.safe_type_text":
        return None
    shortcut_request = requests[-2]
    shortcut_tool = str(shortcut_request.get("tool") or "").strip()
    if shortcut_tool not in {
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    }:
        return None
    shortcut_input = (
        shortcut_request.get("input") if isinstance(shortcut_request.get("input"), dict) else {}
    )
    if str(shortcut_input.get("action") or "").strip() != "find":
        return None
    return text_request


def _typed_input_request_targets_search(input_request: dict[str, Any]) -> bool:
    payload = input_request.get("input") if isinstance(input_request.get("input"), dict) else {}
    target = str(payload.get("target") or "").strip()
    return bool(
        re.search(
            r"(?:搜索|查找|检索|search|find|query)",
            target,
            flags=re.IGNORECASE,
        )
    )


def _is_input_return_followup(text: str, input_request: dict[str, Any]) -> bool:
    hotkey = _desktop_hotkey(text)
    if hotkey == {"key": "return", "modifiers": []}:
        return True
    phrase = _normalize_named_hotkey_phrase(text)
    if phrase in {"确认", "确定", "回车", "enter", "return"}:
        return True
    if phrase not in {"搜索", "查找", "检索", "访问", "打开", "search", "find", "go", "visit", "open"}:
        return False
    payload = input_request.get("input") if isinstance(input_request.get("input"), dict) else {}
    target = str(payload.get("target") or "").strip().lower()
    return bool(
        re.search(
            r"(?:搜索|查找|检索|地址|网址|url|search|find|query|address)",
            target,
            flags=re.IGNORECASE,
        )
    )


def _external_submit_followup_action(text: str) -> str:
    return _submit_foreground_action_for_phrase(_normalize_submit_foreground_phrase(text))


def _desktop_submit_foreground_action(text: str) -> str:
    return _submit_foreground_action_for_phrase(_normalize_submit_foreground_phrase(text))


def _normalize_submit_foreground_phrase(text: str) -> str:
    phrase = _strip_query(text)
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[\s._-]+", "", phrase.lower())


def _submit_foreground_action_for_phrase(phrase: str) -> str:
    return_key_action = _submit_foreground_action_from_return_key_phrase(phrase)
    if return_key_action:
        return return_key_action
    if phrase in {
        "发送",
        "发出",
        "发送当前内容",
        "发送当前输入",
        "发送当前文本",
        "发送当前消息",
        "发送消息",
        "把消息发出",
        "当前内容发送",
        "当前输入发送",
        "当前文本发送",
        "当前消息发送",
        "消息发送",
        "确认发送",
        "send",
        "sendcurrentcontent",
        "sendthecurrentcontent",
        "sendcurrentinput",
        "sendcurrenttext",
        "sendmessage",
        "sendcurrentmessage",
        "sendthecurrentmessage",
        "sendcurrentchatmessage",
        "post",
    }:
        return "send"
    if phrase in {
        "提交",
        "提交当前内容",
        "提交当前输入",
        "提交当前文本",
        "提交当前表单",
        "提交表单",
        "当前内容提交",
        "当前输入提交",
        "当前文本提交",
        "当前表单提交",
        "表单提交",
        "submit",
        "submitcurrentcontent",
        "submitthecurrentcontent",
        "submitcurrentinput",
        "submitcurrenttext",
        "submitcurrentform",
        "submitthecurrentform",
        "submitform",
    }:
        return "submit"
    if phrase in {
        "确认当前内容",
        "确认当前输入",
        "确认当前文本",
        "确认当前对话框",
        "确认当前弹窗",
        "确认当前操作",
        "确认操作",
        "确认",
        "确定",
        "confirm",
        "confirmcurrentcontent",
        "confirmthecurrentcontent",
        "confirmcurrentinput",
        "confirmcurrenttext",
        "confirmcurrentdialog",
        "confirmthecurrentdialog",
    }:
        return "confirm"
    return ""


def _submit_foreground_action_from_return_key_phrase(phrase: str) -> str:
    return_key = r"(?:按|按下|敲|敲下)?(?:一下|下)?(?:回车|enter|return)(?:键)?"
    english_prefix = r"(?:press|hit)(?:enter|return)to"
    if re.fullmatch(rf"(?:{return_key})(?:发送|发出)", phrase) or re.fullmatch(
        rf"{english_prefix}(?:send|post)",
        phrase,
    ):
        return "send"
    if re.fullmatch(rf"(?:{return_key})(?:提交)", phrase) or re.fullmatch(
        rf"{english_prefix}submit",
        phrase,
    ):
        return "submit"
    if re.fullmatch(rf"(?:{return_key})(?:确认|确定)", phrase) or re.fullmatch(
        rf"{english_prefix}(?:confirm|ok)",
        phrase,
    ):
        return "confirm"
    return ""


def _latest_sequence_app_context_is_browser(requests: list[dict[str, Any]]) -> bool:
    app_name = _latest_sequence_app_context_name(requests)
    return bool(app_name and app_name in _BROWSER_APP_NAMES)


def _latest_sequence_app_context_name(requests: list[dict[str, Any]]) -> str:
    for request in reversed(requests):
        tool = str(request.get("tool") or "").strip()
        if tool not in _APP_SEQUENCE_CONTEXT_TOOLS:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if app_name:
            return app_name
    return ""


def _desktop_find_query(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在(?:当前|前台)?(?:窗口|应用|app)?(?:里|中|内|上)?\s*)?"
        r"(?:搜索|搜一下|搜|查找|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:find|search)\s+(?:for\s+)?(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.group("query"))
        if query:
            return query
    return ""


def daily_desktop_intent_candidates(context: str) -> list[dict[str, Any]]:
    """Return ordered desktop tool candidates before policy filtering."""

    text = _clean_text(context)
    if not text or _looks_like_negative_request(text):
        return []

    candidates: list[dict[str, Any]] = []
    if _is_desktop_permissions_request(text):
        candidates.append(_request("desktop.permissions", {}))
        return candidates

    if _looks_like_explanation_request(text):
        return []

    if _looks_like_project_or_design_request(text):
        return []

    app_foreground_payload = _app_open_or_focus_foreground_action_request(text)
    if app_foreground_payload:
        candidates.append(
            _request(
                str(app_foreground_payload["tool"]),
                dict(app_foreground_payload["input"]),
            )
        )

    app_prefix_safe_scroll = _app_prefix_safe_scroll_tool_request(text)
    if app_prefix_safe_scroll:
        candidates.append(app_prefix_safe_scroll)

    app_prefix_safe_key = _app_prefix_safe_key_tool_request(text)
    if app_prefix_safe_key:
        candidates.append(app_prefix_safe_key)

    app_prefix_safe_click = _app_prefix_safe_click_tool_request(text)
    if app_prefix_safe_click:
        candidates.append(app_prefix_safe_click)

    app_prefix_safe_type_text = _app_prefix_safe_type_text_tool_request(text)
    if app_prefix_safe_type_text:
        candidates.append(app_prefix_safe_type_text)

    app_prefix_window_management = _app_prefix_window_management_tool_request(text)
    if app_prefix_window_management:
        candidates.append(app_prefix_window_management)

    safe_shortcut_action = _desktop_safe_shortcut_action(text)
    if safe_shortcut_action:
        candidates.append(_request("desktop.safe_shortcut", {"action": safe_shortcut_action}))

    safe_scroll = _desktop_safe_scroll(text)
    if safe_scroll:
        candidates.append(_request("desktop.safe_scroll", safe_scroll))

    safe_key = _desktop_safe_key(text)
    if safe_key:
        candidates.append(_request("desktop.safe_key", safe_key))

    browser_summary_request = _is_browser_summary_request(text)
    open_extract_payload = _browser_open_url_and_extract_text_request(text)
    if open_extract_payload:
        candidates.append(
            _request(
                "browser.open_url_and_extract_text",
                open_extract_payload,
                presentation="summary" if browser_summary_request else "",
            )
        )

    open_screenshot_payload = _browser_open_url_and_screenshot_request(text)
    if open_screenshot_payload:
        candidates.append(_request("browser.open_url_and_screenshot", open_screenshot_payload))

    browser_open_target_url = _browser_open_target_url(text)
    if browser_open_target_url:
        candidates.append(_request("browser.open_url", {"url": browser_open_target_url}))

    if _is_browser_extract_text_request(text) and not browser_open_target_url:
        candidates.append(
            _request(
                "browser.extract_text",
                {},
                presentation="summary" if browser_summary_request else "",
            )
        )

    if _is_browser_screenshot_request(text) and not browser_open_target_url:
        candidates.append(
            _request("browser.screenshot", {"reason": "user asked to capture the browser page"})
        )

    browser_click_payload = _browser_click_request(text)
    if browser_click_payload:
        candidates.append(_request("browser.click", browser_click_payload))

    browser_type_text_payload = _browser_type_text_request(text)
    if browser_type_text_payload:
        candidates.append(_request("browser.type_text", browser_type_text_payload))

    if _is_browser_current_page_request(text):
        candidates.append(_request("browser.current_page", {}))

    volume_payload = _system_volume_request(text)
    if volume_payload is not None:
        candidates.append(_request("system.volume", volume_payload))

    if _clipboard_read_request(text):
        candidates.append(_request("clipboard.read", {}))

    clipboard_text = _clipboard_write_text(text)
    if clipboard_text:
        candidates.append(_request("clipboard.write", {"text": clipboard_text}))

    schedule_create = _schedule_create_tool_request(text)
    if schedule_create:
        candidates.append(schedule_create)

    notes_create = _notes_create_tool_request(text)
    if notes_create:
        candidates.append(notes_create)

    if _is_running_apps_request(text):
        candidates.append(_request("desktop.running_apps", {}))

    ui_elements_payload = _desktop_ui_elements_request(text)
    if ui_elements_payload is not None:
        candidates.append(_request("desktop.ui_elements", ui_elements_payload))

    windows_payload = _desktop_windows_request(text)
    if windows_payload is not None:
        candidates.append(_request("desktop.windows", windows_payload))

    open_path = _desktop_open_path(text)
    if open_path:
        candidates.append(_request("desktop.open_path", {"path": open_path}))

    reveal_path = _desktop_reveal_path(text)
    if reveal_path:
        candidates.append(_request("desktop.reveal_path", {"path": reveal_path}))

    app_status_name = _app_status_name(text)
    if app_status_name:
        candidates.append(_request("app.status", {"app_name": app_status_name}))

    app_show_or_open_name = _app_show_or_open_name(text)
    if app_show_or_open_name:
        candidates.append(_request("app.show", {"app_name": app_show_or_open_name}))

    focus_window_payload = _app_focus_window_payload(text)
    if focus_window_payload:
        candidates.append(_request("app.focus_window", focus_window_payload))

    app_quit_name = _app_quit_name(text)
    if app_quit_name:
        candidates.append(_request("app.quit", {"app_name": app_quit_name}))

    app_show_name = _app_show_name(text)
    if app_show_name:
        candidates.append(_request("app.show", {"app_name": app_show_name}))

    app_hide_name = _app_hide_name(text)
    if app_hide_name:
        candidates.append(_request("app.hide", {"app_name": app_hide_name}))

    app_minimize_name = _app_minimize_name(text)
    if app_minimize_name:
        candidates.append(_request("app.minimize", {"app_name": app_minimize_name}))

    if _is_hide_current_app_request(text):
        candidates.append(_request("desktop.hide_app", {}))

    if _is_minimize_current_window_request(text):
        candidates.append(_request("desktop.minimize_window", {}))

    if _is_close_current_window_request(text):
        candidates.append(_request("desktop.close_window", {}))

    type_into_ui_element = _desktop_type_into_ui_element(text)
    if type_into_ui_element:
        candidates.append(_request("desktop.type_into_ui_element", type_into_ui_element))

    if not safe_shortcut_action and not _looks_like_app_status_request(text):
        search_url = _browser_search_url(text)
        if search_url:
            candidates.append(_request("browser.open_url", {"url": search_url}))

    if _is_apple_music_open_and_play_request(text):
        candidates.append(_request("media.apple_music_open_and_play", {}))

    music_control = _music_control_action(text)
    if music_control:
        candidates.append(_request("media.apple_music_control", {"action": music_control}))

    music = _music_query(text)
    if music:
        candidates.append(_request("media.apple_music_play", {"query": music}))

    terminal_run_payload = _terminal_run_payload(text)
    if terminal_run_payload:
        candidates.append(_request("terminal.run", terminal_run_payload))

    app_focus_name = _app_focus_name(text)
    if app_focus_name:
        candidates.append(_request("app.focus", {"app_name": app_focus_name}))

    app_name = _app_open_name(text)
    if app_name:
        candidates.append(_request("app.open", {"app_name": app_name}))

    safe_type_text = _desktop_safe_type_text(text)
    if safe_type_text:
        candidates.append(_request("desktop.safe_type_text", {"text": safe_type_text}))

    click_ui_element = _desktop_click_ui_element(text)
    if click_ui_element:
        candidates.append(_request("desktop.click_ui_element", click_ui_element))

    submit_action = _desktop_submit_foreground_action(text)
    if submit_action:
        candidates.append(_request("desktop.submit_foreground", {"action": submit_action}))

    hotkey = _desktop_hotkey(text)
    if hotkey:
        candidates.append(_request("desktop.hotkey", hotkey))

    type_text = _desktop_type_text(text)
    if type_text:
        candidates.append(_request("desktop.type_text", {"text": type_text}))

    safe_click = _desktop_safe_click(text)
    if safe_click:
        candidates.append(_request("desktop.safe_click", safe_click))

    click = _desktop_click(text)
    if click:
        candidates.append(_request("desktop.click", click))

    if _is_screen_capture_request(text) or (
        _is_visual_inspection_followup(text)
        and not _is_active_window_request(text)
        and not _is_bare_visual_inspection_request(text)
    ):
        candidates.append(_request("screen.capture", {"reason": "user asked to capture the screen"}))

    if _is_active_window_request(text):
        candidates.append(_request("desktop.active_window", {}))

    return candidates


def _request(tool: str, payload: dict[str, Any], *, presentation: str = "") -> dict[str, Any]:
    request = {"protocol": "json_fallback", "tool": tool, "input": payload}
    clean_presentation = str(presentation or "").strip()
    if clean_presentation:
        request["presentation"] = clean_presentation
    return request


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
            r"输入|打字|打|敲入|键入|点击|点|单击|双击|按键|快捷键|网页|"
            r"关闭|关掉|退出|隐藏|收起|最小化|切换|切到|切回|聚焦|激活|置前|显示|还原)",
            text,
        )
        or re.search(
            r"(?:不要|不用|无需|不需要|别)\s*(?:把|将)?[^。！？!?，,]{0,24}"
            r"(?:打开|启动|运行|拉起|开启|访问|浏览|前往|切换|切到|切回|聚焦|激活|置前|显示|还原)",
            text,
        )
        or re.search(
            r"(?:do not|don't|without|no need to).{0,24}"
            r"(?:execute|perform|call|play|capture|inspect|type|click|press|hotkey|"
            r"screenshot|read|close|quit|hide|minimi[sz]e|open|launch|start|visit|browse)",
            text.lower(),
        )
    )


def _is_desktop_permissions_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"(?:打开|启动|开启|拉起).{0,8}"
        r"(?:桌面权限|桌面执行权限|本地工具权限|需要的权限|缺少的权限|权限设置|权限页面)",
        text,
    ) or re.search(
        r"\b(?:open|launch|show)\s+(?:desktop|missing|required|permission|permissions)"
        r".{0,24}(?:settings|page|pane)\b",
        lowered,
    ):
        return False
    if re.search(
        r"(?:检查|诊断|查看|看看|确认).{0,12}"
        r"(?:桌面执行|本地工具|自动化|辅助功能|屏幕录制|权限).{0,12}"
        r"(?:权限|状态|问题)?",
        text,
    ):
        return True
    if re.search(
        r"(?:权限诊断|桌面权限|桌面执行权限|本地工具权限|自动化权限状态|辅助功能权限状态|"
        r"屏幕录制权限状态)",
        text,
    ):
        return True
    if re.search(
        r"(?:你|八千代|yachiyo)?\s*(?:需要|缺少|要)\s*(?:什么|哪些|哪个|啥).{0,12}权限",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:为什么|为何|为啥|怎么(?:回事)?).{0,24}"
        r"(?:不能|无法|没法|不会).{0,24}"
        r"(?:控制|操作|执行|打开|启动|播放|点击|输入|截图|截屏|读取窗口)",
        text,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:check|diagnose|inspect|read)\s+(?:desktop|macos|mac|automation|"
            r"accessibility|screen recording)\s+permissions?\b",
            lowered,
        )
        or re.search(
            r"\bwhy\s+can(?:not|'t)\s+(?:you|yachiyo|the agent).{0,40}"
            r"(?:control|operate|open apps?|launch apps?|play music|click|type|"
            r"capture the screen|read windows?)",
            lowered,
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
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<url>{url_token})\s*(?:打开|访问|浏览|前往|打开一下|访问一下|浏览一下)",
        rf"(?:open|visit|browse|go to)\s+(?P<url>{url_token})",
        rf"^(?P<url>{url_token})$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if _url_match_inside_local_path(text, match.start("url")):
            continue
        url = _normalize_url(match.group("url"))
        if url:
            return url
    return ""


def _browser_composite_open_url(text: str) -> str:
    browser_name = (
        r"(?:浏览器|chrome|google\s*chrome|谷歌(?:浏览器)?|safari|firefox|火狐(?:浏览器)?|"
        r"edge(?:浏览器)?|microsoft\s*edge|arc(?:浏览器)?|brave(?:浏览器)?|browser)"
    )
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?(?:打开|访问|浏览|前往|去)\s*(?P<target>[^。！？!?，,]+)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|用)?\s*{browser_name}\s*(?:里|中|内|上)?\s*"
        rf"(?:打开|访问|浏览|前往|去)\s*(?P<target>[^。！？!?，,]+)",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:open|visit|browse|go to)\s+(?P<target>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        url = _browser_target_url(match.group("target"))
        if url:
            return url
    return ""


def _browser_address_bar_url(text: str) -> str:
    browser_name = (
        r"(?:浏览器|chrome|google\s*chrome|谷歌(?:浏览器)?|safari|firefox|火狐(?:浏览器)?|"
        r"edge(?:浏览器)?|microsoft\s*edge|arc(?:浏览器)?|brave(?:浏览器)?|browser)"
    )
    patterns = (
        r"(?:press|hit)\s+(?:command|cmd|⌘)\s*\+?\s*l\s*(?:,?\s*(?:and\s+then|then|and))?\s*"
        r"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s*"
        r"(?:,?\s*(?:and\s+then|then|and))?\s*(?:press|hit)?\s*(?:enter|return)\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:按|敲|使用)\s*(?:command|cmd|⌘|Command|Cmd)\s*\+?\s*l\s*"
        r"(?:[，,；;。]?\s*(?:并|然后|后|之后|再)\s*)?"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)\s*"
        r"(?:[，,；;。]?\s*(?:并|然后|后|之后|再)?\s*(?:按)?(?:回车|enter|return))\s*$",
        r"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s+"
        r"(?:in|into)\s+(?:the\s+)?(?:address\s+bar|url\s+bar|omnibox)"
        r"(?:\s+(?:(?:and\s+then|then|and)\s*)?(?:(?:press|hit)\s*)?(?:enter|return))?\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在)?(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        r"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        r"\s*(?:到|进|在)\s*(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?"
        r"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s+"
        rf"(?:in|into)\s+(?:the\s+)?(?:address\s+bar|url\s+bar|omnibox)"
        rf"(?:\s+(?:and\s+)?(?:press|hit)\s+(?:enter|return))?\s*$",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:type|enter|input)\s+(?P<target>[^!?]+?)"
        rf"(?:\s+(?:and\s+)?(?:press|hit)\s+(?:enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:在)?(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"\s*(?:到|进|在)\s*(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?"
        rf"(?:\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|给|向)?\s*{browser_name}\s*(?:的|里|中|内|上)?\s*"
        rf"(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|给|向)\s*{browser_name}\s*(?:里|中|内|上)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_browser_address_bar_target(match.group("target"))
        url = _browser_address_bar_target_url(target)
        if url:
            return url
    return ""


def _strip_browser_address_bar_target(value: str) -> str:
    target = _strip_query(value)
    target = re.sub(
        r"\s+(?:(?:and\s+then|then|and)\s*)?(?:(?:press|hit)\s*)?(?:enter|return)\s*$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return)\s*$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"\s+(?:并|再|然后|and\s+then|then|and)$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    return _strip_query(target)


def _browser_address_bar_target_url(target: str) -> str:
    clean_target = _strip_browser_address_bar_target(target)
    if not clean_target:
        return ""
    url = _browser_target_url(clean_target)
    if url:
        return url
    return f"https://www.google.com/search?q={quote_plus(clean_target)}"


def _browser_open_target_url(text: str) -> str:
    return (
        _browser_composite_open_url(text)
        or _browser_address_bar_url(text)
        or _browser_open_url(text)
        or _browser_named_site_url(text)
    )


def _browser_open_url_and_extract_text_request(text: str) -> dict[str, str] | None:
    if not _is_browser_open_followup_extract_text_request(text):
        return None
    url = _browser_open_target_url(text)
    if not url:
        return None
    return {"url": url}


def _browser_open_url_and_screenshot_request(text: str) -> dict[str, str] | None:
    if not _is_browser_open_followup_screenshot_request(text):
        return None
    url = _browser_open_target_url(text)
    if not url:
        return None
    return {
        "url": url,
        "reason": "user asked to capture the browser page after opening a URL",
    }


def _is_browser_open_followup_extract_text_request(text: str) -> bool:
    if not _browser_open_target_url(text):
        return False
    lowered = text.lower()
    return bool(
        _is_browser_extract_text_request(text)
        or re.search(
            r"(?:并且|并|然后|之后|后|再)\s*"
            r"(?:读取|读一下|读下|读一读|提取|抓取|获取|总结|摘要|概括)"
            r"(?:一下|下|它|网页|页面|网站|正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:打开|访问|浏览|前往|去).{0,80}"
            r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|总结|摘要|概括)"
            r"(?:一下|下|它|网页|页面|网站|正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"\b(?:and|then)\s+(?:read|extract|get|summari[sz]e)"
            r"(?:\s+(?:the\s+)?(?:page|webpage|website|site|text|content))?\b",
            lowered,
        )
    )


def _is_browser_open_followup_screenshot_request(text: str) -> bool:
    if not _browser_open_target_url(text):
        return False
    lowered = text.lower()
    return bool(
        _is_browser_screenshot_request(text)
        or re.search(
            r"(?:打开|访问|浏览|前往|去).{0,80}"
            r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图|截取)",
            text,
        )
        or re.search(
            r"\b(?:open|visit|browse|go to)\b.{0,80}"
            r"(?:take\s+a\s+screenshot|screenshot|capture)",
            lowered,
        )
    )


def _browser_target_url(value: str) -> str:
    target = _strip_browser_followup(_strip_query(value))
    target = re.sub(r"^(?:一下|下|这个|那个)\s*", "", target)
    return (
        _normalize_url(target)
        or _normalize_site_name(target)
        or _normalize_browser_site_name(target)
    )


def _url_match_inside_local_path(text: str, start: int) -> bool:
    if start <= 0:
        return False
    previous = text[start - 1]
    return previous in {"/", "~", "."}


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


def _browser_named_site_url(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
        r"(?:打开|访问|浏览|前往|去)\s*(?P<site>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<site>[^。！？!?，,]+?)\s*(?:打开|访问|浏览|前往)"
        r"(?:一下|下)?(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:open|visit|browse|go to)\s+(?P<site>[^.!?]+)"
        r"\s+(?:in|with|using)\s+(?:browser|chrome|google|safari)",
        r"(?:open|visit|browse|go to)\s+(?P<site>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_site = match.group("site")
        site = _normalize_site_name(raw_site)
        if not site and _has_browser_open_context(text):
            site = _normalize_browser_site_name(raw_site)
        if site:
            return site
    return ""


def _normalize_site_name(value: str) -> str:
    site = _strip_polite_suffix(_strip_browser_followup(_strip_query(value)))
    site = re.sub(r"^(?:一下|下|这个|那个)\s*", "", site)
    site = re.sub(r"\s*(?:官网|官方网站|官方站|网页|网站|站点|site|website)$", "", site, flags=re.IGNORECASE)
    compact = re.sub(r"[\s._-]+", "", site.lower())
    aliases = {
        "google": "https://www.google.com",
        "谷歌": "https://www.google.com",
        "github": "https://github.com",
        "youtube": "https://www.youtube.com",
        "yt": "https://www.youtube.com",
        "youtubemusic": "https://music.youtube.com",
        "bilibili": "https://www.bilibili.com",
        "b站": "https://www.bilibili.com",
        "哔哩哔哩": "https://www.bilibili.com",
        "百度": "https://www.baidu.com",
        "baidu": "https://www.baidu.com",
        "gmail": "https://mail.google.com",
        "googledrive": "https://drive.google.com",
        "googledocs": "https://docs.google.com",
        "chatgpt": "https://chatgpt.com",
        "claude": "https://claude.ai",
        "perplexity": "https://www.perplexity.ai",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "reddit": "https://www.reddit.com",
        "xiaohongshu": "https://www.xiaohongshu.com",
        "小红书": "https://www.xiaohongshu.com",
        "rednote": "https://www.xiaohongshu.com",
        "weibo": "https://weibo.com",
        "微博": "https://weibo.com",
        "zhihu": "https://www.zhihu.com",
        "知乎": "https://www.zhihu.com",
        "douban": "https://www.douban.com",
        "豆瓣": "https://www.douban.com",
        "douyin": "https://www.douyin.com",
        "抖音": "https://www.douyin.com",
        "tiktok": "https://www.tiktok.com",
        "taobao": "https://www.taobao.com",
        "淘宝": "https://www.taobao.com",
        "jd": "https://www.jd.com",
        "jingdong": "https://www.jd.com",
        "京东": "https://www.jd.com",
    }
    return aliases.get(compact, "")


def _has_browser_open_context(text: str) -> bool:
    return bool(re.search(r"(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)", text, flags=re.IGNORECASE))


def _normalize_browser_site_name(value: str) -> str:
    site = _strip_polite_suffix(_strip_browser_followup(_strip_query(value)))
    site = re.sub(r"\s*(?:官网|官方网站|官方站|网页|网站|站点|site|website)$", "", site, flags=re.IGNORECASE)
    compact = re.sub(r"[\s._-]+", "", site.lower())
    aliases = {
        "applemusic": "https://music.apple.com",
        "music": "https://music.apple.com",
        "音乐": "https://music.apple.com",
    }
    return aliases.get(compact, "")


def _looks_like_search_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
            r"(?:搜索|搜一下|搜|查一下|查查|查(?!看)|检索|百度一下|谷歌一下|google\s+一下)\s*",
            text,
        )
        or re.search(r"^(?:search|google|look up)\b\s+", lowered)
    )


def _browser_search_url(text: str) -> str:
    if _looks_like_click_command(text) or _desktop_click_ui_element(text) or _desktop_type_into_ui_element(text):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<engine>百度|baidu)\s+(?P<query>[^。！？!?]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<engine>百度|baidu)\s*一下\s*(?P<query>[^。！？!?]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)\s*(?P<engine>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:搜索|搜一下|搜|查一下|查查|查(?!看)|检索|谷歌一下|google\s+一下)\s*(?P<query>[^。！？!?]+)",
        r"\b(?:search|google|look up)\b\s+(?:for\s+)?(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.group("query"))
        if query:
            engine = str(match.groupdict().get("engine") or "").strip().lower()
            if engine in {"百度", "baidu"}:
                return f"https://www.baidu.com/s?wd={quote_plus(query)}"
            return f"https://www.google.com/search?q={quote_plus(query)}"
    return ""


def _browser_search_then_click_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _browser_search_then_click(text)
    if not parsed:
        return []
    query, engine, index = parsed
    if engine in {"百度", "baidu"}:
        url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
    else:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    return [
        _request("browser.open_url", {"url": url}),
        _request(
            "browser.click",
            {"selector": f"search-result={index}", "click_count": 1},
        ),
    ]


def _browser_search_then_click(text: str) -> tuple[str, str, int] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<engine_baidu>百度|baidu)\s*一下\s*"
        r"(?P<query_baidu>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后)\s*"
        r"(?:点击|点一下|点按|单击|点|打开|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?P<rank_baidu>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启)\s*(?:浏览器|chrome|google\s*chrome|谷歌|谷歌浏览器|safari)\s*)?"
        r"(?:(?:用|在)\s*(?P<engine>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:搜索|搜一下|搜|查一下|查查|查(?!看)|检索|谷歌一下|google\s+一下)\s*"
        r"(?P<query>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后)\s*"
        r"(?:点击|点一下|点按|单击|点|打开|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)?$",
        r"^(?:please\s+)?(?:(?:open|launch|start)\s+(?:chrome|browser|safari)\s+(?:and\s+)?)?"
        r"(?:(?P<engine_en>google|search|look\s+up)\s+)"
        r"(?P<query_en>.+?)\s+(?:and|then)\s+"
        r"(?:open|click|visit)\s+(?:the\s+)?(?P<rank_en>first|1st)\s+(?:result|link)$",
    )
    for pattern in patterns:
        match = re.search(pattern, _clean_text(text), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(
            groups.get("query") or groups.get("query_baidu") or groups.get("query_en") or ""
        )
        if not query:
            continue
        engine = str(
            groups.get("engine") or groups.get("engine_baidu") or groups.get("engine_en") or ""
        ).strip().lower()
        rank = groups.get("rank") or groups.get("rank_baidu") or groups.get("rank_en") or ""
        index = _browser_search_result_rank_index(rank)
        if index:
            return query, engine, index
    return None


def _browser_search_result_rank_index(value: str) -> int:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    if compact in {"第一个", "第一条", "首个", "第1个", "第1条", "1", "first", "1st"}:
        return 1
    return 0


def _looks_like_click_command(text: str) -> bool:
    return bool(
        re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:双击)|点击|点一下|点按|单击|点|按一下|按)\s*\S+",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(r"^(?:double\s+click|click|press|tap)\s+\S+", text, flags=re.IGNORECASE)
    )


def _browser_click_request(text: str) -> dict[str, Any] | None:
    if not _has_browser_page_context(text):
        return None
    point = _browser_click_point(text)
    if point:
        return {
            "selector": f"point={point['x']},{point['y']}",
            "fallback_x": point["x"],
            "fallback_y": point["y"],
            "click_count": point["click_count"],
        }
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:点击|点一下|点按|单击|点)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?P<label>[^。！？!?，,]+?)\s*(?:按钮|链接|元素)?$",
        r"\b(?:click|press)\s+(?:the\s+)?(?P<label>[^.!?]+?)"
        r"(?:\s+(?:button|link|element))?"
        r"(?:\s+(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        label = _strip_browser_element_label(match.group("label"))
        if not label or _looks_like_click_coordinate_label(label):
            continue
        return {"selector": _browser_selector_from_label(label), "click_count": 1}
    return None


def _browser_click_point(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double2>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        return {
            "x": _number_value(match.group("x")),
            "y": _number_value(match.group("y")),
            "click_count": 2 if groups.get("double") or groups.get("double2") else 1,
        }
    return None


def _browser_type_text_request(text: str) -> dict[str, Any] | None:
    if not _has_browser_page_context(text):
        return None
    point = _browser_type_text_point(text)
    if point:
        return {
            "selector": f"point={point['x']},{point['y']}",
            "text": point["text"],
            "fallback_x": point["x"],
            "fallback_y": point["y"],
        }
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前)?(?:网页|页面|浏览器|当前页)"
        r"(?:上|里|中|内)?(?:的)?\s*(?P<target>[^。！？!?，,]*?)"
        r"(?:输入|填写|键入|打入|填入)\s*(?P<text>[^。！？!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:填写|填入|输入)\s*(?:当前)?(?:网页|页面|浏览器|当前页)?(?:的)?"
        r"(?P<target>[^。！？!?，,]+?)\s*(?:为|成|:|：)\s*(?P<text>[^。！？!?]+)$",
        r"\b(?:type|enter|fill)\s+(?P<text>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?P<target>[^.!?]+?)\s+"
        r"(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _strip_typed_text(match.group("text"))
        if not typed_text:
            continue
        target = _strip_browser_element_label(match.group("target"))
        return {
            "selector": _browser_input_selector_from_target(target),
            "text": typed_text,
        }
    return None


def _browser_type_text_point(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前)?(?:网页|页面|浏览器|当前页)"
        r"(?:上|里|中|内|的|上的)?\s*(?:坐标|位置|coordinate|point)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)\s*"
        r"(?:输入|填写|键入|打入|填入|type|enter|fill)\s*(?P<text>[^。！？!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:输入|填写|键入|打入|填入|type|enter|fill)\s*(?P<text>[^。！？!?]+?)\s*"
        r"(?:到|在|进|into|in)\s*(?:当前)?(?:网页|页面|浏览器|当前页)?"
        r"(?:上|里|中|内|的|上的)?\s*(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _strip_typed_text(match.group("text"))
        if not typed_text:
            continue
        return {
            "x": _number_value(match.group("x")),
            "y": _number_value(match.group("y")),
            "text": typed_text,
        }
    return None


def _has_browser_page_context(text: str) -> bool:
    return bool(
        re.search(r"(?:网页|页面|浏览器|当前页)", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:browser|page)\b", text, flags=re.IGNORECASE)
    )


def _strip_browser_element_label(value: str) -> str:
    label = _strip_query(value)
    label = re.sub(r"^(?:当前)?(?:网页|页面|浏览器|当前页)(?:上的|上|里|中|内|的)?\s*", "", label)
    label = re.sub(r"^(?:的|上的|上|里|中|内)\s*", "", label)
    label = re.sub(r"\s*(?:按钮|链接|元素|button|link|element|field|input|box)$", "", label, flags=re.IGNORECASE)
    return _strip_query(label)


def _looks_like_click_coordinate_label(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:,|，|\s)\s*\d+(?:\.\d+)?", str(value or "").strip()))


def _browser_selector_from_label(label: str) -> str:
    clean = str(label or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    return f"text={clean}"


def _browser_input_selector_from_target(target: str) -> str:
    clean = str(target or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    lowered = clean.lower()
    if re.search(r"(?:搜索|查找|search|query|q)", lowered):
        return _BROWSER_SEARCH_INPUT_SELECTOR
    if re.search(r"(?:密码|password)", lowered):
        return 'input[type="password"]'
    if re.search(r"(?:邮箱|邮件|email|e-mail)", lowered):
        return 'input[type="email"], input[name*="email" i], input[autocomplete="email"]'
    if re.search(r"(?:用户名|账号|账户|user|username|login)", lowered):
        return 'input[name*="user" i], input[autocomplete="username"], input[type="text"]'
    return _BROWSER_TEXT_INPUT_SELECTOR


def _looks_like_css_selector(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(
        stripped.startswith(("#", ".", "["))
        or re.match(r"^(?:button|a|input|textarea|select|form|div|span|\\*)\\b", stripped, flags=re.IGNORECASE)
    )


def _strip_search_query(value: str) -> str:
    query = _strip_query(value)
    query = re.sub(r"^(?:一下|这个|那个)\s*", "", query)
    query = re.sub(r"^下(?:\s+|$)", "", query)
    query = re.sub(
        r"\s*(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)(?:里|中|上|内)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:in|on|with|using)\s+(?:browser|chrome|google|safari)$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    return _strip_query(query)


def _is_browser_current_page_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"(?:刷新|重新加载|reload|refresh)", text, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:总结|摘要|概括|summari[sz]e|summary)", text, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:网页|网站|页面|页|浏览器|标签页).{0,8}"
            r"(?:是什么|是啥|哪个|地址|标题|url)?",
            text,
        )
        or re.search(
            r"(?:这是|这|当前打开的是).{0,4}(?:哪个|什么).{0,4}(?:网页|网站|页面|页|标签页)",
            text,
        )
        or re.search(
            r"(?:看一下|看看|看下|查看).{0,8}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)",
            text,
        )
        or "current page" in lowered
        or "current browser tab" in lowered
        or "active browser tab" in lowered
        or re.search(
            r"\b(?:what|which)\s+(?:page|site|website|tab)\s+(?:am\s+i|are\s+we)\s+on\b",
            lowered,
        )
        or re.search(
            r"\b(?:what|which)\s+(?:page|site|website|tab)\s+is\s+(?:open|active|current)\b",
            lowered,
        )
        or re.search(r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?current\s+(?:url|page|tab)\b", lowered)
    )


def _is_browser_extract_text_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页).{0,10}(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:看看|看一下|看下|查看).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:正文|文字|文本|内容)",
            text,
        )
        or re.search(
            r"(?:把|将)?\s*(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,8}(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取)"
            r"(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:总结|摘要|概括).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:总结|摘要|概括|讲了什么|说了什么|内容是什么)",
            text,
        )
        or "extract text from the current page" in lowered
        or "extract text from this page" in lowered
        or "read the current page" in lowered
        or "read current page" in lowered
        or "read current web page" in lowered
        or "read the current web page" in lowered
        or "read this page" in lowered
        or "read the page" in lowered
        or "summarize current page" in lowered
        or "summarize the current page" in lowered
        or "summarise current page" in lowered
        or "summarise the current page" in lowered
        or "summarize this page" in lowered
        or "summarise this page" in lowered
        or "what is this page about" in lowered
        or "what's this page about" in lowered
    )


def _is_browser_summary_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"(?:总结|摘要|概括|讲了什么|说了什么|内容是什么)", text)
        or re.search(r"\bsummari[sz]e\b", lowered)
        or "what is this page about" in lowered
        or "what's this page about" in lowered
    )


def _is_browser_screenshot_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台)?(?:网页|网站|页面|页|浏览器).{0,8}"
            r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图)",
            text,
        )
        or re.search(
            r"(?:截取|截图|截屏|截一下|截个图|截|抓屏).{0,8}(?:当前|现在|前台)?(?:网页|网站|页面|页|浏览器)",
            text,
        )
        or "browser screenshot" in lowered
        or "page screenshot" in lowered
        or "screenshot the current page" in lowered
        or "screenshot this page" in lowered
        or "screenshot the page" in lowered
        or re.search(r"\btake\s+(?:a\s+)?screenshot\s+of\s+(?:this|the|current)\s+page\b", lowered)
    )


def _system_volume_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    level_patterns = (
        r"(?:设置|设定)(?:系统)?(?:音量|声音)\s*(?:为|到|成)?\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:调到|调至|设为|设置为|设置到)\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:调到|调至|设为|设置为|设置到)\s*"
        r"百分之\s*(?P<level>\d{1,3})",
        r"(?:系统)?(?:音量|声音)\s*(?:设成|设到|调成)\s*(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:音量|声音)\s*(?P<level>\d{1,3})\s*%",
        r"\b(?:set|turn)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:to\s+)?"
        r"(?P<level>\d{1,3})\s*%?\b",
    )
    for pattern in level_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        level = _percentage_value(match.group("level"))
        if level is not None:
            return {"action": "set", "level": level}
    if re.search(r"(?:取消静音|解除静音|取消(?:系统)?静音|恢复声音)", text) or re.search(
        r"\bunmute(?:\s+(?:system\s+)?volume)?\b",
        lowered,
    ):
        return {"action": "unmute"}
    if re.search(r"(?:静音|设为静音|开启静音|关闭声音|把声音关掉|把音量关掉)", text) or re.search(
        r"\bmute(?:\s+(?:system\s+)?volume)?\b",
        lowered,
    ):
        return {"action": "mute"}
    if re.search(
        r"(?:调大|调高|加大|提高|增大|升高).{0,4}(?:音量|声音)|"
        r"(?:音量|声音).{0,4}(?:大一点|高一点|加一点|调大|调高|提高)",
        text,
    ) or re.search(
        r"\b(?:turn|raise|increase)\s+(?:up\s+)?(?:the\s+)?(?:system\s+)?volume\b|"
        r"\bvolume\s+up\b",
        lowered,
    ):
        return {"action": "up"}
    if re.search(
        r"(?:调小|调低|降低|减小|小声).{0,4}(?:音量|声音)|"
        r"(?:音量|声音).{0,4}(?:小一点|低一点|减一点|调小|调低|降低)",
        text,
    ) or re.search(
        r"\b(?:turn|lower|decrease)\s+(?:down\s+)?(?:the\s+)?(?:system\s+)?volume\b|"
        r"\bvolume\s+down\b",
        lowered,
    ):
        return {"action": "down"}
    if re.search(r"(?:当前|现在|系统)?(?:音量|声音).{0,6}(?:多少|是多少|状态)", text) or re.search(
        r"\b(?:current\s+)?(?:system\s+)?volume(?:\s+level|\s+status)?\??$",
        lowered,
    ):
        return {"action": "status"}
    return None


def _clipboard_write_text(text: str) -> str:
    patterns = (
        r"(?:把|将)?\s*(?:这段话|这段文字|这段文本|以下内容|下面内容|内容)?\s*"
        r"(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*(?P<text>.+)$",
        r"(?:复制|拷贝)(?:一下|下)?\s*(?:以下|下面)?(?:内容|这段话|这段文字|这段文本)?\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:写入|放入|放进|保存到)\s*(?:系统)?(?:剪贴板|粘贴板)\s+(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>.+?)\s*(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
        r"(?:复制|拷贝|写入)(?:一下|下)?\s*(?P<text>.+?)\s*(?:到|进|至)\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
        r"(?:系统)?(?:剪贴板|粘贴板)\s*(?:写入|放入|放进|保存|保存为)\s*(?P<text>.+)$",
        r"(?:复制|拷贝|写入)(?:到|进|至)?\s*(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*"
        r"(?P<text>.+)$",
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
    if _clipboard_write_text(text):
        return False
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:读取|查看|看看|看一下|看下|显示|告诉我).{0,8}"
            r"(?:系统)?(?:剪贴板|粘贴板).{0,8}(?:内容|里|里面|是什么|有啥|有什么)?",
            text,
        )
        or re.search(
            r"(?:系统)?(?:剪贴板|粘贴板).{0,8}"
            r"(?:内容|里|里面|是什么|有啥|有什么|读取|查看|看看|看一下|看下|显示)",
            text,
        )
        or re.search(
            r"\b(?:read|show|display|check|tell\s+me)\s+(?:the\s+)?"
            r"(?:system\s+)?clipboard(?:\s+contents?)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:what(?:'s| is)|what)\s+(?:is\s+)?(?:on|in)\s+(?:the\s+)?"
            r"(?:system\s+)?clipboard\b",
            lowered,
        )
    )


def _selected_text_read_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _selected_text_read_request(text):
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "copy"}),
        _request("clipboard.read", {}),
    ]


def _selected_text_read_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean or _clipboard_write_text(clean) or _clipboard_read_request(clean):
        return False
    lowered = clean.lower()
    return bool(
        re.search(
            r"(?:读|读取|查看|看看|看一下|看下|显示|告诉我).{0,12}"
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区)",
            clean,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区).{0,12}"
            r"(?:是什么|是啥|有啥|有什么|读|读取|查看|看看|看一下|看下|显示|告诉我)",
            clean,
        )
        or re.search(
            r"(?:我|当前|现在)?(?:选中|选取|高亮|选择)(?:了|的)?"
            r"(?:内容|文字|文本|这段|这部分|选区)?\s*(?:是什么|是啥|有啥|有什么)",
            clean,
        )
        or re.search(
            r"(?:我|当前|现在)?(?:选中|选取|高亮|选择)(?:了|的)?\s*(?:什么|啥)",
            clean,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}(?:内容|文字|文本|这段|这部分|选区)?"
            r".{0,8}(?:复制|拷贝)(?:给|给我|给我看|出来)",
            clean,
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
    text = str(value or "").strip()
    text = re.sub(r"^(?:一下|下|这个|那个)\s*", "", text)
    text = text.strip(" 「」『』“”\"'`")
    compact = re.sub(r"[\s._-]+", "", text.lower())
    if compact in {"", "这段", "这段文字", "这段文本", "这个", "这个文本", "text", "thistext"}:
        return ""
    return text


def _is_running_apps_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:现在|当前|桌面|电脑|系统|前台|后台)?.{0,8}"
            r"(?:开了|打开了|运行着|正在运行|在运行|启动了).{0,8}"
            r"(?:哪些|什么|什么样的|几个)?.{0,4}(?:应用|app|软件|程序)",
            text,
        )
        or re.search(
            r"(?:列出|查看|看看|显示|读取).{0,8}"
            r"(?:正在运行|在运行|打开|已打开|运行中).{0,8}(?:应用|app|软件|程序)",
            text,
        )
        or re.search(
            r"(?:现在|当前|桌面|电脑|系统|前台|后台)?.{0,8}"
            r"(?:有哪些|有哪|什么|哪些|几个).{0,4}(?:应用|app|软件|程序).{0,8}"
            r"(?:正在运行|在运行|运行中|打开|已打开|开着|启动着)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what|which|list|show|read)\s+(?:apps?|applications?|programs?)\s+"
            r"(?:are\s+)?(?:running|open)\b",
            lowered,
        )
        or re.search(r"\b(?:running|open)\s+(?:apps?|applications?|programs?)\b", lowered)
    )


def _app_status_name(text: str) -> str:
    if not _looks_like_app_status_request(text):
        return ""
    for pattern in _APP_STATUS_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        app_name = _normalize_app_name(raw_app)
        if not app_name or _looks_like_generic_app_open_target(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        return app_name
    return ""


def _looks_like_schedule_creation_request(text: str) -> bool:
    raw = str(text or "").strip()
    lowered = raw.lower()
    return bool(
        re.search(r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我", raw)
        or re.search(r"(?:新建|创建|添加|新增|设置|设定).{0,8}(?:提醒事项|提醒)", raw)
        or re.search(r"(?:提醒事项|reminders?).{0,12}(?:新建|创建|添加|新增|设置|设定|加)", lowered)
        or re.search(r"(?:新建|创建|添加|新增|设置|设定).{0,8}(?:日历事件|日程|日历日程)", raw)
        or re.search(
            r"(?:日历|calendar).{0,12}(?:新建|创建|添加|新增|设置|设定).{0,8}"
            r"(?:日程|事件|event)",
            lowered,
        )
        or re.search(
            r"\b(?:remind me|create (?:a )?reminder|add (?:a )?reminder|"
            r"create (?:a )?calendar event|add (?:a )?calendar event)\b",
            lowered,
        )
    )


def _desktop_windows_request(text: str) -> dict[str, str] | None:
    if _is_active_window_request(text):
        return None
    app_patterns = (
        r"(?:list|show|read)\s+(?:open\s+)?windows\s+(?:in|for|of)\s+(?P<app>[^.!?]+)",
        r"(?:what|which)\s+(?:open\s+)?windows\s+(?:are\s+)?(?:open\s+)?"
        r"(?:in|for|of)\s+(?P<app>[^.!?]+)",
        r"(?:what|which)\s+windows\s+does\s+(?P<app>[^.!?]+?)\s+have",
        r"(?:list|show|read)\s+(?P<app>[^.!?]+?)\s+windows",
        r"(?P<app>[^.!?]+?)\s+windows\?",
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:窗口|windows?)\s*(?:列表|清单|list)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|看一下|看下|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有|打开了|开了|正在显示)?"
        r"(?:哪些|什么|几个|多少).{0,4}(?:窗口|window)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|看一下|看下|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:窗口|windows?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:窗口|windows?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有|打开了|开了|正在显示)?"
        r"(?:哪些|什么|几个|多少).{0,4}(?:窗口|window)",
    )
    for pattern in app_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_generic_window_scope(raw_app):
            return {}
        app_name = _normalize_app_name(raw_app)
        if app_name and not _looks_like_generic_app_open_target(raw_app):
            return {"app_name": app_name}
    if _is_general_windows_request(text):
        return {}
    return None


def _desktop_ui_elements_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    if not (
        re.search(
            r"(?:当前|现在|这个|前台)?(?:窗口|界面|屏幕|应用|app)?"
            r".{0,10}(?:有哪些|有什么|列出|列一下|显示|查看|看看|看一下|读取|识别)"
            r".{0,10}(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)"
            r".{0,10}(?:有哪些|有什么|列表|列一下|显示|查看|看看|看一下|读取|识别)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:list|show|read|inspect)\b.{0,24}\b(?:ui elements|buttons|text fields|controls)\b",
            lowered,
        )
        or re.search(r"\b(?:what|which)\b.{0,24}\b(?:buttons|controls|ui elements)\b", lowered)
        or re.search(r"\bwhat\s+can\s+i\s+(?:click|press|use)\b", lowered)
    ):
        return None
    role_filter = ""
    if re.search(r"(?:按钮|button)", text, flags=re.IGNORECASE):
        role_filter = "button"
    elif re.search(r"(?:输入框|文本框|输入栏|text field|textbox|input)", text, flags=re.IGNORECASE):
        role_filter = "text"
    elif re.search(r"(?:菜单|menu)", text, flags=re.IGNORECASE):
        role_filter = "menu"
    elif re.search(r"(?:复选框|checkbox)", text, flags=re.IGNORECASE):
        role_filter = "checkbox"
    return {"role_filter": role_filter, "limit": 80}


def _app_scoped_ui_elements_tool_requests(text: str) -> list[dict[str, Any]]:
    ui_payload = _desktop_ui_elements_request(text)
    if ui_payload is None:
        return []
    if _is_current_ui_elements_request(text):
        return []
    app_name = _desktop_ui_elements_app_name(text)
    if not app_name:
        return []
    return [
        _request("app.focus", {"app_name": app_name}),
        _request("desktop.ui_elements", ui_payload),
    ]


def _is_current_ui_elements_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)?\s*"
            r"(?:当前|现在|这个|前台|该)\s*(?:应用|app|界面|窗口|屏幕)?\s*"
            r"(?:有哪些|有什么|有啥|有哪个|有哪几个|列出|列一下|显示|查看|看看|看一下|读取|识别|的)?\s*"
            r"(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:list|show|read|inspect|what|which)\b.{0,24}\b"
            r"(?:current|frontmost|foreground|this)\s+"
            r"(?:app|application|window|interface|screen)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _desktop_ui_elements_app_name(text: str) -> str:
    patterns = (
        r"\b(?:list|show|read|inspect)\s+(?:the\s+)?"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)\s+(?:in|on|for|of)\s+(?P<app>[^.!?]+)",
        r"\b(?:what|which)\s+(?:buttons|controls|ui\s+elements|text\s+fields)\s+"
        r"(?:are\s+)?(?:visible|shown|available|there)?\s*(?:in|on|for|of)\s+(?P<app>[^.!?]+)",
        r"\bwhat\s+can\s+i\s+(?:click|press|use)\s+(?:in|on)\s+(?P<app>[^.!?]+)",
        r"\b(?:list|show|read|inspect)\s+(?P<app>[^.!?]+?)\s+"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        if _looks_like_generic_ui_scope(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name and not _looks_like_generic_app_open_target(raw_app):
            return app_name
    return ""


def _app_scoped_ui_action_tool_request(text: str) -> dict[str, Any] | None:
    click_payload = _app_scoped_click_ui_element_request(text)
    if click_payload:
        return _request("app.focus_and_click_ui_element", click_payload)
    type_payload = _app_scoped_type_into_ui_element_request(text)
    if type_payload:
        return _request("app.focus_and_type_into_ui_element", type_payload)
    return None


def _app_scoped_safe_shortcut_tool_request(text: str) -> dict[str, Any] | None:
    shortcut = _app_scoped_safe_shortcut_request(text)
    if not shortcut:
        return None
    mode = str(shortcut.pop("mode"))
    return _request(f"app.{mode}_and_safe_shortcut", shortcut)


def _app_prefix_safe_scroll_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    safe_scroll = _desktop_safe_scroll(followup)
    if not safe_scroll:
        return None
    return _request(
        "app.focus_and_safe_scroll",
        {"app_name": app_name, **safe_scroll},
    )


def _app_prefix_safe_key_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    safe_key = _app_followup_safe_key(followup)
    if not safe_key:
        return None
    return _request(
        "app.focus_and_safe_key",
        {"app_name": app_name, **safe_key},
    )


def _app_open_or_focus_safe_key_tool_request(text: str) -> dict[str, Any] | None:
    payload = _app_open_or_focus_foreground_action_request(text)
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if tool not in {"app.open_and_safe_key", "app.focus_and_safe_key"}:
        return None
    raw_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    return _request(tool, dict(raw_input))


def _app_prefix_safe_click_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    safe_click = _desktop_safe_click(followup)
    if not safe_click:
        return None
    return _request(
        "app.focus_and_safe_click",
        {"app_name": app_name, **safe_click},
    )


def _app_prefix_safe_type_text_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    typed_text = _app_followup_safe_type_text(followup)
    if not typed_text:
        return None
    return _request(
        "app.focus_and_safe_type_text",
        {"app_name": app_name, "text": typed_text},
    )


def _app_prefix_window_management_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if _is_app_prefix_hide_followup(followup):
        return _request("app.hide", {"app_name": app_name})
    if _is_app_prefix_minimize_followup(followup):
        return _request("app.minimize", {"app_name": app_name})
    return None


def _is_app_prefix_hide_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:隐藏|隐藏一下|隐藏下|藏起来|收起|收起来|收一下|收下|hide(?:\s+(?:it|this\s+app))?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_app_prefix_minimize_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:最小化|最小化一下|最小化下|窗口最小化|把窗口最小化|最小化窗口|minimi[sz]e(?:\s+(?:it|this\s+window))?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_followup_safe_key(value: str) -> dict[str, Any] | None:
    safe_key = _desktop_safe_key(value)
    if safe_key:
        return safe_key
    text = _strip_query(value)
    if not _looks_like_bare_safe_key_followup(text):
        return None
    return _desktop_safe_key(f"按{text}")


def _looks_like_bare_safe_key_followup(value: str) -> bool:
    count = r"(?:\d+|[一二两三四五六七八九十])\s*(?:次|下)\s*"
    key = (
        r"(?:esc|escape|tab|home|end|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|"
        r"arrow\s+up|arrow\s+down|arrow\s+left|arrow\s+right|"
        r"制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|向上键|向下键|向左键|向右键|"
        r"上一页键|下一页键|home\s*键|end\s*键)"
    )
    return bool(
        re.fullmatch(
            rf"(?:{count})?{key}(?:\s*(?:键|一下|下))?",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _app_scoped_safe_shortcut_request(text: str) -> dict[str, Any] | None:
    shortcut_pattern = (
        r"(?:复制(?:一下|下)?(?:选中(?:的)?(?:内容|文字))?|"
        r"粘贴(?:一下|下)?(?:(?:到|进|在)?(?:这(?:里)?|当前输入框|输入框|当前窗口|前台))?|"
        r"全选|撤销|重做|"
        r"(?:浏览器|网页|当前网页|当前页)刷新(?:一下|下)?|"
        r"刷新(?:一下|下)?(?:页面|当前页|当前网页|网页)?|返回上一页|回到上一页|"
        r"重新打开(?:(?:刚刚|刚|最近|上次|上个|上一个)关闭的|关闭的)标签页|"
        r"恢复(?:(?:刚刚|刚|最近|上次|上个|上一个)关闭的|关闭的)标签页|"
        r"网页后退(?:一下|下|一次)?|浏览器后退(?:一下|下|一次)?|"
        r"后退一页|后退(?:一下|下|一次)?|前进一页|"
        r"网页前进(?:一下|下|一次)?|浏览器前进(?:一下|下|一次)?|"
        r"前进(?:一下|下|一次)?|"
        r"查找(?:一下|下)?|打开查找(?:框)?(?:一下|下)?|"
        r"打开搜索框(?:一下|下)?|页面(?:内|里)?查找(?:一下|下)?|"
        r"当前页查找(?:一下|下)?|"
        r"新建标签页|新标签页|打开新标签页|开新标签页|开一个新标签页|"
        r"新建窗口|新窗口|打开新窗口|开新窗口|开一个新窗口|"
        r"新建文档|新文档|新建文件|新文件|开新文档|开一个新文档|开新文件|开一个新文件|"
        r"新建表格|新表格|新建工作簿|新工作簿|"
        r"新建演示文稿|新演示文稿|新建幻灯片|新幻灯片|新建ppt|新ppt|"
        r"新建笔记|新建一个笔记|新建一条笔记|新建一篇笔记|新笔记|"
        r"新建备忘录|新建一个备忘录|新建一条备忘录|新建一篇备忘录|新备忘录|"
        r"新建日程|新建一个日程|新建一条日程|新建日历事件|新建一个日历事件|新日程|"
        r"新建事件|新建一个事件|新事件|"
        r"关闭(?:当前|这个|浏览器)?标签页|关掉(?:当前|这个|浏览器)?标签页|"
        r"切(?:换)?到(?:下一个|下个|下一|上一个|上个|上一)标签页|"
        r"(?:下一个|下个|下一|上一个|上个|上一)标签页|"
        r"copy|paste|select\s+all|undo|redo|refresh|reload|reopen\s+(?:the\s+)?(?:last\s+)?closed\s+tab|"
        r"restore\s+(?:the\s+)?(?:last\s+)?closed\s+tab|close\s+(?:the\s+)?(?:current\s+)?tab|"
        r"(?:switch\s+to\s+)?next\s+tab|(?:switch\s+to\s+)?previous\s+tab|"
        r"go\s+back|back|"
        r"go\s+forward|forward|find|new\s+tab|new\s+window|new\s+document|"
        r"new\s+file|new\s+workbook|new\s+spreadsheet|new\s+presentation|new\s+slide|"
        r"new\s+note|new\s+event|new\s+calendar\s+event|"
        r"make\s+a\s+new\s+document|create\s+a\s+new\s+document|"
        r"make\s+a\s+new\s+file|create\s+a\s+new\s+file|"
        r"make\s+a\s+new\s+workbook|create\s+a\s+new\s+workbook|"
        r"make\s+a\s+new\s+spreadsheet|create\s+a\s+new\s+spreadsheet|"
        r"make\s+a\s+new\s+presentation|create\s+a\s+new\s+presentation|"
        r"make\s+a\s+new\s+note|create\s+a\s+new\s+note|"
        r"make\s+a\s+new\s+event|create\s+a\s+new\s+event|"
        r"make\s+a\s+new\s+calendar\s+event|create\s+a\s+new\s+calendar\s+event)"
    )
    patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
            rf"(?:(?:并|然后|后|之后|再)\s*)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "open",
            rf"^(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+"
            rf"(?:(?:and\s+then|then|and)\s+)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)\s*"
            rf"(?:(?:并|然后|后|之后|再)\s*)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            rf"^(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+?)\s+"
            rf"(?:(?:and\s+then|then|and)\s+)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<app>[^。！？!?，,\s]+?)\s*(?:的|里|中|内|上)?\s*"
            rf"(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            rf"^(?P<app>[^.!?]+?)\s+(?P<action>{shortcut_pattern})$",
        ),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if re.search(r"(?:剪贴板|粘贴板|clipboard)", raw_app, flags=re.IGNORECASE):
            continue
        if re.sub(r"[\s._-]+", "", str(raw_app or "").strip().lower()) in {"switchto", "switch"}:
            continue
        if mode == "focus" and re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|运行|拉起|开启|开)",
            text,
        ):
            continue
        app_name = _normalize_app_scoped_ui_action_app(raw_app)
        if not app_name and mode == "open":
            compact = re.sub(r"[\s._-]+", "", _strip_app_name(raw_app).lower())
            if compact in _APP_ALIASES:
                app_name = _normalize_app_name(raw_app)
        action = _desktop_safe_shortcut_action(match.group("action"))
        if app_name and action:
            return {"mode": mode, "app_name": app_name, "action": action}
    return None


def _app_scoped_click_ui_element_request(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到|切到|切换到|聚焦|激活)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:里|中|内|上|的)?\s*"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<label>[^。！？!?，,]+?)"
        r"(?P<kind>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double2>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<app2>[^。！？!?，,]+?)\s*的\s*"
        r"(?P<label2>[^。！？!?，,]+?)"
        r"(?P<kind2>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double3>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<app3>[^。！？!?，,\s]+)\s+"
        r"(?P<label3>[^。！？!?，,]+?)"
        r"(?P<kind3>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?P<verb_en>double\s+click|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)"
        r"(?:\s+(?P<kind_en>button|control|element|field|input|text field|textbox|menu item|menu|checkbox))?"
        r"\s+(?:in|on)\s+(?:the\s+)?(?P<app_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _normalize_app_scoped_ui_action_app(
            groups.get("app")
            or groups.get("app2")
            or groups.get("app3")
            or groups.get("app_en")
            or ""
        )
        label = _strip_app_scoped_ui_action_target(
            groups.get("label")
            or groups.get("label2")
            or groups.get("label3")
            or groups.get("label_en")
            or ""
        )
        kind = (
            groups.get("kind")
            or groups.get("kind2")
            or groups.get("kind3")
            or groups.get("kind_en")
            or ""
        )
        verb = str(groups.get("verb_en") or "").strip().lower()
        if not app_name or not label or _looks_like_click_coordinate_label(label):
            continue
        role_filter = _desktop_ui_element_role_filter(kind)
        if not role_filter and verb == "press":
            role_filter = "button"
        return {
            "app_name": app_name,
            "target": label,
            "role_filter": role_filter,
            "limit": 80,
            "click_count": (
                2
                if (
                    groups.get("double")
                    or groups.get("double2")
                    or groups.get("double3")
                    or verb == "double click"
                )
                else 1
            ),
        }
    return None


def _app_scoped_type_into_ui_element_request(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field|"
        r"[^。！？!?，,]+?(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text\s+field|textbox|input|field|search\s+field|search\s+box|search\s+bar|"
        r"message\s+field|message\s+box|chat\s+box|address\s+bar))"
    )
    bare_target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field)"
    )
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|给|向)\s*(?P<app>[^。！？!?，,]+)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target>{target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<text2>[^。！？!?，,]+?)\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?:到|进|在)\s*"
        r"(?P<app2>[^。！？!?，,]+)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target2>{target_pattern})$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app3>[^。！？!?，,\s]+?)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target3>{bare_target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text3>[^。！？!?]+)$",
        r"^(?:type|enter|input)\s+(?P<text_en>[^.!?]+?)\s+"
        r"(?:into|in|to)\s+(?:the\s+)?"
        rf"(?P<target_en>{target_pattern})\s+"
        r"(?:in|on)\s+(?:the\s+)?(?P<app_en>[^.!?]+)$",
        r"^(?:type|enter|input)\s+(?P<text_en2>[^.!?]+?)\s+"
        r"(?:into|in|to)\s+(?:the\s+)?(?P<app_en2>[^.!?]+?)\s+"
        rf"(?P<target_en2>{target_pattern})$",
        r"^fill\s+(?:the\s+)?(?P<target_en3>[^.!?]+?)\s+"
        r"(?:in|on)\s+(?:the\s+)?(?P<app_en3>[^.!?]+?)\s+"
        r"with\s+(?P<text_en3>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _normalize_app_scoped_ui_action_app(
            groups.get("app")
            or groups.get("app2")
            or groups.get("app3")
            or groups.get("app_en")
            or groups.get("app_en2")
            or groups.get("app_en3")
            or ""
        )
        raw_target = (
            groups.get("target")
            or groups.get("target2")
            or groups.get("target3")
            or groups.get("target_en")
            or groups.get("target_en2")
            or groups.get("target_en3")
            or ""
        )
        typed_text = _strip_typed_text(
            groups.get("text")
            or groups.get("text2")
            or groups.get("text3")
            or groups.get("text_en")
            or groups.get("text_en2")
            or groups.get("text_en3")
            or ""
        )
        target = _strip_desktop_ui_input_target(raw_target)
        if not app_name or not target or not typed_text:
            continue
        return {
            "app_name": app_name,
            "target": target,
            "text": typed_text,
            "role_filter": _desktop_ui_element_role_filter(raw_target),
            "limit": 80,
        }
    return None


def _normalize_app_scoped_ui_action_app(value: str) -> str:
    raw_app = _strip_app_name(value)
    if not raw_app:
        return ""
    if re.match(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启|开|切换到|切到|切回|回到|聚焦|激活|置前)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    compact = re.sub(r"[\s._-]+", "", raw_app.lower())
    if compact in {
        "在",
        "给",
        "向",
        "到",
        "能否",
        "能不能",
        "可以",
        "帮我",
        "请",
        "麻烦",
        "cmd",
        "command",
        "ctrl",
        "control",
        "shift",
        "option",
        "alt",
        "fn",
        "enter",
        "return",
        "tab",
        "esc",
        "escape",
        "页面",
        "网页",
        "当前页",
        "当前页面",
        "当前网页",
        "浏览器",
        "browser",
        "page",
        "currentpage",
        "go",
        "make",
        "makea",
        "create",
        "createa",
    }:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", raw_app):
        return ""
    if _looks_like_generic_ui_scope(raw_app) or _looks_like_generic_app_open_target(raw_app):
        return ""
    if _looks_like_click_coordinate_label(raw_app) or re.search(
        r"(?:坐标|位置|coordinate|point|\d+\s*(?:,|，|\s)\s*\d+)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    if compact not in _APP_ALIASES and re.search(
        r"(?:按钮|控件|元素|输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"搜索|消息|聊天|地址|"
        r"\bbutton\b|\bcontrol\b|\belement\b|\bfield\b|\binput\b|\bbox\b|\bbar\b|"
        r"\bsearch\b|\bmessage\b|\bchat\b|\baddress\b)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    app_name = _normalize_app_name(raw_app)
    if not app_name or _looks_like_local_path(raw_app) or _normalize_site_name(raw_app):
        return ""
    return app_name


def _strip_app_scoped_ui_action_target(value: str) -> str:
    target = _strip_desktop_ui_element_label(value)
    target = re.sub(r"^(?:the|a|an)\s+", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^的\s*", "", target)
    return _strip_query(target)


def _looks_like_generic_ui_scope(value: str) -> bool:
    if _looks_like_generic_window_scope(value):
        return True
    scope_value = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接|列出|查看|看看|看一下|看下|显示|读取|识别)\s*",
        "",
        str(value or "").strip().lower(),
    )
    compact = re.sub(r"[\s._-]+", "", scope_value)
    return compact in {
        "当前",
        "现在",
        "这个",
        "前台",
        "该",
        "当前应用",
        "当前app",
        "当前界面",
        "当前窗口",
        "当前屏幕",
        "当前应用有哪些",
        "当前app有哪些",
        "当前应用界面",
        "前台应用",
        "前台app",
        "前台界面",
        "前台窗口",
        "这个应用",
        "这个app",
        "这个界面",
        "这个窗口",
        "该应用",
        "该app",
        "thecurrent",
        "thecurrentapp",
        "currentapplication",
        "currentapp",
        "currentwindow",
        "currentinterface",
        "current",
        "this",
        "foreground",
        "frontmost",
        "thisapp",
        "thiswindow",
    } or (
        compact.startswith(
            (
                "当前",
                "现在",
                "这个",
                "前台",
                "该",
                "当前应用",
                "当前app",
                "当前界面",
                "前台应用",
                "前台app",
                "前台界面",
                "这个应用",
                "这个app",
                "这个界面",
                "该应用",
                "该app",
            )
        )
        and any(marker in compact for marker in ("有哪些", "有什么", "有啥", "有哪个", "有哪几个"))
    )


def _is_general_windows_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:列出|列一下|列下|查看|看看|显示|读取).{0,8}"
            r"(?:当前|现在|桌面|打开|已打开|所有)?.{0,8}(?:窗口|windows?)",
            text,
        )
        or re.search(r"(?:窗口|windows?)\s*(?:列表|清单|list)$", text, flags=re.IGNORECASE)
        or re.search(r"(?:当前|现在|桌面|所有|全部)?(?:窗口|windows?).{0,8}(?:列出|列一下|列下|列表|清单)", text)
        or re.search(r"(?:打开|已打开|现在|当前|桌面|所有).{0,8}(?:有哪些|什么|几个|多少).{0,4}(?:窗口)", text)
        or re.search(r"\b(?:list|show|read|what|which)\s+(?:open\s+)?windows\b", lowered)
        or re.search(r"\bopen\s+windows\b", lowered)
    )


def _looks_like_generic_window_scope(value: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    return compact in {
        "",
        "当前",
        "当前应用",
        "当前app",
        "当前软件",
        "前台",
        "前台应用",
        "前台app",
        "前台软件",
        "现在",
        "桌面",
        "系统",
        "所有",
        "全部",
        "打开",
        "打开的",
        "已打开",
        "已打开的",
        "有",
        "有哪",
        "有哪些",
        "看看",
        "查看",
        "看一下",
        "看下",
        "列出",
        "列一下",
        "列下",
        "显示",
        "读取",
        "open",
        "all",
        "current",
        "currentapp",
        "foreground",
        "foregroundapp",
        "desktop",
        "windows",
    }


def _looks_like_app_status_request(text: str) -> bool:
    if _is_running_apps_request(text):
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _APP_STATUS_PATTERNS)


def _desktop_open_path(text: str) -> str:
    original_text = str(text or "").strip()
    if _finder_selection_reveal_path_request(original_text):
        return ""
    if _finder_selection_open_path_request(original_text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(original_text):
        return ""
    if _latest_screenshot_open_path_request(original_text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(original_text):
        return ""
    if _latest_desktop_item_open_path_request(original_text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(original_text):
        return ""
    if _latest_download_open_path_request(original_text):
        return "latest_download"
    text = _strip_finder_path_prefix(original_text)
    if _finder_selection_reveal_path_request(text):
        return ""
    if _finder_selection_open_path_request(text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(text):
        return ""
    if _latest_screenshot_open_path_request(text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(text):
        return ""
    if _latest_desktop_item_open_path_request(text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(text):
        return ""
    if _latest_download_open_path_request(text):
        return "latest_download"
    if text != original_text:
        path = _normalize_reveal_path(text)
        if path:
            return path
    if re.search(r"\bin\s+(?:the\s+)?finder\b", text, flags=re.IGNORECASE):
        return ""
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<path>{path_token})\s*(?:打开|开启)(?:一下|下)?",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|开启)\s*(?P<path>{path_token})",
        rf"\bopen\s+(?P<path>{path_token})\b",
        r"\bopen\s+(?P<path>[^.!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<path>[^。！？!?，,]+?)\s*(?:打开|开启)(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|开启)\s*(?P<path>[^。！？!?，,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        path = _normalize_reveal_path(match.group("path"))
        if path:
            return path
    return ""


def _desktop_reveal_path(text: str) -> str:
    original_text = str(text or "").strip()
    if _finder_selection_reveal_path_request(original_text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(original_text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(original_text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(original_text):
        return "latest_download"
    text = _strip_finder_path_prefix(original_text)
    if _finder_selection_reveal_path_request(text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(text):
        return "latest_download"
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<path>{path_token})\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示|显示一下|定位|找一下|找到)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示|显示一下|定位|找一下|找到|打开)\s*(?P<path>{path_token})",
        rf"(?:show|reveal|locate|open)\s+(?P<path>{path_token})(?:\s+in\s+(?:the\s+)?finder)?",
        rf"(?P<path>{path_token})\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示|显示一下|定位|找一下|找到|reveal|show)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"在\s*(?:finder|访达)\s*(?:中|里|内)?\s*"
        r"(?:显示|显示一下|定位|找一下|找到|打开)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<path>[^。！？!?，,]+?)\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        r"(?:显示|显示一下|定位|找一下|找到)(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|显示|显示一下|定位|找一下|找到)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:show|reveal|locate|open)\s+(?P<path>[^.!?]+?)\s+in\s+(?:the\s+)?finder",
        r"(?:show|reveal|locate)\s+(?P<path>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        path = _normalize_reveal_path(match.group("path"))
        if path:
            return path
    return ""


def _latest_screenshot_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}"
            r"(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent|last)\s+"
            r"(?:screenshot|screen\s+shot)\b",
            lowered,
        )
    )


def _latest_screenshot_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示|定位|找一下|找到|打开).{0,12}"
            r"(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示|定位|找一下|找到).{0,12}"
            r"(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent|last)\s+"
            r"(?:screenshot|screen\s+shot)(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _latest_desktop_item_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}"
            r"(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}"
            r"(?:文件|项目|内容|东西).{0,12}(?:打开|开启)",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:desktop\s+)?(?:file|item)\b",
            lowered,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:file|item)\s+on\s+(?:the\s+)?desktop\b",
            lowered,
        )
    )


def _latest_desktop_item_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示|定位|找一下|找到|打开).{0,12}"
            r"(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}(?:文件|项目|内容|东西)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示|定位|找一下|找到).{0,12}(?:桌面).{0,8}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent)\s+(?:desktop\s+)?(?:file|item)"
            r"(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent)\s+(?:file|item)\s+on\s+"
            r"(?:the\s+)?desktop(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _finder_selection_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,10}(?:当前)?(?:选中|选定)的?.{0,6}(?:文件|项目|条目)",
            text,
        )
        or re.search(
            r"(?:当前)?(?:选中|选定)的?.{0,6}(?:文件|项目|条目).{0,10}(?:打开|开启)",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item)\b",
            lowered,
        )
        or re.search(
            r"\b(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item).{0,20}\bopen\b",
            lowered,
        )
    )


def _finder_selection_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示|定位|找一下|找到).{0,10}"
            r"(?:当前)?(?:选中|选定)的?.{0,6}(?:文件|项目|条目)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示|定位|找一下|找到).{0,10}"
            r"(?:当前)?(?:选中|选定)的?.{0,6}(?:文件|项目|条目)",
            text,
        )
        or re.search(
            r"(?:当前)?(?:选中|选定)的?.{0,6}(?:文件|项目|条目).{0,10}"
            r"(?:显示|定位|找一下|找到)",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:currently\s+)?selected\s+"
            r"(?:finder\s+)?(?:file|item)(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _latest_download_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:最近|最新|刚刚|刚才).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:download|downloaded\s+(?:file|item))\b",
            lowered,
        )
    )


def _latest_download_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示|定位|找一下|找到|打开).{0,12}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示|定位|找一下|找到).{0,12}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:download|downloaded\s+(?:file|item))(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _strip_finder_path_prefix(text: str) -> str:
    return re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启)\s*(?:finder|访达|文件管理器|文件浏览器)|"
        r"(?:open|launch|start)\s+(?:the\s+)?(?:finder|file\s+manager|file\s+browser))\s*"
        r"(?:(?:并|然后|后|之后|再)|(?:,?\s*(?:and\s+then|and|then)))?\s*"
        r"(?:(?:看看|看一下|看下|查看|检查|打开|开启|进入)\s*)?",
        "",
        text,
        flags=re.IGNORECASE,
    )


def _normalize_reveal_path(value: str) -> str:
    target = _strip_polite_suffix(_strip_query(value))
    target = re.sub(r"\s+in\s+(?:the\s+)?finder$", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", target)
    if _looks_like_local_path(target):
        return target
    target = re.sub(r"\s*(?:文件夹|目录|路径|folder|directory|path)$", "", target, flags=re.IGNORECASE)
    target = _strip_polite_suffix(_strip_query(target))
    if not target:
        return ""
    compact = re.sub(r"[\s._-]+", "", target.lower())
    common_path = _COMMON_REVEAL_PATHS.get(compact)
    if common_path:
        return common_path
    return ""


def _looks_like_local_path(value: str) -> bool:
    return bool(re.match(r"^(?:~|/|\./|\../)", str(value or "").strip()))


def _app_open_or_focus_foreground_action_request(text: str) -> dict[str, Any] | None:
    open_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if open_match:
        return _app_foreground_action_request_from_match("open", open_match)

    focus_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+?)\s+"
            r"(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if focus_match:
        return _app_foreground_action_request_from_match("focus", focus_match)

    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, _raw_app, app_name, followup = shorthand_match
        return _app_foreground_action_request(mode, app_name, followup)
    return None


def _communication_compose_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_compose_request(text)
    if not parsed:
        return []
    mode, app_name, recipient, message, should_submit = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_type_text", {"text": message}),
    ]
    if should_submit:
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _communication_compose_request(text: str) -> tuple[str, str, str, str, bool] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None

    mode = "focus"
    body = stripped
    prefix_patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
        ),
        (
            "open",
            r"^(?:please\s+)?(?:open|launch|start)\s+",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
        ),
    )
    for candidate_mode, pattern in prefix_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            mode = candidate_mode
            body = stripped[match.end() :].strip()
            break

    split = _known_app_prefix_split(body)
    if not split:
        return None
    _raw_app, app_name, followup = split
    if app_name not in _COMMUNICATION_APP_NAMES:
        return None

    parsed = _communication_recipient_message(followup)
    if not parsed:
        return None
    recipient, message, should_submit = parsed
    return mode, app_name, recipient, message, should_submit


def _communication_recipient_message(text: str) -> tuple[str, str, bool] | None:
    followup = _strip_query(text)
    if not followup:
        return None
    patterns = (
        r"^(?:给|向)\s*(?P<recipient>.+?)\s*"
        r"(?P<verb>发送|发出|发|send)\s*(?P<message>.+)$",
        r"^(?:搜索|搜一下|搜|查找|查一下|检索|find|search)\s*"
        r"(?P<recipient>.+?)\s*"
        r"(?:然后|并且|并|之后|后|再|接着|and\s+then|then|and)\s*"
        r"(?P<verb>输入|打字|键入|敲入|打入|写入|写|发送|发出|发|"
        r"type|enter|input|send)\s*(?P<message>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        recipient = _strip_communication_piece(match.group("recipient"))
        raw_message = str(match.group("message") or "").strip()
        message = _strip_typed_text(raw_message)
        verb = str(match.group("verb") or "").strip().lower()
        should_submit = bool(
            re.search(r"^(?:发送|发出|发|send)$", verb, flags=re.IGNORECASE)
            or _communication_message_has_submit_suffix(raw_message)
        )
        if recipient and message:
            return recipient, message, should_submit
    return None


def _strip_communication_piece(value: str) -> str:
    text = _strip_query(value)
    text = re.sub(r"\s*(?:聊天|会话|对话|chat|conversation)$", "", text, flags=re.IGNORECASE)
    return text.strip(" 「」『』“”\"'`")


def _communication_message_has_submit_suffix(value: str) -> bool:
    return bool(
        re.search(
            r"(?:然后|并且|并|再|接着)\s*(?:发送|发出|提交)$",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:send|submit|post)$",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _app_open_or_focus_find_text_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if app_name in _BROWSER_APP_NAMES:
        return []
    if _desktop_type_into_ui_element(followup):
        return []
    query = _desktop_find_query(followup)
    if not query:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _app_open_or_focus_shortcut_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    parsed = _safe_shortcut_then_type(followup)
    if not parsed:
        return []
    shortcut_action, typed_text, submit_return = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": shortcut_action},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.hotkey", {"key": "return", "modifiers": []}))
    return requests


def _app_open_or_focus_safe_shortcut_sequence_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    actions = _safe_shortcut_action_sequence(followup)
    if len(actions) < 2:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": actions[0]},
        ),
        *[_request("desktop.safe_shortcut", {"action": action}) for action in actions[1:]],
    ]


def _foreground_safe_shortcut_sequence_tool_requests(text: str) -> list[dict[str, Any]]:
    actions = _safe_shortcut_action_sequence(text)
    if len(actions) < 2:
        return []
    return [_request("desktop.safe_shortcut", {"action": action}) for action in actions]


def _app_open_or_focus_screen_capture_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if not _is_screen_capture_request(followup):
        return []
    return [
        _request(f"app.{mode}", {"app_name": app_name}),
        _request("screen.capture", {"reason": "user asked to capture the screen"}),
    ]


def _app_open_or_focus_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    return _app_observe_tool_requests(mode, app_name, followup)


def _app_preposed_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    stripped_text = _strip_query(text)
    if _looks_like_app_status_request(stripped_text):
        return []
    match = re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<action>看看|看一下|看下|看一眼|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
        r"(?P<target>[^。！？!?，,]+)$",
        stripped_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    split = _known_app_prefix_split(match.group("target"))
    if not split:
        return []
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return []
    if (
        _desktop_windows_request(match.group("target")) is not None
        or _desktop_windows_request(_strip_query(text)) is not None
    ):
        return []
    action_followup = f"{match.group('action')} {followup}".strip()
    return _app_observe_tool_requests("focus", app_name, action_followup, include_windows=False)


def _app_prefix_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    split = _known_app_prefix_split(text)
    if not split:
        return []
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return []
    return _app_observe_tool_requests("focus", app_name, followup, include_windows=False)


def _app_observe_tool_requests(
    mode: str,
    app_name: str,
    followup: str,
    *,
    include_windows: bool = True,
) -> list[dict[str, Any]]:
    app_request = _request(f"app.{mode}", {"app_name": app_name})

    if app_name in _BROWSER_APP_NAMES:
        if _is_browser_extract_text_request(followup):
            return [app_request, _request("browser.extract_text", {})]
        if _is_browser_screenshot_request(followup):
            return [
                app_request,
                _request("browser.screenshot", {"reason": "user asked to capture the browser page"}),
            ]
        if _is_browser_current_page_request(followup):
            return [app_request, _request("browser.current_page", {})]

    ui_payload = _desktop_ui_elements_request(followup)
    if ui_payload is not None:
        return [app_request, _request("desktop.ui_elements", ui_payload)]

    windows_payload = _desktop_windows_request(followup) if include_windows else None
    if windows_payload is not None:
        scoped_windows = dict(windows_payload)
        scoped_windows.setdefault("app_name", app_name)
        return [app_request, _request("desktop.windows", scoped_windows)]

    if _is_active_window_request(followup):
        return [app_request, _request("desktop.active_window", {})]

    if (
        _is_screen_capture_request(followup)
        or _is_visual_inspection_followup(followup)
        or _is_app_visual_inspection_followup(followup)
    ):
        return [
            app_request,
            _request("screen.capture", {"reason": "user asked to capture the screen"}),
        ]

    return []


def _app_open_or_focus_click_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    parsed = _click_ui_element_then_type(followup)
    if not parsed:
        return []
    click_payload, typed_text, submit_return = parsed
    if _is_search_ui_input_click(click_payload):
        requests = [
            _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": "find"},
            ),
            _request("desktop.safe_type_text", {"text": typed_text}),
        ]
        if submit_return:
            requests.append(_request("desktop.search_submit", {}))
        return requests
    requests = [
        _request(
            f"app.{mode}_and_click_ui_element",
            {"app_name": app_name, **click_payload},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.hotkey", {"key": "return", "modifiers": []}))
    return requests


def _app_open_or_focus_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    payload = _desktop_type_into_ui_element(followup)
    if not _is_search_text_input_payload(payload):
        return []
    return _search_type_requests(
        payload,
        followup,
        shortcut_tool=f"app.{mode}_and_safe_shortcut",
        shortcut_input={"app_name": app_name, "action": "find"},
    )


def _app_direct_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, _raw_app, app_name, followup = shorthand_match
    else:
        scoped_text = _strip_app_search_scope_prefix(text)
        split = _known_app_prefix_split(scoped_text)
        if not split:
            return []
        _raw_app, app_name, followup = split
        mode = "focus"
    if not app_name or app_name in _BROWSER_APP_NAMES:
        return []
    parsed = _app_search_query_from_followup(followup)
    if parsed is None:
        return []
    typed_text, submit_return = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _strip_app_search_scope_prefix(text: str) -> str:
    return re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在|用|通过|到)\s*",
        "",
        _strip_query(text),
        flags=re.IGNORECASE,
    ).strip()


def _app_search_query_from_followup(value: str) -> tuple[str, bool] | None:
    followup = _strip_query(value)
    patterns = (
        r"^(?:搜索(?!框|栏)|搜一下|搜|查找(?!框)|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:find|search)\s+(?:for\s+)?(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = match.group("query")
        if re.search(
            r"(?:然后|并且|并|再|接着|and\s+then|then|and)\s*"
            r"(?:输入|打字|键入|敲入|发送|提交|点击|点|打开|播放|写入|写|粘贴|"
            r"type|enter\s+text|send|submit|click|open|play|write|paste)\b",
            raw_query,
            flags=re.IGNORECASE,
        ):
            return None
        submit_return = _typed_text_has_return_followup(raw_query, "搜索")
        query = re.sub(
            r"\s*(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?"
            r"(?:回车|确认|确定|搜索|查找|检索)$",
            "",
            raw_query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\s*(?:and\s+then|then|and)\s*(?:press\s+)?(?:enter|return|search|find|go)$",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = _strip_search_query(query)
        if query:
            return query, submit_return
    return None


def _app_open_or_focus_browser_action_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if app_name not in _BROWSER_APP_NAMES:
        return []
    app_request = _request(f"app.{mode}", {"app_name": app_name})
    browser_followup = _browser_context_followup(followup)

    click_payload = _browser_click_request(browser_followup)
    if click_payload:
        return [app_request, _request("browser.click", click_payload)]

    type_payload = _browser_type_text_request(browser_followup)
    if type_payload:
        requests = [app_request, _request("browser.type_text", type_payload)]
        selector = str(type_payload.get("selector") or "")
        if _browser_type_text_should_submit(browser_followup, selector):
            requests.append(_request("desktop.search_submit", {}))
        return requests

    return []


def _browser_context_followup(value: str) -> str:
    followup = _strip_query(value)
    if _has_browser_page_context(followup):
        return followup
    return f"网页{followup}"


def _browser_type_text_should_submit(source_text: str, selector: str) -> bool:
    if not _typed_text_has_return_followup(source_text, "搜索"):
        return False
    return bool(
        re.search(r"(?:search|输入|搜索|query|name=\"q\")", selector, flags=re.IGNORECASE)
    )


def _app_scoped_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    request = _app_scoped_ui_action_tool_request(text)
    if not isinstance(request, dict):
        return []
    tool = str(request.get("tool") or "").strip()
    if tool not in {"app.open_and_type_into_ui_element", "app.focus_and_type_into_ui_element"}:
        return []
    payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    if not _is_search_text_input_payload(payload):
        return []
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return []
    mode = "open" if tool.startswith("app.open") else "focus"
    return _search_type_requests(
        payload,
        text,
        shortcut_tool=f"app.{mode}_and_safe_shortcut",
        shortcut_input={"app_name": app_name, "action": "find"},
    )


def _foreground_click_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _click_ui_element_then_type(text)
    if not parsed:
        return []
    click_payload, typed_text, submit_return = parsed
    if not _is_search_ui_input_click(click_payload):
        return []
    requests = [
        _request("desktop.safe_shortcut", {"action": "find"}),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _foreground_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    payload = _desktop_type_into_ui_element(text)
    if not _is_search_text_input_payload(payload):
        return []
    return _search_type_requests(
        payload,
        text,
        shortcut_tool="desktop.safe_shortcut",
        shortcut_input={"action": "find"},
    )


def _search_type_requests(
    payload: dict[str, Any] | None,
    source_text: str,
    *,
    shortcut_tool: str,
    shortcut_input: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    typed_text = str(payload.get("text") or "").strip()
    target = str(payload.get("target") or "").strip()
    if not typed_text or not target:
        return []
    requests = [
        _request(shortcut_tool, shortcut_input),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if _typed_text_has_return_followup(source_text, target):
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _notes_create_and_type_tool_requests(text: str) -> list[dict[str, Any]]:
    typed_text = _notes_create_and_type_text(text)
    if not typed_text:
        return []
    return [
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]


def _notes_create_tool_request(text: str) -> dict[str, Any] | None:
    body = _notes_create_and_type_text(text)
    if not body:
        return None
    return _request("notes.create", {"body": body})


def _schedule_create_tool_request(text: str) -> dict[str, Any] | None:
    reminder_payload = _reminder_create_payload(text)
    if reminder_payload:
        return _request("reminders.create", reminder_payload)
    calendar_payload = _calendar_event_create_payload(text)
    if calendar_payload:
        return _request("calendar.create_event", calendar_payload)
    return None


def _reminder_create_payload(value: str) -> dict[str, Any] | None:
    body = _reminder_create_body(value)
    if not body:
        return None
    scheduled = _extract_schedule_datetime_and_title(body)
    if scheduled:
        due, title = scheduled
        if title:
            return {"title": title, "due_at": _local_datetime_text(due)}
    title = _reminders_create_and_type_text(value)
    if title:
        return {"title": title}
    clean_body = _strip_schedule_title(body)
    if clean_body and not _looks_like_reminder_title_with_due_time(clean_body):
        return {"title": clean_body}
    return None


def _calendar_event_create_payload(value: str) -> dict[str, Any] | None:
    body = _calendar_event_create_body(value)
    if not body:
        return None
    scheduled = _extract_schedule_datetime_and_title(body)
    if not scheduled:
        return None
    start, title = scheduled
    if not title:
        return None
    end = start + timedelta(hours=1)
    return {
        "title": title,
        "start_at": _local_datetime_text(start),
        "end_at": _local_datetime_text(end),
    }


def _reminder_create_body(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒|reminder)\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_prefixed>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒|reminder)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:提醒事项|reminders?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:新建|创建|添加|新增|加)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒)?\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<body_to_reminders>[^。！？!?]+?)\s*"
        r"(?:加到|添加到|新增到|放到|加入)\s*(?:提醒事项|提醒|reminders?)$",
        r"^(?:please\s+)?remind me\s+(?P<body>[^.!?]+)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
        r"(?:called|named|for|to)?\s*(?P<body>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            groups = match.groupdict()
            return _strip_query(
                groups.get("body")
                or groups.get("body_prefixed")
                or groups.get("body_to_reminders")
                or ""
            )
    return ""


def _calendar_event_create_body(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历事件|日程|日历日程|calendar event)\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_prefixed>[^。！？!?]+?)\s*(?:的)?(?:日历事件|日程|日历日程|calendar event)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)?\s*(?:日历|calendar)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日程|事件|event)?\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<body_to_calendar>[^。！？!?]+?)\s*"
        r"(?:加到|添加到|新增到|放到|加入)\s*(?:日历|calendar)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?calendar event\s+"
        r"(?:called|named|for)?\s*(?P<body>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            groups = match.groupdict()
            return _strip_query(
                groups.get("body")
                or groups.get("body_prefixed")
                or groups.get("body_to_calendar")
                or ""
            )
    return ""


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
)


def _extract_schedule_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in _SCHEDULE_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        scheduled = _datetime_from_schedule_match(match)
        if scheduled is None:
            continue
        title = _strip_schedule_title(f"{text[: match.start()]} {text[match.end() :]}")
        if title:
            return scheduled, title
    return None


def _datetime_from_schedule_match(match: re.Match[str]) -> datetime | None:
    full = str(match.group("full") or "")
    hour = _parse_schedule_number(match.group("hour"))
    if hour is None or hour < 0 or hour > 23:
        return None
    minute = 30 if match.groupdict().get("half") else _parse_schedule_number(match.groupdict().get("minute") or "0")
    if minute is None or minute < 0 or minute > 59:
        return None
    if any(marker in full for marker in ("下午", "晚上", "今晚", "明晚")) and hour < 12:
        hour += 12
    if "中午" in full and hour < 11:
        hour += 12
    if any(marker in full for marker in ("上午", "早上", "凌晨")) and hour == 12:
        hour = 0
    day_offset = 0
    if "后天" in full:
        day_offset = 2
    elif any(marker in full for marker in ("明天", "明日", "明晚")):
        day_offset = 1
    target_date = date.today() + timedelta(days=day_offset)
    return datetime.combine(target_date, time(hour=hour, minute=minute))


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
        tail = text[1:]
        return 10 + _CHINESE_DIGITS.get(tail, 0)
    if "十" in text:
        head, _, tail = text.partition("十")
        head_value = _CHINESE_DIGITS.get(head)
        if head_value is None:
            return None
        return head_value * 10 + (_CHINESE_DIGITS.get(tail, 0) if tail else 0)
    return None


def _strip_schedule_title(value: str) -> str:
    title = _strip_typed_text(str(value or ""))
    title = re.sub(r"^(?:在|于|到时候|的时候|时|要|去|做|进行|参加|记得|提醒我)\s*", "", title)
    title = re.sub(r"\s*(?:的时候|时|在|于)$", "", title).strip()
    return _strip_typed_text(title)


def _local_datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def _reminders_create_and_type_tool_requests(text: str) -> list[dict[str, Any]]:
    title = _reminders_create_and_type_text(text)
    if not title:
        return []
    return [
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Reminders", "action": "new_reminder"},
        ),
        _request("desktop.safe_type_text", {"text": title}),
    ]


def _reminders_create_and_type_text(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒|reminder)\s*[:：]?\s*(?P<title>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:提醒事项|reminders?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:新建|创建|添加|新增|加)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒)?\s*[:：]?\s*(?P<title_open>[^。！？!?]+)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
        r"(?:called|named|for|to)?\s*(?P<title_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        title = _strip_typed_text(
            groups.get("title") or groups.get("title_open") or groups.get("title_en") or ""
        )
        if _looks_like_reminder_title_with_due_time(title):
            continue
        if title:
            return title
    return ""


def _looks_like_reminder_title_with_due_time(value: str) -> bool:
    return bool(
        re.search(
            r"(?:今天|明天|后天|上午|下午|晚上|今晚|早上|中午|凌晨|"
            r"\d{1,2}\s*(?:点|:|：)|半小时后|一小时后|[一二两三四五六七八九十]+点)",
            str(value or ""),
        )
        or re.search(r"\b(?:today|tomorrow|tonight|am|pm|a\.m\.|p\.m\.)\b", str(value or ""), flags=re.IGNORECASE)
    )


def _notes_create_and_type_text(value: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s+(?P<text_short>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:记一下|记下|记录一下|记录|记上)\s*(?P<text_memory>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|开|打开)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*(?:备忘录|笔记|note)?\s*)?"
        r"(?:输入|打字|键入|敲入|打入|打上|写入|写下|写上|写|记录|记下|记一下|记上|打)\s*"
        r"(?P<text>[^。！？!?]+)$",
        r"^(?:please\s+)?(?:create|make|open)\s+(?:a\s+)?(?:new\s+)?note\s+"
        r"(?:and\s+)?(?:type|write|enter|record|with|saying)\s+(?P<text_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        typed_text = _strip_typed_text(
            groups.get("text")
            or groups.get("text_en")
            or groups.get("text_short")
            or groups.get("text_memory")
            or ""
        )
        if typed_text:
            return typed_text
    return ""


def _is_search_text_input_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    target = str(payload.get("target") or "").strip()
    role_filter = str(payload.get("role_filter") or "").strip()
    if not str(payload.get("text") or "").strip():
        return False
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target, flags=re.IGNORECASE):
        return False
    return not role_filter or bool(
        re.search(r"(?:text|field|input|search|输入|文本|搜索)", role_filter, flags=re.IGNORECASE)
    )


def _app_foreground_action_match(
    text: str,
    patterns: tuple[str, ...],
) -> tuple[str, str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        followup = _strip_app_foreground_followup_prefix(_strip_query(match.group("followup")))
        if raw_app and followup:
            return raw_app, followup
    return None


def _app_foreground_action_request_from_match(
    mode: str,
    match: tuple[str, str],
) -> dict[str, Any] | None:
    raw_app, followup = match
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    app_name = _normalize_app_name(raw_app)
    if not app_name or _looks_like_generic_app_open_target(raw_app):
        return None
    return _app_foreground_action_request(mode, app_name, followup)


def _app_foreground_action_request(
    mode: str,
    app_name: str,
    followup: str,
) -> dict[str, Any] | None:
    shortcut_action = _desktop_safe_shortcut_action(followup)
    if shortcut_action:
        return {
            "tool": f"app.{mode}_and_safe_shortcut",
            "input": {"app_name": app_name, "action": shortcut_action},
        }
    safe_scroll = _desktop_safe_scroll(followup)
    if safe_scroll:
        return {
            "tool": f"app.{mode}_and_safe_scroll",
            "input": {"app_name": app_name, **safe_scroll},
        }
    safe_key = _app_followup_safe_key(followup)
    if safe_key:
        return {
            "tool": f"app.{mode}_and_safe_key",
            "input": {"app_name": app_name, **safe_key},
        }
    safe_click = _desktop_safe_click(followup)
    if safe_click:
        return {
            "tool": f"app.{mode}_and_safe_click",
            "input": {"app_name": app_name, **safe_click},
        }
    click_ui_element = _desktop_click_ui_element(followup, require_context=False)
    if click_ui_element:
        return {
            "tool": f"app.{mode}_and_click_ui_element",
            "input": {"app_name": app_name, **click_ui_element},
        }
    type_into_ui_element = _desktop_type_into_ui_element(followup)
    if type_into_ui_element:
        return {
            "tool": f"app.{mode}_and_type_into_ui_element",
            "input": {"app_name": app_name, **type_into_ui_element},
        }
    hotkey = _desktop_hotkey(followup)
    if hotkey:
        return {
            "tool": f"app.{mode}_and_hotkey",
            "input": {"app_name": app_name, **hotkey},
        }
    typed_text = _app_followup_safe_type_text(followup)
    if typed_text:
        return {
            "tool": f"app.{mode}_and_safe_type_text",
            "input": {"app_name": app_name, "text": typed_text},
        }
    return None


def _app_open_or_focus_known_app_followup_match(text: str) -> tuple[str, str, str, str] | None:
    stripped = _strip_query(text)
    prefix_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "open",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
                r"^(?:please\s+)?(?:open|launch|start)\s+",
            ),
        ),
        (
            "focus",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
                r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
            ),
        ),
    )
    for mode, patterns in prefix_patterns:
        for pattern in patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            remainder = stripped[match.end() :].strip()
            split = _known_app_followup_split(remainder)
            if split:
                raw_app, app_name, followup = split
                return mode, raw_app, app_name, followup
    return None


def _known_app_followup_split(value: str) -> tuple[str, str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for alias, app_name in _known_app_followup_aliases():
        split = _split_compact_app_prefix(text, alias)
        if not split:
            continue
        raw_app, followup = split
        followup = _strip_known_app_followup_prefix(followup)
        if followup and _looks_like_known_app_followup(followup):
            return raw_app, app_name, followup
    return None


def _known_app_prefix_split(value: str) -> tuple[str, str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for alias, app_name in _known_app_followup_aliases():
        split = _split_compact_app_prefix(text, alias)
        if not split:
            continue
        raw_app, followup = split
        followup = _strip_known_app_followup_prefix(followup)
        if raw_app and followup:
            return raw_app, app_name, followup
    return None


def _known_app_followup_aliases() -> list[tuple[str, str]]:
    candidates: dict[str, str] = {}
    for alias, app_name in _APP_ALIASES.items():
        candidates.setdefault(alias, app_name)
    for app_name in set(_APP_ALIASES.values()):
        candidates.setdefault(app_name, app_name)
    return sorted(
        candidates.items(),
        key=lambda item: len(_compact_app_alias(item[0])),
        reverse=True,
    )


def _split_compact_app_prefix(value: str, alias: str) -> tuple[str, str] | None:
    compact_alias = _compact_app_alias(alias)
    if not compact_alias:
        return None
    consumed = 0
    end_index = 0
    for index, char in enumerate(value):
        if re.fullmatch(r"[\s._-]", char):
            continue
        if consumed >= len(compact_alias):
            break
        if char.lower() != compact_alias[consumed]:
            return None
        consumed += 1
        end_index = index + 1
    if consumed != len(compact_alias):
        return None
    raw_app = value[:end_index].strip()
    followup = value[end_index:].strip()
    if not raw_app or not followup:
        return None
    separator = value[end_index : end_index + 1]
    if (
        re.search(r"[A-Za-z0-9]$", raw_app)
        and re.match(r"[A-Za-z0-9]", followup)
        and not re.fullmatch(r"[\s._-]", separator or "")
    ):
        return None
    return raw_app, followup


def _strip_known_app_followup_prefix(value: str) -> str:
    followup = _strip_app_foreground_followup_prefix(_strip_query(value))
    followup = re.sub(
        r"^(?:应用|app|软件|程序)?(?:里|中|内|上(?!滑|滚|翻|一页)|的|里面|界面里|界面中)\s*",
        "",
        followup,
        flags=re.IGNORECASE,
    )
    return followup.strip()


def _looks_like_known_app_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    return bool(
        _desktop_safe_shortcut_action(followup)
        or _desktop_safe_scroll(followup)
        or _desktop_safe_click(followup)
        or _desktop_click_ui_element(followup, require_context=False)
        or _desktop_type_into_ui_element(followup)
        or _desktop_safe_key(followup)
        or _desktop_hotkey(followup)
        or _app_followup_safe_type_text(followup)
        or _app_search_query_from_followup(followup) is not None
        or _desktop_find_query(followup)
        or _browser_click_request(_browser_context_followup(followup)) is not None
        or _browser_type_text_request(_browser_context_followup(followup)) is not None
        or _desktop_ui_elements_request(followup) is not None
        or _desktop_windows_request(followup) is not None
        or _is_active_window_request(followup)
        or _is_browser_extract_text_request(followup)
        or _is_browser_screenshot_request(followup)
        or _is_browser_current_page_request(followup)
        or _is_screen_capture_request(followup)
        or _is_visual_inspection_followup(followup)
        or _is_app_visual_inspection_followup(followup)
        or _safe_shortcut_then_type(followup) is not None
        or bool(_safe_shortcut_action_sequence(followup))
    )


def _is_visual_inspection_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    lowered = followup.lower()
    return bool(
        re.search(
            r"^(?:看看|看一下|看下|看一眼|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
            r"(?:当前|这个|该)?(?:界面|画面|窗口|屏幕|桌面|应用|app)(?:上|里|中|内)?"
            r"(?:内容|状态|情况)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:当前|这个|该|现在)?(?:界面|画面|窗口|屏幕|桌面|应用|app)"
            r"(?:上|里|中|内)?(?:内容|状态|情况)?.{0,4}"
            r"(?:是什么|是啥|有什么|有啥|有哪些|看到什么|长什么样|怎么样)$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:当前|这个|该|现在)?(?:界面|画面|窗口|屏幕|桌面|应用|app)"
            r"(?:上|里|中|内)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:你|你现在|现在)?(?:能)?(?:看见|看到|观察到|识别到)"
            r"(?:什么|啥|哪些内容|什么内容)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:看看|看一下|看下|查看|观察(?:一下|下)?|识别(?:一下|下)?|看一眼)$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b(?:look at|inspect|view|read)\s+(?:the\s+)?(?:screen|window|ui|interface)\b", lowered)
    )


def _is_bare_visual_inspection_request(value: str) -> bool:
    text = _strip_query(value)
    return bool(
        re.fullmatch(
            r"(?:看看|看一下|看下|看一眼|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_app_visual_inspection_followup(value: str) -> bool:
    followup = _strip_query(value)
    if not followup:
        return False
    return bool(
        re.match(
            r"^(?:看看|看一下|看下|看一眼|查看|检查|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
            r"[^。！？!?]{0,40}$",
            followup,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_possible_app_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    return bool(
        re.match(
            r"^(?:在|向|给)?(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
            r"(?:上|里|中|内|的|里的|中的)?\s*"
            r"(?:输入|填写|键入|打入|填入|写入|写|打字|打上|打|"
            r"搜索|搜一下|搜|查找|查一下|查查|检索|"
            r"点击|点一下|点按|单击|点|按一下|按|双击|"
            r"发送|发出|提交|确认|确定|"
            r"新建|开新|保存|复制|粘贴|全选|撤销|重做|"
            r"滚动|上滑|下滑|向上滚动|向下滚动|向左滚动|向右滚动)",
            followup,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:type|enter|input|fill|search|find|click|press|tap|send|submit|"
            r"save|copy|paste|undo|redo|scroll|new)\b",
            followup,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:看看|看一下|看下|查看|看|读取|观察|检查)\s*[^。！？!?]*$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"(?:蓝牙|bluetooth|wi-?fi|无线网络|网络|声音|音量|显示器|显示|屏幕|"
            r"电池|键盘|鼠标|触控板|trackpad|通知|隐私|安全性|隐私与安全性|"
            r"辅助功能|壁纸|桌面与程序坞|通用|icloud|apple\s*id)(?:设置|偏好)?",
            followup,
            flags=re.IGNORECASE,
        )
    )


def _app_followup_safe_type_text(value: str) -> str:
    typed_text = _desktop_safe_type_text(value)
    if typed_text:
        return typed_text
    text = str(value or "").strip()
    if not text or re.search(r"(?:剪贴板|粘贴板|clipboard)", text, flags=re.IGNORECASE):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在(?:当前|前台)?(?:窗口|应用|app)?(?:里|中|内|上)?\s*)?"
        r"(?:写入|写下|写上|写|记录|记下|记一下|记上)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<text2>[^。！？!?]+?)\s*"
        r"(?:写入|写下|写上|写|记录|记下|记一下|记上)(?:进去|到当前窗口|到前台)?$",
        r"^(?:write|record|note\s+down)\s+(?P<text_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        typed_text = _strip_typed_text(
            groups.get("text") or groups.get("text2") or groups.get("text_en") or ""
        )
        if typed_text:
            return typed_text
    return ""


def _safe_shortcut_then_type(value: str) -> tuple[str, str, bool] | None:
    action_pattern = (
        r"新建标签页|新标签页|打开新标签页|开新标签页|开一个新标签页|"
        r"新建窗口|新窗口|打开新窗口|开新窗口|开一个新窗口|"
        r"新建文档|新文档|新建文件|新文件|开新文档|开一个新文档|开新文件|开一个新文件|"
        r"新建表格|新表格|新建工作簿|新工作簿|"
        r"新建演示文稿|新演示文稿|新建幻灯片|新幻灯片|新建ppt|新ppt|"
        r"新建笔记|新建一个笔记|新建一条笔记|新建一篇笔记|新笔记|"
        r"新建备忘录|新建一个备忘录|新建一条备忘录|新建一篇备忘录|新备忘录|"
        r"新建提醒事项|新建一个提醒事项|新建一条提醒事项|新建一项提醒事项|新建提醒|新提醒|"
        r"新建日程|新建一个日程|新建一条日程|新建日历事件|新建一个日历事件|新日程|"
        r"新建事件|新建一个事件|新事件|"
        r"new\s+tab|new\s+window|new\s+document|new\s+file|new\s+note|"
        r"new\s+reminder|new\s+event|new\s+calendar\s+event|"
        r"make\s+a\s+new\s+document|create\s+a\s+new\s+document|"
        r"make\s+a\s+new\s+file|create\s+a\s+new\s+file|"
        r"make\s+a\s+new\s+note|create\s+a\s+new\s+note|"
        r"make\s+a\s+new\s+event|create\s+a\s+new\s+event|"
        r"make\s+a\s+new\s+calendar\s+event|create\s+a\s+new\s+calendar\s+event|"
        r"make\s+a\s+new\s+reminder|create\s+a\s+new\s+reminder"
    )
    pattern = (
        rf"^(?P<action>{action_pattern})\s*"
        r"(?:(?:并且|并|然后|之后|后|再|and|then)\s*)?"
        r"(?:输入|打字|键入|敲入|打入|打上|写入|写|打|type|enter text)\s*"
        r"(?P<text>[^。！？!?]+)$"
    )
    match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
    if not match:
        return None
    action = _desktop_safe_shortcut_action(match.group("action"))
    raw_text = match.group("text")
    typed_text = _strip_typed_text(raw_text)
    if not action or not typed_text:
        return None
    return action, typed_text, _typed_text_has_return_followup(raw_text, "")


def _safe_shortcut_action_sequence(value: str) -> list[str]:
    text = _strip_query(value)
    if not text:
        return []
    compact = _normalize_named_hotkey_phrase(text)
    compact_sequences = {
        "全选复制": ["select_all", "copy"],
        "全选并复制": ["select_all", "copy"],
        "全选后复制": ["select_all", "copy"],
        "全选再复制": ["select_all", "copy"],
        "复制当前窗口": ["select_all", "copy"],
        "复制当前窗口内容": ["select_all", "copy"],
        "复制当前页面": ["select_all", "copy"],
        "复制当前页面内容": ["select_all", "copy"],
        "copycurrentwindow": ["select_all", "copy"],
        "copycurrentwindowcontents": ["select_all", "copy"],
        "copycurrentpage": ["select_all", "copy"],
        "copycurrentpagecontents": ["select_all", "copy"],
    }
    if compact in compact_sequences:
        return compact_sequences[compact]
    parts = re.split(
        r"(?:[，,；;。]\s*|(?:然后|接着|之后|随后|并且|并|再|后(?!退))\s*|"
        r"\s+(?:and\s+then|then|and)\s+)",
        text,
        flags=re.IGNORECASE,
    )
    actions: list[str] = []
    for part in parts:
        clause = _strip_sequence_clause_prefix(part)
        if not clause:
            continue
        action = _desktop_safe_shortcut_action(clause)
        if not action:
            return []
        actions.append(action)
    return actions if len(actions) >= 2 else []


def _click_ui_element_then_type(value: str) -> tuple[dict[str, Any], str, bool] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<label>[^。！？!?，,]+?)(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写|打字|打上|打)\s*"
        r"(?P<text>[^。！？!?]+)$",
        r"^(?:(?P<double_en>double\s+click)|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:type|enter|input|fill)\s+(?P<text_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_label = groups.get("label") or groups.get("label_en") or ""
        raw_text = groups.get("text") or groups.get("text_en") or ""
        target = _strip_desktop_ui_element_label(raw_label) or _strip_desktop_ui_input_target(raw_label)
        typed_text = _strip_typed_text(raw_text)
        if not target or not typed_text:
            continue
        return (
            {
                "target": target,
                "role_filter": _desktop_ui_element_role_filter(raw_label),
                "limit": 80,
                "click_count": 2 if groups.get("double") or groups.get("double_en") else 1,
            },
            typed_text,
            _typed_text_has_return_followup(raw_text, raw_label),
        )
    return None


def _is_search_ui_input_click(payload: dict[str, Any]) -> bool:
    target = str(payload.get("target") or "").strip()
    role_filter = str(payload.get("role_filter") or "").strip()
    click_count = payload.get("click_count", 1)
    if click_count != 1:
        return False
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target, flags=re.IGNORECASE):
        return False
    return not role_filter or bool(
        re.search(r"(?:text|field|input|search|输入|文本|搜索)", role_filter, flags=re.IGNORECASE)
    )


def _typed_text_has_return_followup(raw_text: str, target: str) -> bool:
    text = str(raw_text or "").strip()
    if not text:
        return False
    if re.search(
        r"(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?(?:回车|确认|确定)$",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:and\s+then|then|and)\s*(?:press\s+)?(?:enter|return)$",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    target_text = str(target or "")
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target_text, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?(?:搜索|查找|检索)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:press\s+)?(?:search|find|go)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _compact_app_alias(value: str) -> str:
    return re.sub(r"[\s._-]+", "", str(value or "").strip().lower())


def _app_focus_name(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:并|然后|后|之后|再)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:切换到|切到|切回|回到|聚焦|激活|置前|带到|带回|移到|放到|切过来)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:到|回到)\s*(?:前台|前面|最前面|最前)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来))?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+)",
        r"bring\s+(?P<app>[^.!?]+?)\s+to\s+(?:the\s+)?(?:front|foreground)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_window_target(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_open_target(raw_app):
            continue
        if _looks_like_foreground_text_input_phrase(raw_app):
            continue
        if _is_next_foreground_focus_request(raw_app) or _is_previous_foreground_focus_request(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_show_or_open_name(text: str) -> str:
    if _desktop_reveal_path(text) or _desktop_open_path(text):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:并|然后|后|之后|再)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*(?:，|,)?\s*(?:如果|要是)?(?:没|没有|未)(?:打开|启动|运行|开|在运行)"
        r".*(?:打开|启动|运行|拉起|开启)",
        r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
        r"(?:focus|activate|show|bring(?:\s+to\s+front)?)",
        r"(?:focus|activate|switch to|show)\s+(?P<app>[^.!?]+?)\s*,?\s*"
        r"(?:open|launch|start)\s+(?:it\s+)?(?:if\s+(?:needed|not\s+open|closed))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_generic_app_open_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_focus_window_payload(text: str) -> dict[str, str] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*的\s*(?:标题(?:包含|为)?|名为|叫)?\s*"
        r"(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*(?:标题(?:包含|为)?|名为|叫)\s*"
        r"(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,\s]+?)"
        r"\s+(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"\b(?:focus|activate|switch to)\s+(?P<app>.+?)\s+window\s+"
        r"(?:(?:titled|called|matching|containing)\s+)?(?P<title>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        raw_title = match.group("title")
        if _looks_like_local_path(_strip_app_name(raw_app)) or _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        title = _strip_window_title(raw_title)
        if app_name and title:
            return {"app_name": app_name, "title_contains": title}
    return None


def _app_quit_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:退出|关闭|关掉|结束|终止)(?:一下|下|掉)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:退出|关闭|关掉|结束|终止)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:quit|close|exit|shut down|terminate)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_show_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
        or _desktop_reveal_path(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:显示出来|显示一下|显示(?!器)|还原一下|还原|恢复|取消隐藏)",
        r"(?:把|将)\s*(?P<app>[^。！？!?，,]+?)\s*(?:显示出来|还原|恢复|取消隐藏)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:显示(?!器)|还原|恢复|取消隐藏)\s*(?P<app>[^。！？!?，,]+)",
        r"\b(?:show|unhide|restore)\s+(?P<app>[^.!?]+)",
        r"\bbring\s+back\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_hide_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:隐藏|收起)(?:一下|下)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:隐藏|收起)\s*(?P<app>[^。！？!?，,]+)",
        r"\bhide\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_minimize_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:最小化)(?:一下|下)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:最小化)\s*(?P<app>[^。！？!?，,]+)",
        r"\bminimi[sz]e\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _terminal_run_payload(text: str) -> dict[str, Any] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None
    terminal_patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:terminal|终端|命令行)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:运行|执行|跑|run|execute)\s*(?:一下\s*)?(?:命令|指令|command)?\s*[:：]?\s*"
        r"(?P<command>.+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)\s*(?:terminal|终端|命令行|shell)\s*(?:里|中|内|上)?\s*"
        r"(?:运行|执行|跑|run|execute)\s*(?:一下\s*)?(?:命令|指令|command)?\s*[:：]?\s*"
        r"(?P<command>.+)$",
        r"^(?:please\s+)?(?:run|execute)\s+(?P<command>.+?)\s+"
        r"(?:in|with|from)\s+(?:the\s+)?(?:terminal|shell)$",
        r"^(?:terminal|shell)\s+(?:run|execute)\s+(?P<command>.+)$",
    )
    for pattern in terminal_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        payload = _terminal_run_payload_from_command(match.group("command"), terminal_context=True)
        if payload:
            return payload
    generic_patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:运行|执行|跑)\s*(?:一下\s*)?(?:命令|指令)?\s*[:：]?\s*(?P<command>.+)$",
        r"^(?:please\s+)?(?:run|execute)\s+(?P<command>.+)$",
    )
    for pattern in generic_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        payload = _terminal_run_payload_from_command(match.group("command"), terminal_context=False)
        if payload:
            return payload
    return None


def _terminal_run_payload_from_command(
    value: str,
    *,
    terminal_context: bool,
) -> dict[str, Any] | None:
    command = _strip_terminal_command(value)
    if not _looks_like_terminal_command(command, terminal_context=terminal_context):
        return None
    payload: dict[str, Any] = {"command": command}
    if _terminal_command_requires_shell(command):
        payload["shell"] = True
    return payload


def _strip_terminal_command(value: str) -> str:
    command = _strip_query(value)
    command = re.sub(r"^(?:命令|指令|command)\s*[:：]?\s*", "", command, flags=re.IGNORECASE)
    command = command.strip()
    for left, right in (("```", "```"), ("`", "`"), ("“", "”"), ("\"", "\""), ("'", "'")):
        if command.startswith(left) and command.endswith(right) and len(command) > len(left) + len(right):
            return command[len(left) : -len(right)].strip()
    return command


def _looks_like_terminal_command(command: str, *, terminal_context: bool) -> bool:
    if not command or len(command) > 400:
        return False
    parts = _terminal_command_parts(command)
    head = str(parts[0] if parts else "").strip()
    if not head:
        return False
    compact_head = re.sub(r"[\s._-]+", "", head.lower())
    if compact_head in _APP_ALIASES and len(parts) <= 1:
        return False
    if re.search(r"[\u4e00-\u9fff]", head):
        return False
    if re.match(r"^(?:一个|一条|某个|这个|那个)?(?:会|能|可以)?(?:失败|成功)?(?:的)?(?:命令|指令|脚本|代码|任务)", command):
        return False
    normalized_head = head.lower()
    if normalized_head.startswith(("./", "../", "/")):
        return True
    if normalized_head in _TERMINAL_COMMAND_HEADS:
        return True
    return bool(terminal_context and re.fullmatch(r"[A-Za-z0-9_./+-]+", head))


def _terminal_command_parts(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _terminal_command_requires_shell(command: str) -> bool:
    return bool(re.search(r"(?:&&|\|\||[|;&<>]|\$\(|`)", command))


def _app_open_name(text: str) -> str:
    media_app = _media_app_open_name(text)
    if media_app:
        return media_app
    permission_settings = _permission_settings_open_name(text)
    if permission_settings:
        return permission_settings
    system_settings_target = _system_settings_open_name(text)
    if system_settings_target:
        return system_settings_target
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
        or _looks_like_schedule_creation_request(text)
        or _desktop_safe_shortcut_action(text)
    ):
        return ""

    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?P<verb>打开|启动|运行|拉起|开启|开)\s*(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<verb>打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?P<app>[^。！？!?，,]+)",
        r"(?P<verb>open|launch|start)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if _looks_like_generic_app_open_target(raw_app):
            continue
        if app_name:
            return app_name
    return ""


def _system_settings_open_name(text: str) -> str:
    lowered = text.lower()
    if not re.search(
        r"(?:打开|启动|开启|拉起|显示|前往|进入|open|launch|show|go\s+to)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""
    if not re.search(
        r"(?:系统设置|系统偏好|设置|偏好|settings?|preferences?|pane|page|面板|页面|权限|permission)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""
    return _system_settings_target_name(text)


def _system_settings_target_name(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:蓝牙|\bbluetooth\b)", lowered):
        return "蓝牙"
    if re.search(r"(?:wi-?fi|无线网络|无线局域网)", lowered):
        return "Wi-Fi"
    if re.search(r"(?:网络|\bnetwork\b)", lowered):
        return "网络"
    if re.search(r"(?:辅助功能|无障碍|\baccessibility\b|\bassistive\b)", lowered):
        return "辅助功能权限"
    if re.search(r"(?:屏幕录制|屏幕录像|\bscreen\s+recording\b|\bscreen\s+capture\b)", lowered):
        return "屏幕录制权限"
    if re.search(r"(?:自动化|\bautomation\b|\bapple\s*events?\b)", lowered):
        return "自动化权限"
    if re.search(r"(?:完全磁盘访问|\bfull\s+disk\s+access\b)", lowered):
        return "完全磁盘访问"
    if re.search(r"(?:文件和文件夹|文件与文件夹|\bfiles?\s+and\s+folders?\b)", lowered):
        return "文件和文件夹"
    if re.search(r"(?:输入监控|\binput\s+monitoring\b)", lowered):
        return "输入监控"
    if re.search(r"(?:麦克风|\bmicrophone\b)", lowered):
        return "麦克风"
    if re.search(r"(?:摄像头|相机|\bcamera\b)", lowered):
        return "摄像头"
    if re.search(r"(?:隐私与安全性|隐私和安全性|隐私.*安全|\bprivacy\b|\bsecurity\b)", lowered):
        return "隐私与安全性"
    return ""


def _permission_settings_open_name(text: str) -> str:
    lowered = text.lower()
    if re.search(
        r"(?:打开|启动|开启|拉起|显示|前往|进入).{0,20}"
        r"(?:桌面权限|桌面执行权限|本地工具权限|需要的权限|缺少的权限|权限设置|权限页面|"
        r"屏幕录制|辅助功能|自动化|隐私与安全性|隐私.*安全)",
        text,
    ):
        return _permission_settings_target_name(text) or "隐私与安全性"
    if re.search(
        r"\b(?:open|launch|show)\s+(?:desktop|missing|required|permission|permissions)"
        r".{0,24}(?:settings|page|pane)\b",
        lowered,
    ):
        return _permission_settings_target_name(text) or "隐私与安全性"
    english_target = _permission_settings_target_name(text)
    if english_target and re.search(
        r"\b(?:open|launch|show|go\s+to)\b.{0,24}"
        r"(?:privacy|security|accessibility|automation|screen\s+recording|screen\s+capture)"
        r".{0,24}(?:settings|permissions?|pane|page)?\b",
        lowered,
    ):
        return english_target
    return ""


def _permission_settings_target_name(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:辅助功能|无障碍|\baccessibility\b|\bassistive\b)", lowered):
        return "辅助功能权限"
    if re.search(r"(?:屏幕录制|屏幕录像|\bscreen\s+recording\b|\bscreen\s+capture\b)", lowered):
        return "屏幕录制权限"
    if re.search(r"(?:自动化|\bautomation\b|\bapple\s*events?\b)", lowered):
        return "自动化权限"
    if re.search(r"(?:隐私与安全性|隐私和安全性|隐私.*安全|\bprivacy\b|\bsecurity\b)", lowered):
        return "隐私与安全性"
    return ""


def _media_app_open_name(text: str) -> str:
    lowered = text.lower()
    if not re.search(r"(?:播放|放|打开|启动|运行|open|launch|start|play)", lowered):
        return ""
    named_play_app = _non_apple_music_named_play_app_name(text)
    if named_play_app:
        return named_play_app
    generic_play_app = _music_app_generic_play_open_name(text)
    if generic_play_app:
        return generic_play_app
    for pattern in (
        r"^(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:播放一下|播一下|放一下|播放|播|放|打开|启动|运行)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?P<app>[^.!?]+?)\s+(?:play|start|open|launch)[.!?]*$",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    for pattern in (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:播放|放|打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+)",
        r"(?:open|launch|start|play)\s+(?P<app>[^.!?]+)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    if re.search(r"apple\s*music", lowered):
        return "Music"
    if re.search(r"(?:播放|放|打开|启动|运行)\s*(?:一下\s*)?(?:音乐|music)(?:应用|app|软件|程序)?\s*$", lowered):
        return "Music"
    if re.search(r"(?:open|launch|start|play)\s+music(?:\s+app)?\s*$", lowered):
        return "Music"
    return ""


def _non_apple_music_named_play_app_name(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:(?:并|然后|后|之后|再)\s*)?(?:开始)?(?:播放|播|放)\s*(?P<query>[^。！？!?，,]+)$",
        r"^(?P<app>[^。！？!?，,]+?)\s*(?:播放|播|放)\s*(?P<query>[^。！？!?，,]+)$",
        r"^(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
        r"(?:play|start\s+playing)\s+(?P<query>[^.!?]+)$",
        r"^(?P<app>[^.!?]+?)\s+(?:play|start\s+playing)\s+(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        query = _strip_music_query_context(match.group("query"))
        if app_name and app_name != "Music" and query and _is_specific_music_query(query):
            return app_name
    return ""


def _known_music_app_name(value: str) -> str:
    app_name = _normalize_app_name(value)
    raw_compact = re.sub(r"[\s._-]+", "", _strip_app_name(value).lower())
    app_compact = re.sub(r"[\s._-]+", "", app_name.lower())
    if raw_compact in _MUSIC_APP_COMPACTS or app_compact in _MUSIC_APP_COMPACTS:
        return app_name
    return ""


def _music_app_generic_play_open_name(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:(?:并|然后|后|之后|再)\s*)?(?:随便|随机)?(?:开始)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
        r"(?:play|start\s+playing)[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:play|start\s+playing)\s+(?P<app>[^.!?]+?)[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    return ""


def _normalize_app_name(value: str) -> str:
    app = _strip_app_name(value)
    if not app:
        return ""
    if _normalize_url(app):
        return ""
    lowered = app.lower()
    compact = re.sub(r"[\s._-]+", "", lowered)
    return _APP_ALIASES.get(compact, app)


def _strip_app_name(value: str) -> str:
    app = _strip_query(value)
    app = _strip_app_foreground_followup(app)
    app = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", app)
    app = re.sub(
        r"\s*(?:应用|app|软件|程序|客户端|桌面版|桌面客户端|client|desktop\s*app|desktop\s*client)$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = _strip_polite_suffix(app)
    return app.strip()


def _strip_app_foreground_followup(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再)\s*"
        r"(?:输入|打字|键入|敲入|打入|打上|打|写入|写|复制|粘贴|全选|撤销|重做|"
        r"查找|打开查找|新建标签页|新标签页|打开新标签页|新建窗口|新窗口|打开新窗口|"
        r"刷新|返回上一页|回到上一页|后退|前进).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:type|enter text|copy|paste|select all|undo|redo|find|new tab|new window|"
        r"refresh|reload|go back|back|go forward|forward).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    known_split = _known_app_followup_split(text)
    if known_split:
        raw_app, _app_name, _followup = known_split
        if raw_app:
            return raw_app.strip()
    known_prefix = _known_app_prefix_split(text)
    if known_prefix:
        raw_app, _app_name, followup = known_prefix
        if raw_app and _looks_like_possible_app_followup(followup):
            return raw_app.strip()
    return text.strip()


def _strip_app_foreground_followup_prefix(value: str) -> str:
    return re.sub(
        r"^(?:并且|并|然后|之后|后(?!退)|再|and|then)\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_generic_app_open_target(value: str) -> bool:
    app = _strip_app_name(value)
    if not app:
        return True
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in _APP_ALIASES:
        return False
    if compact in {
        "窗口",
        "当前窗口",
        "这个窗口",
        "新窗口",
        "新建窗口",
        "标签页",
        "当前标签页",
        "这个标签页",
        "新标签页",
        "新建标签页",
        "window",
        "currentwindow",
        "thiswindow",
        "newwindow",
        "tab",
        "currenttab",
        "thistab",
        "newtab",
        "权限",
        "这个权限",
        "当前权限",
        "permission",
        "permissions",
        "thispermission",
        "currentpermission",
        "能否",
        "能不能",
        "可以",
        "帮我",
        "请",
        "麻烦",
    }:
        return True
    lowered = app.lower()
    if re.search(r"(?:命令|指令|脚本|代码|任务|测试)", lowered):
        return True
    if re.search(r"\b(?:command|shell|script|code|test)\b", lowered):
        return True
    if _looks_like_composite_action_target(app):
        return True
    if re.fullmatch(r"(?:一个|一条|某个|这个|那个).+", app):
        return True
    return False


def _looks_like_composite_action_target(value: str) -> bool:
    target = str(value or "").strip()
    if not target:
        return False
    return bool(
        re.search(
            r"(?:并|然后|之后|再|如果|要是).{0,24}"
            r"(?:打开|启动|运行|拉起|开启|访问|浏览|前往|搜索|搜|查|切换|切到|"
            r"聚焦|激活|置前|显示|还原|播放|放)",
            target,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:and|then|if)\b.{0,32}"
            r"\b(?:open|launch|start|visit|browse|search|focus|activate|show|play)\b",
            target,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_generic_app_quit_target(value: str) -> bool:
    app = _strip_app_name(value)
    if not app:
        return True
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in _APP_ALIASES:
        return False
    if compact in {
        "窗口",
        "当前窗口",
        "这个窗口",
        "当前页面",
        "这个页面",
        "标签页",
        "当前标签页",
        "window",
        "currentwindow",
        "thiswindow",
        "tab",
        "currenttab",
        "page",
        "currentpage",
    }:
        return True
    if re.search(r"(?:窗口|标签页|页面)", app):
        return True
    if re.search(r"\b(?:window|tab|page)\b", app.lower()):
        return True
    return _looks_like_generic_app_open_target(value)


def _looks_like_current_app_scope(value: str) -> bool:
    app = _strip_app_name(value)
    compact = re.sub(r"[\s._-]+", "", app.lower())
    return compact in {
        "当前",
        "现在",
        "前台",
        "这个",
        "该",
        "当前应用",
        "前台应用",
        "当前app",
        "前台app",
        "current",
        "foreground",
        "active",
        "this",
        "currentapp",
        "foregroundapp",
        "activeapp",
        "thisapp",
        "currentapplication",
        "foregroundapplication",
        "activeapplication",
        "thisapplication",
    }


def _looks_like_foreground_text_input_phrase(value: str) -> bool:
    text = _strip_query(value)
    return bool(
        re.match(
            r"^(?:输入|打字|键入|敲入|打入|打上|写入|写|打)(?:\s|$)",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(r"^(?:type|enter|input|write)\s+", text, flags=re.IGNORECASE)
    )


def _looks_like_common_path_target(value: str) -> bool:
    app = _strip_app_name(value)
    compact = re.sub(r"[\s._-]+", "", app.lower())
    return compact in _COMMON_REVEAL_PATHS


def _looks_like_window_target(value: str) -> bool:
    text = str(value or "")
    return bool(re.search(r"(?:窗口|window)", text, flags=re.IGNORECASE))


def _strip_window_title(value: str) -> str:
    title = _strip_query(value)
    title = re.sub(r"^(?:标题|title|named|called|matching|containing)\s*", "", title, flags=re.IGNORECASE)
    return _strip_query(title)


def _music_query(text: str) -> str:
    if (
        _looks_like_generic_music_play_request(text)
        or _looks_like_scoped_generic_music_play_request(text)
        or _music_app_generic_play_open_name(text)
        or _non_apple_music_named_play_app_name(text)
    ):
        return ""
    patterns = (
        r"(?:play)\s+(?P<query>[^.!?]+?)\s+(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?",
        r"(?:帮我|请|麻烦)?(?:直接)?来(?:一首|首)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?(?:播放(?!器)|播(?!放器)|放(?!器))(?:一下|一首|首)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?播放(?!器)[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?放(?!器)[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?(?P<query>[^。！？!?，,]+?)\s*(?:播放一下|播一下|放一下|放一首|播放一首|来一首)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
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
    if _known_music_app_name(query):
        return False
    return normalized not in {
        "下",
        "一下",
        "音乐",
        "music",
        "song",
        "songs",
        "歌曲",
        "首歌",
        "一首歌",
        "applemusic",
        "musicapp",
        "音乐app",
        "音乐应用",
        "音乐软件",
        "音乐播放器",
        "播放器",
        "歌",
        "点歌",
        "点儿歌",
        "些歌",
        "一点歌",
        "一点儿歌",
    }


def _music_control_action(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:下一首|下一曲|下首|切下一首|跳下一首|下一首歌|切歌|换一首|换首歌|换歌)", text) or re.search(
        r"\b(?:next|skip)\s+(?:song|track)\b",
        lowered,
    ):
        return "next"
    if re.search(r"(?:上一首|上一曲|上首|切上一首|回到上一首|上一首歌)", text) or re.search(
        r"\b(?:previous|prev|back)\s+(?:song|track)\b",
        lowered,
    ):
        return "previous"
    if re.search(r"(?:播放\s*/\s*暂停|暂停\s*/\s*播放|播放暂停|切换播放|切换暂停)", text) or re.search(
        r"\b(?:toggle|play\s*/\s*pause|playpause)\b",
        lowered,
    ):
        return "toggle"
    if re.search(r"(?:暂停|停一下|停止播放|先停一下)(?:\s*(?:音乐|歌曲|apple\s*music|music))?", lowered) or re.search(
        r"\bpause\s+(?:music|apple\s*music|playback)\b",
        lowered,
    ):
        return "pause"
    if re.search(
        r"(?:继续播放|恢复播放|接着播放|开始播放)(?:\s*(?:音乐|歌曲|apple\s*music|music))?",
        lowered,
    ) or re.search(r"\b(?:resume|continue|start)\s+(?:music|apple\s*music|playback)\b", lowered):
        return "play"
    if _music_app_generic_play_open_name(text) == "Music":
        return "play"
    if _looks_like_scoped_generic_music_play_request(text):
        return "play"
    if re.search(
        r"^(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
        r"(?:播放一下|播一下|放一下|播放|播|放|开始播放|继续播放)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:音乐|歌曲|歌|music|songs?)\s*(?:播放|播|放)(?:一下|一首|首)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?(?:播放|放)一下"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?(?:播放|放)(?:一下)?"
        r"\s*(?:音乐|music|apple\s*music)(?:应用|app|软件|程序)?\s*"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if _looks_like_generic_music_play_request(text):
        return "play"
    if re.fullmatch(r"(?:播放|放)(?:一下)?(?:音乐|music|apple\s*music)(?:应用|app|软件|程序)?", lowered):
        return "play"
    if re.fullmatch(r"(?:play|start)\s+(?:music|apple\s*music)(?:\s+app)?", lowered):
        return "play"
    return ""


def _is_apple_music_open_and_play_request(text: str) -> bool:
    lowered = text.lower()
    if _music_app_generic_play_open_name(text) == "Music":
        return True
    if _looks_like_generic_music_play_request(text):
        return True
    if _looks_like_scoped_generic_music_play_request(text):
        return True
    return bool(
        re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:播放|放)(?:一下)?\s*"
            r"(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:启动|打开|运行|拉起|开启)(?:一下)?\s*"
            r"(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:并|然后|后|之后|再)\s*(?:开始)?(?:播放|放一下|播放一下)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:播放一下|播一下|放一下|播放|播|放|开始播放|继续播放)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(r"(?:play|start)\s+(?:apple\s*music|music)(?:\s+app)?", lowered)
    )


def _looks_like_scoped_generic_music_play_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:用|在|通过)\s*(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?"
            r"(?:里|中|上|内|里面)?\s*"
            r"(?:随便|随机)?"
            r"(?:(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲)|"
            r"(?:来点|来些)(?:音乐|歌|歌曲)|(?:放|播放|播)(?:一下)?(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(
            r"(?:play|start)\s+(?:a\s+)?(?:song|music|some\s+music)\s+"
            r"(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?",
            lowered,
        )
    )


def _looks_like_generic_music_play_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:随便|随机)?"
            r"(?:(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲)|"
            r"(?:来点|来些)(?:音乐|歌|歌曲)|(?:放|播放|播)(?:一下)?(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:随便|随机)?(?:来|放|播放|播)(?:一首|首)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(r"(?:play|start)\s+(?:a\s+)?(?:song|music|some\s+music)", lowered)
    )


def _looks_like_project_or_design_request(text: str) -> bool:
    value = str(text or "").strip()
    if len(value) < 160 and "\n" not in value:
        return False
    lowered = value.lower()
    has_project_terms = bool(
        re.search(
            r"(?:class=|css|html|ui|界面|设计|设计风格|功能|需求|要求|验收|生成一个新的|不要覆盖|保持现有功能)",
            lowered,
            flags=re.IGNORECASE,
        )
    )
    has_spec_shape = bool(
        re.search(r"(?:^|\n)\s*\d+[.、]", value)
        or re.search(r"(?:要求|需求|验收)\s*[：:]", value)
        or re.search(r"class\s*=", value, flags=re.IGNORECASE)
    )
    return has_project_terms and has_spec_shape


def _desktop_hotkey(text: str) -> dict[str, Any] | None:
    named = _desktop_named_hotkey(text)
    if named:
        return named
    hotkey_part = (
        r"(?:command|cmd|shift|option|alt|control|ctrl|⌘|⇧|⌥|⌃|fn|"
        r"回车|确认|确定|换行|空格|退出|删除|退格|上箭头|下箭头|左箭头|右箭头|"
        r"enter|return|escape|esc|tab|space|delete|backspace|up|down|left|right|"
        r"[A-Za-z0-9])"
    )
    suffix = r"\s*(?:键|快捷键|热键|一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$"
    patterns = (
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:按下|按|发送|触发|快捷键|热键|组合键|按键)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})+){suffix}",
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按下|按|发送|触发)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part}){suffix}",
        rf"^press\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)\s*[.!?]*$",
        rf"^trigger\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)\s*[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_hotkey_combo(match.group("combo"))
        if parsed:
            return parsed
    return None


def _desktop_named_hotkey(text: str) -> dict[str, Any] | None:
    phrase = _normalize_named_hotkey_phrase(text)
    mapping: dict[str, tuple[str, tuple[str, ...]]] = {
        "复制": ("c", ("command",)),
        "复制选中内容": ("c", ("command",)),
        "复制选中文字": ("c", ("command",)),
        "复制选中的文字": ("c", ("command",)),
        "复制当前选中内容": ("c", ("command",)),
        "复制当前选中文字": ("c", ("command",)),
        "copy": ("c", ("command",)),
        "copyselection": ("c", ("command",)),
        "copyselectedtext": ("c", ("command",)),
        "粘贴": ("v", ("command",)),
        "paste": ("v", ("command",)),
        "全选": ("a", ("command",)),
        "selectall": ("a", ("command",)),
        "撤销": ("z", ("command",)),
        "undo": ("z", ("command",)),
        "重做": ("z", ("command", "shift")),
        "redo": ("z", ("command", "shift")),
        "保存": ("s", ("command",)),
        "保存文档": ("s", ("command",)),
        "保存当前文档": ("s", ("command",)),
        "保存文件": ("s", ("command",)),
        "save": ("s", ("command",)),
        "savefile": ("s", ("command",)),
        "savedocument": ("s", ("command",)),
        "刷新": ("r", ("command",)),
        "浏览器刷新": ("r", ("command",)),
        "网页刷新": ("r", ("command",)),
        "当前网页刷新": ("r", ("command",)),
        "当前页刷新": ("r", ("command",)),
        "reload": ("r", ("command",)),
        "refresh": ("r", ("command",)),
        "重新打开关闭的标签页": ("t", ("command", "shift")),
        "重新打开上个关闭的标签页": ("t", ("command", "shift")),
        "恢复关闭的标签页": ("t", ("command", "shift")),
        "恢复上一个关闭的标签页": ("t", ("command", "shift")),
        "reopenclosedtab": ("t", ("command", "shift")),
        "reopentheclosedtab": ("t", ("command", "shift")),
        "reopenlastclosedtab": ("t", ("command", "shift")),
        "restoreclosedtab": ("t", ("command", "shift")),
        "下一个标签页": ("]", ("command", "shift")),
        "下个标签页": ("]", ("command", "shift")),
        "下一标签页": ("]", ("command", "shift")),
        "切到下一个标签页": ("]", ("command", "shift")),
        "切换到下一个标签页": ("]", ("command", "shift")),
        "nexttab": ("]", ("command", "shift")),
        "switchtonexttab": ("]", ("command", "shift")),
        "上一个标签页": ("[", ("command", "shift")),
        "上个标签页": ("[", ("command", "shift")),
        "上一标签页": ("[", ("command", "shift")),
        "切到上一个标签页": ("[", ("command", "shift")),
        "切换到上一个标签页": ("[", ("command", "shift")),
        "previoustab": ("[", ("command", "shift")),
        "switchtoprevioustab": ("[", ("command", "shift")),
        "查找": ("f", ("command",)),
        "打开查找": ("f", ("command",)),
        "打开查找框": ("f", ("command",)),
        "打开搜索框": ("f", ("command",)),
        "页面查找": ("f", ("command",)),
        "页面内查找": ("f", ("command",)),
        "页面里查找": ("f", ("command",)),
        "当前页查找": ("f", ("command",)),
        "find": ("f", ("command",)),
        "findinpage": ("f", ("command",)),
        "findonpage": ("f", ("command",)),
        "pagefind": ("f", ("command",)),
        "openfind": ("f", ("command",)),
        "openfindbox": ("f", ("command",)),
        "新建标签页": ("t", ("command",)),
        "新标签页": ("t", ("command",)),
        "打开新标签页": ("t", ("command",)),
        "newtab": ("t", ("command",)),
        "关闭标签页": ("w", ("command",)),
        "关闭当前标签页": ("w", ("command",)),
        "关闭浏览器标签页": ("w", ("command",)),
        "关闭这个标签页": ("w", ("command",)),
        "closecurrenttab": ("w", ("command",)),
        "closethecurrenttab": ("w", ("command",)),
        "closetab": ("w", ("command",)),
        "回车": ("return", ()),
        "确认": ("return", ()),
        "确定": ("return", ()),
        "enter": ("return", ()),
        "return": ("return", ()),
    }
    combo = mapping.get(phrase)
    if combo is None:
        return None
    key, modifiers = combo
    return {"key": key, "modifiers": list(modifiers)}


def _desktop_safe_shortcut_action(text: str) -> str:
    phrase = _normalize_named_hotkey_phrase(text)
    mapping = {
        "复制": "copy",
        "复制选中内容": "copy",
        "复制选中的内容": "copy",
        "复制选中文字": "copy",
        "复制选中的文字": "copy",
        "复制当前选中内容": "copy",
        "复制当前选中的内容": "copy",
        "复制当前选中文字": "copy",
        "复制当前选中的文字": "copy",
        "复制一下选中内容": "copy",
        "复制一下选中的内容": "copy",
        "复制一下选中文字": "copy",
        "复制一下选中的文字": "copy",
        "copy": "copy",
        "copyselection": "copy",
        "copyselectedtext": "copy",
        "粘贴": "paste",
        "粘贴剪贴板": "paste",
        "粘贴剪贴板内容": "paste",
        "剪贴板内容粘贴": "paste",
        "把剪贴板内容粘贴": "paste",
        "把剪贴板内容粘贴到当前输入框": "paste",
        "把剪贴板内容粘贴到输入框": "paste",
        "剪贴板内容粘贴到当前输入框": "paste",
        "剪贴板内容粘贴到输入框": "paste",
        "粘贴到这里": "paste",
        "粘贴到这": "paste",
        "粘贴在这里": "paste",
        "粘贴到当前输入框": "paste",
        "粘贴到输入框": "paste",
        "粘贴到当前窗口": "paste",
        "粘贴到前台": "paste",
        "粘贴进当前输入框": "paste",
        "粘贴进输入框": "paste",
        "粘贴进当前窗口": "paste",
        "粘贴进前台": "paste",
        "粘贴在当前输入框": "paste",
        "粘贴在输入框": "paste",
        "粘贴在当前窗口": "paste",
        "粘贴在前台": "paste",
        "paste": "paste",
        "pasteclipboard": "paste",
        "pasteclipboardcontents": "paste",
        "pasteintocurrentinput": "paste",
        "pasteintoinput": "paste",
        "pasteintocurrentwindow": "paste",
        "pasteintoforeground": "paste",
        "pasteincurrentinput": "paste",
        "pasteininput": "paste",
        "pasteincurrentwindow": "paste",
        "pasteinforeground": "paste",
        "全选": "select_all",
        "selectall": "select_all",
        "撤销": "undo",
        "undo": "undo",
        "重做": "redo",
        "redo": "redo",
        "刷新": "refresh",
        "浏览器刷新": "refresh",
        "网页刷新": "refresh",
        "当前网页刷新": "refresh",
        "当前页刷新": "refresh",
        "刷新一下页面": "refresh",
        "刷新下页面": "refresh",
        "刷新页面": "refresh",
        "刷新一下当前页": "refresh",
        "刷新下当前页": "refresh",
        "刷新当前页": "refresh",
        "刷新一下当前网页": "refresh",
        "刷新下当前网页": "refresh",
        "刷新当前网页": "refresh",
        "刷新一下网页": "refresh",
        "刷新下网页": "refresh",
        "刷新网页": "refresh",
        "reload": "refresh",
        "refresh": "refresh",
        "重新打开关闭的标签页": "reopen_closed_tab",
        "重新打开刚关闭的标签页": "reopen_closed_tab",
        "重新打开刚刚关闭的标签页": "reopen_closed_tab",
        "重新打开最近关闭的标签页": "reopen_closed_tab",
        "重新打开上次关闭的标签页": "reopen_closed_tab",
        "重新打开上个关闭的标签页": "reopen_closed_tab",
        "重新打开上一个关闭的标签页": "reopen_closed_tab",
        "恢复关闭的标签页": "reopen_closed_tab",
        "恢复刚关闭的标签页": "reopen_closed_tab",
        "恢复刚刚关闭的标签页": "reopen_closed_tab",
        "恢复最近关闭的标签页": "reopen_closed_tab",
        "恢复上次关闭的标签页": "reopen_closed_tab",
        "恢复上个关闭的标签页": "reopen_closed_tab",
        "恢复上一个关闭的标签页": "reopen_closed_tab",
        "reopenclosedtab": "reopen_closed_tab",
        "reopentheclosedtab": "reopen_closed_tab",
        "reopenlastclosedtab": "reopen_closed_tab",
        "restoreclosedtab": "reopen_closed_tab",
        "关闭标签页": "close_tab",
        "关闭当前标签页": "close_tab",
        "关闭浏览器标签页": "close_tab",
        "关闭这个标签页": "close_tab",
        "关掉标签页": "close_tab",
        "关掉当前标签页": "close_tab",
        "关掉浏览器标签页": "close_tab",
        "关掉这个标签页": "close_tab",
        "closetab": "close_tab",
        "closecurrenttab": "close_tab",
        "closethecurrenttab": "close_tab",
        "下一个标签页": "next_tab",
        "下个标签页": "next_tab",
        "下一标签页": "next_tab",
        "切到下一个标签页": "next_tab",
        "切换到下一个标签页": "next_tab",
        "nexttab": "next_tab",
        "switchtonexttab": "next_tab",
        "上一个标签页": "previous_tab",
        "上个标签页": "previous_tab",
        "上一标签页": "previous_tab",
        "切到上一个标签页": "previous_tab",
        "切换到上一个标签页": "previous_tab",
        "previoustab": "previous_tab",
        "switchtoprevioustab": "previous_tab",
        "返回上一页": "browser_back",
        "回到上一页": "browser_back",
        "网页后退": "browser_back",
        "浏览器后退": "browser_back",
        "后退一页": "browser_back",
        "后退": "browser_back",
        "goback": "browser_back",
        "back": "browser_back",
        "前进一页": "browser_forward",
        "网页前进": "browser_forward",
        "浏览器前进": "browser_forward",
        "前进": "browser_forward",
        "goforward": "browser_forward",
        "forward": "browser_forward",
        "查找": "find",
        "打开查找": "find",
        "打开查找框": "find",
        "打开搜索框": "find",
        "页面查找": "find",
        "页面内查找": "find",
        "页面里查找": "find",
        "当前页查找": "find",
        "find": "find",
        "findinpage": "find",
        "findonpage": "find",
        "pagefind": "find",
        "openfind": "find",
        "openfindbox": "find",
        "新建标签页": "new_tab",
        "新标签页": "new_tab",
        "打开新标签页": "new_tab",
        "开新标签页": "new_tab",
        "开一个新标签页": "new_tab",
        "newtab": "new_tab",
        "新建窗口": "new_window",
        "新窗口": "new_window",
        "打开新窗口": "new_window",
        "开新窗口": "new_window",
        "开一个新窗口": "new_window",
        "newwindow": "new_window",
        "新建文档": "new_document",
        "新文档": "new_document",
        "新建文件": "new_document",
        "新文件": "new_document",
        "开新文档": "new_document",
        "开一个新文档": "new_document",
        "开新文件": "new_document",
        "开一个新文件": "new_document",
        "新建表格": "new_document",
        "新表格": "new_document",
        "新建工作簿": "new_document",
        "新工作簿": "new_document",
        "新建演示文稿": "new_document",
        "新演示文稿": "new_document",
        "新建幻灯片": "new_document",
        "新幻灯片": "new_document",
        "新建ppt": "new_document",
        "新ppt": "new_document",
        "newdocument": "new_document",
        "newfile": "new_document",
        "newworkbook": "new_document",
        "newspreadsheet": "new_document",
        "newpresentation": "new_document",
        "newslide": "new_document",
        "makeanewdocument": "new_document",
        "createanewdocument": "new_document",
        "makenewdocument": "new_document",
        "createnewdocument": "new_document",
        "makeanewfile": "new_document",
        "createanewfile": "new_document",
        "makenewfile": "new_document",
        "createnewfile": "new_document",
        "makeanewworkbook": "new_document",
        "createanewworkbook": "new_document",
        "makenewworkbook": "new_document",
        "createnewworkbook": "new_document",
        "makeanewspreadsheet": "new_document",
        "createanewspreadsheet": "new_document",
        "makenewspreadsheet": "new_document",
        "createnewspreadsheet": "new_document",
        "makeanewpresentation": "new_document",
        "createanewpresentation": "new_document",
        "makenewpresentation": "new_document",
        "createnewpresentation": "new_document",
        "新建笔记": "new_note",
        "新建一个笔记": "new_note",
        "新建一条笔记": "new_note",
        "新建一篇笔记": "new_note",
        "新笔记": "new_note",
        "新建备忘录": "new_note",
        "新建一个备忘录": "new_note",
        "新建一条备忘录": "new_note",
        "新建一篇备忘录": "new_note",
        "新备忘录": "new_note",
        "新建提醒事项": "new_reminder",
        "新建一个提醒事项": "new_reminder",
        "新建一条提醒事项": "new_reminder",
        "新建一项提醒事项": "new_reminder",
        "新建提醒": "new_reminder",
        "新提醒": "new_reminder",
        "新建日程": "new_event",
        "新建一个日程": "new_event",
        "新建一条日程": "new_event",
        "新建日历事件": "new_event",
        "新建一个日历事件": "new_event",
        "新日程": "new_event",
        "新建事件": "new_event",
        "新建一个事件": "new_event",
        "新事件": "new_event",
        "newnote": "new_note",
        "makeanewnote": "new_note",
        "createanewnote": "new_note",
        "makenewnote": "new_note",
        "createnewnote": "new_note",
        "newreminder": "new_reminder",
        "makeanewreminder": "new_reminder",
        "createanewreminder": "new_reminder",
        "makenewreminder": "new_reminder",
        "createnewreminder": "new_reminder",
        "newevent": "new_event",
        "newcalendarevent": "new_event",
        "makeanewevent": "new_event",
        "createanewevent": "new_event",
        "makenewevent": "new_event",
        "createnewevent": "new_event",
        "makeanewcalendarevent": "new_event",
        "createanewcalendarevent": "new_event",
        "makenewcalendarevent": "new_event",
        "createnewcalendarevent": "new_event",
    }
    return mapping.get(phrase, "")


def _desktop_safe_key(text: str) -> dict[str, Any] | None:
    if _is_next_foreground_focus_request(text):
        return {"action": "tab", "repeat_count": 1}
    if _is_previous_foreground_focus_request(text):
        return {"action": "shift_tab", "repeat_count": 1}
    count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    key = (
        r"(?P<{name}>esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right|"
        r"退出|取消|制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|向上键|向下键|向左键|向右键|上|下|左|右|"
        r"上一页键|下一页键|上一页|下一页|home\s*键|end\s*键)"
    )
    patterns = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:按一下|按下|按|发送|触发)\s*"
            rf"(?:{count.format(name='count_before')}\s*(?:次|下)\s*)?"
            rf"{key.format(name='key')}"
            rf"(?:\s*{count.format(name='count_after')}\s*(?:次|下))?"
            r"\s*(?:键)?(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:please\s+)?(?:press|send|hit)\s+(?:the\s+)?"
            rf"{key.format(name='key_en')}"
            rf"(?:\s+{count.format(name='count_en')}\s*(?:times?)?)?\s*$"
        ),
        (
            rf"^(?:please\s+)?{count.format(name='count_en_before')}\s*(?:times?\s+)?"
            r"(?:press|send|hit)\s+(?:the\s+)?"
            rf"{key.format(name='key_en_before')}\s*$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_key = (
            groups.get("key")
            or groups.get("key_en")
            or groups.get("key_en_before")
            or ""
        )
        action = _safe_key_action(raw_key)
        repeat_count = _safe_key_repeat_count(
            groups.get("count_before")
            or groups.get("count_after")
            or groups.get("count_en")
            or groups.get("count_en_before")
        )
        if action and repeat_count:
            return {"action": action, "repeat_count": repeat_count}
    return None


def _is_next_foreground_focus_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到|focus\s+)?\s*"
            r"(?:下一个|下一项|下个|next)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目|field|input|control|element)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:focus|move|go|jump|tab)\s+(?:to\s+)?(?:the\s+)?next\s+"
            r"(?:field|input|control|element)\s*$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_previous_foreground_focus_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到|focus\s+)?\s*"
            r"(?:上一个|上一项|上个|previous|prev)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目|field|input|control|element)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|嘛|吧|呢)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:focus|move|go|jump)\s+(?:to\s+)?(?:the\s+)?(?:previous|prev)\s+"
            r"(?:field|input|control|element)\s*$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _safe_key_action(value: str) -> str:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    return {
        "esc": "escape",
        "escape": "escape",
        "退出": "escape",
        "取消": "escape",
        "tab": "tab",
        "制表": "tab",
        "制表键": "tab",
        "up": "arrow_up",
        "uparrow": "arrow_up",
        "arrowup": "arrow_up",
        "上": "arrow_up",
        "上箭头": "arrow_up",
        "向上箭头": "arrow_up",
        "往上箭头": "arrow_up",
        "朝上箭头": "arrow_up",
        "向上键": "arrow_up",
        "down": "arrow_down",
        "downarrow": "arrow_down",
        "arrowdown": "arrow_down",
        "下": "arrow_down",
        "下箭头": "arrow_down",
        "向下箭头": "arrow_down",
        "往下箭头": "arrow_down",
        "朝下箭头": "arrow_down",
        "向下键": "arrow_down",
        "left": "arrow_left",
        "leftarrow": "arrow_left",
        "arrowleft": "arrow_left",
        "左": "arrow_left",
        "左箭头": "arrow_left",
        "向左箭头": "arrow_left",
        "往左箭头": "arrow_left",
        "朝左箭头": "arrow_left",
        "向左键": "arrow_left",
        "right": "arrow_right",
        "rightarrow": "arrow_right",
        "arrowright": "arrow_right",
        "右": "arrow_right",
        "右箭头": "arrow_right",
        "向右箭头": "arrow_right",
        "往右箭头": "arrow_right",
        "朝右箭头": "arrow_right",
        "向右键": "arrow_right",
        "home": "home",
        "home键": "home",
        "end": "end",
        "end键": "end",
        "pageup": "page_up",
        "上一页键": "page_up",
        "上一页": "page_up",
        "pagedown": "page_down",
        "下一页键": "page_down",
        "下一页": "page_down",
    }.get(compact, "")


def _safe_key_repeat_count(value: str | None) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return 1
    if raw.isdigit():
        count = int(raw)
    else:
        count = _SCROLL_PAGE_COUNTS.get(raw, 0)
    return count if 1 <= count <= 20 else 0


_SCROLL_PAGE_COUNTS = {
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
    "十": 10,
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
}


def _desktop_safe_scroll(text: str) -> dict[str, Any] | None:
    page_count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    zh_prefix = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|把|将)?\s*(?:当前|前台|这个|该)?"
        r"(?:窗口|界面|应用|app|网页|页面|屏幕)?(?:上|里|中|内)?\s*"
    )
    patterns = (
        (
            zh_prefix
            + r"(?P<direction>向下|往下|朝下|下|向上|往上|朝上|上)"
            + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)"
            + rf"(?:\s*{page_count.format(name='count')}\s*(?:页|屏|次))?"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?P<direction_phrase>下滑|上滑|下滚|上滚|下翻|上翻|下一页|上一页)"
            + rf"(?:\s*{page_count.format(name='count_phrase')}\s*(?:页|屏|次))?"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?:翻到|翻至|滚到|滚至|滑到|滑至|转到|转至|跳到|跳至|到)\s*"
            + r"(?P<direction_target>下一页|上一页)"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+"
            r"(?P<direction_en>down|up)"
            + rf"(?:\s+{page_count.format(name='count_en')}\s*(?:pages?|times?)?)?"
            + r"\s*$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+"
            r"(?:the\s+)?(?:current\s+)?(?:page|window|screen)\s+"
            r"(?P<direction_en_target>down|up)"
            + rf"(?:\s+{page_count.format(name='count_en_target')}\s*(?:pages?|times?)?)?"
            + r"\s*$"
        ),
        (
            rf"^(?:please\s+)?{page_count.format(name='count_en_prefix')}\s+"
            r"(?:pages?\s+)?(?:scroll|page)\s+(?P<direction_en_prefix>down|up)\s*$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        direction = (
            groups.get("direction")
            or groups.get("direction_phrase")
            or groups.get("direction_target")
            or groups.get("direction_en")
            or groups.get("direction_en_target")
            or groups.get("direction_en_prefix")
            or ""
        )
        pages = _scroll_page_count(
            groups.get("count")
            or groups.get("count_phrase")
            or groups.get("count_en")
            or groups.get("count_en_target")
            or groups.get("count_en_prefix")
        )
        if direction and pages:
            return {
                "direction": "up" if _scroll_direction_is_up(direction) else "down",
                "pages": pages,
            }
    return None


def _scroll_direction_is_up(value: str) -> bool:
    direction = str(value or "").strip().lower()
    return direction in {"向上", "往上", "朝上", "上", "上滑", "上滚", "上翻", "上一页", "up"}


def _scroll_page_count(value: str | None) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return 1
    if raw.isdigit():
        count = int(raw)
    else:
        count = _SCROLL_PAGE_COUNTS.get(raw, 0)
    return count if 1 <= count <= 10 else 0


def _normalize_named_hotkey_phrase(text: str) -> str:
    phrase = _strip_query(text)
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按一下|按下|按|执行|触发|发送)?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(r"\s*(?:一下|下|一次|键|快捷键|热键|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)$", "", phrase)
    return re.sub(r"[\s._-]+", "", phrase.lower())


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
        "确认": "return",
        "确定": "return",
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
        part = re.sub(r"键$", "", raw_part.lower())
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
    if _browser_type_text_request(text) or _desktop_type_into_ui_element(text):
        return ""
    if _is_next_foreground_focus_request(text) or _is_previous_foreground_focus_request(text):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在前台|向前台|给当前窗口)?"
        r"(?:输入|打字|键入|敲入|打入|打上)\s*(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在前台|向前台|给当前窗口|在当前窗口)\s*(?:写入|写)\s*(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在前台|向前台|给当前窗口|在当前窗口)?"
        r"打\s+(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?把\s*(?P<text>.+?)\s*"
        r"(?:输入|打字|键入|敲入|打入|打上|打)\s*(?:进去|到当前窗口|到前台)?$",
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


def _desktop_type_into_ui_element(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    bare_target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field)"
    )
    target_pattern = (
        rf"(?:{bare_target_pattern}|[^。！？!?，,]+?(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text\s+field|textbox|input|field|search\s+field|search\s+box|search\s+bar|"
        r"message\s+field|message\s+box|chat\s+box|address\s+bar))"
    )
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
        r"(?:上|里|中|内|的|里的|中的)?\s*"
        rf"(?P<target>{target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:填写|填入|把|将)?\s*(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
        r"(?:上|里|中|内|的|里的|中的)?\s*"
        rf"(?P<target2>{target_pattern})\s*(?:为|成|:|：)\s*(?P<text2>[^。！？!?]+)$",
        r"^(?:type|enter|fill)\s+(?P<text_en>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?:the\s+)?"
        rf"(?P<target_en>{target_pattern})"
        r"(?:\s+(?:in|on)\s+(?:the\s+)?(?:current|foreground)\s+(?:window|app|application|ui))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_target = groups.get("target") or groups.get("target2") or groups.get("target_en") or ""
        raw_text = groups.get("text") or groups.get("text2") or groups.get("text_en") or ""
        typed_text = _strip_typed_text(raw_text)
        target = _strip_desktop_ui_input_target(raw_target)
        if not target or not typed_text:
            continue
        return {
            "target": target,
            "text": typed_text,
            "role_filter": _desktop_ui_element_role_filter(raw_target),
            "limit": 80,
        }
    return None


def _desktop_safe_type_text(text: str) -> str:
    return _desktop_type_text(text)


def _strip_typed_text(value: str) -> str:
    text = _strip_query(value)
    text = re.sub(r"\s*(?:进去|到当前窗口|到前台|然后回车|并回车)$", "", text)
    text = re.sub(
        r"\s*(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?"
        r"(?:回车|确认|确定|搜索|查找|检索|访问|打开|发送|发出|提交)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:and\s+then|then|and)\s*(?:press\s+)?"
        r"(?:enter|return|search|find|go|visit|open|send|submit|post)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _strip_query(text)


def _desktop_click(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|点|click)\s*"
        r"(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到)\s*(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)\s*"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|点|click)",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            break
    if not match:
        return None
    payload: dict[str, Any] = {
        "x": _number_value(match.group("x")),
        "y": _number_value(match.group("y")),
        "click_count": 2 if match.group("double") else 1,
    }
    return payload


def _desktop_safe_click(text: str) -> dict[str, Any] | None:
    payload = _desktop_click(text)
    if not payload or payload.get("click_count") != 1:
        return None
    return {"x": payload["x"], "y": payload["y"]}


def _desktop_click_ui_element(text: str, *, require_context: bool = True) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<context>(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?(?:上|里|中|内|的|里的|中的)?)\s*"
        r"(?P<label>[^。！？!?，,]+?)"
        r"(?P<kind>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:(?P<double_en>double\s+click)|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)"
        r"(?:\s+(?P<kind_en>button|control|element|field|input|text field|textbox|menu item|menu|checkbox))?"
        r"(?:\s+(?:in|on)\s+(?:the\s+)?(?:current|foreground)\s+(?:window|app|application|ui))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_label = groups.get("label") or groups.get("label_en") or ""
        kind = groups.get("kind") or groups.get("kind_en") or ""
        context = groups.get("context") or ""
        if require_context and not kind and not _desktop_ui_click_has_context(text, context):
            continue
        label = _strip_desktop_ui_element_label(raw_label)
        if not label or _looks_like_click_coordinate_label(label):
            continue
        return {
            "target": label,
            "role_filter": _desktop_ui_element_role_filter(kind or text),
            "limit": 80,
            "click_count": 2 if groups.get("double") or groups.get("double_en") else 1,
        }
    return None


def _desktop_ui_click_has_context(text: str, context: str) -> bool:
    return bool(
        str(context or "").strip()
        or re.search(
            r"(?:当前|前台|界面|窗口|应用|控件|按钮|元素|输入框|文本框|输入栏|菜单|复选框)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:current|foreground)\s+(?:window|app|application|ui)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _strip_desktop_ui_element_label(value: str) -> str:
    label = _strip_query(value)
    label = re.sub(
        r"^(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)(?:上|里|中|内|的|里的|中的)?\s*",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(
        r"\s*(?:按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框|"
        r"搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"button|control|element|field|input|text field|textbox|search field|search box|"
        r"search bar|message field|message box|chat box|address bar|menu item|menu|checkbox)$",
        "",
        label,
        flags=re.IGNORECASE,
    )
    return _strip_query(label)


def _strip_desktop_ui_input_target(value: str) -> str:
    target = _strip_desktop_ui_element_label(value)
    if target and target not in {"在", "向", "给"}:
        return target
    compact = _strip_query(value)
    compact = re.sub(r"^(?:在|向|给)\s*", "", compact)
    target = _strip_desktop_ui_element_label(compact)
    if target:
        return target
    fallback_targets = {
        "搜索框": "搜索",
        "搜索栏": "搜索",
        "消息框": "消息",
        "聊天框": "聊天",
        "地址栏": "地址",
        "search field": "search",
        "search box": "search",
        "search bar": "search",
        "message field": "message",
        "message box": "message",
        "chat box": "chat",
        "address bar": "address",
    }
    return fallback_targets.get(compact.lower(), compact)


def _desktop_ui_element_role_filter(value: str) -> str:
    lowered = str(value or "").lower()
    if re.search(r"(?:按钮|button)", lowered, flags=re.IGNORECASE):
        return "button"
    if re.search(
        r"(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text field|textbox|input|field|search field|search box|search bar|"
        r"message field|message box|chat box|address bar)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return "text"
    if re.search(r"(?:菜单项|菜单|menu item|menu)", lowered, flags=re.IGNORECASE):
        return "menu"
    if re.search(r"(?:复选框|checkbox)", lowered, flags=re.IGNORECASE):
        return "checkbox"
    return ""


def _is_close_current_window_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:关闭|关掉)\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*(?:关闭|关掉)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:close|dismiss)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_minimize_current_window_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:最小化|收起)\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*(?:最小化|收起)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:minimi[sz]e|hide)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_hide_current_app_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:隐藏|收起)\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            r"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*(?:隐藏|收起)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bhide\s+(?:the\s+)?(?:current|foreground|active|this)\s+"
            r"(?:app|application)\b",
            lowered,
        )
    )


def _number_value(value: str) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _percentage_value(value: str) -> int | None:
    try:
        number = int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 100:
        return None
    return number


def _strip_query(value: str) -> str:
    return str(value or "").strip(" 「」『』“”\"'`，,。.!?？！？ ")


def _strip_browser_followup(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再)\s*"
        r"(?:读取|读一下|读下|读一读|提取|抓取|获取|查看|看看|看一下|"
        r"总结|摘要|概括|截取|截图|截屏|截一下|截个图|截|抓屏).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+"
        r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|总结|摘要|概括)"
        r"(?:一下|下)?(?:网页|页面|网站|正文|文字|文本|内容)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:截取|截图|截屏|截一下|截个图|截|抓屏|屏幕截图)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:read|extract|get|summari[sz]e|take\s+a\s+screenshot|screenshot|capture).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _strip_polite_suffix(value: str) -> str:
    return re.sub(
        r"\s*(?:一下|一下儿|一下子|可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)$",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _is_screen_capture_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"(?:截个?图|截图|截屏|屏幕截图|抓屏|拍屏)", text)
        or re.search(r"(?:当前|现在|这个)?(?:屏幕|桌面).{0,8}(?:截图|截屏|截一下|截个图|抓屏|拍屏)", text)
        or re.search(r"(?:截取|截图|截屏|截一下|截个图|截|抓屏|拍屏).{0,8}(?:当前|现在|这个)?(?:屏幕|桌面)", text)
        or re.search(r"(?:看一下|看看|看下|查看|读取).{0,8}(?:当前|现在|这个)?(?:屏幕|桌面)", text)
        or re.search(r"(?:当前|现在|这个)?(?:屏幕|桌面).{0,8}(?:是什么|是啥|内容|画面)", text)
        or "take a screenshot" in lowered
        or "capture the screen" in lowered
        or "screen capture" in lowered
    )


def _is_active_window_request(text: str) -> bool:
    if _is_running_apps_request(text):
        return False
    if re.search(r"(?:关闭|关掉|退出|结束|close|quit|exit)", text, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:哪些|几个|多少).{0,4}(?:窗口|windows?)", text, flags=re.IGNORECASE):
        return False
    if re.search(
        r"(?:列出|列一下|列下|显示|读取).{0,12}(?:窗口|windows?)|"
        r"(?:窗口|windows?).{0,8}(?:列表|清单|列出|列一下|列下)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:窗口|应用|app).{0,8}"
            r"(?:是什么|是啥|哪个|名字|标题)?",
            text,
        )
        or re.search(
            r"(?:当前|现在).{0,8}(?:用的是|正在用).{0,8}(?:哪个|什么).{0,4}(?:app|应用)",
            text,
            flags=re.IGNORECASE,
        )
        or "active window" in lowered
        or "foreground window" in lowered
        or "current window" in lowered
        or re.search(r"\b(?:what|which)\s+(?:app|application)\s+am\s+i\s+using\b", lowered)
        or re.search(r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?(?:active|foreground|frontmost)\s+(?:app|application)\b", lowered)
        or re.search(r"\b(?:what|which)\s+window\s+is\s+(?:active|current|foreground)\b", lowered)
    )


__all__ = [
    "daily_desktop_entrypoint_tool_requests",
    "daily_desktop_intent_candidates",
    "daily_desktop_intent_sequence_candidates",
    "daily_desktop_intent_tool_request",
    "daily_desktop_intent_tool_requests",
    "daily_desktop_recovery_prompt",
]
