"""Shared desktop intent parsing hints for planner snapshots and execution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .app_name_hints import legacy_music_app_name_hint
from .hotkey_hints import legacy_normalize_hotkey_token, legacy_parse_hotkey_combo

_GENERIC_MUSIC_QUERIES = {
    "",
    "music",
    "apple music",
    "音乐",
    "歌",
    "歌曲",
    "播放器",
    "音乐播放器",
    "状态",
    "播放状态",
    "播放进度",
    "在播状态",
    "进度",
    "播",
    "apple",
    "个",
    "点",
    "东西",
    "听听",
    "音乐听听",
    "一下",
    "一首",
    "首",
    "吗",
    "嘛",
    "吧",
    "呢",
    "么",
    "some music",
    "something",
    "anything",
    "a song",
    "song",
    "songs",
}

_FINDER_SAFE_SHORTCUT_PHRASES: tuple[tuple[str, str], ...] = (
    ("finder_quick_look", "快速查看"),
    ("finder_quick_look", "快速查看选中项"),
    ("finder_quick_look", "快速查看选中文件"),
    ("finder_quick_look", "快速预览"),
    ("finder_quick_look", "预览选中项"),
    ("finder_quick_look", "预览选中文件"),
    ("finder_quick_look", "按空格"),
    ("finder_quick_look", "按空格键"),
    ("finder_quick_look", "空格"),
    ("finder_quick_look", "space"),
    ("finder_quick_look", "pressspace"),
    ("new_folder", "新建文件夹"),
    ("new_folder", "新建一个文件夹"),
    ("new_folder", "创建文件夹"),
    ("new_folder", "创建一个文件夹"),
    ("new_folder", "新建目录"),
    ("new_folder", "创建目录"),
    ("new_folder", "newfolder"),
    ("new_folder", "makeanewfolder"),
    ("new_folder", "createanewfolder"),
    ("rename_selected", "重命名选中项"),
    ("rename_selected", "重命名选中文件"),
    ("rename_selected", "重命名当前选中项"),
    ("rename_selected", "重命名当前选中文件"),
    ("rename_selected", "renameselected"),
    ("rename_selected", "renameselectedfile"),
    ("parent_folder", "上一级"),
    ("parent_folder", "上一级文件夹"),
    ("parent_folder", "上一级目录"),
    ("parent_folder", "打开上一级文件夹"),
    ("parent_folder", "回到上级目录"),
    ("parent_folder", "parentfolder"),
    ("parent_folder", "openparentfolder"),
    ("finder_get_info", "显示简介"),
    ("finder_get_info", "查看简介"),
    ("finder_get_info", "显示选中文件简介"),
    ("finder_get_info", "显示选中项简介"),
    ("finder_get_info", "getinfo"),
    ("finder_get_info", "showinfo"),
    ("copy", "复制选中项"),
    ("copy", "复制选中文件"),
    ("copy", "复制选中文本"),
    ("copy", "复制当前选中项"),
    ("copy", "复制当前选中文件"),
    ("copy", "复制当前选中文本"),
    ("copy", "copyselectedfile"),
)


def app_control_mode(text: str) -> str:
    return (
        "focus"
        if contains_any(
            text,
            [
                "切到",
                "聚焦",
                "focus",
                "switch to",
                "switch ",
                "activate ",
                "bring ",
                "go back to",
                "switch back to",
                "back to",
            ],
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
    if re.search(
        r"\b(?:press|hit|tap)\s+(?:command|cmd|control|ctrl|option|alt|shift)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ) or re.search(
        r"(?:按|敲).{0,6}(?:command|cmd|⌘|control|ctrl|option|alt|shift)",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        return None
    patterns = (
        r"(?P<target_post>[^。！？!?，,]{1,60}?)(?:按钮|控件|元素|菜单项|菜单|复选框)?\s*(?:双击|点击|点一下|点按|单击)$",
        r"(?:双击|点击|点一下|点按|单击|按一下|按(?!钮)|点(?!击|按|一下))\s*(?P<target>[^。！？!?，,]+)",
        r"(?:double\s+click|click|press|tap)\s+(?:the\s+)?(?P<target_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_target = (
            match.groupdict().get("target")
            or match.groupdict().get("target_post")
            or match.groupdict().get("target_en")
            or ""
        )
        target = clean_target(raw_target)
        if not target:
            continue
        return {
            "target": target,
            "role_filter": role_filter(match.group(0)),
            "click_count": 2 if contains_any(match.group(0), ["双击", "double click"]) else 1,
        }
    return None


def type_into_ui_hint(text: str, *, app_name: str = "") -> dict[str, Any] | None:
    patterns = (
        r"(?P<target>[^。！？!?，,]{1,40}?(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*(?:输入|键入|填写|填入|写入|写)\s*(?P<text>[^。！？!?，,]+)",
        r"(?:type|enter|fill)\s+(?P<text_en2>[^.!?,]+?)\s+"
        r"(?:into|in|inside)\s+(?:the\s+)?"
        r"(?P<target_en2>[^.!?,]{1,40}?(?:search box|search field|message field|address bar|input|field|text box))",
        r"(?P<target_en>[^.!?,]{1,40}?(?:search box|search field|message field|address bar|input|field|text box))\s*(?:type|enter|fill)\s*(?P<text_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_target = (
            match.groupdict().get("target")
            or match.groupdict().get("target_en")
            or match.groupdict().get("target_en2")
            or ""
        )
        raw_text = (
            match.groupdict().get("text")
            or match.groupdict().get("text_en")
            or match.groupdict().get("text_en2")
            or ""
        )
        target = clean_type_target(raw_target, app_name=app_name)
        typed_text = clean_followup_text(raw_text)
        if _looks_like_current_input_target(raw_target, target):
            continue
        if target and typed_text:
            return {"target": target, "text": typed_text, "role_filter": "text"}
    return None


def safe_type_text_hint(text: str) -> str:
    patterns = (
        r"(?:输入(?!框|栏)|键入|填写|填入|写入|写)\s*(?P<text>[^。！？!?，,]+)",
        r"(?:type|enter|fill)\s+(?P<text_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = clean_followup_text(
            match.groupdict().get("text") or match.groupdict().get("text_en") or ""
        )
        typed_text = re.sub(
            r"^(?:文本|文字|内容|text)\s+",
            "",
            typed_text,
            flags=re.IGNORECASE,
        ).strip()
        if typed_text:
            return typed_text
    return ""


def _looks_like_current_input_target(raw_target: str, clean_target_value: str) -> bool:
    raw = clean(raw_target)
    target = clean(clean_target_value)
    if target in {"当前", "现在", "前台", "这个", "该"}:
        return True
    return bool(
        re.fullmatch(
            r"(?:在|到|往|向)?\s*(?:当前|现在|前台|这个|该)\s*"
            r"(?:输入框|输入栏|文本框|消息框|聊天框|input|field|text\s*box)",
            raw,
            flags=re.IGNORECASE,
        )
    )


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
    lowered = value.lower()
    if not re.search(r"(?:窗口|windows?)", value, flags=re.IGNORECASE):
        return None
    if re.search(
        r"(?:当前|现在|这个|前台|该)?(?:窗口|window)"
        r".{0,8}(?:内容|文字|文本|正文|content|text)",
        value,
        flags=re.IGNORECASE,
    ):
        return None
    if _looks_like_current_window_observation(value, lowered):
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


def _looks_like_current_window_observation(value: str, lowered: str) -> bool:
    if re.search(
        r"(?:列表|清单|所有|全部|哪些|几个|多少|list|all|windows)",
        value,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:查看|看看|看一下|看下|显示|读取)?\s*"
            r"(?:当前|现在|前台|这个|该)\s*(?:窗口|window)"
            r"\s*(?:是什么|是啥|哪个|什么|标题|名称|名字)?"
            r"(?:一下|下|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|read|inspect|look\s+at|check)\s+"
            r"(?:the\s+)?(?:current|active|foreground|frontmost|this)\s+window\b",
            lowered,
        )
    )


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
            "hide_other_apps",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:隐藏|hide)\s*(?:其他|其它|其余|别的|other)\s*(?:应用|app|apps|applications)$",
        ),
        (
            "status",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:检查一下|检查|看看|看一下|查看|确认)?\s*"
            r"(?P<app_status>[^。！？!?，,]+?)\s*(?:是否)?"
            r"(?:在运行|运行中|运行|开着|开没开)"
            r"(?:吗|嘛|呢|吧|么|\?|？)?$",
        ),
        (
            "status",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:检查一下|检查|看看|看一下|查看|确认)?\s*"
            r"(?P<app_status_open>[^。！？!?，,]+?)\s*(?:是否)?"
            r"(?:打开了|开了|打开|开启)(?:吗|嘛|呢|吧|么|\?|？)$",
        ),
        (
            "status",
            r"(?:is|check\s+if|see\s+if)\s+(?P<app_status_en>[^.!?]+?)\s+"
            r"(?:is\s+)?(?:running|open)(?:\s+please)?$",
        ),
        (
            "show",
            r"^(?:你能(?:不能)?(?:帮我)?|你可以(?:帮我)?|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:显示|显示一下|显示出来|调出来|叫出来|还原|恢复|取消隐藏|show|restore|unhide)\s*"
            r"(?P<app>[^。！？!?，,]+)",
        ),
        (
            "show",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|开启|拉起)\s*(?P<app_front_open>[^。！？!?，,]+?)\s*"
            r"(?:并|然后|再)?\s*(?:切到|到)?前台$",
        ),
        (
            "show",
            r"(?P<app2>[^。！？!?，,]+?)\s*"
            r"(?:显示出来|调出来|还原|恢复|取消隐藏|叫出来|show|restore|unhide)$",
        ),
        (
            "hide",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:隐藏一下|隐藏|藏起来|收起来|收起|hide)\s*"
            r"(?P<app3>[^。！？!?，,]+)",
        ),
        (
            "hide",
            r"(?P<app4>[^。！？!?，,]+?)\s*"
            r"(?:隐藏|藏起来|收起来|收起|hide)(?:一下|下)?$",
        ),
        (
            "minimize",
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            r"(?P<app5>[^。！？!?，,]+?)\s*(?:最小化|minimi[sz]e)(?:一下|下)?$",
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
        if action == "hide_other_apps":
            return None
        if action == "quit" and re.search(r"(?:窗口|window)", value, flags=re.IGNORECASE):
            continue
        if action == "show" and re.search(
            r"(?:切到|聚焦|focus|switch\s+to|activate)",
            value,
            flags=re.IGNORECASE,
        ) and not re.search(
            r"(?:前台|置前|叫出来|显示|还原|恢复|调出来|show|restore|unhide)",
            value,
            flags=re.IGNORECASE,
        ):
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
    if _is_show_all_hidden_apps_request(value, lowered):
        return {"action": "show_all_apps", "scope": "desktop"}
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
    normalized = re.sub(r"\s+", "", value).lower()
    if normalized in {"退出当前应用", "退出当前app", "关闭当前应用", "关闭当前app"}:
        return {"key": "q", "modifiers": ["command"]}
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
        combo = re.sub(
            r"\s+(?:in|on)\s+(?:the\s+)?(?:current|foreground|active)\s+"
            r"(?:window|app|application)\s*$",
            "",
            match.group("combo"),
            flags=re.IGNORECASE,
        )
        parsed = _parse_hotkey_combo(combo)
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
    if not action:
        action = _safe_shortcut_action_from_trailing_phrase(value)
    return {"action": action} if action else None


def safe_shortcut_sequence_hint(text: str) -> list[dict[str, str]]:
    value = clean(text)
    actions: list[str] = []
    for part in [
        item.strip()
        for item in re.split(r"(?:然后|再|接着|之后|and\s+then|then|[,，。])", value)
        if item.strip()
    ]:
        compound_actions = _compound_safe_shortcut_actions(part)
        if compound_actions:
            actions.extend(compound_actions)
            continue
        action = (
            _safe_shortcut_action_from_hotkey_hint(part)
            or _safe_shortcut_action_from_phrase(part)
            or _safe_shortcut_action_from_trailing_phrase(part)
        )
        if action:
            actions.append(action)
    return [{"action": action} for action in actions] if len(actions) > 1 else []


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
            r"^(?:你能帮我|你可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:按一下|按下|按|发送|触发)\s*"
            rf"(?:{count.format(name='count_before')}\s*(?:次|下)\s*)?"
            rf"{key.format(name='key')}"
            rf"(?:\s*{count.format(name='count_after')}\s*(?:次|下))?"
            r"\s*(?:键)?(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:press|send|hit)\s+(?:the\s+)?"
            rf"{key.format(name='key_en')}"
            rf"(?:\s+{count.format(name='count_en')}\s*(?:times?)?)?"
            r"(?:\s+please)?[.!?]?\s*$"
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
    if re.search(
        zh_prefix + r"(?:翻到|翻至|跳到|跳至)\s*(?P<page>下一页|上一页)(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        value,
        flags=re.IGNORECASE,
    ):
        return {"direction": "up" if "上一页" in value else "down", "pages": 1}
    return None


def safe_click_hint(text: str) -> dict[str, int | float] | None:
    value = clean(text)
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|点|click)\s*"
        r"(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到)\s*(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x2>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y2>\d+(?:\.\d+)?)\s*"
        r"(?:(?P<double2>双击|double\s+click)|点击|点一下|点按|单击|点|click)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        x = match.groupdict().get("x") or match.groupdict().get("x2") or ""
        y = match.groupdict().get("y") or match.groupdict().get("y2") or ""
        click_count = 2 if match.groupdict().get("double") or match.groupdict().get("double2") else 1
        payload: dict[str, int | float] = {"x": _numeric_value(x), "y": _numeric_value(y)}
        if click_count != 1:
            payload["click_count"] = click_count
        return payload
    return None


def media_playback_hint(text: str) -> dict[str, str]:
    action = media_action_hint(text)
    app_name = music_app_name_hint(text)
    if not app_name and _implicit_apple_music_control_hint(text, action=action):
        app_name = "Music"
    return {
        "action": action,
        "app_name": app_name,
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
        if control_only:
            tool_name = (
                _first_allowed(("media.apple_music_control", "media.system_control"), allowed)
                if app_name
                else _first_allowed(("media.system_control", "media.apple_music_control"), allowed)
            )
            return tool_name, {"action": "play"} if tool_name else {}
        generic_tool = _first_allowed(("media.music_app_open_and_play",), allowed)
        if generic_tool:
            return generic_tool, {"app_name": app_name or "Music"}
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


def media_app_query_search_plan(
    inputs: Mapping[str, Any],
    allowed_tools: Iterable[str] | None,
) -> list[tuple[str, dict[str, Any]]]:
    allowed = _allowed_tool_set(allowed_tools)
    action = str(inputs.get("action") or "").strip() or "play"
    app_name = str(inputs.get("app_name") or "").strip()
    query = str(inputs.get("query") or "").strip()
    if action != "play" or not app_name or not query:
        return []

    type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
    submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    if not type_tool or not submit_tool:
        return []

    discovery_step = []
    discover_tool = _first_allowed(("desktop.list_apps",), allowed)
    if discover_tool:
        discovery_step = [(discover_tool, {"query": app_name, "limit": 20})]

    app_search_tool = _first_allowed(
        ("app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"),
        allowed,
    )
    if app_search_tool:
        plan = [
            *discovery_step,
            (app_search_tool, {"app_name": app_name, "action": "find"}),
            (type_tool, {"text": query}),
            (submit_tool, {}),
        ]
        play_tool = _first_allowed(("media.music_app_open_and_play",), allowed)
        if play_tool:
            plan.append((play_tool, {"app_name": app_name}))
        _append_media_app_verify_step(plan, allowed)
        return plan

    app_tool = _first_allowed(("app.open", "app.focus"), allowed)
    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    if not app_tool or not shortcut_tool:
        return []
    plan = [
        *discovery_step,
        (app_tool, {"app_name": app_name}),
        (shortcut_tool, {"action": "find"}),
        (type_tool, {"text": query}),
        (submit_tool, {}),
    ]
    play_tool = _first_allowed(("media.music_app_open_and_play",), allowed)
    if play_tool:
        plan.append((play_tool, {"app_name": app_name}))
    _append_media_app_verify_step(plan, allowed)
    return plan


def _append_media_app_verify_step(
    plan: list[tuple[str, dict[str, Any]]],
    allowed: set[str] | None,
) -> None:
    tool_name = _first_allowed(
        ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
        allowed,
    )
    if not tool_name:
        return
    payload = {"role_filter": "", "limit": 80} if tool_name == "desktop.ui_elements" else {}
    plan.append((tool_name, payload))


def media_action_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if contains_any(
        lowered,
        [
            "当前播放",
            "现在播放",
            "正在播放",
            "播放什么",
            "播放状态",
            "播放进度",
            "在播状态",
            "status",
            "currently playing",
        ],
    ):
        return "status"
    if contains_any(lowered, ["下一首", "下一曲", "下首", "切歌", "换歌", "跳过", "next", "skip"]):
        return "next"
    if contains_any(lowered, ["上一首", "上一曲", "previous"]) or re.search(
        r"\bback\s+(?:one\s+)?(?:track|song)\b",
        lowered,
    ):
        return "previous"
    if contains_any(
        lowered,
        ["暂停", "停一下", "停止", "停止播放", "别放了", "关掉", "pause", "stop playing"],
    ):
        return "pause"
    if _media_resume_play_hint(str(text or "")):
        return "play"
    if re.search(r"\bput\s+.+\s+on\s+(?:apple\s*music|music)\b", lowered):
        return "play"
    if contains_any(
        lowered,
        ["来点", "听点", "听一首", "听首", "想听", "听音乐", "听歌", "listen to music", "put on some music"],
    ):
        return "play"
    if contains_any(lowered, ["播放", "播", "放", "play"]):
        return "play"
    return ""


def media_control_only_hint(text: str, *, action: str = "") -> bool:
    lowered = str(text or "").lower()
    if action in {"next", "previous", "pause"}:
        return not re.search(r"apple\s*music|苹果音乐|spotify|网易云|qq\s*音乐|qq music", lowered)
    if action == "play":
        return _media_resume_play_hint(str(text or "")) or bool(
            re.fullmatch(r"\s*(?:播放|播|放)(?:一下|下)?\s*", str(text or ""), flags=re.IGNORECASE)
        )
    return False


def _media_resume_play_hint(text: str) -> bool:
    value = clean(text)
    lowered = value.lower()
    return bool(
        re.fullmatch(r"(?:播放继续|继续播放|恢复播放|接着播放)", value, flags=re.IGNORECASE)
        or re.search(
            r"(?:继续|恢复|接着).{0,8}(?:当前|现在|正在播放的)?(?:音乐|歌曲|歌|媒体|播放)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:resume|continue)\s+(?:the\s+)?(?:current\s+)?(?:music|song|track|media|playback|playing)\b",
            lowered,
        )
    )


def _implicit_apple_music_control_hint(text: str, *, action: str = "") -> bool:
    value = clean(text)
    if action == "next":
        return bool(re.fullmatch(r"(?:下一首|下一曲|下首)", value, flags=re.IGNORECASE))
    if action == "play":
        return bool(re.fullmatch(r"(?:播放|播|放)(?:一下|下)?", value, flags=re.IGNORECASE))
    return False


def music_app_name_hint(text: str) -> str:
    return legacy_music_app_name_hint(text)


def media_query_hint(text: str) -> str:
    value = clean(text)
    if re.fullmatch(r"(?:播放|播|放)(?:一下|下)?", value, flags=re.IGNORECASE):
        return ""
    if re.fullmatch(r"(?:play|start playing)", value, flags=re.IGNORECASE):
        return ""
    patterns = (
        r"(?:put|play)\s+(?P<query_put>.+?)\s+(?:on|in|with)\s+(?:apple\s*music|music)",
        r"(?:search|find)\s+(?:apple\s*music|music)\s+for\s+(?P<query_search>.+?)\s+(?:and\s+)?(?:play|start)",
        r"(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query_search_in>.+?)\s+"
        r"(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?\s+"
        r"(?:and\s+)?(?:play|start)",
        r"(?:apple\s*music|music)(?:\s+app)?\s+(?:search|find|look\s+up)\s+"
        r"(?:for\s+)?(?P<query_app_search>.+?)\s+(?:and\s+)?(?:play|start)",
        r"(?:open|launch|start)\s+(?:apple\s*music|music)\s+(?:and\s+)?(?:search|find)\s+(?P<query_open_search>.+?)\s+(?:and\s+)?(?:play|start)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过|打开|启动)?\s*(?:apple\s*music|苹果音乐|音乐(?:应用|app)?)"
        r"(?:里|中|上|内|里面)?\s*"
        r"(?:搜索|搜一下|搜|查找|找|检索)(?:一下|下)?\s*"
        r"(?P<query_zh_scoped_search>[^。！？!?，,]+?)\s*"
        r"(?:(?:并|然后|再|接着|之后)\s*)?(?:播放|播|放)(?:一下)?",
        r"(?:搜索|搜一下|搜|查找|找|检索)(?:一下|下)?\s*(?P<query_zh_search>[^。！？!?，,]+?)(?:并|然后|再)?(?:播放|播|放)(?:一下)?",
        r"(?P<query_zh_suffix>[^。！？!?，,]+?)(?:播放|播|放)(?:一下)?$",
        r"(?:想听|听听|听一首|听首|听点|来点)\s*(?P<query_listen>[^。！？!?，,]+)",
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
            or groups.get("query_search_in")
            or groups.get("query_app_search")
            or groups.get("query_open_search")
            or groups.get("query_zh_scoped_search")
            or groups.get("query_zh_search")
            or groups.get("query_zh_suffix")
            or groups.get("query_listen")
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
    query = re.sub(r"^(?:in|on|with|using)\s+", "", query, flags=re.IGNORECASE)
    query = re.sub(
        r"(?:用|在|打开|启动|通过)?\s*(?:apple\s*music|苹果音乐|音乐(?:应用|app)|spotify|网易云音乐?|qq\s*音乐|qq music)",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"^\s*(?:里的|中的|里面|里|中|上|内|的)\s*", "", query)
    query = re.split(
        r"(?:并|然后|再|接着|之后|后|and\s+then|then)",
        query,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    query = query.strip(" .，,。")
    query = re.sub(r"(?:吧|嘛|吗|呢|么)$", "", query).strip(" .，,。")
    return "" if query.lower() in _GENERIC_MUSIC_QUERIES else query


def clean_target(value: str) -> str:
    target = clean(value)
    target = re.split(
        r"(?:然后|并且|并|再|接着|之后|后|输入|键入|填写|填入|写入|写|and\s+then|then|and|type|enter|fill)",
        target,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    target = re.sub(
        r"\s*(?:按钮|控件|元素|菜单项|菜单|复选框|输入框|文本框|输入栏|"
        r"button|control|element|menu item|menu|checkbox|field|input|text field|text box|textbox)$",
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
    target = re.sub(
        r"\s*(?:button|control|element|menu item|menu|checkbox|field|input|text field|text box|textbox)$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"^(?:在|用|通过)\s*[\w .·-]{1,40}?(?:里|中|上|内|的)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(r"^(?:的|里|中|上|内)\s*", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:可见的?|visible|shown)\s*", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:搜索框|搜索栏)$", "搜索", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:地址栏)$", "地址", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:消息框|聊天框)$", "消息", target, flags=re.IGNORECASE)
    return target.strip(" .，,。")


def clean_type_target(value: str, *, app_name: str = "") -> str:
    raw_field_suffix = re.search(
        r"(?:^|并|然后|再|接着|之后|后|,|，)\s*(?:在|向|到|in|inside|into)?\s*"
        r"(?P<field>搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search box|search field|message field|address bar|input field|text box)$",
        clean(value),
        flags=re.IGNORECASE,
    )
    if raw_field_suffix:
        field = raw_field_suffix.group("field").strip()
        return clean_target(field) or field

    named_field_match = re.search(
        r"(?:名为|叫做|叫)\s*(?P<name>[^。！？!?，,]{1,40}?)\s*(?:的)?\s*"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏)",
        clean(value),
        flags=re.IGNORECASE,
    )
    if named_field_match:
        return f"名为 {named_field_match.group('name').strip()} 的"

    target = clean_target(value)
    target = re.sub(
        r"^(?:打开|启动|切到|聚焦|open|launch|focus|switch to)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    target = re.sub(
        r"^(?:在|用|通过|in|inside|within|using|with)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    clean_app_name = clean(app_name)
    if clean_app_name and target.lower().startswith(clean_app_name.lower()):
        target = target[len(clean_app_name):].strip()
    if clean_app_name:
        target = _strip_app_prefix_from_type_target(target)
    target = re.sub(r"^(?:的|在|里|中|上|in|inside)\s*", "", target, flags=re.IGNORECASE)
    target = re.sub(
        r"^(?:点击|点一下|点按|单击|按一下|按|click|press|tap)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(r"^.*?(消息框|聊天框)$", r"\1", target, flags=re.IGNORECASE)
    raw_field_match = re.search(
        r"(搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search box|search field|message field|address bar|input field|text box)$",
        clean(value),
        flags=re.IGNORECASE,
    )
    if raw_field_match and clean_app_name and target in {"搜索", "消息", "地址"}:
        target = raw_field_match.group(1)
    if not clean_app_name:
        target = re.sub(r"^(?:搜索框|搜索栏)$", "搜索", target, flags=re.IGNORECASE)
        target = re.sub(r"^(?:地址栏)$", "地址", target, flags=re.IGNORECASE)
        target = re.sub(r"^(?:消息框|聊天框)$", "消息", target, flags=re.IGNORECASE)
    return target.strip(" .，,。") or clean_target(value)


def _strip_app_prefix_from_type_target(value: str) -> str:
    return re.sub(
        r"^[\w .·-]{1,40}?(?:的|里(?:的)?|中(?:的)?|上(?:的)?|内(?:的)?)?\s*"
        r"(?=(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search box|search field|message field|address bar|input field|text box))",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )


def clean_followup_text(value: str) -> str:
    text = clean(value)
    text = re.split(
        r"(?:并且|然后|再|接着|之后|后|并)?\s*(?:发送|提交|确认|回车|搜索|send|submit|confirm|enter|return|search)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = re.sub(r"\s*(?:到|至)?(?:当前|前台)(?:输入框|窗口|应用)?$", "", text, flags=re.IGNORECASE)
    return text.strip(" .，,。")


def role_filter(value: str) -> str:
    lowered = value.lower()
    cleaned = re.sub(
        r"^(?:双击|点击|点一下|点按|单击|按一下|按|点)\s*",
        "",
        clean(value),
        flags=re.IGNORECASE,
    )
    if contains_any(lowered, ["按钮", "button"]):
        return "button"
    if contains_any(lowered, ["菜单", "menu"]):
        return "menu"
    if contains_any(lowered, ["复选框", "checkbox"]):
        return "checkbox"
    if contains_any(
        lowered,
        ["搜索框", "搜索栏", "消息框", "聊天框", "地址栏", "输入框", "文本框", "输入栏", "field", "input", "text"],
    ):
        return "text"
    if cleaned in {"搜索", "登录", "创建", "确认", "发送", "提交"}:
        return "button"
    if re.search(r"\b(?:click|press|tap)\b", lowered):
        if re.search(r"\b(?:in|inside|within)\s+[A-Z][A-Za-z0-9 ._-]*$", value):
            return ""
        return "button"
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
    app = re.sub(r"\s*(?:窗口|windows?)\s*$", "", app, flags=re.IGNORECASE)
    app = re.sub(
        r"\s*(?:所有|全部|哪些|什么|几个|多少|all|open)\s*$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(
        r"\s*(?:有|打开了|开了|正在显示|open|opened|running)\s*$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(r"\s*(?:的)$", "", app, flags=re.IGNORECASE)
    app = app.strip(" .，,。")
    if re.fullmatch(
        r"(?:当前|现在|前台|这个|该)?(?:应用|app|软件|程序|窗口|window)(?:的)?",
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
            r"(?:读取|阅读|读一下|读下|读一读|读|查看|看看|观察|识别|提取|抓取|获取)"
            r".{0,8}(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,8}(?:文字|文本|内容|正文)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|查看|观察|识别|获取)"
            r".{0,40}(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
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
        or re.search(
            r"\bwhere\s+(?:is|are)\s+(?:the\s+)?[^.!?]{0,40}?"
            r"(?:button|control|ui element|text field)\b",
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
    if re.search(r"(?:文字|文本|正文|内容|content|text)", value, flags=re.IGNORECASE):
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
        r"(?:列出|查看|看看|看一下|看下|显示|读取|观察|识别)\s*"
        r"(?P<app_surface>[^。！？!?，,]+?)\s*(?:的)?\s*"
        r"(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|观察|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|观察|识别)\s*"
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
        r"^(?:帮我|请|麻烦|你能|能否|能不能|可以|直接|把|将|列出|查看|看看|看一下|看下|显示|读取|观察|识别|"
        r"list|show|read|inspect|the)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    app = re.sub(r"^(?:打开|启动|开启|运行|拉起|切到|聚焦)\s*", "", app)
    app = re.sub(
        r"^(?:open|launch|start|focus|activate|switch\s+to)\s+",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    app = re.sub(r"\s*(?:并|然后|再|接着|之后|后|and|then)\s*$", "", app, flags=re.IGNORECASE)
    app = re.split(
        r"(?:看看|看一下|看下|查看|读取|观察|识别|有哪些|有什么|有啥|"
        r"\b(?:look\s+at|inspect|view|show\s+me|show|read|which|what)\b)",
        app,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
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
    app = re.sub(
        r"\s*(?:当前|现在|这个|前台|该|current|active|foreground|this)?\s*"
        r"(?:界面|窗口|屏幕|页面|网页|标签页|应用|"
        r"ui|interface|window|screen|page|webpage|app|application)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip()
    if re.fullmatch(
        r"(?:当前|现在|这个|前台|该)?"
        r"(?:应用|app|界面|窗口|屏幕|页面|网页|标签页|"
        r"ui|interface|window|screen|page|webpage)",
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
        "page",
        "webpage",
        "ui",
        "current",
        "active",
        "foreground",
        "my",
        "me",
        "the",
        "this",
        "and",
        "then",
        "你能",
        "我",
        "我的",
        "我现在的",
        "现在的",
        "当前的",
        "这个",
        "那个",
        "该",
        "应用",
        "应用程序",
        "桌面",
        "窗口",
        "界面",
        "屏幕",
        "图",
        "页面",
        "网页",
        "标签页",
        "当前页面",
        "当前网页",
        "这个页面",
        "这个网页",
        "当前",
        "前台",
        "并",
        "然后",
        "再",
        "接着",
        "之后",
        "后",
    }
    return "" if app.lower().strip(" .，,。") in generic else app.strip(" .，,。")


def _looks_like_screen_capture_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:截(?:一下|下)图|截个?图|截个?屏|截图|截屏|屏幕截图|抓屏|拍屏)", value)
        or re.search(
            r"(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面|窗口)"
            r".{0,8}(?:截图|截屏|截一下|截个图|抓屏|拍屏)",
            value,
        )
        or re.search(
            r"(?:截取|截图|截屏|截一下|截个图|截|抓屏|拍屏)"
            r".{0,16}(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面|窗口)",
            value,
        )
        or re.search(r"(?:拍一下|拍下|拍一张|拍个).{0,8}(?:屏幕|桌面|界面|画面|窗口)", value)
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
        or re.search(
            r"(?:打开|启动|开启|拉起|切到|聚焦|把|将).{1,40}"
            r"(?:看看|看一下|看下|查看|读取|读一下|读下|看).{0,16}"
            r"(?:消息|聊天|未读|新消息|cpu|CPU)",
            value,
        )
        or re.search(
            r"\b(?:open|launch|start|focus)\s+.+?\s+(?:and|then)\s+"
            r"(?:read|check|view|look\s+at)\s+(?:messages?|cpu)\b",
            lowered,
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
        r"^(?:截取|截图|截屏|截一下|截下|截个图|截|抓屏|拍屏)\s*"
        r"(?P<app_capture>[^。！？!?，,]+?)\s*(?:的)?\s*"
        r"(?:当前|现在|这个|前台)?(?:窗口|界面|画面|屏幕)?$",
        r"^(?P<app_suffix>[^。！？!?，,]+?)\s*(?:的)?\s*"
        r"(?:当前|现在|这个|前台)?(?:窗口|界面|画面|屏幕)?\s*"
        r"(?:截图|截屏|截一下|截下|截个图|抓屏|拍屏)$",
        r"(?:看一下|看看|看下|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:界面|画面)",
        r"(?P<app2>[^。！？!?，,]+?)\s*(?:界面|画面).{0,8}(?:截图|截屏|看一下|看看|查看|观察)",
        r"(?P<app3>[^。！？!?，,]+?)\s*(?:看一下|看看|看下|查看|观察(?:一下|下)?)\s*(?:界面|画面)",
        r"^(?:把|将)?\s*(?P<app_preopen>[^。！？!?，,]+?)\s*"
        r"(?:打开|启动|开启|拉起)\s*(?:然后|并|再|接着|之后)?\s*"
        r"(?:看看|看一下|看下|查看|读取|读一下|读下|看).{0,16}"
        r"(?:消息|聊天|未读|新消息|cpu|CPU)",
        r"^(?:打开|启动|开启|拉起|切到|聚焦)?\s*(?P<app_messages>[^。！？!?，,]+?)\s*"
        r"(?:然后|并|再|接着|之后)?\s*"
        r"(?:看看|看一下|看下|查看|读取|读一下|读下|看).{0,16}"
        r"(?:消息|聊天|未读|新消息|cpu|CPU)",
        r"\b(?:open|launch|start|focus)\s+(?P<app_messages_en>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:and|then)\s+(?:read|check|view|look\s+at)\s+(?:messages?|cpu)\b",
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
        r"^(?:你能(?:不能)?(?:帮我)?|你可以(?:帮我)?|帮我|请|麻烦|能否|能不能|可以|直接|把|将|the)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(r"\s*(?:并|然后|再|接着|之后|后|then)\s*$", "", app, flags=re.IGNORECASE)
    app = re.sub(r"^(?:打开|启动|开启|运行|拉起|切到|聚焦)\s*", "", app)
    app = re.sub(
        r"^(?:open|launch|start|focus|activate|bring)\s+|^switch\s+to\s+",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = re.sub(
        r"\s*(?:一下|下|起来|掉|显示出来|还原|恢复|取消隐藏|隐藏|藏起来|收起|收起来|"
        r"调出来|打开|启动|开启|运行|拉起|切到|聚焦|到前台|切到前台|置前|前台|叫出来|"
        r"open|launch|start|focus|activate|bring|"
        r"最小化|退出|关闭|关掉|结束|终止|show|restore|unhide|hide|minimi[sz]e|"
        r"quit|close|exit|terminate|please|pls|吗|嘛|呢|吧|么|\?|？)$",
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
        "来",
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
        or re.search(
            r"(?:最小化)\s*(?:当前|现在|前台|这个|该)\s*(?:应用|app|软件|程序)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)\s*(?:应用|app|软件|程序)\s*(?:最小化)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bminimi[sz]e\s+(?:the\s+)?(?:current|foreground|active|this)\s+"
            r"(?:app|application)\b",
            lowered,
        )
    )


def _is_foreground_app_hide_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:隐藏|收起|藏起|藏起来)(?:一下|下)?\s*"
            r"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*"
            r"(?:隐藏|收起|藏起|藏起来)(?:一下|下)?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bhide\s+(?:the\s+)?(?:current|foreground|active|this)\s+(?:app|application)\b",
            lowered,
        )
    )


def _is_show_all_hidden_apps_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:显示|展示|恢复|还原|取消隐藏)\s*(?:所有|全部)?\s*(?:已)?隐藏(?:的)?\s*(?:应用|app|软件|程序)?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:所有|全部)?\s*(?:已)?隐藏(?:的)?\s*(?:应用|app|软件|程序)\s*"
            r"(?:显示|展示|恢复|还原|取消隐藏)(?:出来)?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|restore|unhide)\s+(?:all\s+)?hidden\s+(?:apps?|applications?)\b",
            lowered,
        )
        or re.search(
            r"\bshow\s+all\s+(?:apps?|applications?)\b",
            lowered,
        )
    )


def _parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    combo = clean(value)
    combo = re.sub(r"\s*(?:吗|嘛|呢|please)$", "", combo, flags=re.IGNORECASE).strip()
    if re.search(r"(?:to\s+send|发送|提交|确认)", combo, flags=re.IGNORECASE):
        return None
    combo = re.sub(r"\bkey\b", " ", combo, flags=re.IGNORECASE)
    return legacy_parse_hotkey_combo(combo)


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
        r"^(?:你能帮我|你可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以|直接)\s*",
        "",
        clean(value),
        flags=re.IGNORECASE,
    )
    phrase = re.sub(r"\s*(?:一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)$", "", phrase)
    normalized = re.sub(r"\s+", "", phrase).lower()
    if re.fullmatch(
        r"(?:把|将)?(?:当前|这个|该)?(?:网页|页面|页|标签页)?(?:链接|网址|地址)"
        r"(?:复制|拷贝|复制给我|拷贝给我|放到剪贴板|放进剪贴板|放到系统剪贴板|放进系统剪贴板)",
        normalized,
    ) or re.fullmatch(
        r"(?:copy|put)(?:the)?(?:current|active)?(?:page|tab)?(?:link|url)"
        r"(?:to(?:the)?(?:system)?clipboard|tome)?",
        normalized,
    ):
        return "copy_current_page_link"
    if re.fullmatch(
        r"(?:把|将)?(?:当前|这个|该)?(?:选中|选中的)?(?:文本|文字|内容)"
        r"(?:复制|拷贝)(?:到|至|进|放到|放进)?(?:系统)?(?:剪贴板|粘贴板)",
        normalized,
    ) or re.fullmatch(
        r"(?:copy|put)(?:the)?(?:current|selected)?(?:text|selection|content)"
        r"(?:to(?:the)?(?:system)?clipboard)?",
        normalized,
    ):
        return "copy"
    screenshot_action = _screenshot_safe_shortcut_action(normalized)
    if screenshot_action:
        return screenshot_action
    mapping = {
        "复制": "copy",
        "复制这个": "copy",
        "复制选中内容": "copy",
        "复制选中的内容": "copy",
        "复制选中文本": "copy",
        "复制当前选中内容": "copy",
        "复制当前选中文本": "copy",
        "当前链接复制给我": "copy_current_page_link",
        "当前网页链接复制给我": "copy_current_page_link",
        "当前页面链接复制给我": "copy_current_page_link",
        "复制当前网页链接": "copy_current_page_link",
        "复制当前页面链接": "copy_current_page_link",
        "当前页地址复制": "copy_current_page_link",
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
        "粘贴到当前输入框": "paste",
        "把剪贴板内容粘贴到当前输入框": "paste",
        "pasteintocurrentinput": "paste",
        "pasteintocurrentfield": "paste",
        "隐藏其他应用": "hide_other_apps",
        "隐藏其它应用": "hide_other_apps",
        "隐藏其余应用": "hide_other_apps",
        "隐藏别的应用": "hide_other_apps",
        "hideotherapps": "hide_other_apps",
        "hideotherapplications": "hide_other_apps",
        "任务控制中心": "mission_control",
        "打开任务控制中心": "mission_control",
        "显示任务控制中心": "mission_control",
        "调出任务控制中心": "mission_control",
        "missioncontrol": "mission_control",
        "openmissioncontrol": "mission_control",
        "showmissioncontrol": "mission_control",
        "打开聚焦搜索": "spotlight_search",
        "显示聚焦搜索": "spotlight_search",
        "聚焦搜索": "spotlight_search",
        "spotlight": "spotlight_search",
        "spotlightsearch": "spotlight_search",
        "openspotlight": "spotlight_search",
        "showspotlight": "spotlight_search",
        "打开emoji面板": "emoji_picker",
        "显示emoji面板": "emoji_picker",
        "emoji面板": "emoji_picker",
        "emojipicker": "emoji_picker",
        "showemojipicker": "emoji_picker",
        "打开强制退出窗口": "force_quit_dialog",
        "显示强制退出窗口": "force_quit_dialog",
        "强制退出窗口": "force_quit_dialog",
        "forcequitapplications": "force_quit_dialog",
        "showforcequitapplications": "force_quit_dialog",
        "锁屏": "lock_screen",
        "锁定屏幕": "lock_screen",
        "lockscreen": "lock_screen",
        "全选": "select_all",
        "selectall": "select_all",
        "撤销": "undo",
        "undo": "undo",
        "重做": "redo",
        "redo": "redo",
        "查找": "find",
        "打开查找": "find",
        "搜索": "find",
        "打开搜索": "find",
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
        "新建笔记": "new_note",
        "新建一个笔记": "new_note",
        "新建一条笔记": "new_note",
        "新建一篇笔记": "new_note",
        "新笔记": "new_note",
        "创建笔记": "new_note",
        "创建一个笔记": "new_note",
        "新建备忘录": "new_note",
        "新建一个备忘录": "new_note",
        "新建一条备忘录": "new_note",
        "新建一篇备忘录": "new_note",
        "新备忘录": "new_note",
        "创建备忘录": "new_note",
        "创建一个备忘录": "new_note",
        "新建提醒事项": "new_reminder",
        "新建一个提醒事项": "new_reminder",
        "新建一条提醒事项": "new_reminder",
        "新建一项提醒事项": "new_reminder",
        "新建提醒": "new_reminder",
        "新提醒": "new_reminder",
        "创建提醒事项": "new_reminder",
        "创建一个提醒事项": "new_reminder",
        "创建提醒": "new_reminder",
        "创建一个提醒": "new_reminder",
        "新建日程": "new_event",
        "新建一个日程": "new_event",
        "新建一条日程": "new_event",
        "新建日历事件": "new_event",
        "新建一个日历事件": "new_event",
        "新建事件": "new_event",
        "新建一个事件": "new_event",
        "新建会议": "new_event",
        "新会议": "new_event",
        "创建日程": "new_event",
        "创建一个日程": "new_event",
        "创建事件": "new_event",
        "创建一个事件": "new_event",
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
        "newmeeting": "new_event",
        "newcalendarevent": "new_event",
        "makeanewevent": "new_event",
        "createanewevent": "new_event",
        "makenewevent": "new_event",
        "createnewevent": "new_event",
        "makeanewmeeting": "new_event",
        "createanewmeeting": "new_event",
        "新建消息": "new_message",
        "新消息": "new_message",
        "创建消息": "new_message",
        "创建一条消息": "new_message",
        "写消息": "new_message",
        "写新消息": "new_message",
        "撰写消息": "new_message",
        "新建聊天": "new_message",
        "新聊天": "new_message",
        "创建聊天": "new_message",
        "新建会话": "new_message",
        "新会话": "new_message",
        "新建邮件": "new_message",
        "新邮件": "new_message",
        "创建邮件": "new_message",
        "创建一封邮件": "new_message",
        "写邮件": "new_message",
        "写新邮件": "new_message",
        "撰写邮件": "new_message",
        "撰写新邮件": "new_message",
        "发邮件": "new_message",
        "发送邮件": "new_message",
        "composemessage": "new_message",
        "newmessage": "new_message",
        "newchat": "new_message",
        "newconversation": "new_message",
        "startconversation": "new_message",
        "composeemail": "new_message",
        "composemail": "new_message",
        "newemail": "new_message",
        "newmail": "new_message",
        "createemail": "new_message",
        "createmail": "new_message",
        "writeemail": "new_message",
        "writemail": "new_message",
        "新建文档": "new_document",
        "新建一个文档": "new_document",
        "新建一份文档": "new_document",
        "新文档": "new_document",
        "新建文件": "new_document",
        "新建一个文件": "new_document",
        "新建一份文件": "new_document",
        "新文件": "new_document",
        "新建表格": "new_document",
        "新建一个表格": "new_document",
        "新建一份表格": "new_document",
        "新表格": "new_document",
        "新建工作簿": "new_document",
        "新建一个工作簿": "new_document",
        "新工作簿": "new_document",
        "新建演示": "new_document",
        "新建一个演示": "new_document",
        "新建演示文稿": "new_document",
        "新建一个演示文稿": "new_document",
        "新建一份演示文稿": "new_document",
        "新演示文稿": "new_document",
        "新建幻灯片": "new_document",
        "新建一个幻灯片": "new_document",
        "新幻灯片": "new_document",
        "新建ppt": "new_document",
        "新ppt": "new_document",
        "新建项目": "new_document",
        "新建一个项目": "new_document",
        "创建项目": "new_document",
        "创建一个项目": "new_document",
        "新项目": "new_document",
        "新建工作区": "new_document",
        "新建一个工作区": "new_document",
        "创建工作区": "new_document",
        "创建一个工作区": "new_document",
        "新建workspace": "new_document",
        "创建workspace": "new_document",
        "创建新workspace": "new_document",
        "新workspace": "new_document",
        "newdocument": "new_document",
        "newfile": "new_document",
        "newworkbook": "new_document",
        "newspreadsheet": "new_document",
        "newpresentation": "new_document",
        "newslide": "new_document",
        "newproject": "new_document",
        "newworkspace": "new_document",
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
        "makeanewproject": "new_document",
        "createanewproject": "new_document",
        "makenewproject": "new_document",
        "createnewproject": "new_document",
        "makeanewworkspace": "new_document",
        "createanewworkspace": "new_document",
        "makenewworkspace": "new_document",
        "createnewworkspace": "new_document",
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
        "下一个窗口": "next_window",
        "切到下一个窗口": "next_window",
        "切换到下一个窗口": "next_window",
        "nextwindow": "next_window",
        "switchtonextwindow": "next_window",
        "下一个应用": "switch_next_app",
        "切到下一个应用": "switch_next_app",
        "切换到下一个应用": "switch_next_app",
        "nextapp": "switch_next_app",
        "switchtonextapp": "switch_next_app",
        "上一个标签": "previous_tab",
        "上一个标签页": "previous_tab",
        "切到上一个标签页": "previous_tab",
        "切换到上一个标签页": "previous_tab",
        "previoustab": "previous_tab",
        "switchtoprevioustab": "previous_tab",
        "上一个窗口": "previous_window",
        "切到上一个窗口": "previous_window",
        "切换到上一个窗口": "previous_window",
        "previouswindow": "previous_window",
        "switchtopreviouswindow": "previous_window",
        "上一个应用": "switch_previous_app",
        "切到上一个应用": "switch_previous_app",
        "切换到上一个应用": "switch_previous_app",
        "previousapp": "switch_previous_app",
        "switchtopreviousapp": "switch_previous_app",
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
        "gobackonepage": "browser_back",
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
        "显示应用窗口": "application_windows",
        "显示当前应用窗口": "application_windows",
        "显示当前应用所有窗口": "application_windows",
        "显示当前应用的所有窗口": "application_windows",
        "显示前台应用窗口": "application_windows",
        "显示前台应用所有窗口": "application_windows",
        "应用窗口": "application_windows",
        "应用窗口都显示": "application_windows",
        "showappwindows": "application_windows",
        "showapplicationwindows": "application_windows",
        "applicationwindows": "application_windows",
        "最大化": "toggle_full_screen",
        "窗口最大化": "toggle_full_screen",
        "当前窗口最大化": "toggle_full_screen",
        "全屏": "toggle_full_screen",
        "窗口全屏": "toggle_full_screen",
        "当前窗口全屏": "toggle_full_screen",
        "进入全屏": "toggle_full_screen",
        "进入全屏模式": "toggle_full_screen",
        "maximize": "toggle_full_screen",
        "maximizewindow": "toggle_full_screen",
        "fullscreen": "toggle_full_screen",
        "fullscreencurrentwindow": "toggle_full_screen",
        "enterfullscreen": "toggle_full_screen",
        "聚焦地址栏": "focus_address_bar",
        "打开地址栏": "focus_address_bar",
        "选中地址栏": "focus_address_bar",
        "focusaddressbar": "focus_address_bar",
        "focusurlbar": "focus_address_bar",
        "addressbar": "focus_address_bar",
    }
    action = mapping.get(normalized, "")
    if action:
        return action
    return _finder_safe_shortcut_action(normalized, mode="exact")


def _screenshot_safe_shortcut_action(normalized: str) -> str:
    if normalized in {
        "选区截图",
        "截图选区",
        "截取选区",
        "区域截图",
        "选择区域截图",
        "选取区域截图",
        "框选截图",
        "screenshotselection",
        "screenshotselectedarea",
        "selectedareascreenshot",
        "regionscreenshot",
        "captureselectedarea",
        "capturearegion",
        "capturearea",
    }:
        return "screenshot_selection"
    if normalized in {
        "截图工具",
        "打开截图工具",
        "显示截图工具",
        "启动截图工具",
        "截图面板",
        "打开截图面板",
        "显示截图面板",
        "启动截图面板",
        "屏幕截图工具",
        "打开屏幕截图工具",
        "屏幕截图面板",
        "打开屏幕截图面板",
        "录屏",
        "屏幕录制",
        "录屏工具",
        "打开录屏工具",
        "录屏面板",
        "打开录屏面板",
        "开始录屏",
        "screenshottoolbar",
        "openscreenshottoolbar",
        "showscreenshottoolbar",
        "launchscreenshottoolbar",
        "screenshottool",
        "openscreenshottool",
        "screenshotpanel",
        "openscreenshotpanel",
        "screencapturetoolbar",
        "openscreencapturetoolbar",
        "screencapturetool",
        "openscreencapturetool",
        "screencapturepanel",
        "openscreencapturepanel",
        "screenrecording",
        "screenrecordingtoolbar",
        "openscreenrecordingtoolbar",
        "screenrecordingtool",
        "openscreenrecordingtool",
        "screenrecordingpanel",
        "openscreenrecordingpanel",
    }:
        return "screenshot_toolbar"
    return ""


def _safe_shortcut_action_from_trailing_phrase(value: str) -> str:
    normalized = re.sub(r"[\s._·-]+", "", clean(value).lower())
    if not normalized:
        return ""
    screenshot_action = _screenshot_safe_shortcut_action(normalized)
    if screenshot_action:
        return screenshot_action
    if contains_any(normalized, ["音量", "声音", "亮度", "volume", "sound", "brightness"]):
        return ""
    full_screen_suffixes = (
        "窗口最大化",
        "当前窗口最大化",
        "最大化",
        "窗口全屏",
        "当前窗口全屏",
        "进入全屏模式",
        "进入全屏",
        "全屏",
        "maximizewindow",
        "maximize",
        "fullscreencurrentwindow",
        "fullscreenwindow",
        "fullscreen",
        "enterfullscreen",
    )
    if any(normalized.endswith(suffix) for suffix in full_screen_suffixes):
        return "toggle_full_screen"
    new_document_suffixes = (
        "新建文档",
        "新建一个文档",
        "新建一份文档",
        "新建文件",
        "新建一个文件",
        "新建一份文件",
        "新建表格",
        "新建一个表格",
        "新建一份表格",
        "新建工作簿",
        "新建一个工作簿",
        "新建演示",
        "新建一个演示",
        "新建演示文稿",
        "新建一个演示文稿",
        "新建一份演示文稿",
        "新建幻灯片",
        "新建一个幻灯片",
        "新建ppt",
        "新建项目",
        "新建一个项目",
        "创建项目",
        "创建一个项目",
        "新建工作区",
        "新建一个工作区",
        "创建工作区",
        "创建一个工作区",
        "新建workspace",
        "创建workspace",
        "创建新workspace",
        "新workspace",
        "newdocument",
        "newfile",
        "newworkbook",
        "newspreadsheet",
        "newpresentation",
        "newslide",
        "newproject",
        "newworkspace",
        "makeanewdocument",
        "createanewdocument",
        "makeanewfile",
        "createanewfile",
        "makeanewworkbook",
        "createanewworkbook",
        "makeanewspreadsheet",
        "createanewspreadsheet",
        "makeanewpresentation",
        "createanewpresentation",
        "makeanewproject",
        "createanewproject",
        "makeanewworkspace",
        "createanewworkspace",
    )
    if any(normalized.endswith(suffix) for suffix in new_document_suffixes):
        return "new_document"
    finder_action = _finder_safe_shortcut_action(normalized, mode="suffix")
    if finder_action:
        return finder_action
    return ""


def _finder_safe_shortcut_action(normalized: str, *, mode: str) -> str:
    for action, phrase in _FINDER_SAFE_SHORTCUT_PHRASES:
        clean_phrase = re.sub(r"[\s._·-]+", "", phrase.lower())
        if mode == "exact" and normalized == clean_phrase:
            return action
        if mode == "suffix" and normalized.endswith(clean_phrase):
            return action
    return ""


def _compound_safe_shortcut_actions(value: str) -> list[str]:
    normalized = re.sub(r"[\s._·-]+", "", clean(value).lower())
    if not normalized:
        return []
    if "全选" in normalized and "复制" in normalized and normalized.index("全选") < normalized.index("复制"):
        return ["select_all", "copy"]
    if (
        "selectall" in normalized
        and "copy" in normalized
        and normalized.index("selectall") < normalized.index("copy")
    ):
        return ["select_all", "copy"]
    return []


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
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|聚焦|焦点到)?\s*"
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
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|聚焦|焦点到)?\s*"
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
    return legacy_normalize_hotkey_token(value)


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
