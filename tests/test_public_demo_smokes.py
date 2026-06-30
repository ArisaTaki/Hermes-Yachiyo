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
    assert summary["release_level"] == "partial_demo_ready"
    assert summary["required_flow_count"] == 17
    assert summary["passed_required_flow_count"] == 11
    assert summary["missing_required_flow_ids"] == [
        "real_desktop_app_open",
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "workflow_provider",
        "studio_replay_ui",
        "workflow_ui",
    ]
    assert summary["selected_count"] == 11
    assert summary["passed_count"] == 11
    assert summary["skipped_count"] == 6
    assert [flow["id"] for flow in summary["flows"] if flow["selected"]] == [
        "data_analysis_artifact",
        "browser_research_artifact",
        "desktop_planner_discovery",
        "agent_entrypoint_desktop_execution",
        "agent_entrypoint_data_analysis",
        "agent_studio_planner_orchestration",
        "real_desktop_discovery",
        "approval_resume",
        "yachiyo_route_approval",
        "group_run",
        "workflow_run",
    ]
    assert len(commands) == 11
    entrypoint_commands = [
        command
        for command in commands
        if any("smoke_agent_entrypoint_" in part for part in command)
    ]
    assert entrypoint_commands
    assert all("--workdir" not in command for command in entrypoint_commands)
    assert any(action["id"] == "real_desktop_app_open" for action in summary["next_actions"])
    blocker = next(
        item for item in summary["release_blockers"] if item["id"] == "real_desktop_app_open"
    )
    assert blocker["status"] == "skipped"
    assert blocker["opt_in_flag"] == "--include-real-desktop-open"


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
    assert summary["release_level"] == "planned"
    assert summary["selected_count"] == summary["flow_count"]
    assert {flow["status"] for flow in summary["flows"]} == {"planned"}
    assert set(summary["missing_required_flow_ids"]) == {
        flow["id"] for flow in summary["flows"]
    }


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
    assert summary["release_level"] == "full_public_demo_ready"
    assert summary["passed_required_flow_count"] == summary["required_flow_count"] == 17
    assert summary["missing_required_flow_ids"] == []
    assert summary["release_blockers"] == []
    assert summary["selected_count"] == summary["flow_count"] == 17
    assert summary["skipped_count"] == 0
    assert len(commands) == 17
    assert any(
        command[:2] == ["node", "scripts/smoke_agent_run_detail_ui.mjs"]
        and "--report-json" in command
        for command in commands
    )
    assert any(
        command[:2] == ["node", "scripts/smoke_workflow_save_run_ui.mjs"]
        and "--report-json" in command
        for command in commands
    )


def test_public_demo_smokes_real_desktop_open_can_be_opted_in_separately(
    tmp_path,
    monkeypatch,
):
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
        include_real_desktop_open=True,
    )

    selected_ids = [flow["id"] for flow in summary["flows"] if flow["selected"]]
    assert "real_desktop_app_open" in selected_ids
    assert "real_desktop_ui_inspection" not in selected_ids
    assert "real_desktop_interaction" not in selected_ids
    assert summary["selected_count"] == 12
    assert summary["passed_count"] == 12
    assert any("smoke_real_desktop_app_open.py" in part for command in commands for part in command)
    assert not any(
        "smoke_real_desktop_interaction.py" in part
        for command in commands
        for part in command
    )


