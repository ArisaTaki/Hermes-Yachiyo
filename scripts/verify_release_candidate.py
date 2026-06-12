"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_release_artifacts import Finding, verify_release_artifacts
from packages.security import redact_api_error_text

DEFAULT_ARTIFACT_PATHS: tuple[Path, ...] = (
    Path("dist/backend"),
    Path("dist/electron"),
    Path("release"),
)
PACKAGED_APP_NAME = "Oha-Yachiyo.app"
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


def _resolve_report_path(root: Path, report_json: Path) -> Path:
    root_path = root.resolve(strict=False)
    report_path = report_json if report_json.is_absolute() else root / report_json
    resolved = report_path.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError:
        raise ValueError(
            f"release candidate report path must stay inside project root: {report_json}"
        )
    return resolved


def _validate_artifact_paths(root: Path, artifact_paths: Sequence[Path]) -> tuple[Path, ...]:
    root_path = root.resolve(strict=False)
    for artifact_path in artifact_paths:
        candidate = artifact_path if artifact_path.is_absolute() else root / artifact_path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_path)
        except ValueError:
            raise ValueError(
                f"release candidate artifact path must stay inside project root: {artifact_path}"
            )
    return tuple(artifact_paths)


def _validate_smoke_script_paths(root: Path, smoke_scripts: Sequence[Path]) -> tuple[Path, ...]:
    root_path = root.resolve(strict=False)
    for smoke_script in smoke_scripts:
        candidate = smoke_script if smoke_script.is_absolute() else root / smoke_script
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root_path)
        except ValueError:
            raise ValueError(
                f"release candidate smoke script path must stay inside project root: {smoke_script}"
            )
    return tuple(smoke_scripts)


def _absolute_artifact_path(root: Path, artifact_path: Path) -> Path:
    return artifact_path if artifact_path.is_absolute() else root / artifact_path


def release_candidate_dmg_paths(root: Path, artifact_paths: Sequence[Path]) -> tuple[Path, ...]:
    dmg_paths: list[Path] = []
    seen: set[Path] = set()
    for artifact_path in artifact_paths:
        candidate = _absolute_artifact_path(root, artifact_path)
        if candidate.is_file() and candidate.suffix.lower() == ".dmg":
            resolved = candidate.resolve(strict=False)
            if resolved not in seen:
                dmg_paths.append(artifact_path)
                seen.add(resolved)
        elif candidate.is_dir():
            for dmg in sorted(candidate.rglob("*.dmg")):
                resolved = dmg.resolve(strict=False)
                if resolved in seen:
                    continue
                try:
                    dmg_paths.append(dmg.relative_to(root))
                except ValueError:
                    dmg_paths.append(dmg)
                seen.add(resolved)
    return tuple(dmg_paths)


