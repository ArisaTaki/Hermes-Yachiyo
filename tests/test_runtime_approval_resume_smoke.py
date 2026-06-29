from __future__ import annotations

import json

from scripts import smoke_runtime_approval_resume as smoke


def test_runtime_approval_resume_smoke_covers_completed_resume():
    evidence = smoke.run_smoke()
    completed = evidence["completed"]

    assert evidence["ok"] is True
    assert completed["ok"] is True
    assert completed["result"]["status"] == "completed"
    assert completed["result"]["result"] == "resumed model output"
    assert completed["result"]["finalized"] is True
    assert completed["call_order"] == [
        "claim_pending_approval",
        "approve_tool_run",
        "project_running",
        "call_agent_tool",
        "fatal_tool_failure_detail",
        "append_tool_result_message",
        "run_tool_requests",
        "continue_custom_api_agent",
        "project_completed",
        "project_result",
    ]
    assert completed["calls"][3]["approved"] is True


def test_runtime_approval_resume_smoke_covers_required_failed_and_duplicate_paths():
    evidence = smoke.run_smoke()

    assert evidence["required"]["ok"] is True
    assert evidence["required"]["result"]["status"] == "approval_required"
    assert evidence["required"]["result"]["pending_approval"]["resume_kind"] == (
        "runtime_approval_resume_smoke"
    )
    assert evidence["fatal"]["ok"] is True
    assert evidence["fatal"]["result"]["status"] == "failed"
    assert "agent.tool.failed" in evidence["fatal"]["result"]["timeline_events"]
    assert "continue_custom_api_agent" not in evidence["fatal"]["call_order"]
    assert evidence["duplicate_claim"]["ok"] is True
    assert evidence["duplicate_claim"]["call_order"] == [
        "claim_pending_approval",
        "get_current_run",
    ]


def test_runtime_approval_resume_smoke_covers_execution_gate():
    evidence = smoke.run_smoke()
    gate = evidence["execution_gate"]

    assert gate["ok"] is True
    assert gate["completed"]["status"] == "completed"
    assert gate["already_completed"]["status"] == "completed"
    assert gate["duplicate"]["status"] == "approval_required"
    assert gate["call_order"] == ["get_run", "approve_once", "get_run", "get_run"]


def test_runtime_approval_resume_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "runtime_approval_resume_smoke"
    assert output["completed"]["result"]["status"] == "completed"


def test_runtime_approval_resume_smoke_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "runtime-approval-resume.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "runtime_approval_resume_smoke"
    assert "runtime approval resume smoke report:" in captured.err
    assert str(report_path) in captured.err
