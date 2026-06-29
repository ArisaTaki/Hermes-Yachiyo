"""Compact observed-content snapshots for model follow-up context."""

from __future__ import annotations

import re
from typing import Any


def latest_followup_content_snapshot(
    timeline: list[dict[str, Any]],
    observation_tools: list[str],
) -> dict[str, Any]:
    wanted_tools = {str(tool or "").strip() for tool in observation_tools if str(tool or "").strip()}
    if not wanted_tools:
        wanted_tools = {
            "browser.extract_text",
            "browser.open_url_and_extract_text",
            "clipboard.read",
            "desktop.ui_elements",
            "screen.capture",
            "workspace.read",
        }
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
        if tool_name in {"browser.extract_text", "browser.open_url_and_extract_text"}:
            return browser_extract_text_content_snapshot(result, input_preview, source_tool=tool_name)
        if tool_name == "clipboard.read":
            return clipboard_read_content_snapshot(result, input_preview)
        if tool_name == "workspace.read":
            return workspace_read_content_snapshot(result, input_preview)
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
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


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
        _add_failure_fields(snapshot, result)
    elif path:
        snapshot["summary"] = f"Screen image captured at {path}; no OCR text was extracted."
    return _compact_snapshot(snapshot)


def browser_extract_text_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
    *,
    source_tool: str = "browser.extract_text",
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_text = data.get("text") if "text" in data else result.get("text")
    text, preview_truncated = _clean_followup_content_text_preview(
        raw_text,
        max_chars=4000,
        preserve_lines=True,
    )
    snapshot: dict[str, Any] = {
        "source_tool": source_tool,
        "ok": bool(result.get("ok")),
        "url": str(data.get("url") or result.get("url") or input_preview.get("url") or "").strip(),
        "selector": str(data.get("selector") or input_preview.get("selector") or "").strip(),
        "text_length": _number_value(data.get("text_length")) or len(str(raw_text or "")),
        "truncated": bool(data.get("truncated") or preview_truncated),
    }
    if text:
        snapshot["text"] = text
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def clipboard_read_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_text = data.get("text") if "text" in data else result.get("text")
    text, preview_truncated = _clean_followup_content_text_preview(
        raw_text,
        max_chars=4000,
        preserve_lines=True,
    )
    snapshot: dict[str, Any] = {
        "source_tool": "clipboard.read",
        "ok": bool(result.get("ok")),
        "text_length": _number_value(data.get("text_length")) or len(str(raw_text or "")),
        "truncated": bool(data.get("truncated") or preview_truncated),
        "max_chars": _number_value(data.get("max_chars")) or _number_value(input_preview.get("max_chars")),
    }
    if text:
        snapshot["text"] = text
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def workspace_read_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    raw_text = result.get("content") if "content" in result else result.get("text")
    text, preview_truncated = _clean_followup_content_text_preview(
        raw_text,
        max_chars=4000,
        preserve_lines=True,
    )
    snapshot: dict[str, Any] = {
        "source_tool": "workspace.read",
        "ok": bool(result.get("ok")),
        "path": str(result.get("path") or input_preview.get("path") or "").strip(),
        "text_length": len(str(raw_text or "")),
        "truncated": preview_truncated,
    }
    if text:
        snapshot["text"] = text
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


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
        clean_followup_content_text(element.get("value"), max_chars=500),
        clean_followup_content_text(element.get("name"), max_chars=500),
        clean_followup_content_text(element.get("description"), max_chars=500),
    ]
    for value in values:
        if useful_desktop_content_text(value):
            return value
    return ""


def clean_followup_content_text(
    value: Any,
    *,
    max_chars: int = 500,
    preserve_lines: bool = False,
) -> str:
    text, _truncated = _clean_followup_content_text_preview(
        value,
        max_chars=max_chars,
        preserve_lines=preserve_lines,
    )
    return text


def _clean_followup_content_text_preview(
    value: Any,
    *,
    max_chars: int,
    preserve_lines: bool = False,
) -> tuple[str, bool]:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if preserve_lines:
        text = "\n".join(re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return f"{text[:max_chars].rstrip()}...", True
    return text, False


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


def _add_failure_fields(snapshot: dict[str, Any], result: dict[str, Any]) -> None:
    for key in ("summary", "error", "permission_targets", "recovery_hints"):
        if result.get(key) not in (None, "", []):
            snapshot[key] = result.get(key)


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if value not in ("", None, [])}


def _number_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
