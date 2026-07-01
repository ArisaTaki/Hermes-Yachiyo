"""Local RC signoff refresh helper tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import refresh_local_rc_signoff as refresh


def test_refresh_local_rc_signoff_build_uses_project_venv_python(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    build_calls: list[dict[str, object]] = []
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(
        refresh,
        "build_release_candidate_artifacts",
        lambda **kwargs: build_calls.append(kwargs),
    )

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh._build_release_candidate_artifacts(
        channel="experimental",
        repository="owner/repo",
    )

    assert build_calls == []
    assert commands == [
        (
            [
                str(venv_python),
                "scripts/build_release_candidate_artifacts.py",
                "--channel",
                "experimental",
                "--repository",
                "owner/repo",
            ],
            False,
        )
    ]


def test_refresh_local_rc_signoff_build_uses_venv_entrypoint_when_it_is_symlink(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    build_calls: list[dict[str, object]] = []
    base_python = tmp_path / "base" / "python"
    base_python.parent.mkdir(parents=True)
    base_python.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(base_python)
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh.sys, "executable", str(base_python))
    monkeypatch.setattr(
        refresh,
        "build_release_candidate_artifacts",
        lambda **kwargs: build_calls.append(kwargs),
    )

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh._build_release_candidate_artifacts(
        channel="experimental",
        repository=None,
    )

    assert build_calls == []
    assert commands == [
        (
            [
                str(venv_python),
                "scripts/build_release_candidate_artifacts.py",
                "--channel",
                "experimental",
            ],
            False,
        )
    ]


def test_refresh_local_rc_signoff_runs_batch_screen_draft_and_preview(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", lambda **_: None)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            if report_path.endswith("-source-capabilities.json"):
                write_report(report_path, {"ok": True})
            elif report_path.endswith("-packaged-batch.json"):
                write_report(report_path, {"ok": True})
            elif report_path.endswith("-screen.json"):
                write_report(report_path, {"ok": False})
                return 1
            elif report_path.endswith("-preview.json"):
                write_report(
                    report_path,
                    {
                        "ok": False,
                        "manual_release_candidate_check_summary": {
                            "remaining_count": 2,
                            "remaining_check_ids": [
                                "gatekeeper_first_launch",
                                "screen_recording_permission",
                            ],
                        },
                        "manual_release_candidate_check_findings": [],
                        "source_revision_final_signoff_findings": [],
                        "manual_release_candidate_check_source_revision_findings": [],
                    },
                )
                return 1
        if "--output-json" in command:
            output_path = command[command.index("--output-json") + 1]
            write_report(
                output_path,
                {
                    "ok": False,
                    "status_counts": {"passed": 18, "missing": 11},
                },
            )
            return 1
        if "--write-manual-checks-draft" in command:
            draft_path = command[command.index("--write-manual-checks-draft") + 1]
            write_report(
                draft_path,
                {
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    }
                },
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = command[command.index("--write-manual-checks-markdown") + 1]
            report_path = tmp_path / markdown_path
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("# Manual Signoff\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    reports = refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        channel="experimental",
        repository="owner/repo",
    )

    assert reports["batch_report"] == tmp_path / "tmp" / "rc-verification-abc12345-packaged-batch.json"
    assert reports["source_capability_report"] == tmp_path / "tmp" / "rc-verification-abc12345-source-capabilities.json"
    assert reports["screen_report"] == tmp_path / "tmp" / "rc-verification-abc12345-screen.json"
    assert reports["native_capability_matrix_report"] == tmp_path / "tmp" / "rc-verification-abc12345-native-capability-matrix.json"
    assert reports["release_readiness_report"] == tmp_path / "tmp" / "rc-verification-abc12345-release-readiness.json"
    assert reports["release_readiness_markdown"] == tmp_path / "tmp" / "rc-verification-abc12345-release-readiness.md"
    assert reports["diagnostics_bundle"] == tmp_path / "tmp" / "oha-yachiyo-diagnostics-abc12345.zip"
    assert reports["release_smoke_report"] == tmp_path / "tmp" / "rc-verification-abc12345-release-smoke.json"
    assert reports["release_smoke_markdown"] == tmp_path / "tmp" / "rc-verification-abc12345-release-smoke.md"
    assert reports["public_demo_report"] == tmp_path / "tmp" / "rc-verification-abc12345-public-demo.json"
    assert reports["public_demo_markdown"] == tmp_path / "tmp" / "rc-verification-abc12345-public-demo.md"
    assert reports["signoff_draft"] == tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    assert reports["signoff_markdown"] == tmp_path / "tmp" / "rc-signoff-abc12345-current.md"
    assert reports["signoff_preview"] == tmp_path / "tmp" / "rc-signoff-abc12345-preview.json"
    assert commands[0][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--source-only",
        "--report-json",
        "tmp/rc-verification-abc12345-source-capabilities.json",
    ]
    assert commands[1][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--run-full-local-native-agent-rc",
        "--report-json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
    ]
    assert commands[2] == (
        [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--require-artifacts",
            "--run-dmg-screen-smoke",
            "--report-json",
            "tmp/rc-verification-abc12345-screen.json",
        ],
        True,
    )
    assert commands[3] == (
        [
            sys.executable,
            "scripts/summarize_native_agent_capabilities.py",
            "tmp/rc-verification-abc12345-source-capabilities.json",
            "tmp/rc-verification-abc12345-packaged-batch.json",
            "tmp/rc-verification-abc12345-screen.json",
            "--output-json",
            "tmp/rc-verification-abc12345-native-capability-matrix.json",
        ],
        True,
    )
    assert commands[4] == (
        [
            sys.executable,
            "scripts/summarize_release_readiness.py",
            "tmp/rc-verification-abc12345-source-capabilities.json",
            "tmp/rc-verification-abc12345-packaged-batch.json",
            "tmp/rc-verification-abc12345-screen.json",
            "--output-json",
            "tmp/rc-verification-abc12345-release-readiness.json",
            "--output-markdown",
            "tmp/rc-verification-abc12345-release-readiness.md",
        ],
        True,
    )
    assert "--mark-provider-smoke-not-applicable-if-missing" in commands[5][0]
    assert commands[5][0][:7] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        "tmp/rc-verification-abc12345-source-capabilities.json",
        "--manual-checks-json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
        "--manual-checks-json",
    ]
    assert commands[6] == (
        [
            sys.executable,
            "scripts/verify_release_candidate.py",
            "--manual-checks-json",
            "tmp/rc-signoff-abc12345-current.json",
            "--write-manual-checks-markdown",
            "tmp/rc-signoff-abc12345-current.md",
        ],
        False,
    )
    assert commands[7][1] is True
    assert commands[8] == (
        [
            sys.executable,
            "scripts/run_public_demo_smokes.py",
            "--output-json",
            "tmp/rc-verification-abc12345-public-demo.json",
            "--output-markdown",
            "tmp/rc-verification-abc12345-public-demo.md",
        ],
        True,
    )
    assert commands[9] == (
        [
            sys.executable,
            "scripts/collect_release_diagnostics.py",
            "--label",
            "abc12345",
            "--include-app-logs",
            "--output-zip",
            "tmp/oha-yachiyo-diagnostics-abc12345.zip",
        ],
        True,
    )
    assert commands[10] == (
        [
            sys.executable,
            "scripts/summarize_release_smoke.py",
            "tmp/rc-verification-abc12345-source-capabilities.json",
            "tmp/rc-verification-abc12345-packaged-batch.json",
            "tmp/rc-verification-abc12345-screen.json",
            "tmp/rc-verification-abc12345-public-demo.json",
            "--diagnostics-zip",
            "tmp/oha-yachiyo-diagnostics-abc12345.zip",
            "--output-json",
            "tmp/rc-verification-abc12345-release-smoke.json",
            "--output-markdown",
            "tmp/rc-verification-abc12345-release-smoke.md",
        ],
        True,
    )


def test_refresh_local_rc_signoff_rejects_non_manual_preview_failure(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", lambda **_: None)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            if report_path.endswith("-preview.json"):
                write_report(
                    report_path,
                    {
                        "ok": False,
                        "manual_release_candidate_check_summary": {
                            "remaining_count": 2,
                        },
                        "source_findings": [
                            {
                                "path": "apps/frontend",
                                "message": "unexpected legacy token",
                            }
                        ],
                    },
                )
                return 1
            write_report(report_path, {"ok": True})
        if "--write-manual-checks-draft" in command:
            write_report(
                command[command.index("--write-manual-checks-draft") + 1],
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    try:
        refresh.refresh_local_rc_signoff(short_commit="abc12345")
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 1
    else:
        raise AssertionError("non-manual preview findings must fail the refresh")


def test_refresh_local_rc_signoff_reuses_current_reports(monkeypatch, tmp_path):
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)

    def fail_build(**_: object) -> None:
        raise AssertionError("current report reuse should not rebuild artifacts")

    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", fail_build)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    current_source = {
        "ok": True,
        "source_revision": {
            "available": True,
            "commit": "abc12345deadbeef",
            "short_commit": "abc1234",
            "dirty": False,
        }
    }
    write_report("tmp/rc-verification-abc12345-source-capabilities.json", current_source)
    write_report("tmp/rc-verification-abc12345-packaged-batch.json", current_source)
    write_report("tmp/rc-verification-abc12345-screen.json", current_source)

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            assert not report_path.endswith("-source-capabilities.json")
            assert not report_path.endswith("-packaged-batch.json")
            assert not report_path.endswith("-screen.json")
        if "--write-manual-checks-draft" in command:
            draft_path = command[command.index("--write-manual-checks-draft") + 1]
            write_report(
                draft_path,
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        if "--output-json" in command:
            write_report(
                command[command.index("--output-json") + 1],
                {"ok": False, "status_counts": {"passed": 18, "missing": 11}},
            )
        if "--report-json" in command:
            write_report(
                report_path,
                {
                    "ok": False,
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    },
                    "source_revision_final_signoff_findings": [],
                    "manual_release_candidate_check_source_revision_findings": [],
                },
            )
            return 1
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    reports = refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        reuse_current_reports=True,
    )

    assert reports["batch_report"].exists()
    assert reports["screen_report"].exists()
    assert reports["native_capability_matrix_report"].exists()
    assert len(commands) == 8
    assert commands[0] == (
        [
            sys.executable,
            "scripts/summarize_native_agent_capabilities.py",
            "tmp/rc-verification-abc12345-source-capabilities.json",
            "tmp/rc-verification-abc12345-packaged-batch.json",
            "tmp/rc-verification-abc12345-screen.json",
            "--output-json",
            "tmp/rc-verification-abc12345-native-capability-matrix.json",
        ],
        True,
    )
    assert commands[1] == (
        [
            sys.executable,
            "scripts/summarize_release_readiness.py",
            "tmp/rc-verification-abc12345-source-capabilities.json",
            "tmp/rc-verification-abc12345-packaged-batch.json",
            "tmp/rc-verification-abc12345-screen.json",
            "--output-json",
            "tmp/rc-verification-abc12345-release-readiness.json",
            "--output-markdown",
            "tmp/rc-verification-abc12345-release-readiness.md",
        ],
        True,
    )
    assert commands[2][0][:5] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        "tmp/rc-verification-abc12345-source-capabilities.json",
        "--manual-checks-json",
    ]
    assert "tmp/rc-verification-abc12345-packaged-batch.json" in commands[2][0]
    assert commands[3][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        "tmp/rc-signoff-abc12345-current.json",
        "--write-manual-checks-markdown",
        "tmp/rc-signoff-abc12345-current.md",
    ]
    assert commands[4][1] is True
    assert commands[5] == (
        [
            sys.executable,
            "scripts/run_public_demo_smokes.py",
            "--output-json",
            "tmp/rc-verification-abc12345-public-demo.json",
            "--output-markdown",
            "tmp/rc-verification-abc12345-public-demo.md",
        ],
        True,
    )
    assert commands[6] == (
        [
            sys.executable,
            "scripts/collect_release_diagnostics.py",
            "--label",
            "abc12345",
            "--include-app-logs",
            "--output-zip",
            "tmp/oha-yachiyo-diagnostics-abc12345.zip",
        ],
        True,
    )
    assert commands[7][0] == [
        sys.executable,
        "scripts/summarize_release_smoke.py",
        "tmp/rc-verification-abc12345-source-capabilities.json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
        "tmp/rc-verification-abc12345-screen.json",
        "tmp/rc-verification-abc12345-public-demo.json",
        "--diagnostics-zip",
        "tmp/oha-yachiyo-diagnostics-abc12345.zip",
        "--output-json",
        "tmp/rc-verification-abc12345-release-smoke.json",
        "--output-markdown",
        "tmp/rc-verification-abc12345-release-smoke.md",
    ]
    assert commands[7][1] is True


def test_refresh_local_rc_signoff_merges_existing_public_demo_reports(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)

    def fail_build(**_: object) -> None:
        raise AssertionError("current report reuse should not rebuild artifacts")

    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", fail_build)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    current_source = {
        "ok": True,
        "source_revision": {
            "available": True,
            "commit": "abc12345deadbeef",
            "short_commit": "abc1234",
            "dirty": False,
        },
    }
    write_report("tmp/rc-verification-abc12345-source-capabilities.json", current_source)
    write_report("tmp/rc-verification-abc12345-packaged-batch.json", current_source)

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--write-manual-checks-draft" in command:
            write_report(
                command[command.index("--write-manual-checks-draft") + 1],
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        if "--output-json" in command:
            write_report(
                command[command.index("--output-json") + 1],
                {"ok": False, "status_counts": {"passed": 18, "missing": 11}},
            )
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            write_report(
                report_path,
                {
                    "ok": False,
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    },
                    "source_revision_final_signoff_findings": [],
                    "manual_release_candidate_check_source_revision_findings": [],
                },
            )
            return 1 if report_path.endswith("-preview.json") else 0
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        reuse_current_reports=True,
        skip_screen_smoke=True,
        public_demo_reports=(Path("tmp/public-demo-smokes-ui-missing.json"),),
    )

    release_smoke_command = next(
        command
        for command, _allow_failure in commands
        if command[:2] == [sys.executable, "scripts/summarize_release_smoke.py"]
    )
    assert "tmp/public-demo-smokes-ui-missing.json" in release_smoke_command
    assert "tmp/rc-verification-abc12345-public-demo.json" in release_smoke_command
    assert release_smoke_command.index("tmp/public-demo-smokes-ui-missing.json") < (
        release_smoke_command.index("tmp/rc-verification-abc12345-public-demo.json")
    )


def test_refresh_local_rc_signoff_does_not_reuse_failed_batch_report(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    build_calls: list[dict[str, object]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)

    def fake_build(**kwargs: object) -> None:
        build_calls.append(kwargs)

    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", fake_build)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    write_report(
        "tmp/rc-verification-abc12345-source-capabilities.json",
        {
            "ok": True,
            "source_revision": {
                "available": True,
                "commit": "abc12345deadbeef",
                "short_commit": "abc1234",
                "dirty": False,
            },
        },
    )
    write_report(
        "tmp/rc-verification-abc12345-packaged-batch.json",
        {
            "ok": False,
            "source_revision": {
                "available": True,
                "commit": "abc12345deadbeef",
                "short_commit": "abc1234",
                "dirty": False,
            },
        },
    )

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            write_report(
                report_path,
                {
                    "ok": False,
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    },
                    "source_revision_final_signoff_findings": [],
                    "manual_release_candidate_check_source_revision_findings": [],
                },
            )
            return 1 if report_path.endswith("-preview.json") else 0
        if "--write-manual-checks-draft" in command:
            write_report(
                command[command.index("--write-manual-checks-draft") + 1],
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        reuse_current_reports=True,
        skip_screen_smoke=True,
    )

    assert build_calls == [{"channel": "experimental", "repository": None}]
    assert commands[0][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--run-full-local-native-agent-rc",
        "--report-json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
    ]


def test_refresh_local_rc_signoff_reruns_batch_for_provider_smoke(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    build_calls: list[dict[str, object]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)

    def fake_build(**kwargs: object) -> None:
        build_calls.append(kwargs)

    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", fake_build)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    current_source = {
        "source_revision": {
            "available": True,
            "commit": "abc12345deadbeef",
            "short_commit": "abc12345",
            "dirty": False,
        }
    }
    write_report("tmp/rc-verification-abc12345-source-capabilities.json", current_source)
    write_report("tmp/rc-verification-abc12345-packaged-batch.json", current_source)

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            write_report(
                report_path,
                {
                    "ok": False,
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    },
                    "source_revision_final_signoff_findings": [],
                    "manual_release_candidate_check_source_revision_findings": [],
                },
            )
            return 1 if report_path.endswith("-preview.json") else 0
        if "--write-manual-checks-draft" in command:
            write_report(
                command[command.index("--write-manual-checks-draft") + 1],
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        reuse_current_reports=True,
        run_provider_smoke=True,
        skip_screen_smoke=True,
    )

    assert build_calls == [{"channel": "experimental", "repository": None}]
    batch_command = commands[0][0]
    assert "tmp/rc-verification-abc12345-packaged-batch.json" in batch_command
    assert "--run-provider-smoke" in batch_command
    public_demo_command = next(
        command
        for command, _allow_failure in commands
        if command[:2] == [sys.executable, "scripts/run_public_demo_smokes.py"]
    )
    assert "--include-provider-workflow" in public_demo_command


def test_refresh_local_rc_signoff_can_run_real_desktop_source_capability_smokes(
    monkeypatch,
    tmp_path,
):
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(refresh, "build_release_candidate_artifacts", lambda **_: None)

    def write_report(path: str, payload: dict[str, object]) -> None:
        report_path = tmp_path / path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
            write_report(
                report_path,
                {
                    "ok": False,
                    "manual_release_candidate_check_summary": {
                        "remaining_count": 2,
                    },
                    "source_revision_final_signoff_findings": [],
                    "manual_release_candidate_check_source_revision_findings": [],
                },
            )
            return 1 if report_path.endswith("-preview.json") else 0
        if "--write-manual-checks-draft" in command:
            write_report(
                command[command.index("--write-manual-checks-draft") + 1],
                {"manual_release_candidate_check_summary": {"remaining_count": 2}},
            )
        if "--write-manual-checks-markdown" in command:
            markdown_path = tmp_path / command[
                command.index("--write-manual-checks-markdown") + 1
            ]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text("# Manual Signoff\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    refresh.refresh_local_rc_signoff(
        short_commit="abc12345",
        skip_screen_smoke=True,
        run_real_desktop_smokes=True,
    )

    source_command = commands[0][0]
    assert source_command[:3] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--source-only",
    ]
    assert "--run-real-desktop-app-open-smoke" in source_command
    assert "--run-real-desktop-ui-inspection-smoke" in source_command
    assert "--run-real-desktop-interaction-smoke" in source_command
    assert "tmp/rc-verification-abc12345-source-capabilities.json" in source_command
    public_demo_command = next(
        command
        for command, _allow_failure in commands
        if command[:2] == [sys.executable, "scripts/run_public_demo_smokes.py"]
    )
    assert "--include-real-desktop" in public_demo_command


def test_refresh_local_rc_signoff_print_status_uses_current_draft(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "gatekeeper_first_launch",
                        "status": "manual_required",
                    },
                    {
                        "id": "packaged_bridge_isolation",
                        "status": "passed",
                        "evidence": "Packaged Bridge smoke passed.",
                    },
                    {
                        "id": "screen_recording_permission",
                        "status": "manual_required",
                    },
                    {
                        "id": "chat_native_file_upload",
                        "status": "passed",
                        "evidence": "Packaged Chat native file smoke passed.",
                    },
                    {
                        "id": "packaged_ui_sampling",
                        "status": "passed",
                        "evidence": "Packaged UI sampling smoke passed.",
                    },
                    {
                        "id": "real_provider_smoke",
                        "status": "not_applicable",
                        "evidence": "Provider smoke credentials were unavailable.",
                    },
                ],
                "manual_release_candidate_check_summary": {
                    "remaining_check_ids": [
                        "gatekeeper_first_launch",
                        "screen_recording_permission",
                        "external_integrations_smoke",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    readiness = tmp_path / "tmp" / "rc-verification-abc12345-release-readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "status": "incomplete",
                "passed_count": 26,
                "capability_count": 30,
                "missing_capability_ids": [
                    "source_real_desktop_interaction",
                    "provider_text_stream",
                ],
                "blockers": [
                    {
                        "type": "runtime_blocking_condition",
                        "id": "desktop_session_locked",
                        "capabilities": [
                            {"id": "source_real_desktop_interaction"},
                        ],
                    },
                    {
                        "type": "provider_credentials_missing",
                        "id": "oha_yachiyo_smoke_credentials",
                        "capabilities": [
                            {"id": "provider_text_stream"},
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    release_smoke = tmp_path / "tmp" / "rc-verification-abc12345-release-smoke.json"
    release_smoke.write_text(
        json.dumps(
            {
                "status": "incomplete",
                "passed_count": 6,
                "item_count": 9,
                "missing_item_ids": ["chat_desktop_task", "workflow", "public_demo"],
                "items": [
                    {
                        "id": "public_demo",
                        "status": "missing",
                        "related_evidence": {
                            "public_demo_assessment": [
                                {
                                    "release_level": "partial_demo_ready",
                                    "missing_required_flow_ids": [
                                        "real_desktop_interaction",
                                        "workflow_provider",
                                    ],
                                    "release_blockers": [
                                        {
                                            "id": "workflow_provider",
                                            "status": "skipped",
                                            "opt_in_flag": "--include-provider-workflow",
                                            "reason": "requires live provider smoke credentials",
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    public_demo = tmp_path / "tmp" / "rc-verification-abc12345-public-demo.json"
    public_demo.write_text(
        json.dumps(
            {
                "status": "partial",
                "release_level": "partial_demo_ready",
                "complete": False,
                "passed_count": 11,
                "selected_count": 11,
                "passed_required_flow_count": 11,
                "required_flow_count": 17,
                "missing_required_flow_ids": [
                    "real_desktop_interaction",
                    "workflow_provider",
                ],
                "release_blockers": [
                    {
                        "id": "real_desktop_interaction",
                        "status": "skipped",
                        "opt_in_flag": "--include-real-desktop-interaction",
                        "reason": "types and clicks in a real macOS application",
                    }
                ],
                "next_actions": [
                    {"id": "real_desktop_interaction"},
                    {"id": "workflow_provider"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert refresh.main(["--short-commit", "abc12345", "--print-status"]) == 0
    output = capsys.readouterr().out
    assert "manual release-candidate check progress: 4/7 complete, 3 remaining" in output
    assert "local RC release readiness:" in output
    assert "- capabilities: 26/30 passed" in output
    assert "source_real_desktop_interaction" in output
    assert "provider_text_stream" in output
    assert "blocker runtime_blocking_condition:desktop_session_locked" in output
    assert "blocker provider_credentials_missing:oha_yachiyo_smoke_credentials" in output
    assert "local RC release smoke:" in output
    assert "- user paths: 6/9 passed" in output
    assert "chat_desktop_task" in output
    assert "workflow" in output
    assert "public_demo" in output
    assert "- public demo level: partial_demo_ready" in output
    assert "- missing public demo flows: real_desktop_interaction, workflow_provider" in output
    assert "public demo blocker workflow_provider: skipped" in output
    assert "--include-provider-workflow" in output
    assert "local RC public demo:" in output
    assert "- status: partial" in output
    assert "- selected demos: 11/11 passed" in output
    assert "- complete evidence: false" in output
    assert "- release level: partial_demo_ready" in output
    assert "- required demos: 11/17 passed" in output
    assert "- missing required demos: real_desktop_interaction, workflow_provider" in output
    assert "demo blocker real_desktop_interaction: skipped" in output
    assert "--include-real-desktop-interaction" in output
    assert "real_desktop_interaction" in output
    assert "workflow_provider" in output
    assert (
        f"{sys.executable} scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-screen-smoke --report-json "
        "tmp/rc-verification-abc12345-screen.json"
    ) in output
    assert "tmp/rc-verification-screen.json" not in output
    assert "local RC OS evidence command:" in output
    assert "placeholder values are rejected" in output
    assert "--write-os-evidence tmp/rc-signoff-abc12345-os-evidence.json" in output
    assert "--gatekeeper-evidence" in output
    assert "--screen-recording-evidence" in output


def test_refresh_local_rc_signoff_print_status_fails_when_draft_missing(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "rc-signoff-old12345-current.json").write_text("{}", encoding="utf-8")
    (tmp / "rc-verification-old12345-release-readiness.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (tmp / "rc-verification-old12345-release-smoke.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (tmp / "rc-verification-old12345-public-demo.json").write_text(
        "{}",
        encoding="utf-8",
    )

    assert refresh.main(["--short-commit", "abc12345", "--print-status"]) == 1
    stderr = capsys.readouterr().err
    assert "local RC signoff draft not found: tmp/rc-signoff-abc12345-current.json" in stderr
    assert "latest available local RC evidence:" in stderr
    assert "latest signoff draft: tmp/rc-signoff-old12345-current.json" in stderr
    assert "latest release readiness: tmp/rc-verification-old12345-release-readiness.json" in stderr
    assert "latest release smoke: tmp/rc-verification-old12345-release-smoke.json" in stderr
    assert "latest public demo: tmp/rc-verification-old12345-public-demo.json" in stderr
    assert "refresh current local RC signoff draft:" in stderr
    assert (
        f"{sys.executable} scripts/refresh_local_rc_signoff.py "
        "--short-commit abc12345 --reuse-current-reports"
    ) in stderr
    assert (
        f"{sys.executable} scripts/refresh_local_rc_signoff.py "
        "--short-commit abc12345 --print-status"
    ) in stderr
    assert "--run-real-desktop-smokes" in stderr
    assert "--run-provider-smoke" in stderr


def test_refresh_local_rc_signoff_cli_passes_public_demo_reports(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    captured: dict[str, object] = {}

    def fake_refresh(**kwargs: object) -> dict[str, Path]:
        captured.update(kwargs)
        report_path = tmp_path / "tmp" / "rc-verification-abc12345-release-smoke.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        return {"release_smoke_report": report_path}

    monkeypatch.setattr(refresh, "refresh_local_rc_signoff", fake_refresh)

    assert refresh.main(
        [
            "--short-commit",
            "abc12345",
            "--public-demo-report",
            "tmp/public-demo-smokes-real-desktop-missing.json",
            "--public-demo-report",
            "tmp/public-demo-smokes-ui-missing.json",
        ]
    ) == 0

    assert captured["public_demo_reports"] == (
        Path("tmp/public-demo-smokes-real-desktop-missing.json"),
        Path("tmp/public-demo-smokes-ui-missing.json"),
    )
    output = capsys.readouterr().out
    assert "release_smoke_report: tmp/rc-verification-abc12345-release-smoke.json" in output


def test_refresh_local_rc_signoff_prefers_aggregate_public_demo_status():
    details = refresh._public_demo_details_from_release_smoke(
        {
            "items": [
                {
                    "id": "public_demo",
                    "related_evidence": {
                        "public_demo_assessment": [
                            {
                                "kind": "public_demo_assessment",
                                "release_level": "partial_demo_ready",
                                "missing_required_flow_ids": [
                                    "real_desktop_app_open",
                                    "studio_replay_ui",
                                ],
                            },
                            {
                                "kind": "public_demo_aggregate",
                                "release_level": "blocked",
                                "missing_required_flow_ids": [
                                    "real_desktop_ui_inspection",
                                    "workflow_provider",
                                ],
                            },
                        ]
                    },
                }
            ]
        }
    )

    assert details["kind"] == "public_demo_aggregate"
    assert details["release_level"] == "blocked"
    assert details["missing_required_flow_ids"] == [
        "real_desktop_ui_inspection",
        "workflow_provider",
    ]


def test_refresh_local_rc_signoff_prints_os_signoff_guide(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_summary": {
                    "remaining_check_ids": [
                        "gatekeeper_first_launch",
                        "screen_recording_permission",
                        "external_integrations_smoke",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    screen_report = tmp_path / "tmp" / "rc-verification-abc12345-screen.json"
    screen_report.write_text(
        json.dumps(
            {
                "dmg_screen_probe": {
                    "app_launch_paths": [
                        {
                            "dmg_path": "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
                            "app_path": (
                                "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
                                "Oha-Yachiyo.app"
                            ),
                            "backend_path": (
                                "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
                                "Oha-Yachiyo.app/Contents/Resources/backend/"
                                "oha-yachiyo-backend"
                            ),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert (
        refresh.main(["--short-commit", "abc12345", "--print-os-signoff-guide"])
        == 0
    )

    output = capsys.readouterr().out
    assert "local RC OS signoff guide:" in output
    assert "signoff draft: tmp/rc-signoff-abc12345-current.json" in output
    assert "Finder Control-click -> Open" in output
    assert "--check-gatekeeper-readiness" in output
    assert "tmp/rc-verification-abc12345-gatekeeper-readiness.json" in output
    assert (
        "stable Screen Recording app path: "
        "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app"
    ) in output
    assert (
        "stable Screen Recording backend path: "
        "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
        "Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend"
    ) in output
    assert (
        'open -R "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app"'
        in output
    )
    assert (
        'open -R "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/'
        'Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend"'
        in output
    )
    assert refresh.SCREEN_RECORDING_SETTINGS_URL in output
    assert "--run-dmg-screen-smoke" in output
    assert "placeholder values are rejected" in output
    assert "--write-os-evidence tmp/rc-signoff-abc12345-os-evidence.json" in output
    assert (
        "non-OS checks still required before final signoff: external_integrations_smoke"
        in output
    )
    assert "python scripts/smoke_external_integrations.py" in output
    assert "--bridge-only --report-json tmp/external-integrations-bridge-preflight.json" in output
    assert "--report-json tmp/external-integrations-smoke.json" in output
    assert "--manual-checks-json tmp/rc-signoff-abc12345-current.json" in output
    assert "--manual-checks-json tmp/rc-signoff-abc12345-os-evidence.json" in output
    assert "--manual-checks-json tmp/external-integrations-smoke.json" in output
    assert "--require-manual-checks-complete" in output


def test_refresh_local_rc_signoff_prints_external_only_final_command(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_summary": {
                    "remaining_check_ids": ["external_integrations_smoke"]
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        refresh.main(["--short-commit", "abc12345", "--print-os-signoff-guide"])
        == 0
    )

    output = capsys.readouterr().out
    assert "non-OS checks still required before final signoff: external_integrations_smoke" in output
    assert "python scripts/smoke_external_integrations.py" in output
    assert "--bridge-only --report-json tmp/external-integrations-bridge-preflight.json" in output
    assert "--manual-checks-json tmp/rc-signoff-abc12345-current.json" in output
    assert "--manual-checks-json tmp/external-integrations-smoke.json" in output
    assert "--manual-checks-json tmp/rc-signoff-abc12345-os-evidence.json" not in output


def test_refresh_local_rc_signoff_writes_os_evidence_with_source_revisions(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    source_revisions = [
        {
            "source": "tmp/rc-verification-abc12345-packaged-batch.json",
            "available": True,
            "commit": "abc12345deadbeef",
            "short_commit": "abc1234",
            "dirty": False,
        }
    ]
    draft.write_text(
        json.dumps(
            {
                "checks": [],
                "manual_release_candidate_check_source_revisions": source_revisions,
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "tmp" / "rc-signoff-abc12345-os-evidence.json"

    assert (
        refresh.main(
            [
                "--short-commit",
                "abc12345",
                "--write-os-evidence",
                "tmp/rc-signoff-abc12345-os-evidence.json",
                "--gatekeeper-evidence",
                "Mounted dist/electron/Oha-Yachiyo.dmg and opened the app via Finder Control-click -> Open.",
                "--screen-recording-evidence",
                "Granted Screen Recording to tmp/rc-screen-smoke/Oha-Yachiyo.app and reran /screen/current successfully.",
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["gatekeeper_first_launch"]["status"] == "passed"
    assert "Control-click" in checks["gatekeeper_first_launch"]["evidence"]
    assert checks["screen_recording_permission"]["status"] == "passed"
    assert "Screen Recording" in checks["screen_recording_permission"]["evidence"]
    assert payload["manual_release_candidate_checks_source"] == (
        "tmp/rc-signoff-abc12345-current.json"
    )
    assert payload["manual_release_candidate_check_source_revisions"] == source_revisions
    stdout = capsys.readouterr().out
    assert "local RC OS evidence: tmp/rc-signoff-abc12345-os-evidence.json" in stdout
    assert "--manual-checks-json tmp/rc-signoff-abc12345-current.json" in stdout
    assert "--manual-checks-json tmp/rc-signoff-abc12345-os-evidence.json" in stdout


def test_refresh_local_rc_signoff_rejects_empty_os_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_source_revisions": [
                    {
                        "source": "tmp/rc-verification-abc12345-packaged-batch.json",
                        "available": True,
                        "commit": "abc12345deadbeef",
                        "short_commit": "abc1234",
                        "dirty": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        refresh.main(
            [
                "--short-commit",
                "abc12345",
                "--write-os-evidence",
                "tmp/rc-signoff-abc12345-os-evidence.json",
            ]
        )
        == 1
    )
    assert not (tmp_path / "tmp" / "rc-signoff-abc12345-os-evidence.json").exists()


def test_refresh_local_rc_signoff_rejects_placeholder_os_evidence(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_source_revisions": [
                    {
                        "source": "tmp/rc-verification-abc12345-packaged-batch.json",
                        "available": True,
                        "commit": "abc12345deadbeef",
                        "short_commit": "abc1234",
                        "dirty": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        refresh.main(
            [
                "--short-commit",
                "abc12345",
                "--write-os-evidence",
                "tmp/rc-signoff-abc12345-os-evidence.json",
                "--gatekeeper-evidence",
                "<record Gatekeeper/Finder first-launch evidence>",
                "--screen-recording-evidence",
                "<record Screen Recording evidence after rerunning --run-dmg-screen-smoke or a manual screenshot/proactive probe>",
            ]
        )
        == 1
    )

    assert not (tmp_path / "tmp" / "rc-signoff-abc12345-os-evidence.json").exists()
    stderr = capsys.readouterr().err
    assert "replace placeholder OS evidence" in stderr
    assert "--gatekeeper-evidence" in stderr
    assert "--screen-recording-evidence" in stderr


def test_refresh_local_rc_signoff_requires_provider_credentials(monkeypatch):
    for name in refresh.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    assert refresh.main(["--run-provider-smoke"]) == 2
