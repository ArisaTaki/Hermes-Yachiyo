from __future__ import annotations

import json
import subprocess

from scripts import run_public_demo_smokes as demo


def _fake_completed(command: list[str], *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=f"ran {' '.join(command)}\n",
        stderr="",
    )


def test_public_demo_smokes_default_runs_source_flows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps({"ok": True, "mode": report.stem}),
                encoding="utf-8",
            )
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(tmp_dir="tmp/demo")

    assert summary["ok"] is True
    assert summary["complete"] is False
    assert summary["status"] == "partial"
    assert summary["selected_count"] == 7
    assert summary["passed_count"] == 7
    assert summary["skipped_count"] == 6
    assert [flow["id"] for flow in summary["flows"] if flow["selected"]] == [
        "data_analysis_artifact",
        "browser_research_artifact",
        "desktop_planner_discovery",
        "real_desktop_discovery",
        "approval_resume",
        "group_run",
        "workflow_run",
    ]
    assert len(commands) == 7
    assert any(action["id"] == "real_desktop_app_open" for action in summary["next_actions"])


def test_public_demo_smokes_plan_only_does_not_run_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def fail_run(command):
        raise AssertionError(f"plan-only should not run {command}")

    monkeypatch.setattr(demo, "_run_command", fail_run)

    summary = demo.run_public_demo_smokes(
        tmp_dir="tmp/demo",
        include_real_desktop=True,
        include_provider_workflow=True,
        include_ui=True,
        plan_only=True,
    )

    assert summary["ok"] is False
    assert summary["complete"] is False
    assert summary["status"] == "planned"
    assert summary["selected_count"] == summary["flow_count"]
    assert {flow["status"] for flow in summary["flows"]} == {"planned"}


def test_public_demo_smokes_opt_in_selects_all_flows(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"ok": True}), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(
        tmp_dir="tmp/demo",
        include_real_desktop=True,
        include_provider_workflow=True,
        include_ui=True,
    )

    assert summary["ok"] is True
    assert summary["complete"] is True
    assert summary["status"] == "passed"
    assert summary["selected_count"] == summary["flow_count"] == 13
    assert summary["skipped_count"] == 0
    assert len(commands) == 13
    assert ["node", "scripts/smoke_agent_run_detail_ui.mjs"] in commands


def test_public_demo_smokes_records_selected_skipped_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ok": True, "mode": report.stem}
            if "real-desktop-discovery" in report.name:
                payload.update(
                    {
                        "skipped": True,
                        "reason": "real desktop discovery smoke only runs on macOS",
                    }
                )
            report.write_text(json.dumps(payload), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(tmp_dir="tmp/demo")

    real_desktop = next(
        flow for flow in summary["flows"] if flow["id"] == "real_desktop_discovery"
    )
    assert real_desktop["selected"] is True
    assert real_desktop["status"] == "skipped"
    assert real_desktop["evidence_skipped"] is True
    assert summary["ok"] is True
    assert summary["complete"] is False
    assert summary["passed_count"] == 6
    assert summary["skipped_count"] == 7
    assert any(action["id"] == "real_desktop_discovery" for action in summary["next_actions"])


def test_public_demo_smokes_cli_writes_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    output_json = tmp_path / "tmp" / "demo.json"
    output_markdown = tmp_path / "tmp" / "demo.md"

    def fake_run(command):
        command = list(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"ok": True}), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    exit_code = demo.main(
        [
            "--tmp-dir",
            "tmp/demo",
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "# Oha-Yachiyo Public Demo Smoke Summary" in markdown
    assert "`data_analysis_artifact`" in markdown
