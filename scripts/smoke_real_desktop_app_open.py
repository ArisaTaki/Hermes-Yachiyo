#!/usr/bin/env python3
"""Opt-in smoke-test for real macOS desktop app discovery and app.open."""

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

DEFAULT_APP_NAME = "Calculator"


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
    final_status = desktop_tools.app_status(app_name)
    final_running = _status_running(final_status)
    return {
        "requested": True,
        "attempted": True,
        "ok": quit_result.get("ok") is True and final_running is False,
        "result": quit_result,
        "final_status": final_status,
        "final_running": final_running,
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
    after_status = desktop_tools.app_status(opened_app_name)
    after_running = _status_running(after_status)
    open_data = open_result.get("data") if isinstance(open_result.get("data"), dict) else {}
    open_verified = open_data.get("launch_verified")
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
        "open_verified_running": open_verified is True or after_running is True,
        "after_status_ok": after_status.get("ok") is True,
        "after_status_running": after_running is True,
        "cleanup_ok": cleanup_result.get("ok") is True,
        "did_not_quit_existing_app": not (
            cleanup
            and before_running is True
            and cleanup_result.get("attempted") is True
        ),
    }
    return {
        "ok": all(checks.values()),
        "mode": "real_desktop_app_open_smoke",
        "skipped": False,
        "platform": current_platform,
        "app_name": clean_app_name,
        "discovered_app_name": discovered_app_name,
        "opened_app_name": opened_app_name,
        "discovery": {
            "result": discovery,
            "names": discovered_names,
        },
        "before_status": before_status,
        "open_result": open_result,
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
