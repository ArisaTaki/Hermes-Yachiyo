"""Local file and Finder access hints for runtime planner execution."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.path_aliases import common_desktop_path_marker


def file_access_hint(prompt: str) -> dict[str, str]:
    text = _clean(prompt)
    if not text:
        return {}
    if re.search(r"https?://", text, flags=re.IGNORECASE):
        return {}
    reveal_path = _reveal_path(text)
    if reveal_path:
        return {"action": "reveal_path", "path": reveal_path}
    open_path = _open_path(text)
    if open_path:
        return {"action": "open_path", "path": open_path}
    return {}


def file_access_tool_preview(
    inputs: Mapping[str, Any],
    allowed_tools: Iterable[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    action = str(inputs.get("action") or "").strip()
    path = str(inputs.get("path") or "").strip()
    if not action or not path:
        return None, {}
    tool_name = "desktop.reveal_path" if action == "reveal_path" else "desktop.open_path"
    if allowed_tools is not None and tool_name not in {str(tool or "").strip() for tool in allowed_tools}:
        return None, {}
    return tool_name, {"path": path}


def _open_path(text: str) -> str:
    if _is_reveal_request(text):
        return ""
    dynamic_path = _dynamic_open_path(text)
    if dynamic_path:
        return dynamic_path
    explicit_path = _explicit_path(text)
    if explicit_path and _looks_like_open_request(text):
        return explicit_path
    common_path = _common_path(text)
    if common_path and _looks_like_open_request(text):
        return common_path
    return ""


def _reveal_path(text: str) -> str:
    if not _is_reveal_request(text):
        return ""
    dynamic_path = _dynamic_reveal_path(text)
    if dynamic_path:
        return dynamic_path
    explicit_path = _explicit_path(text)
    if explicit_path:
        return explicit_path
    return _common_path(text)


def _dynamic_open_path(text: str) -> str:
    lowered = text.lower()
    if _contains_any(text, ("选中的 finder 文件", "当前选中的 finder 文件", "选中的文件", "当前选中的文件")):
        return "finder_selection"
    if re.search(r"\bopen\s+(?:the\s+)?(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item)\b", lowered):
        return "finder_selection"
    if _contains_any(text, ("刚才的截图", "最新截图", "最近截图", "上一张截图")):
        return "latest_screenshot"
    if re.search(r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent|last)\s+(?:screenshot|screen\s+shot)\b", lowered):
        return "latest_screenshot"
    if _contains_any(text, ("下载目录里的最新文件", "最近下载", "最新下载", "最后下载", "上一个下载")):
        return "latest_download"
    if re.search(r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+(?:download|downloaded\s+(?:file|item))\b", lowered):
        return "latest_download"
    if _contains_any(text, ("桌面最近文件", "桌面最新文件", "桌面最近项目", "桌面最新项目")):
        return "latest_desktop_item"
    if re.search(r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+(?:desktop\s+)?(?:file|item)\b", lowered):
        return "latest_desktop_item"
    return ""


def _dynamic_reveal_path(text: str) -> str:
    lowered = text.lower()
    if _contains_any(text, ("选中的 finder 文件", "当前选中的 finder 文件", "选中文件", "选中的文件")):
        return "finder_selection"
    if re.search(r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item)", lowered):
        return "finder_selection"
    if _contains_any(text, ("刚才的截图", "最新截图", "最近截图", "上一张截图")):
        return "latest_screenshot"
    if re.search(r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent|last)\s+(?:screenshot|screen\s+shot)", lowered):
        return "latest_screenshot"
    if _contains_any(text, ("最近下载", "最新下载", "最后下载", "上一个下载")):
        return "latest_download"
    if re.search(r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+(?:download|downloaded\s+(?:file|item))", lowered):
        return "latest_download"
    if _contains_any(text, ("桌面最近文件", "桌面最新文件", "桌面最近项目", "桌面最新项目")):
        return "latest_desktop_item"
    if re.search(r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+(?:desktop\s+)?(?:file|item)", lowered):
        return "latest_desktop_item"
    return ""


def _explicit_path(text: str) -> str:
    match = re.search(r"(?P<path>(?:~|/|\./|\../)[^。！？!?，,]+)", text)
    if not match:
        return ""
    return _normalize_path(match.group("path"))


def _common_path(text: str) -> str:
    return common_desktop_path_marker(text)


def _looks_like_open_request(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(text, ("打开", "开启", "拉起", "进入", "查看", "看看")) or bool(
        re.search(r"\b(?:open|view)\b", lowered)
    )


def _is_reveal_request(text: str) -> bool:
    lowered = text.lower()
    return _contains_any(text, ("显示", "定位", "找一下", "找到")) or bool(
        re.search(r"\b(?:show|reveal|locate)\b", lowered)
    )


def _normalize_path(value: str) -> str:
    path = _clean(value)
    path = re.sub(r"\s+in\s+(?:the\s+)?finder$", "", path, flags=re.IGNORECASE)
    path = re.sub(r"(?:文件夹|目录|路径|folder|directory|path)$", "", path, flags=re.IGNORECASE)
    return path.strip(" .，,。")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term.lower() in text.lower() for term in terms)
