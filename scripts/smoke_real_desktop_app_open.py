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
DESKTOP_APP_OPEN_TOOL_CHAIN = [
    "desktop.list_apps",
    "desktop.open_app",
    "desktop.verify",
    "app.status",
]
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

    def desktop_running_apps(self) -> dict[str, Any]:
        return desktop_tools.running_apps()

    def desktop_windows(self, app_name: str = "") -> dict[str, Any]:
        return desktop_tools.windows(app_name)

    def desktop_ui_elements(
        self,
        *,
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        return desktop_tools.ui_elements(
            role_filter=role_filter,
            limit=limit,
            app_name=app_name,
        )

    def app_status(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_status(app_name)

    def app_open(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_open(app_name)

    def app_focus(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_focus(app_name)

    def app_show(self, app_name: str) -> dict[str, Any]:
        return desktop_tools.app_show(app_name)


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


def _app_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    return [dict(app) for app in apps if isinstance(app, dict)]


def _tool_data(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _tool_checks(result: dict[str, Any] | None) -> dict[str, Any]:
    data = _tool_data(result)
    checks = data.get("checks")
    return checks if isinstance(checks, dict) else {}


def _foreground_ready(result: dict[str, Any] | None) -> bool:
    data = _tool_data(result)
    checks = _tool_checks(result)
    return (
        data.get("ready_for_foreground_action") is True
        or checks.get("ready_for_foreground_action") is True
    )


def _foreground_readiness_result(result: dict[str, Any] | None) -> dict[str, Any]:
    data = _tool_data(result)
    checks = _tool_checks(result)
    readiness = {
        "ok": bool(isinstance(result, dict) and result.get("ok") is True),
        "ready": _foreground_ready(result),
        "summary": str((result or {}).get("summary") or "").strip()
        if isinstance(result, dict)
        else "",
        "focus_verified": data.get("focus_verified") is True
        or checks.get("focus_verified") is True,
        "visibility_limited": data.get("visibility_limited") is True,
        "visibility_status": str(data.get("visibility_status") or "").strip(),
        "window_count": int(data.get("window_count") or 0),
        "ui_element_count": int(data.get("ui_element_count") or 0),
        "control_like_count": int(data.get("control_like_count") or 0),
        "inspection_level": str(data.get("inspection_level") or "").strip(),
        "recommended_tools": _string_list(
            (result or {}).get("recommended_tools") if isinstance(result, dict) else None
        )
        or _string_list(data.get("recommended_tools")),
        "recovery_actions": _dict_list(
            (result or {}).get("recovery_actions") if isinstance(result, dict) else None
        )
        or _dict_list(data.get("recovery_actions")),
    }
    blocking_evidence = _merge_blocking_evidence(result or {})
    for key in (
        "error",
        "blocking_condition",
        "blocking_conditions",
        "permission_targets",
        "missing_permissions",
        "recovery_hints",
    ):
        if key in blocking_evidence:
            readiness[key] = blocking_evidence[key]
    return readiness


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
        nested_results = [result]
        data = _tool_data(result)
        for key in ("focus_result", "open_result", "windows", "ui_elements"):
            nested = data.get(key)
            if isinstance(nested, dict):
                nested_results.append(nested)
        evidence = _merge_blocking_evidence_from_flat_results(nested_results)
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


def _merge_blocking_evidence_from_flat_results(
    results: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    list_keys = (
        "blocking_conditions",
        "permission_targets",
        "missing_permissions",
        "recovery_hints",
        "recommended_tools",
    )
    for result in results:
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


def _bool_checks(checks: dict[str, Any]) -> dict[str, bool]:
    return {str(key): value for key, value in checks.items() if isinstance(value, bool)}


def _desktop_execution_case(
    case_id: str,
    *,
    app_name: str,
    tool_chain: Sequence[str],
    checks: dict[str, Any],
    stage: str | None = None,
) -> dict[str, Any]:
    bool_checks = _bool_checks(checks)
    case: dict[str, Any] = {
        "id": case_id,
        "app_name": app_name,
        "tool_chain": list(tool_chain),
        "passed": bool(bool_checks) and all(bool_checks.values()),
        "checks": bool_checks,
    }
    if stage:
        case["stage"] = stage
    return case


def _planner_alignment(
    *,
    intent_category: str,
    app_name: str,
    capabilities: Sequence[str],
    tool_chain: Sequence[str],
    mutates_desktop: bool,
    approval_required: bool = False,
) -> dict[str, Any]:
    return {
        "intent_category": intent_category,
        "target_app": app_name,
        "execution_pattern": ["discover", "execute", "verify"],
        "capabilities": list(capabilities),
        "tool_plan": [{"tool": tool_name} for tool_name in tool_chain],
        "approval_policy": {
            "mutates_desktop": mutates_desktop,
            "approval_required": approval_required,
        },
    }


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
    capability_query: str = "",
    require_foreground_ready: bool = False,
    recover_foreground: bool = True,
    cleanup: bool = True,
) -> dict[str, Any]:
    current_platform = platform.system()
    clean_app_name = str(app_name or "").strip() or DEFAULT_APP_NAME
    clean_capability_query = str(capability_query or "").strip()
    discovery_query = clean_capability_query or clean_app_name
    selection_source = "capability_query" if clean_capability_query else "app_name_query"
    if current_platform != "Darwin":
        return {
            "ok": True,
            "mode": "real_desktop_app_open_smoke",
            "skipped": True,
            "platform": current_platform,
            "app_name": clean_app_name,
            **({"capability_query": clean_capability_query} if clean_capability_query else {}),
            "reason": "real desktop app open smoke only runs on macOS",
        }

    broker = _RuntimeDesktopBroker()
    discovery = _runtime_tool_call(
        broker,
        "desktop.list_apps",
        {"query": discovery_query, "limit": 10},
    )
    discovered_candidates = _app_candidates(discovery)
    discovered_names = _app_names(discovery)
    if clean_capability_query:
        selected_candidate = discovered_candidates[0] if discovered_candidates else {}
        discovered_app_name = str(selected_candidate.get("name") or clean_app_name).strip()
        if not discovered_candidates:
            checks = {
                "discovered_app": discovery.get("ok") is True and bool(discovered_names),
                "selected_discovered_app": False,
                "capability_match_recorded": False,
            }
            return {
                "ok": False,
                "mode": "real_desktop_app_open_smoke",
                "skipped": False,
                "platform": current_platform,
                "tool_chain": ["desktop.list_apps"],
                "case_count": 1,
                "cases": [
                    _desktop_execution_case(
                        "open_discovered_app",
                        app_name=clean_app_name,
                        tool_chain=["desktop.list_apps"],
                        checks=checks,
                        stage="app_discovery",
                    )
                ],
                "planner_alignment": _planner_alignment(
                    intent_category="desktop_app_open",
                    app_name=clean_app_name,
                    capabilities=["desktop.app_discovery"],
                    tool_chain=["desktop.list_apps"],
                    mutates_desktop=False,
                ),
                "app_name": clean_app_name,
                "discovery_query": discovery_query,
                "selection_source": selection_source,
                "capability_query": clean_capability_query,
                "selected_candidate": selected_candidate,
                "matched_capability": "",
                "discovered_app_name": "",
                "opened_app_name": "",
                "error": str(discovery.get("error") or "capability_app_not_found"),
                "discovery": {
                    "result": discovery,
                    "names": discovered_names,
                },
                "checks": checks,
            }
    else:
        selected_name = next(
            (name for name in discovered_names if name.casefold() == clean_app_name.casefold()),
            discovered_names[0] if discovered_names else clean_app_name,
        )
        selected_candidate = next(
            (
                candidate
                for candidate in discovered_candidates
                if str(candidate.get("name") or "").strip() == selected_name
            ),
            discovered_candidates[0] if discovered_candidates else {},
        )
        discovered_app_name = selected_name
    matched_capability = str(selected_candidate.get("matched_capability") or "").strip()
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

    foreground_inspect_result: dict[str, Any] | None = None
    foreground_recovery_result: dict[str, Any] | None = None
    foreground_reinspect_result: dict[str, Any] | None = None
    if require_foreground_ready and open_result.get("ok") is True:
        foreground_inspect_result = _runtime_tool_call(
            broker,
            "desktop.inspect_app",
            {
                "app_name": opened_app_name,
                "open_if_needed": False,
                "focus": True,
                "limit": 80,
            },
        )
        if recover_foreground and not _foreground_ready(foreground_inspect_result):
            foreground_recovery_result = _runtime_tool_call(
                broker,
                "app.show",
                {"app_name": opened_app_name},
            )
            if foreground_recovery_result.get("ok") is True:
                foreground_reinspect_result = _runtime_tool_call(
                    broker,
                    "desktop.inspect_app",
                    {
                        "app_name": opened_app_name,
                        "open_if_needed": False,
                        "focus": True,
                        "limit": 80,
                    },
                )
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
    foreground_final_result = (
        foreground_reinspect_result
        or foreground_inspect_result
        or verify_result
    )
    foreground_readiness = {
        "required": require_foreground_ready,
        "recover_foreground": recover_foreground,
        "verify": _foreground_readiness_result(verify_result),
        "final": _foreground_readiness_result(foreground_final_result),
    }
    if foreground_inspect_result is not None:
        foreground_readiness["inspect"] = _foreground_readiness_result(
            foreground_inspect_result
        )
    if foreground_recovery_result is not None:
        foreground_readiness["recovery"] = {
            "tool": "app.show",
            "ok": foreground_recovery_result.get("ok") is True,
            "summary": str(foreground_recovery_result.get("summary") or "").strip(),
        }
    if foreground_reinspect_result is not None:
        foreground_readiness["reinspect"] = _foreground_readiness_result(
            foreground_reinspect_result
        )
    tool_chain = ["desktop.list_apps", "desktop.open_app", "desktop.verify"]
    if foreground_inspect_result is not None:
        tool_chain.append("desktop.inspect_app")
    if foreground_recovery_result is not None:
        tool_chain.append("app.show")
    if foreground_reinspect_result is not None:
        tool_chain.append("desktop.inspect_app")
    tool_chain.append("app.status")
    cleanup_result = _cleanup_evidence(
        app_name=opened_app_name,
        cleanup=cleanup,
        before_running=before_running,
        after_running=after_running,
    )
    checks = {
        "discovered_app": discovery.get("ok") is True and bool(discovered_names),
        "selected_discovered_app": bool(discovered_app_name and discovered_app_name in discovered_names),
        "capability_match_recorded": bool(matched_capability) if clean_capability_query else True,
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
        "foreground_ready_when_required": (
            not require_foreground_ready
            or foreground_readiness["final"].get("ready") is True
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
    blocking_evidence = _merge_blocking_evidence(
        open_result,
        verify_result,
        foreground_final_result,
        after_status,
    )
    case = _desktop_execution_case(
        "open_discovered_app",
        app_name=opened_app_name,
        tool_chain=tool_chain,
        checks=checks,
    )
    return {
        "ok": all(checks.values()),
        "mode": "real_desktop_app_open_smoke",
        "skipped": False,
        "platform": current_platform,
        "tool_chain": tool_chain,
        "case_count": 1,
        "cases": [case],
        "planner_alignment": _planner_alignment(
            intent_category="desktop_app_open",
            app_name=opened_app_name,
            capabilities=[
                "desktop.app_discovery",
                "desktop.app_launch",
                "desktop.app_verification",
            ],
            tool_chain=tool_chain,
            mutates_desktop=True,
        ),
        "app_name": clean_app_name,
        "discovery_query": discovery_query,
        "selection_source": selection_source,
        **({"capability_query": clean_capability_query} if clean_capability_query else {}),
        "selected_candidate": selected_candidate,
        "matched_capability": matched_capability,
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
        "foreground_inspect_result": foreground_inspect_result,
        "foreground_recovery_result": foreground_recovery_result,
        "foreground_reinspect_result": foreground_reinspect_result,
        "foreground_readiness": foreground_readiness,
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
        "--capability-query",
        default="",
        help=(
            "Optional capability query, such as browser or file manager. "
            "When set, the smoke opens the best desktop.list_apps candidate."
        ),
    )
    parser.add_argument(
        "--require-foreground-ready",
        action="store_true",
        help=(
            "Fail unless desktop.inspect_app proves the opened app is ready for "
            "foreground actions. Attempts app.show recovery once when needed."
        ),
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
        capability_query=args.capability_query,
        require_foreground_ready=args.require_foreground_ready,
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
