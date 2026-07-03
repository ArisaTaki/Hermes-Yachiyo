"""Shared Yachiyo runtime progress event projections."""

from __future__ import annotations

from apps.shell.yachiyo_agent.runtime_progress import (
    public_task_progress_events_for_tool_result,
    task_progress_event_payloads_for_tool_result,
)


def test_public_task_progress_events_preserve_task_group_workflow_context() -> None:
    events = public_task_progress_events_for_tool_result(
        tool_request=_tool_request(),
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "result": {"ok": True, "action": "artifact.write", "summary": "done"},
        },
        run_id="run-1",
        after_sequence=20,
    )

    assert [event.event_type for event in events] == [
        "agent.task.workspace_item.updated",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
    ]
    assert [event.sequence for event in events] == [21, 22, 23]
    for event in events:
        assert event.run_id == "run-1"
        assert event.core_id == "task-core-1"
        assert event.workspace_id == "task-workspace-1"
        assert event.task_id == "task-1"
        assert event.group_run_id == "group-run-1"
        assert event.workflow_run_id == "workflow-run-1"
        assert event.payload["status"] == "completed"


def test_task_progress_payloads_can_be_scoped_for_group_and_workflow_runs() -> None:
    tool_event = {
        "event": "agent.tool.call",
        "detail": "artifact.write",
        "result": {"ok": True, "action": "artifact.write"},
    }

    group_events = task_progress_event_payloads_for_tool_result(
        tool_request=_tool_request(),
        tool_event=tool_event,
        event_scope="group.run",
    )
    workflow_events = task_progress_event_payloads_for_tool_result(
        tool_request=_tool_request(),
        tool_event=tool_event,
        event_scope="workflow.run",
    )

    assert [event["event"] for event in group_events] == [
        "group.run.task.workspace_item.updated",
        "group.run.task.todo.updated",
        "group.run.task.checkpoint.updated",
    ]
    assert [event["event"] for event in workflow_events] == [
        "workflow.run.task.workspace_item.updated",
        "workflow.run.task.todo.updated",
        "workflow.run.task.checkpoint.updated",
    ]
    assert group_events[1]["planner_event_type"] == "agent.task.todo.updated"
    assert workflow_events[2]["planner_event_type"] == "agent.task.checkpoint.updated"


def _tool_request() -> dict:
    return {
        "tool": "artifact.write",
        "input": {"path": "report.md"},
        "source": "runtime_planner",
        "step_id": "write-report",
        "core_id": "task-core-1",
        "workspace_id": "task-workspace-1",
        "decision_id": "decision-1",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "group_run_id": "group-run-1",
        "workflow_run_id": "workflow-run-1",
        "task_workspace_items": [
            {
                "item_id": "workspace-report",
                "title": "report.md",
                "kind": "artifact",
                "status": "planned",
                "source_step_id": "write-report",
            }
        ],
        "task_todo": {
            "todo_id": "todo-write-report",
            "title": "Write report",
            "status": "pending",
            "step_id": "write-report",
            "tool_name": "artifact.write",
        },
        "task_checkpoints": [
            {
                "checkpoint_id": "checkpoint-write-report",
                "title": "Verify report",
                "status": "planned",
                "after_step_id": "write-report",
            }
        ],
    }