def test_public_demo_smokes_cli_accepts_granular_real_desktop_open_flag(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    output_json = tmp_path / "tmp" / "demo-open.json"

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
            "--include-real-desktop-open",
            "--output-json",
            str(output_json),
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    selected_ids = [flow["id"] for flow in payload["flows"] if flow["selected"]]
    assert "real_desktop_app_open" in selected_ids
    assert "real_desktop_ui_inspection" not in selected_ids
    assert "real_desktop_interaction" not in selected_ids


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
    assert summary["passed_count"] == 10
    assert summary["skipped_count"] == 7
    assert summary["release_level"] == "partial_demo_ready"
    assert "real_desktop_discovery" in summary["missing_required_flow_ids"]
    assert any(action["id"] == "real_desktop_discovery" for action in summary["next_actions"])


def test_public_demo_smokes_projects_provider_missing_env_as_skipped_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ok": True, "mode": report.stem}
            if report.name == "workflow-provider.json":
                payload = {
                    "ok": False,
                    "skipped": True,
                    "mode": "native_workflow_full_chain_smoke",
                    "stage": "provider_credentials",
                    "reason": "provider_smoke_credentials_missing",
                    "blocking_condition": "provider_smoke_credentials_missing",
                    "blocking_conditions": ["provider_smoke_credentials_missing"],
                    "missing_env": [
                        "OHA_YACHIYO_SMOKE_BASE_URL",
                        "OHA_YACHIYO_SMOKE_MODEL",
                        "OHA_YACHIYO_SMOKE_API_KEY",
                    ],
                    "recovery_hints": [
                        "Configure OHA_YACHIYO_SMOKE_* credentials.",
                    ],
                }
            report.write_text(json.dumps(payload), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(
        tmp_dir="tmp/demo",
        include_provider_workflow=True,
    )

    provider = next(flow for flow in summary["flows"] if flow["id"] == "workflow_provider")
    assert provider["selected"] is True
    assert provider["status"] == "skipped"
    assert provider["evidence_skipped"] is True
    assert provider["evidence_summary"]["blocking_condition"] == (
        "provider_smoke_credentials_missing"
    )
    assert provider["evidence_summary"]["missing_env"] == [
        "OHA_YACHIYO_SMOKE_BASE_URL",
        "OHA_YACHIYO_SMOKE_MODEL",
        "OHA_YACHIYO_SMOKE_API_KEY",
    ]
    assert summary["ok"] is True
    assert summary["release_level"] == "partial_demo_ready"
    assert "workflow_provider" in summary["missing_required_flow_ids"]
    blocker = next(
        item for item in summary["release_blockers"] if item["id"] == "workflow_provider"
    )
    assert blocker["reason"] == "provider_smoke_credentials_missing"
    assert blocker["evidence_summary"]["missing_env"] == [
        "OHA_YACHIYO_SMOKE_BASE_URL",
        "OHA_YACHIYO_SMOKE_MODEL",
        "OHA_YACHIYO_SMOKE_API_KEY",
    ]
    action = next(item for item in summary["next_actions"] if item["id"] == "workflow_provider")
    assert action["status"] == "skipped"
    assert action["reason"] == "provider_smoke_credentials_missing"


def test_public_demo_smokes_marks_selected_failure_as_release_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ok": report.name != "browser-research-artifact.json"}
            if report.name == "browser-research-artifact.json":
                payload.update(
                    {
                        "mode": "browser_research_artifact_smoke",
                        "stage": "browser_planner",
                        "error": "desktop_session_locked",
                        "blocking_condition": "desktop_session_locked",
                        "blocking_conditions": [
                            "desktop_session_locked",
                            "screen_capture_blank",
                        ],
                        "checks": {"desktop_session_ready": False},
                    }
                )
            report.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(tmp_dir="tmp/demo")

    assert summary["ok"] is False
    assert summary["status"] == "failed"
    assert summary["release_level"] == "blocked"
    assert "browser_research_artifact" in summary["missing_required_flow_ids"]
    blocker = next(
        item for item in summary["release_blockers"] if item["id"] == "browser_research_artifact"
    )
    assert blocker["status"] == "failed"
    assert blocker["reason"] == "desktop_session_locked, screen_capture_blank"
    assert blocker["evidence_summary"]["blocking_condition"] == "desktop_session_locked"
    assert blocker["evidence_summary"]["blocking_conditions"] == [
        "desktop_session_locked",
        "screen_capture_blank",
    ]
    assert blocker["evidence_summary"]["checks"] == {"desktop_session_ready": False}
    action = next(
        item for item in summary["next_actions"] if item["id"] == "browser_research_artifact"
    )
    assert action["reason"] == "desktop_session_locked, screen_capture_blank"
    markdown = demo.render_markdown(summary)
    assert "Blocker: `desktop_session_locked, screen_capture_blank`" in markdown


def test_public_demo_smokes_does_not_reuse_stale_report_after_failed_flow(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    stale_report = tmp_path / "tmp" / "demo" / "browser-research-artifact.json"
    stale_report.parent.mkdir(parents=True, exist_ok=True)
    stale_report.write_text(
        json.dumps({"ok": True, "mode": "stale-success"}),
        encoding="utf-8",
    )

    def fake_run(command):
        command = list(command)
        if "scripts/smoke_browser_planner_artifacts.py" in command:
            return _fake_completed(command, returncode=1)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"ok": True}), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(tmp_dir="tmp/demo")

    flow = next(flow for flow in summary["flows"] if flow["id"] == "browser_research_artifact")
    assert flow["status"] == "failed"
    assert flow["evidence_ok"] is False
    assert flow["evidence_summary"] == {}
    assert not stale_report.exists()


def test_public_demo_smokes_records_ui_evidence_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        if "--report-json" in command:
            report = tmp_path / command[command.index("--report-json") + 1]
            if not report.is_absolute():
                report = tmp_path / report
            report.parent.mkdir(parents=True, exist_ok=True)
            payload = {"ok": True, "mode": report.stem}
            if report.name == "studio-replay-ui.json":
                payload = {
                    "ok": True,
                    "mode": "agent_run_detail_ui_smoke",
                    "stage": "completed",
                    "checks": {
                        "electron_smoke_completed": True,
                        "run_event_pagination_verified": True,
                    },
                }
            elif report.name == "workflow-ui.json":
                payload = {
                    "ok": True,
                    "mode": "workflow_save_run_ui_smoke",
                    "stage": "completed",
                    "checks": {
                        "electron_smoke_completed": True,
                        "bridge_contract_verified": True,
                    },
                }
            report.write_text(json.dumps(payload), encoding="utf-8")
        return _fake_completed(command)

    monkeypatch.setattr(demo, "_run_command", fake_run)

    summary = demo.run_public_demo_smokes(
        tmp_dir="tmp/demo",
        include_real_desktop=True,
        include_provider_workflow=True,
        include_ui=True,
    )

    studio = next(flow for flow in summary["flows"] if flow["id"] == "studio_replay_ui")
    workflow = next(flow for flow in summary["flows"] if flow["id"] == "workflow_ui")
    assert studio["report_json"].endswith("studio-replay-ui.json")
    assert workflow["report_json"].endswith("workflow-ui.json")
    assert studio["evidence_mode"] == "agent_run_detail_ui_smoke"
    assert workflow["evidence_mode"] == "workflow_save_run_ui_smoke"
    assert studio["evidence_summary"]["stage"] == "completed"
    assert workflow["evidence_summary"]["stage"] == "completed"
    assert studio["evidence_summary"]["checks"] == {
        "electron_smoke_completed": True,
        "run_event_pagination_verified": True,
    }
    assert workflow["evidence_summary"]["checks"] == {
        "electron_smoke_completed": True,
        "bridge_contract_verified": True,
    }


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
    assert payload["release_level"] == "partial_demo_ready"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "# Oha-Yachiyo Public Demo Smoke Summary" in markdown
    assert "Release level: partial_demo_ready" in markdown
    assert "## Release Blockers" in markdown
    assert "`data_analysis_artifact`" in markdown
