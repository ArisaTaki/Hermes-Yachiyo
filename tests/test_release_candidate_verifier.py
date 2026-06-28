"""Release-candidate verification entrypoint tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import verify_release_candidate as rc


def _manual_check_ids() -> list[str]:
    return [check["id"] for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS]


def _external_integrations_passed_check() -> dict[str, str]:
    return {
        "id": "external_integrations_smoke",
        "status": "passed",
        "evidence": (
            "External integration smoke passed with real Live2D, GPT-SoVITS, "
            "and AstrBot plugin bridge resources."
        ),
        "evidence_source": "automated_rc_gate",
    }


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


def test_release_candidate_verifier_reports_source_revision(tmp_path, monkeypatch):
    commit = "abcdef1234567890abcdef1234567890abcdef12"

    def fake_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout=" M README.md\n")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(root=tmp_path, report_json=Path("tmp/rc.json")) == 0

    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["source_revision"] == {
        "available": True,
        "commit": commit,
        "short_commit": "abcdef1",
        "dirty": True,
    }


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


def test_release_candidate_verifier_source_only_rejects_gatekeeper_readiness(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        check_gatekeeper_readiness=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --check-gatekeeper-readiness" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["gatekeeper_readiness"]["status"] == "skipped"


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


def test_release_candidate_verifier_source_only_rejects_packaged_backend_bridge_smoke(
    tmp_path, monkeypatch, capsys
):
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        run_packaged_backend_bridge_smoke=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    assert calls == []
    output = capsys.readouterr().out
    assert "--source-only cannot be combined with --run-packaged-backend-bridge-smoke" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["source_release_guards"]["status"] == "skipped"
    assert report["built_artifact_guards"]["status"] == "failed"
    assert report["packaged_backend_bridge_smoke"]["status"] == "skipped"


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
    assert report["data_analysis_artifact_smoke"]["status"] == "passed"
    assert report["data_analysis_artifact_smoke"]["evidence"]["ok"] is True
    assert report["data_analysis_artifact_smoke"]["evidence"]["result"]["artifact_paths"] == [
        "reports/sales.md",
        "reports/sales-summary.csv",
        "reports/sales.html",
        "reports/sales-chart.png",
    ]
    assert all(
        item["matched"]
        for item in report["data_analysis_artifact_smoke"]["evidence"]["readback"]
    )
    assert report["browser_planner_artifact_smoke"]["status"] == "passed"
    assert report["browser_planner_artifact_smoke"]["evidence"]["ok"] is True
    assert report["browser_planner_artifact_smoke"]["evidence"]["case_count"] == 4
    assert {
        case["id"]
        for case in report["browser_planner_artifact_smoke"]["evidence"]["cases"]
    } == {
        "current_page_report",
        "explicit_url_report",
        "current_page_screenshot",
        "search_report",
    }
    assert report["desktop_planner_discovery_smoke"]["status"] == "passed"
    assert report["desktop_planner_discovery_smoke"]["evidence"]["ok"] is True
    assert report["desktop_planner_discovery_smoke"]["evidence"]["case_count"] == 4
    assert {
        case["id"]
        for case in report["desktop_planner_discovery_smoke"]["evidence"]["cases"]
    } == {
        "generic_app_open",
        "generic_app_read_buttons",
        "app_scoped_click",
        "app_scoped_type",
    }
    assert report["approval_policy_gate_smoke"]["status"] == "passed"
    assert report["approval_policy_gate_smoke"]["evidence"]["ok"] is True
    assert report["approval_policy_gate_smoke"]["evidence"]["planner_case_count"] == 5
    assert {
        case["id"]
        for case in report["approval_policy_gate_smoke"]["evidence"]["planner_cases"]
    } == {
        "low_risk_app_open",
        "low_risk_current_page_report",
        "medium_risk_app_click",
        "medium_risk_app_type",
        "medium_risk_browser_click",
    }
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
    assert [
        check["id"] for check in report["manual_release_candidate_check_statuses"]
    ] == _manual_check_ids()
    assert all(
        check["status"] == "manual_required"
        for check in report["manual_release_candidate_check_statuses"]
    )
    assert all(
        check["required_before"] == "public_release_signoff"
        for check in report["manual_release_candidate_check_statuses"]
    )
    assert report["manual_release_candidate_check_summary"] == {
        "total": len(rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS),
        "status_counts": {
            "manual_required": len(rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS),
            "passed": 0,
            "failed": 0,
            "not_applicable": 0,
        },
        "remaining_count": len(rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS),
        "remaining_check_ids": _manual_check_ids(),
        "remaining_next_actions": [
            {"id": check["id"], "next_action": check["next_action"]}
            for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
        ],
        "remaining_notes": [],
        "remaining_commands": [
            {"id": check_id, "command": command}
            for check_id, command in rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS.items()
        ],
        "failed_check_ids": [],
        "automated_evidence_check_ids": [],
    }


def test_release_candidate_verifier_reports_data_analysis_artifact_smoke(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "data analysis artifact smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["data_analysis_artifact_smoke"]
    assert section["status"] == "passed"
    assert section["run_requested"] is True
    assert section["findings"] == []
    assert section["evidence"]["mode"] == "data_analysis_artifact_smoke"
    assert section["evidence"]["result"]["source_kind"] == "csv"
    assert section["evidence"]["result"]["rows"] == 3
    assert section["evidence"]["result"]["artifact_manifest"][-1] == {
        "path": "reports/sales-chart.png",
        "kind": "chart",
        "actual_kind": "image",
    }


def test_release_candidate_verifier_fails_when_data_analysis_artifact_smoke_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    def fake_run_data_analysis_artifact_smoke(workdir):
        assert workdir == tmp_path / rc.DATA_ANALYSIS_ARTIFACT_SMOKE_WORKDIR
        return {
            "ok": False,
            "mode": "data_analysis_artifact_smoke",
            "workspace": str(workdir),
            "error": "markdown artifact was not readable",
            "readback": [{"path": "reports/sales.md", "matched": False}],
        }

    monkeypatch.setattr(
        rc,
        "run_data_analysis_artifact_smoke",
        fake_run_data_analysis_artifact_smoke,
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "data analysis artifact smoke: failed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["data_analysis_artifact_smoke"]
    assert report["ok"] is False
    assert section["status"] == "failed"
    assert section["evidence"]["error"] == "markdown artifact was not readable"
    assert section["findings"] == [
        {
            "path": "tmp/data-analysis-artifact-smoke",
            "message": "markdown artifact was not readable",
        }
    ]


def test_release_candidate_verifier_reports_browser_planner_artifact_smoke(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "browser planner artifact smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["browser_planner_artifact_smoke"]
    assert section["status"] == "passed"
    assert section["run_requested"] is True
    assert section["findings"] == []
    assert section["evidence"]["mode"] == "browser_planner_artifact_smoke"
    case_by_id = {case["id"]: case for case in section["evidence"]["cases"]}
    assert case_by_id["current_page_report"]["requests"][0]["tool"] == "browser.extract_text"
    assert case_by_id["explicit_url_report"]["requests"][0]["tool"] == (
        "browser.open_url_and_extract_text"
    )
    assert case_by_id["current_page_screenshot"]["artifacts_expected"] == [
        "browser/current-page.png"
    ]


def test_release_candidate_verifier_fails_when_browser_planner_artifact_smoke_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    monkeypatch.setattr(
        rc,
        "run_browser_planner_artifact_smoke",
        lambda: {
            "ok": False,
            "mode": "browser_planner_artifact_smoke",
            "error": "search report did not use a browser tool",
            "cases": [],
        },
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "browser planner artifact smoke: failed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["browser_planner_artifact_smoke"]
    assert report["ok"] is False
    assert section["status"] == "failed"
    assert section["evidence"]["error"] == "search report did not use a browser tool"
    assert section["findings"] == [
        {
            "path": str(tmp_path / "scripts/smoke_browser_planner_artifacts.py"),
            "message": "search report did not use a browser tool",
        }
    ]


def test_release_candidate_verifier_reports_desktop_planner_discovery_smoke(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "desktop planner discovery smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["desktop_planner_discovery_smoke"]
    assert section["status"] == "passed"
    assert section["run_requested"] is True
    assert section["findings"] == []
    assert section["evidence"]["mode"] == "desktop_planner_discovery_smoke"
    case_by_id = {case["id"]: case for case in section["evidence"]["cases"]}
    assert [request["tool"] for request in case_by_id["generic_app_open"]["requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert case_by_id["app_scoped_click"]["requests"][1]["tool"] == (
        "app.focus_and_click_ui_element"
    )
    assert case_by_id["app_scoped_type"]["requests"][1]["tool"] == (
        "app.focus_and_type_into_ui_element"
    )
    assert all(
        case["checks"]["uses_no_browser_tool"]
        for case in case_by_id.values()
    )


def test_release_candidate_verifier_fails_when_desktop_planner_discovery_smoke_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    monkeypatch.setattr(
        rc,
        "run_desktop_planner_discovery_smoke",
        lambda: {
            "ok": False,
            "mode": "desktop_planner_discovery_smoke",
            "error": "Notion click routed to browser",
            "cases": [],
        },
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "desktop planner discovery smoke: failed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["desktop_planner_discovery_smoke"]
    assert report["ok"] is False
    assert section["status"] == "failed"
    assert section["evidence"]["error"] == "Notion click routed to browser"
    assert section["findings"] == [
        {
            "path": str(tmp_path / "scripts/smoke_desktop_planner_discovery.py"),
            "message": "Notion click routed to browser",
        }
    ]


def test_release_candidate_verifier_reports_approval_policy_gate_smoke(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "approval policy gate smoke: passed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["approval_policy_gate_smoke"]
    assert section["status"] == "passed"
    assert section["run_requested"] is True
    assert section["findings"] == []
    assert section["evidence"]["mode"] == "approval_policy_gate_smoke"
    case_by_id = {case["id"]: case for case in section["evidence"]["planner_cases"]}
    assert case_by_id["low_risk_app_open"]["approvals_required"] == []
    assert case_by_id["medium_risk_app_click"]["approvals_required"] == [
        "operate-foreground-ui"
    ]
    assert section["evidence"]["runtime_policy"]["compiled"]["approval_required"][
        "terminal.run"
    ] is True
    assert "browser.click" in section["evidence"]["group_policy"]["approval_required_tools"]


def test_release_candidate_verifier_fails_when_approval_policy_gate_smoke_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    monkeypatch.setattr(
        rc,
        "run_approval_policy_gate_smoke",
        lambda: {
            "ok": False,
            "mode": "approval_policy_gate_smoke",
            "error": "browser click was not marked for approval",
            "planner_cases": [],
        },
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        report_json=Path("tmp/source-only-rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "approval policy gate smoke: failed" in output
    report = json.loads((tmp_path / "tmp" / "source-only-rc.json").read_text(encoding="utf-8"))
    section = report["approval_policy_gate_smoke"]
    assert report["ok"] is False
    assert section["status"] == "failed"
    assert section["evidence"]["error"] == "browser click was not marked for approval"
    assert section["findings"] == [
        {
            "path": str(tmp_path / "scripts/smoke_approval_policy_gate.py"),
            "message": "browser click was not marked for approval",
        }
    ]


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
                    _external_integrations_passed_check(),
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
        "external_integrations_smoke": "passed",
    }
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    assert report["manual_release_candidate_check_summary"]["remaining_check_ids"] == []
    assert report["manual_release_candidate_check_summary"]["remaining_next_actions"] == []


def test_release_candidate_verifier_final_signoff_rejects_dirty_source_revision(
    tmp_path, monkeypatch, capsys
):
    commit = "1234567890abcdef1234567890abcdef12345678"
    (tmp_path / "release").mkdir()
    evidence_path = tmp_path / "tmp" / "manual-checks.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        **check,
                        "status": "not_applicable" if check["id"] == "real_provider_smoke" else "passed",
                        "evidence": f"{check['id']} evidence recorded.",
                    }
                    for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout=" M docs/release-packaging.md\n")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/manual-checks.json"),
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: passed" in output
    assert "source revision final signoff guard: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["source_revision"] == {
        "available": True,
        "commit": commit,
        "short_commit": "1234567",
        "dirty": True,
    }
    assert report["source_revision_final_signoff_findings"] == [
        {
            "path": str(tmp_path),
            "message": (
                "final signoff requires a clean source revision at 1234567; "
                "commit or discard uncommitted changes and rebuild release artifacts "
                "before final signoff"
            ),
        }
    ]


def test_release_candidate_verifier_final_signoff_rejects_stale_manual_evidence_source_revision(
    tmp_path, monkeypatch, capsys
):
    current_commit = "2222222222222222222222222222222222222222"
    stale_commit = "1111111111111111111111111111111111111111"
    checks_path = tmp_path / "tmp" / "manual-checks.json"
    checks_path.parent.mkdir()
    checks_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        **check,
                        "status": (
                            "not_applicable"
                            if check["id"] == "real_provider_smoke"
                            else "passed"
                        ),
                        "evidence": f"{check['id']} release signoff evidence.",
                    }
                    for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
                ],
                "manual_release_candidate_check_source_revisions": [
                    {
                        "source": "tmp/stale-rc.json",
                        "available": True,
                        "commit": stale_commit,
                        "short_commit": "1111111",
                        "dirty": False,
                    },
                    {
                        "source": "tmp/current-dirty-rc.json",
                        "available": True,
                        "commit": current_commit,
                        "short_commit": "2222222",
                        "dirty": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{current_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        manual_checks_json=Path("tmp/manual-checks.json"),
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: passed" in output
    assert "manual evidence source revision guard: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["source_revision"] == {
        "available": True,
        "commit": current_commit,
        "short_commit": "2222222",
        "dirty": False,
    }
    assert report["manual_release_candidate_check_source_revision_findings"] == [
        {
            "path": "tmp/stale-rc.json",
            "message": (
                "manual release-candidate evidence source revision 1111111 "
                "does not match current source_revision.commit 2222222; rerun "
                "RC evidence or regenerate manual checks from the current source "
                "before final signoff"
            ),
        },
        {
            "path": "tmp/current-dirty-rc.json",
            "message": (
                "final signoff requires manual release-candidate evidence from "
                "a clean source revision; tmp/current-dirty-rc.json@2222222 "
                "was recorded with dirty source"
            ),
        },
    ]


def test_release_candidate_verifier_final_signoff_requires_manual_evidence_source_revision(
    tmp_path, monkeypatch, capsys
):
    current_commit = "2222222222222222222222222222222222222222"
    checks_path = tmp_path / "tmp" / "manual-checks.json"
    checks_path.parent.mkdir()
    checks_path.write_text(
        json.dumps(
            {
                "checks": [
                    {
                        **check,
                        "status": (
                            "not_applicable"
                            if check["id"] == "real_provider_smoke"
                            else "passed"
                        ),
                        "evidence": f"{check['id']} release signoff evidence.",
                    }
                    for check in rc.MANUAL_RELEASE_CANDIDATE_CHECK_DETAILS
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{current_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        source_only=True,
        manual_checks_json=Path("tmp/manual-checks.json"),
        require_manual_checks_complete=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "manual release-candidate check evidence: passed" in output
    assert "manual evidence source revision guard: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["manual_release_candidate_check_status"] == "passed"
    assert report["source_revision"] == {
        "available": True,
        "commit": current_commit,
        "short_commit": "2222222",
        "dirty": False,
    }
    assert report["manual_release_candidate_check_source_revision_findings"] == [
        {
            "path": "tmp/manual-checks.json",
            "message": (
                "final signoff requires manual release-candidate evidence "
                "source revisions; regenerate the manual checks draft or Markdown "
                "from a current RC report before final signoff"
            ),
        }
    ]


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
                "source_revision": {
                    "available": True,
                    "commit": "fedcba9876543210fedcba9876543210fedcba98",
                    "short_commit": "fedcba9",
                    "dirty": False,
                },
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
    assert report["manual_release_candidate_check_source_revisions"] == [
        {
            "source": "tmp/prior-rc-report.json",
            "available": True,
            "commit": "fedcba9876543210fedcba9876543210fedcba98",
            "short_commit": "fedcba9",
            "dirty": False,
        }
    ]
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"


def test_release_candidate_verifier_preserves_manual_source_capability_matrix(
    tmp_path,
    monkeypatch,
    capsys,
):
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "real_provider_smoke":
            check["status"] = "passed"
            check["evidence"] = "Provider smoke passed with Native Agent matrix."
            check["evidence_source"] = "automated_rc_gate"
    evidence_path = tmp_path / "tmp" / "provider-rc.json"
    evidence_path.parent.mkdir()
    evidence_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": prior_statuses,
                "native_agent_capability_matrix": {
                    "status": "passed",
                    "ok": True,
                    "capability_count": 13,
                    "status_counts": {"passed": 13, "missing": 0},
                    "missing_capability_ids": [],
                    "capabilities": [
                        {
                            "id": "agent_multi_tool_pipeline",
                            "status": "passed",
                            "evidence_summary": {"tool_call_count": 2},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])

    assert rc.verify_release_candidate(
        root=tmp_path,
        manual_checks_json=Path("tmp/provider-rc.json"),
        report_json=Path("tmp/rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "Native Agent capability matrix: passed (13 capabilities)" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    matrix = report["native_agent_capability_matrix"]
    assert matrix["status"] == "passed"
    assert matrix["ok"] is True
    assert matrix["capability_count"] == 13
    assert matrix["missing_capability_ids"] == []
    assert matrix["source_reports"] == ["tmp/provider-rc.json"]
    assert matrix["capabilities"][0]["id"] == "agent_multi_tool_pipeline"


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
                    _external_integrations_passed_check(),
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
    assert statuses["external_integrations_smoke"]["status"] == "passed"


def test_release_candidate_verifier_accumulates_automated_evidence_from_multiple_rc_reports(
    tmp_path,
):
    packaged_ui_statuses = rc._manual_release_candidate_check_report()
    for check in packaged_ui_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-ui-sampling-smoke passed for release/Oha-Yachiyo.dmg."
            check["evidence_source"] = "automated_rc_gate"
        if check["id"] == "packaged_ui_sampling":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-ui-sampling-smoke sampled #/chat and #/agents/workflows."
            check["evidence_source"] = "automated_rc_gate"
    chat_file_statuses = rc._manual_release_candidate_check_report()
    for check in chat_file_statuses:
        if check["id"] == "chat_native_file_upload":
            check["status"] = "passed"
            check["evidence"] = "Automated --run-dmg-chat-native-file-smoke passed for release/Oha-Yachiyo.dmg."
            check["evidence_source"] = "automated_rc_gate"

    packaged_ui_report = tmp_path / "tmp" / "packaged-ui-rc.json"
    chat_file_report = tmp_path / "tmp" / "chat-file-rc.json"
    packaged_ui_report.parent.mkdir(parents=True)
    packaged_ui_report.write_text(
        json.dumps({"manual_release_candidate_check_statuses": packaged_ui_statuses}),
        encoding="utf-8",
    )
    chat_file_report.write_text(
        json.dumps({"manual_release_candidate_check_statuses": chat_file_statuses}),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        (Path("tmp/packaged-ui-rc.json"), Path("tmp/chat-file-rc.json")),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    assert statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert statuses["packaged_ui_sampling"]["status"] == "passed"
    assert statuses["chat_native_file_upload"]["status"] == "passed"
    assert statuses["packaged_bridge_isolation"]["evidence_source"] == "automated_rc_gate"
    assert statuses["packaged_ui_sampling"]["evidence_source"] == "automated_rc_gate"
    assert statuses["chat_native_file_upload"]["evidence_source"] == "automated_rc_gate"
    summary = rc._manual_release_candidate_check_summary(checks)
    assert summary["remaining_check_ids"] == [
        "gatekeeper_first_launch",
        "screen_recording_permission",
        "real_provider_smoke",
        "external_integrations_smoke",
    ]
    assert summary["remaining_commands"] == [
        {
            "id": "gatekeeper_first_launch",
            "command": rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS[
                "gatekeeper_first_launch"
            ],
        },
        {
            "id": "screen_recording_permission",
            "command": rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS[
                "screen_recording_permission"
            ],
        },
        {
            "id": "real_provider_smoke",
            "command": rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS[
                "real_provider_smoke"
            ],
        },
        {
            "id": "external_integrations_smoke",
            "command": rc.MANUAL_RELEASE_CANDIDATE_CHECK_AUTOMATION_COMMANDS[
                "external_integrations_smoke"
            ],
        },
    ]
    assert summary["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation",
        "chat_native_file_upload",
        "packaged_ui_sampling",
    ]


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
                "<!-- manual_release_candidate_check_source_revisions: "
                '[{"available":true,"commit":"1111111111111111111111111111111111111111",'
                '"dirty":false,"short_commit":"1111111","source":"tmp/final-rc.json"}] -->',
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
                "- [x] `external_integrations_smoke` - passed",
                "  - Evidence source: automated_rc_gate",
                "  - Evidence: External integration smoke passed with real Live2D, GPT-SoVITS, and AstrBot plugin bridge resources",
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
    assert report["manual_release_candidate_check_source_revisions"] == [
        {
            "source": "tmp/final-rc.json",
            "available": True,
            "commit": "1111111111111111111111111111111111111111",
            "short_commit": "1111111",
            "dirty": False,
        }
    ]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 0
    statuses = {
        check["id"]: check for check in report["manual_release_candidate_check_statuses"]
    }
    assert statuses["real_provider_smoke"]["status"] == "not_applicable"
    assert statuses["real_provider_smoke"]["evidence_source"] == "credentials_unavailable"
    assert statuses["external_integrations_smoke"]["status"] == "passed"
    assert statuses["external_integrations_smoke"]["evidence_source"] == "automated_rc_gate"


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
                "- [x] `external_integrations_smoke`",
                "  - Evidence: External integration smoke passed with real resources",
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
    assert statuses["external_integrations_smoke"]["status"] == "passed"


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
    assert [check["id"] for check in template["checks"]] == _manual_check_ids()
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
                "source_revision": {
                    "available": True,
                    "commit": "0123456789abcdef0123456789abcdef01234567",
                    "short_commit": "0123456",
                    "dirty": False,
                },
                "manual_release_candidate_check_statuses": prior_statuses,
                "manual_release_candidate_check_summary": {
                    "remaining_count": 6,
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
        "tmp/final-rc.json",
    )

    assert draft_path == tmp_path / "tmp" / "final-rc-signoff.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["manual_release_candidate_checks_source"] == "tmp/final-rc.json"
    assert draft["manual_release_candidate_check_source_revisions"] == [
        {
            "source": "tmp/final-rc.json",
            "available": True,
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "short_commit": "0123456",
            "dirty": False,
        }
    ]
    assert draft["manual_release_candidate_check_summary"]["remaining_count"] == 6
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


def test_release_candidate_verifier_merges_external_integration_smoke_report(
    tmp_path,
):
    smoke_report_path = tmp_path / "tmp" / "external-integrations-smoke.json"
    smoke_report_path.parent.mkdir(parents=True)
    smoke_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "bridge_url": "http://127.0.0.1:18420",
                "checks": [
                    {"id": "bridge_status", "status": "passed"},
                    {"id": "live2d_resource", "status": "passed"},
                    {"id": "gpt_sovits_tts", "status": "passed"},
                    {"id": "astrbot_plugin_bridge", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        Path("tmp/external-integrations-smoke.json"),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    external = statuses["external_integrations_smoke"]
    assert external["status"] == "passed"
    assert external["evidence_source"] == "automated_rc_gate"
    assert "live2d_resource, gpt_sovits_tts, astrbot_plugin_bridge" in external["evidence"]
    summary = rc._manual_release_candidate_check_summary(checks)
    assert summary["remaining_count"] == 6
    assert summary["automated_evidence_check_ids"] == ["external_integrations_smoke"]


def test_release_candidate_verifier_marks_failed_external_integration_smoke_report(
    tmp_path,
):
    smoke_report_path = tmp_path / "tmp" / "external-integrations-smoke.json"
    smoke_report_path.parent.mkdir(parents=True)
    smoke_report_path.write_text(
        json.dumps(
            {
                "ok": False,
                "bridge_url": "http://127.0.0.1:18420",
                "checks": [
                    {"id": "bridge_status", "status": "passed"},
                    {"id": "live2d_resource", "status": "passed"},
                    {
                        "id": "gpt_sovits_tts",
                        "status": "failed",
                        "error": "GPT-SoVITS TTS test failed",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        Path("tmp/external-integrations-smoke.json"),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    external = statuses["external_integrations_smoke"]
    assert external["status"] == "failed"
    assert external["evidence_source"] == "automated_rc_gate"
    assert "gpt_sovits_tts=failed" in external["evidence"]
    assert "missing required checks: astrbot_plugin_bridge" in external["evidence"]
    assert rc._manual_release_candidate_check_status(checks, []) == "failed"


def test_release_candidate_verifier_keeps_partial_external_integration_smoke_manual(
    tmp_path,
):
    smoke_report_path = tmp_path / "tmp" / "external-integrations-smoke.json"
    smoke_report_path.parent.mkdir(parents=True)
    smoke_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "bridge_url": "http://127.0.0.1:18420",
                "checks": [
                    {"id": "bridge_status", "status": "passed"},
                    {"id": "live2d_resource", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        Path("tmp/external-integrations-smoke.json"),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    external = statuses["external_integrations_smoke"]
    assert external["status"] == "manual_required"
    assert "passed selected checks: live2d_resource" in external["notes"]
    assert "gpt_sovits_tts, astrbot_plugin_bridge" in external["notes"]
    summary = rc._manual_release_candidate_check_summary(checks)
    assert summary["remaining_count"] == 7
    assert summary["remaining_notes"] == [
        {"id": "external_integrations_smoke", "notes": external["notes"]}
    ]


def test_release_candidate_verifier_merges_multiple_external_supporting_notes(
    tmp_path,
):
    bridge_report_path = tmp_path / "tmp" / "external-bridge-preflight.json"
    partial_report_path = tmp_path / "tmp" / "external-live2d-partial.json"
    bridge_report_path.parent.mkdir(parents=True)
    bridge_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "complete": False,
                "mode": "bridge_only",
                "bridge_url": "http://127.0.0.1:18420",
                "missing_required_check_ids": [
                    "live2d_resource",
                    "gpt_sovits_tts",
                    "astrbot_plugin_bridge",
                ],
                "checks": [{"id": "bridge_status", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )
    partial_report_path.write_text(
        json.dumps(
            {
                "ok": True,
                "complete": False,
                "bridge_url": "http://127.0.0.1:18421",
                "missing_required_check_ids": [
                    "gpt_sovits_tts",
                    "astrbot_plugin_bridge",
                ],
                "checks": [
                    {"id": "bridge_status", "status": "passed"},
                    {"id": "live2d_resource", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        (bridge_report_path.relative_to(tmp_path), partial_report_path.relative_to(tmp_path)),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    external = statuses["external_integrations_smoke"]
    assert external["status"] == "manual_required"
    assert "bridge-only preflight passed against http://127.0.0.1:18420" in external["notes"]
    assert "passed selected checks: live2d_resource" in external["notes"]
    assert "gpt_sovits_tts, astrbot_plugin_bridge" in external["notes"]

    markdown_path = rc.write_manual_release_candidate_checks_markdown(
        tmp_path,
        Path("tmp/external-signoff.md"),
        (bridge_report_path.relative_to(tmp_path), partial_report_path.relative_to(tmp_path)),
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert (
        "  - Notes: Supporting automated evidence: external integration bridge-only "
        "preflight passed against http://127.0.0.1:18420"
    ) in markdown
    assert (
        "    Supporting automated evidence: external integration smoke passed selected "
        "checks: live2d_resource"
    ) in markdown

    markdown_checks, markdown_findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        None,
        markdown_path.relative_to(tmp_path),
    )
    assert markdown_findings == []
    markdown_statuses = {check["id"]: check for check in markdown_checks}
    assert "bridge-only preflight passed" in markdown_statuses[
        "external_integrations_smoke"
    ]["notes"]
    assert "passed selected checks: live2d_resource" in markdown_statuses[
        "external_integrations_smoke"
    ]["notes"]


def test_release_candidate_verifier_keeps_external_bridge_only_report_manual(
    tmp_path,
):
    smoke_report_path = tmp_path / "tmp" / "external-bridge-preflight.json"
    smoke_report_path.parent.mkdir(parents=True)
    smoke_report_path.write_text(
        json.dumps(
            {
                "ok": False,
                "mode": "bridge_only",
                "bridge_url": "http://127.0.0.1:18420",
                "checks": [
                    {
                        "id": "bridge_status",
                        "status": "failed",
                        "error": "/status returned service=legacy; expected oha-yachiyo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    checks, findings = rc._load_manual_release_candidate_checks(
        tmp_path,
        Path("tmp/external-bridge-preflight.json"),
    )

    assert findings == []
    statuses = {check["id"]: check for check in checks}
    external = statuses["external_integrations_smoke"]
    assert external["status"] == "manual_required"
    assert "bridge-only preflight did not pass" in external["notes"]
    assert "service=legacy" in external["notes"]
    assert rc._manual_release_candidate_check_status(checks, []) == "manual_required"


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
    assert draft["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert draft["manual_release_candidate_check_summary"]["remaining_check_ids"] == [
        "gatekeeper_first_launch",
        "screen_recording_permission",
        "chat_native_file_upload",
        "packaged_ui_sampling",
        "external_integrations_smoke",
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


def test_release_candidate_verifier_draft_keeps_failed_dmg_screen_probe_notes(
    tmp_path,
    monkeypatch,
    capsys,
):
    for env_name in rc.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    signoff_statuses = rc._manual_release_candidate_check_report()
    passed_evidence = {
        "packaged_bridge_isolation": "Automated --run-dmg-app-smoke passed for dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
        "chat_native_file_upload": "Automated --run-dmg-chat-native-file-smoke passed for dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
        "packaged_ui_sampling": "Automated --run-dmg-ui-sampling-smoke passed for dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
    }
    for check in signoff_statuses:
        evidence = passed_evidence.get(check["id"])
        if evidence:
            check["status"] = "passed"
            check["evidence"] = evidence
            check["evidence_source"] = "automated_rc_gate"

    signoff_path = tmp_path / "tmp" / "rc-signoff.json"
    screen_report_path = tmp_path / "tmp" / "rc-screen.json"
    signoff_path.parent.mkdir(parents=True)
    signoff_path.write_text(
        json.dumps({"manual_release_candidate_check_statuses": signoff_statuses}),
        encoding="utf-8",
    )

    screen_statuses = rc._manual_release_candidate_check_report()
    for check in screen_statuses:
        if check["id"] == "packaged_bridge_isolation":
            check["status"] = "passed"
            check["evidence"] = (
                "Automated --run-dmg-screen-smoke reached packaged /status for "
                "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg"
            )
            check["evidence_source"] = "automated_rc_gate"
    screen_report_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": screen_statuses,
                "dmg_screen_probe": {
                    "status": "failed",
                    "dmg_paths": [
                        "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
                    ],
                    "bridge_ready_dmg_paths": [
                        "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
                    ],
                    "screens": [],
                    "findings": [
                        {
                            "path": "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
                            "message": (
                                "release candidate packaged /screen/current probe failed: "
                                '{"detail":{"error":"screen_capture_permission_denied",'
                                '"message":"grant permission",'
                                '"detail":"temporary backend path /private/var/folders/example"}}'
                            ),
                        }
                    ],
                    "run_requested": True,
                },
            }
        ),
        encoding="utf-8",
    )

    draft_path = rc.write_manual_release_candidate_checks_draft(
        tmp_path,
        Path("tmp/rc-signoff-current-with-screen-attempt.json"),
        (
            Path("tmp/rc-signoff.json"),
            Path("tmp/rc-screen.json"),
        ),
        mark_provider_smoke_not_applicable_if_missing=True,
    )

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["manual_release_candidate_check_summary"]["remaining_count"] == 3
    assert draft["manual_release_candidate_check_summary"]["remaining_check_ids"] == [
        "gatekeeper_first_launch",
        "screen_recording_permission",
        "external_integrations_smoke",
    ]
    assert draft["manual_release_candidate_check_summary"]["remaining_notes"] == [
        {
            "id": "screen_recording_permission",
            "notes": (
                "Supporting automated evidence: --run-dmg-screen-smoke reached "
                "packaged Bridge for dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg, "
                "but /screen/current failed with screen_capture_permission_denied; "
                "keep this check manual_required until Screen Recording is granted "
                "and the probe passes."
            ),
        }
    ]
    checks = {check["id"]: check for check in draft["checks"]}
    assert checks["packaged_bridge_isolation"]["status"] == "passed"
    assert checks["chat_native_file_upload"]["status"] == "passed"
    assert checks["packaged_ui_sampling"]["status"] == "passed"
    assert checks["real_provider_smoke"]["status"] == "not_applicable"
    assert checks["screen_recording_permission"]["status"] == "manual_required"
    notes = checks["screen_recording_permission"]["notes"]
    assert "--run-dmg-screen-smoke reached packaged Bridge" in notes
    assert "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg" in notes
    assert "screen_capture_permission_denied" in notes
    assert "/private/var/folders" not in notes

    assert rc.print_manual_release_candidate_checks_status(
        tmp_path,
        (
            Path("tmp/rc-signoff.json"),
            Path("tmp/rc-screen.json"),
        ),
        mark_provider_smoke_not_applicable_if_missing=True,
    )
    output = capsys.readouterr().out
    assert "manual release-candidate supporting notes:" in output
    assert (
        "- [screen_recording_permission] Supporting automated evidence: "
        "--run-dmg-screen-smoke reached packaged Bridge"
    ) in output
    assert "screen_capture_permission_denied" in output
    assert "/private/var/folders" not in output


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
    assert "manual release-candidate check progress: 2/7 complete, 5 remaining" in output
    assert (
        "manual release-candidate check summary: 5 remaining "
        "(gatekeeper_first_launch, screen_recording_permission, "
        "chat_native_file_upload, packaged_ui_sampling, external_integrations_smoke)"
    ) in output
    assert "- [screen_recording_permission] Prefer rerunning the RC gate with --run-dmg-screen-smoke" in output
    assert "manual release-candidate recommended commands:" in output
    assert (
        "- [screen_recording_permission] "
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-screen-smoke --report-json tmp/rc-verification-screen.json"
    ) in output
    assert (
        "- [chat_native_file_upload] "
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-chat-native-file-smoke "
        "--report-json tmp/rc-verification-chat-native-file.json"
    ) in output

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
    assert "manual release-candidate check progress: 2/7 complete, 5 remaining" in output
    assert "manual release-candidate next actions:" in output
    assert "manual release-candidate recommended commands:" in output


def test_release_candidate_verifier_manual_check_status_action_prints_without_artifact_gate(
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
                "--print-manual-checks-status",
                "--mark-provider-smoke-not-applicable-if-missing",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "manual release-candidate checks status:" in output
    assert "manual release-candidate check progress: 2/7 complete, 5 remaining" in output
    assert (
        "manual release-candidate check summary: 5 remaining "
        "(gatekeeper_first_launch, screen_recording_permission, "
        "chat_native_file_upload, packaged_ui_sampling, external_integrations_smoke)"
    ) in output
    assert "- [gatekeeper_first_launch] Manually mount the final DMG" in output
    assert "manual release-candidate recommended commands:" in output
    assert (
        "- [packaged_ui_sampling] "
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-ui-sampling-smoke --report-json tmp/rc-verification-packaged-ui.json"
    ) in output
    assert "Source release guard" not in output


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
    assert "- Remaining checks: 5" in markdown
    assert "## Remaining Automation Commands" in markdown
    assert "- `screen_recording_permission`" in markdown
    assert (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-screen-smoke --report-json tmp/rc-verification-screen.json"
    ) in markdown
    assert "- `chat_native_file_upload`" in markdown
    assert (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-chat-native-file-smoke "
        "--report-json tmp/rc-verification-chat-native-file.json"
    ) in markdown
    assert "- `packaged_ui_sampling`" in markdown
    assert (
        "python scripts/verify_release_candidate.py --require-artifacts "
        "--run-dmg-ui-sampling-smoke --report-json tmp/rc-verification-packaged-ui.json"
    ) in markdown
    assert "- `external_integrations_smoke`" in markdown
    assert "python scripts/smoke_external_integrations.py" in markdown
    assert "- `real_provider_smoke`" not in markdown
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
        json.dumps(
            {
                "checks": draft_checks,
                "manual_release_candidate_check_source_revisions": [
                    {
                        "source": "tmp/final-rc.json",
                        "available": True,
                        "commit": "2222222222222222222222222222222222222222",
                        "short_commit": "2222222",
                        "dirty": False,
                    }
                ],
            }
        ),
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
    assert "- Source revisions: `tmp/final-rc.json@2222222`" in markdown
    assert "manual_release_candidate_check_source_revisions" in markdown
    assert "2222222222222222222222222222222222222222" in markdown
    assert "- Remaining checks: 5" in markdown
    assert "## How To Fill" in markdown
    assert "omitted status defaults to `passed`" in markdown
    assert "Every `passed`, `failed`, or `not_applicable` item needs non-empty `Evidence:`" in markdown
    assert "## Final Gate" in markdown
    assert "--manual-checks-markdown tmp/final-rc-signoff.md" in markdown
    assert "--require-manual-checks-complete --report-json tmp/rc-with-manual-checks.json" in markdown
    assert "## Remaining Automation Commands" in markdown
    assert "- `screen_recording_permission`" in markdown
    assert "--run-dmg-screen-smoke --report-json tmp/rc-verification-screen.json" in markdown
    assert "- `chat_native_file_upload`" in markdown
    assert (
        "--run-dmg-chat-native-file-smoke "
        "--report-json tmp/rc-verification-chat-native-file.json"
    ) in markdown
    assert "- `packaged_ui_sampling`" in markdown
    assert "--run-dmg-ui-sampling-smoke --report-json tmp/rc-verification-packaged-ui.json" in markdown
    assert "- `external_integrations_smoke`" in markdown
    assert "python scripts/smoke_external_integrations.py" in markdown
    assert "## Remaining Manual Checks" in markdown
    assert "- [ ] `gatekeeper_first_launch`" in markdown
    assert "Evidence to record:" in markdown
    assert "## Completed Or Not Applicable Checks" in markdown
    assert "- [x] `packaged_bridge_isolation` - passed" in markdown
    assert "Evidence source: automated_rc_gate" in markdown
    assert "- [x] `real_provider_smoke` - not_applicable" in markdown
    assert "Evidence source: credentials_unavailable" in markdown


def test_release_candidate_verifier_signoff_outputs_surface_native_agent_matrix(
    tmp_path,
    capsys,
):
    prior_statuses = rc._manual_release_candidate_check_report()
    for check in prior_statuses:
        if check["id"] == "real_provider_smoke":
            check["status"] = "passed"
            check["evidence"] = "Provider smoke passed with Native Agent matrix."
            check["evidence_source"] = "automated_rc_gate"

    source_path = tmp_path / "tmp" / "provider-rc.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        json.dumps(
            {
                "manual_release_candidate_check_statuses": prior_statuses,
                "native_agent_capability_matrix": {
                    "status": "passed",
                    "ok": True,
                    "capability_count": 13,
                    "status_counts": {"passed": 13, "missing": 0},
                    "missing_capability_ids": [],
                    "capabilities": [
                        {
                            "id": "agent_multi_tool_pipeline",
                            "label": "Sequential multi-tool Agent pipeline",
                            "status": "passed",
                            "evidence_summary": {"tool_call_count": 2},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    draft_path = rc.write_manual_release_candidate_checks_draft(
        tmp_path,
        Path("tmp/final-rc-signoff.json"),
        Path("tmp/provider-rc.json"),
    )
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["native_agent_capability_matrix"]["status"] == "passed"
    assert draft["native_agent_capability_matrix"]["source_reports"] == [
        "tmp/provider-rc.json"
    ]

    markdown_path = rc.write_manual_release_candidate_checks_markdown(
        tmp_path,
        Path("tmp/final-rc-signoff.md"),
        Path("tmp/final-rc-signoff.json"),
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "## Native Agent Capability Matrix" in markdown
    assert "- Status: passed (13 capabilities)" in markdown
    assert "- Capabilities: 13/13 passed" in markdown
    assert "`tmp/provider-rc.json`" in markdown
    assert "- Missing capabilities: none" in markdown
    assert (
        "- [x] `agent_multi_tool_pipeline` - Sequential multi-tool Agent pipeline"
        in markdown
    )
    assert "<!-- native_agent_capability_matrix: " in markdown

    matrix_from_markdown = rc._native_agent_capability_matrix_from_manual_inputs(
        tmp_path,
        None,
        Path("tmp/final-rc-signoff.md"),
        run_requested=False,
    )
    assert matrix_from_markdown is not None
    assert matrix_from_markdown["status"] == "passed"

    assert rc.print_manual_release_candidate_checks_status(
        tmp_path,
        Path("tmp/final-rc-signoff.json"),
    )
    output = capsys.readouterr().out
    assert "Native Agent capability matrix: passed (13 capabilities)" in output
    assert "Native Agent capability matrix sources: tmp/provider-rc.json" in output

    assert rc.print_manual_release_candidate_checks_status(
        tmp_path,
        Path("tmp/final-rc-signoff.md"),
    )
    output = capsys.readouterr().out
    assert "Native Agent capability matrix: passed (13 capabilities)" in output
    assert "tmp/final-rc-signoff.md" in output


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
        "--write-manual-checks-markdown, or --print-manual-checks-status"
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


def test_release_candidate_verifier_records_gatekeeper_readiness(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg_path = release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg_path.write_bytes(b"fake dmg")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:2] == ["hdiutil", "detach"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["xattr", "-p", "com.apple.quarantine"]:
            if command[-1].endswith(".dmg"):
                return SimpleNamespace(returncode=0, stdout="0081;Example;Safari;\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="No such xattr")
        if command[:2] == ["codesign", "--verify"]:
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="valid on disk\nsatisfies its Designated Requirement\n",
            )
        if command[:2] == ["codesign", "-dv"]:
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="Identifier=app.oha-yachiyo\nAuthority=Oha-Yachiyo Self Signed\n",
            )
        if command[:2] == ["spctl", "--assess"]:
            return SimpleNamespace(
                returncode=3,
                stdout="",
                stderr="rejected\nsource=no usable signature\n",
            )
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        check_gatekeeper_readiness=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    output = capsys.readouterr().out
    assert "Gatekeeper readiness: passed" in output
    assert [command[:2] for command in commands[:2]] == [
        ["hdiutil", "attach"],
        ["xattr", "-p"],
    ]
    assert commands[-1][:2] == ["hdiutil", "detach"]
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["gatekeeper_readiness"]["status"] == "passed"
    assert report["gatekeeper_readiness"]["dmg_paths"] == [
        "release/Oha-Yachiyo-0.4.0-arm64.dmg"
    ]
    assert report["gatekeeper_readiness"]["findings"] == []
    assessment = report["gatekeeper_readiness"]["assessments"][0]
    assert assessment["dmg_path"] == "release/Oha-Yachiyo-0.4.0-arm64.dmg"
    assert assessment["dmg_quarantine"]["present"] is True
    assert assessment["app_quarantine"]["present"] is False
    assert assessment["codesign_verify"]["ok"] is True
    assert "Oha-Yachiyo Self Signed" in assessment["codesign_display"]["output"]
    assert assessment["spctl_assess"]["ok"] is False
    assert assessment["spctl_assess"]["exit_code"] == 3
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    gatekeeper = manual_statuses["gatekeeper_first_launch"]
    assert gatekeeper["status"] == "manual_required"
    assert "--check-gatekeeper-readiness collected codesign" in gatekeeper["notes"]
    assert "does not replace Finder Control-click" in gatekeeper["notes"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 7
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == []


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


def test_release_candidate_verifier_runs_packaged_backend_bridge_smoke(
    tmp_path, monkeypatch, capsys
):
    source_commit = "abc1234567890abc1234567890abc1234567890a"
    backend_dir = tmp_path / "dist" / "backend"
    backend_dir.mkdir(parents=True)
    backend = backend_dir / "oha-yachiyo-backend"
    backend.write_text("#!/bin/sh\n", encoding="utf-8")
    backend.chmod(0o755)
    popen_calls: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return (
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,'
                b'"task_counts":{},"native_agent_ready":false,'
                b'"build_metadata":{"commit":"abc1234567890abc1234567890abc1234567890a",'
                b'"short_commit":"abc1234"}}'
            )

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

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{source_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: 49124)
    monkeypatch.setattr(rc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rc.urllib.request, "urlopen", lambda url, timeout: FakeResponse())

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("dist/backend"),),
        run_packaged_backend_bridge_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert len(popen_calls) == 1
    assert popen_calls[0]["command"] == [str(backend)]
    assert popen_calls[0]["cwd"] == str(backend_dir)
    assert popen_calls[0]["start_new_session"] is True
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49124"
    assert env["OHA_YACHIYO_HOME"].endswith("/.oha-yachiyo")
    assert env["OHA_YACHIYO_BRIDGE_ACCESS_LOG"] == "0"
    output = capsys.readouterr().out
    assert "packaged backend bridge smoke: passed" in output
    assert "DMG packaged build metadata revision guards: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["packaged_backend_bridge_smoke"] == {
        "status": "passed",
        "backend_paths": ["dist/backend/oha-yachiyo-backend"],
        "bridge_statuses": [
            {
                "backend_path": "dist/backend/oha-yachiyo-backend",
                "bridge_url": "http://127.0.0.1:49124",
                "service": "oha-yachiyo",
                "version": "0.4.0",
                "native_agent_ready": False,
                "build_metadata": {
                    "commit": "abc1234567890abc1234567890abc1234567890a",
                    "short_commit": "abc1234",
                },
            }
        ],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    external = manual_statuses["external_integrations_smoke"]
    assert external["status"] == "manual_required"
    assert "--run-packaged-backend-bridge-smoke started" in external["notes"]
    assert "full release signoff still needs live2d_resource" in external["notes"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 7
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == []


def test_release_candidate_verifier_runs_dmg_app_startup_smoke(
    tmp_path, monkeypatch, capsys
):
    source_commit = "abc1234567890abc1234567890abc1234567890a"
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
            return (
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,'
                b'"task_counts":{},"native_agent_ready":false,'
                b'"build_metadata":{"commit":"abc1234567890abc1234567890abc1234567890a",'
                b'"short_commit":"abc1234"}}'
            )

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

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{source_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
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
    assert "DMG packaged build metadata revision guards: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["source_revision"]["commit"] == source_commit
    assert report["dmg_app_smoke"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "bridge_statuses": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "service": "oha-yachiyo",
                "version": "0.4.0",
                "native_agent_ready": False,
                "build_metadata": {
                    "commit": "abc1234567890abc1234567890abc1234567890a",
                    "short_commit": "abc1234",
                },
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
    assert "--run-dmg-app-smoke passed" in manual_statuses["packaged_bridge_isolation"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 6
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation"
    ]


def test_release_candidate_verifier_rejects_stale_dmg_bridge_build_metadata(
    tmp_path, monkeypatch, capsys
):
    source_commit = "1111111222222233333334444444555555566666"
    stale_commit = "aaaaaaabbbbbbbcccccccdddddddeeeeeeeffffff"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{source_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    def fake_verify_dmg_app_startup(root, dmg_paths):
        assert root == tmp_path
        assert tuple(dmg_paths) == (Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),)
        return [], [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "service": "oha-yachiyo",
                "version": "0.4.0",
                "native_agent_ready": True,
                "build_metadata": {
                    "commit": stale_commit,
                    "short_commit": "aaaaaaa",
                },
            }
        ]

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "verify_dmg_app_startup", fake_verify_dmg_app_startup)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_app_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "DMG app startup smoke: passed" in output
    assert "DMG packaged build metadata revision guards: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["dmg_app_smoke"]["status"] == "failed"
    assert report["dmg_app_smoke"]["bridge_statuses"][0]["build_metadata"]["commit"] == stale_commit
    assert report["dmg_app_smoke"]["findings"] == [
        {
            "path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
            "message": (
                "dmg_app_smoke packaged Bridge build_metadata.commit aaaaaaa "
                "does not match source_revision.commit 1111111; rebuild the DMG "
                "from the current source before final signoff"
            ),
        }
    ]
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["status"] == "manual_required"
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == []


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
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,'
                b'"native_agent_ready":true,'
                b'"build_metadata":{"commit":"def1234567890abc1234567890abc1234567890a",'
                b'"short_commit":"def1234"}}'
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
    assert popen_calls[0]["command"] == [
        str(
            tmp_path
            / "tmp"
            / "rc-screen-smoke"
            / "Oha-Yachiyo-0.4.0-arm64"
            / "Oha-Yachiyo.app"
            / "Contents"
            / "MacOS"
            / "Oha-Yachiyo"
        )
    ]
    assert popen_calls[0]["cwd"] == str(
        tmp_path
        / "tmp"
        / "rc-screen-smoke"
        / "Oha-Yachiyo-0.4.0-arm64"
        / "Oha-Yachiyo.app"
    )
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
        "bridge_ready_dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "bridge_statuses": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "service": "oha-yachiyo",
                "version": "0.4.0",
                "native_agent_ready": True,
                "build_metadata": {
                    "commit": "def1234567890abc1234567890abc1234567890a",
                    "short_commit": "def1234",
                },
            }
        ],
        "app_launch_paths": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "app_path": "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app",
                "backend_path": (
                    "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
                    "Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend"
                ),
            }
        ],
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
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation",
        "screen_recording_permission",
    ]


def test_release_candidate_verifier_keeps_bridge_evidence_when_dmg_screen_probe_fails_after_status(
    tmp_path, monkeypatch, capsys
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")

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

    def fake_run(command, **_kwargs):
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_urlopen(url, timeout):
        if str(url).endswith("/status"):
            return FakeResponse(
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,'
                b'"native_agent_ready":true,'
                b'"build_metadata":{"commit":"fed1234567890abc1234567890abc1234567890a",'
                b'"short_commit":"fed1234"}}'
            )
        if str(url).endswith("/screen/current"):
            return FakeResponse(b'{"format":"png","width":0,"height":1080}')
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_allocate_loopback_port", lambda: 49126)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    monkeypatch.setattr(rc.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(rc.urllib.request, "urlopen", fake_urlopen)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_screen_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "DMG screen recording probe: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["dmg_screen_probe"]["status"] == "failed"
    assert report["dmg_screen_probe"]["bridge_ready_dmg_paths"] == [
        "release/Oha-Yachiyo-0.4.0-arm64.dmg"
    ]
    assert report["dmg_screen_probe"]["bridge_statuses"] == [
        {
            "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
            "service": "oha-yachiyo",
            "version": "0.4.0",
            "native_agent_ready": True,
            "build_metadata": {
                "commit": "fed1234567890abc1234567890abc1234567890a",
                "short_commit": "fed1234",
            },
        }
    ]
    assert report["dmg_screen_probe"]["app_launch_paths"] == [
        {
            "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
            "app_path": "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app",
            "backend_path": (
                "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
                "Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend"
            ),
        }
    ]
    assert report["dmg_screen_probe"]["screens"] == []
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["packaged_bridge_isolation"]["status"] == "passed"
    assert "--run-dmg-screen-smoke reached packaged /status" in manual_statuses[
        "packaged_bridge_isolation"
    ]["evidence"]
    assert manual_statuses["screen_recording_permission"]["status"] == "manual_required"
    assert "--run-dmg-screen-smoke reached packaged Bridge" in manual_statuses[
        "screen_recording_permission"
    ]["notes"]
    assert (
        "Stable app/backend paths for macOS Screen Recording permission: "
        "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/Oha-Yachiyo.app"
    ) in manual_statuses["screen_recording_permission"]["notes"]
    assert (
        "tmp/rc-screen-smoke/Oha-Yachiyo-0.4.0-arm64/"
        "Oha-Yachiyo.app/Contents/Resources/backend/oha-yachiyo-backend"
    ) in manual_statuses["screen_recording_permission"]["notes"]
    assert "release/Oha-Yachiyo-0.4.0-arm64.dmg" in manual_statuses[
        "screen_recording_permission"
    ]["notes"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 6
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation"
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
    commands: list[dict[str, object]] = []
    popen_calls: list[dict[str, object]] = []
    ports = iter((49125, 49225))

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return (
                b'{"service":"oha-yachiyo","version":"0.4.0","uptime_seconds":1,'
                b'"native_agent_ready":true,'
                b'"build_metadata":{"commit":"1234abc567890abc1234567890abc1234567890a",'
                b'"short_commit":"1234abc"}}'
            )

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
        commands.append({"command": command, "kwargs": kwargs})
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

    assert commands[0]["command"][:2] == ["hdiutil", "attach"]
    node_command = commands[1]["command"]
    assert node_command[:2] == ["node", str(rc.DMG_UI_SAMPLING_SMOKE_SCRIPT)]
    assert node_command[node_command.index("--debug-port") + 1] == "49225"
    assert commands[1]["kwargs"]["timeout"] == 190.0
    assert commands[2]["command"][:2] == ["hdiutil", "detach"]
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
        "bridge_ready_dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "bridge_statuses": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "service": "oha-yachiyo",
                "version": "0.4.0",
                "native_agent_ready": True,
                "build_metadata": {
                    "commit": "1234abc567890abc1234567890abc1234567890a",
                    "short_commit": "1234abc",
                },
            }
        ],
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
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 5
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "packaged_bridge_isolation",
        "packaged_ui_sampling",
    ]


def test_release_candidate_verifier_runs_dmg_chat_native_file_smoke(
    tmp_path, monkeypatch, capsys
):
    source_commit = "bbb1234567890abc1234567890abc1234567890a"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")
    (tmp_path / "scripts").mkdir()
    (tmp_path / rc.DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT).write_text(
        "#!/usr/bin/env node\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = Path(command[command.index("-mountpoint") + 1])
            executable = mount_dir / "Oha-Yachiyo.app" / "Contents" / "MacOS" / "Oha-Yachiyo"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
        elif command[:2] == ["node", str(rc.DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT)]:
            report_path = Path(command[command.index("--report-json") + 1])
            report_path.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "selected_file_name": "packaged-native-picker-smoke.svg",
                        "selected_file_count": 1,
                        "submitted_attachment_count": 1,
                        "run_id": "main_chat_run_packaged_native_file_smoke",
                        "task_id": "task-packaged-chat-native-file-smoke",
                        "image_viewer_verified": True,
                        "run_detail_verified": True,
                        "desktop_picker_ipc_verified": True,
                        "app_build_metadata": {
                            "commit": source_commit,
                            "short_commit": "bbb1234",
                            "version": "0.4.0",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0,
                stdout="[packaged-chat-native-file] passed\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{source_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(rc.sys, "platform", "darwin")
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_chat_native_file_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 0

    assert commands[0][:2] == ["hdiutil", "attach"]
    assert commands[1][:2] == ["node", str(rc.DMG_CHAT_NATIVE_FILE_SMOKE_SCRIPT)]
    assert commands[1][commands[1].index("--app-executable") + 1].endswith(
        "/Oha-Yachiyo.app/Contents/MacOS/Oha-Yachiyo"
    )
    assert commands[1][commands[1].index("--app-cwd") + 1].endswith("/Oha-Yachiyo.app")
    assert commands[2][:2] == ["hdiutil", "detach"]
    output = capsys.readouterr().out
    assert "DMG Chat native file smoke: passed" in output
    assert "DMG packaged build metadata revision guards: passed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["dmg_chat_native_file_smoke"] == {
        "status": "passed",
        "dmg_paths": ["release/Oha-Yachiyo-0.4.0-arm64.dmg"],
        "uploads": [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "selected_file_name": "packaged-native-picker-smoke.svg",
                "selected_file_count": 1,
                "submitted_attachment_count": 1,
                "run_id": "main_chat_run_packaged_native_file_smoke",
                "task_id": "task-packaged-chat-native-file-smoke",
                "image_viewer_verified": True,
                "run_detail_verified": True,
                "desktop_picker_ipc_verified": True,
                "app_build_metadata": {
                    "commit": source_commit,
                    "short_commit": "bbb1234",
                    "version": "0.4.0",
                },
            }
        ],
        "findings": [],
        "run_requested": True,
    }
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["chat_native_file_upload"]["status"] == "passed"
    assert manual_statuses["chat_native_file_upload"]["evidence_source"] == "automated_rc_gate"
    assert "--run-dmg-chat-native-file-smoke passed" in manual_statuses[
        "chat_native_file_upload"
    ]["evidence"]
    assert "main_chat_run_packaged_native_file_smoke" in manual_statuses[
        "chat_native_file_upload"
    ]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 6
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "chat_native_file_upload",
    ]


def test_release_candidate_verifier_rejects_stale_dmg_chat_native_file_app_metadata(
    tmp_path, monkeypatch, capsys
):
    source_commit = "1111111222222233333334444444555555566666"
    stale_commit = "bbbbbbbcccccccdddddddeeeeeeefffffffaaaaaaa"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "Oha-Yachiyo-0.4.0-arm64.dmg").write_bytes(b"fake dmg")

    def fake_source_revision_run(command, *, root):
        assert root == tmp_path
        if command == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{source_commit}\n")
        if command == ["git", "status", "--short"]:
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command!r}")

    def fake_verify_dmg_chat_native_file_upload_smoke(root, dmg_paths):
        assert root == tmp_path
        assert tuple(dmg_paths) == (Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),)
        return [], [
            {
                "dmg_path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
                "selected_file_name": "packaged-native-picker-smoke.svg",
                "selected_file_count": 1,
                "submitted_attachment_count": 1,
                "run_id": "main_chat_run_packaged_native_file_smoke",
                "task_id": "task-packaged-chat-native-file-smoke",
                "image_viewer_verified": True,
                "run_detail_verified": True,
                "desktop_picker_ipc_verified": True,
                "app_build_metadata": {
                    "commit": stale_commit,
                    "short_commit": "bbbbbbb",
                    "version": "0.4.0",
                },
            }
        ]

    monkeypatch.setattr(rc, "_run_source_revision_git_command", fake_source_revision_run)
    monkeypatch.setattr(rc, "verify_release_artifacts", lambda **_kwargs: [])
    monkeypatch.setattr(
        rc,
        "verify_dmg_chat_native_file_upload_smoke",
        fake_verify_dmg_chat_native_file_upload_smoke,
    )

    assert rc.verify_release_candidate(
        root=tmp_path,
        artifact_paths=(Path("release"),),
        run_dmg_chat_native_file_smoke=True,
        report_json=Path("tmp/rc.json"),
    ) == 1

    output = capsys.readouterr().out
    assert "DMG Chat native file smoke: passed" in output
    assert "DMG packaged build metadata revision guards: failed" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["dmg_chat_native_file_smoke"]["status"] == "failed"
    assert report["dmg_chat_native_file_smoke"]["uploads"][0]["app_build_metadata"][
        "commit"
    ] == stale_commit
    assert report["dmg_chat_native_file_smoke"]["findings"] == [
        {
            "path": "release/Oha-Yachiyo-0.4.0-arm64.dmg",
            "message": (
                "dmg_chat_native_file_smoke packaged Electron app "
                "app_build_metadata.commit bbbbbbb does not match "
                "source_revision.commit 1111111; rebuild the DMG from the "
                "current source before final signoff"
            ),
        }
    ]
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["chat_native_file_upload"]["status"] == "manual_required"
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == []


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

    findings, bridge_statuses = rc.verify_dmg_app_startup(
        tmp_path,
        (Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),),
    )

    assert findings == [
        rc.Finding(
            Path("release/Oha-Yachiyo-0.4.0-arm64.dmg"),
            "mounted Oha-Yachiyo.app must contain executable Oha-Yachiyo",
        )
    ]
    assert bridge_statuses == []


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
        {
            "command": [
                rc.sys.executable,
                str(rc.NATIVE_AGENT_FULL_CHAIN_SMOKE_SCRIPT),
            ],
            "cwd": tmp_path,
            "text": True,
        },
        {
            "command": [
                rc.sys.executable,
                str(rc.NATIVE_WORKFLOW_FULL_CHAIN_SMOKE_SCRIPT),
            ],
            "cwd": tmp_path,
            "text": True,
        },
    ]
    output = capsys.readouterr().out
    assert "real provider smoke: passed" in output
    assert "Native Agent capability matrix: incomplete" in output
    report = json.loads((tmp_path / "tmp" / "rc.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["provider_smoke"] == {
        "status": "passed",
        "checks": [
            {"label": "text_stream", "exit_code": 0, "summary": {"ok": True}},
            {"label": "tool_call_stream", "exit_code": 0, "summary": {"ok": True}},
            {"label": "native_agent_full_chain", "exit_code": 0, "summary": {"ok": True}},
            {"label": "native_workflow_full_chain", "exit_code": 0, "summary": {"ok": True}},
        ],
        "findings": [],
        "run_requested": True,
    }
    assert report["native_agent_capability_matrix"]["status"] == "incomplete"
    assert "agent_multi_tool_pipeline" in report["native_agent_capability_matrix"]["missing_capability_ids"]
    manual_statuses = {
        check["id"]: check
        for check in report["manual_release_candidate_check_statuses"]
    }
    assert manual_statuses["real_provider_smoke"]["status"] == "passed"
    assert manual_statuses["real_provider_smoke"]["evidence_source"] == "automated_rc_gate"
    assert "text_stream exit_code=0" in manual_statuses["real_provider_smoke"]["evidence"]
    assert "native_agent_full_chain exit_code=0" in manual_statuses["real_provider_smoke"]["evidence"]
    assert "native_workflow_full_chain exit_code=0" in manual_statuses["real_provider_smoke"]["evidence"]
    assert report["manual_release_candidate_check_summary"]["remaining_count"] == 6
    assert report["manual_release_candidate_check_summary"]["automated_evidence_check_ids"] == [
        "real_provider_smoke"
    ]


def test_provider_smoke_summary_omits_sensitive_json():
    summary = rc._provider_smoke_stdout_summary(
        '{"ok": true, "api_key": "sk-test-provider-smoke-secret"}\n'
    )

    assert summary == {"ok": True, "api_key": "[redacted]"}
    assert "sk-test-provider-smoke-secret" not in json.dumps(summary)


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
