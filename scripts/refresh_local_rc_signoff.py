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


def _project_venv_python() -> Path:
    return ROOT / ".venv" / "bin" / "python"


def _same_python(left: Path, right: Path) -> bool:
    return left.expanduser().absolute() == right.expanduser().absolute()


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


def _build_release_candidate_artifacts(*, channel: str, repository: str | None) -> None:
    venv_python = _project_venv_python()
    if venv_python.exists() and not _same_python(Path(sys.executable), venv_python):
        command = [
            str(venv_python),
            "scripts/build_release_candidate_artifacts.py",
            "--channel",
            channel,
        ]
        if repository:
            command.extend(["--repository", repository])
        _run(command)
        return
    build_release_candidate_artifacts(channel=channel, repository=repository)


def _non_manual_findings(report: dict[str, object]) -> list[tuple[str, object]]:
    findings: list[tuple[str, object]] = []
    for key, value in sorted(report.items()):
        if not key.endswith("findings"):
            continue
        if not value:
            continue
        findings.append((key, value))
    return findings


def _string_items(value: object) -> list[str]:
    if isinstance(value, str):
        values: list[object] = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return []
    return [str(item) for item in values if str(item)]


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _load_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_or_display(path: Path) -> Path:
    try:
        return path.resolve(strict=False).relative_to(ROOT.resolve(strict=False))
    except ValueError:
        return path


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


def _latest_tmp_report(pattern: str) -> Path | None:
    tmp_dir = ROOT / "tmp"
    if not tmp_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for path in tmp_dir.glob(pattern):
        if not path.is_file():
            continue
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _print_missing_current_signoff_guidance(
    *,
    label: str,
    signoff_draft: Path,
) -> None:
    print(
        f"local RC signoff draft not found: {signoff_draft.relative_to(ROOT)}",
        file=sys.stderr,
    )
    latest_reports = [
        ("latest signoff draft", _latest_tmp_report("rc-signoff-*-current.json")),
        (
            "latest release readiness",
            _latest_tmp_report("rc-verification-*-release-readiness.json"),
        ),
        (
            "latest Oha product smoke",
            _latest_tmp_report("rc-verification-*-oha-desktop-agent-release-smoke.json"),
        ),
        (
            "latest release smoke",
            _latest_tmp_report("rc-verification-*-release-smoke.json"),
        ),
        (
            "latest public demo",
            _latest_tmp_report("rc-verification-*-public-demo.json"),
        ),
    ]
    existing_reports = [
        (label_text, path)
        for label_text, path in latest_reports
        if path is not None and path != signoff_draft
    ]
    if existing_reports:
        print("latest available local RC evidence:", file=sys.stderr)
        for label_text, path in existing_reports:
            print(f"- {label_text}: {path.relative_to(ROOT)}", file=sys.stderr)
    print("refresh current local RC signoff draft:", file=sys.stderr)
    print(
        f"  {sys.executable} scripts/refresh_local_rc_signoff.py "
        f"--short-commit {label} --reuse-current-reports",
        file=sys.stderr,
    )
    print("then rerun status:", file=sys.stderr)
    print(
        f"  {sys.executable} scripts/refresh_local_rc_signoff.py "
        f"--short-commit {label} --print-status",
        file=sys.stderr,
    )
    print(
        "add --run-real-desktop-smokes or --run-provider-smoke when collecting "
        "opt-in release evidence for this commit.",
        file=sys.stderr,
    )


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
    print(
        "replace the <record ...> placeholders with real OS evidence before "
        "running this command; placeholder values are rejected."
    )
    print(" ".join(command))


def _local_screen_smoke_command(*, label: str) -> str:
    return (
        f"{sys.executable} scripts/verify_release_candidate.py "
        "--require-artifacts --run-dmg-screen-smoke "
        f"--report-json tmp/rc-verification-{label}-screen.json"
    )


def _local_gatekeeper_readiness_command(*, label: str) -> str:
    return (
        f"{sys.executable} scripts/verify_release_candidate.py "
        "--require-artifacts --check-gatekeeper-readiness "
        f"--report-json tmp/rc-verification-{label}-gatekeeper-readiness.json"
    )


