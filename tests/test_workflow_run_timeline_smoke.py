from __future__ import annotations

import json

from scripts import smoke_workflow_run_timeline as smoke


def test_workflow_run_timeline_smoke_projects_public_replay_state() -> None:
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["mode"] == "workflow_run_timeline_smoke"
    assert all(evidence["checks"].values())
    assert evidence["started"]["workflow_run_id"] == smoke.WORKFLOW_RUN_ID
    assert evidence["started"]["workflow_id"] == smoke.WORKFLOW_ID
    assert evidence["started"]["pending_approval"]["approval_id"] == smoke.APPROVAL_ID
    assert evidence["started"]["children"][0]["workflow_node_id"] == "agent-review"
    assert evidence["started"]["artifacts"][0]["path"] == smoke.ARTIFACT_PATH
    assert [event["event_type"] for event in evidence["event_page"]["events"]] == [
        "workflow.node.started",
        "agent.tool.approval_required",
    ]
    assert [call["name"] for call in evidence["calls"]] == [
        "list_workflows",
        "get_workflow",
        "start_workflow_run",
        "list_run_timelines",
        "get_run_timeline",
        "get_run_event_stream",
        "get_run_event_page",
    ]


def test_workflow_run_timeline_smoke_cli_writes_report(tmp_path, capsys) -> None:
    report = tmp_path / "workflow-run-smoke.json"

    exit_code = smoke.main(["--report-json", str(report)])

    assert exit_code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["mode"] == "workflow_run_timeline_smoke"
    stdout = capsys.readouterr().out
    assert '"workflow_run_timeline_smoke"' in stdout
