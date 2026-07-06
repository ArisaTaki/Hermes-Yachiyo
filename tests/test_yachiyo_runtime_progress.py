"""Shared Yachiyo runtime progress event projections."""

from __future__ import annotations

from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner
from apps.shell.yachiyo_agent.runtime_progress import (
    public_task_replan_events_for_tool_result,
    public_task_progress_events_for_tool_result,
    task_replan_event_payloads_for_tool_result,
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


def test_public_task_progress_events_block_explicit_verification_failure() -> None:
    events = public_task_progress_events_for_tool_result(
        tool_request=_tool_request(),
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "verification_failed": True,
            "result": {
                "ok": True,
                "summary": "Report artifact was written but failed verification.",
            },
        },
        run_id="run-1",
        after_sequence=30,
    )

    assert [event.event_type for event in events] == [
        "agent.task.workspace_item.updated",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
    ]
    assert [event.payload["status"] for event in events] == [
        "blocked",
        "blocked",
        "blocked",
    ]


def test_task_progress_events_mark_operate_step_pending_verification() -> None:
    events = public_task_progress_events_for_tool_result(
        tool_request={
            **_tool_request(),
            "requires_post_action_verification": True,
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "result": {"ok": True, "summary": "Report artifact written."},
        },
        run_id="run-1",
        after_sequence=40,
    )

    assert [event.payload["status"] for event in events] == [
        "in_progress",
        "in_progress",
        "ready",
    ]
    assert all(
        event.payload["verification_status"] == "pending_verification"
        for event in events
    )
    assert events[1].payload["todo"]["metadata"]["verification_status"] == (
        "pending_verification"
    )
    assert events[2].payload["checkpoint"]["payload"]["verification_status"] == (
        "pending_verification"
    )
    assert events[2].payload["requires_post_action_verification"] is True


def test_task_progress_events_complete_targets_from_verify_step_result() -> None:
    source_request = _tool_request()
    verify_request = {
        "tool": "desktop.ui_elements",
        "source": "runtime_planner",
        "step_id": "verify-report",
        "runtime_stage": "verify",
        "core_id": source_request["core_id"],
        "workspace_id": source_request["workspace_id"],
        "decision_id": source_request["decision_id"],
        "plan_id": source_request["plan_id"],
        "task_id": source_request["task_id"],
        "task_verification_targets": [
            {
                "step_id": "write-report",
                "todo": source_request["task_todo"],
                "checkpoints": source_request["task_checkpoints"],
            }
        ],
    }

    events = public_task_progress_events_for_tool_result(
        tool_request=verify_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "desktop.ui_elements",
            "result": {"ok": True, "summary": "Report artifact is visible."},
        },
        run_id="run-1",
        after_sequence=50,
    )

    assert [event.event_type for event in events] == [
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
    ]
    assert [event.payload["status"] for event in events] == ["completed", "completed"]
    assert all(event.payload["verification_status"] == "verified" for event in events)
    assert events[0].payload["verified_by_step_id"] == "verify-report"
    assert events[0].payload["verification_tool"] == "desktop.ui_elements"
    assert events[0].payload["todo"]["metadata"]["verification_status"] == "verified"
    assert events[0].payload["todo"]["metadata"]["verified_by_step_id"] == "verify-report"
    assert events[1].payload["checkpoint"]["payload"]["verification_status"] == "verified"
    assert events[1].payload["checkpoint"]["payload"]["verification_tool"] == (
        "desktop.ui_elements"
    )


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