def _is_placeholder_evidence(value: str) -> bool:
    text = value.strip()
    return text.startswith("<record ") and text.endswith(">")


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
    non_os_remaining = sorted(set(remaining_ids) - set(os_remaining))
    print("local RC OS signoff guide:")
    print(f"- signoff draft: {signoff_draft.relative_to(ROOT)}")
    if not os_remaining and not non_os_remaining:
        print("- no Gatekeeper or Screen Recording manual checks remain")
        return True

    dmg_path, app_path, backend_path = _screen_probe_launch_paths(label=label)
    if os_remaining:
        print(f"- DMG: {dmg_path}")
        print(f"- stable Screen Recording app path: {app_path}")
        print(f"- stable Screen Recording backend path: {backend_path}")
    if "gatekeeper_first_launch" in os_remaining:
        print(
            "- Gatekeeper: mount the DMG and launch Oha-Yachiyo.app via Finder "
            "Control-click -> Open or the System Settings allow-open flow."
        )
        print("- Gatekeeper readiness diagnostics:")
        print(f"  {_local_gatekeeper_readiness_command(label=label)}")
    if "screen_recording_permission" in os_remaining:
        print(
            "- Screen Recording: reveal the stable app path, grant permission, "
            "then rerun the screen smoke."
        )
        print(f"  open -R \"{app_path}\"")
        print(f"  open -R \"{backend_path}\"")
        print(f"  open \"{SCREEN_RECORDING_SETTINGS_URL}\"")
        print(f"  {_local_screen_smoke_command(label=label)}")

    extra_manual_json_args: list[str] = []
    if non_os_remaining:
        print(
            "- non-OS checks still required before final signoff: "
            + ", ".join(non_os_remaining)
        )
    if "external_integrations_smoke" in non_os_remaining:
        extra_manual_json_args.append("tmp/external-integrations-smoke.json")
        print("- external integrations evidence:")
        print(
            "  python scripts/verify_release_candidate.py "
            "--require-artifacts --run-packaged-backend-bridge-smoke "
            f"--report-json tmp/rc-verification-{label}-backend-bridge.json"
        )
        print(
            "  python scripts/smoke_external_integrations.py "
            "--bridge-url http://127.0.0.1:18420 "
            "--bridge-only --report-json tmp/external-integrations-bridge-preflight.json"
        )
        print(
            "  python scripts/smoke_external_integrations.py "
            "--bridge-url http://127.0.0.1:18420 "
            "--live2d-archive /path/to/yachiyo-live2d.zip "
            "--tts-voice-archive /path/to/yachiyo-gpt-sovits.zip "
            "--gpt-sovits-base-url http://127.0.0.1:9880 "
            "--astrbot --report-json tmp/external-integrations-smoke.json"
        )

    command = _os_evidence_command_parts(label=label, signoff_draft=signoff_draft)
    if command:
        print("- after OS evidence is true, write the project-local evidence JSON:")
        print(
            "  replace the <record ...> placeholders with real OS evidence; "
            "placeholder values are rejected."
        )
        print("  " + " ".join(command))
    final_command = [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--require-artifacts",
        "--manual-checks-json",
        f"tmp/rc-signoff-{label}-current.json",
    ]
    if command:
        final_command.extend(
            [
                "--manual-checks-json",
                f"tmp/rc-signoff-{label}-os-evidence.json",
            ]
        )
    for manual_json in extra_manual_json_args:
        final_command.extend(["--manual-checks-json", manual_json])
    final_command.extend(
        [
            "--require-manual-checks-complete",
            "--report-json",
            f"tmp/rc-signoff-{label}-final.json",
        ]
    )
    print("- final signoff command:")
    print("  " + " ".join(final_command))
    return True


