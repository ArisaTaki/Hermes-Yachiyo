"""Run Electron UI smoke scripts and optionally write a release report."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def electron_ui_smoke_scripts(root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return ()
    return tuple(
        sorted(
            path.relative_to(root)
            for path in scripts_dir.glob("smoke_*_ui.mjs")
            if path.is_file()
        )
    )


def _resolve_project_path(root: Path, path: Path, label: str) -> Path:
    root_path = root.resolve(strict=False)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise ValueError(f"{label} path must stay inside project root: {path}")
    return resolved


def _write_report(root: Path, report_json: Path, report: dict[str, Any]) -> None:
    report_path = _resolve_project_path(root, report_json, "Electron UI smoke report")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_electron_ui_smokes(
    *,
    root: Path = PROJECT_ROOT,
    smoke_scripts: Sequence[Path] | None = None,
    report_json: Path | None = None,
) -> int:
    root = Path(root)
    selected_scripts = (
        tuple(smoke_scripts)
        if smoke_scripts is not None
        else electron_ui_smoke_scripts(root)
    )
    failed = False
    results: list[dict[str, object]] = []

    if not selected_scripts:
        print("Electron UI smoke: failed\n- no scripts/smoke_*_ui.mjs scripts found")
        failed = True

    for script in selected_scripts:
        try:
            script_path = _resolve_project_path(root, script, "Electron UI smoke script")
        except ValueError as exc:
            print(f"Electron UI smoke: failed\n- {exc}")
            results.append({"script": str(script), "exit_code": None, "error": str(exc)})
            failed = True
            continue

        relative_script = script_path.relative_to(root.resolve(strict=False))
        print(f"Electron UI smoke: node {relative_script}")
        try:
            result = subprocess.run(["node", str(relative_script)], cwd=root, check=False)
        except OSError as exc:
            print(f"- {relative_script} could not start: {exc}")
            results.append({"script": str(relative_script), "exit_code": None, "error": str(exc)})
            failed = True
            continue

        results.append({"script": str(relative_script), "exit_code": result.returncode})
        if result.returncode != 0:
            print(f"- {relative_script} failed with exit code {result.returncode}")
            failed = True

    report = {
        "ok": not failed,
        "script_count": len(selected_scripts),
        "scripts": results,
    }
    if report_json is not None:
        _write_report(root, report_json, report)
        print(f"Electron UI smoke report: {report_json}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Oha-Yachiyo Electron UI smoke scripts.")
    parser.add_argument(
        "scripts",
        nargs="*",
        type=Path,
        help="Optional smoke scripts. Defaults to scripts/smoke_*_ui.mjs.",
    )
    parser.add_argument("--report-json", type=Path, help="Optional project-local JSON report path.")
    args = parser.parse_args(argv)
    return run_electron_ui_smokes(
        smoke_scripts=tuple(args.scripts) if args.scripts else None,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