def test_task_progress_payloads_can_infer_group_and_workflow_scope() -> None:
    tool_event = {
        "event": "agent.tool.call",
        "detail": "artifact.write",
        "result": {"ok": True, "action": "artifact.write"},
    }
    group_request = {**_tool_request(), "workflow_run_id": ""}
    workflow_request = {**_tool_request(), "group_run_id": "", "run_group_id": ""}

    group_events = task_progress_event_payloads_for_tool_result(
        tool_request=group_request,
        tool_event=tool_event,
        event_scope="auto",
    )
    workflow_events = task_progress_event_payloads_for_tool_result(
        tool_request=workflow_request,
        tool_event=tool_event,
        event_scope="auto",
    )

    assert group_events[0]["event"] == "group.run.task.workspace_item.updated"
    assert group_events[0]["planner_scope"] == "group.run"
    assert workflow_events[0]["event"] == "workflow.run.task.workspace_item.updated"
    assert workflow_events[0]["planner_scope"] == "workflow.run"


def test_task_progress_payloads_infer_scope_from_nested_request_context() -> None:
    tool_event = {
        "event": "agent.tool.call",
        "detail": "artifact.write",
        "result": {"ok": True, "action": "artifact.write"},
    }
    metadata_group_request = {
        **_tool_request(),
        "workflow_run_id": "",
        "group_run_id": "",
        "run_group_id": "",
        "metadata": {"group_run_id": "group-run-from-metadata"},
    }
    payload_workflow_request = {
        **_tool_request(),
        "workflow_run_id": "",
        "group_run_id": "",
        "run_group_id": "",
        "payload": {"workflow_run_id": "workflow-run-from-payload"},
    }

    group_events = task_progress_event_payloads_for_tool_result(
        tool_request=metadata_group_request,
        tool_event=tool_event,
        event_scope="auto",
    )
    workflow_events = task_progress_event_payloads_for_tool_result(
        tool_request=payload_workflow_request,
        tool_event=tool_event,
        event_scope="auto",
    )

    assert group_events[0]["event"] == "group.run.task.workspace_item.updated"
    assert group_events[0]["planner_scope"] == "group.run"
    assert workflow_events[0]["event"] == "workflow.run.task.workspace_item.updated"
    assert workflow_events[0]["planner_scope"] == "workflow.run"


def test_task_progress_payloads_infer_scope_from_tool_event_context() -> None:
    request = {
        **_tool_request(),
        "workflow_run_id": "",
        "group_run_id": "",
        "run_group_id": "",
    }

    group_events = task_progress_event_payloads_for_tool_result(
        tool_request=request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "metadata": {"group_run_id": "group-run-from-event"},
            "result": {"ok": True, "action": "artifact.write"},
        },
        event_scope="auto",
    )
    workflow_events = task_progress_event_payloads_for_tool_result(
        tool_request=request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "result": {
                "ok": True,
                "action": "artifact.write",
                "workflow_run_id": "workflow-run-from-result",
            },
        },
        event_scope="auto",
    )

    assert group_events[0]["event"] == "group.run.task.workspace_item.updated"
    assert group_events[0]["planner_scope"] == "group.run"
    assert workflow_events[0]["event"] == "workflow.run.task.workspace_item.updated"
    assert workflow_events[0]["planner_scope"] == "workflow.run"


def test_task_progress_payloads_scope_replan_recovery_from_trigger_list() -> None:
    workflow_request = {
        **_tool_request(),
        "group_run_id": "",
        "workflow_run_id": "workflow-run-1",
        "replan_request_id": "replan-1",
        "replan_recovery_action_id": "replan-1:action:1:artifact.write",
        "replan_triggers": ["verification_failed"],
        "replan_signal_ids": ["signal-1"],
        "recovery_action_label": "Write report artifact",
        "source_step_id": "analyze-data",
        "source_tool_name": "data.analyze",
        "target_capability_id": "artifact.output",
    }

    events = task_progress_event_payloads_for_tool_result(
        tool_request=workflow_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "result": {"ok": True, "action": "artifact.write"},
        },
        event_scope="auto",
    )

    recovery_event = [
        event for event in events if event["event"] == "workflow.run.replan.recovery.updated"
    ][0]
    assert recovery_event["planner_event_type"] == "agent.replan.recovery.updated"
    assert recovery_event["planner_scope"] == "workflow.run"
    assert recovery_event["trigger"] == "verification_failed"
    assert recovery_event["replan_trigger"] == "verification_failed"
    assert recovery_event["replan_triggers"] == ["verification_failed"]
    assert recovery_event["replan_signal_ids"] == ["signal-1"]
    assert recovery_event["replan_recovery_action_id"] == (
        "replan-1:action:1:artifact.write"
    )
    assert recovery_event["source_step_id"] == "analyze-data"
    assert recovery_event["source_tool_name"] == "data.analyze"
    assert recovery_event["target_capability_id"] == "artifact.output"
    assert recovery_event["recovery_actions"][0]["action_id"] == (
        "replan-1:action:1:artifact.write"
    )
    assert recovery_event["recovery_actions"][0]["metadata"]["replan_signal_ids"] == [
        "signal-1"
    ]


