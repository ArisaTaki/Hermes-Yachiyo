from scripts import smoke_agent_entrypoint_data_analysis as smoke


def test_data_analysis_smoke_extracts_task_core_from_runtime_plan() -> None:
    task_core = {
        "core_id": "task-core-1",
        "workspace": {
            "workspace_id": "task-workspace-1",
            "items": [{"path": "inputs/sales.csv"}, {"path": "analysis-report.md"}],
        },
        "todos": [{"step_id": "read-data-source"}],
        "checkpoints": [{"after_step_id": "read-data-source"}],
        "replan_signals": [{"trigger": "verification_failed"}],
    }

    extracted = smoke._task_core_from_payloads(
        {},
        {"payload": {"runtime_plan": {"task_core": task_core}}},
    )
    summary = smoke._task_core_summary(extracted)

    assert summary["core_id"] == "task-core-1"
    assert summary["workspace_id"] == "task-workspace-1"
    assert summary["workspace_paths"] == ["inputs/sales.csv", "analysis-report.md"]
    assert summary["todo_step_ids"] == ["read-data-source"]
    assert summary["checkpoint_step_ids"] == ["read-data-source"]
    assert summary["replan_triggers"] == ["verification_failed"]


def test_data_analysis_smoke_extracts_task_core_from_studio_payload() -> None:
    task_core = {
        "core_id": "task-core-studio",
        "workspace": {"workspace_id": "task-workspace-studio", "items": []},
    }

    extracted = smoke._task_core_from_payloads(
        {},
        {"payload": {"yachiyo_task_core": task_core}},
    )

    assert extracted["core_id"] == "task-core-studio"
