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


def _report_matches_current_source(report_path: Path, *, short_commit: str) -> bool:
    if not report_path.exists():
        return False
    try:
        report = _load_report(report_path)
    except (OSError, json.JSONDecodeError):
        return False
    source_revision = report.get("source_revision")
    if not isinstance(source_revision, dict):
        return False
    if source_revision.get("dirty") is not False:
        return False
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
        and _report_matches_current_source(batch_report, short_commit=label)
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
