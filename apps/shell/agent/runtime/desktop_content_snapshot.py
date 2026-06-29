"""Compact desktop observation snapshots for model follow-up context."""

from __future__ import annotations

import re
from typing import Any


def latest_desktop_content_snapshot(
    timeline: list[dict[str, Any]],
    observation_tools: list[str],
) -> dict[str, Any]:
    wanted_tools = {str(tool or "").strip() for tool in observation_tools if str(tool or "").strip()}
    if not wanted_tools:
        wanted_tools = {"desktop.ui_elements", "screen.capture"}
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        tool_name = str(event.get("detail") or event.get("tool") or "").strip()
        if tool_name not in wanted_tools:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if tool_name == "desktop.ui_elements":
            return desktop_ui_elements_content_snapshot(result, input_preview)
        if tool_name == "screen.capture":
            return screen_capture_content_snapshot(result, input_preview)
    return {}


def desktop_ui_elements_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    elements = data.get("elements")
    if not isinstance(elements, list):
        elements = result.get("elements") if isinstance(result.get("elements"), list) else []
    lines, truncated = desktop_ui_element_text_lines(elements)
    app_name = str(
        data.get("app_name")
        or input_preview.get("app_name")
        or result.get("app_name")
        or ""
    ).strip()
    title = str(data.get("title") or result.get("title") or "").strip()
    snapshot: dict[str, Any] = {
        "source_tool": "desktop.ui_elements",
        "ok": bool(result.get("ok")),
        "app_name": app_name,
        "title": title,
        "element_count": int(data.get("count") or len(elements) or 0),
        "text_item_count": len(lines),
        "truncated": bool(truncated or data.get("truncated")),
    }
    if lines:
        snapshot["text"] = "\n".join(lines)
    if not result.get("ok"):
        for key in ("summary", "error", "permission_targets", "recovery_hints"):
            if result.get(key) not in (None, "", []):
                snapshot[key] = result.get(key)
    return {key: value for key, value in snapshot.items() if value not in ("", None, [])}


def screen_capture_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
    path = str(data.get("path") or artifact.get("path") or "").strip()
    snapshot: dict[str, Any] = {
        "source_tool": "screen.capture",
        "ok": bool(result.get("ok")),
        "path": path,
        "reason": str(input_preview.get("reason") or result.get("reason") or "").strip(),
    }
    if not result.get("ok"):
        for key in ("summary", "error", "permission_targets", "recovery_hints"):
            if result.get(key) not in (None, "", []):
                snapshot[key] = result.get(key)
    elif path:
        snapshot["summary"] = f"Screen image captured at {path}; no OCR text was extracted."
    return {key: value for key, value in snapshot.items() if value not in ("", None, [])}


def desktop_ui_element_text_lines(
    elements: list[Any],
    *,
    max_items: int = 32,
    max_chars: int = 3200,
) -> tuple[list[str], bool]:
    lines: list[str] = []
    seen: set[str] = set()
    used_chars = 0
    truncated = False
    for element in elements:
        if not isinstance(element, dict):
            continue
        text = desktop_ui_element_text(element)
        if not text:
            continue
        normalized = text.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        next_chars = len(text) + 1
        if len(lines) >= max_items or used_chars + next_chars > max_chars:
            truncated = True
            break
        lines.append(text)
        used_chars += next_chars
    return lines, truncated or len(lines) < len(seen)


def desktop_ui_element_text(element: dict[str, Any]) -> str:
    values = [
        clean_desktop_content_text(element.get("value")),
        clean_desktop_content_text(element.get("name")),
        clean_desktop_content_text(element.get("description")),
    ]
    for value in values:
        if useful_desktop_content_text(value):
            return value
    return ""


def clean_desktop_content_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > 500:
        return f"{text[:500].rstrip()}..."
    return text


def useful_desktop_content_text(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 2:
        return False
    lowered = text.casefold()
    if lowered in {
        "true",
        "false",
        "none",
        "null",
        "button",
        "group",
        "image",
        "text",
        "window",
    }:
        return False
    return True
