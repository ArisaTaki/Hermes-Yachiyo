"""Conservative daily desktop intent planner for Chat entrypoints."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlparse


_APP_ALIASES = {
    "applemusic": "Music",
    "music": "Music",
    "音乐": "Music",
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
    "settings": "System Settings",
    "系统设置": "System Settings",
    "设置": "System Settings",
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

_COMMON_REVEAL_PATHS = {
    "desktop": "~/Desktop",
    "desktopfolder": "~/Desktop",
    "桌面": "~/Desktop",
    "桌面文件夹": "~/Desktop",
    "downloads": "~/Downloads",
    "downloadsfolder": "~/Downloads",
    "下载": "~/Downloads",
    "下载文件夹": "~/Downloads",
    "documents": "~/Documents",
    "documentsfolder": "~/Documents",
    "文档": "~/Documents",
    "文档文件夹": "~/Documents",
    "文稿": "~/Documents",
    "文稿文件夹": "~/Documents",
    "home": "~",
    "homefolder": "~",
    "主目录": "~",
    "用户文件夹": "~",
    "applications": "/Applications",
    "applicationsfolder": "/Applications",
    "applicationfolder": "/Applications",
    "应用程序": "/Applications",
    "应用程序文件夹": "/Applications",
}

_APP_STATUS_PATTERNS = (
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
    """Return a structured low-risk desktop tool request for clear daily Chat intents."""

    allowed = {str(tool or "").strip() for tool in allowed_tools}
    for request in daily_desktop_intent_candidates(context):
        if str(request.get("tool") or "") in allowed:
            return request
    return None


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

    url = _browser_open_url(text)
    if url:
        candidates.append(_request("browser.open_url", {"url": url}))

    named_site_url = _browser_named_site_url(text)
    if named_site_url:
        candidates.append(_request("browser.open_url", {"url": named_site_url}))

    if _is_browser_extract_text_request(text):
        candidates.append(_request("browser.extract_text", {}))

    if _is_browser_screenshot_request(text):
        candidates.append(
            _request("browser.screenshot", {"reason": "user asked to capture the browser page"})
        )

    if _is_browser_current_page_request(text):
        candidates.append(_request("browser.current_page", {}))

    volume_payload = _system_volume_request(text)
    if volume_payload is not None:
        candidates.append(_request("system.volume", volume_payload))

    clipboard_text = _clipboard_write_text(text)
    if clipboard_text:
        candidates.append(_request("clipboard.write", {"text": clipboard_text}))

    if _is_running_apps_request(text):
        candidates.append(_request("desktop.running_apps", {}))

    windows_payload = _desktop_windows_request(text)
    if windows_payload is not None:
        candidates.append(_request("desktop.windows", windows_payload))

    app_status_name = _app_status_name(text)
    if app_status_name:
        candidates.append(_request("app.status", {"app_name": app_status_name}))

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

    if not _looks_like_app_status_request(text):
        search_url = _browser_search_url(text)
        if search_url:
            candidates.append(_request("browser.open_url", {"url": search_url}))

    open_path = _desktop_open_path(text)
    if open_path:
        candidates.append(_request("desktop.open_path", {"path": open_path}))

    reveal_path = _desktop_reveal_path(text)
    if reveal_path:
        candidates.append(_request("desktop.reveal_path", {"path": reveal_path}))

    music_control = _music_control_action(text)
    if music_control:
        candidates.append(_request("media.apple_music_control", {"action": music_control}))

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
        r"(?:为什么|为何|为啥|怎么回事).{0,16}"
        r"(?:不能|无法|没法|不会).{0,16}"
        r"(?:控制|操作|执行|打开应用|启动应用|播放音乐|点击|输入|截图|截屏|读取窗口)",
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


def _browser_named_site_url(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|访问|浏览|前往|去)\s*(?P<site>[^。！？!?，,]+)",
        r"(?:open|visit|browse|go to)\s+(?P<site>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        site = _normalize_site_name(match.group("site"))
        if site:
            return site
    return ""


def _normalize_site_name(value: str) -> str:
    site = _strip_polite_suffix(_strip_query(value))
    site = re.sub(r"^(?:一下|下|这个|那个)\s*", "", site)
    site = re.sub(r"\s*(?:网页|网站|站点|site|website)$", "", site, flags=re.IGNORECASE)
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


def _looks_like_search_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
            r"(?:搜索|搜一下|搜|查一下|查查|检索)\s*",
            text,
        )
        or re.search(r"^(?:search|google|look up)\b\s+", lowered)
    )


def _browser_search_url(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
        r"(?:搜索|搜一下|搜|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)",
        r"\b(?:search|google|look up)\b\s+(?:for\s+)?(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.group("query"))
        if query:
            return f"https://www.google.com/search?q={quote_plus(query)}"
    return ""


def _strip_search_query(value: str) -> str:
    query = _strip_query(value)
    query = re.sub(r"^(?:一下|下|这个|那个)\s*", "", query)
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
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|浏览器).{0,10}(?:正文|文字|文本|内容)?",
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


def _system_volume_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    level_patterns = (
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:调到|调至|设为|设置为|设置到)\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?",
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
        r"(?:把|将)\s*(?P<text>.+?)\s*(?:复制|拷贝|写入|放到|放进|保存到)\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
        r"(?:复制|拷贝|写入)\s*(?P<text>.+?)\s*(?:到|进|至)\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
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


def _desktop_windows_request(text: str) -> dict[str, str] | None:
    if _is_active_window_request(text):
        return None
    app_patterns = (
        r"(?:list|show|read)\s+(?P<app>[^.!?]+?)\s+windows",
        r"(?P<app>[^.!?]+?)\s+windows\?",
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


def _is_general_windows_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:列出|查看|看看|显示|读取).{0,8}"
            r"(?:当前|现在|桌面|打开|已打开|所有)?.{0,8}(?:窗口|windows?)",
            text,
        )
        or re.search(r"(?:打开|已打开|现在|当前|桌面|所有).{0,8}(?:有哪些|什么|几个|多少).{0,4}(?:窗口)", text)
        or re.search(r"\b(?:list|show|read|what|which)\s+(?:open\s+)?windows\b", lowered)
        or re.search(r"\bopen\s+windows\b", lowered)
    )


def _looks_like_generic_window_scope(value: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    return compact in {
        "",
        "当前",
        "现在",
        "桌面",
        "系统",
        "所有",
        "全部",
        "打开",
        "打开的",
        "已打开",
        "已打开的",
        "open",
        "all",
        "current",
        "desktop",
        "windows",
    }


def _looks_like_app_status_request(text: str) -> bool:
    if _is_running_apps_request(text):
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _APP_STATUS_PATTERNS)


def _desktop_open_path(text: str) -> str:
    if re.search(r"\bin\s+(?:the\s+)?finder\b", text, flags=re.IGNORECASE):
        return ""
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|开启)\s*(?P<path>{path_token})",
        rf"\bopen\s+(?P<path>{path_token})\b",
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
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示|显示一下|定位|找一下|找到|打开)\s*(?P<path>{path_token})",
        rf"(?:show|reveal|locate|open)\s+(?P<path>{path_token})(?:\s+in\s+(?:the\s+)?finder)?",
        rf"(?P<path>{path_token})\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示|显示一下|定位|找一下|找到|reveal|show)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"在\s*(?:finder|访达)\s*(?:中|里|内)?\s*"
        r"(?:显示|显示一下|定位|找一下|找到|打开)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|显示|显示一下|定位|找一下|找到)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:show|reveal|locate|open)\s+(?P<path>[^.!?]+?)\s+in\s+(?:the\s+)?finder",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        path = _normalize_reveal_path(match.group("path"))
        if path:
            return path
    return ""


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


def _app_focus_name(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_window_target(raw_app):
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
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:显示|还原|恢复|取消隐藏)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:把|将)\s*(?P<app>[^。！？!?，,]+?)\s*(?:显示出来|还原|恢复|取消隐藏)",
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
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_open_name(text: str) -> str:
    media_app = _media_app_open_name(text)
    if media_app:
        return media_app
    permission_settings = _permission_settings_open_name(text)
    if permission_settings:
        return permission_settings
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""

    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<verb>打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+)",
        r"(?P<verb>open|launch|start)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _normalize_site_name(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if _looks_like_generic_app_open_target(raw_app):
            continue
        if app_name:
            return app_name
    return ""


def _permission_settings_open_name(text: str) -> str:
    lowered = text.lower()
    if re.search(
        r"(?:打开|启动|开启|拉起).{0,8}"
        r"(?:桌面权限|桌面执行权限|本地工具权限|需要的权限|缺少的权限|权限设置|权限页面)",
        text,
    ):
        return "隐私与安全性"
    if re.search(
        r"\b(?:open|launch|show)\s+(?:desktop|missing|required|permission|permissions)"
        r".{0,24}(?:settings|page|pane)\b",
        lowered,
    ):
        return "Privacy & Security"
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
    return _APP_ALIASES.get(compact, app)


def _strip_app_name(value: str) -> str:
    app = _strip_query(value)
    app = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", app)
    app = re.sub(r"\s*(?:应用|app|软件|程序)$", "", app, flags=re.IGNORECASE)
    app = _strip_polite_suffix(app)
    return app.strip()


def _looks_like_generic_app_open_target(value: str) -> bool:
    app = _strip_app_name(value)
    if not app:
        return True
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in _APP_ALIASES:
        return False
    lowered = app.lower()
    if re.search(r"(?:命令|指令|脚本|代码|任务|测试)", lowered):
        return True
    if re.search(r"\b(?:command|shell|script|code|test)\b", lowered):
        return True
    if re.fullmatch(r"(?:一个|一条|某个|这个|那个).+", app):
        return True
    return False


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
    if _looks_like_generic_music_play_request(text):
        return ""
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
    }


def _music_control_action(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:下一首|下一曲|下首|切下一首|跳下一首|下一首歌)", text) or re.search(
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


def _looks_like_generic_music_play_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:(?:来点|来些)(?:音乐|歌|歌曲)|(?:放|播放|播)(?:一下)?(?:音乐|歌|歌曲)|"
            r"(?:放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(r"(?:play|start)\s+(?:a\s+)?(?:song|music|some\s+music)", lowered)
    )


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
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:按下|按|发送|触发|快捷键|热键|组合键|按键)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})+)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按下|按|发送|触发)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part})",
        rf"(?:press|send)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)",
        rf"trigger\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)"
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


def _desktop_named_hotkey(text: str) -> dict[str, Any] | None:
    phrase = _normalize_named_hotkey_phrase(text)
    mapping: dict[str, tuple[str, tuple[str, ...]]] = {
        "复制": ("c", ("command",)),
        "复制选中内容": ("c", ("command",)),
        "复制当前选中内容": ("c", ("command",)),
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
        "save": ("s", ("command",)),
        "刷新": ("r", ("command",)),
        "reload": ("r", ("command",)),
        "refresh": ("r", ("command",)),
        "查找": ("f", ("command",)),
        "find": ("f", ("command",)),
        "新建标签页": ("t", ("command",)),
        "新标签页": ("t", ("command",)),
        "打开新标签页": ("t", ("command",)),
        "newtab": ("t", ("command",)),
        "关闭标签页": ("w", ("command",)),
        "关闭当前标签页": ("w", ("command",)),
        "closetab": ("w", ("command",)),
    }
    combo = mapping.get(phrase)
    if combo is None:
        return None
    key, modifiers = combo
    return {"key": key, "modifiers": list(modifiers)}


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
        r"(?:屏幕坐标|屏幕|坐标|位置)?\s*"
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


def _strip_polite_suffix(value: str) -> str:
    return re.sub(
        r"\s*(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)$",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _is_screen_capture_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"(?:截个?图|截图|截屏|屏幕截图|抓屏|拍屏)", text)
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
