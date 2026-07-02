from __future__ import annotations

import json

from scripts import smoke_group_run_timeline as smoke


def test_group_run_timeline_smoke_covers_public_group_run_snapshots():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["mode"] == "group_run_timeline_smoke"
    assert evidence["started"]["group_run_id"] == smoke.GROUP_RUN_ID
    assert evidence["started"]["run_group_id"] == smoke.GROUP_RUN_ID
    assert evidence["started"]["participants"][0]["run_id"] == smoke.CHILD_RUN_ID
    assert evidence["started"]["participants"][0]["run_status"] == "approval_required"
    assert evidence["started"]["pending_approvals"][0]["approval_id"] == smoke.APPROVAL_ID
    assert evidence["started"]["pending_approvals"][0]["group_run_id"] == smoke.GROUP_RUN_ID
    artifact_paths = {artifact["path"] for artifact in evidence["started"]["shared_artifacts"]}
    assert smoke.ARTIFACT_PATH in artifact_paths
    assert evidence["listed"][0]["group_run_id"] == smoke.LISTED_GROUP_RUN_ID
    assert evidence["fetched"]["child_run_ids"] == [smoke.CHILD_RUN_ID]
    assert all(evidence["checks"].values())


def test_group_run_timeline_smoke_covers_event_stream_and_page():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert [event["event_type"] for event in evidence["event_stream"][:2]] == [
        "group.run.started",
        "group.member.started",
    ]
    assert evidence["event_stream"][0]["payload"]["group_run_id"] == smoke.GROUP_RUN_ID
    assert evidence["event_page"]["run_id"] == smoke.GROUP_RUN_ID
    assert evidence["event_page"]["after_sequence"] == 1
    assert evidence["event_page"]["limit"] == 2
    assert [event["event_type"] for event in evidence["event_page"]["events"]] == [
        "group.member.started",
        "group.run.tool.approval_required",
    ]
    assert evidence["event_page"]["has_more"] is True
    assert [call["name"] for call in evidence["calls"]] == [
        "start_group_run",
        "list_group_runs",
        "get_group_run",
        "get_group_run_event_stream",
        "get_group_run_event_page",
    ]


def test_group_run_timeline_smoke_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "group-run-timeline.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "group_run_timeline_smoke"
    assert "group run timeline smoke report:" in captured.err
    assert str(report_path) in captured.err
