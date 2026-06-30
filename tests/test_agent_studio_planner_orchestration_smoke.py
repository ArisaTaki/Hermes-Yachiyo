from __future__ import annotations

import json

from scripts import smoke_agent_studio_planner_orchestration as smoke


def test_agent_studio_planner_orchestration_smoke_covers_workflow_group_and_handoff(
    tmp_path,
):
    report = smoke.run_smoke()

    assert report["ok"] is True
    assert report["mode"] == "agent_studio_planner_orchestration_smoke"
    case_by_id = {case["id"]: case for case in report["cases"]}
    assert case_by_id["workflow_orchestration_start"]["status"] == "started"
    assert case_by_id["workflow_orchestration_start"]["kind"] == "workflow"
    assert case_by_id["workflow_orchestration_start"]["intent_kind"] == (
        "workflow_orchestration"
    )
    assert case_by_id["workflow_orchestration_start"]["workflow_run_id"] == (
        "workflow-run-studio-planner"
    )
    assert "start_workflow_run" in case_by_id["workflow_orchestration_start"]["call_names"]

    assert case_by_id["group_run_orchestration_start"]["status"] == "started"
    assert case_by_id["group_run_orchestration_start"]["kind"] == "group_run"
    assert case_by_id["group_run_orchestration_start"]["intent_kind"] == "multi_agent"
    assert case_by_id["group_run_orchestration_start"]["group_run_id"] == (
        "group-run-studio-planner"
    )
    assert "start_group_run" in case_by_id["group_run_orchestration_start"]["call_names"]

    assert case_by_id["missing_target_handoff"]["status"] == "target_not_found"
    assert "start_workflow_run" not in case_by_id["missing_target_handoff"]["call_names"]
    assert "start_group_run" not in case_by_id["missing_target_handoff"]["call_names"]

    output_path = tmp_path / "studio-planner.json"
    assert smoke.main(["--report-json", str(output_path)]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["started_workflow_run_id"] == "workflow-run-studio-planner"