def test_replan_recovery_without_step_id_updates_target_progress() -> None:
    source_request = _tool_request()
    recovery_request = {
        "tool": "desktop.open_app",
        "source": "agent_studio_replan_recovery",
        "core_id": source_request["core_id"],
        "workspace_id": source_request["workspace_id"],
        "decision_id": source_request["decision_id"],
        "plan_id": source_request["plan_id"],
        "task_id": source_request["task_id"],
        "workflow_run_id": source_request["workflow_run_id"],
        "replan_request_id": "replan-1",
        "action_id": "action-open-app",
        "replan_trigger": "tool_failure",
        "replan_triggers": ["tool_failure"],
        "replan_signal_ids": ["signal-1"],
        "recovery_action_label": "Open target app",
        "source_step_id": "open-app",
        "source_tool_name": "desktop.open_app",
        "target_capability_id": "desktop.app_discovery",
        "task_verification_targets": [
            {
                "step_id": "write-report",
                "todo": source_request["task_todo"],
                "checkpoints": source_request["task_checkpoints"],
            }
        ],
    }

    events = task_progress_event_payloads_for_tool_result(
        tool_request=recovery_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "desktop.open_app",
            "result": {"ok": True, "summary": "Opened the target app."},
        },
        event_scope="auto",
    )

    assert [event["event"] for event in events] == [
        "workflow.run.task.todo.updated",
        "workflow.run.task.checkpoint.updated",
        "workflow.run.replan.recovery.updated",
    ]
    assert events[0]["status"] == "completed"
    assert events[0]["step_id"] == "write-report"
    assert events[0]["verified_by_step_id"] == (
        "replan-recovery:replan-1:action-open-app"
    )
    assert events[0]["verification_tool"] == "desktop.open_app"
    assert events[1]["checkpoint"]["payload"]["verified_by_step_id"] == (
        "replan-recovery:replan-1:action-open-app"
    )
    recovery_event = events[2]
    assert recovery_event["planner_event_type"] == "agent.replan.recovery.updated"
    assert recovery_event["selected_step_id"] == (
        "replan-recovery:replan-1:action-open-app"
    )
    assert recovery_event["task_verification_targets"][0]["step_id"] == "write-report"
    assert recovery_event["replan_triggers"] == ["tool_failure"]
    assert recovery_event["replan_signal_ids"] == ["signal-1"]
    assert recovery_event["replan_recovery_action_id"] == "action-open-app"
    assert recovery_event["source_step_id"] == "open-app"
    assert recovery_event["source_tool_name"] == "desktop.open_app"
    assert recovery_event["target_capability_id"] == "desktop.app_discovery"
    action = recovery_event["recovery_actions"][0]
    assert action["action_id"] == "action-open-app"
    assert action["verification_targets"][0]["step_id"] == "write-report"
    assert action["metadata"]["verification_target_step_ids"] == ["write-report"]
    assert action["metadata"]["replan_signal_ids"] == ["signal-1"]