def refresh_local_rc_signoff(
    *,
    short_commit: str | None = None,
    channel: str = "experimental",
    repository: str | None = None,
    skip_build: bool = False,
    skip_source_capability_smoke: bool = False,
    run_real_desktop_smokes: bool = False,
    run_provider_smoke: bool = False,
    skip_screen_smoke: bool = False,
    reuse_current_reports: bool = False,
    provider_manifest: Path | None = None,
    public_demo_reports: tuple[Path, ...] = (),
) -> dict[str, Path]:
    label = short_commit or _git_short_commit()
    tmp_dir = ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    source_capability_report = tmp_dir / f"rc-verification-{label}-source-capabilities.json"
    batch_report = tmp_dir / f"rc-verification-{label}-packaged-batch.json"
    screen_report = tmp_dir / f"rc-verification-{label}-screen.json"
    native_capability_matrix_report = tmp_dir / f"rc-verification-{label}-native-capability-matrix.json"
    release_readiness_report = tmp_dir / f"rc-verification-{label}-release-readiness.json"
    release_readiness_markdown = tmp_dir / f"rc-verification-{label}-release-readiness.md"
    diagnostics_bundle = tmp_dir / f"oha-yachiyo-diagnostics-{label}.zip"
    release_smoke_report = tmp_dir / f"rc-verification-{label}-release-smoke.json"
    release_smoke_markdown = tmp_dir / f"rc-verification-{label}-release-smoke.md"
    oha_desktop_agent_smoke_report = (
        tmp_dir / f"rc-verification-{label}-oha-desktop-agent-release-smoke.json"
    )
    public_demo_report = tmp_dir / f"rc-verification-{label}-public-demo.json"
    public_demo_markdown = tmp_dir / f"rc-verification-{label}-public-demo.md"
    signoff_draft = tmp_dir / f"rc-signoff-{label}-current.json"
    signoff_markdown = tmp_dir / f"rc-signoff-{label}-current.md"
    signoff_preview = tmp_dir / f"rc-signoff-{label}-preview.json"
    source_capability_report_is_current = (
        reuse_current_reports
        and not run_real_desktop_smokes
        and _report_matches_current_source(
            source_capability_report,
            short_commit=label,
        )
    )
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
        _build_release_candidate_artifacts(channel=channel, repository=repository)
        screen_report_is_current = False

    if not skip_source_capability_smoke and not source_capability_report_is_current:
        source_capability_command = [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--source-only",
            "--report-json",
            str(source_capability_report.relative_to(ROOT)),
        ]
        if run_real_desktop_smokes:
            source_capability_command.extend(
                [
                    "--run-real-desktop-app-open-smoke",
                    "--run-real-desktop-ui-inspection-smoke",
                    "--run-real-desktop-interaction-smoke",
                ]
            )
        _run(source_capability_command)

    if not batch_report_is_current:
        batch_command = [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--require-artifacts",
            "--check-dmg-mount",
            "--check-gatekeeper-readiness",
            "--run-packaged-backend-bridge-smoke",
            "--run-dmg-app-smoke",
            "--run-dmg-ui-sampling-smoke",
            "--run-dmg-chat-native-file-smoke",
            "--report-json",
            str(batch_report.relative_to(ROOT)),
        ]
        if run_real_desktop_smokes:
            batch_command.extend(
                [
                    "--run-real-desktop-app-open-smoke",
                    "--run-real-desktop-ui-inspection-smoke",
                    "--run-real-desktop-interaction-smoke",
                    "--allow-real-desktop-interaction-existing-app",
                ]
            )
        if run_provider_smoke:
            batch_command.append("--run-provider-smoke")
        _run(batch_command)

    manual_sources = []
    if not skip_source_capability_smoke and source_capability_report.exists():
        manual_sources.append(source_capability_report)
    manual_sources.append(batch_report)
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

    capability_matrix_command = [
        sys.executable,
        "scripts/summarize_native_agent_capabilities.py",
    ]
    for source in manual_sources:
        capability_matrix_command.append(str(source.relative_to(ROOT)))
    capability_matrix_command.extend(
        [
            "--output-json",
            str(native_capability_matrix_report.relative_to(ROOT)),
        ]
    )
    capability_matrix_code = _run(capability_matrix_command, allow_failure=True)
    if capability_matrix_code and not native_capability_matrix_report.exists():
        raise subprocess.CalledProcessError(
            capability_matrix_code,
            capability_matrix_command,
        )

    release_readiness_command = [
        sys.executable,
        "scripts/summarize_release_readiness.py",
    ]
    for source in manual_sources:
        release_readiness_command.append(str(source.relative_to(ROOT)))
    release_readiness_command.extend(
        [
            "--output-json",
            str(release_readiness_report.relative_to(ROOT)),
            "--output-markdown",
            str(release_readiness_markdown.relative_to(ROOT)),
        ]
    )
    release_readiness_code = _run(release_readiness_command, allow_failure=True)
    if release_readiness_code and not release_readiness_report.exists():
        raise subprocess.CalledProcessError(
            release_readiness_code,
            release_readiness_command,
        )

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

    for stale_release_smoke in (
        release_smoke_report,
        release_smoke_markdown,
        oha_desktop_agent_smoke_report,
        public_demo_report,
        public_demo_markdown,
    ):
        stale_release_smoke.unlink(missing_ok=True)

    public_demo_command = [
        sys.executable,
        "scripts/run_public_demo_smokes.py",
        "--output-json",
        str(public_demo_report.relative_to(ROOT)),
        "--output-markdown",
        str(public_demo_markdown.relative_to(ROOT)),
    ]
    if run_real_desktop_smokes:
        public_demo_command.append("--include-real-desktop")
    if run_provider_smoke:
        public_demo_command.append("--include-provider-workflow")
    public_demo_code = _run(public_demo_command, allow_failure=True)
    if public_demo_code and not public_demo_report.exists():
        raise subprocess.CalledProcessError(public_demo_code, public_demo_command)

    oha_desktop_agent_smoke_command = [
        sys.executable,
        "scripts/smoke_oha_desktop_agent_release.py",
        "--run-isolated-provider-smoke",
        "--report-json",
        str(oha_desktop_agent_smoke_report.relative_to(ROOT)),
    ]
    if provider_manifest is not None:
        oha_desktop_agent_smoke_command.extend(
            ["--provider-manifest", str(provider_manifest)]
        )
    oha_desktop_agent_smoke_code = _run(
        oha_desktop_agent_smoke_command,
        allow_failure=True,
    )
    if oha_desktop_agent_smoke_code and not oha_desktop_agent_smoke_report.exists():
        raise subprocess.CalledProcessError(
            oha_desktop_agent_smoke_code,
            oha_desktop_agent_smoke_command,
        )

    diagnostics_command = [
        sys.executable,
        "scripts/collect_release_diagnostics.py",
        "--label",
        label,
        "--include-app-logs",
        "--output-zip",
        str(diagnostics_bundle.relative_to(ROOT)),
    ]
    diagnostics_code = _run(diagnostics_command, allow_failure=True)
    if diagnostics_code and not diagnostics_bundle.exists():
        raise subprocess.CalledProcessError(diagnostics_code, diagnostics_command)

    release_smoke_command = [
        sys.executable,
        "scripts/summarize_release_smoke.py",
    ]
    for source in manual_sources:
        release_smoke_command.append(str(source.relative_to(ROOT)))
    if oha_desktop_agent_smoke_report.exists():
        release_smoke_command.append(str(oha_desktop_agent_smoke_report.relative_to(ROOT)))
    for source in public_demo_reports:
        release_smoke_command.append(str(_relative_or_display(source)))
    if public_demo_report.exists():
        release_smoke_command.append(str(public_demo_report.relative_to(ROOT)))
    release_smoke_command.extend(
        [
            "--diagnostics-zip",
            str(diagnostics_bundle.relative_to(ROOT)),
            "--output-json",
            str(release_smoke_report.relative_to(ROOT)),
            "--output-markdown",
            str(release_smoke_markdown.relative_to(ROOT)),
        ]
    )
    release_smoke_code = _run(release_smoke_command, allow_failure=True)
    if release_smoke_code and not release_smoke_report.exists():
        raise subprocess.CalledProcessError(
            release_smoke_code,
            release_smoke_command,
        )

    return {
        "source_capability_report": source_capability_report,
        "batch_report": batch_report,
        "screen_report": screen_report,
        "native_capability_matrix_report": native_capability_matrix_report,
        "release_readiness_report": release_readiness_report,
        "release_readiness_markdown": release_readiness_markdown,
        "diagnostics_bundle": diagnostics_bundle,
        "oha_desktop_agent_smoke_report": oha_desktop_agent_smoke_report,
        "release_smoke_report": release_smoke_report,
        "release_smoke_markdown": release_smoke_markdown,
        "public_demo_report": public_demo_report,
        "public_demo_markdown": public_demo_markdown,
        "signoff_draft": signoff_draft,
        "signoff_markdown": signoff_markdown,
        "signoff_preview": signoff_preview,
    }


