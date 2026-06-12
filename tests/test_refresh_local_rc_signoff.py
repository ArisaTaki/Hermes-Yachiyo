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
    assert commands[3][1] is True


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
        return 0

    monkeypatch.setattr(refresh, "_run", fake_run)

    try:
        refresh.refresh_local_rc_signoff(short_commit="abc12345")
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 1
    else:
        raise AssertionError("non-manual preview findings must fail the refresh")


def test_refresh_local_rc_signoff_requires_provider_credentials(monkeypatch):
    for name in refresh.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    assert refresh.main(["--run-provider-smoke"]) == 2
