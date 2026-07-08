from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import smoke_agent_studio_planner_orchestration as smoke


def _assert_task_core(summary, *, expected_step_id):
    assert summary["core_id"]
    assert summary["workspace_id"]
    assert summary["workspace_item_count"] > 0
    assert expected_step_id in summary["todo_step_ids"]
    assert expected_step_id in summary["checkpoint_step_ids"]
    assert expected_step_id in summary["replan_checkpoint_step_ids"]


def test_task_core_summary_normalizes_orchestration_payload():
    summary = smoke._task_core_summary(
        {
            "core_id": "core-1",
            "workspace": {
                "workspace_id": "workspace-1",
                "items": [{"item_id": "item-1"}],
            },
            "todos": [{"step_id": "workflow-orchestration"}],
            "checkpoints": [
                {
                    "after_step_id": "workflow-orchestration",
                    "replan_on_failure": True,
                }
            ],
            "replan_signals": [{"trigger": "checkpoint_failed"}],
        }
    )

    _assert_task_core(summary, expected_step_id="workflow-orchestration")
    assert summary["replan_triggers"] == ["checkpoint_failed"]


def test_event_types_accepts_dicts_and_models():
    assert smoke._event_types(
        [
            {"event_type": "workflow.run.task_core.created"},
            SimpleNamespace(event_type="workflow.run.task.todo.updated"),
        ]
    ) == [
        "workflow.run.task_core.created",
        "workflow.run.task.todo.updated",
    ]


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
    assert "workflow.run.task_core.created" in case_by_id[
        "workflow_orchestration_start"
    ]["event_types"]
    _assert_task_core(
        case_by_id["workflow_orchestration_start"]["task_core_summary"],
        expected_step_id="workflow-orchestration",
    )
    assert case_by_id["workflow_orchestration_start"]["metadata_task_core_summary"][
        "core_id"
    ] == case_by_id["workflow_orchestration_start"]["task_core_summary"]["core_id"]

    assert case_by_id["group_run_orchestration_start"]["status"] == "started"
    assert case_by_id["group_run_orchestration_start"]["kind"] == "group_run"
    assert case_by_id["group_run_orchestration_start"]["intent_kind"] == "multi_agent"
    assert case_by_id["group_run_orchestration_start"]["group_run_id"] == (
        "group-run-studio-planner"
    )
    assert "start_group_run" in case_by_id["group_run_orchestration_start"]["call_names"]
    assert "group.run.task_core.created" in case_by_id[
        "group_run_orchestration_start"
    ]["event_types"]
    _assert_task_core(
        case_by_id["group_run_orchestration_start"]["task_core_summary"],
        expected_step_id="group-multi_agent",
    )
    assert case_by_id["group_run_orchestration_start"]["metadata_task_core_summary"][
        "core_id"
    ] == case_by_id["group_run_orchestration_start"]["task_core_summary"]["core_id"]

    assert case_by_id["missing_target_handoff"]["status"] == "target_not_found"
    assert "start_workflow_run" not in case_by_id["missing_target_handoff"]["call_names"]
    assert "start_group_run" not in case_by_id["missing_target_handoff"]["call_names"]
    _assert_task_core(
        case_by_id["missing_target_handoff"]["task_core_summary"],
        expected_step_id="workflow-orchestration",
    )

    output_path = tmp_path / "studio-planner.json"
    assert smoke.main(["--report-json", str(output_path)]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["started_workflow_run_id"] == "workflow-run-studio-planner"