def print_local_rc_signoff_status(*, short_commit: str | None = None) -> bool:
    label = short_commit or _git_short_commit()
    signoff_draft = ROOT / "tmp" / f"rc-signoff-{label}-current.json"
    if not signoff_draft.exists():
        _print_missing_current_signoff_guidance(label=label, signoff_draft=signoff_draft)
        return False

    from scripts import verify_release_candidate as rc

    automation_commands = rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS
    previous_gatekeeper_command = automation_commands.get("gatekeeper_first_launch")
    previous_screen_command = automation_commands.get("screen_recording_permission")
    automation_commands["gatekeeper_first_launch"] = _local_gatekeeper_readiness_command(
        label=label
    )
    automation_commands["screen_recording_permission"] = _local_screen_smoke_command(
        label=label
    )
    try:
        ok = rc.print_manual_release_candidate_checks_status(
            ROOT,
            signoff_draft.relative_to(ROOT),
        )
    finally:
        if previous_gatekeeper_command is None:
            automation_commands.pop("gatekeeper_first_launch", None)
        else:
            automation_commands["gatekeeper_first_launch"] = previous_gatekeeper_command
        if previous_screen_command is None:
            automation_commands.pop("screen_recording_permission", None)
        else:
            automation_commands["screen_recording_permission"] = previous_screen_command
    if ok:
        _print_release_progress_lanes(label=label, signoff_draft=signoff_draft)
        _print_release_readiness_status(label=label)
        _print_release_smoke_status(label=label)
        _print_public_demo_status(label=label)
        _print_os_evidence_command(label=label, signoff_draft=signoff_draft)
    return ok


