from __future__ import annotations

import json
import subprocess
import sys
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
        "selected_count": 13 if release_level == "full_public_demo_ready" else 7,
        "passed_count": 13 if release_level == "full_public_demo_ready" else 7,
        "required_flow_count": 13,
        "passed_required_flow_count": 13 if release_level == "full_public_demo_ready" else 7,
        "missing_required_flow_ids": []
        if release_level == "full_public_demo_ready"
        else ["real_desktop_interaction", "workflow_provider"],
        "release_blockers": []
        if release_level == "full_public_demo_ready"
        else [
            {
                "id": "workflow_provider",
                "status": "skipped",
                "opt_in_flag": "--include-provider-workflow",
                "reason": "requires live provider smoke credentials",
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
        return _completed(command)

    monkeypatch.setattr(gate, "_run_command", fake_run)

    summary = gate.run_public_release_gate(tmp_dir="tmp/gate")

    assert summary["ok"] is True
    assert summary["release_ready"] is False
    assert summary["status"] == "needs_release_evidence"
    assert summary["check_count"] == 4
    assert summary["failed_count"] == 0
    assert [command[:2] for command in commands[:2]] == [
        [sys.executable, "scripts/verify_release_artifacts.py"],
        [sys.executable, "scripts/verify_secret_redaction.py"],
    ]
    public_demo = next(item for item in summary["checks"] if item["id"] == "public_demo")
    assert public_demo["release_level"] == "partial_demo_ready"
    assert public_demo["missing_required_flow_ids"] == [
        "real_desktop_interaction",
        "workflow_provider",
    ]
    action = next(item for item in summary["next_actions"] if item["id"] == "public_demo")
    assert action["command"] == "python scripts/run_public_demo_smokes.py --full-demo"


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
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "Release level: `partial_demo_ready`" in markdown
    assert "python scripts/run_public_demo_smokes.py --full-demo" in markdown


def test_public_release_gate_passes_when_full_public_demo_is_present(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    def fake_run(command):
        command = list(command)
        _write_public_demo_report(command, release_level="full_public_demo_ready")
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