def test_public_task_replan_events_project_failed_tool_result() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    tool_request = {
        "tool": "data.analyze",
        "step_id": "analyze-data-file",
        "task_id": "task-1",
        "run_id": "run-1",
    }

    events = public_task_replan_events_for_tool_result(
        decision,
        tool_request=tool_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": False, "error": "unsupported chart type"},
        },
        run_id="run-1",
        after_sequence=30,
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "agent.replan.requested"
    assert event.run_id == "run-1"
    assert event.sequence == 31
    assert event.core_id == decision.plan.task_core.core_id
    assert event.task_id == "task-1"
    assert event.payload["trigger"] == "tool_failure"
    assert event.payload["source_step_id"] == "analyze-data-file"
    assert event.payload["source_tool_name"] == "data.analyze"
    assert event.payload["target_capability_id"] == "data.analysis"
    assert event.payload["fallback_tools"] == ["terminal.run"]
    assert "unsupported chart type" in event.payload["failure_detail"]
    assert "task_core_context" in event.payload["metadata"]


def test_public_task_replan_events_project_explicit_verification_failure() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    events = public_task_replan_events_for_tool_result(
        decision,
        tool_request={
            "tool": "data.analyze",
            "step_id": "analyze-data-file",
            "task_id": "task-1",
            "run_id": "run-1",
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "verification_failed": True,
            "result": {
                "ok": True,
                "summary": "The generated report did not include the requested chart.",
            },
        },
        run_id="run-1",
        after_sequence=40,
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "agent.replan.requested"
    assert event.sequence == 41
    assert event.payload["trigger"] == "verification_failed"
    assert event.payload["source_step_id"] == "analyze-data-file"
    assert event.payload["source_tool_name"] == "data.analyze"
    assert event.payload["target_capability_id"] == "data.analysis"


def test_public_task_replan_events_recover_active_window_mismatch_by_opening_target_app() -> None:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.active_window"],
    )

    events = public_task_replan_events_for_tool_result(
        decision,
        tool_request={
            "tool": "desktop.active_window",
            "step_id": "verify-desktop-result",
            "capability_id": "active_window",
            "task_id": "task-1",
            "run_id": "run-1",
            "verification_target": {"app_name": "PixelForge"},
            "task_verification_targets": [{"step_id": "open-or-focus-app"}],
            "replan_triggers": ["verification_failed"],
            "replan_signal_ids": ["replan-verify-focus"],
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "desktop.active_window",
            "result": {
                "ok": False,
                "error": "foreground_focus_unverified",
                "verification_failed": True,
                "blocking_condition": "foreground_focus_unverified",
                "expected_app_name": "PixelForge",
                "active_app_name": "Finder",
                "data": {
                    "expected_app_name": "PixelForge",
                    "active_app_name": "Finder",
                    "focus_verified": False,
                },
            },
        },
        run_id="run-1",
        after_sequence=50,
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "agent.replan.requested"
    assert event.payload["trigger"] == "verification_failed"
    assert event.payload["fallback_tools"][:2] == ["app.open", "desktop.active_window"]
    assert event.payload["verification_targets"] == [{"step_id": "open-or-focus-app"}]
    assert event.payload["task_verification_targets"] == [
        {"step_id": "open-or-focus-app"}
    ]
    assert event.payload["observation_evidence"]["blocking_condition"] == (
        "foreground_focus_unverified"
    )
    assert event.payload["observation_retry"]["source_tool"] == "desktop.active_window"
    actions = event.payload["metadata"]["recovery_actions"]
    assert actions[0]["tool"] == "app.open"
    assert actions[0]["input"] == {"app_name": "PixelForge"}
    assert actions[0]["selected"] is True
    assert actions[0]["observation_retry"]["reason"] == "foreground_focus_unverified"
    assert actions[0]["metadata"]["runtime_replan_auto_start_eligible"] is True
    continuation = actions[0]["deferred_continuation"][0]
    assert continuation["tool"] == "desktop.active_window"
    assert continuation["verification_target"] == {
        "app_name": "PixelForge",
        "source_tool": "desktop.active_window",
    }


def test_task_replan_payloads_scope_group_run_and_skip_success() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    tool_request = {
        "tool": "data.analyze",
        "step_id": "analyze-data-file",
        "task_id": "task-1",
        "group_run_id": "group-run-1",
    }

    group_events = task_replan_event_payloads_for_tool_result(
        decision,
        tool_request=tool_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": False, "error": "tool unavailable"},
        },
        event_scope="group.run",
    )
    success_events = task_replan_event_payloads_for_tool_result(
        decision,
        tool_request=tool_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": True, "summary": "done"},
        },
        event_scope="group.run",
    )

    assert len(group_events) == 1
    assert group_events[0]["event"] == "group.run.replan.requested"
    assert group_events[0]["planner_event_type"] == "agent.replan.requested"
    assert group_events[0]["payload"]["planner_event_type"] == "agent.replan.requested"
    assert group_events[0]["payload"]["planner_scope"] == "group.run"
    assert group_events[0]["payload"]["trigger"] == "tool_unavailable"
    assert success_events == []