def _print_release_progress_lanes(*, label: str, signoff_draft: Path) -> None:
    print("release progress lanes:")
    _print_public_release_gate_lane(label=label)
    _print_manual_signoff_lane(signoff_draft=signoff_draft)
    _print_opt_in_real_desktop_lane(label=label)


def _print_public_release_gate_lane(*, label: str) -> None:
    gate_report = ROOT / "tmp" / f"public-release-gate-{label}.json"
    if not gate_report.exists():
        print(
            "- automated/public release gate: evidence not found "
            f"({gate_report.relative_to(ROOT)})"
        )
        return
    try:
        report = _load_report(gate_report)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"- automated/public release gate: unreadable ({exc})")
        return
    status = str(report.get("status") or "unknown")
    release_ready = report.get("release_ready")
    progress = report.get("progress")
    automated = progress.get("automated_checks") if isinstance(progress, dict) else {}
    if not isinstance(automated, dict):
        automated = {}
    passed = automated.get("passed", report.get("passed_count"))
    total = automated.get("total", report.get("check_count"))
    code_remaining = (
        progress.get("code_remaining_percent") if isinstance(progress, dict) else None
    )
    release_remaining = (
        progress.get("release_remaining_percent") if isinstance(progress, dict) else None
    )
    ready_label = "ready" if release_ready is True else status
    details = []
    if isinstance(passed, int) and isinstance(total, int) and total:
        details.append(f"{passed}/{total} checks")
    if isinstance(code_remaining, (int, float)):
        details.append(f"code remaining {code_remaining:.1f}%")
    if isinstance(release_remaining, (int, float)):
        details.append(f"release remaining {release_remaining:.1f}%")
    suffix = f" ({', '.join(details)})" if details else ""
    print(f"- automated/public release gate: {ready_label}{suffix}")


