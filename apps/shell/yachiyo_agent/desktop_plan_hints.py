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
}


def app_control_mode(text: str) -> str:
    return "focus" if contains_any(text, ["切到", "聚焦", "focus", "switch to"]) else "open"


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


def media_playback_hint(text: str) -> dict[str, str]:
    action = media_action_hint(text)
    return {
        "action": action,
        "app_name": music_app_name_hint(text),
        "query": media_query_hint(text) if action == "play" else "",
    }


def media_tool_preview(
    inputs: Mapping[str, Any],
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    allowed = _allowed_tool_set(allowed_tools)
    action = str(inputs.get("action") or "").strip() or "play"
    app_name = str(inputs.get("app_name") or "").strip()
    query = str(inputs.get("query") or "").strip()
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
        tool_name = _first_allowed(
            ("media.apple_music_open_and_play", "media.apple_music_control", "media.system_control"),
            allowed,
        )
        return tool_name, {"action": "play"} if tool_name in {"media.apple_music_control", "media.system_control"} else {}
    tool_name = _first_allowed(("media.apple_music_control", "media.system_control"), allowed)
    return tool_name, {"action": action} if tool_name else {}


def media_action_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if contains_any(lowered, ["当前播放", "现在播放", "正在播放", "播放什么", "status", "currently playing"]):
        return "status"
    if contains_any(lowered, ["下一首", "下一曲", "next"]):
        return "next"
    if contains_any(lowered, ["上一首", "上一曲", "previous", "back"]):
        return "previous"
    if contains_any(lowered, ["暂停", "停止播放", "pause", "stop playing"]):
        return "pause"
    if contains_any(lowered, ["继续", "恢复播放", "resume", "continue"]):
        return "play"
    if contains_any(lowered, ["播放", "播", "放", "play"]):
        return "play"
    return ""


def music_app_name_hint(text: str) -> str:
    lowered = str(text or "").lower()
    if re.search(r"spotify", lowered):
        return "Spotify"
    if re.search(r"网易云|netease", lowered):
        return "网易云音乐"
    if re.search(r"qq\s*音乐|qq music", lowered):
        return "QQ 音乐"
    if re.search(r"apple\s*music|苹果音乐|音乐(?:应用|app)?", lowered):
        return "Music"
    return ""


def media_query_hint(text: str) -> str:
    value = clean(text)
    patterns = (
        r"(?:播放|播|放)(?:一下|一首|首)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:play|start playing)\s+(?P<query_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = match.groupdict().get("query") or match.groupdict().get("query_en") or ""
        query = _clean_media_query(query)
        if query:
            return query
    return ""


def _clean_media_query(value: str) -> str:
    query = clean(value)
    query = re.sub(
        r"(?:用|在|打开|启动|通过)?\s*(?:apple\s*music|苹果音乐|音乐(?:应用|app)?|spotify|网易云音乐?|qq\s*音乐|qq music)",
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
