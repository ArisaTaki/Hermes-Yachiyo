"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_release_artifacts import Finding, verify_release_artifacts

DEFAULT_ARTIFACT_PATHS: tuple[Path, ...] = (
    Path("dist/backend"),
    Path("dist/electron"),
    Path("release"),
)
MANUAL_RELEASE_CANDIDATE_CHECKS: tuple[str, ...] = (
    "Mount the DMG and launch Oha-Yachiyo.app once with the documented Gatekeeper first-launch flow.",
    "Confirm the packaged app starts its local bridge and does not connect to a development backend.",
    "Grant Screen Recording permission to Oha-Yachiyo.app and verify the local screenshot/proactive probe path.",
    "If real provider credentials are available, run the opt-in streaming/tool-call provider smoke in release workflow.",
)


def existing_artifact_paths(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in DEFAULT_ARTIFACT_PATHS if (root / path).exists())


def release_ui_smoke_scripts(root: Path) -> tuple[Path, ...]:
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return ()
    return tuple(sorted(path.relative_to(root) for path in scripts_dir.glob("smoke_*_ui.mjs") if path.is_file()))


def _print_findings(title: str, findings: Sequence[Finding]) -> None:
    if not findings:
        print(f"{title}: passed")
        return
    print(f"{title}: failed")
    for finding in findings:
        print(f"- {finding.format()}")


def _finding_report(findings: Sequence[Finding]) -> list[dict[str, str]]:
    return [{"path": str(finding.path), "message": finding.message} for finding in findings]


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_release_candidate(
    *,
    root: Path = PROJECT_ROOT,
    artifact_paths: Sequence[Path] | None = None,
    require_artifacts: bool = False,
    run_ui_smoke: bool = False,
    smoke_scripts: Sequence[Path] | None = None,
    report_json: Path | None = None,
) -> int:
    root = Path(root)
    failed = False
    report: dict[str, Any] = {
        "ok": False,
        "source_release_guards": {"status": "pending", "findings": []},
        "built_artifact_guards": {
            "status": "pending",
            "artifact_paths": [],
            "findings": [],
        },
        "electron_ui_smoke": {
            "status": "pending",
            "scripts": [],
            "run_requested": run_ui_smoke,
        },
        "manual_release_candidate_check_status": "manual_required",
        "manual_release_candidate_checks": list(MANUAL_RELEASE_CANDIDATE_CHECKS),
    }

    source_findings = verify_release_artifacts(root=root)
    _print_findings("source release guards", source_findings)
    failed = failed or bool(source_findings)
    report["source_release_guards"] = {
        "status": "failed" if source_findings else "passed",
        "findings": _finding_report(source_findings),
    }

    selected_artifacts = tuple(artifact_paths) if artifact_paths is not None else existing_artifact_paths(root)
    if selected_artifacts:
        artifact_findings = verify_release_artifacts(
            root=root,
            paths=selected_artifacts,
            allow_binary_targets=True,
            check_packaged_app_bundle=True,
        )
        _print_findings("built artifact guards", artifact_findings)
        failed = failed or bool(artifact_findings)
        report["built_artifact_guards"] = {
            "status": "failed" if artifact_findings else "passed",
            "artifact_paths": [str(path) for path in selected_artifacts],
            "findings": _finding_report(artifact_findings),
        }
    elif require_artifacts:
        print(
            "built artifact guards: failed\n"
            "- release candidate artifacts not found under dist/backend, dist/electron, or release"
        )
        failed = True
        report["built_artifact_guards"] = {
            "status": "failed",
            "artifact_paths": [],
            "findings": [
                {
                    "path": str(root),
                    "message": "release candidate artifacts not found under dist/backend, dist/electron, or release",
                }
            ],
        }
    else:
        print("built artifact guards: skipped; pass --require-artifacts for a release-candidate gate")
        report["built_artifact_guards"] = {
            "status": "skipped",
            "artifact_paths": [],
            "findings": [],
        }

    selected_smoke_scripts = tuple(smoke_scripts) if smoke_scripts is not None else release_ui_smoke_scripts(root)
    smoke_results: list[dict[str, object]] = []
    if run_ui_smoke:
        if not selected_smoke_scripts:
            print("Electron UI smoke: failed\n- no scripts/smoke_*_ui.mjs scripts found")
            failed = True
        for script in selected_smoke_scripts:
            print(f"Electron UI smoke: node {script}")
            result = subprocess.run(["node", str(script)], cwd=root, check=False)
            smoke_results.append({"script": str(script), "exit_code": result.returncode})
            if result.returncode != 0:
                print(f"- {script} failed with exit code {result.returncode}")
                failed = True
        smoke_failed = (not selected_smoke_scripts) or any(
            item["exit_code"] for item in smoke_results
        )
        report["electron_ui_smoke"] = {
            "status": "failed" if smoke_failed else "passed",
            "scripts": smoke_results,
            "run_requested": run_ui_smoke,
        }
    else:
        print("Electron UI smoke: skipped; pass --run-ui-smoke after installing frontend dependencies")
        report["electron_ui_smoke"] = {
            "status": "skipped",
            "scripts": [str(script) for script in selected_smoke_scripts],
            "run_requested": run_ui_smoke,
        }

    print("manual release-candidate checks:")
    for check in MANUAL_RELEASE_CANDIDATE_CHECKS:
        print(f"- {check}")

    report["ok"] = not failed
    if report_json is not None:
        _write_report(root / report_json, report)
        print(f"release candidate report: {report_json}")

    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local Oha-Yachiyo release-candidate verification gates."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional built artifact paths. Defaults to existing dist/backend, dist/electron, and release.",
    )
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail when no built release artifacts are present.",
    )
    parser.add_argument(
        "--run-ui-smoke",
        action="store_true",
        help="Run every scripts/smoke_*_ui.mjs Electron UI smoke.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write a machine-readable release-candidate verification report.",
    )
    args = parser.parse_args(argv)
    return verify_release_candidate(
        artifact_paths=args.paths or None,
        require_artifacts=args.require_artifacts,
        run_ui_smoke=args.run_ui_smoke,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
