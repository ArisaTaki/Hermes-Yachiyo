#!/usr/bin/env python3
"""Smoke-test real macOS desktop app discovery without opening apps."""

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

CORE_APP_QUERIES: tuple[dict[str, Any], ...] = (
    {"id": "safari", "query": "Safari", "expected_names": ["Safari"]},
    {
        "id": "system_settings",
        "query": "System Settings",
        "expected_names": ["System Settings", "System Preferences"],
    },
    {"id": "textedit", "query": "TextEdit", "expected_names": ["TextEdit"]},
)


def _app_names(result: dict[str, Any]) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    return [
        str(app.get("name") or "").strip()
        for app in apps
        if isinstance(app, dict) and str(app.get("name") or "").strip()
    ]


def _case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    query = str(case["query"])
    expected_names = [str(name) for name in case["expected_names"]]
    result = desktop_tools.list_apps(query=query, limit=10)
    names = _app_names(result)
    checks = {
        "list_apps_ok": result.get("ok") is True,
        "query_preserved": (
            isinstance(result.get("data"), dict)
            and str(result["data"].get("query") or "") == query
        ),
        "found_expected_app": any(name in names for name in expected_names),
        "did_not_open_app": result.get("action") == "desktop.list_apps"
        and result.get("permission_error") is False,
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "query": query,
        "expected_names": expected_names,
        "names": names,
        "summary": str(result.get("summary") or ""),
        "checks": checks,
    }


def _catalog_evidence() -> dict[str, Any]:
    result = desktop_tools.list_apps(query="", limit=20)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    names = _app_names(result)
    checks = {
        "list_apps_ok": result.get("ok") is True,
        "found_apps": int(data.get("total_count") or 0) > 0 and bool(names),
        "did_not_open_app": result.get("action") == "desktop.list_apps"
        and result.get("permission_error") is False,
    }
    return {
        "ok": all(checks.values()),
        "names": names,
        "total_count": int(data.get("total_count") or 0),
        "summary": str(result.get("summary") or ""),
        "checks": checks,
    }


def _permission_preflight_evidence() -> dict[str, Any]:
    try:
        result = desktop_tools.permission_preflight()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "ok": result.get("ok") is True,
        "ready": bool(data.get("ready")),
        "permission_targets": list(data.get("permission_targets") or []),
        "affected_tools": list(data.get("affected_tools") or []),
        "diagnostic_route": str(data.get("diagnostic_route") or ""),
        "summary": str(result.get("summary") or ""),
    }


def run_smoke() -> dict[str, Any]:
    current_platform = platform.system()
    if current_platform != "Darwin":
        return {
            "ok": True,
            "mode": "real_desktop_discovery_smoke",
            "skipped": True,
            "platform": current_platform,
            "reason": "real desktop discovery smoke only runs on macOS",
            "cases": [],
        }
    catalog = _catalog_evidence()
    cases = [_case_evidence(case) for case in CORE_APP_QUERIES]
    permission_preflight = _permission_preflight_evidence()
    return {
        "ok": catalog["ok"] and all(case["ok"] for case in cases),
        "mode": "real_desktop_discovery_smoke",
        "skipped": False,
        "platform": current_platform,
        "catalog": catalog,
        "case_count": len(cases),
        "cases": cases,
        "permission_preflight": permission_preflight,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional JSON evidence report path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke()
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(
            f"real desktop discovery smoke report: {args.report_json}",
            file=sys.stderr,
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
