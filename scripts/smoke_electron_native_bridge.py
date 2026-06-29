#!/usr/bin/env python3
"""Opt-in smoke-test for the Electron native runtime bridge."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "apps" / "frontend"
ELECTRON_BIN = FRONTEND_DIR / "node_modules" / ".bin" / (
    "electron.cmd" if platform.system() == "Windows" else "electron"
)
ELECTRON_MAIN = FRONTEND_DIR / "dist-electron" / "main.js"
SMOKE_PREFIX = "electron-native-bridge-smoke:"
SMOKE_ENV = "OHA_YACHIYO_ELECTRON_NATIVE_BRIDGE_SMOKE"
SMOKE_APP_ENV = "OHA_YACHIYO_ELECTRON_NATIVE_BRIDGE_SMOKE_APP"
DEFAULT_TIMEOUT_SECONDS = 45


def _run_compile() -> dict[str, Any]:
    result = subprocess.run(
        ["npm", "exec", "tsc", "--", "-p", "tsconfig.electron.json"],
        cwd=FRONTEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _parse_smoke_output(stdout: str) -> dict[str, Any] | None:
    for line in stdout.splitlines():
        if not line.startswith(SMOKE_PREFIX):
            continue
        raw_payload = line[len(SMOKE_PREFIX) :].strip()
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "mode": "electron_native_bridge_smoke",
                "error": f"invalid smoke JSON: {exc}",
                "raw_payload": raw_payload,
            }
        return payload if isinstance(payload, dict) else {
            "ok": False,
            "mode": "electron_native_bridge_smoke",
            "error": "smoke payload was not an object",
            "raw_payload": raw_payload,
        }
    return None


def run_smoke(
    *,
    compile_electron: bool = True,
    focus_app: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not ELECTRON_BIN.exists():
        return {
            "ok": False,
            "mode": "electron_native_bridge_smoke",
            "error": "electron_not_installed",
            "electron_bin": str(ELECTRON_BIN),
            "checks": {"electron_bin_exists": False},
        }
    compile_result: dict[str, Any] | None = None
    if compile_electron:
        compile_result = _run_compile()
        if compile_result.get("ok") is not True:
            return {
                "ok": False,
                "mode": "electron_native_bridge_smoke",
                "error": "electron_main_compile_failed",
                "compile": compile_result,
                "checks": {"electron_compile_ok": False},
            }
    if not ELECTRON_MAIN.exists():
        return {
            "ok": False,
            "mode": "electron_native_bridge_smoke",
            "error": "electron_main_not_built",
            "electron_main": str(ELECTRON_MAIN),
            "compile": compile_result or {},
            "checks": {"electron_main_exists": False},
        }

    env = {
        **os.environ,
        SMOKE_ENV: "1",
        "OHA_YACHIYO_SKIP_BACKEND": "1",
        "ELECTRON_ENABLE_LOGGING": "1",
    }
    clean_focus_app = str(focus_app or "").strip()
    if clean_focus_app:
        env[SMOKE_APP_ENV] = clean_focus_app
    process = subprocess.run(
        [str(ELECTRON_BIN), str(ELECTRON_MAIN)],
        cwd=FRONTEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    payload = _parse_smoke_output(process.stdout)
    if payload is None:
        payload = {
            "ok": False,
            "mode": "electron_native_bridge_smoke",
            "error": "smoke_output_not_found",
        }
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    payload.update(
        {
            "ok": payload.get("ok") is True and process.returncode == 0,
            "electron_returncode": process.returncode,
            "compile": compile_result or {"skipped": not compile_electron},
            "stdout_tail": process.stdout[-4000:],
            "stderr_tail": process.stderr[-4000:],
            "checks": {
                **checks,
                "electron_process_ok": process.returncode == 0,
                "smoke_output_found": _parse_smoke_output(process.stdout) is not None,
            },
        }
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument(
        "--focus-app",
        default="",
        help="Optional app name for a real native focus attempt. Empty means status/auth only.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument("--report-json", type=Path)
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
        compile_electron=not args.no_compile,
        focus_app=args.focus_app,
        timeout_seconds=args.timeout_seconds,
    )
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"electron native bridge smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
