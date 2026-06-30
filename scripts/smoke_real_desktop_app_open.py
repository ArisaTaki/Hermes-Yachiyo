#!/usr/bin/env python3
"""Opt-in smoke-test for real macOS desktop app discovery and desktop.open_app."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools import desktop as desktop_tools
from apps.shell.agent.tools.registry import dispatch_tool_call

DEFAULT_APP_NAME = "Calculator"
_CLEANUP_STATUS_MAX_POLLS = 12
_CLEANUP_STATUS_POLL_INTERVAL_SECONDS = 0.25


class _RuntimeDesktopBroker:
    """Small broker surface for exercising the production tool dispatch registry."""

    def desktop_list_apps(self, query: str = "", limit: Any = 200) -> dict[str, Any]:
        return desktop_tools.list_apps(query=query, limit=limit)

    def desktop_inspect_app(
        self,
        app_name: str,
        *,
        open_if_needed: Any = True,
        focus: Any = True,
        role_filter: str = "",
        limit: Any = 80,
    ) -> dict[str, Any]:
        return desktop_tools.inspect_app(
            app_name,
            open_if_needed=open_if_needed,
            focus=focus,
            role_filter=role_filter,
            limit=limit,
        )

    def desktop_active_window(self) -> dict[str, Any]:
        return desktop_tools.active_window()

    def app_status(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_status(app_name)

    def app_open(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_open(app_name)


def _runtime_tool_call(
    broker: _RuntimeDesktopBroker,
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return dispatch_tool_call(broker, tool_name, payload)


def _app_names(result: dict[str, Any]) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    return [
        str(app.get("name") or "").strip()
        for app in apps
        if isinstance(app, dict) and str(app.get("name") or "").strip()
    ]


def _status_running(result: dict[str, Any]) -> bool | None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    running = data.get("running")
    return running if isinstance(running, bool) else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values: list[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        return []
    values: list[str] = []
    for item in raw_values:
        clean = str(item or "").strip()
        if clean and clean not in values:
            values.append(clean)
    return values


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


def _blocking_evidence_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project a tool result's blocker fields into smoke top-level evidence."""

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    conditions: list[str] = []
    for source in (result, data):
        _append_unique(conditions, _string_list(source.get("blocking_conditions")))
        _append_unique(conditions, _string_list(source.get("blocking_condition")))
    error = str(result.get("error") or "").strip()
    if error in {"desktop_session_locked", "foreground_focus_unavailable"}:
        _append_unique(conditions, [error])

    evidence: dict[str, Any] = {}
    if error and (conditions or error == "app_focus_not_verified"):
        evidence["error"] = error
    if conditions:
        evidence["blocking_condition"] = conditions[0]
        evidence["blocking_conditions"] = conditions

    for key in ("permission_targets", "missing_permissions", "recovery_hints", "recommended_tools"):
        values: list[str] = []
        for source in (result, data):
            _append_unique(values, _string_list(source.get(key)))
        if values:
            evidence[key] = values

    recovery_actions: list[dict[str, Any]] = []
    seen_actions: set[str] = set()
    for source in (result, data):
        for action in _dict_list(source.get("recovery_actions")):
            action_key = json.dumps(action, sort_keys=True, ensure_ascii=False)
            if action_key in seen_actions:
                continue
            seen_actions.add(action_key)
            recovery_actions.append(action)
    if recovery_actions:
        evidence["recovery_actions"] = recovery_actions
    return evidence


