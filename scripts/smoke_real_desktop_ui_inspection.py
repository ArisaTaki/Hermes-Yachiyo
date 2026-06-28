#!/usr/bin/env python3
"""Opt-in smoke-test for real macOS named-app UI inspection."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools import desktop as desktop_tools
from scripts.smoke_real_desktop_app_open import (
    DEFAULT_APP_NAME,
    _app_names,
    _cleanup_evidence,
    _resolved_open_app_name,
    _status_running,
)


CONTROL_LIKE_ROLES = {
    "AXButton",
    "AXCheckBox",
    "AXComboBox",
    "AXPopUpButton",
    "AXRadioButton",
    "AXSlider",
    "AXTextArea",
    "AXTextField",
}


def _data(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("data") if isinstance(result.get("data"), dict) else {}


def _running_app_names(result: dict[str, Any]) -> list[str]:
    apps = _data(result).get("apps")
    if not isinstance(apps, list):
        return []
    return [
        str(app.get("name") or "").strip()
        for app in apps
        if isinstance(app, dict) and str(app.get("name") or "").strip()
    ]


def _ui_elements(result: dict[str, Any]) -> list[dict[str, Any]]:
    elements = _data(result).get("elements")
    return [item for item in elements if isinstance(item, dict)] if isinstance(elements, list) else []


def _role_counts(elements: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in elements:
        role = str(element.get("role") or "").strip()
        if not role:
            continue
        counts[role] = counts.get(role, 0) + 1
    return counts


def _control_like_count(elements: list[dict[str, Any]]) -> int:
    return sum(1 for element in elements if str(element.get("role") or "") in CONTROL_LIKE_ROLES)


def run_smoke(
    *,
    app_name: str = DEFAULT_APP_NAME,
    cleanup: bool = True,
) -> dict[str, Any]:
    current_platform = platform.system()
    clean_app_name = str(app_name or "").strip() or DEFAULT_APP_NAME
    if current_platform != "Darwin":
        return {
            "ok": True,
            "mode": "real_desktop_ui_inspection_smoke",
            "skipped": True,
            "platform": current_platform,
            "app_name": clean_app_name,
            "reason": "real desktop UI inspection smoke only runs on macOS",
        }

    discovery = desktop_tools.list_apps(query=clean_app_name, limit=10)
    discovered_names = _app_names(discovery)
    discovered_app_name = next(
        (name for name in discovered_names if name.casefold() == clean_app_name.casefold()),
        discovered_names[0] if discovered_names else clean_app_name,
    )
    before_status = desktop_tools.app_status(discovered_app_name)
    before_running = _status_running(before_status)
    open_result = desktop_tools.app_open(discovered_app_name)
    opened_app_name = _resolved_open_app_name(discovered_app_name, open_result)
    running_result = desktop_tools.running_apps()
    windows_result = desktop_tools.windows(opened_app_name)
    focus_result = desktop_tools.app_focus(opened_app_name)
    active_window = desktop_tools.active_window()
    ui_result = desktop_tools.ui_elements(app_name=opened_app_name, limit=40)
    menu_result = desktop_tools.ui_elements(
        app_name=opened_app_name,
        role_filter="menu",
        limit=40,
    )
    after_status = desktop_tools.app_status(opened_app_name)
    after_running = _status_running(after_status)
    cleanup_result = _cleanup_evidence(
        app_name=opened_app_name,
        cleanup=cleanup,
        before_running=before_running,
        after_running=after_running,
    )

    active_app_name = str(_data(active_window).get("app_name") or "")
    running_names = _running_app_names(running_result)
    elements = _ui_elements(ui_result)
    menu_elements = _ui_elements(menu_result)
    ui_data = _data(ui_result)
    windows_data = _data(windows_result)
    raw_role_counts = ui_data.get("role_counts")
    role_counts = raw_role_counts if isinstance(raw_role_counts, dict) else _role_counts(elements)
    role_bearing_count = sum(
        int(count)
        for count in role_counts.values()
        if isinstance(count, (int, float)) and not isinstance(count, bool)
    )
    unclassified_count = int(
        ui_data.get("unclassified_count") or max(0, len(elements) - role_bearing_count)
    )
    menu_role_count = sum(count for role, count in role_counts.items() if "Menu" in role)
    menu_level_count = int(ui_data.get("menu_level_count") or len(menu_elements) or menu_role_count)
    control_like_count = int(ui_data.get("control_like_count") or _control_like_count(elements))
    ui_inspection_level = str(ui_data.get("inspection_level") or "").strip()
    if not ui_inspection_level:
        ui_inspection_level = (
            "control"
            if control_like_count > 0
            else "menu"
            if menu_level_count > 0
            else "empty"
            if not elements
            else "structural"
        )
    ui_app_name = str(_data(ui_result).get("app_name") or "")
    checks = {
        "discovered_app": discovery.get("ok") is True and bool(discovered_names),
        "open_ok": open_result.get("ok") is True,
        "running_apps_ok": running_result.get("ok") is True,
        "running_apps_contains_app": opened_app_name in running_names,
        "windows_query_ok": windows_result.get("ok") is True,
        "focus_tool_returned": focus_result.get("ok") is True,
        "active_window_query_ok": active_window.get("ok") is True,
        "named_ui_elements_ok": ui_result.get("ok") is True,
        "named_ui_elements_match_app": ui_app_name == opened_app_name,
        "named_ui_elements_nonempty": bool(elements),
        "named_ui_roles_nonempty": bool(role_counts),
        "menu_level_ui_visible": bool(menu_elements) or menu_role_count > 0,
        "cleanup_ok": cleanup_result.get("ok") is True,
        "did_not_quit_existing_app": not (
            cleanup
            and before_running is True
            and cleanup_result.get("attempted") is True
        ),
    }
    return {
        "ok": all(checks.values()),
        "mode": "real_desktop_ui_inspection_smoke",
        "skipped": False,
        "platform": current_platform,
        "app_name": clean_app_name,
        "discovered_app_name": discovered_app_name,
        "opened_app_name": opened_app_name,
        "focus_verified": active_app_name == opened_app_name,
        "window_count": int(_data(windows_result).get("count") or 0),
        "window_visibility_status": str(windows_data.get("window_visibility_status") or ""),
        "window_visibility_limited": windows_data.get("visibility_limited") is True,
        "ui_element_count": len(elements),
        "ui_role_counts": role_counts,
        "ui_unclassified_count": unclassified_count,
        "ui_inspection_level": ui_inspection_level,
        "ui_visibility_status": str(ui_data.get("visibility_status") or ""),
        "ui_visibility_limited": ui_data.get("visibility_limited") is True,
        "menu_level_count": menu_level_count,
        "control_like_count": control_like_count,
        "discovery": {"result": discovery, "names": discovered_names},
        "before_status": before_status,
        "open_result": open_result,
        "running_apps": running_result,
        "windows": windows_result,
        "focus_result": focus_result,
        "active_window": active_window,
        "ui_elements": ui_result,
        "menu_ui_elements": menu_result,
        "after_status": after_status,
        "cleanup": cleanup_result,
        "checks": checks,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-name",
        default=DEFAULT_APP_NAME,
        help=f"Installed app name or query to inspect. Defaults to {DEFAULT_APP_NAME}.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Leave the app open after the smoke. Existing running apps are never quit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(
        app_name=args.app_name,
        cleanup=not args.no_cleanup,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