def _print_manual_signoff_lane(*, signoff_draft: Path) -> None:
    try:
        report = _load_report(signoff_draft)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"- local manual signoff: unreadable ({exc})")
        return
    summary = report.get("manual_release_candidate_check_summary")
    if not isinstance(summary, dict):
        print("- local manual signoff: summary missing")
        return
    remaining_ids = _string_items(summary.get("remaining_check_ids"))
    check_ids = {
        str(check.get("id") or "")
        for check in _dict_items(report.get("checks"))
        if str(check.get("id") or "")
    }
    total = summary.get("total")
    if not isinstance(total, int) and check_ids:
        total = len(check_ids.union(remaining_ids))
    remaining = summary.get("remaining_count")
    if not isinstance(remaining, int) and remaining_ids:
        remaining = len(remaining_ids)
    if isinstance(total, int) and isinstance(remaining, int):
        complete = max(total - remaining, 0)
        line = f"- local manual signoff: {complete}/{total} complete"
        if remaining:
            line += f", {remaining} remaining"
        if remaining_ids:
            line += f" ({', '.join(remaining_ids)})"
        print(line)
        return
    if remaining_ids:
        print(f"- local manual signoff: remaining {', '.join(remaining_ids)}")
    else:
        print("- local manual signoff: progress unknown")


def _print_opt_in_real_desktop_lane(*, label: str) -> None:
    missing = _missing_real_desktop_capabilities(label=label)
    if missing:
        print(
            "- opt-in real desktop evidence: not collected by default "
            f"({', '.join(missing)}); isolated desktop evidence is used to avoid "
            "foreground mouse/keyboard capture"
        )
        return
    print("- opt-in real desktop evidence: collected or not required")


def _missing_real_desktop_capabilities(*, label: str) -> list[str]:
    for report_path in (
        ROOT / "tmp" / f"rc-verification-{label}-release-readiness.json",
        ROOT / "tmp" / f"rc-verification-{label}-native-capability-matrix.json",
    ):
        if not report_path.exists():
            continue
        try:
            report = _load_report(report_path)
        except (OSError, json.JSONDecodeError):
            continue
        missing = list(dict.fromkeys([
            *_string_items(report.get("missing_capability_ids")),
            *_string_items(report.get("optional_missing_capability_ids")),
            *_string_items(report.get("all_missing_capability_ids")),
        ]))
        real_desktop_missing = [
            item for item in missing if item.startswith("source_real_desktop_")
        ]
        if real_desktop_missing:
            return real_desktop_missing
    return []


def _print_release_readiness_status(*, label: str) -> None:
    readiness_report = ROOT / "tmp" / f"rc-verification-{label}-release-readiness.json"
    if not readiness_report.exists():
        return
    try:
        report = _load_report(readiness_report)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"local RC release readiness: could not read {readiness_report.relative_to(ROOT)}: {exc}",
            file=sys.stderr,
        )
        return
    print("local RC release readiness:")
    status = str(report.get("status") or "unknown")
    passed = report.get("passed_count")
    total = report.get("capability_count")
    print(f"- status: {status}")
    optional_missing_ids = report.get("optional_missing_capability_ids")
    optional_missing = (
        [str(item) for item in optional_missing_ids if str(item)]
        if isinstance(optional_missing_ids, list)
        else []
    )
    if isinstance(passed, int) and isinstance(total, int):
        if optional_missing:
            required_total = max(total - len(optional_missing), 0)
            required_passed = min(passed, required_total)
            print(f"- required capabilities: {required_passed}/{required_total} passed")
        else:
            print(f"- capabilities: {passed}/{total} passed")
    missing_ids = report.get("missing_capability_ids")
    if isinstance(missing_ids, list) and missing_ids:
        missing = ", ".join(str(item) for item in missing_ids if str(item))
        if missing:
            print(f"- missing capabilities: {missing}")
    if optional_missing:
        print(f"- optional opt-in capabilities: {', '.join(optional_missing)}")
    blockers = report.get("blockers")
    if isinstance(blockers, list):
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            blocker_type = str(blocker.get("type") or "blocker")
            blocker_id = str(blocker.get("id") or "")
            capabilities = blocker.get("capabilities")
            capability_ids = []
            if isinstance(capabilities, list):
                capability_ids = [
                    str(item.get("id") or "")
                    for item in capabilities
                    if isinstance(item, dict) and str(item.get("id") or "")
                ]
            target = ", ".join(capability_ids) if capability_ids else "unknown"
            print(f"- blocker {blocker_type}:{blocker_id}: {target}")


