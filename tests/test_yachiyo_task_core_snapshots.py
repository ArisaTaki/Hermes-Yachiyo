"""TaskCore projection regressions for public runtime events."""

from __future__ import annotations

from apps.shell.yachiyo_agent.run_timeline_snapshots import run_timeline_snapshot_from_payload
from apps.shell.yachiyo_agent.task_cards import agent_task_snapshot_from_payload


def test_task_core_reconstructs_from_public_plan_steps_and_updates() -> None:
    payload = {
        "run_id": "run-1",
        "task_id": "task-1",
        "title": "Analyze sales",
        "status": "running",
        "events": [
            _plan_created_event(),
            *_plan_step_events(),
            {
                "event_type": "agent.task.todo.updated",
                "payload": {
                    "step_id": "read-source",
                    "status": "completed",
                    "todo": {
                        "todo_id": "todo-read-source",
                        "title": "Read source",
                        "step_id": "read-source",
                        "tool_name": "workspace.read",
                        "status": "completed",
                    },
                },
            },
            {
                "event_type": "agent.task.workspace_item.updated",
                "payload": {
                    "workspace_item_id": "sales-input",
                    "status": "completed",
                    "workspace_item": {
                        "item_id": "sales-input",
                        "title": "sales.csv",
                        "kind": "input",
                        "path": "sales.csv",
                        "source_step_id": "read-source",
                        "status": "completed",
                    },
                },
            },
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "run-analysis",
                    "tool_name": "data.analyze",
                    "status": "failed",
                    "result": {"ok": False, "error": "empty dataset"},
                },
            },
        ],
    }

    timeline = run_timeline_snapshot_from_payload(payload)
    task = agent_task_snapshot_from_payload(payload)

    assert timeline.task_core is not None
    assert task.task_core is not None
    assert timeline.task_core.core_id == "task-core:intent-analysis"
    assert timeline.task_core.workspace.workspace_id == "task-workspace:intent-analysis"
    assert timeline.task_core.workspace.items[0].item_id == "sales-input"
    assert timeline.task_core.workspace.items[0].status == "completed"
    assert [todo.step_id for todo in timeline.task_core.todos] == [
        "read-source",
        "run-analysis",
    ]
    assert [todo.status for todo in timeline.task_core.todos] == [
        "completed",
        "blocked",
    ]
    assert [checkpoint.after_step_id for checkpoint in timeline.task_core.checkpoints] == [
        "read-source",
        "run-analysis",
    ]
    assert timeline.task_core.checkpoints[1].status == "blocked"
    assert timeline.task_core.replan_signals[0].source_step_id == "run-analysis"
    assert timeline.task_core.replan_signals[0].fallback_tools == ["terminal.run"]
    assert task.task_core.core_id == timeline.task_core.core_id


def test_replan_projection_uses_reconstructed_task_core_id() -> None:
    snapshot = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "status": "failed",
            "events": [
                _plan_created_event(),
                *_plan_step_events(),
                {
                    "event_type": "agent.tool.call",
                    "payload": {
                        "step_id": "run-analysis",
                        "tool_name": "data.analyze",
                        "status": "failed",
                        "result": {"ok": False, "error": "empty dataset"},
                    },
                },
            ],
        }
    )

    replan_event = snapshot.events[-1]

    assert replan_event.event_type == "agent.replan.requested"
    assert replan_event.payload["core_id"] == "task-core:intent-analysis"


def _plan_created_event() -> dict:
    return {
        "event_type": "agent.plan.created",
        "payload": {
            "decision_id": "decision-1",
            "plan": {
                "plan_id": "plan-1",
                "intent": {
                    "intent_id": "intent-analysis",
                    "kind": "data_analysis",
                    "title": "Analyze sales",
                },
                "tool_plan": {
                    "plan_id": "tool-plan-1",
                    "title": "Analyze sales tool plan",
                    "steps": _tool_plan_steps(),
                },
            },
        },
    }


def _plan_step_events() -> list[dict]:
    return [
        {
            "event_type": "agent.plan.step",
            "payload": {"step": step},
        }
        for step in _tool_plan_steps()
    ]


def _tool_plan_steps() -> list[dict]:
    return [
        {
            "step_id": "read-source",
            "title": "Read source",
            "capability_id": "file.workspace_read",
            "tool_name": "workspace.read",
            "input_preview": {"path": "sales.csv"},
        },
        {
            "step_id": "run-analysis",
            "title": "Run analysis",
            "capability_id": "data.analysis",
            "tool_name": "data.analyze",
            "fallback_tools": ["terminal.run"],
        },
    ]
