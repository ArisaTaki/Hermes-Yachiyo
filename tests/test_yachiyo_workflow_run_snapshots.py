"""WorkflowRun public snapshot projector regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import WorkflowRunSnapshot
from apps.shell.yachiyo_agent.workflow_run_snapshots import (
    workflow_run_payload_with_lifecycle,
    workflow_run_snapshot_from_payload,
)


def test_workflow_run_snapshot_module_projects_lifecycle_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-direct",
            "kind": "workflow_run",
            "status": "completed",
            "workflow_id": "workflow-1",
            "objective": "Review docs",
            "current_node_id": "done",
            "current_node_label": "Done",
            "created_at": "2026-06-17T00:00:00Z",
            "updated_at": "2026-06-17T00:00:03Z",
        }
    )

    assert workflow_run.workflow_id == "workflow-1"
    assert workflow_run.workflow_run_id == "workflow-run-direct"
    assert workflow_run.current_node_id == "done"
    assert workflow_run.current_node_label == "Done"
    assert [event.event_type for event in workflow_run.events] == [
        "workflow.run.started",
        "workflow.run.completed",
    ]
    assert workflow_run.events[-1].payload["status"] == "completed"


def test_workflow_run_snapshot_returns_existing_public_snapshot() -> None:
    existing = WorkflowRunSnapshot(
        run_id="workflow-run-existing",
        workflow_run_id="workflow-run-existing",
        workflow_id="workflow-1",
        status="completed",
        objective="Already projected",
    )

    assert workflow_run_snapshot_from_payload(existing) is existing


def test_workflow_run_payload_with_lifecycle_does_not_duplicate_aliases() -> None:
    payload = workflow_run_payload_with_lifecycle(
        {
            "run_id": "workflow-run-alias",
            "kind": "workflow_run",
            "status": "succeeded",
            "events": [
                {"event_type": "workflow.started"},
                {"event_type": "workflow.completed"},
            ],
        }
    )

    assert [event["event_type"] for event in payload["events"]] == [
        "workflow.started",
        "workflow.completed",
    ]


def test_workflow_run_snapshot_projects_planner_summary_from_workflow_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-planner",
            "kind": "workflow_run",
            "status": "processing",
            "events": [
                {
                    "event_type": "workflow.run.plan.created",
                    "payload": {
                        "source": "runtime_planner",
                        "decision_id": "decision-workflow",
                        "plan": {
                            "plan_id": "plan-workflow",
                            "intent": {
                                "intent_id": "intent-workflow",
                                "kind": "data_analysis",
                                "title": "Analyze sales",
                            },
                            "capabilities": [{"capability_id": "data.analysis"}],
                            "tool_plan": {
                                "steps": [
                                    {
                                        "step_id": "analyze",
                                        "capability_id": "data.analysis",
                                        "tool_name": "python.exec",
                                    }
                                ],
                                "required_capabilities": ["data.analysis"],
                                "artifacts_expected": ["markdown_report"],
                            },
                        },
                    },
                },
                {
                    "event_type": "workflow.run.plan.selection",
                    "payload": {
                        "source": "runtime_planner",
                        "selection_source": "runtime_planner",
                        "selection_role": "workflow_primary",
                        "selected_tools": ["python.exec"],
                    },
                },
            ],
        }
    )

    assert workflow_run.planner_summary is not None
    assert workflow_run.planner_summary.decision_id == "decision-workflow"
    assert workflow_run.planner_summary.plan_id == "plan-workflow"
    assert workflow_run.planner_summary.intent_kind == "data_analysis"
    assert workflow_run.planner_summary.plan_tools == ["python.exec"]
    assert workflow_run.planner_summary.selected_tools == ["python.exec"]
    assert workflow_run.planner_summary.plan_capabilities == ["data.analysis"]
    assert workflow_run.planner_summary.artifacts_expected == ["markdown_report"]
    assert workflow_run.planner_summary.event_count == 2


def test_workflow_run_snapshot_scopes_replan_from_failed_tool_event() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-replan",
            "workflow_run_id": "workflow-run-replan",
            "workflow_id": "workflow-1",
            "kind": "workflow_run",
            "task_id": "task-workflow-replan",
            "status": "running",
            "events": [
                {
                    "event_type": "workflow.run.plan.created",
                    "payload": {
                        "source": "runtime_planner",
                        "planner_event_type": "agent.plan.created",
                        "planner_scope": "workflow.run",
                        "decision_id": "decision-workflow-replan",
                        "plan": {
                            "plan_id": "plan-workflow-replan",
                            "intent": {
                                "intent_id": "intent-workflow-replan",
                                "kind": "data_analysis",
                                "title": "Analyze sales",
                                "user_goal": "Analyze sales",
                                "confidence": 0.9,
                                "required_capabilities": ["data.analysis"],
                            },
                            "capabilities": [],
                            "tool_plan": {
                                "plan_id": "tool-plan-workflow-replan",
                                "title": "Workflow analysis tools",
                                "steps": [
                                    {
                                        "step_id": "analyze-data",
                                        "title": "Analyze data",
                                        "capability_id": "data.analysis",
                                        "tool_name": "python.exec",
                                        "fallback_tools": ["artifact.write"],
                                    }
                                ],
                                "required_capabilities": ["data.analysis"],
                            },
                        },
                    },
                },
                {
                    "event_type": "agent.tool.call",
                    "payload": {
                        "step_id": "analyze-data",
                        "tool_name": "python.exec",
                        "status": "failed",
                        "result": {"ok": False, "error": "Python execution failed"},
                    },
                },
            ],
        }
    )

    event_types = [event.event_type for event in workflow_run.events]
    assert "workflow.run.replan.requested" in event_types
    assert "agent.replan.requested" not in event_types
    replan_event = next(
        event
        for event in workflow_run.events
        if event.event_type == "workflow.run.replan.requested"
    )
    assert replan_event.payload["planner_event_type"] == "agent.replan.requested"
    assert replan_event.payload["planner_scope"] == "workflow_run"
    assert workflow_run.replan_recoveries
    assert workflow_run.replan_recoveries[0].workflow_run_id == "workflow-run-replan"
    assert workflow_run.runtime_debug is not None
    assert workflow_run.runtime_debug.replan_recovery_count == 1
    assert workflow_run.runtime_debug.latest_replan_trigger == "tool_failure"


def test_workflow_run_snapshot_projects_task_core_progress_from_workflow_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-task-core",
            "workflow_run_id": "workflow-run-task-core",
            "workflow_id": "workflow-1",
            "kind": "workflow_run",
            "status": "completed",
            "objective": "Analyze shared report",
            "events": _completed_task_core_events(),
        }
    )

    event_types = [event.event_type for event in workflow_run.events]
    assert "workflow.run.task_core.created" in event_types
    assert "workflow.run.task.todo.updated" in event_types
    assert "workflow.run.task.checkpoint.updated" in event_types
    assert workflow_run.task_core is not None
    assert workflow_run.task_core.workspace.workspace_id == "task-workspace-1"
    assert workflow_run.task_core.todos[0].status == "completed"
    assert workflow_run.task_core.checkpoints[0].status == "completed"
    assert workflow_run.task_progress is not None
    assert workflow_run.task_progress.status == "completed"
    assert workflow_run.task_progress.completed_todos == 1
    assert workflow_run.task_progress.completed_checkpoints == 1
    assert workflow_run.runtime_debug is not None
    assert workflow_run.runtime_debug.needs_replan is False


def _completed_task_core_events() -> list[dict]:
    return [
        {
            "event_type": "agent.task_core.created",
            "payload": {
                "core_id": "task-core-1",
                "task_core": {
                    "core_id": "task-core-1",
                    "workspace": {
                        "workspace_id": "task-workspace-1",
                        "title": "Analysis Workspace",
                    },
                    "todos": [
                        {
                            "todo_id": "todo-analyze",
                            "title": "Analyze data",
                            "step_id": "analyze-data",
                            "tool_name": "data.analyze",
                            "status": "pending",
                        }
                    ],
                    "checkpoints": [
                        {
                            "checkpoint_id": "checkpoint-analyze",
                            "title": "Verify analysis",
                            "after_step_id": "analyze-data",
                            "status": "planned",
                        }
                    ],
                    "replan_signals": [],
                },
            },
        },
        {
            "event_type": "agent.task.todo.updated",
            "payload": {
                "todo_id": "todo-analyze",
                "status": "completed",
                "todo": {
                    "todo_id": "todo-analyze",
                    "title": "Analyze data",
                    "step_id": "analyze-data",
                    "tool_name": "data.analyze",
                    "status": "completed",
                },
            },
        },
        {
            "event_type": "agent.task.checkpoint.updated",
            "payload": {
                "checkpoint_id": "checkpoint-analyze",
                "status": "completed",
                "checkpoint": {
                    "checkpoint_id": "checkpoint-analyze",
                    "title": "Verify analysis",
                    "after_step_id": "analyze-data",
                    "status": "completed",
                },
            },
        },
    ]