def _print_release_smoke_status(*, label: str) -> None:
    release_smoke_report = ROOT / "tmp" / f"rc-verification-{label}-release-smoke.json"
    if not release_smoke_report.exists():
        return
    try:
        report = _load_report(release_smoke_report)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"local RC release smoke: could not read {release_smoke_report.relative_to(ROOT)}: {exc}",
            file=sys.stderr,
        )
        return
    print("local RC release smoke:")
    status = str(report.get("status") or "unknown")
    passed = report.get("passed_count")
    total = report.get("item_count")
    print(f"- status: {status}")
    if isinstance(passed, int) and isinstance(total, int):
        print(f"- user paths: {passed}/{total} passed")
    missing_ids = report.get("missing_item_ids")
    if isinstance(missing_ids, list) and missing_ids:
        missing = ", ".join(str(item) for item in missing_ids if str(item))
        if missing:
            print(f"- missing user paths: {missing}")
    _print_release_smoke_blockers(report)
    public_demo_details = _public_demo_details_from_release_smoke(report)
    if public_demo_details:
        _print_public_demo_detail_lines(public_demo_details, prefix="public demo")


def _print_release_smoke_blockers(report: dict[str, object]) -> None:
    for item in _dict_items(report.get("items")):
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        for blocker in _dict_items(item.get("release_blockers")):
            blocker_id = str(blocker.get("id") or "")
            if not blocker_id:
                continue
            reason = str(blocker.get("reason") or "").strip()
            evidence = blocker.get("evidence_summary")
            evidence = evidence if isinstance(evidence, dict) else {}
            suffix_parts = [reason] if reason else []
            provider_contract_ok = evidence.get("provider_contract_ok")
            if isinstance(provider_contract_ok, bool):
                suffix_parts.append(
                    f"provider_contract_ok={str(provider_contract_ok).lower()}"
                )
            provider_contract_blockers = _string_items(
                evidence.get("provider_contract_blocking_conditions")
            )
            if provider_contract_blockers:
                suffix_parts.append(
                    "provider_contract_blocking_conditions="
                    + ",".join(provider_contract_blockers)
                )
            suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
            print(f"- release blocker {item_id}: {blocker_id}{suffix}")


def _print_public_demo_status(*, label: str) -> None:
    public_demo_report = ROOT / "tmp" / f"rc-verification-{label}-public-demo.json"
    if not public_demo_report.exists():
        return
    try:
        report = _load_report(public_demo_report)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"local RC public demo: could not read {public_demo_report.relative_to(ROOT)}: {exc}",
            file=sys.stderr,
        )
        return
    print("local RC public demo:")
    status = str(report.get("status") or "unknown")
    print(f"- status: {status}")
    passed = report.get("passed_count")
    selected = report.get("selected_count")
    if isinstance(passed, int) and isinstance(selected, int):
        print(f"- selected demos: {passed}/{selected} passed")
    complete = report.get("complete")
    if isinstance(complete, bool):
        print(f"- complete evidence: {str(complete).lower()}")
    release_level = str(report.get("release_level") or "")
    if release_level:
        print(f"- release level: {release_level}")
    passed_required = report.get("passed_required_flow_count")
    required = report.get("required_flow_count")
    if isinstance(passed_required, int) and isinstance(required, int) and required:
        print(f"- required demos: {passed_required}/{required} passed")
    missing_required = _string_items(report.get("missing_required_flow_ids"))
    if missing_required:
        print(f"- missing required demos: {', '.join(missing_required)}")
    _print_demo_blockers(_dict_items(report.get("release_blockers")))
    next_actions = report.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        action_ids = [
            str(action.get("id") or "")
            for action in next_actions
            if isinstance(action, dict) and str(action.get("id") or "")
        ]
        if action_ids:
            print(f"- remaining demos: {', '.join(action_ids)}")


