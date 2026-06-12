"""Release-candidate verification entrypoint tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import verify_release_candidate as rc


def test_release_candidate_verifier_runs_source_and_artifact_guards(tmp_path, monkeypatch, capsys):
    (tmp_path / "release").mkdir()
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    assert rc.verify_release_candidate(root=tmp_path) == 0

    assert calls == [
        {"root": tmp_path},
        {
            "root": tmp_path,
            "paths": (Path("release"),),
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
    ]
    output = capsys.readouterr().out
    assert "source release guards: passed" in output
    assert "built artifact guards: passed" in output
    assert "manual release-candidate checks:" in output
    assert "[gatekeeper_first_launch]" in output
    assert "[screen_recording_permission]" in output


def test_release_candidate_verifier_source_only_skips_existing_artifacts(tmp_path, monkeypatch, capsys):
    (tmp_path / "dist" / "electron").mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    assert calls == [{"root": tmp_path}]
    output = capsys.readouterr().out
    assert "source release guards: passed" in output
    assert "built artifact guards: skipped by --source-only" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_release_guards"]["status"] == "passed"
    assert report["built_artifact_guards"] == {
        "status": "skipped",
        "artifact_paths": [],
        "findings": [],
    }


def test_release_candidate_verifier_source_only_rejects_require_artifacts(tmp_path, monkeypatch, capsys):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        require_artifacts=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --require-artifacts" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_artifact_paths(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        artifact_paths=(Path("release"),),
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with artifact paths" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_ui_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    def fail_run(*_args, **_kwargs):
        raise AssertionError("source-only must not run UI smoke")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_ui_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-ui-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_dmg_mount(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        check_dmg_mount=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --check-dmg-mount" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"


def test_release_candidate_verifier_source_only_rejects_dmg_app_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_dmg_app_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-dmg-app-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["dmg_app_smoke"]["status"] == "skipped"


def test_release_candidate_verifier_source_only_rejects_provider_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_provider_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-provider-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["provider_smoke"]["status"] == "skipped"


def test_release_candidate_verifier_source_only_rejects_dmg_ui_sampling_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_dmg_ui_sampling_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-dmg-ui-sampling-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["dmg_ui_sampling_smoke"]["status"] == "skipped"


def test_release_candidate_verifier_writes_report_json(tmp_path, monkeypatch):
    (tmp_path / "release").mkdir()

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("release/rc-verification.json"),
    ) == 0

    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_release_guards"]["status"] == "passed"
    assert report["built_artifact_guards"]["status"] == "passed"
    assert report["built_artifact_guards"]["artifact_paths"] == ["release"]
    assert report["dmg_mount_guards"]["status"] == "skipped"
    assert report["dmg_app_smoke"]["status"] == "skipped"
    assert report["dmg_ui_sampling_smoke"]["status"] == "skipped"
    assert report["provider_smoke"]["status"] == "skipped"
    assert report["electron_ui_smoke"]["status"] == "skipped"
    assert report["manual_release_candidate_check_status"] == "manual_required"
    assert report["manual_release_candidate_checks"] == list(rc.MANUAL_RELEASE_CANDIDATE_CHECKS)
    assert report["manual_release_candidate_check_statuses"] == list(
        rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
    )
    assert [check["id"] for check in report["manual_release_candidate_check_statuses"]] == [
        "gatekeeper_first_launch",
        "packaged_bridge_isolation",
        "screen_recording_permission",
        "chat_native_file_upload",
        "packaged_ui_sampling",
        "real_provider_smoke",
    ]
    assert all(
        check["status"] == "manual_required"
        for check in report["manual_release_candidate_check_statuses"]
    )
    assert all(
        check["required_before"] == "public_release_signoff"
        for check in report["manual_release_candidate_check_statuses"]
    )
    assert report["manual_release_candidate_check_summary"] == {
        "total": 6,
        "status_counts": {
            "manual_required": 6,
            "passed": 0,
            "failed": 0,
            "not_applicable": 0,
        },
        "remaining_count": 6,
        "remaining_check_ids": [
            "gatekeeper_first_launch",
            "packaged_bridge_isolation",
            "screen_recording_permission",
            "chat_native_file_upload",
            "packaged_ui_sampling",
            "real_provider_smoke",
        ],
        "remaining_next_actions": [
            {"id": check["id"], "next_action": check["next_action"]}
            for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
        ],
        "failed_check_ids": [],
        "automated_evidence_check_ids": [],
    }


def test_release_candidate_verifier_merges_manual_check_evidence(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "release").mkdir()
    evidence_path = tmp_path / "tmp" / "manual-checks.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "gatekeeper_first_launch",
                        "status": "passed",
                        "evidence": "Finder Control-click -> Open reached the app.",
                    },
                    {
                        "id": "packaged_bridge_isolation",
                        "status": "passed",
                        "evidence": "Packaged /status returned service=oha-yachiyo on 127.0.0.1.",
                    },
                    {
                        "id": "screen_recording_permission",
                        "status": "passed",
                        "evidence": "System Settings allowed Oha-Yachiyo and screenshot probe succeeded.",
                    },
                    {
                        "id": "chat_native_file_upload",
                        "status": "passed",
                        "evidence": "Native file picker selected sample.png, preview/send/viewer/Run Detail passed.",
                    },
                    {
                        "id": "packaged_ui_sampling",
                        "status": "passed",
                        "evidence": "Sampled Chat approval/cancel, Run Detail, Workflow, Agent Studio, TTS, and Live2D.",
                    },
                    {
                        "id": "real_provider_smoke",
                        "status": "not_applicable",
                        "evidence": "Provider credentials unavailable for this local RC pass.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/manual-checks.json"),
        report_json=Path("tmp/rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["manual_release_candidate_check_findings"] == []
    assert report["manual_release_candidate_checks_source"] == "tmp/manual-checks.json"
    statuses = {
        check["id"]: check["status"]
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses == {
        "gatekeeper_first_launch": "passed",
        "packaged_bridge_isolation": "passed",
        "screen_recording_permission": "passed",
        "chat_native_file_upload": "passed",
        "packaged_ui_sampling": "passed",
        "real_provider_smoke": "not_applicable",
    }
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    assert report["manual_release_candidate_check_summary"]["remaining_check_ids"] == []
    assert report["manual_release_candidate_check_summary"]["remaining_next_actions"] == []


def test_release_candidate_verifier_accepts_previous_rc_report_manual_statuses(
    tmp_path, monkeypatch, capsys
):
    prior_report_path = tmp_path / "tmp" / "prior-rc-report.json"
    prior_report_path.parent.mkdir()
    prior_statuses = []
    for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS:
        status = "passed"
        evidence = f"{check['id']} passed in previous RC report."
        payload = {
            **check,
            "status": status,
            "evidence": evidence,
        }
        if check["id"] == "packaged_bridge_isolation":
            payload["evidence_source"] = "automated_rc_gate"
            payload["evidence"] = "Automated --run-dmg-app-smoke passed in previous RC report."
        prior_statuses.append(payload)
    prior_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "manual_release_candidate_check_statuses": prior_statuses,
                "manual_release_candidate_check_summary": {
                    "remaining_count": 0,
                    "remaining_check_ids": [],
                    "automated_evidence_check_ids": ["packaged_bridge_isolation"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/prior-rc-report.json"),
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "manual release-candidate check summary: complete" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation"
    ]
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"


def test_release_candidate_verifier_merges_multiple_manual_check_json_sources(
    tmp_path,
    monkeypatch,
):
    auto_statuses = rc._manual_release_candidate_check_report()
    for check in auto_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"
    auto_report_path = tmp_path / "tmp" / "auto-rc.json"
    auto_report_path.parent.mkdir(parents=True)
    auto_report_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": auto_statuses,
                "electron_ui_smoke": {
                    "status": "passed",
                    "script_count": 2,
                    "scripts": [
                        {
                            "script": "scripts/smoke_chat_image_attachment_ui.mjs",
                            "exit_code": 0,
                        },
                        {
                            "script": "scripts/smoke_workflow_save_run_ui.mjs",
                            "exit_code": 0,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    manual_path = tmp_path / "tmp" / "manual-checks.json"
    manual_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "gatekeeper_first_launch",
                        "status": "passed",
                        "evidence": "Gatekeeper first launch reached the packaged app.",
                    },
                    {
                        "id": "screen_recording_permission",
                        "status": "passed",
                        "evidence": "Screen Recording permission granted and screenshot probe passed.",
                    },
                    {
                        "id": "chat_native_file_upload",
                        "status": "passed",
                        "evidence": "Packaged native file picker selected sample.png and Run Detail opened.",
                    },
                    {
                        "id": "packaged_ui_sampling",
                        "status": "passed",
                        "evidence": "Packaged Chat, Run Detail, Workflow, Agent Studio, TTS, and Live2D sampled.",
                    },
                    {
                        "id": "real_provider_smoke",
                        "status": "not_applicable",
                        "evidence": "Provider credentials unavailable for this RC.",
                        "evidence_source": "credentials_unavailable",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert (
        rc.verify_release_candidate(
            root=tmp_path,
            manual_checks_json=(Path("tmp/auto-rc.json"), Path("tmp/manual-checks.json")),
            require_manual_checks_complete=True,
            report_json=Path("tmp/rc.json"),
        )
        == 0
    )

    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert (
        report["manual_release_candidate_checks_source"]
        == "tmp/auto-rc.json, tmp/manual-checks.json"
    )
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert statuses["chat_native_file_upload"]["status"] == "passed"
    assert "desktop chooseChatImages API path" in statuses["chat_native_file_upload"]["notes"]
    assert statuses["packaged_ui_sampling"]["status"] == "passed"
    assert "scripts/smoke_workflow_save_run_ui.mjs" in statuses["packaged_ui_sampling"]["notes"]
    assert statuses["real_provider_smoke"]["status"] == "not_applicable"


def test_release_candidate_verifier_requires_complete_manual_checks_for_signoff(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: incomplete" in output
    assert "manual release-candidate next actions:" in output
    assert "[packaged_bridge_isolation] Prefer rerunning the RC gate with --run-dmg-app-smoke" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "manual_required"
    assert report["manual_release_candidate_checks_required"] is True


def test_release_candidate_verifier_accepts_complete_manual_checks_for_signoff(
    tmp_path, monkeypatch, capsys
):
    evidence_path = tmp_path / "tmp" / "manual-checks.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": check["id"],
                        "status": "passed",
                        "evidence": f"{check['id']} passed for final signoff.",
                    }
                    for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/manual-checks.json"),
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: passed" in output
    assert "manual release-candidate check evidence: incomplete" not in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["manual_release_candidate_checks_required"] is True
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    assert report["manual_release_candidate_check_summary"]["remaining_next_actions"] == []


def test_release_candidate_verifier_accepts_complete_manual_markdown_for_signoff(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    markdown_path = tmp_path / "tmp" / "manual-checks.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "\n".join(
            [
                "# Oha-Yachiyo Manual Release-Candidate Signoff",
                "",
                "## Remaining Manual Checks",
                "",
                "- [x] `gatekeeper_first_launch` - passed",
                "  - Evidence: Gatekeeper first launch reached the packaged app",
                "- [x] `packaged_bridge_isolation` - passed",
                "  - Evidence source: automated_rc_gate",
                "  - Evidence: Automated --run-dmg-app-smoke passed",
                "- [x] `screen_recording_permission` - passed",
                "  - Evidence: Screen Recording permission granted and screenshot probe passed",
                "- [x] `chat_native_file_upload` - passed",
                "  - Evidence: Native file picker selected image and Run Detail opened",
                "- [x] `packaged_ui_sampling` - passed",
                "  - Evidence: Packaged Chat, Run Detail, Workflow, Agent Studio, TTS, and Live2D sampled",
                "- [x] `real_provider_smoke` - not_applicable",
                "  - Evidence source: credentials_unavailable",
                "  - Evidence: OHA_YACHIYO_SMOKE_* credentials unavailable",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        rc.verify_release_candidate(
            root=tmp_path,
            source_only=True,
            manual_checks_markdown=Path("tmp/manual-checks.md"),
            require_manual_checks_complete=True,
            report_json=Path("tmp/rc.json"),
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "manual release-candidate check summary: complete" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["manual_release_candidate_checks_source"] == "tmp/manual-checks.md"
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    statuses = {
        check["id"]: check for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses["real_provider_smoke"]["status"] == "not_applicable"
    assert statuses["real_provider_smoke"]["evidence_source"] == "credentials_unavailable"


def test_release_candidate_verifier_markdown_checked_items_default_to_passed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    markdown_path = tmp_path / "tmp" / "manual-checks.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "\n".join(
            [
                "# Oha-Yachiyo Manual Release-Candidate Signoff",
                "",
                "## Remaining Manual Checks",
                "",
                "- [x] `gatekeeper_first_launch`",
                "  - Evidence: Gatekeeper first launch reached the packaged app",
                "- [x] `packaged_bridge_isolation`",
                "  - Evidence source: automated_rc_gate",
                "  - Evidence: Automated --run-dmg-app-smoke passed",
                "- [x] `screen_recording_permission`",
                "  - Evidence: Screen Recording permission granted and screenshot probe passed",
                "- [x] `chat_native_file_upload`",
                "  - Evidence: Native file picker selected image and Run Detail opened",
                "- [x] `packaged_ui_sampling`",
                "  - Evidence: Packaged app mature surfaces sampled",
                "- [x] `real_provider_smoke` - not_applicable",
                "  - Evidence source: credentials_unavailable",
                "  - Evidence: OHA_YACHIYO_SMOKE_* credentials unavailable",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        rc.verify_release_candidate(
            root=tmp_path,
            source_only=True,
            manual_checks_markdown=Path("tmp/manual-checks.md"),
            require_manual_checks_complete=True,
            report_json=Path("tmp/rc.json"),
        )
        == 0
    )

    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    statuses = {
        check["id"]: check for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses["gatekeeper_first_launch"]["status"] == "passed"
    assert statuses["packaged_ui_sampling"]["status"] == "passed"
    assert statuses["real_provider_smoke"]["status"] == "not_applicable"


def test_release_candidate_verifier_fails_failed_manual_check_evidence(
    tmp_path, monkeypatch, capsys
):
    evidence_path = tmp_path / "tmp" / "manual-checks.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "screen_recording_permission",
                        "status": "failed",
                        "evidence": "macOS did not show Oha-Yachiyo in Screen Recording settings.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/manual-checks.json"),
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "[screen_recording_permission] failed" in output
    assert "manual release-candidate check evidence: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "failed"
    assert report["manual_release_candidate_check_findings"] == []


def test_release_candidate_verifier_writes_manual_check_template(tmp_path):
    template_path = rc.write_manual_release_candidate_checks_template(
        tmp_path,
        Path("tmp/manual-rc-checks.template.json"),
    )

    assert template_path == tmp_path / "tmp" / "manual-rc-checks.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert [check["id"] for check in template["checks"]] == [
        "gatekeeper_first_launch",
        "packaged_bridge_isolation",
        "screen_recording_permission",
        "chat_native_file_upload",
        "packaged_ui_sampling",
        "real_provider_smoke",
    ]
    assert all(check["status"] == "manual_required" for check in template["checks"])
    assert all(check["evidence"] == "" for check in template["checks"])
    assert all(check["evidence_prompt"] for check in template["checks"])
    assert all(check["next_action"] for check in template["checks"])
    assert all(
        check["required_before"] == "public_release_signoff"
        for check in template["checks"]
    )


def test_release_candidate_verifier_writes_manual_check_draft_from_prior_report(tmp_path):
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"

    prior_report_path = tmp_path / "tmp" / "final-rc.json"
    prior_report_path.parent.mkdir(parents=True)
    prior_report_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": prior_statuses,
                "manual_release_candidate_check_summary": {
                    "remaining_count": 5,
                    "automated_evidence_check_ids": ["packaged_bridge_isolation"],
                },
                "electron_ui_smoke": {
                    "status": "passed",
                    "script_count": 3,
                    "scripts": [
                        {
                            "script": "scripts/smoke_chat_image_attachment_ui.mjs",
                            "exit_code": 0,
                        },
                        {
                            "script": "scripts/smoke_chat_approval_ui.mjs",
                            "exit_code": 0,
                        },
                        {
                            "script": "scripts/smoke_workflow_save_run_ui.mjs",
                            "exit_code": 0,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    draft_path = rc.write_manual_release_candidate_checks_draft(
        tmp_path,
        Path("tmp/final-rc-signoff.json"),
        Path("tmp/final-rc.json"),
    )

    assert draft_path == tmp_path / "tmp" / "final-rc-signoff.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["manual_release_candidate_checks_source"] == "tmp/final-rc.json"
    assert draft["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert draft["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation"
    ]
    checks = {check["id"]: check for check in draft["checks"]}
    assert checks["gatekeeper_first_launch"]["status"] == "manual_required"
    assert checks["gatekeeper_first_launch"]["evidence"] == ""
    assert checks["gatekeeper_first_launch"]["evidence_prompt"]
    assert checks["gatekeeper_first_launch"]["next_action"]
    assert checks["packaged_bridge_isolation"]["status"] == "passed"
    assert checks["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert "--run-dmg-app-smoke passed" in checks["packaged_bridge_isolation"]["evidence"]
    assert checks["packaged_ui_sampling"]["status"] == "manual_required"
    assert "--run-ui-smoke passed 3 Electron UI smoke scripts" in checks["packaged_ui_sampling"]["notes"]
    assert "scripts/smoke_workflow_save_run_ui.mjs" in checks["packaged_ui_sampling"]["notes"]
    assert checks["chat_native_file_upload"]["status"] == "manual_required"
    assert "desktop chooseChatImages API path" in checks[
        "chat_native_file_upload"
    ]["notes"]
    assert "packaged OS file picker still requires manual evidence" in checks[
        "chat_native_file_upload"
    ]["notes"]


def test_release_candidate_verifier_draft_merges_standalone_electron_ui_smoke_report(
    tmp_path,
):
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"

    prior_report_path = tmp_path / "release" / "rc-verification.json"
    smoke_report_path = tmp_path / "release" / "electron-ui-smoke.json"
    prior_report_path.parent.mkdir(parents=True)
    prior_report_path.write_text(
        json.dumps({"manual_release_candidate_check_statuses": prior_statuses}),
        encoding="utf-8",
    )
    smoke_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "script_count": 2,
                "scripts": [
                    {
                        "script": "scripts/smoke_chat_image_attachment_ui.mjs",
                        "exit_code": 0,
                    },
                    {
                        "script": "scripts/smoke_workflow_save_run_ui.mjs",
                        "exit_code": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    draft_path = rc.write_manual_release_candidate_checks_draft(
        tmp_path,
        Path("release/manual-rc-checks.draft.json"),
        (
            Path("release/rc-verification.json"),
            Path("release/electron-ui-smoke.json"),
        ),
    )

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert (
        draft["manual_release_candidate_checks_source"]
        == "release/rc-verification.json, release/electron-ui-smoke.json"
    )
    checks = {check["id"]: check for check in draft["checks"]}
    assert checks["packaged_ui_sampling"]["status"] == "manual_required"
    assert "--run-ui-smoke passed 2 Electron UI smoke scripts" in checks[
        "packaged_ui_sampling"
    ]["notes"]
    assert "scripts/smoke_workflow_save_run_ui.mjs" in checks[
        "packaged_ui_sampling"
    ]["notes"]
    assert "desktop chooseChatImages API path" in checks[
        "chat_native_file_upload"
    ]["notes"]


def test_release_candidate_verifier_manual_check_draft_can_mark_provider_not_applicable(
    tmp_path,
    monkeypatch,
):
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"

    prior_report_path = tmp_path / "tmp" / "final-rc.json"
    prior_report_path.parent.mkdir(parents=True)
    prior_report_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": prior_statuses,
                "electron_ui_smoke": {
                    "status": "passed",
                    "script_count": 2,
                    "scripts": [
                        {
                            "script": "scripts/smoke_chat_image_attachment_ui.mjs",
                            "exit_code": 0,
                        },
                        {
                            "script": "scripts/smoke_workflow_management_ui.mjs",
                            "exit_code": 0,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    draft_path = rc.write_manual_release_candidate_checks_draft(
        tmp_path,
        Path("tmp/final-rc-signoff.json"),
        Path("tmp/final-rc.json"),
        mark_provider_smoke_not_applicable_if_missing=True,
    )

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["manual_release_candidate_check_summary"]["remaining_count"] == 4
    assert draft["manual_release_candidate_check_summary"]["remaining_check_ids"] == [
        "gatekeeper_first_launch",
        "screen_recording_permission",
        "chat_native_file_upload",
        "packaged_ui_sampling",
    ]
    checks = {check["id"]: check for check in draft["checks"]}
    assert checks["real_provider_smoke"]["status"] == "not_applicable"
    assert checks["real_provider_smoke"]["evidence_source"] == "credentials_unavailable"
    assert "missing environment variables" in checks["real_provider_smoke"]["evidence"]
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        assert env_name in checks["real_provider_smoke"]["evidence"]
    assert checks["packaged_bridge_isolation"]["status"] == "passed"
    assert checks["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"

    loaded_checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        Path("tmp/final-rc-signoff.json"),
    )
    assert findings == []
    loaded = {check["id"]: check for check in loaded_checks}
    assert loaded["real_provider_smoke"]["status"] == "not_applicable"
    assert loaded["real_provider_smoke"]["evidence_source"] == "credentials_unavailable"


def test_release_candidate_verifier_manual_check_write_actions_print_remaining_summary(
    tmp_path,
    monkeypatch,
    capsys,
):
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(rc, "PROJECT_ROOT", tmp_path)
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"

    prior_report_path = tmp_path / "tmp" / "final-rc.json"
    prior_report_path.parent.mkdir(parents=True)
    prior_report_path.write_text(
        json.dumps({"manual_release_candidate_check_statuses": prior_statuses}),
        encoding="utf-8",
    )

    assert (
        rc.main(
            [
                "--manual-checks-json",
                "tmp/final-rc.json",
                "--write-manual-checks-draft",
                "tmp/final-rc-signoff.json",
                "--mark-provider-smoke-not-applicable-if-missing",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "manual release-candidate checks draft: tmp/final-rc-signoff.json" in output
    assert "manual release-candidate check progress: 2/6 complete, 4 remaining" in output
    assert (
        "manual release-candidate check summary: 4 remaining "
        "(gatekeeper_first_launch, screen_recording_permission, "
        "chat_native_file_upload, packaged_ui_sampling)"
    ) in output
    assert "- [screen_recording_permission] Prefer rerunning the RC gate with --run-dmg-screen-smoke" in output

    assert (
        rc.main(
            [
                "--manual-checks-json",
                "tmp/final-rc-signoff.json",
                "--write-manual-checks-markdown",
                "tmp/final-rc-signoff.md",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "manual release-candidate checks markdown: tmp/final-rc-signoff.md" in output
    assert "manual release-candidate check progress: 2/6 complete, 4 remaining" in output
    assert "manual release-candidate next actions:" in output


def test_release_candidate_verifier_manual_check_markdown_can_mark_provider_not_applicable(
    tmp_path,
    monkeypatch,
):
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"

    prior_report_path = tmp_path / "tmp" / "final-rc.json"
    prior_report_path.parent.mkdir(parents=True)
    prior_report_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": prior_statuses,
                "electron_ui_smoke": {
                    "status": "passed",
                    "script_count": 2,
                    "scripts": [
                        {
                            "script": "scripts/smoke_chat_image_attachment_ui.mjs",
                            "exit_code": 0,
                        },
                        {
                            "script": "scripts/smoke_workflow_management_ui.mjs",
                            "exit_code": 0,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    markdown_path = rc.write_manual_release_candidate_checks_markdown(
        tmp_path,
        Path("tmp/final-rc-signoff.md"),
        Path("tmp/final-rc.json"),
        mark_provider_smoke_not_applicable_if_missing=True,
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "- Remaining checks: 4" in markdown
    assert "- [x] `real_provider_smoke` - not_applicable" in markdown
    assert "Evidence source: credentials_unavailable" in markdown
    assert "--run-ui-smoke passed 2 Electron UI smoke scripts" in markdown
    assert "scripts/smoke_workflow_management_ui.mjs" in markdown
    assert "desktop chooseChatImages API path" in markdown
    assert "packaged OS file picker still requires manual evidence" in markdown
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        assert env_name in markdown


def test_release_candidate_verifier_writes_manual_check_markdown_from_draft(tmp_path):
    draft_checks = rc._manual_release_candidate_check_report()
    for check in draft_checks:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-app-smoke passed for release/Oha-Yachiyo.dmg"
            check["evidence_source"] = "automated_rc_gate"
        if check["id"] == "real_provider_smoke":
            check["status"] = "not_applicable"
            check["evidence"] = "missing environment variables: OHA_YACHIYO_SMOKE_API_KEY"
            check["evidence_source"] = "credentials_unavailable"

    draft_path = tmp_path / "tmp" / "final-rc-signoff.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(
        json.dumps({"checks": draft_checks}),
        encoding="utf-8",
    )

    markdown_path = rc.write_manual_release_candidate_checks_markdown(
        tmp_path,
        Path("tmp/final-rc-signoff.md"),
        Path("tmp/final-rc-signoff.json"),
    )

    assert markdown_path == tmp_path / "tmp" / "final-rc-signoff.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown.startswith("# Oha-Yachiyo Manual Release-Candidate Signoff\n")
    assert "- Source: `tmp/final-rc-signoff.json`" in markdown
    assert "- Remaining checks: 4" in markdown
    assert "## How To Fill" in markdown
    assert "omitted status defaults to `passed`" in markdown
    assert "Every `passed`, `failed`, or `not_applicable` item needs non-empty `Evidence:`" in markdown
    assert "## Final Gate" in markdown
    assert "--manual-checks-markdown tmp/final-rc-signoff.md" in markdown
    assert "--require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json" in markdown
    assert "## Remaining Manual Checks" in markdown
    assert "- [ ] `gatekeeper_first_launch`" in markdown
    assert "Evidence to record:" in markdown
    assert "## Completed Or Not Applicable Checks" in markdown
    assert "- [x] `packaged_bridge_isolation` - passed" in markdown
    assert "Evidence source: automated_rc_gate" in markdown
    assert "- [x] `real_provider_smoke` - not_applicable" in markdown
    assert "Evidence source: credentials_unavailable" in markdown


def test_release_candidate_verifier_rejects_manual_check_template_outside_root(tmp_path):
    outside = tmp_path.parent / "manual-rc-checks.template.json"

    try:
        rc.write_manual_release_candidate_checks_template(tmp_path, outside)
    except ValueError as exc:
        assert "manual release-candidate checks template path must stay inside project root" in str(exc)
    else:
        raise AssertionError("manual check template path outside root must fail")
    assert not outside.exists()


def test_release_candidate_verifier_rejects_manual_check_draft_outside_root(tmp_path):
    outside = tmp_path.parent / "manual-rc-checks.draft.json"

    try:
        rc.write_manual_release_candidate_checks_draft(tmp_path, outside)
    except ValueError as exc:
        assert "manual release-candidate checks draft path must stay inside project root" in str(exc)
    else:
        raise AssertionError("manual check draft path outside root must fail")
    assert not outside.exists()


def test_release_candidate_verifier_rejects_template_and_draft_cli_conflict(capsys):
    assert (
        rc.main(
            [
                "--write-manual-checks-template",
                "tmp/template.json",
                "--write-manual-checks-draft",
                "tmp/draft.json",
            ]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert (
        "choose only one of --write-manual-checks-template, --write-manual-checks-draft, "
        "or --write-manual-checks-markdown"
    ) in output


def test_release_candidate_verifier_rejects_json_and_markdown_input_conflict(capsys):
    assert (
        rc.main(
            [
                "--manual-checks-json",
                "tmp/manual-checks.json",
                "--manual-checks-markdown",
                "tmp/manual-checks.md",
            ]
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "choose either --manual-checks-json or --manual-checks-markdown" in output


def test_release_candidate_verifier_report_can_mark_provider_not_applicable_without_credentials(
    tmp_path,
    monkeypatch,
):
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    checks = rc._manual_release_candidate_check_report()
    for check in checks:
        if check["id"] == "real_provider_smoke":
            continue
        check["status"] = "passed"
        check["evidence"] = f"{check['id']} release signoff evidence"
    checks_path = tmp_path / "tmp" / "manual-checks.json"
    checks_path.parent.mkdir(parents=True)
    checks_path.write_text(json.dumps({"checks": checks}), encoding="utf-8")

    assert (
        rc.verify_release_candidate(
            root=tmp_path,
            source_only=True,
            manual_checks_json=Path("tmp/manual-checks.json"),
            require_manual_checks_complete=True,
            mark_provider_smoke_not_applicable_if_missing=True,
            report_json=Path("tmp/rc.json"),
        )
        == 0
    )

    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses["real_provider_smoke"]["status"] == "not_applicable"
    assert statuses["real_provider_smoke"]["evidence_source"] == "credentials_unavailable"
    assert "missing environment variables" in statuses["real_provider_smoke"]["evidence"]
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        assert env_name in statuses["real_provider_smoke"]["evidence"]


def test_release_candidate_verifier_checks_mounted_dmg_app(tmp_path, monkeypatch, capsys):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg_path = release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg_path.write_bytes(b"fake dmg")
    calls: list[dict[str, object]] = []
    commands: list[list[str]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            (mount_dir / "Oha-Yachiyo.app" / "Contents" / "Resources").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        check_dmg_mount=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    mount_path = Path(commands[0][commands[0].index("-mountpoint") + 1])
    assert calls == [
        {"root": tmp_path},
        {
            "root": tmp_path,
            "paths": (Path("release"),),
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
        {
            "root": tmp_path,
            "paths": (mount_path / "Oha-Yachiyo.app" / "Contents" / "Resources",),
            "check_required_files": False,
            "check_release_security_guards": False,
            "allow_binary_targets": True,
            "check_packaged_app_bundle": True,
        },
    ]
    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["hdiutil", "detach"]
    output = capsys.readouterr().out
    assert "DMG mount guards: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_mount_guards"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "findings": [],
        "run_requested": True,
    }


def test_release_candidate_verifier_dmg_mount_fails_without_dmgs(tmp_path, monkeypatch, capsys):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        check_dmg_mount=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate DMG mount check requested but no .dmg artifacts were found" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["dmg_mount_guards"]["status"] == "failed"


def test_release_candidate_verifier_terminates_packaged_app_process_group(monkeypatch):
    signals: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 12345
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(rc.os, "getpgid", lambda pid: 45678)
    monkeypatch.setattr(rc.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    process = FakeProcess()
    rc._terminate_process(process)

    assert signals == [(45678, rc.signal.SIGTERM)]
    assert process.terminated is False


def test_release_candidate_verifier_runs_dmg_app_startup_smoke(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")
    commands: list[list[str]] = []
    popen_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,"task_counts":{},"native_agent_ready":false}'

    class FakeProcess:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(command, **kwargs):
        popen_calls.append(
            {
                "command": command,
                "cwd": kwargs.get("cwd"),
                "env": kwargs.get("env"),
                "start_new_session": kwargs.get("start_new_session"),
            }
        )
        return FakeProcess()

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: 49123)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda url, timeout: FakeResponse())

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_app_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["hdiutil", "detach"]
    assert len(popen_calls) == 1
    assert popen_calls[0]["command"][0].endswith("/Oha-Yachiyo.app/Contents/MacOS/Oha-Yachiyo")
    assert popen_calls[0]["cwd"].endswith("/Oha-Yachiyo.app")
    assert popen_calls[0]["start_new_session"] is True
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49123"
    assert env["OHA_YACHIYO_HOME"].endswith("/.oha-yachiyo")
    output = capsys.readouterr().out
    assert "DMG app startup smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_app_smoke"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert manual_statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert "--run-dmg-app-smoke passed" in manual_statuses["packaged_bridge_isolation"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation"
    ]


def test_release_candidate_verifier_runs_dmg_screen_recording_probe(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")
    commands: list[list[str]] = []
    popen_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self._body

    class FakeProcess:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(command, **kwargs):
        popen_calls.append(
            {
                "command": command,
                "cwd": kwargs.get("cwd"),
                "env": kwargs.get("env"),
                "start_new_session": kwargs.get("start_new_session"),
            }
        )
        return FakeProcess()

    def fake_urlopen(url, timeout):
        if str(url).endswith("/status"):
            return FakeResponse(
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1}'
            )
        if str(url).endswith("/screen/current"):
            return FakeResponse(
                b'{"image_base64":"private-image-bytes","format":"png","width":1920,"height":1080,"captured_at":"2026-06-12T00:00:00Z"}'
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: 49124)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc.urllib.request, "urlopen", fake_urlopen)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_screen_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["hdiutil", "detach"]
    assert len(popen_calls) == 1
    assert popen_calls[0]["start_new_session"] is True
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49124"
    output = capsys.readouterr().out
    assert "DMG screen recording probe: passed" in output
    report_text = (tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8")
    assert "private-image-bytes" not in report_text
    report = json.loads(report_text)
    assert report["ok"] is True
    assert report["dmg_screen_probe"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "screens": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "width": 1920,
                "height": 1080,
                "format": "png",
                "captured_at": "2026-06-12T00:00:00Z",
            }
        ],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert manual_statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert manual_statuses["screen_recording_permission"]["status"] == "passed"
    assert manual_statuses["screen_recording_permission"]["evidence_source"] == "automated_rc_gate"
    assert "/screen/current 1920x1080 png" in manual_statuses["screen_recording_permission"]["evidence"]
    assert "Screenshot image bytes were not archived" in manual_statuses["screen_recording_permission"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 4
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation",
        "screen_recording_permission",
    ]


def test_release_candidate_verifier_runs_dmg_ui_sampling_smoke(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")
    (tmp_path / "scripts").mkdir()
    (tmp_path / rc.DMG_UI_SAMPLING_SMOKE_SCRIPT).write_text(
        "#!/usr/bin/env node\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    popen_calls: list[dict[str, object]] = []
    ports = iter((49125, 49225))

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1}'

    class FakeProcess:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", ""

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        elif command[:2] == ["node", str(rc.DMG_UI_SAMPLING_SMOKE_SCRIPT)]:
            report_path = Path(command[command.index("--report-json") + 1])
            report_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "sample_count": 3,
                        "samples": [
                            {"id": "chat", "route": "#/chat"},
                            {"id": "workflow_studio", "route": "#/agents/workflows"},
                            {"id": "live2d_settings", "route": "#/settings/live2d"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0,
                stdout="[packaged-ui-sampling] passed 3 packaged routes\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_popen(command, **kwargs):
        popen_calls.append(
            {
                "command": command,
                "cwd": kwargs.get("cwd"),
                "env": kwargs.get("env"),
                "start_new_session": kwargs.get("start_new_session"),
            }
        )
        return FakeProcess()

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: next(ports))
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda url, timeout: FakeResponse())

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_ui_sampling_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["node", str(rc.DMG_UI_SAMPLING_SMOKE_SCRIPT)]
    assert commands[1][commands[1].index("--debug-port") + 1] == "49225"
    assert commands[2][:2] == ["hdiutil", "detach"]
    assert len(popen_calls) == 1
    assert popen_calls[0]["command"][0].endswith("/Oha-Yachiyo.app/Contents/MacOS/Oha-Yachiyo")
    assert "--remote-debugging-port=49225" in popen_calls[0]["command"]
    assert "--remote-allow-origins=*" in popen_calls[0]["command"]
    assert popen_calls[0]["start_new_session"] is True
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49125"
    output = capsys.readouterr().out
    assert "DMG packaged UI sampling smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_ui_sampling_smoke"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "samples": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "sample_count": 3,
                "routes": ["#/chat", "#/agents/workflows", "#/settings/live2d"],
            }
        ],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert manual_statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert "--run-dmg-ui-sampling-smoke passed" in manual_statuses["packaged_bridge_isolation"]["evidence"]
    assert manual_statuses["packaged_ui_sampling"]["status"] == "passed"
    assert manual_statuses["packaged_ui_sampling"]["evidence_source"] == "automated_rc_gate"
    assert "#/agents/workflows" in manual_statuses["packaged_ui_sampling"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 4
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation",
        "packaged_ui_sampling",
    ]


def test_release_candidate_dmg_app_startup_smoke_requires_executable(
    tmp_path, monkeypatch
):
    dmg_path = tmp_path / "release" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg_path.parent.mkdir()
    dmg_path.write_bytes(b"fake dmg")

    def fake_run(command, **kwargs):
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            (mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS").mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("missing executable must not be launched")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", fail_popen)

    findings = rc.verify_dmg_app_startup(tmp_path, (Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),))

    assert findings == [
        rc.Finding(
            Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),
            "mounted Oha-Yachiyo.app must contain executable Oha-Yachiyo",
        )
    ]


def test_release_candidate_verifier_runs_provider_smoke(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_MODEL", "smoke-model")
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_API_KEY", "sk-test-provider-smoke")
    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "cwd": kwargs.get("cwd"), "text": kwargs.get("text")})
        return SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_provider_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert calls == [
        {
            "command": [
                rc.sys.executable,
                str(rc.PROVIDER_SMOKE_SCRIPT),
                "--require-content",
                "--expect-finish-reason",
                "stop",
            ],
            "cwd": tmp_path,
            "text": True,
        },
        {
            "command": [
                rc.sys.executable,
                str(rc.PROVIDER_SMOKE_SCRIPT),
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
            ],
            "cwd": tmp_path,
            "text": True,
        },
    ]
    output = capsys.readouterr().out
    assert "real provider smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["provider_smoke"] == {
        "status": "passed",
        "checks": [
            {"label": "text_stream", "exit_code": 0},
            {"label": "tool_call_stream", "exit_code": 0},
        ],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["real_provider_smoke"]["status"] == "passed"
    assert manual_statuses["real_provider_smoke"]["evidence_source"] == "automated_rc_gate"
    assert "text_stream exit_code=0" in manual_statuses["real_provider_smoke"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "real_provider_smoke"
    ]


def test_release_candidate_verifier_does_not_override_failed_manual_evidence(
    tmp_path, monkeypatch, capsys
):
    evidence_path = tmp_path / "tmp" / "manual-checks.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "real_provider_smoke",
                        "status": "failed",
                        "evidence": "Credentialed provider smoke returned unexpected tool-call arguments.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_MODEL", "smoke-model")
    monkeypatch.setenv("OHA_YACHIYO_SMOKE_API_KEY", "sk-test-provider-smoke")
    monkeypatch.setattr(
        rc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr=""),
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_provider_smoke=True,
        manual_checks_json=Path("tmp/manual-checks.json"),
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "real provider smoke: passed" in output
    assert "[real_provider_smoke] failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "failed"
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["real_provider_smoke"]["status"] == "failed"
    assert manual_statuses["real_provider_smoke"]["evidence"] == (
        "Credentialed provider smoke returned unexpected tool-call arguments."
    )
    assert "evidence_source" not in manual_statuses["real_provider_smoke"]
    assert report["manual_release_candidate_check_summary"]["failed_check_ids"] == [
        "real_provider_smoke"
    ]


def test_release_candidate_verifier_provider_smoke_fails_without_credentials(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    for name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("provider smoke must not start without credentials")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_provider_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "real provider smoke: failed" in output
    assert "OHA_YACHIYO_SMOKE_BASE_URL" in output
    assert "OHA_YACHIYO_SMOKE_MODEL" in output
    assert "OHA_YACHIYO_SMOKE_API_KEY" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["provider_smoke"]["status"] == "failed"
    assert report["provider_smoke"]["checks"] == []
    assert "missing environment variables" in report["provider_smoke"]["findings"][0]["message"]


def test_release_candidate_verifier_requires_artifacts_when_requested(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(root=tmp_path, require_artifacts=True) == 1

    output = capsys.readouterr().out
    assert "release candidate artifacts not found" in output


def test_release_candidate_verifier_writes_failed_report_json(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        require_artifacts=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["built_artifact_guards"]["findings"] == [
        {
            "path": str(tmp_path),
            "message": "release candidate artifacts not found under dist/backend, dist/electron, or release",
        }
    ]


def test_release_candidate_verifier_rejects_report_json_outside_root(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("../outside-rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate report: failed" in output
    assert "release candidate report path must stay inside project root" in output
    assert not (tmp_path.parent / "outside-rc-verification.json").exists()


def test_release_candidate_verifier_reports_report_json_write_failure(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "release").mkdir()
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fail_write(_path, _report):
        raise OSError("disk full")

    monkeypatch.setattr(rc, "_write_report", fail_write)

    assert rc.verify_release_candidate(
        root=tmp_path,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "release candidate report: failed" in output
    assert "disk full" in output


def test_release_candidate_verifier_rejects_artifact_paths_outside_root(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []

    def fake_verify_release_artifacts(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(rc, "verify_release_artifacts", fake_verify_release_artifacts)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("invalid artifact paths must not be mounted")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("../outside-release"),),
        check_dmg_mount=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    assert calls == [{"root": tmp_path}]
    output = capsys.readouterr().out
    assert "built artifact guards: failed" in output
    assert "DMG mount guards: skipped because artifact paths failed validation" in output
    assert "release candidate artifact path must stay inside project root" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["built_artifact_guards"] == {
        "status": "failed",
        "artifact_paths": ["../outside-release"],
        "findings": [
            {
                "path": str(tmp_path),
                "message": "release candidate artifact path must stay inside project root: ../outside-release",
            }
        ],
    }
    assert report["dmg_mount_guards"]["status"] == "skipped"


def test_release_candidate_verifier_runs_electron_ui_smoke_scripts(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    first = scripts / "smoke_alpha_ui.mjs"
    second = scripts / "smoke_beta_ui.mjs"
    first.write_text("console.log('alpha')\n", encoding="utf-8")
    second.write_text("console.log('beta')\n", encoding="utf-8")
    commands: list[dict[str, object]] = []

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fake_run(command, *, cwd, check):
        commands.append({"command": command, "cwd": cwd, "check": check})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_ui_smoke=True,
        report_json=Path("release/rc-verification.json"),
    ) == 0

    assert commands == [
        {"command": ["node", "scripts/smoke_alpha_ui.mjs"], "cwd": tmp_path, "check": False},
        {"command": ["node", "scripts/smoke_beta_ui.mjs"], "cwd": tmp_path, "check": False},
    ]
    report = json.loads((tmp_path / "release" / "rc-verification.json").read_text(encoding="utf-8"))
    assert report["electron_ui_smoke"] == {
        "status": "passed",
        "script_count": 2,
        "scripts": [
            {"script": "scripts/smoke_alpha_ui.mjs", "exit_code": 0},
            {"script": "scripts/smoke_beta_ui.mjs", "exit_code": 0},
        ],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_ui_sampling"]["status"] == "manual_required"
    assert "--run-ui-smoke passed 2 Electron UI smoke scripts" in manual_statuses[
        "packaged_ui_sampling"
    ]["notes"]
    assert "scripts/smoke_alpha_ui.mjs" in manual_statuses["packaged_ui_sampling"]["notes"]


def test_release_candidate_verifier_rejects_smoke_scripts_outside_root(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fail_run(*_args, **_kwargs):
        raise AssertionError("outside smoke script must not run")

    monkeypatch.setattr(rc.subprocess, "run", fail_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_ui_smoke=True,
        smoke_scripts=(Path("../outside-smoke-ui.mjs"),),
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "Electron UI smoke: failed" in output
    assert "Electron UI smoke script path must stay inside project root" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["electron_ui_smoke"] == {
        "status": "failed",
        "script_count": 1,
        "scripts": [
            {
                "script": "../outside-smoke-ui.mjs",
                "exit_code": None,
                "error": (
                    "Electron UI smoke script path must stay inside project root: "
                    "../outside-smoke-ui.mjs"
                ),
            }
        ],
        "run_requested": True,
    }


def test_release_candidate_verifier_reports_electron_ui_smoke_failure(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    smoke = scripts / "smoke_fail_ui.mjs"
    smoke.write_text("process.exit(7)\n", encoding="utf-8")

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(
        rc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )

    assert rc.verify_release_candidate(root=tmp_path, run_ui_smoke=True) == 1

    output = capsys.readouterr().out
    assert "scripts/smoke_fail_ui.mjs failed with exit code 7" in output


def test_release_candidate_verifier_reports_electron_ui_smoke_start_failure(
    tmp_path, monkeypatch, capsys
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    smoke = scripts / "smoke_missing_node_ui.mjs"
    smoke.write_text("console.log('missing node')\n", encoding="utf-8")

    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fake_run(*_args, **_kwargs):
        raise OSError("node not found")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        run_ui_smoke=True,
        report_json=Path("release/rc-verification.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "scripts/smoke_missing_node_ui.mjs could not start: node not found" in output
    report_path = tmp_path / "release" / "rc-verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["electron_ui_smoke"] == {
        "status": "failed",
        "script_count": 1,
        "scripts": [
            {
                "script": "scripts/smoke_missing_node_ui.mjs",
                "exit_code": None,
                "error": "node not found",
            }
        ],
        "run_requested": True,
    }
