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
        "desktop.active_window",
        "desktop.inspect_app",
        "desktop.read_ui",
        "desktop.list_apps",
        "desktop.list_windows",
        "desktop.windows",
        "desktop.ui_elements",
        "file.read",
        "file.search",
        "screen.capture",
        "terminal.run",
        "workspace.list",
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
    if tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
        return desktop_ui_elements_content_snapshot(
            result,
            input_preview,
            source_tool=tool_name,
        )
    if tool_name == "desktop.active_window":
        return desktop_active_window_content_snapshot(result, input_preview)
    if tool_name == "desktop.inspect_app":
        return desktop_inspect_app_content_snapshot(result, input_preview)
    if tool_name in {"desktop.list_windows", "desktop.windows"}:
        return desktop_windows_content_snapshot(result, input_preview, source_tool=tool_name)
    if tool_name == "screen.capture":
        return screen_capture_content_snapshot(result, input_preview)
    if tool_name in {"browser.extract_text", "browser.open_url_and_extract_text"}:
        return browser_extract_text_content_snapshot(result, input_preview, source_tool=tool_name)
    if tool_name == "clipboard.read":
        return clipboard_read_content_snapshot(result, input_preview)
    if tool_name == "data.analyze":
        return data_analyze_content_snapshot(result, input_preview)
    if tool_name == "terminal.run":
        return terminal_run_content_snapshot(result, input_preview)
    if tool_name in {"workspace.list", "file.search"}:
        return workspace_list_content_snapshot(
            result,
            input_preview,
            source_tool=tool_name,
        )
    if tool_name == "desktop.list_apps":
        return desktop_list_apps_content_snapshot(result, input_preview)
    if tool_name in {"workspace.read", "file.read"}:
        return workspace_read_content_snapshot(result, input_preview, source_tool=tool_name)
    return {}


def desktop_ui_elements_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
    *,
    source_tool: str = "desktop.ui_elements",
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
        "source_tool": source_tool,
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


def desktop_active_window_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    app_name = str(
        data.get("app_name")
        or data.get("frontmost_app")
        or result.get("app_name")
        or input_preview.get("app_name")
        or ""
    ).strip()
    title = str(
        data.get("title")
        or data.get("window_title")
        or result.get("title")
        or ""
    ).strip()
    if result.get("ok") and not app_name:
        return {}
    snapshot: dict[str, Any] = {
        "source_tool": "desktop.active_window",
        "ok": bool(result.get("ok")),
        "app_name": app_name,
        "title": title,
    }
    if app_name or title:
        snapshot["text"] = "Active window: " + " - ".join(
            part for part in (app_name, title) if part
        )
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def desktop_windows_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
    *,
    source_tool: str = "desktop.list_windows",
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    windows = data.get("windows") if isinstance(data.get("windows"), list) else result.get("windows")
    if not isinstance(windows, list):
        windows = []
    window_candidates = _desktop_window_candidates(windows)
    app_name = str(data.get("app_name") or input_preview.get("app_name") or result.get("app_name") or "").strip()
    lines = []
    for window in window_candidates:
        title = str(window.get("title") or "").strip()
        candidate_app = str(window.get("app_name") or "").strip()
        if title and candidate_app:
            lines.append(f"- {candidate_app}: {title}")
        elif title:
            lines.append(f"- {title}")
        elif candidate_app:
            lines.append(f"- {candidate_app}")
    snapshot: dict[str, Any] = {
        "source_tool": source_tool,
        "ok": bool(result.get("ok")),
        "app_name": app_name,
        "window_count": len(windows),
        "truncated": len(windows) > 24 or bool(data.get("truncated") or result.get("truncated")),
    }
    if window_candidates:
        snapshot["windows"] = window_candidates
    if lines:
        snapshot["text"] = (
            f"Open windows for {app_name}:\n" if app_name else "Open windows:\n"
        ) + "\n".join(lines)
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def desktop_inspect_app_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    ui_result = data.get("ui_elements") if isinstance(data.get("ui_elements"), dict) else {}
    ui_data = ui_result.get("data") if isinstance(ui_result.get("data"), dict) else {}
    elements = ui_data.get("elements")
    if not isinstance(elements, list):
        elements = ui_result.get("elements") if isinstance(ui_result.get("elements"), list) else []
    ui_lines, ui_truncated = desktop_ui_element_text_lines(elements)
    active_result = data.get("active_window") if isinstance(data.get("active_window"), dict) else {}
    active_data = active_result.get("data") if isinstance(active_result.get("data"), dict) else {}
    app_name = str(
        data.get("app_name")
        or input_preview.get("app_name")
        or result.get("app_name")
        or ""
    ).strip()
    active_app_name = str(
        active_data.get("app_name")
        or active_data.get("frontmost_app")
        or active_result.get("app_name")
        or ""
    ).strip()
    active_title = str(active_data.get("title") or active_result.get("title") or "").strip()
    summary = str(result.get("summary") or "").strip()
    text_lines = []
    if summary:
        text_lines.append(summary)
    if active_app_name or active_title:
        text_lines.append(
            "Active window: " + " - ".join(
                part for part in (active_app_name, active_title) if part
            )
        )
    if ui_lines:
        text_lines.append("Visible UI text:\n" + "\n".join(ui_lines))
    snapshot: dict[str, Any] = {
        "source_tool": "desktop.inspect_app",
        "ok": bool(result.get("ok")),
        "app_name": app_name,
        "requested_app_name": str(data.get("requested_app_name") or "").strip(),
        "discovered_app_name": str(data.get("discovered_app_name") or "").strip(),
        "running": data.get("running"),
        "focus_verified": data.get("focus_verified"),
        "ready_for_foreground_action": data.get("ready_for_foreground_action"),
        "inspection_level": str(data.get("inspection_level") or "").strip(),
        "visibility_limited": data.get("visibility_limited"),
        "window_count": _number_value(data.get("window_count")),
        "ui_element_count": _number_value(data.get("ui_element_count")),
        "control_like_count": _number_value(data.get("control_like_count")),
        "recommended_tools": _string_list(data.get("recommended_tools") or result.get("recommended_tools"))[:8],
        "recovery_actions": _compact_recovery_actions(
            data.get("recovery_actions") or result.get("recovery_actions")
        ),
        "truncated": bool(ui_truncated or ui_data.get("truncated") or ui_result.get("truncated")),
    }
    if text_lines:
        snapshot["text"] = "\n".join(text_lines)
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


