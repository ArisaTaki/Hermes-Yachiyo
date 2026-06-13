#!/usr/bin/env python3
"""Refresh local release-candidate evidence and final signoff draft for HEAD."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SMOKE_ENV_VARS = (
    "OHA_YACHIYO_SMOKE_BASE_URL",
    "OHA_YACHIYO_SMOKE_MODEL",
    "OHA_YACHIYO_SMOKE_API_KEY",
)
SCREEN_RECORDING_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)
DEFAULT_SCREEN_SMOKE_APP_PATH = Path(
    "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app"
)
DEFAULT_SCREEN_SMOKE_BACKEND_PATH = (
    DEFAULT_SCREEN_SMOKE_APP_PATH
    / "Contents"
    / "Resources"
    / "backend"
    / "oha-yachiyo-backend"
)
DEFAULT_DMG_PATH = Path("dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_release_candidate_artifacts import build_release_candidate_artifacts


def _run(command: list[str], *, allow_failure: bool = False) -> int:
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode and not allow_failure:
        raise subprocess.CalledProcessError(result.returncode, command)
    return result.returncode


def _git_short_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=8", "HEAD"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _provider_smoke_configured() -> bool:
    return all(os.getenv(name, "").strip() for name in PROVIDER_SMOKE_ENV_VARS)


def _non_manual_findings(report: dict[str, object]) -> list[tuple[str, object]]:
    findings: list[tuple[str, object]] = []
    for key, value in sorted(report.items()):
        if not key.endswith("findings"):
            continue
        if not value:
            continue
        findings.append((key, value))
    return findings


def _load_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_project_file(path: Path, label: str) -> Path:
    root = ROOT.resolve(strict=False)
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"{label} path must stay inside project root: {path}")
    return resolved


def _report_matches_current_source(
    report_path: Path,
    *,
    short_commit: str,
    require_ok: bool = False,
) -> bool:
    if not report_path.exists():
        return False
    try:
        report = _load_report(report_path)
    except (OSError, json.JSONDecodeError):
        return False
    if require_ok and report.get("ok") is not True:
        return False
    source_revision = report.get("source_revision")
    if not isinstance(source_revision, dict):
        return False
    if source_revision.get("dirty") is not False:
        return False
    commit = source_revision.get("commit")
    if isinstance(commit, str) and commit:
        return commit.startswith(short_commit)
    return source_revision.get("short_commit") == short_commit


def _preview_failure_is_only_manual_incomplete(report_path: Path) -> bool:
    report = _load_report(report_path)
    summary = report.get("manual_release_candidate_check_summary")
    remaining_count = (
        int(summary.get("remaining_count", 0))
        if isinstance(summary, dict)
        else 0
    )
    if remaining_count <= 0:
        return False
    return not _non_manual_findings(report)


def _remaining_check_ids(report_path: Path) -> list[str]:
    try:
        report = _load_report(report_path)
    except (OSError, json.JSONDecodeError):
        return []
    summary = report.get("manual_release_candidate_check_summary")
    if not isinstance(summary, dict):
        return []
    remaining = summary.get("remaining_check_ids")
    if not isinstance(remaining, list):
        return []
    return [str(check_id) for check_id in remaining if isinstance(check_id, str)]


def _os_evidence_command_parts(*, label: str, signoff_draft: Path) -> list[str]:
    remaining_ids = set(_remaining_check_ids(signoff_draft))
    os_check_ids = {
        "gatekeeper_first_launch",
        "screen_recording_permission",
    }
    if not remaining_ids.intersection(os_check_ids):
        return []

    command = [
        f"{sys.executable} scripts/refresh_local_rc_signoff.py",
        f"--write-os-evidence tmp/rc-signoff-{label}-os-evidence.json",
    ]
    if "gatekeeper_first_launch" in remaining_ids:
        command.append(
            '--gatekeeper-evidence "<record Gatekeeper/Finder first-launch evidence>"'
        )
    if "screen_recording_permission" in remaining_ids:
        command.append(
            '--screen-recording-evidence "<record Screen Recording evidence after '
            'rerunning --run-dmg-screen-smoke or a manual screenshot/proactive probe>"'
        )
    return command


def _print_os_evidence_command(*, label: str, signoff_draft: Path) -> None:
    command = _os_evidence_command_parts(label=label, signoff_draft=signoff_draft)
    if not command:
        return
    print("local RC OS evidence command:")
    print(" ".join(command))


def _screen_probe_launch_paths(*, label: str) -> tuple[str, str, str]:
    screen_report = ROOT / "tmp" / f"rc-verification-{label}-screen.json"
    fallback = (
        str(DEFAULT_DMG_PATH),
        str(DEFAULT_SCREEN_SMOKE_APP_PATH),
        str(DEFAULT_SCREEN_SMOKE_BACKEND_PATH),
    )
    if not screen_report.exists():
        return fallback
    try:
        report = _load_report(screen_report)
    except (OSError, json.JSONDecodeError):
        return fallback
    probe = report.get("dmg_screen_probe")
    if not isinstance(probe, dict):
        return fallback
    launch_paths = probe.get("app_launch_paths")
    if not isinstance(launch_paths, list) or not launch_paths:
        return fallback
    first = launch_paths[0]
    if not isinstance(first, dict):
        return fallback
    dmg_path = first.get("dmg_path")
    app_path = first.get("app_path")
    backend_path = first.get("backend_path")
    return (
        dmg_path if isinstance(dmg_path, str) and dmg_path else str(DEFAULT_DMG_PATH),
        app_path
        if isinstance(app_path, str) and app_path
        else str(DEFAULT_SCREEN_SMOKE_APP_PATH),
        backend_path
        if isinstance(backend_path, str) and backend_path
        else str(DEFAULT_SCREEN_SMOKE_BACKEND_PATH),
    )


def print_local_os_signoff_guide(*, short_commit: str | None = None) -> bool:
    label = short_commit or _git_short_commit()
    signoff_draft = ROOT / "tmp" / f"rc-signoff-{label}-current.json"
    if not signoff_draft.exists():
        print(
            f"local RC signoff draft not found: {signoff_draft.relative_to(ROOT)}",
            file=sys.stderr,
        )
        return False
    remaining_ids = set(_remaining_check_ids(signoff_draft))
    os_remaining = [
        check_id
        for check_id in ("gatekeeper_first_launch", "screen_recording_permission")
        if check_id in remaining_ids
    ]
    print("local RC OS signoff guide:")
    print(f"- signoff draft: {signoff_draft.relative_to(ROOT)}")
    if not os_remaining:
        print("- no Gatekeeper or Screen Recording manual checks remain")
        return True

    dmg_path, app_path, backend_path = _screen_probe_launch_paths(label=label)
    print(f"- DMG: {dmg_path}")
    print(f"- stable Screen Recording app path: {app_path}")
    print(f"- stable Screen Recording backend path: {backend_path}")
    if "gatekeeper_first_launch" in os_remaining:
        print(
            "- Gatekeeper: mount the DMG and launch Oha-Yachiyo.app via Finder "
            "Control-click -> Open or the System Settings allow-open flow."
        )
    if "screen_recording_permission" in os_remaining:
        print(
            "- Screen Recording: reveal the stable app path, grant permission, "
            "then rerun the screen smoke."
        )
        print(f"  open -R \"{app_path}\"")
        print(f"  open -R \"{backend_path}\"")
        print(f"  open \"{SCREEN_RECORDING_SETTINGS_URL}\"")
        print(
            "  "
            f"{sys.executable} scripts/verify_release_candidate.py "
            "--require-artifacts --run-dmg-screen-smoke "
            f"--report-json tmp/rc-verification-{label}-screen.json"
        )

    command = _os_evidence_command_parts(label=label, signoff_draft=signoff_draft)
    if command:
        print("- after OS evidence is true, write the project-local evidence JSON:")
        print("  " + " ".join(command))
    print("- final signoff command:")
    print(
        "  "
        f"{sys.executable} scripts/verify_release_candidate.py "
        "--require-artifacts "
        f"--manual-checks-json tmp/rc-signoff-{label}-current.json "
        f"--manual-checks-json tmp/rc-signoff-{label}-os-evidence.json "
        "--require-manual-checks-complete "
        f"--report-json tmp/rc-signoff-{label}-final.json"
    )
    return True


def refresh_local_rc_signoff(
    *,
    short_commit: str | None = None,
    channel: str = "experimental",
    repository: str | None = None,
    skip_build: bool = False,
    run_provider_smoke: bool = False,
    skip_screen_smoke: bool = False,
    reuse_current_reports: bool = False,
) -> dict[str, Path]:
    label = short_commit or _git_short_commit()
    tmp_dir = ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    batch_report = tmp_dir / f"rc-verification-{label}-packaged-batch.json"
    screen_report = tmp_dir / f"rc-verification-{label}-screen.json"
    signoff_draft = tmp_dir / f"rc-signoff-{label}-current.json"
    signoff_markdown = tmp_dir / f"rc-signoff-{label}-current.md"
    signoff_preview = tmp_dir / f"rc-signoff-{label}-preview.json"
    batch_report_is_current = (
        reuse_current_reports
        and not run_provider_smoke
        and _report_matches_current_source(
            batch_report,
            short_commit=label,
            require_ok=True,
        )
    )
    screen_report_is_current = (
        reuse_current_reports
        and _report_matches_current_source(screen_report, short_commit=label)
    )

    if not skip_build and not batch_report_is_current:
        build_release_candidate_artifacts(channel=channel, repository=repository)
        screen_report_is_current = False

    if not batch_report_is_current:
        batch_command = [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--require-artifacts",
            "--check-dmg-mount",
            "--run-dmg-app-smoke",
            "--run-dmg-ui-sampling-smoke",
            "--run-dmg-chat-native-file-smoke",
            "--report-json",
            str(batch_report.relative_to(ROOT)),
        ]
        if run_provider_smoke:
            batch_command.append("--run-provider-smoke")
        _run(batch_command)

    manual_sources = [batch_report]
    if not skip_screen_smoke:
        if not screen_report_is_current:
            screen_command = [
                sys.executable,
                "scripts/verify_release_candidate.py",
                "--require-artifacts",
                "--run-dmg-screen-smoke",
                "--report-json",
                str(screen_report.relative_to(ROOT)),
            ]
            _run(screen_command, allow_failure=True)
        if screen_report.exists():
            manual_sources.append(screen_report)

    draft_command = [sys.executable, "scripts/verify_release_candidate.py"]
    for source in manual_sources:
        draft_command.extend(["--manual-checks-json", str(source.relative_to(ROOT))])
    draft_command.extend(
        [
            "--mark-provider-smoke-not-applicable-if-missing",
            "--write-manual-checks-draft",
            str(signoff_draft.relative_to(ROOT)),
        ]
    )
    _run(draft_command)

    markdown_command = [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        str(signoff_draft.relative_to(ROOT)),
        "--write-manual-checks-markdown",
        str(signoff_markdown.relative_to(ROOT)),
    ]
    _run(markdown_command)

    preview_command = [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--require-artifacts",
        "--manual-checks-json",
        str(signoff_draft.relative_to(ROOT)),
        "--require-manual-checks-complete",
        "--report-json",
        str(signoff_preview.relative_to(ROOT)),
    ]
    preview_code = _run(preview_command, allow_failure=True)
    if preview_code and not _preview_failure_is_only_manual_incomplete(signoff_preview):
        raise subprocess.CalledProcessError(preview_code, preview_command)

    return {
        "batch_report": batch_report,
        "screen_report": screen_report,
        "signoff_draft": signoff_draft,
        "signoff_markdown": signoff_markdown,
        "signoff_preview": signoff_preview,
    }


def print_local_rc_signoff_status(*, short_commit: str | None = None) -> bool:
    label = short_commit or _git_short_commit()
    signoff_draft = ROOT / "tmp" / f"rc-signoff-{label}-current.json"
    if not signoff_draft.exists():
        print(
            f"local RC signoff draft not found: {signoff_draft.relative_to(ROOT)}",
            file=sys.stderr,
        )
        return False
    command = [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        str(signoff_draft.relative_to(ROOT)),
        "--print-manual-checks-status",
    ]
    ok = _run(command, allow_failure=True) == 0
    if ok:
        _print_os_evidence_command(label=label, signoff_draft=signoff_draft)
    return ok


def write_local_os_manual_evidence(
    *,
    output_path: Path,
    short_commit: str | None = None,
    gatekeeper_evidence: str = "",
    screen_recording_evidence: str = "",
) -> Path:
    label = short_commit or _git_short_commit()
    signoff_draft = ROOT / "tmp" / f"rc-signoff-{label}-current.json"
    if not signoff_draft.exists():
        raise ValueError(
            f"local RC signoff draft not found: {signoff_draft.relative_to(ROOT)}"
        )
    gatekeeper_evidence = gatekeeper_evidence.strip()
    screen_recording_evidence = screen_recording_evidence.strip()
    if not gatekeeper_evidence and not screen_recording_evidence:
        raise ValueError(
            "provide --gatekeeper-evidence, --screen-recording-evidence, or both"
        )

    draft = _load_report(signoff_draft)
    source_revisions = draft.get("manual_release_candidate_check_source_revisions")
    if not isinstance(source_revisions, list) or not source_revisions:
        raise ValueError(
            f"{signoff_draft.relative_to(ROOT)} is missing "
            "manual_release_candidate_check_source_revisions; refresh local RC "
            "signoff before recording OS evidence"
        )

    checks: list[dict[str, str]] = []
    if gatekeeper_evidence:
        checks.append(
            {
                "id": "gatekeeper_first_launch",
                "status": "passed",
                "evidence": gatekeeper_evidence,
                "notes": "Recorded via refresh_local_rc_signoff.py --write-os-evidence.",
            }
        )
    if screen_recording_evidence:
        checks.append(
            {
                "id": "screen_recording_permission",
                "status": "passed",
                "evidence": screen_recording_evidence,
                "notes": "Recorded via refresh_local_rc_signoff.py --write-os-evidence.",
            }
        )

    resolved = _resolve_project_file(output_path, "local RC OS evidence")
    _write_report(
        resolved,
        {
            "checks": checks,
            "manual_release_candidate_checks_source": str(signoff_draft.relative_to(ROOT)),
            "manual_release_candidate_check_source_revisions": source_revisions,
        },
    )
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short-commit", help="Override report filename commit label.")
    parser.add_argument(
        "--channel",
        default="experimental",
        choices=("stable", "alpha", "experimental"),
        help="Release channel metadata for local artifact rebuilds.",
    )
    parser.add_argument("--repository", help="GitHub owner/repo for build metadata.")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-screen-smoke", action="store_true")
    parser.add_argument(
        "--print-status",
        action="store_true",
        help="Print the current HEAD local RC signoff status without building or writing reports.",
    )
    parser.add_argument(
        "--print-os-signoff-guide",
        action="store_true",
        help=(
            "Print the concrete Gatekeeper and Screen Recording signoff steps "
            "for the current local RC draft without changing evidence status."
        ),
    )
    parser.add_argument(
        "--write-os-evidence",
        type=Path,
        help=(
            "Write a small project-local manual evidence JSON for Gatekeeper and/or "
            "Screen Recording OS signoff, inheriting source revision metadata from "
            "the current local RC signoff draft."
        ),
    )
    parser.add_argument(
        "--gatekeeper-evidence",
        default="",
        help="Evidence text for the gatekeeper_first_launch manual check.",
    )
    parser.add_argument(
        "--screen-recording-evidence",
        default="",
        help="Evidence text for the screen_recording_permission manual check.",
    )
    parser.add_argument(
        "--reuse-current-reports",
        action="store_true",
        help=(
            "Reuse existing batch/screen reports when their source_revision "
            "matches the current clean HEAD short commit."
        ),
    )
    parser.add_argument(
        "--run-provider-smoke",
        action="store_true",
        help="Run real provider smoke during the packaged batch gate.",
    )
    args = parser.parse_args(argv)
    selected_actions = [
        args.print_status,
        args.print_os_signoff_guide,
        args.write_os_evidence is not None,
    ]
    if sum(1 for selected in selected_actions if selected) > 1:
        print(
            "local RC signoff action: failed\n"
            "- choose only one of --print-status, --print-os-signoff-guide, "
            "or --write-os-evidence",
            file=sys.stderr,
        )
        return 1
    if args.print_status:
        return 0 if print_local_rc_signoff_status(short_commit=args.short_commit) else 1
    if args.print_os_signoff_guide:
        return 0 if print_local_os_signoff_guide(short_commit=args.short_commit) else 1
    if args.write_os_evidence is not None:
        try:
            evidence_path = write_local_os_manual_evidence(
                output_path=args.write_os_evidence,
                short_commit=args.short_commit,
                gatekeeper_evidence=args.gatekeeper_evidence,
                screen_recording_evidence=args.screen_recording_evidence,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"local RC OS evidence: failed\n- {exc}", file=sys.stderr)
            return 1
        print(f"local RC OS evidence: {evidence_path.relative_to(ROOT)}")
        label = args.short_commit or _git_short_commit()
        print("local RC final signoff command:")
        print(
            f"{sys.executable} scripts/verify_release_candidate.py "
            f"--require-artifacts "
            f"--manual-checks-json tmp/rc-signoff-{label}-current.json "
            f"--manual-checks-json {evidence_path.relative_to(ROOT)} "
            f"--require-manual-checks-complete "
            f"--report-json tmp/rc-signoff-{label}-final.json"
        )
        return 0
    if args.run_provider_smoke and not _provider_smoke_configured():
        missing = [
            name for name in PROVIDER_SMOKE_ENV_VARS if not os.getenv(name, "").strip()
        ]
        print(
            "provider smoke credentials missing: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    try:
        reports = refresh_local_rc_signoff(
            short_commit=args.short_commit,
            channel=args.channel,
            repository=args.repository,
            skip_build=args.skip_build,
            run_provider_smoke=args.run_provider_smoke,
            skip_screen_smoke=args.skip_screen_smoke,
            reuse_current_reports=args.reuse_current_reports,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"local RC signoff refresh failed: {' '.join(map(str, exc.cmd))}",
            file=sys.stderr,
        )
        return exc.returncode or 1

    print("local RC signoff reports:")
    for label, path in reports.items():
        if label == "screen_report" and not path.exists():
            continue
        print(f"- {label}: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
