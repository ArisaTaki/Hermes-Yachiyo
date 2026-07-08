from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts import run_public_release_gate as gate


def _completed(command: list[str], *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=f"ran {' '.join(command)}\n",
        stderr="",
    )


def _write_public_demo_report(command: list[str], *, release_level: str) -> None:
    if "scripts/run_public_demo_smokes.py" not in command:
        return
    output_json = command[command.index("--output-json") + 1]
    missing_flow_ids = (
        []
        if release_level == "full_public_demo_ready"
        else ["studio_replay_ui", "workflow_ui"]
    )
    required_flow_count = len(gate._public_demo_required_flow_ids([]))
    passed_flow_count = required_flow_count - len(missing_flow_ids)
    payload = {
        "ok": True,
        "status": "passed" if release_level == "full_public_demo_ready" else "partial",
        "release_level": release_level,
        "complete": release_level == "full_public_demo_ready",
        "selected_count": passed_flow_count,
        "passed_count": passed_flow_count,
        "required_flow_count": required_flow_count,
        "passed_required_flow_count": passed_flow_count,
        "missing_required_flow_ids": missing_flow_ids,
        "release_blockers": []
        if release_level == "full_public_demo_ready"
        else [
            {
                "id": "studio_replay_ui",
                "status": "skipped",
                "opt_in_flag": "--include-ui",
                "opt_in_reason": "starts Vite and Electron UI smoke",
                "reason": "ui_smoke_not_collected",
                "evidence_summary": {
                    "stage": "ui_smoke",
                    "blocking_condition": "ui_smoke_not_collected",
                },
            }
        ],
        "full_demo_command": "python scripts/run_public_demo_smokes.py --full-demo",
        "flows": [{"id": "workflow_run", "status": "passed"}],
    }
    output_path = gate._resolve_path(Path(output_json))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_release_smoke_report(command: list[str], *, ok: bool) -> None:
    if "scripts/summarize_release_smoke.py" not in command:
        return
    output_json = command[command.index("--output-json") + 1]
    missing_item_ids = [
        "packaged_launch",
        "chat_desktop_task",
        "approval_card",
        "agent_studio_run_timeline",
        "group_run",
        "workflow",
        "artifact_readback",
        "diagnostics_export",
    ]
    if "--diagnostics-zip" in command:
        missing_item_ids.remove("diagnostics_export")
    payload = {
        "ok": ok,
        "status": "passed" if ok else "incomplete",
        "item_count": 10,
        "passed_count": 10 if ok else 10 - len(missing_item_ids),
        "missing_count": 0 if ok else len(missing_item_ids),
        "missing_item_ids": [] if ok else missing_item_ids,
        "items": [],
        "next_actions": []
        if ok
        else [
            {
                "id": "packaged_launch",
                "command": "python scripts/verify_release_candidate.py --require-artifacts",
            }
        ],
    }
    output_path = gate._resolve_path(Path(output_json))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload), encoding="utf-8")


def _write_diagnostics_bundle(command: list[str]) -> None:
    if "scripts/collect_release_diagnostics.py" not in command:
        return
    output_zip = command[command.index("--output-zip") + 1]
    output_path = gate._resolve_path(Path(output_zip))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "ok": True,
        "included_count": 1,
        "skipped_count": 0,
        "redaction": {"applied": True},
        "included": [{"source": "tmp/gate/public-demo.json"}],
    }
    with zipfile.ZipFile(output_path, "w") as archive:
        archive.writestr("diagnostics/manifest.json", json.dumps(manifest))