def _merge_blocking_evidence(*results: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    list_keys = (
        "blocking_conditions",
        "permission_targets",
        "missing_permissions",
        "recovery_hints",
        "recommended_tools",
    )
    for result in results:
        if not isinstance(result, dict):
            continue
        evidence = _blocking_evidence_from_result(result)
        if evidence.get("error") and not merged.get("error"):
            merged["error"] = evidence["error"]
        if evidence.get("blocking_condition") and not merged.get("blocking_condition"):
            merged["blocking_condition"] = evidence["blocking_condition"]
        for key in list_keys:
            values = _string_list(merged.get(key))
            _append_unique(values, _string_list(evidence.get(key)))
            if values:
                merged[key] = values
        actions = _dict_list(merged.get("recovery_actions"))
        seen_actions = {
            json.dumps(action, sort_keys=True, ensure_ascii=False)
            for action in actions
        }
        for action in _dict_list(evidence.get("recovery_actions")):
            action_key = json.dumps(action, sort_keys=True, ensure_ascii=False)
            if action_key in seen_actions:
                continue
            seen_actions.add(action_key)
            actions.append(action)
        if actions:
            merged["recovery_actions"] = actions
    return merged


def _resolved_open_app_name(requested_app_name: str, result: dict[str, Any]) -> str:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return str(data.get("app_name") or data.get("resolved_app_name") or requested_app_name).strip()


def _cleanup_evidence(
    *,
    app_name: str,
    cleanup: bool,
    before_running: bool | None,
    after_running: bool | None,
) -> dict[str, Any]:
    if not cleanup:
        return {
            "requested": False,
            "attempted": False,
            "ok": True,
            "reason": "cleanup not requested",
        }
    if before_running is True:
        return {
            "requested": True,
            "attempted": False,
            "ok": True,
            "reason": "app was already running before smoke",
        }
    if before_running is None:
        return {
            "requested": True,
            "attempted": False,
            "ok": True,
            "reason": "before status was unknown; refusing to quit a possibly user-opened app",
        }
    if after_running is not True:
        return {
            "requested": True,
            "attempted": False,
            "ok": True,
            "reason": "app was not verified running after open",
        }
    quit_result = desktop_tools.app_quit(app_name)
    final_status: dict[str, Any] = {}
    final_running: bool | None = None
    status_polls: list[dict[str, Any]] = []
    for attempt in range(1, _CLEANUP_STATUS_MAX_POLLS + 1):
        final_status = desktop_tools.app_status(app_name)
        final_running = _status_running(final_status)
        status_polls.append({"attempt": attempt, "running": final_running})
        if final_running is False:
            break
        if attempt < _CLEANUP_STATUS_MAX_POLLS:
            time.sleep(_CLEANUP_STATUS_POLL_INTERVAL_SECONDS)
    return {
        "requested": True,
        "attempted": True,
        "ok": quit_result.get("ok") is True and final_running is False,
        "result": quit_result,
        "final_status": final_status,
        "final_running": final_running,
        "status_polls": status_polls,
    }


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
            "mode": "real_desktop_app_open_smoke",
            "skipped": True,
            "platform": current_platform,
            "app_name": clean_app_name,
            "reason": "real desktop app open smoke only runs on macOS",
        }

    broker = _RuntimeDesktopBroker()
    discovery = _runtime_tool_call(
        broker,
        "desktop.list_apps",
        {"query": clean_app_name, "limit": 10},
    )
    discovered_names = _app_names(discovery)
    discovered_app_name = next(
        (name for name in discovered_names if name.casefold() == clean_app_name.casefold()),
        discovered_names[0] if discovered_names else clean_app_name,
    )
    before_status = _runtime_tool_call(
        broker,
        "app.status",
        {"app_name": discovered_app_name},
    )
    before_running = _status_running(before_status)
    open_result = _runtime_tool_call(
        broker,
        "desktop.open_app",
        {"app_name": discovered_app_name},
    )
    opened_app_name = _resolved_open_app_name(discovered_app_name, open_result)
    if open_result.get("ok") is True:
        verify_result = _runtime_tool_call(
            broker,
            "desktop.verify",
            {"app_name": opened_app_name, "limit": 40},
        )
    else:
        verify_result = {
            "ok": False,
            "action": "desktop.verify",
            "skipped": True,
            "reason": "desktop.open_app failed",
            "data": {"app_name": opened_app_name},
        }
    after_status = _runtime_tool_call(
        broker,
        "app.status",
        {"app_name": opened_app_name},
    )
    after_running = _status_running(after_status)
    open_data = open_result.get("data") if isinstance(open_result.get("data"), dict) else {}
    open_verified = open_data.get("launch_verified")
    verify_data = verify_result.get("data") if isinstance(verify_result.get("data"), dict) else {}
    verify_checks = (
        verify_data.get("checks") if isinstance(verify_data.get("checks"), dict) else {}
    )
    cleanup_result = _cleanup_evidence(
        app_name=opened_app_name,
        cleanup=cleanup,
        before_running=before_running,
        after_running=after_running,
    )
    checks = {
        "discovered_app": discovery.get("ok") is True and bool(discovered_names),
        "before_status_ok": before_status.get("ok") is True,
        "open_ok": open_result.get("ok") is True,
        "open_alias_used": open_result.get("action") == "desktop.open_app",
        "open_verified_running": open_verified is True or after_running is True,
        "verify_ok": verify_result.get("ok") is True,
        "verify_alias_used": verify_result.get("action") == "desktop.verify",
        "verify_status_running": (
            verify_checks.get("status_running") is True
            or verify_data.get("running") is True
            or after_running is True
        ),
        "after_status_ok": after_status.get("ok") is True,
        "after_status_running": after_running is True,
        "cleanup_ok": cleanup_result.get("ok") is True,
        "did_not_quit_existing_app": not (
            cleanup
            and before_running is True
            and cleanup_result.get("attempted") is True
        ),
    }
    blocking_evidence = _merge_blocking_evidence(open_result, verify_result, after_status)
    return {
        "ok": all(checks.values()),
        "mode": "real_desktop_app_open_smoke",
        "skipped": False,
        "platform": current_platform,
        "tool_chain": ["desktop.list_apps", "desktop.open_app", "desktop.verify", "app.status"],
        "app_name": clean_app_name,
        "discovered_app_name": discovered_app_name,
        "opened_app_name": opened_app_name,
        **blocking_evidence,
        "discovery": {
            "result": discovery,
            "names": discovered_names,
        },
        "before_status": before_status,
        "open_result": open_result,
        "verify_result": verify_result,
        "after_status": after_status,
        "cleanup": cleanup_result,
        "checks": checks,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-name",
        default=DEFAULT_APP_NAME,
        help=f"Installed app name or query to open. Defaults to {DEFAULT_APP_NAME}.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Leave the app open after the smoke. Existing running apps are never quit.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    return parser


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(
        app_name=args.app_name,
        cleanup=not args.no_cleanup,
    )
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(
            f"real desktop app open smoke report: {args.report_json}",
            file=sys.stderr,
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
