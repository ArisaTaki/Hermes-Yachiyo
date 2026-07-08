from scripts import smoke_agent_entrypoint_desktop_execution as smoke


def test_desktop_execution_smoke_summarizes_runtime_task_core() -> None:
    task_core = {
        "core_id": "task-core-desktop",
        "workspace": {
            "workspace_id": "task-workspace-desktop",
            "items": [{"item_id": "input"}, {"item_id": "scratch"}],
        },
        "todos": [
            {"step_id": "discover-desktop-state", "tool_name": "desktop.list_apps"},
            {"step_id": "open-or-focus-app", "tool_name": "app.open"},
        ],
        "checkpoints": [
            {"after_step_id": "discover-desktop-state"},
            {"after_step_id": "open-or-focus-app"},
        ],
        "replan_signals": [{"trigger": "verification_failed"}],
    }

    summary = smoke._task_core_summary(task_core)

    assert summary["core_id"] == "task-core-desktop"
    assert summary["workspace_item_count"] == 2
    assert summary["todo_step_ids"] == [
        "discover-desktop-state",
        "open-or-focus-app",
    ]
    assert smoke._task_core_checks(
        summary,
        expected_step_ids=["discover-desktop-state", "open-or-focus-app"],
        expected_tools=["desktop.list_apps", "app.open"],
    ) == {
        "task_core_projected": True,
        "task_core_has_workspace": True,
        "task_core_has_workspace_items": True,
        "task_core_has_todo_steps": True,
        "task_core_has_todo_tools": True,
        "task_core_has_checkpoints": True,
        "task_core_has_replan_signal": True,
    }


def test_desktop_execution_smoke_extracts_studio_task_core() -> None:
    task_core = {
        "core_id": "task-core-studio",
        "workspace": {"workspace_id": "task-workspace-studio"},
    }

    extracted = smoke._task_core_from_selection_event(
        {"payload": {"yachiyo_execution_envelope": {"task_core": task_core}}},
    )

    assert extracted["core_id"] == "task-core-studio"