def _write_public_demo_batch_report(
    path: Path,
    *,
    passed_flow_ids: set[str],
    failed_flow_ids: set[str] | None = None,
) -> None:
    failed_flow_ids = failed_flow_ids or set()
    required_flow_ids = gate._public_demo_required_flow_ids([])
    missing_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id not in passed_flow_ids
    ]
    blockers = []
    for flow_id in missing_flow_ids:
        status = "failed" if flow_id in failed_flow_ids else "skipped"
        blockers.append(
            {
                "id": flow_id,
                "status": status,
                "category": "real_desktop" if flow_id.startswith("real_desktop_") else "",
                "opt_in_flag": {
                    "real_desktop_app_open": "--include-real-desktop-open",
                    "real_desktop_ui_inspection": "--include-real-desktop-ui-inspection",
                    "real_desktop_interaction": "--include-real-desktop-interaction",
                }.get(flow_id, ""),
                "reason": "screen_capture_blank" if status == "failed" else "not collected",
                "evidence_summary": {
                    "blocking_condition": "screen_capture_blank",
                }
                if status == "failed"
                else {},
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": not failed_flow_ids,
                "status": "failed" if failed_flow_ids else "partial",
                "release_level": "blocked" if failed_flow_ids else "partial_demo_ready",
                "complete": False,
                "selected_count": len(passed_flow_ids),
                "passed_count": len(passed_flow_ids),
                "required_flow_count": len(required_flow_ids),
                "passed_required_flow_count": len(passed_flow_ids),
                "missing_required_flow_ids": missing_flow_ids,
                "release_blockers": blockers,
                "flows": [
                    {
                        "id": flow_id,
                        "status": "passed"
                        if flow_id in passed_flow_ids
                        else "failed"
                        if flow_id in failed_flow_ids
                        else "skipped",
                        "category": "real_desktop"
                        if flow_id.startswith("real_desktop_")
                        else "source",
                        "opt_in_flag": {
                            "real_desktop_app_open": "--include-real-desktop-open",
                            "real_desktop_ui_inspection": "--include-real-desktop-ui-inspection",
                            "real_desktop_interaction": "--include-real-desktop-interaction",
                        }.get(flow_id, ""),
                    }
                    for flow_id in required_flow_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def test_public_release_gate_defaults_to_safe_preflight_with_demo_blockers(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_public_demo_report(command, release_level="partial_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(tmp_dir="tmp/gate")

    assert summary["ok"] is True
    assert summary["release_ready"] is False
    assert summary["status"] == "needs_release_evidence"
    assert summary["check_count"] == 8
    assert summary["failed_count"] == 0
    assert [command[:2] for command in commands[:2]] == [
        [sys.executable, "scripts/verify_release_artifacts.py"],
        [sys.executable, "scripts/verify_secret_redaction.py"],
    ]
    assert any(
        "scripts/summarize_agent_market_parity.py" in command
        for command in commands
    )
    assert any(
        "scripts/smoke_planner_runtime_tool_parity.py" in command
        for command in commands
    )
    oha_product_command = next(
        command for command in commands if "scripts/smoke_oha_desktop_agent_release.py" in command
    )
    assert oha_product_command[oha_product_command.index("--report-json") + 1] == str(
        tmp_path / "tmp" / "gate" / "oha-desktop-agent-release-smoke.json"
    )
    release_pytest_command = next(command for command in commands if "pytest" in command)
    assert "tests/test_public_release_gate.py" in release_pytest_command
    public_demo_command = next(
        command for command in commands if "scripts/run_public_demo_smokes.py" in command
    )
    assert public_demo_command[public_demo_command.index("--tmp-dir") + 1] == str(
        tmp_path / "tmp" / "gate"
    )
    diagnostics_command = next(
        command for command in commands if "scripts/collect_release_diagnostics.py" in command
    )
    assert diagnostics_command[diagnostics_command.index("--include") + 1] == str(
        tmp_path / "tmp" / "gate"
    )
    assert diagnostics_command[diagnostics_command.index("--output-zip") + 1] == str(
        tmp_path / "tmp" / "gate" / "diagnostics.zip"
    )
    release_smoke_command = next(
        command for command in commands if "scripts/summarize_release_smoke.py" in command
    )
    assert str(
        tmp_path / "tmp" / "gate" / "oha-desktop-agent-release-smoke.json"
    ) in release_smoke_command
    assert str(tmp_path / "tmp" / "gate" / "diagnostics.zip") in release_smoke_command
    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["release_level"] == "partial_demo_ready"
    assert public_demo["missing_required_flow_ids"] == ["studio_replay_ui", "workflow_ui"]
    assert public_demo["release_blockers"][0]["reason"] == "ui_smoke_not_collected"
    assert summary["public_demo"]["release_level"] == "partial_demo_ready"
    assert summary["public_demo"]["passed_required_flow_count"] == 14
    assert summary["public_demo"]["required_flow_count"] == 16
    assert summary["public_demo"]["remaining_required_flow_count"] == 2
    ui_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_ui"
    )
    assert ui_action["command"] == (
        "python scripts/run_public_demo_smokes.py --include-ui "
        "--output-json tmp/public-demo-smokes-ui-missing.json "
        "--output-markdown tmp/public-demo-smokes-ui-missing.md"
    )
    assert summary["release_smoke"]["status"] == "incomplete"
    assert "packaged_launch" in summary["release_smoke"]["missing_item_ids"]
    assert "diagnostics_export" not in summary["release_smoke"]["missing_item_ids"]
    assert any(action["id"] == "packaged_launch" for action in summary["next_actions"])
    assert summary["progress"]["stage"] == "release_evidence"
    assert summary["progress"]["automated_checks"] == {"passed": 8, "total": 8}
    assert summary["progress"]["public_demo"] == {"passed": 14, "total": 16}
    assert summary["progress"]["release_smoke"] == {"passed": 3, "total": 10}
    assert summary["progress"]["external_blocked"] is False


def test_public_release_gate_strict_mode_fails_until_release_ready(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    output_json = tmp_path / "tmp" / "gate.json"
    output_markdown = tmp_path / "tmp" / "gate.md"

    def fake_run(command):
        command = list(command)
        _write_public_demo_report(command, release_level="partial_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    exit_code = gate.main(
        [
            "--tmp-dir",
            "tmp/gate",
            "--require-release-ready",
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    assert exit_code == 1
    assert capsys.readouterr().out == ""
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["status"] == "needs_release_evidence"
    assert payload["release_smoke"]["status"] == "incomplete"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "Public demo: 14/16 required flows (`partial_demo_ready`)" in markdown
    assert "Release level: `partial_demo_ready`" in markdown
    assert "## Release Smoke" in markdown
    assert "Demo blocker `studio_replay_ui`: `ui_smoke_not_collected`" in markdown
    assert "Progress stage: `release_evidence`" in markdown
    assert "Code progress: 73.5% (26.5% remaining)" in markdown
    assert "--include-ui" in markdown
    assert "tmp/public-demo-smokes-ui-missing.json" in markdown
    assert "--include-real-desktop --include-provider-workflow --include-ui" not in markdown


def test_public_release_gate_passes_when_full_release_smoke_is_present(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_public_demo_report(command, release_level="full_public_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=True)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        require_release_ready=True,
    )

    assert summary["ok"] is True
    assert summary["release_ready"] is True
    assert summary["status"] == "ready"
    assert summary["include_isolated_provider_smoke"] is True
    assert summary["release_blocker_count"] == 0
    assert summary["next_actions"] == []
    assert summary["progress"]["stage"] == "ready"
    assert summary["progress"]["code_completion_percent"] == 100.0
    assert summary["progress"]["release_completion_percent"] == 100.0
    oha_product_command = next(
        command
        for command in commands
        if "scripts/smoke_oha_desktop_agent_release.py" in command
    )
    assert "--run-isolated-provider-smoke" in oha_product_command


def test_public_release_gate_reports_failed_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        _write_public_demo_report(command, release_level="full_public_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=True)
        return _completed(
            command,
            returncode=1
            if command[:2] == [sys.executable, "scripts/verify_secret_redaction.py"]
            else 0,
        )

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(tmp_dir="tmp/gate")

    assert summary["ok"] is False
    assert summary["status"] == "failed"
    failed = next(item for item in summary["checks"] if item["id"] == "secret_redaction")
    assert failed["status"] == "failed"
    action = next(item for item in summary["next_actions"] if item["id"] == "secret_redaction")
    assert "verify_secret_redaction.py" in action["command"]


def test_public_release_gate_accepts_existing_release_smoke_sources(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        release_smoke_reports=["tmp/source-capabilities.json"],
        diagnostics_zips=["tmp/diagnostics.zip"],
    )

    release_smoke_command = next(
        command for command in commands if "scripts/summarize_release_smoke.py" in command
    )
    assert str(tmp_path / "tmp" / "source-capabilities.json") in release_smoke_command
    assert "--diagnostics-zip" in release_smoke_command
    assert str(tmp_path / "tmp" / "diagnostics.zip") in release_smoke_command
    assert summary["release_smoke"]["status"] == "incomplete"


def test_public_release_gate_accepts_existing_public_demo_reports(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "public-demo-ui.json"
    passed_flow_ids = set(gate._public_demo_required_flow_ids([]))
    passed_flow_ids.remove("studio_replay_ui")
    _write_public_demo_batch_report(
        report_path,
        passed_flow_ids=passed_flow_ids,
        failed_flow_ids={"studio_replay_ui"},
    )
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        include_release_smoke=False,
        include_diagnostics_bundle=False,
        public_demo_reports=["tmp/public-demo-ui.json"],
    )

    assert not any("scripts/run_public_demo_smokes.py" in command for command in commands)
    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["release_level"] == "blocked"
    assert "real_desktop_app_open" not in public_demo["missing_required_flow_ids"]
    assert public_demo["missing_required_flow_ids"] == ["studio_replay_ui"]
    ui_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_ui"
    )
    assert "--include-ui" in ui_action["command"]


def test_public_release_gate_does_not_double_count_public_demo_release_smoke_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "public-demo.json"
    passed_flow_ids = set(gate._public_demo_required_flow_ids([]))
    missing_flow_ids = {
        "studio_replay_ui",
    }
    passed_flow_ids.difference_update(missing_flow_ids)
    _write_public_demo_batch_report(
        report_path,
        passed_flow_ids=passed_flow_ids,
        failed_flow_ids=missing_flow_ids,
    )

    def fake_run(command):
        command = list(command)
        if "scripts/summarize_release_smoke.py" in command:
            output_json = command[command.index("--output-json") + 1]
            output_path = gate._resolve_path(Path(output_json))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "status": "incomplete",
                        "item_count": 10,
                        "passed_count": 9,
                        "missing_count": 1,
                        "missing_item_ids": ["public_demo"],
                        "items": [],
                        "next_actions": [
                            {
                                "id": "public_demo",
                                "command": "python scripts/run_public_demo_smokes.py --full-demo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        include_diagnostics_bundle=False,
        public_demo_reports=["tmp/public-demo.json"],
    )

    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["missing_required_flow_ids"] == ["studio_replay_ui"]
    assert summary["release_smoke"]["missing_item_ids"] == ["public_demo"]
    assert summary["release_blocker_count"] == len(public_demo["release_blockers"]) == 1
    assert summary["external_requirement_count"] == 0
    assert summary["external_requirements"] == []


def test_public_release_gate_keeps_more_informative_public_demo_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    required_flow_ids = gate._public_demo_required_flow_ids([])
    passed_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id != "studio_replay_ui"
    ]
    generic_path = tmp_path / "tmp" / "public-demo-generic.json"
    detailed_path = tmp_path / "tmp" / "public-demo-detailed.json"
    base_report = {
        "ok": True,
        "status": "partial",
        "release_level": "partial_demo_ready",
        "complete": False,
        "selected_count": len(passed_flow_ids),
        "passed_count": len(passed_flow_ids),
        "required_flow_count": len(required_flow_ids),
        "passed_required_flow_count": len(passed_flow_ids),
        "missing_required_flow_ids": ["studio_replay_ui"],
        "flows": [
            {
                "id": flow_id,
                "status": "passed" if flow_id in passed_flow_ids else "skipped",
            }
            for flow_id in required_flow_ids
        ],
    }
    generic_path.parent.mkdir(parents=True, exist_ok=True)
    generic_path.write_text(
        json.dumps(
            {
                **base_report,
                "release_blockers": [
                    {
                        "id": "studio_replay_ui",
                        "status": "skipped",
                        "reason": "ui_smoke_not_collected",
                        "opt_in_flag": "--include-ui",
                        "opt_in_reason": "starts Vite and Electron UI smoke",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    detailed_path.write_text(
        json.dumps(
            {
                **base_report,
                "release_blockers": [
                    {
                        "id": "studio_replay_ui",
                        "status": "skipped",
                        "reason": "electron_ui_smoke_failed",
                        "opt_in_flag": "--include-ui",
                        "opt_in_reason": "starts Vite and Electron UI smoke",
                        "evidence_summary": {
                            "blocking_condition": "electron_ui_smoke_failed",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        include_release_smoke=False,
        include_diagnostics_bundle=False,
        public_demo_reports=[
            "tmp/public-demo-generic.json",
            "tmp/public-demo-detailed.json",
        ],
    )

    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    blocker = next(
        item for item in public_demo["release_blockers"] if item["id"] == "studio_replay_ui"
    )
    assert blocker["reason"] == "electron_ui_smoke_failed"
    assert summary["external_requirement_count"] == 0
    assert summary["external_requirements"] == []
    markdown = gate.render_markdown(summary)
    assert "Release blockers: 1" in markdown
    assert "External requirements: 0" in markdown
    assert "## External Requirements" not in markdown
    assert "scripts/run_public_demo_smokes.py --include-ui" in markdown


def test_public_release_gate_reports_workflow_provider_smoke_external_requirement(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    for env_name in gate.PROVIDER_SMOKE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    def fake_run(command):
        command = list(command)
        if "scripts/summarize_release_smoke.py" in command:
            output_json = command[command.index("--output-json") + 1]
            output_path = gate._resolve_path(Path(output_json))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "status": "incomplete",
                        "item_count": 10,
                        "passed_count": 9,
                        "missing_count": 1,
                        "missing_item_ids": ["workflow"],
                        "items": [],
                        "next_actions": [
                            {
                                "id": "workflow",
                                "command": (
                                    "python scripts/verify_release_candidate.py "
                                    "--require-artifacts --check-dmg-mount "
                                    "--run-provider-smoke "
                                    "--report-json tmp/rc-verification-provider-smoke.json"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        include_diagnostics_bundle=False,
    )

    assert summary["release_smoke"]["missing_item_ids"] == ["workflow"]
    assert summary["external_requirement_count"] == 1
    assert summary["progress"]["stage"] == "external_requirements"
    assert summary["progress"]["external_blocked"] is True
    assert summary["progress"]["release_smoke"] == {"passed": 9, "total": 10}
    requirement = summary["external_requirements"][0]
    assert requirement["id"] == "provider_smoke_credentials"
    assert requirement["kind"] == "provider_credentials"
    assert requirement["missing_env"] == list(gate.PROVIDER_SMOKE_ENV_VARS)
    assert requirement["blocking_conditions"] == ["provider_smoke_credentials_missing"]
    markdown = gate.render_markdown(summary)
    assert "External requirements: 1" in markdown
    assert "Provider Workflow smoke credentials" in markdown
    assert "`OHA_YACHIYO_SMOKE_API_KEY`" in markdown


def test_public_release_gate_markdown_defaults_missing_blocker_counts():
    markdown = gate.render_markdown(
        {
            "status": "needs_release_evidence",
            "release_ready": False,
            "passed_count": 0,
            "check_count": 0,
            "checks": [],
        }
    )

    assert "Release blockers: 0" in markdown
    assert "External requirements: 0" in markdown
    assert "None" not in markdown


def test_public_release_gate_reports_stale_external_release_reports(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "_current_git_commit", lambda: "b" * 40)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_release_smoke_report(command, ok=True)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)
    report_path = tmp_path / "tmp" / "old-rc.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "source_revision": {
                    "commit": "a" * 40,
                    "short_commit": "aaaaaaa",
                }
            }
        ),
        encoding="utf-8",
    )

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_public_demo=False,
        include_diagnostics_bundle=False,
        release_smoke_reports=["tmp/old-rc.json"],
    )

    assert summary["ok"] is True
    assert summary["release_ready"] is False
    assert summary["release_blocker_count"] == 1
    freshness = next(
        item for item in summary["checks"] if item["id"] == "external_report_freshness"
    )
    assert freshness["status"] == "passed"
    assert freshness["release_blockers"][0]["status"] == "stale"
    assert "old-rc.json was generated for aaaaaaaa" in freshness["release_blockers"][0]["reason"]
    action = next(
        item for item in summary["next_actions"] if item["id"] == "external_report_freshness"
    )
    assert "verify_release_candidate.py" in action["command"]
    release_smoke_command = next(
        command for command in commands if "scripts/summarize_release_smoke.py" in command
    )
    assert str(report_path) not in release_smoke_command


def test_public_release_gate_passes_granular_real_desktop_demo_flags(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_public_demo_report(command, release_level="partial_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_real_desktop_open=True,
        include_ui=True,
    )

    public_demo_command = next(
        command for command in commands if "scripts/run_public_demo_smokes.py" in command
    )
    assert "--include-real-desktop-open" in public_demo_command
    assert "--include-ui" in public_demo_command
    assert "--include-real-desktop" not in public_demo_command
    assert "--include-real-desktop-ui-inspection" not in public_demo_command
    assert "--include-real-desktop-interaction" not in public_demo_command
    ui_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_ui"
    )
    assert not any(
        item["id"] == "public_demo_real_desktop"
        for item in summary["next_actions"]
    )
    assert "--include-ui" in ui_action["command"]
    assert summary["status"] == "needs_release_evidence"


def test_public_release_gate_can_request_isolated_provider_smoke(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_public_demo_report(command, release_level="partial_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_isolated_provider_smoke=True,
    )

    oha_product_command = next(
        command
        for command in commands
        if "scripts/smoke_oha_desktop_agent_release.py" in command
    )
    assert "--run-isolated-provider-smoke" in oha_product_command


def test_public_release_gate_passes_allow_existing_real_desktop_app_flag(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        command = list(command)
        commands.append(command)
        _write_public_demo_report(command, release_level="partial_demo_ready")
        _write_diagnostics_bundle(command)
        _write_release_smoke_report(command, ok=False)
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    gate.run_public_release_gate(
        tmp_dir="tmp/gate",
        include_real_desktop_interaction=True,
        allow_existing_real_desktop_app=True,
    )

    public_demo_command = next(
        command for command in commands if "scripts/run_public_demo_smokes.py" in command
    )
    assert "--include-real-desktop-interaction" in public_demo_command
    assert "--allow-existing-real-desktop-app" in public_demo_command


def test_public_release_gate_next_action_suggests_allow_existing_real_desktop_app():
    actions = gate._public_demo_next_actions(
        {
            "status": "passed",
            "release_level": "blocked",
            "missing_required_flow_ids": ["real_desktop_interaction"],
            "release_blockers": [
                {
                    "id": "real_desktop_interaction",
                    "category": "real_desktop",
                    "status": "failed",
                    "opt_in_flag": "--include-real-desktop-interaction",
                    "reason": "app_already_running",
                    "evidence_summary": {"error": "app_already_running"},
                }
            ],
        }
    )

    assert len(actions) == 1
    assert actions[0]["id"] == "public_demo_real_desktop"
    assert "--include-real-desktop-interaction" in actions[0]["command"]
    assert "--allow-existing-real-desktop-app" in actions[0]["command"]


def test_public_release_gate_public_demo_next_action_falls_back_for_unknown_flow():
    command = gate._public_demo_next_command(
        {
            "release_level": "partial_demo_ready",
            "missing_required_flow_ids": ["unknown_demo_flow"],
            "release_blockers": [{"id": "unknown_demo_flow"}],
        }
    )

    assert command == gate._full_demo_command()