def test_task_replan_payloads_preserve_failed_recovery_action_context() -> None:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    recovery_request = {
        "tool": "terminal.run",
        "input": {"cmd": "python analyze_sales.py"},
        "source": "agent_studio_replan_recovery",
        "step_id": "analyze-data-file",
        "task_id": "task-1",
        "workflow_run_id": "workflow-run-1",
        "replan_request_id": "replan-parent-1",
        "replan_recovery_action_id": "replan-parent-1:action:1:terminal.run",
        "replan_trigger": "tool_failure",
        "replan_triggers": ["tool_failure"],
        "replan_signal_ids": ["signal-analyze"],
        "recovery_action_label": "Run fallback analysis script",
        "source_step_id": "analyze-data-file",
        "source_tool_name": "data.analyze",
        "target_capability_id": "data.analysis",
        "task_verification_targets": [
            {"step_id": "analyze-data-file", "todo_id": "todo-analyze"}
        ],
    }

    events = task_replan_event_payloads_for_tool_result(
        decision,
        tool_request=recovery_request,
        tool_event={
            "event": "agent.tool.call",
            "detail": "terminal.run",
            "result": {"ok": False, "error": "script failed"},
        },
        event_scope="workflow.run",
        run_id="workflow-run-1",
        task_id="task-1",
    )

    assert len(events) == 1
    event = events[0]
    assert event["event"] == "workflow.run.replan.requested"
    assert event["planner_event_type"] == "agent.replan.requested"
    assert event["payload"]["trigger"] == "tool_failure"
    assert event["payload"]["source_step_id"] == "analyze-data-file"
    assert event["payload"]["source_tool_name"] == "terminal.run"
    assert event["payload"]["target_capability_id"] == "data.analysis"
    metadata = event["payload"]["metadata"]
    assert metadata["replan_recovery_failed"] is True
    assert metadata["parent_replan_request_id"] == "replan-parent-1"
    assert metadata["parent_replan_trigger"] == "tool_failure"
    assert metadata["failed_recovery_action_id"] == (
        "replan-parent-1:action:1:terminal.run"
    )
    assert metadata["failed_recovery_action_label"] == "Run fallback analysis script"
    assert metadata["failed_recovery_tool"] == "terminal.run"
    assert metadata["failed_recovery_input"] == {"cmd": "python analyze_sales.py"}
    assert metadata["failed_recovery_source"] == "agent_studio_replan_recovery"
    assert metadata["original_source_tool_name"] == "data.analyze"
    assert metadata["replan_signal_ids"] == ["signal-analyze"]
    assert metadata["failed_recovery_verification_targets"][0]["step_id"] == (
        "analyze-data-file"
    )
    assert metadata["failed_recovery_result_preview"]["error"] == "script failed"


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
