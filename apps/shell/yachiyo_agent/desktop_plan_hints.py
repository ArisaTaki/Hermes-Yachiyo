"""Shared desktop intent parsing hints for planner snapshots and execution."""

from __future__ import annotations

import re
from typing import Any


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


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def contains_any(text: str, needles: list[str] | tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle).lower() in lowered for needle in needles)
