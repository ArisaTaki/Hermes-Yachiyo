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
    payload = {
        "ok": True,
        "status": "passed" if release_level == "full_public_demo_ready" else "partial",
        "release_level": release_level,
        "complete": release_level == "full_public_demo_ready",
        "selected_count": 17 if release_level == "full_public_demo_ready" else 11,
        "passed_count": 17 if release_level == "full_public_demo_ready" else 11,
        "required_flow_count": 17,
        "passed_required_flow_count": 17 if release_level == "full_public_demo_ready" else 11,
        "missing_required_flow_ids": []
        if release_level == "full_public_demo_ready"
        else ["real_desktop_interaction", "workflow_provider"],
        "release_blockers": []
        if release_level == "full_public_demo_ready"
        else [
            {
                "id": "real_desktop_interaction",
                "status": "failed",
                "opt_in_flag": "--include-real-desktop-interaction",
                "opt_in_reason": "types and clicks in a real macOS application",
                "reason": "desktop_session_locked",
                "evidence_summary": {
                    "stage": "session_preflight",
                    "blocking_condition": "desktop_session_locked",
                    "checks": {"desktop_session_ready": False},
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
        "item_count": 9,
        "passed_count": 9 if ok else 9 - len(missing_item_ids),
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
    assert summary["check_count"] == 7
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
    assert str(tmp_path / "tmp" / "gate" / "diagnostics.zip") in release_smoke_command
    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["release_level"] == "partial_demo_ready"
    assert public_demo["missing_required_flow_ids"] == [
        "real_desktop_interaction",
        "workflow_provider",
    ]
    assert public_demo["release_blockers"][0]["reason"] == "desktop_session_locked"
    desktop_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_real_desktop"
    )
    provider_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_provider"
    )
    assert "--include-real-desktop-interaction" in desktop_action["command"]
    assert "--include-provider-workflow" not in desktop_action["command"]
    assert "--include-real-desktop " not in desktop_action["command"]
    assert "--include-real-desktop-open" not in desktop_action["command"]
    assert "--include-ui" not in desktop_action["command"]
    assert "tmp/public-demo-smokes-real-desktop-missing.json" in desktop_action["command"]
    assert desktop_action["release_blockers"][0]["reason"] == "desktop_session_locked"
    assert provider_action["command"] == (
        "python scripts/run_public_demo_smokes.py --include-provider-workflow "
        "--output-json tmp/public-demo-smokes-provider-missing.json "
        "--output-markdown tmp/public-demo-smokes-provider-missing.md"
    )
    assert summary["release_smoke"]["status"] == "incomplete"
    assert "packaged_launch" in summary["release_smoke"]["missing_item_ids"]
    assert "diagnostics_export" not in summary["release_smoke"]["missing_item_ids"]
    assert any(action["id"] == "packaged_launch" for action in summary["next_actions"])


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
    assert "Release level: `partial_demo_ready`" in markdown
    assert "## Release Smoke" in markdown
    assert "Demo blocker `real_desktop_interaction`: `desktop_session_locked`" in markdown
    assert "--include-real-desktop-interaction" in markdown
    assert "--include-provider-workflow" in markdown
    assert "tmp/public-demo-smokes-real-desktop-missing.json" in markdown
    assert "tmp/public-demo-smokes-provider-missing.json" in markdown
    assert "--include-real-desktop --include-provider-workflow --include-ui" not in markdown


def test_public_release_gate_passes_when_full_release_smoke_is_present(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
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
    assert summary["release_blocker_count"] == 0
    assert summary["next_actions"] == []


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
    report_path = tmp_path / "tmp" / "public-demo-real-desktop.json"
    passed_flow_ids = set(gate._public_demo_required_flow_ids([]))
    passed_flow_ids.remove("real_desktop_ui_inspection")
    passed_flow_ids.remove("real_desktop_interaction")
    _write_public_demo_batch_report(
        report_path,
        passed_flow_ids=passed_flow_ids,
        failed_flow_ids={"real_desktop_ui_inspection", "real_desktop_interaction"},
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
        public_demo_reports=["tmp/public-demo-real-desktop.json"],
    )

    assert not any("scripts/run_public_demo_smokes.py" in command for command in commands)
    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["release_level"] == "blocked"
    assert "real_desktop_app_open" not in public_demo["missing_required_flow_ids"]
    assert public_demo["missing_required_flow_ids"] == [
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
    ]
    desktop_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_real_desktop"
    )
    assert "--include-real-desktop-open" not in desktop_action["command"]
    assert "--include-real-desktop-ui-inspection" in desktop_action["command"]
    assert "--include-real-desktop-interaction" in desktop_action["command"]


def test_public_release_gate_does_not_double_count_public_demo_release_smoke_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "public-demo.json"
    passed_flow_ids = set(gate._public_demo_required_flow_ids([]))
    missing_flow_ids = {
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "workflow_provider",
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
                        "item_count": 9,
                        "passed_count": 8,
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
    assert public_demo["missing_required_flow_ids"] == [
        "real_desktop_ui_inspection",
        "real_desktop_interaction",
        "workflow_provider",
    ]
    assert summary["release_smoke"]["missing_item_ids"] == ["public_demo"]
    assert summary["release_blocker_count"] == len(public_demo["release_blockers"]) == 3
    assert summary["external_requirement_count"] == 2
    assert [item["id"] for item in summary["external_requirements"]] == [
        "real_desktop_smoke_opt_in",
        "provider_smoke_credentials",
    ]
    real_desktop_requirement = summary["external_requirements"][0]
    assert real_desktop_requirement["opt_in_flags"] == [
        "--include-real-desktop-ui-inspection",
        "--include-real-desktop-interaction",
    ]
    assert real_desktop_requirement["opt_in_reasons"] == [
        "opens and inspects a real macOS application",
        "types and clicks in a real macOS application",
    ]


def test_public_release_gate_keeps_more_informative_public_demo_blocker(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    required_flow_ids = gate._public_demo_required_flow_ids([])
    passed_flow_ids = [
        flow_id for flow_id in required_flow_ids if flow_id != "workflow_provider"
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
        "missing_required_flow_ids": ["workflow_provider"],
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
                        "id": "workflow_provider",
                        "status": "skipped",
                        "reason": "requires live provider smoke credentials",
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
                        "id": "workflow_provider",
                        "status": "skipped",
                        "reason": "provider_smoke_credentials_missing",
                        "evidence_summary": {
                            "blocking_condition": "provider_smoke_credentials_missing",
                            "missing_env": [
                                "OHA_YACHIYO_SMOKE_BASE_URL",
                                "OHA_YACHIYO_SMOKE_MODEL",
                            ],
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
        item for item in public_demo["release_blockers"] if item["id"] == "workflow_provider"
    )
    assert blocker["reason"] == "provider_smoke_credentials_missing"
    assert blocker["evidence_summary"]["missing_env"] == [
        "OHA_YACHIYO_SMOKE_BASE_URL",
        "OHA_YACHIYO_SMOKE_MODEL",
    ]
    provider_requirement = next(
        item
        for item in summary["external_requirements"]
        if item["id"] == "provider_smoke_credentials"
    )
    assert provider_requirement["opt_in_flags"] == ["--include-provider-workflow"]
    assert provider_requirement["opt_in_reasons"] == [
        "requires live provider smoke credentials"
    ]
    assert provider_requirement["missing_env"] == [
        "OHA_YACHIYO_SMOKE_BASE_URL",
        "OHA_YACHIYO_SMOKE_MODEL",
    ]
    markdown = gate.render_markdown(summary)
    assert "## External Requirements" in markdown
    assert "`provider_smoke_credentials`" in markdown
    assert "Opt-in flags: `--include-provider-workflow`" in markdown
    assert "Opt-in reasons: requires live provider smoke credentials" in markdown
    assert "`OHA_YACHIYO_SMOKE_BASE_URL`" in markdown
    assert "scripts/run_public_demo_smokes.py --include-provider-workflow" in markdown


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
    desktop_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_real_desktop"
    )
    provider_action = next(
        item for item in summary["next_actions"] if item["id"] == "public_demo_provider"
    )
    assert "--include-real-desktop-open" not in desktop_action["command"]
    assert "--include-ui" not in desktop_action["command"]
    assert "--include-real-desktop-interaction" in desktop_action["command"]
    assert "--include-provider-workflow" not in desktop_action["command"]
    assert "--include-provider-workflow" in provider_action["command"]
    assert summary["status"] == "needs_release_evidence"


def test_public_release_gate_public_demo_next_action_falls_back_for_unknown_flow():
    command = gate._public_demo_next_command(
        {
            "release_level": "partial_demo_ready",
            "missing_required_flow_ids": ["unknown_demo_flow"],
            "release_blockers": [{"id": "unknown_demo_flow"}],
        }
    )

    assert command == gate._full_demo_command()