def _public_demo_details_from_release_smoke(report: dict[str, object]) -> dict[str, object]:
    for item in _dict_items(report.get("items")):
        if item.get("id") != "public_demo":
            continue
        related = item.get("related_evidence")
        if not isinstance(related, dict):
            continue
        for evidence_id in ("public_demo_assessment", "public_demo_selected"):
            entries = _dict_items(related.get(evidence_id))
            if entries:
                return _preferred_public_demo_entry(entries)
    for action in _dict_items(report.get("next_actions")):
        if action.get("id") == "public_demo":
            return action
    return {}


def _preferred_public_demo_entry(entries: list[dict[str, object]]) -> dict[str, object]:
    for entry in entries:
        if entry.get("kind") == "public_demo_aggregate":
            return entry
    return entries[0] if entries else {}


def _print_public_demo_detail_lines(details: dict[str, object], *, prefix: str) -> None:
    release_level = str(details.get("release_level") or "")
    if release_level:
        print(f"- {prefix} level: {release_level}")
    missing_required = _string_items(details.get("missing_required_flow_ids"))
    if missing_required:
        print(f"- missing {prefix} flows: {', '.join(missing_required)}")
    _print_demo_blockers(_dict_items(details.get("release_blockers")), prefix=prefix)


def _print_demo_blockers(
    blockers: list[dict[str, object]],
    *,
    prefix: str = "demo",
) -> None:
    for blocker in blockers:
        blocker_id = str(blocker.get("id") or "")
        if not blocker_id:
            continue
        status = str(blocker.get("status") or "unknown")
        opt_in = str(blocker.get("opt_in_flag") or "")
        reason = str(blocker.get("reason") or "")
        suffix_parts = []
        if opt_in:
            suffix_parts.append(f"requires {opt_in}")
        if reason:
            suffix_parts.append(reason)
        suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
        print(f"- {prefix} blocker {blocker_id}: {status}{suffix}")


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
    placeholder_fields = []
    if gatekeeper_evidence and _is_placeholder_evidence(gatekeeper_evidence):
        placeholder_fields.append("--gatekeeper-evidence")
    if screen_recording_evidence and _is_placeholder_evidence(screen_recording_evidence):
        placeholder_fields.append("--screen-recording-evidence")
    if placeholder_fields:
        raise ValueError(
            "replace placeholder OS evidence before writing final signoff evidence: "
            + ", ".join(placeholder_fields)
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
    parser.add_argument("--skip-source-capability-smoke", action="store_true")
    parser.add_argument(
        "--run-real-desktop-smokes",
        action="store_true",
        help=(
            "Include opt-in real desktop app open, UI inspection, and interaction "
            "smokes in the source capability, packaged batch, and public-demo "
            "reports. By default, local RC refresh uses isolated desktop evidence "
            "and avoids foreground mouse/keyboard capture."
        ),
    )
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
    parser.add_argument(
        "--provider-manifest",
        type=Path,
        help=(
            "Provider manifest to pass to the isolated Oha desktop-agent product "
            "smoke during local RC signoff refresh."
        ),
    )
    parser.add_argument(
        "--public-demo-report",
        action="append",
        default=[],
        type=Path,
        help=(
            "Existing public-demo JSON to merge into the release-smoke summary. "
            "May be repeated for batched real desktop, provider, or UI evidence."
        ),
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
            skip_source_capability_smoke=args.skip_source_capability_smoke,
            run_real_desktop_smokes=args.run_real_desktop_smokes,
            run_provider_smoke=args.run_provider_smoke,
            skip_screen_smoke=args.skip_screen_smoke,
            reuse_current_reports=args.reuse_current_reports,
            provider_manifest=args.provider_manifest,
            public_demo_reports=tuple(args.public_demo_report),
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
