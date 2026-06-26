"""Shared desktop intent parsing hints for planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_GENERIC_MUSIC_QUERIES = {
    "",
    "music",
    "apple music",
    "音乐",
    "歌",
    "歌曲",
    "播放器",
    "音乐播放器",
    "apple",
    "个",
    "一下",
    "一首",
    "首",
    "some music",
    "a song",
    "song",
    "songs",
}


def app_control_mode(text: str) -> str:
    return (
        "focus"
        if contains_any(
            text,
            ["切到", "聚焦", "focus", "switch to", "switch ", "activate ", "bring "],
        )
        else "open"
    )


def app_control_tool_candidates(mode: str) -> tuple[str, ...]:
    return ("app.focus", "app.open") if mode == "focus" else ("app.open", "app.focus")


def app_foreground_tool_candidates(mode: str, action: str) -> tuple[str, ...]:
    prefix = "focus" if mode == "focus" else "open"
    alternate = "open" if prefix == "focus" else "focus"
    return (f"app.{prefix}_and_{action}", f"app.{alternate}_and_{action}")


def click_target_hint(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:双击|点击|点一下|点按|单击|按一下|按)\s*(?P<target>[^。！？!?，,]+)",
        r"(?:double\s+click|click|press|tap)\s+(?:the\s+)?(?P<target_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_target = match.groupdict().get("target") or match.groupdict().get("target_en") or ""
        target = clean_target(raw_target)
        if not target:
            continue
        return {
            "target": target,
            "role_filter": role_filter(raw_target),
            "click_count": 2 if contains_any(match.group(0), ["双击", "double click"]) else 1,
        }
    return None


def type_into_ui_hint(text: str, *, app_name: str = "") -> dict[str, Any] | None:
    patterns = (
        r"(?P<target>[^。！？!?，,]{1,40}?(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*(?:输入|键入|填写|填入|写入|写)\s*(?P<text>[^。！？!?，,]+)",
        r"(?P<target_en>[^.!?,]{1,40}?(?:search box|search field|message field|address bar|input|field|text box))\s*(?:type|enter|fill)\s*(?P<text_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_target = match.groupdict().get("target") or match.groupdict().get("target_en") or ""
        raw_text = match.groupdict().get("text") or match.groupdict().get("text_en") or ""
        target = clean_type_target(raw_target, app_name=app_name)
        typed_text = clean_followup_text(raw_text)
        if target and typed_text:
            return {"target": target, "text": typed_text, "role_filter": "text"}
    return None


def safe_type_text_hint(text: str) -> str:
    patterns = (
        r"(?:输入|键入|填写|填入|写入|写)\s*(?P<text>[^。！？!?，,]+)",
        r"(?:type|enter|fill)\s+(?P<text_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = clean_followup_text(
            match.groupdict().get("text") or match.groupdict().get("text_en") or ""
        )
        if typed_text:
            return typed_text
    return ""


def submit_action_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if contains_any(lowered, ["发送", "send"]):
        return "send"
    if contains_any(
        lowered,
        ["搜索", "回车", "确认", "提交", "search", "enter", "return", "confirm", "submit"],
    ):
        return "confirm"
    return ""


def window_list_hint(text: str) -> dict[str, str] | None:
    value = clean(text)
    if not re.search(r"(?:窗口|windows?)", value, flags=re.IGNORECASE):
        return None
    patterns = (
        r"(?:list|show|read)\s+(?:open\s+)?windows\s+(?:in|for|of)\s+(?P<app_en>[^.!?]+)",
        r"(?:what|which)\s+(?:open\s+)?windows\s+(?:are\s+)?(?:open\s+)?"
        r"(?:in|for|of)\s+(?P<app_en_question>[^.!?]+)",
        r"(?:list|show|read)\s+(?P<app_en2>[^.!?]+?)\s+windows",
        r"(?P<app_en3>[^.!?]+?)\s+windows\?",
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:窗口|windows?)\s*(?:列表|清单|list)$",
        r"(?P<app_question>[^。！？!?，,]+?)\s*(?:有|打开了|开了|正在显示)?"
        r"(?:哪些|什么|几个|多少).{0,4}(?:窗口|window)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|看一下|看下|显示|读取)\s*"
        r"(?P<app2>[^。！？!?，,]{1,40}?)\s*(?:的)?\s*(?:窗口|windows?)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = next(
            (
                item
                for item in match.groupdict().values()
                if item is not None and str(item).strip()
            ),
            "",
        )
        app_name = _clean_window_app_name_hint(raw_app)
        return {"app_name": app_name} if app_name else {}
    if re.search(
        r"(?:列出|查看|看看|看一下|看下|显示|读取).{0,12}(?:窗口|windows?)|"
        r"(?:窗口|windows?).{0,8}(?:列表|清单|列出|列一下|列下)|"
        r"\b(?:list|show|read)\s+(?:open\s+)?windows\b",
        value,
        flags=re.IGNORECASE,
    ):
        return {}
    return None


def focus_window_hint(text: str) -> dict[str, str] | None:
    value = clean(text)
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
        r"\b(?:focus|activate|switch to)\s+(?P<app_en>.+?)\s+window\s+"
        r"(?:(?:titled|called|matching|containing)\s+)?(?P<title_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.groupdict().get("app") or match.groupdict().get("app_en") or ""
        raw_title = match.groupdict().get("title") or match.groupdict().get("title_en") or ""
        app_name = _clean_window_app_name_hint(raw_app)
        title = _clean_window_title_hint(raw_title)
        if app_name and title:
            return {"app_name": app_name, "title_contains": title}
    return None


def ui_inspection_hint(text: str) -> dict[str, Any] | None:
    value = clean(text)
    lowered = value.lower()
    if not _looks_like_ui_inspection_request(value, lowered):
        return None
    payload: dict[str, Any] = {
        "role_filter": _ui_role_filter_hint(value),
        "limit": 80,
    }
    app_name = _ui_inspection_app_name_hint(value)
    if app_name:
        payload["app_name"] = app_name
    return payload


def screen_capture_hint(text: str) -> dict[str, Any] | None:
    value = clean(text)
    lowered = value.lower()
    if re.search(r"(?:截图工具|截图面板|屏幕截图工具|screenshot\s*(?:tool|toolbar|panel))", value, flags=re.IGNORECASE):
        return None
    if not _looks_like_screen_capture_request(value, lowered):
        return None
    payload: dict[str, Any] = {"reason": "user asked to capture the screen"}
    app_name = _screen_capture_app_name_hint(value)
    if app_name:
        payload["app_name"] = app_name
    return payload


def app_management_hint(text: str) -> dict[str, str] | None:
    value = clean(text)
    if foreground_management_hint(value):
        return None
    patterns: tuple[tuple[str, str], ...] = (
        (
            "show",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:显示|显示一下|显示出来|调出来|叫出来|还原|恢复|取消隐藏|show|restore|unhide)\s*"
            r"(?P<app>[^。！？!?，,]+)",
        ),
        (
            "show",
            r"(?P<app2>[^。！？!?，,]+?)\s*(?:显示出来|还原|恢复|取消隐藏|show|restore|unhide)$",
        ),
        (
            "hide",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:隐藏|隐藏一下|藏起来|收起|收起来|hide)\s*"
            r"(?P<app3>[^。！？!?，,]+)",
        ),
        (
            "hide",
            r"(?P<app4>[^。！？!?，,]+?)\s*(?:隐藏|藏起来|收起|收起来|hide)$",
        ),
        (
            "minimize",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            r"(?P<app5>[^。！？!?，,]+?)\s*(?:最小化|minimi[sz]e)$",
        ),
        (
            "minimize",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:最小化|minimi[sz]e)\s*(?P<app6>[^。！？!?，,]+)",
        ),
        (
            "quit",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:退出|关闭|关掉|结束|终止|quit|close|exit|terminate)\s*"
            r"(?P<app7>[^。！？!?，,]+)",
        ),
        (
            "quit",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            r"(?P<app8>[^。！？!?，,]+?)\s*(?:退出|关闭|关掉|结束|终止|quit|close|exit|terminate)$",
        ),
    )
    for action, pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        if action == "quit" and re.search(r"(?:窗口|window)", value, flags=re.IGNORECASE):
            continue
        raw_app = next(
            (
                item
                for item in match.groupdict().values()
                if item is not None and str(item).strip()
            ),
            "",
        )
        app_name = _clean_management_app_name_hint(raw_app)
        if app_name:
            return {"action": action, "app_name": app_name}
    return None


def foreground_management_hint(text: str) -> dict[str, str] | None:
    value = clean(text)
    lowered = value.lower()
    if _is_foreground_window_close_request(value, lowered):
        return {"action": "close_window", "scope": "window"}
    if _is_foreground_app_quit_request(value, lowered):
        return {"action": "quit_app", "scope": "app"}
    if _is_foreground_window_minimize_request(value, lowered):
        return {"action": "minimize_window", "scope": "window"}
    if _is_foreground_app_hide_request(value, lowered):
        return {"action": "hide_app", "scope": "app"}
    return None


def hotkey_hint(text: str) -> dict[str, Any] | None:
    value = clean(text)
    if not contains_any(
        value.lower(),
        ["按", "敲", "快捷键", "press", "hit", "tap", "hotkey", "shortcut"],
    ):
        return None
    patterns = (
        r"(?:按|敲|发送快捷键|快捷键)\s*(?:一下|下)?\s*(?P<combo>[^。！？!?，,]+)",
        r"(?:press|hit|tap)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?(?P<combo>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_hotkey_combo(match.group("combo"))
        if parsed:
            return parsed
    return None


def safe_shortcut_hint(text: str) -> dict[str, str] | None:
    value = clean(text)
    action = _safe_shortcut_action_from_hotkey_hint(value) or _safe_shortcut_action_from_phrase(value)
    if not action:
        for part in reversed(
            [
                item.strip()
                for item in re.split(r"(?:然后|再|接着|之后|and\s+then|then|[,，。])", value)
                if item.strip()
            ]
        ):
            action = _safe_shortcut_action_from_phrase(part)
            if action:
                break
    return {"action": action} if action else None


def safe_key_hint(text: str) -> dict[str, Any] | None:
    value = clean(text)
    lowered = value.lower()
    if _looks_like_show_desktop_request(value, lowered):
        return {"action": "show_desktop", "repeat_count": 1}
    if _looks_like_next_focus_request(value, lowered):
        return {"action": "tab", "repeat_count": 1}
    if _looks_like_previous_focus_request(value, lowered):
        return {"action": "shift_tab", "repeat_count": 1}
    count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    key = (
        r"(?P<{name}>esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right|"
        r"退出|取消|制表键|制表|向上箭头|向下箭头|向左箭头|向右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|上方向键|下方向键|左方向键|右方向键|"
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
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        action = _safe_key_action(
            groups.get("key") or groups.get("key_en") or ""
        )
        repeat_count = _bounded_count(
            groups.get("count_before") or groups.get("count_after") or groups.get("count_en"),
            default=1,
            maximum=20,
        )
        if action and repeat_count:
            return {"action": action, "repeat_count": repeat_count}
    return None


def safe_scroll_hint(text: str) -> dict[str, Any] | None:
    value = clean(text)
    count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    zh_prefix = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|把|将)?\s*(?:当前|前台|这个|该)?"
        r"(?:窗口|界面|应用|app|网页|页面|屏幕)?(?:上|里|中|内)?\s*"
    )
    patterns = (
        (
            zh_prefix
            + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)(?:到|至)?\s*"
            + r"(?P<extent>页面底部|页面顶部|底部|底端|最底下|最下面|顶部|顶端|最上面|最上方)"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?P<direction>向下|往下|朝下|下|向上|往上|朝上|上)"
            + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)"
            + rf"(?:\s*{count.format(name='count')}\s*(?:页|屏|次))?"
            + r"(?:一点|点|一些|一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?P<direction_phrase>下滑|上滑|下滚|上滚|下翻|上翻|下一页|上一页)"
            + rf"(?:\s*{count.format(name='count_phrase')}\s*(?:页|屏|次))?"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+"
            r"(?P<direction_en>down|up)"
            + rf"(?:\s+{count.format(name='count_en')}\s*(?:pages?|times?)?)?"
            + r"\s*$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+(?:to\s+)?(?:the\s+)?"
            r"(?P<extent_en>bottom|top)\s*$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        direction = (
            groups.get("extent")
            or groups.get("direction")
            or groups.get("direction_phrase")
            or groups.get("direction_en")
            or groups.get("extent_en")
            or ""
        )
        pages = (
            10
            if groups.get("extent") or groups.get("extent_en")
            else _bounded_count(
                groups.get("count") or groups.get("count_phrase") or groups.get("count_en"),
                default=1,
                maximum=10,
            )
        )
        if direction and pages:
            return {"direction": "up" if _scroll_direction_is_up(direction) else "down", "pages": pages}
    if re.search(
        zh_prefix + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        value,
        flags=re.IGNORECASE,
    ) or re.search(r"^(?:please\s+)?(?:scroll|page)(?:\s+(?:a\s+)?(?:little|bit))?\s*$", value, flags=re.IGNORECASE):
        return {"direction": "down", "pages": 1}
    return None


def safe_click_hint(text: str) -> dict[str, int | float] | None:
    value = clean(text)
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:点击|点一下|点按|单击|点|click)\s*"
        r"(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到)\s*(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x2>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y2>\d+(?:\.\d+)?)\s*"
        r"(?:点击|点一下|点按|单击|点|click)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        x = match.groupdict().get("x") or match.groupdict().get("x2") or ""
        y = match.groupdict().get("y") or match.groupdict().get("y2") or ""
        return {"x": _numeric_value(x), "y": _numeric_value(y)}
    return None


def media_playback_hint(text: str) -> dict[str, str]:
    action = media_action_hint(text)
    return {
        "action": action,
        "app_name": music_app_name_hint(text),
        "query": media_query_hint(text) if action == "play" else "",
        "control_only": "true" if media_control_only_hint(text, action=action) else "",
    }


def media_tool_preview(
    inputs: Mapping[str, Any],
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    allowed = _allowed_tool_set(allowed_tools)
    action = str(inputs.get("action") or "").strip() or "play"
    app_name = str(inputs.get("app_name") or "").strip()
    query = str(inputs.get("query") or "").strip()
    control_only = str(inputs.get("control_only") or "").strip().lower() == "true"
    is_apple_music = not app_name or app_name == "Music"
    if action == "status":
        return _first_allowed(("media.apple_music_status",), allowed), {}
    if query and is_apple_music:
        return _first_allowed(("media.apple_music_play",), allowed), {"query": query}
    if app_name and not is_apple_music:
        if action == "play":
            return _first_allowed(("media.music_app_open_and_play",), allowed), {"app_name": app_name}
        tool_name = _first_allowed(("media.music_app_control", "media.system_control"), allowed)
        payload = {"app_name": app_name, "action": action} if tool_name == "media.music_app_control" else {"action": action}
        return tool_name, payload
    if action == "play":
        if control_only and not app_name:
            tool_name = _first_allowed(("media.system_control", "media.apple_music_control"), allowed)
            return tool_name, {"action": "play"} if tool_name else {}
        tool_name = _first_allowed(
            ("media.apple_music_open_and_play", "media.apple_music_control", "media.system_control"),
            allowed,
        )
        return tool_name, {"action": "play"} if tool_name in {"media.apple_music_control", "media.system_control"} else {}
    if not app_name:
        tool_name = _first_allowed(("media.system_control", "media.apple_music_control"), allowed)
        return tool_name, {"action": action} if tool_name else {}
    tool_name = _first_allowed(("media.apple_music_control", "media.system_control"), allowed)
    return tool_name, {"action": action} if tool_name else {}


def media_action_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if contains_any(lowered, ["当前播放", "现在播放", "正在播放", "播放什么", "status", "currently playing"]):
        return "status"
    if contains_any(lowered, ["下一首", "下一曲", "下首", "切歌", "换歌", "跳过", "next", "skip"]):
        return "next"
    if contains_any(lowered, ["上一首", "上一曲", "previous", "back"]):
        return "previous"
    if contains_any(
        lowered,
        ["暂停", "停一下", "停止", "停止播放", "别放了", "关掉", "pause", "stop playing"],
    ):
        return "pause"
    if contains_any(lowered, ["继续", "恢复播放", "resume", "continue"]):
        return "play"
    if re.search(r"\bput\s+.+\s+on\s+(?:apple\s*music|music)\b", lowered):
        return "play"
    if contains_any(lowered, ["来点", "听点", "听一首", "听首"]):
        return "play"
    if contains_any(lowered, ["播放", "播", "放", "play"]):
        return "play"
    return ""


def media_control_only_hint(text: str, *, action: str = "") -> bool:
    lowered = str(text or "").lower()
    if action in {"next", "previous", "pause"}:
        return not re.search(r"apple\s*music|苹果音乐|spotify|网易云|qq\s*音乐|qq music", lowered)
    if action == "play":
        return contains_any(lowered, ["继续", "恢复播放", "resume", "continue"])
    return False


def music_app_name_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if re.search(r"spotify", lowered):
        return "Spotify"
    if re.search(r"网易云|netease", lowered):
        return "网易云音乐"
    if re.search(r"qq\s*音乐|qq music", lowered):
        return "QQ 音乐"
    if re.search(r"apple\s*music|苹果音乐|音乐(?:应用|app)", lowered):
        return "Music"
    return ""


def media_query_hint(text: str) -> str:
    value = clean(text)
    patterns = (
        r"(?:put|play)\s+(?P<query_put>.+?)\s+(?:on|in|with)\s+(?:apple\s*music|music)",
        r"(?:search|find)\s+(?:apple\s*music|music)\s+for\s+(?P<query_search>.+?)\s+(?:and\s+)?(?:play|start)",
        r"(?:open|launch|start)\s+(?:apple\s*music|music)\s+(?:and\s+)?(?:search|find)\s+(?P<query_open_search>.+?)\s+(?:and\s+)?(?:play|start)",
        r"(?:搜索|查找|找)\s*(?P<query_zh_search>[^。！？!?，,]+?)(?:并|然后|再)?(?:播放|播|放)(?:一下)?",
        r"(?P<query_zh_suffix>[^。！？!?，,]+?)(?:播放|播|放)(?:一下)?$",
        r"(?:播放|播|放)(?:一下|一首|首|个|点)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:play|start playing)\s+(?P<query_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = (
            groups.get("query_put")
            or groups.get("query_search")
            or groups.get("query_open_search")
            or groups.get("query_zh_search")
            or groups.get("query_zh_suffix")
            or groups.get("query")
            or groups.get("query_en")
            or ""
        )
        query = _clean_media_query(query)
        if query:
            return query
    return ""


def _clean_media_query(value: str) -> str:
    query = clean(value)
    query = re.sub(r"^some\s+(?=[a-z])", "", query)
    query = re.sub(
        r"(?:用|在|打开|启动|通过)?\s*(?:apple\s*music|苹果音乐|音乐(?:应用|app)|spotify|网易云音乐?|qq\s*音乐|qq music)",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.split(
        r"(?:并|然后|再|接着|之后|后|and\s+then|then)",
        query,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    query = query.strip(" .，,。")
    return "" if query.lower() in _GENERIC_MUSIC_QUERIES else query


def clean_target(value: str) -> str:
    target = clean(value)
    target = re.split(
        r"(?:然后|并且|并|再|接着|之后|后|and\s+then|then|and)",
        target,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    target = re.sub(
        r"\s*(?:按钮|控件|元素|菜单项|菜单|复选框|button|control|element|menu item|menu|checkbox)$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"\s+(?:in|inside|within|using|with)\s+[A-Za-z][A-Za-z0-9 ._-]{1,40}$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    return target.strip(" .，,。")


def clean_type_target(value: str, *, app_name: str = "") -> str:
    target = clean_target(value)
    target = re.sub(
        r"^(?:打开|启动|切到|聚焦|open|launch|focus|switch to)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    clean_app_name = clean(app_name)
    if clean_app_name and target.lower().startswith(clean_app_name.lower()):
        target = target[len(clean_app_name):].strip()
    target = re.sub(r"^(?:的|里|中|上|in|inside)\s*", "", target, flags=re.IGNORECASE)
    return target.strip(" .，,。") or clean_target(value)


def clean_followup_text(value: str) -> str:
    text = clean(value)
    text = re.split(
        r"(?:并且|然后|再|接着|之后|后|并)?\s*(?:发送|提交|确认|回车|搜索|send|submit|confirm|enter|return|search)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return text.strip(" .，,。")


def role_filter(value: str) -> str:
    lowered = value.lower()
    if contains_any(lowered, ["按钮", "button"]):
        return "button"
    if contains_any(lowered, ["菜单", "menu"]):
        return "menu"
    if contains_any(lowered, ["复选框", "checkbox"]):
        return "checkbox"
    if contains_any(lowered, ["输入框", "文本框", "输入栏", "field", "input", "text"]):
        return "text"
    return ""


def _clean_window_app_name_hint(value: str) -> str:
    app = clean(value)
    app = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接|列出|查看|看看|看一下|看下|显示|读取|"
        r"list|show|read|the)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    app = re.sub(
        r"\s*(?:有|打开了|开了|正在显示|open|opened|running)?\s*"
        r"(?:哪些|什么|几个|多少|all|open)?\s*(?:窗口|windows?)?$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = app.strip(" .，,。")
    if re.fullmatch(
        r"(?:当前|现在|前台|这个|该)?(?:应用|app|软件|程序|窗口|window)",
        app,
        flags=re.IGNORECASE,
    ):
        return ""
    generic = {
        "",
        "app",
        "application",
        "desktop",
        "window",
        "windows",
        "current",
        "active",
        "foreground",
        "all",
        "应用",
        "应用程序",
        "桌面",
        "窗口",
        "所有",
        "全部",
        "当前",
        "前台",
    }
    return "" if app.lower() in generic else app


def _clean_window_title_hint(value: str) -> str:
    title = clean(value)
    title = re.sub(
        r"^(?:标题(?:包含|为)?|名为|叫|titled|called|matching|containing)\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s*(?:窗口|window)$", "", title, flags=re.IGNORECASE)
    return title.strip(" .，,。")


def _looks_like_ui_inspection_request(value: str, lowered: str) -> bool:
    if _looks_like_foreground_mutation(value, lowered):
        return False
    return bool(
        re.search(
            r"(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,8}(?:文字|文本|内容|正文)"
            r".{0,8}(?:是什么|是啥|有哪些|有什么|读取|读一下|查看|看看|识别)?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|查看|看看|识别|提取|抓取|获取)"
            r".{0,8}(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,8}(?:文字|文本|内容|正文)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)?"
            r".{0,10}(?:有哪些|有什么|列出|列一下|显示|查看|看看|看一下|读取|识别)"
            r".{0,10}(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)"
            r".{0,10}(?:有哪些|有什么|列表|列一下|显示|查看|看看|看一下|读取|识别)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|inspect|show|extract)\b.{0,16}\b"
            r"(?:current|this|active|foreground)\s+(?:window|ui|interface|screen)\b"
            r"(?:.{0,16}\b(?:text|content)\b)?",
            lowered,
        )
        or re.search(
            r"\b(?:list|show|read|inspect)\b.{0,24}\b(?:ui elements|buttons|text fields|controls)\b",
            lowered,
        )
        or re.search(r"\b(?:what|which)\b.{0,24}\b(?:buttons|controls|ui elements)\b", lowered)
        or re.search(
            r"\b(?:visible|shown|available)\s+(?:buttons|controls|ui elements|text fields)\b",
            lowered,
        )
        or re.search(r"\bwhat\s+can\s+i\s+(?:click|press|use)\b", lowered)
    )


def _looks_like_foreground_mutation(value: str, lowered: str) -> bool:
    if re.search(r"\bwhat\s+can\s+i\s+(?:click|press|use)\b", lowered):
        return False
    return bool(
        re.search(
            r"(?:双击|点击|点一下|点按|单击|按一下|按下|输入|键入|填写|填入|写入|发送|提交)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b(?:double\s+click|click|press|tap|type|enter|fill|send|submit)\b", lowered)
    )


def _ui_role_filter_hint(value: str) -> str:
    if re.search(r"(?:文字|文本|正文|content|text)", value, flags=re.IGNORECASE):
        return "text"
    if re.search(r"(?:按钮|button)", value, flags=re.IGNORECASE):
        return "button"
    if re.search(r"(?:输入框|文本框|输入栏|text field|textbox|input)", value, flags=re.IGNORECASE):
        return "text"
    if re.search(r"(?:菜单|menu)", value, flags=re.IGNORECASE):
        return "menu"
    if re.search(r"(?:复选框|checkbox)", value, flags=re.IGNORECASE):
        return "checkbox"
    return ""


def _ui_inspection_app_name_hint(value: str) -> str:
    patterns = (
        r"\b(?:list|show|read|inspect)\s+(?:the\s+)?"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)\s+(?:in|on|for|of)\s+(?P<app_en>[^.!?]+)",
        r"\b(?:what|which)\s+(?:buttons|controls|ui\s+elements|text\s+fields)\s+"
        r"(?:are\s+)?(?:visible|shown|available|there)?\s*(?:in|on|for|of)\s+(?P<app_en2>[^.!?]+)",
        r"\bwhat\s+can\s+i\s+(?:click|press|use)\s+(?:in|on)\s+(?P<app_en3>[^.!?]+)",
        r"\b(?:list|show|read|inspect)\s+(?P<app_en4>[^.!?]+?)\s+"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app2>[^。！？!?，,]+?)\s*(?:的)?\s*(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app3>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = next(
            (
                item
                for item in match.groupdict().values()
                if item is not None and str(item).strip()
            ),
            "",
        )
        app_name = _clean_ui_app_name_hint(raw_app)
        if app_name:
            return app_name
    return ""


def _clean_ui_app_name_hint(value: str) -> str:
    app = clean(value)
    app = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接|列出|查看|看看|看一下|看下|显示|读取|识别|"
        r"list|show|read|inspect|the)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    app = re.sub(
        r"\s*(?:有哪些|有什么|有啥|有哪个|有哪几个|visible|shown|available|there)?\s*"
        r"(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作|"
        r"ui\s+elements|buttons|text\s+fields|controls)?$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(
        r"\s*(?:当前|现在|这个|前台|该|current|active|foreground|this)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    if re.fullmatch(
        r"(?:当前|现在|这个|前台|该)?(?:应用|app|界面|窗口|屏幕|ui|interface|window|screen)",
        app,
        flags=re.IGNORECASE,
    ):
        return ""
    generic = {
        "",
        "app",
        "application",
        "desktop",
        "window",
        "interface",
        "screen",
        "ui",
        "current",
        "active",
        "foreground",
        "应用",
        "应用程序",
        "桌面",
        "窗口",
        "界面",
        "屏幕",
        "当前",
        "前台",
    }
    return "" if app.lower().strip(" .，,。") in generic else app.strip(" .，,。")


def _looks_like_screen_capture_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:截(?:一下|下)图|截个?图|截个?屏|截图|截屏|屏幕截图|抓屏|拍屏)", value)
        or re.search(
            r"(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)"
            r".{0,8}(?:截图|截屏|截一下|截个图|抓屏|拍屏)",
            value,
        )
        or re.search(
            r"(?:截取|截图|截屏|截一下|截个图|截|抓屏|拍屏)"
            r".{0,8}(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)",
            value,
        )
        or re.search(r"(?:拍一下|拍下|拍一张|拍个).{0,8}(?:屏幕|桌面|界面|画面)", value)
        or re.search(
            r"(?:看一下|看看|看下|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)"
            r".{0,12}(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)",
            value,
        )
        or re.search(
            r"(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)"
            r".{0,8}(?:是什么|是啥|内容|画面|有什么|有啥)",
            value,
        )
        or "take a screenshot" in lowered
        or "capture the screen" in lowered
        or "screen capture" in lowered
        or re.search(r"\bscreenshot\s+(?:my|the|this|current)?\s*(?:screen|desktop)?\b", lowered)
        or re.search(
            r"\b(?:look at|inspect|view|read|show me|show)\s+"
            r"(?:my|the|this|current)?\s*(?:screen|desktop|interface|ui)\b",
            lowered,
        )
        or re.search(r"\bwhat(?:'s| is)?\s+on\s+(?:my|the|this|current)?\s*(?:screen|desktop)\b", lowered)
    )


def _screen_capture_app_name_hint(value: str) -> str:
    patterns = (
        r"(?:看一下|看看|看下|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:界面|画面)",
        r"(?P<app2>[^。！？!?，,]+?)\s*(?:界面|画面).{0,8}(?:截图|截屏|看一下|看看|查看|观察)",
        r"\b(?:look at|inspect|view|show me|show)\s+(?P<app_en>.+?)\s+"
        r"(?:screen|interface|ui)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = next(
            (
                item
                for item in match.groupdict().values()
                if item is not None and str(item).strip()
            ),
            "",
        )
        app_name = _clean_ui_app_name_hint(raw_app)
        if app_name:
            return app_name
    return ""


def _clean_management_app_name_hint(value: str) -> str:
    app = clean(value)
    app = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接|把|将|the)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(r"\s*(?:然后|再|接着|之后|后|then)\s*$", "", app, flags=re.IGNORECASE)
    app = re.sub(r"^(?:打开|启动|开启|运行|拉起|切到|聚焦)\s*", "", app)
    app = re.sub(
        r"^(?:open|launch|start|focus|activate|bring)\s+|^switch\s+to\s+",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(
        r"\s*(?:一下|下|起来|掉|显示出来|还原|恢复|取消隐藏|隐藏|藏起来|收起|收起来|"
        r"打开|启动|开启|运行|拉起|切到|聚焦|open|launch|start|focus|activate|"
        r"最小化|退出|关闭|关掉|结束|终止|show|restore|unhide|hide|minimi[sz]e|"
        r"quit|close|exit|terminate)$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = app.strip(" .，,。")
    generic = {
        "",
        "app",
        "application",
        "desktop",
        "window",
        "应用",
        "应用程序",
        "桌面",
        "窗口",
        "当前",
        "前台",
    }
    return "" if app.lower() in generic else app


def _is_foreground_window_close_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:关闭|关掉|关上|关(?:一下|下|了)?)\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*(?:关闭|关掉|关上|关(?:一下|下|了)?)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:close|dismiss)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_foreground_app_quit_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:退出|关闭|关掉|结束|终止)\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*(?:退出|关闭|关掉|结束|终止)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:quit|close|exit|terminate)\s+(?:the\s+)?"
            r"(?:current|foreground|active|this)\s+(?:app|application)\b",
            lowered,
        )
    )


def _is_foreground_window_minimize_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:最小化|收起|收起来|隐藏)\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*(?:最小化|收起|收起来|隐藏)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:minimi[sz]e|hide)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_foreground_app_hide_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:隐藏|收起|藏起|藏起来)\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*(?:隐藏|收起|藏起|藏起来)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bhide\s+(?:the\s+)?(?:current|foreground|active|this)\s+(?:app|application)\b",
            lowered,
        )
    )


def _parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    combo = clean(value)
    combo = re.sub(r"\s*(?:吗|嘛|呢|please)$", "", combo, flags=re.IGNORECASE).strip()
    if re.search(r"(?:to\s+send|发送|提交|确认)", combo, flags=re.IGNORECASE):
        return None
    combo = re.sub(r"\bkey\b|键", " ", combo, flags=re.IGNORECASE)
    combo = combo.replace("+", " ").replace("-", " ")
    tokens = [token for token in re.split(r"\s+", combo.strip()) if token]
    if not tokens:
        return None
    modifiers: list[str] = []
    key = ""
    for token in tokens:
        normalized = _normalize_hotkey_token(token)
        if not normalized:
            continue
        if normalized in {"command", "control", "option", "shift"}:
            if normalized not in modifiers:
                modifiers.append(normalized)
            continue
        key = normalized
    if not key:
        return None
    return {"key": key, "modifiers": modifiers}


def _safe_shortcut_action_from_hotkey_hint(value: str) -> str:
    hotkey = hotkey_hint(value)
    if not hotkey:
        return ""
    key = str(hotkey.get("key") or "").strip().lower()
    modifiers = frozenset(str(item).strip().lower() for item in hotkey.get("modifiers") or [])
    mapping = {
        ("c", frozenset({"command"})): "copy",
        ("v", frozenset({"command"})): "paste",
        ("a", frozenset({"command"})): "select_all",
        ("z", frozenset({"command"})): "undo",
        ("z", frozenset({"command", "shift"})): "redo",
        ("f", frozenset({"command"})): "find",
        ("l", frozenset({"command"})): "focus_address_bar",
        ("t", frozenset({"command"})): "new_tab",
        ("n", frozenset({"command"})): "new_window",
        ("n", frozenset({"command", "shift"})): "new_private_window",
        ("w", frozenset({"command"})): "close_tab",
        ("r", frozenset({"command"})): "refresh",
        ("d", frozenset({"command"})): "bookmark_page",
        ("y", frozenset({"command"})): "show_history",
        ("i", frozenset({"command", "option"})): "open_devtools",
        ("]", frozenset({"command"})): "browser_forward",
        ("[", frozenset({"command"})): "browser_back",
        ("t", frozenset({"command", "shift"})): "reopen_closed_tab",
    }
    return mapping.get((key, modifiers), "")


def _safe_shortcut_action_from_phrase(value: str) -> str:
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接)\s*",
        "",
        clean(value),
        flags=re.IGNORECASE,
    )
    phrase = re.sub(r"\s*(?:一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)$", "", phrase)
    normalized = re.sub(r"\s+", "", phrase).lower()
    mapping = {
        "复制": "copy",
        "复制这个": "copy",
        "复制选中内容": "copy",
        "复制选中的内容": "copy",
        "复制当前选中内容": "copy",
        "复制当前网页链接": "copy_current_page_link",
        "复制当前页面链接": "copy_current_page_link",
        "copy": "copy",
        "copyselection": "copy",
        "copyselectedtext": "copy",
        "copycurrentpagelink": "copy_current_page_link",
        "copycurrenturl": "copy_current_page_link",
        "粘贴": "paste",
        "前台粘贴": "paste",
        "粘贴到当前窗口": "paste",
        "paste": "paste",
        "pasteintocurrentwindow": "paste",
        "全选": "select_all",
        "selectall": "select_all",
        "撤销": "undo",
        "undo": "undo",
        "重做": "redo",
        "redo": "redo",
        "查找": "find",
        "打开查找": "find",
        "find": "find",
        "刷新": "refresh",
        "浏览器刷新": "refresh",
        "网页刷新": "refresh",
        "当前网页刷新": "refresh",
        "当前页刷新": "refresh",
        "刷新当前页面": "refresh",
        "刷新当前页": "refresh",
        "刷新当前网页": "refresh",
        "刷新这个页面": "refresh",
        "刷新这个网页": "refresh",
        "刷新页面": "refresh",
        "refresh": "refresh",
        "refreshpage": "refresh",
        "refreshthecurrentpage": "refresh",
        "reload": "refresh",
        "reloadpage": "refresh",
        "reloadthecurrentpage": "refresh",
        "新建标签": "new_tab",
        "新建标签页": "new_tab",
        "新标签页": "new_tab",
        "打开新标签页": "new_tab",
        "开新标签页": "new_tab",
        "新开标签页": "new_tab",
        "开一个新标签页": "new_tab",
        "新开一个标签页": "new_tab",
        "newtab": "new_tab",
        "opennewtab": "new_tab",
        "openanewtab": "new_tab",
        "新建窗口": "new_window",
        "打开新窗口": "new_window",
        "打开一个新窗口": "new_window",
        "新建浏览器窗口": "new_window",
        "newwindow": "new_window",
        "opennewwindow": "new_window",
        "新建无痕窗口": "new_private_window",
        "打开无痕窗口": "new_private_window",
        "新建隐身窗口": "new_private_window",
        "打开隐身窗口": "new_private_window",
        "新建私密窗口": "new_private_window",
        "打开私密窗口": "new_private_window",
        "newprivatewindow": "new_private_window",
        "openprivatewindow": "new_private_window",
        "newincognitowindow": "new_private_window",
        "openincognitowindow": "new_private_window",
        "incognitowindow": "new_private_window",
        "关闭标签页": "close_tab",
        "关闭当前标签页": "close_tab",
        "关闭当前网页": "close_tab",
        "关闭这个网页": "close_tab",
        "把当前网页关掉": "close_tab",
        "把这个网页关掉": "close_tab",
        "closetab": "close_tab",
        "closethistab": "close_tab",
        "closecurrenttab": "close_tab",
        "closethecurrenttab": "close_tab",
        "closethispage": "close_tab",
        "下一个标签": "next_tab",
        "下一个标签页": "next_tab",
        "切到下一个标签页": "next_tab",
        "切换到下一个标签页": "next_tab",
        "nexttab": "next_tab",
        "switchtonexttab": "next_tab",
        "上一个标签": "previous_tab",
        "上一个标签页": "previous_tab",
        "切到上一个标签页": "previous_tab",
        "切换到上一个标签页": "previous_tab",
        "previoustab": "previous_tab",
        "switchtoprevioustab": "previous_tab",
        "重新打开关闭的标签页": "reopen_closed_tab",
        "重新打开刚才关闭的标签页": "reopen_closed_tab",
        "重新打开刚关闭的标签页": "reopen_closed_tab",
        "reopenclosedtab": "reopen_closed_tab",
        "reopenlastclosedtab": "reopen_closed_tab",
        "前进下一页": "browser_forward",
        "前进": "browser_forward",
        "forwardpage": "browser_forward",
        "goforward": "browser_forward",
        "返回上一页": "browser_back",
        "后退上一页": "browser_back",
        "后退": "browser_back",
        "goback": "browser_back",
        "backpage": "browser_back",
        "加入书签": "bookmark_page",
        "添加书签": "bookmark_page",
        "收藏当前网页": "bookmark_page",
        "把当前网页加入书签": "bookmark_page",
        "bookmarkthispage": "bookmark_page",
        "bookmarkcurrentpage": "bookmark_page",
        "打开历史记录": "show_history",
        "显示历史记录": "show_history",
        "浏览器历史记录": "show_history",
        "打开浏览器历史记录": "show_history",
        "showhistory": "show_history",
        "openhistory": "show_history",
        "打开开发者工具": "open_devtools",
        "显示开发者工具": "open_devtools",
        "开发者工具": "open_devtools",
        "打开当前网页开发者工具": "open_devtools",
        "打开当前网页的开发者工具": "open_devtools",
        "opendevtools": "open_devtools",
        "showdevtools": "open_devtools",
        "聚焦地址栏": "focus_address_bar",
        "打开地址栏": "focus_address_bar",
        "选中地址栏": "focus_address_bar",
        "focusaddressbar": "focus_address_bar",
        "focusurlbar": "focus_address_bar",
        "addressbar": "focus_address_bar",
    }
    return mapping.get(normalized, "")


def _looks_like_show_desktop_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:显示|露出|查看|看看|看一下|切到|切换到|回到|返回到|回)\s*"
            r"(?:当前|现在)?(?:桌面|desktop)"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"^(?:show|reveal|switch\s+to|go\s+to)\s+(?:the\s+)?desktop\s*(?:please)?$", lowered)
    )


def _looks_like_next_focus_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到)?\s*"
            r"(?:下一个|下一项|下个|next)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"^(?:focus|move|go|jump|tab)\s+(?:to\s+)?(?:the\s+)?next\s+(?:field|input|control|element)\s*$", lowered)
    )


def _looks_like_previous_focus_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到)?\s*"
            r"(?:上一个|上一项|上个|previous|prev)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"^(?:focus|move|go|jump)\s+(?:to\s+)?(?:the\s+)?(?:previous|prev)\s+(?:field|input|control|element)\s*$", lowered)
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
        "上箭头": "arrow_up",
        "上方向键": "arrow_up",
        "向上箭头": "arrow_up",
        "down": "arrow_down",
        "downarrow": "arrow_down",
        "arrowdown": "arrow_down",
        "下箭头": "arrow_down",
        "下方向键": "arrow_down",
        "向下箭头": "arrow_down",
        "left": "arrow_left",
        "leftarrow": "arrow_left",
        "arrowleft": "arrow_left",
        "左箭头": "arrow_left",
        "左方向键": "arrow_left",
        "向左箭头": "arrow_left",
        "right": "arrow_right",
        "rightarrow": "arrow_right",
        "arrowright": "arrow_right",
        "右箭头": "arrow_right",
        "右方向键": "arrow_right",
        "向右箭头": "arrow_right",
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


def _scroll_direction_is_up(value: str) -> bool:
    direction = str(value or "").strip().lower()
    return direction in {
        "向上",
        "往上",
        "朝上",
        "上",
        "上滑",
        "上滚",
        "上翻",
        "上一页",
        "页面顶部",
        "顶部",
        "顶端",
        "最上面",
        "最上方",
        "up",
        "top",
    }


def _bounded_count(value: str | None, *, default: int, maximum: int) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw.isdigit():
        count = int(raw)
    else:
        count = {
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
        }.get(raw, 0)
    return count if 1 <= count <= maximum else 0


def _numeric_value(value: str) -> int | float:
    number = float(str(value or "0"))
    return int(number) if number.is_integer() else number


def _normalize_hotkey_token(value: str) -> str:
    token = clean(value).lower().strip(" .，,。?？!！")
    aliases = {
        "cmd": "command",
        "command": "command",
        "⌘": "command",
        "ctrl": "control",
        "control": "control",
        "option": "option",
        "opt": "option",
        "alt": "option",
        "shift": "shift",
        "return": "return",
        "enter": "return",
        "回车": "return",
        "esc": "escape",
        "escape": "escape",
        "tab": "tab",
        "space": "space",
        "空格": "space",
    }
    return aliases.get(token, token if re.fullmatch(r"[a-z0-9]", token) else "")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def contains_any(text: str, needles: list[str] | tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle).lower() in lowered for needle in needles)


def _allowed_tool_set(allowed_tools: Iterable[str] | None) -> set[str] | None:
    if allowed_tools is None:
        return None
    return {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}


def _first_allowed(tools: Iterable[str], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None
