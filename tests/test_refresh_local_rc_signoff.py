"""Local RC signoff refresh helper tests."""

from __future__ import annotations

import json
import subprocess
import sys

from scripts import refresh_local_rc_signoff as refresh


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
            if report_path.endswith("-packaged-batch.json"):
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
    assert reports["screen_report"] == tmp_path / "tmp" / "rc-verification-abc12345-screen.json"
    assert reports["signoff_draft"] == tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    assert reports["signoff_markdown"] == tmp_path / "tmp" / "rc-signoff-abc12345-current.md"
    assert reports["signoff_preview"] == tmp_path / "tmp" / "rc-signoff-abc12345-preview.json"
    assert commands[0][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--require-artifacts",
        "--check-dmg-mount",
        "--run-dmg-app-smoke",
        "--run-dmg-ui-sampling-smoke",
        "--run-dmg-chat-native-file-smoke",
        "--report-json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
    ]
    assert commands[1] == (
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
    assert "--mark-provider-smoke-not-applicable-if-missing" in commands[2][0]
    assert commands[3] == (
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
    assert commands[4][1] is True


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
    write_report("tmp/rc-verification-abc12345-packaged-batch.json", current_source)
    write_report("tmp/rc-verification-abc12345-screen.json", current_source)

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        if "--report-json" in command:
            report_path = command[command.index("--report-json") + 1]
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
    assert len(commands) == 3
    assert commands[0][0][:5] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        "tmp/rc-verification-abc12345-packaged-batch.json",
        "--manual-checks-json",
    ]
    assert commands[1][0] == [
        sys.executable,
        "scripts/verify_release_candidate.py",
        "--manual-checks-json",
        "tmp/rc-signoff-abc12345-current.json",
        "--write-manual-checks-markdown",
        "tmp/rc-signoff-abc12345-current.md",
    ]
    assert commands[2][1] is True


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
        "--require-artifacts",
        "--check-dmg-mount",
        "--run-dmg-app-smoke",
        "--run-dmg-ui-sampling-smoke",
        "--run-dmg-chat-native-file-smoke",
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


def test_refresh_local_rc_signoff_print_status_uses_current_draft(
    monkeypatch,
    tmp_path,
    capsys,
):
    commands: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    draft = tmp_path / "tmp" / "rc-signoff-abc12345-current.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": [],
                "manual_release_candidate_check_summary": {
                    "remaining_check_ids": [
                        "gatekeeper_first_launch",
                        "screen_recording_permission",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run(command: list[str], *, allow_failure: bool = False) -> int:
        commands.append((command, allow_failure))
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    assert refresh.main(["--short-commit", "abc12345", "--print-status"]) == 0
    assert commands == [
        (
            [
                sys.executable,
                "scripts/verify_release_candidate.py",
                "--manual-checks-json",
                "tmp/rc-signoff-abc12345-current.json",
                "--print-manual-checks-status",
            ],
            True,
        )
    ]
    output = capsys.readouterr().out
    assert "local RC OS evidence command:" in output
    assert "--write-os-evidence tmp/rc-signoff-abc12345-os-evidence.json" in output
    assert "--gatekeeper-evidence" in output
    assert "--screen-recording-evidence" in output


def test_refresh_local_rc_signoff_print_status_fails_when_draft_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(refresh, "ROOT", tmp_path)

    assert refresh.main(["--short-commit", "abc12345", "--print-status"]) == 1


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


def test_refresh_local_rc_signoff_requires_provider_credentials(monkeypatch):
    for name in refresh.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    assert refresh.main(["--run-provider-smoke"]) == 2