def terminal_run_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    stdout_raw = result.get("stdout")
    stderr_raw = result.get("stderr")
    stdout, stdout_truncated = _clean_followup_content_text_preview(
        stdout_raw,
        max_chars=4000,
        preserve_lines=True,
    )
    stderr, stderr_truncated = _clean_followup_content_text_preview(
        stderr_raw,
        max_chars=2000,
        preserve_lines=True,
    )
    exit_code = result.get("exit_code")
    if exit_code in (None, ""):
        exit_code = result.get("returncode")
    snapshot: dict[str, Any] = {
        "source_tool": "terminal.run",
        "ok": bool(result.get("ok")),
        "command": str(result.get("command") or input_preview.get("command") or "").strip(),
        "stdout_length": len(str(stdout_raw or "")),
        "stderr_length": len(str(stderr_raw or "")),
        "truncated": bool(stdout_truncated or stderr_truncated),
    }
    if exit_code not in (None, ""):
        snapshot["exit_code"] = _number_value(exit_code)
    text = _terminal_run_snapshot_text(stdout, stderr, result)
    if text:
        snapshot["text"] = text
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def workspace_list_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
    *,
    source_tool: str = "workspace.list",
) -> dict[str, Any]:
    entries = _workspace_list_entries(result)
    entry_candidates = _workspace_list_entry_candidates(entries)
    lines = []
    for entry in entry_candidates:
        name = str(entry.get("name") or entry.get("path") or "").strip()
        if not name:
            continue
        entry_type = str(entry.get("type") or entry.get("kind") or "").strip()
        lines.append(f"- {name}" + (f" ({entry_type})" if entry_type else ""))
    text = "\n".join(lines)
    snapshot: dict[str, Any] = {
        "source_tool": source_tool,
        "ok": bool(result.get("ok")),
        "path": str(result.get("path") or input_preview.get("path") or ".").strip(),
        "pattern": str(
            input_preview.get("pattern")
            or (result.get("filter") if isinstance(result.get("filter"), dict) else {}).get("pattern")
            or ""
        ).strip(),
        "file_type": str(
            input_preview.get("file_type")
            or (result.get("filter") if isinstance(result.get("filter"), dict) else {}).get("file_type")
            or ""
        ).strip(),
        "entry_count": len(entries),
        "matched_count": _number_value(result.get("matched_count")),
        "total_entries": _number_value(result.get("total_entries")),
        "truncated": len(entries) > 32 or bool(result.get("truncated")),
    }
    if entry_candidates:
        snapshot["entries"] = entry_candidates
    if text:
        snapshot["text"] = (
            f"Candidate files in {snapshot['path']}:\n{text}"
            if snapshot.get("path")
            else f"Candidate files:\n{text}"
        )
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def desktop_list_apps_content_snapshot(
    result: dict[str, Any],
    input_preview: dict[str, Any],
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    apps = data.get("apps") if isinstance(data.get("apps"), list) else result.get("apps")
    if not isinstance(apps, list):
        apps = []
    app_candidates = _desktop_list_app_candidates(apps)
    lines = []
    for app in app_candidates:
        name = str(app.get("name") or "").strip()
        if not name:
            continue
        path = str(app.get("path") or "").strip()
        score = app.get("match_score")
        suffixes = []
        if path:
            suffixes.append(path)
        if score not in (None, ""):
            suffixes.append(f"score={score}")
        lines.append(f"- {name}" + (f" ({'; '.join(suffixes)})" if suffixes else ""))
    query = str(data.get("query") or input_preview.get("query") or "").strip()
    snapshot: dict[str, Any] = {
        "source_tool": "desktop.list_apps",
        "ok": bool(result.get("ok")),
        "query": query,
        "app_count": len(apps),
        "total_count": _number_value(data.get("total_count") or result.get("total_count")),
        "truncated": len(apps) > 24 or bool(data.get("truncated") or result.get("truncated")),
    }
    if app_candidates:
        snapshot["apps"] = app_candidates
    if lines:
        snapshot["text"] = (
            f"Candidate apps for {query}:\n" if query else "Candidate apps:\n"
        ) + "\n".join(lines)
    if not result.get("ok"):
        _add_failure_fields(snapshot, result)
    return _compact_snapshot(snapshot)


def _workspace_list_entries(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("entries", "files", "items"):
        raw_items = result.get(key)
        if not isinstance(raw_items, list):
            continue
        return [dict(item) for item in raw_items if isinstance(item, dict)]
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    for key in ("entries", "files", "items"):
        raw_items = data.get(key)
        if not isinstance(raw_items, list):
            continue
        return [dict(item) for item in raw_items if isinstance(item, dict)]
    return []


def _workspace_list_entry_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in entries[:32]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        path = str(entry.get("path") or entry.get("display_path") or "").strip()
        if not name and path:
            name = path.rsplit("/", 1)[-1]
        if not name and not path:
            continue
        candidate: dict[str, Any] = {}
        if name:
            candidate["name"] = name
        if path and path != name:
            candidate["path"] = path
        entry_type = str(entry.get("type") or entry.get("kind") or "").strip()
        if entry_type:
            candidate["type"] = entry_type
        for key in ("modified_at", "mtime", "mtime_ns", "size", "score"):
            value = entry.get(key)
            if value not in (None, ""):
                candidate[key] = value
        candidates.append(candidate)
    return candidates


def _desktop_list_app_candidates(apps: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for app in apps[:24]:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or "").strip()
        if not name:
            continue
        candidate: dict[str, Any] = {"name": name}
        for source_key, target_key in (
            ("path", "path"),
            ("bundle_id", "bundle_id"),
            ("match_score", "match_score"),
            ("score", "score"),
            ("confidence", "confidence"),
        ):
            value = app.get(source_key)
            if value not in (None, ""):
                candidate[target_key] = value
        candidates.append(candidate)
    return candidates


def _desktop_window_candidates(windows: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for window in windows[:24]:
        if not isinstance(window, dict):
            continue
        title = str(
            window.get("title")
            or window.get("window_title")
            or window.get("name")
            or ""
        ).strip()
        app_name = str(
            window.get("app_name")
            or window.get("app")
            or window.get("owner_name")
            or ""
        ).strip()
        if not title and not app_name:
            continue
        candidate: dict[str, Any] = {}
        if app_name:
            candidate["app_name"] = app_name
        if title:
            candidate["title"] = title
        for key in ("window_id", "id", "is_minimized", "is_visible"):
            value = window.get(key)
            if value not in (None, ""):
                candidate[key] = value
        candidates.append(candidate)
    return candidates


def _terminal_run_snapshot_text(stdout: str, stderr: str, result: dict[str, Any]) -> str:
    if stdout and stderr:
        return f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
    if stdout:
        return stdout
    if stderr:
        return f"stderr:\n{stderr}" if result.get("ok") else stderr
    text, _truncated = _clean_followup_content_text_preview(
        result.get("summary") or result.get("error"),
        max_chars=1000,
        preserve_lines=True,
    )
    return text


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


def _compact_recovery_actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        action = {
            key: item.get(key)
            for key in ("label", "tool", "input", "risk_level", "permission_target")
            if item.get(key) not in (None, "", [])
        }
        if action:
            actions.append(action)
    return actions


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
