"""Local release-candidate verification entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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
PACKAGED_APP_EXECUTABLE_NAME = "Oha-Yachiyo"
DMG_APP_SMOKE_TIMEOUT_SECONDS = 45.0
PROVIDER_SMOKE_ENV_VARS: tuple[str, ...] = (
    "OHA_YACHIYO_SMOKE_BASE_URL",
    "OHA_YACHIYO_SMOKE_MODEL",
    "OHA_YACHIYO_SMOKE_API_KEY",
)
PROVIDER_SMOKE_SCRIPT = Path("scripts/smoke_openai_compatible_stream.py")
PROVIDER_SMOKE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "text_stream",
        (
            "--require-content",
            "--expect-finish-reason",
            "stop",
        ),
    ),
    (
        "tool_call_stream",
        (
            "--tool-call",
            "--require-tool-call",
            "--require-tool-result-content",
            "--expect-tool-name",
            "workspace_read",
            "--expect-tool-argument-substring",
            "README.md",
            "--expect-tool-argument-json-field",
            "path=README.md",
            "--expect-finish-reason",
            "tool_calls",
            "--expect-tool-result-finish-reason",
            "stop",
        ),
    ),
)
MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS: tuple[dict[str, str], ...] = (
    {
        "id": "gatekeeper_first_launch",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Mount the DMG and launch Oha-Yachiyo.app once with the documented Gatekeeper first-launch flow.",
        "evidence": "Record the mounted DMG path and confirm Finder Control-click -> Open or System Settings allow-open flow reaches the app.",
    },
    {
        "id": "packaged_bridge_isolation",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Confirm the packaged app starts its local bridge and does not connect to a development backend.",
        "evidence": "Record the packaged bridge /status response and confirm the bridge URL is local loopback.",
    },
    {
        "id": "screen_recording_permission",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "Grant Screen Recording permission to Oha-Yachiyo.app and verify the local screenshot/proactive probe path.",
        "evidence": "Record the System Settings permission state and a successful local screenshot or proactive probe result.",
    },
    {
        "id": "real_provider_smoke",
        "status": "manual_required",
        "required_before": "public_release_signoff",
        "description": "If real provider credentials are available, run --run-provider-smoke for the opt-in streaming/tool-call provider gate.",
        "evidence": "Archive the RC report provider_smoke section from a credentialed run, or record that provider credentials were unavailable.",
    },
)
MANUAL_RELEASE_CANDIDATE_CHECKS: tuple[str, ...] = tuple(
    check["description"] for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
)


def _manual_release_candidate_check_report() -> list[dict[str, str]]:
    return [dict(check) for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS]


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


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _terminate_process(process: subprocess.Popen[str], timeout_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            pass


def _read_process_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        return "", ""
    return stdout or "", stderr or ""


def _redacted_process_detail(stdout: str, stderr: str) -> str:
    detail = "\n".join(part.strip() for part in (stderr, stdout) if part and part.strip())
    return redact_api_error_text(detail.strip())


def _provider_smoke_missing_env() -> list[str]:
    return [name for name in PROVIDER_SMOKE_ENV_VARS if not os.getenv(name, "").strip()]


def verify_provider_smoke(root: Path) -> tuple[list[Finding], list[dict[str, object]]]:
    findings: list[Finding] = []
    results: list[dict[str, object]] = []
    missing_env = _provider_smoke_missing_env()
    if missing_env:
        findings.append(
            Finding(
                root,
                "real provider smoke requested but missing environment variables: "
                + ", ".join(missing_env),
            )
        )
        return findings, results

    script = root / PROVIDER_SMOKE_SCRIPT
    for label, args in PROVIDER_SMOKE_COMMANDS:
        command = [sys.executable, str(PROVIDER_SMOKE_SCRIPT), *args]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            detail = redact_api_error_text(str(exc))
            findings.append(Finding(script, f"real provider {label} smoke could not start: {detail}"))
            results.append({"label": label, "exit_code": None})
            continue
        results.append({"label": label, "exit_code": result.returncode})
        if result.returncode != 0:
            detail = _redacted_process_detail(result.stdout, result.stderr)
            message = f"real provider {label} smoke failed with exit code {result.returncode}"
            if detail:
                message = f"{message}: {detail}"
            findings.append(Finding(script, message))
    return findings, results


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


def _read_status_json(bridge_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{bridge_url}/status", timeout=1.0) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def verify_dmg_app_startup(
    root: Path,
    dmg_paths: Sequence[Path],
    *,
    timeout_seconds: float = DMG_APP_SMOKE_TIMEOUT_SECONDS,
) -> list[Finding]:
    findings: list[Finding] = []
    if not dmg_paths:
        findings.append(Finding(root, "release candidate DMG app startup smoke requested but no .dmg artifacts were found"))
        return findings
    if sys.platform != "darwin":
        findings.append(Finding(root, "release candidate DMG app startup smoke requires macOS"))
        return findings
    for dmg_path in dmg_paths:
        absolute_dmg = _absolute_artifact_path(root, dmg_path)
        mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-rc-app-"))
        attached = False
        process: subprocess.Popen[str] | None = None
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
                message = "release candidate DMG could not be mounted for app startup smoke"
                if detail:
                    message = f"{message}: {detail}"
                findings.append(Finding(dmg_path, message))
                continue
            attached = True
            app_path = mount_dir / PACKAGED_APP_NAME
            executable_path = app_path / "Contents" / "MacOS" / PACKAGED_APP_EXECUTABLE_NAME
            if not executable_path.is_file():
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} must contain executable {PACKAGED_APP_EXECUTABLE_NAME}"))
                continue
            if not os.access(executable_path, os.X_OK):
                findings.append(Finding(dmg_path, f"mounted {PACKAGED_APP_NAME} executable is not executable"))
                continue
            bridge_url = f"http://127.0.0.1:{_allocate_loopback_port()}"
            with tempfile.TemporaryDirectory(prefix="oha-yachiyo-rc-home-") as home_dir:
                env = {
                    **os.environ,
                    "HOME": home_dir,
                    "OHA_YACHIYO_HOME": str(Path(home_dir) / ".oha-yachiyo"),
                    "OHA_YACHIYO_BRIDGE_URL": bridge_url,
                }
                process = subprocess.Popen(
                    [str(executable_path)],
                    cwd=str(app_path),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + timeout_seconds
                last_error = ""
                passed = False
                while time.monotonic() < deadline:
                    exit_code = process.poll()
                    if exit_code is not None:
                        stdout, stderr = _read_process_output(process)
                        detail = _redacted_process_detail(stdout, stderr)
                        message = f"release candidate app exited before /status was ready: exit_code={exit_code}"
                        if detail:
                            message = f"{message}: {detail}"
                        findings.append(Finding(dmg_path, message))
                        break
                    try:
                        status = _read_status_json(bridge_url)
                    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                        last_error = redact_api_error_text(str(exc))
                        time.sleep(0.5)
                        continue
                    if status.get("service") == "oha-yachiyo":
                        passed = True
                        break
                    last_error = redact_api_error_text(f"unexpected /status service={status.get('service')!r}")
                    time.sleep(0.5)
                if not passed and not any(finding.path == dmg_path for finding in findings):
                    message = f"release candidate app did not expose /status within {timeout_seconds:.0f}s"
                    if last_error:
                        message = f"{message}: {last_error}"
                    findings.append(Finding(dmg_path, message))
        finally:
            if process is not None:
                _terminate_process(process)
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
                    message = "release candidate DMG could not be detached after app startup smoke"
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
    run_dmg_app_smoke: bool = False,
    run_provider_smoke: bool = False,
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
        "dmg_app_smoke": {
            "status": "pending",
            "dmg_paths": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        },
        "provider_smoke": {
            "status": "pending",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
        },
        "manual_release_candidate_check_status": "manual_required",
        "manual_release_candidate_checks": list(MANUAL_RELEASE_CANDIDATE_CHECKS),
        "manual_release_candidate_check_statuses": _manual_release_candidate_check_report(),
    }

    source_only_conflicts: list[str] = []
    if source_only:
        if artifact_paths:
            source_only_conflicts.append("artifact paths")
        if require_artifacts:
            source_only_conflicts.append("--require-artifacts")
        if check_dmg_mount:
            source_only_conflicts.append("--check-dmg-mount")
        if run_dmg_app_smoke:
            source_only_conflicts.append("--run-dmg-app-smoke")
        if run_provider_smoke:
            source_only_conflicts.append("--run-provider-smoke")
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
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
        report["provider_smoke"] = {
            "status": "skipped",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
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
            report["dmg_app_smoke"] = {
                "status": "skipped",
                "dmg_paths": [],
                "findings": [],
                "run_requested": run_dmg_app_smoke,
            }
            report["provider_smoke"] = {
                "status": "skipped",
                "checks": [],
                "findings": [],
                "run_requested": run_provider_smoke,
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

    if run_dmg_app_smoke and not artifact_paths_valid:
        print("DMG app startup smoke: skipped because artifact paths failed validation")
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }
    elif run_dmg_app_smoke:
        dmg_paths = release_candidate_dmg_paths(root, selected_artifacts)
        startup_findings = verify_dmg_app_startup(root, dmg_paths)
        _print_findings("DMG app startup smoke", startup_findings)
        failed = failed or bool(startup_findings)
        report["dmg_app_smoke"] = {
            "status": "failed" if startup_findings else "passed",
            "dmg_paths": [str(path) for path in dmg_paths],
            "findings": _finding_report(startup_findings),
            "run_requested": run_dmg_app_smoke,
        }
    else:
        print("DMG app startup smoke: skipped; pass --run-dmg-app-smoke to launch the app inside DMG artifacts")
        report["dmg_app_smoke"] = {
            "status": "skipped",
            "dmg_paths": [],
            "findings": [],
            "run_requested": run_dmg_app_smoke,
        }

    if run_provider_smoke:
        provider_findings, provider_results = verify_provider_smoke(root)
        _print_findings("real provider smoke", provider_findings)
        failed = failed or bool(provider_findings)
        report["provider_smoke"] = {
            "status": "failed" if provider_findings else "passed",
            "checks": provider_results,
            "findings": _finding_report(provider_findings),
            "run_requested": run_provider_smoke,
        }
    else:
        print("real provider smoke: skipped; pass --run-provider-smoke when OHA_YACHIYO_SMOKE_* credentials are configured")
        report["provider_smoke"] = {
            "status": "skipped",
            "checks": [],
            "findings": [],
            "run_requested": run_provider_smoke,
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
    for check in MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS:
        print(f"- [{check['id']}] {check['description']}")

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
        "--run-dmg-app-smoke",
        action="store_true",
        help="Launch the app inside discovered DMGs and wait for its packaged /status endpoint.",
    )
    parser.add_argument(
        "--run-provider-smoke",
        action="store_true",
        help="Run opt-in real provider streaming and tool-call smoke using OHA_YACHIYO_SMOKE_* credentials.",
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
        run_dmg_app_smoke=args.run_dmg_app_smoke,
        run_provider_smoke=args.run_provider_smoke,
        run_ui_smoke=args.run_ui_smoke,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