def verify_dmg_mount_artifacts(root: Path, dmg_paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG mount check requested but no .dmg artifacts were found"))
        return findings
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG mount check requires macOS hdiutil"))
        return findings
    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-dmg-"))
        attached = False
        try:
            attach = subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(absolute_dmg),
                    "-nobrowse",
                    "-readonly",
                    "-mountpoint",
                    str(mount_dir),
                    "-quiet",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if attach.returncode != 0:
                detail = redact_api_error_text((attach.stderr or attach.stdout or "").strip())
                message = "release candidate DMG could not be mounted"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            if not app_path.is_dir():
                findings.append(Finding(dmg_path, f"mounted release candidate DMG must contain {PACKAGED_APP_NAME}"))
                continue
            resources_path = app_path / "Contents" / "Resources"
            if not resources_path.is_dir():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain Contents/Resources"))
                continue
            findings.extend(
                verify_release_artifacts(
                    root=root,
                    paths=(resources_path,),
                    check_required_files=False,
                    check_release_security_guards=False,
                    allow_binary_targets=True,
                    check_packaged_app_bundle=True,
                )
            )
        finally:
            if attached:
                detach = subprocess.run(
                    ["hdiutil", "detach", str(mount_dir), "-quiet"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if detach.returncode != 0:
                    detail = redact_api_error_text((detach.stderr or detach.stdout or "").strip())
                    message = "release candidate DMG could not be detached"
                    if detail:
                        message = f"{message}: {detail}"
                    findings.append(Finding(dmg_path, message))
            shutil.rmtree(mount_dir, ignore_errors=True)
    return findings


def verify_release_candidate(
    *,
    root: Path = PROJECT_ROOT,
    artifact_paths: Sequence[Path] | None = None,
    require_artifacts: bool = False,
    source_only: bool = False,
    check_dmg_mount: bool = False,
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
        "dmg_mount_guards": {
            "status": "pending",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        },
        "manual_release_candidate_check_status": "manual_required",
        "manual_release_candidate_checks": list(MANUAL_RELEASE_CANDIDATE_CHECKS),
    }

    source_only_conflicts: list[str] = []
    if source_only:
        if artifact_paths:
            source_only_conflicts.append("artifact paths")
        if require_artifacts:
            source_only_conflicts.append("--require-artifacts")
        if check_dmg_mount:
            source_only_conflicts.append("--check-dmg-mount")
        if run_ui_smoke:
            source_only_conflicts.append("--run-ui-smoke")

    if source_only_conflicts:
        conflict_message = f"--source-only cannot be combined with {', '.join(source_only_conflicts)}"
        print("source release guards: skipped")
        print(f"built artifact guards: failed\n- {conflict_message}")
        report["source_release_guards"] = {
            "status": "skipped",
            "findings": [],
        }
        report["built_artifact_guards"] = {
            "status": "failed",
            "artifact_paths": [],
            "findings": [
                {
                    "path": str(root),
                    "message": conflict_message,
                }
            ],
        }
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }
        report["electron_ui_smoke"] = {
            "status": "skipped",
            "scripts": [],
            "run_requested": run_ui_smoke,
        }
        if report_json is not None:
            try:
                report_path = _resolve_report_path(root, report_json)
                _write_report(report_path, report)
            except (OSError, ValueError) as exc:
                print(f"release candidate report: failed\n- {exc}")
                return 1
            print(f"release candidate report: {report_json}")
        return 1

    source_findings = verify_release_artifacts(root=root)
    _print_findings("source release guards", source_findings)
    failed = failed or bool(source_findings)
    report["source_release_guards"] = {
        "status": "failed" if source_findings else "passed",
        "findings": _finding_report(source_findings),
    }

    selected_artifacts = (
        ()
        if source_only
        else tuple(artifact_paths) if artifact_paths is not None else existing_artifact_paths(root)
    )
    artifact_paths_valid = True
    try:
        selected_artifacts = _validate_artifact_paths(root, selected_artifacts)
    except ValueError as exc:
        print(f"built artifact guards: failed\n- {exc}")
        failed = True
        artifact_paths_valid = False
        report["built_artifact_guards"] = {
            "status": "failed",
            "artifact_paths": [str(path) for path in selected_artifacts],
            "findings": [{"path": str(root), "message": str(exc)}],
        }
    if report["built_artifact_guards"]["status"] == "pending":
        if source_only:
            print("built artifact guards: skipped by --source-only")
            report["built_artifact_guards"] = {
                "status": "skipped",
                "artifact_paths": [],
                "findings": [],
            }
            report["dmg_mount_guards"] = {
                "status": "skipped",
                "dmg_paths": [],
                "findings": [],
                "run_requested": check_dmg_mount,
            }
        elif selected_artifacts:
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

    if check_dmg_mount and not artifact_paths_valid:
        print("DMG mount guards: skipped because artifact paths failed validation")
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }
    elif check_dmg_mount:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        dmg_findings = verify_dmg_mount_artifacts(root, dmg_paths)
        _print_findings("DMG mount guards", dmg_findings)
        failed = failed or bool(dmg_findings)
        report["dmg_mount_guards"] = {
            "status": "failed" if dmg_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "findings": _finding_report(dmg_findings),
            "run_requested": check_dmg_mount,
        }
    else:
        print("DMG mount guards: skipped; pass --check-dmg-mount to inspect the app inside DMG artifacts")
        report["dmg_mount_guards"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": check_dmg_mount,
        }

    selected_smoke_scripts = tuple(smoke_scripts) if smoke_scripts is not None else release_ui_smoke_scripts(root)
    smoke_results: list[dict[str, object]] = []
    if run_ui_smoke:
        try:
            selected_smoke_scripts = _validate_smoke_script_paths(root, selected_smoke_scripts)
        except ValueError as exc:
            print(f"Electron UI smoke: failed\n- {exc}")
            smoke_results.append(
                {
                    "script": ", ".join(str(script) for script in selected_smoke_scripts),
                    "exit_code": None,
                    "error": str(exc),
                }
            )
            selected_smoke_scripts = ()
            failed = True
        if not selected_smoke_scripts and not smoke_results:
            print("Electron UI smoke: failed\n- no scripts/smoke_*_ui.mjs scripts found")
            failed = True
        for script in selected_smoke_scripts:
            print(f"Electron UI smoke: node {script}")
            try:
                result = subprocess.run(["node", str(script)], cwd=root, check=False)
            except OSError as exc:
                print(f"- {script} could not start: {exc}")
                smoke_results.append(
                    {"script": str(script), "exit_code": None, "error": str(exc)}
                )
                failed = True
            else:
                smoke_results.append({"script": str(script), "exit_code": result.returncode})
                if result.returncode != 0:
                    print(f"- {script} failed with exit code {result.returncode}")
                    failed = True
        smoke_failed = (not selected_smoke_scripts) or any(
            item["exit_code"] is None or item["exit_code"] for item in smoke_results
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
        try:
            report_path = _resolve_report_path(root, report_json)
            _write_report(report_path, report)
        except (OSError, ValueError) as exc:
            print(f"release candidate report: failed\n- {exc}")
            return 1
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
        "--source-only",
        action="store_true",
        help="Run source-level release guards only, rejecting built artifacts and UI smoke gates.",
    )
    parser.add_argument(
        "--run-ui-smoke",
        action="store_true",
        help="Run every scripts/smoke_*_ui.mjs Electron UI smoke.",
    )
    parser.add_argument(
        "--check-dmg-mount",
        action="store_true",
        help="Mount every discovered DMG and verify the packaged app inside it.",
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
        source_only=args.source_only,
        check_dmg_mount=args.check_dmg_mount,
        run_ui_smoke=args.run_ui_smoke,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
