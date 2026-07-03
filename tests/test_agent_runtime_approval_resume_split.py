"""Tests for approval resume coordinator split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext


def test_approval_resume_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.ApprovalResumeCoordinator is ApprovalResumeCoordinator


def test_approval_resume_records_runtime_task_progress_events() -> None:
    task_core = {
        "core_id": "core-approval",
        "workspace": {"workspace_id": "workspace-1", "title": "Approval task"},
        "todos": [
            {
                "todo_id": "todo-click",
                "step_id": "operate-foreground-ui",
                "title": "Click export",
                "status": "pending",
            },
            {
                "todo_id": "todo-artifact",
                "step_id": "write-artifact",
                "title": "Write artifact",
                "status": "pending",
            },
        ],
        "checkpoints": [
            {
                "checkpoint_id": "checkpoint-click",
                "after_step_id": "operate-foreground-ui",
                "title": "Export clicked",
                "status": "planned",
            },
            {
                "checkpoint_id": "checkpoint-artifact",
                "after_step_id": "write-artifact",
                "title": "Artifact written",
                "status": "planned",
            },
        ],
    }
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-1",
            plan_id="plan-1",
            plan={
                "plan_id": "plan-1",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "operate-foreground-ui",
                            "tool_name": "desktop.click_ui_element",
                        },
                        {
                            "step_id": "write-artifact",
                            "tool_name": "artifact.write",
                        },
                    ]
                },
            },
        ),
        _timeline(
            "agent.task_core.created",
            "task core",
            decision_id="decision-1",
            plan_id="plan-1",
            core_id="core-approval",
            task_id="task-approval",
            group_run_id="group-run-approval",
            workflow_run_id="workflow-run-approval",
            task_core=task_core,
        ),
        _timeline(
            "agent.task.todo.updated",
            "Click export",
            decision_id="decision-1",
            step_id="operate-foreground-ui",
            todo_id="todo-click",
            status="blocked",
        ),
        _timeline(
            "agent.task.checkpoint.updated",
            "Export clicked",
            decision_id="decision-1",
            step_id="operate-foreground-ui",
            checkpoint_id="checkpoint-click",
            status="waiting_approval",
        ),
    ]
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.click_ui_element", "artifact.write"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.click_ui_element",
            "input": {"target": "Export"},
        },
        tool_name="desktop.click_ui_element",
        input_preview={"target": "Export"},
        remaining_requests=[
            {"tool": "artifact.write", "input": {"path": "ok.md"}},
        ],
        next_iteration=3,
    )
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=_approved_tool_call,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            (run_id, event_type, payload)
        ),
    )

    coordinator.execute_approved_tool(context)

    completed_todos = [
        event
        for event in context.timeline
        if event["event"] == "agent.task.todo.updated"
        and event.get("status") == "completed"
    ]
    completed_checkpoints = [
        event
        for event in context.timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event.get("status") == "completed"
    ]
    assert {event["step_id"] for event in completed_todos} == {
        "operate-foreground-ui",
        "write-artifact",
    }
    assert {event["step_id"] for event in completed_checkpoints} == {
        "operate-foreground-ui",
        "write-artifact",
    }
    click_todo = next(
        event
        for event in completed_todos
        if event["step_id"] == "operate-foreground-ui"
    )
    click_checkpoint = next(
        event
        for event in completed_checkpoints
        if event["step_id"] == "operate-foreground-ui"
    )
    assert click_todo["previous_status"] == "blocked"
    assert click_checkpoint["previous_status"] == "waiting_approval"
    assert click_todo["task_id"] == "task-approval"
    assert click_todo["group_run_id"] == "group-run-approval"
    assert click_todo["workflow_run_id"] == "workflow-run-approval"
    assert {
        (run_id, event_type)
        for run_id, event_type, _payload in run_events
    } >= {
        ("run-approval", "agent.task.todo.updated"),
        ("run-approval", "agent.task.checkpoint.updated"),
    }


def test_approval_resume_records_replan_and_blocked_progress_for_failed_tool() -> None:
    task_core = {
        "core_id": "core-approval",
        "workspace": {"workspace_id": "workspace-1", "title": "Approval task"},
        "todos": [
            {
                "todo_id": "todo-analysis",
                "step_id": "run-analysis",
                "title": "Run analysis",
                "status": "pending",
            }
        ],
        "checkpoints": [
            {
                "checkpoint_id": "checkpoint-analysis",
                "after_step_id": "run-analysis",
                "title": "Analysis completed",
                "status": "planned",
            }
        ],
    }
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-1",
            plan_id="plan-1",
            plan={
                "plan_id": "plan-1",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "run-analysis",
                            "tool_name": "terminal.run",
                        }
                    ]
                },
            },
        ),
        _timeline(
            "agent.task_core.created",
            "task core",
            decision_id="decision-1",
            plan_id="plan-1",
            core_id="core-approval",
            task_id="task-approval",
            group_run_id="group-run-approval",
            workflow_run_id="workflow-run-approval",
            task_core=task_core,
        ),
    ]
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run", "python.run"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "input": {"command": "python analyze.py"},
            "step_id": "run-analysis",
            "capability_id": "terminal.execution",
            "decision_id": "decision-1",
            "plan_id": "plan-1",
            "core_id": "core-approval",
            "workspace_id": "workspace-1",
            "task_id": "task-approval",
            "group_run_id": "group-run-approval",
            "workflow_run_id": "workflow-run-approval",
            "fallback_tools": ["python.run"],
            "replan_triggers": ["tool_failure"],
            "replan_signal_ids": ["replan-run-analysis"],
        },
        tool_name="terminal.run",
        input_preview={"command": "python analyze.py"},
        remaining_requests=[],
        next_iteration=3,
    )
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "script failed",
        },
        fatal_tool_failure_detail=lambda *_args: "terminal.run failed fatally",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            (run_id, event_type, payload)
        ),
    )

    with pytest.raises(AgentRuntimeError):
        coordinator.execute_approved_tool(context)

    blocked_todo = next(
        event
        for event in context.timeline
        if event["event"] == "agent.task.todo.updated"
        and event.get("status") == "blocked"
    )
    blocked_checkpoint = next(
        event
        for event in context.timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event.get("status") == "blocked"
    )
    replan_event = next(
        event
        for event in context.timeline
        if event["event"] == "agent.replan.requested"
    )
    replan_payload = replan_event["payload"]

    assert blocked_todo["task_id"] == "task-approval"
    assert blocked_todo["group_run_id"] == "group-run-approval"
    assert blocked_todo["workflow_run_id"] == "workflow-run-approval"
    assert blocked_checkpoint["task_id"] == "task-approval"
    assert replan_payload["source_step_id"] == "run-analysis"
    assert replan_payload["source_tool_name"] == "terminal.run"
    assert replan_payload["fallback_tools"] == ["python.run"]
    assert replan_payload["task_id"] == "task-approval"
    assert replan_payload["group_run_id"] == "group-run-approval"
    assert replan_payload["workflow_run_id"] == "workflow-run-approval"
    assert {
        (run_id, event_type)
        for run_id, event_type, _payload in run_events
    } >= {
        ("run-approval", "agent.task.todo.updated"),
        ("run-approval", "agent.task.checkpoint.updated"),
        ("run-approval", "agent.replan.requested"),
    }


def _approved_tool_call(
    tool_request: dict[str, Any],
    _allowed_tools: list[str],
    _broker: Any,
    timeline: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]],
    approved: bool,
    run_id: str,
    budget: Any,
) -> dict[str, Any]:
    result = {"ok": True, "summary": "Clicked export"}
    timeline.append(
        _timeline(
            "agent.tool.call",
            str(tool_request.get("tool") or ""),
            input_preview=tool_request.get("input") or {},
            result=result,
            approved=approved,
            run_id=run_id,
            budget=budget,
            artifact_count=len(artifacts),
        )
    )
    return result


def _append_tool_result_message(
    messages: list[dict[str, Any]],
    tool_request: dict[str, Any],
    tool_result: dict[str, Any],
) -> None:
    messages.append(
        {
            "role": "tool",
            "name": str(tool_request.get("tool") or ""),
            "content": str(tool_result),
        }
    )


def _run_remaining_tool_requests(
    requests: list[dict[str, Any]],
    _allowed_tools: list[str],
    _broker: Any,
    _messages: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    *,
    next_iteration: int,
    run_id: str,
    budget: Any,
) -> None:
    for request in requests:
        result = {"ok": True, "summary": "Artifact written"}
        artifacts.append({"path": "ok.md"})
        timeline.append(
            _timeline(
                "agent.tool.call",
                str(request.get("tool") or ""),
                input_preview=request.get("input") or {},
                result=result,
                next_iteration=next_iteration,
                run_id=run_id,
                budget=budget,
            )
        )


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}
