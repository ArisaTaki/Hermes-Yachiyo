"""Compact observed-content snapshots for model follow-up context."""

from __future__ import annotations

import re
from typing import Any


FOLLOWUP_CONTENT_SNAPSHOT_TOOLS: frozenset[str] = frozenset(
    {
        "browser.extract_text",
        "browser.open_url_and_extract_text",
        "clipboard.read",
        "data.analyze",
        "desktop.ui_elements",
        "file.read",
        "screen.capture",
        "workspace.read",
    }
)


def latest_followup_content_snapshot(
    timeline: list[dict[str, Any]],
    observation_tools: list[str],
) -> dict[str, Any]:
    wanted_tools = _wanted_followup_content_tools(observation_tools)
    for event in reversed(timeline):
        tool_name, result, input_preview = _followup_tool_event_parts(event)
        if tool_name not in wanted_tools:
            continue
        snapshot = followup_content_snapshot_for_tool_call(tool_name, result, input_preview)
        if snapshot:
            return snapshot
    return {}


def followup_content_snapshots(
    timeline: list[dict[str, Any]],
    observation_tools: list[str],
    *,
    max_snapshots: int = 6,
) -> list[dict[str, Any]]:
    wanted_tools = _wanted_followup_content_tools(observation_tools)
    clean_max = max(1, int(max_snapshots or 6))
    snapshots: list[dict[str, Any]] = []
    seen_tools: set[str] = set()
    for event in reversed(timeline):
        tool_name, result, input_preview = _followup_tool_event_parts(event)
        if tool_name not in wanted_tools or tool_name in seen_tools:
            continue
        snapshot = followup_content_snapshot_for_tool_call(tool_name, result, input_preview)
        if not snapshot:
            continue
        snapshots.append(snapshot)
        seen_tools.add(tool_name)
        if len(snapshots) >= clean_max:
            break
    snapshots.reverse()
    return snapshots


def followup_content_snapshot_for_tool_call(
    tool_name: str,
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "desktop.ui_elements":
        return desktop_ui_elements_content_snapshot(result, input_preview)
    if tool_name == "screen.capture":
        return screen_capture_content_snapshot(result, input_preview)
    if tool_name in {"browser.extract_text", "browser.open_url_and_extract_text"}:
        return browser_extract_text_content_snapshot(result, input_preview, source_tool=tool_name)
    if tool_name == "clipboard.read":
        return clipboard_read_content_snapshot(result, input_preview)
    if tool_name == "data.analyze":
        return data_analyze_content_snapshot(result, input_preview)
    if tool_name in {"workspace.read", "file.read"}:
        return workspace_read_content_snapshot(result, input_preview, source_tool=tool_name)
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
    *,
    source_tool: str = "workspace.read",
) -> dict[str, Any]:
    raw_text = result.get("content") if "content" in result else result.get("text")
    text, preview_truncated = _clean_followup_content_text_preview(
        raw_text,
        max_chars=4000,
        preserve_lines=True,
    )
    snapshot: dict[str, Any] = {
        "source_tool": source_tool,
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


def data_analyze_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    artifact_paths = _ordered_text_list(result.get("artifact_paths"))
    if not artifact_paths:
        artifact_paths = [
            str(item.get("path") or "").strip()
            for item in result.get("artifacts") or []
            if isinstance(item, dict) and str(item.get("path") or "").strip()
        ]
    artifact_manifest = _artifact_manifest_preview(
        result.get("artifact_manifest") or input_preview.get("artifact_manifest")
    )
    columns = _ordered_text_list(result.get("columns"))
    path = str(result.get("path") or input_preview.get("path") or "").strip()
    source_kind = str(result.get("source_kind") or input_preview.get("source_kind") or "").strip()
    snapshot: dict[str, Any] = {
        "source_tool": "data.analyze",
        "ok": bool(result.get("ok")),
        "path": path,
        "source_kind": source_kind,
        "rows": _number_value(result.get("rows")),
        "analyzed_rows": _number_value(result.get("analyzed_rows")),
        "columns": columns,
        "artifact_paths": artifact_paths,
        "artifact_manifest": artifact_manifest,
        "artifact_count": len(artifact_paths),
    }
    text = data_analyze_snapshot_text(snapshot, result)
    if text:
        snapshot["text"] = text
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def data_analyze_snapshot_text(snapshot: dict[str, Any], result: dict[str, Any]) -> str:
    if snapshot.get("ok") is False:
        summary = clean_followup_content_text(result.get("summary") or result.get("error"), max_chars=1000)
        return f"Data analysis failed: {summary}" if summary else ""
    path = str(snapshot.get("path") or "data source")
    source_kind = str(snapshot.get("source_kind") or "data")
    rows = _number_value(snapshot.get("rows"))
    analyzed_rows = _number_value(snapshot.get("analyzed_rows"))
    columns = _ordered_text_list(snapshot.get("columns"))
    artifact_manifest = snapshot.get("artifact_manifest")
    artifact_paths = _ordered_text_list(snapshot.get("artifact_paths"))
    lines = [f"Data analysis result for {path} ({source_kind})."]
    if rows:
        row_text = f"{rows} rows"
        if analyzed_rows and analyzed_rows != rows:
            row_text = f"{row_text}; analyzed {analyzed_rows}"
        lines.append(row_text)
    if columns:
        lines.append(f"Columns: {', '.join(columns[:12])}")
    artifacts_text = _artifact_manifest_text(artifact_manifest)
    if not artifacts_text and artifact_paths:
        artifacts_text = ", ".join(artifact_paths[:8])
    if artifacts_text:
        lines.append(f"Artifacts: {artifacts_text}")
    summary = clean_followup_content_text(result.get("summary"), max_chars=1000)
    if summary:
        lines.append(summary)
    return "\n".join(lines)


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


def _wanted_followup_content_tools(observation_tools: list[str]) -> set[str]:
    wanted_tools = {
        str(tool or "").strip()
        for tool in observation_tools
        if str(tool or "").strip()
    }
    if not wanted_tools:
        return set(FOLLOWUP_CONTENT_SNAPSHOT_TOOLS)
    return wanted_tools & set(FOLLOWUP_CONTENT_SNAPSHOT_TOOLS)


def _followup_tool_event_parts(
    event: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if event.get("event") != "agent.tool.call":
        return "", {}, {}
    tool_name = str(event.get("detail") or event.get("tool") or "").strip()
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
    return tool_name, result, input_preview


def _artifact_manifest_preview(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    manifest: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        kind = str(item.get("kind") or item.get("actual_kind") or "").strip()
        entry = {"path": path}
        if kind:
            entry["kind"] = kind
        manifest.append(entry)
        if len(manifest) >= 8:
            break
    return manifest


def _artifact_manifest_text(value: Any) -> str:
    items = value if isinstance(value, list) else []
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        kind = str(item.get("kind") or "").strip()
        parts.append(f"{path} ({kind})" if kind else path)
    return ", ".join(parts)


def _ordered_text_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values


def _number_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
