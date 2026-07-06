"""Tests for tool-call execution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.desktop_execution_providers import (
    DesktopExecutionProviderRegistry,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPlugin,
    clear_restricted_tool_plugins,
    register_restricted_tool_plugin,
)
from apps.shell.agent.tools.policy import ToolDescriptorRegistry
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeBudget:
    def __init__(self) -> None:
        self.claims: list[tuple[str, bool]] = []

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.claims.append((tool_name, terminal_execution))


class FakeToolCallEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def denied(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("denied", args, kwargs))

    def requested(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("requested", args, kwargs))

    def failed(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("failed", args, kwargs))

    def started(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("started", args, kwargs))

    def result(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("result", args, kwargs))

    def agent_tool_call(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("agent_tool_call", args, kwargs))


class FakeTraceEvents:
    def memory_skill_trace_event(
        self,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "memory.add":
            return None
        return {
            "event_type": "memory.write.add",
            "payload": {"tool": tool_name, "input_preview": input_preview, "ok": tool_result.get("ok")},
        }

    def artifact_created_payload(
        self,
        tool_result: dict[str, Any],
        *,
        run_id: str,
        source_tool: str = "artifact.write",
    ) -> dict[str, Any]:
        artifact = tool_result.get("artifact") if isinstance(tool_result.get("artifact"), dict) else {}
        payload = {
            "run_id": run_id,
            "path": artifact.get("path") or tool_result.get("path"),
            "source_tool": source_tool,
        }
        if artifact:
            payload["artifact"] = {**artifact, "source_tool": source_tool}
        return payload


class FakeBroker:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(self, tool_name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        self.calls.append((tool_name, payload, approved))
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


class FakeSandboxDesktopAdapter:
    provider_kind = "sandbox_desktop"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def can_execute(
        self,
        tool_name: str,
        route: dict[str, Any],
        tool_request: dict[str, Any],
    ) -> bool:
        return tool_name == "desktop.safe_type_text"

    def execute(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        tool_request: dict[str, Any],
        route: dict[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": tool_name,
                "payload": dict(payload),
                "route": dict(route),
                "approved": approved,
            }
        )
        return {
            "ok": True,
            "tool": tool_name,
            "summary": "Executed in sandbox desktop provider",
            "data": {"text": str(payload.get("text") or "")},
        }


class FakePendingApprovalBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(
        self,
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pending = {
            "approval_id": "approval-1",
            "tool": tool_request.get("tool"),
            "messages": messages,
            "next_iteration": next_iteration,
            "remaining_tool_requests": remaining_tool_requests,
        }
        self.calls.append(pending)
        return pending


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _executor(
    *,
    tool_call_events: FakeToolCallEvents,
    trace_events: FakeTraceEvents | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
    allows_tool=None,
    desktop_provider_registry: Any | None = None,
) -> RuntimeToolCallExecutor:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events or FakeTraceEvents(),
        append_run_event=append_run_event,
        allows_tool=allows_tool,
        desktop_provider_registry=desktop_provider_registry,
    )


def _runner(
    *,
    call_agent_tool,
    pending_approval_builder: FakePendingApprovalBuilder | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> RuntimeToolRequestRunner:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda user_goal, tool_name: (
            "no terminal"
            if tool_name == "terminal.run" and "no commands" in user_goal
            else ""
        ),
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=pending_approval_builder or FakePendingApprovalBuilder(),
        call_agent_tool=call_agent_tool,
    )


def test_runtime_tool_request_runner_resolves_analysis_artifact_body(tmp_path) -> None:
    artifact_text = "Data analysis result for sales.csv.\nEast revenue: 10."
    artifact_path = tmp_path / "analysis-report.md"
    artifact_path.write_text(artifact_text, encoding="utf-8")
    captured_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    class Broker:
        artifact_root = tmp_path

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        return {"ok": True, "summary": "typed"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {
                    "body_source": "analysis_artifact",
                    "artifact_path": "analysis-report.md",
                    "target_action": "app_paste",
                },
                "source": "runtime_planner",
            }
        ],
        ["desktop.safe_type_text"],
        Broker(),
        [{"role": "user", "content": "分析 sales.csv 并写入前台应用"}],
        timeline,
        [
            {
                "path": "analysis-report.md",
                "kind": "markdown",
                "source_tool": "data.analyze",
            }
        ],
        next_iteration=1,
        run_id="run-artifact-body",
    )

    assert captured_requests[0]["input"]["text"] == artifact_text
    assert captured_requests[0]["input"]["body_source"] == "analysis_artifact"
    assert captured_requests[0]["input_resolution"] == {
        "field": "text",
        "body_source": "analysis_artifact",
        "artifact_path": "analysis-report.md",
        "source_tool": "data.analyze",
        "resolved_text_bytes": len(artifact_text.encode("utf-8")),
    }
    assert (
        "run-artifact-body",
        "agent.tool.input_resolved",
        {
            "field": "text",
            "body_source": "analysis_artifact",
            "artifact_path": "analysis-report.md",
            "source_tool": "data.analyze",
            "resolved_text_bytes": len(artifact_text.encode("utf-8")),
            "tool": "desktop.safe_type_text",
        },
    ) in run_events


def test_runtime_tool_request_runner_resolves_research_artifact_body(tmp_path) -> None:
    artifact_text = "Research summary for example.com.\nKey finding: stable."
    artifact_path = tmp_path / "research-summary.md"
    artifact_path.write_text(artifact_text, encoding="utf-8")
    captured_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    class Broker:
        artifact_root = tmp_path

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        return {"ok": True, "summary": "typed"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {
                    "body_source": "research_artifact",
                    "artifact_path": "research-summary.md",
                    "target_action": "app_paste",
                },
                "source": "runtime_planner",
            }
        ],
        ["desktop.safe_type_text"],
        Broker(),
        [{"role": "user", "content": "调研 example.com 并写入前台应用"}],
        timeline,
        [
            {
                "path": "research-summary.md",
                "kind": "markdown",
                "source_tool": "artifact.write",
            }
        ],
        next_iteration=1,
        run_id="run-research-artifact-body",
    )

    assert captured_requests[0]["input"]["text"] == artifact_text
    assert captured_requests[0]["input"]["body_source"] == "research_artifact"
    assert captured_requests[0]["input_resolution"] == {
        "field": "text",
        "body_source": "research_artifact",
        "artifact_path": "research-summary.md",
        "source_tool": "artifact.write",
        "resolved_text_bytes": len(artifact_text.encode("utf-8")),
    }
    assert (
        "run-research-artifact-body",
        "agent.tool.input_resolved",
        {
            "field": "text",
            "body_source": "research_artifact",
            "artifact_path": "research-summary.md",
            "source_tool": "artifact.write",
            "resolved_text_bytes": len(artifact_text.encode("utf-8")),
            "tool": "desktop.safe_type_text",
        },
    ) in run_events


def test_runtime_tool_request_runner_preserves_scope_on_task_progress_events() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "done",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
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
        ],
        ["artifact.write"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "write report"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    todo_event = next(
        event for event in timeline if event["event"] == "workflow.run.task.todo.updated"
    )
    checkpoint_event = next(
        event for event in timeline if event["event"] == "workflow.run.task.checkpoint.updated"
    )
    for event in (todo_event, checkpoint_event):
        assert event["task_id"] == "task-1"
        assert event["group_run_id"] == "group-run-1"
        assert event["workflow_run_id"] == "workflow-run-1"
        assert event["status"] == "completed"
        assert event["planner_scope"] == "workflow.run"
    assert todo_event["planner_event_type"] == "agent.task.todo.updated"
    assert checkpoint_event["planner_event_type"] == "agent.task.checkpoint.updated"

    run_todo_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "workflow.run.task.todo.updated"
    )
    assert run_todo_event["task_id"] == "task-1"
    assert run_todo_event["group_run_id"] == "group-run-1"
    assert run_todo_event["workflow_run_id"] == "workflow-run-1"
    assert run_todo_event["planner_event_type"] == "agent.task.todo.updated"


def test_runtime_tool_request_runner_records_group_scoped_task_progress() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "artifact.write",
            "summary": "done",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "artifact.write",
                "input": {"path": "report.md"},
                "source": "runtime_planner",
                "step_id": "write-report",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "group_run_id": "group-run-1",
                "task_todo": {
                    "todo_id": "todo-write-report",
                    "title": "Write report",
                    "status": "pending",
                    "step_id": "write-report",
                    "tool_name": "artifact.write",
                },
            }
        ],
        ["artifact.write"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "write report"}],
        timeline,
        [],
        next_iteration=1,
        run_id="group-run-1",
        budget=FakeBudget(),
    )

    todo_event = next(
        event for event in timeline if event["event"] == "group.run.task.todo.updated"
    )
    assert todo_event["group_run_id"] == "group-run-1"
    assert todo_event["planner_event_type"] == "agent.task.todo.updated"
    assert todo_event["planner_scope"] == "group.run"
    assert next(
        event_type
        for _run_id, event_type, _payload in run_events
        if event_type == "group.run.task.todo.updated"
    )


def test_runtime_tool_request_runner_marks_operate_steps_ready_for_verification() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "clicked",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "runtime_role": "click_ui",
                "requires_post_action_verification": True,
                "task_todo": {
                    "todo_id": "todo-operate",
                    "title": "Click Export",
                    "status": "pending",
                    "step_id": "operate-foreground-ui",
                    "tool_name": "app.open_and_click_ui_element",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-operate",
                        "title": "Verify Export",
                        "status": "planned",
                        "after_step_id": "operate-foreground-ui",
                    }
                ],
            }
        ],
        ["app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify",
        budget=FakeBudget(),
    )

    todo_event = next(event for event in timeline if event["event"] == "agent.task.todo.updated")
    checkpoint_event = next(
        event for event in timeline if event["event"] == "agent.task.checkpoint.updated"
    )
    assert todo_event["status"] == "in_progress"
    assert todo_event["todo"]["status"] == "in_progress"
    assert checkpoint_event["status"] == "ready"
    assert checkpoint_event["checkpoint"]["status"] == "ready"
    assert not any(event["event"] == "agent.replan.requested" for event in timeline)

    run_checkpoint_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.checkpoint.updated"
    )
    assert run_checkpoint_event["status"] == "ready"


def test_runtime_tool_request_runner_completes_operate_step_after_verify() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    operate_todo = {
        "todo_id": "todo-operate",
        "title": "Click Export",
        "status": "pending",
        "step_id": "operate-foreground-ui",
        "tool_name": "app.open_and_click_ui_element",
    }
    operate_checkpoint = {
        "checkpoint_id": "checkpoint-operate",
        "title": "Verify Export",
        "status": "planned",
        "after_step_id": "operate-foreground-ui",
    }

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "done",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "task_todo": operate_todo,
                "task_checkpoints": [operate_checkpoint],
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"role_filter": "text", "limit": 80},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "depends_on": ["operate-foreground-ui"],
                "task_verification_targets": [
                    {
                        "step_id": "operate-foreground-ui",
                        "todo": operate_todo,
                        "checkpoints": [operate_checkpoint],
                    }
                ],
            },
        ],
        ["app.open_and_click_ui_element", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-complete",
        budget=FakeBudget(),
    )

    todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert todo_statuses == ["in_progress", "completed"]
    assert checkpoint_statuses == ["ready", "completed"]
    completed_checkpoint = next(
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
        and event["status"] == "completed"
    )
    assert completed_checkpoint["verified_by_step_id"] == "verify-desktop-result"
    assert completed_checkpoint["previous_status"] == "ready"

    run_todo_statuses = [
        payload["status"]
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.todo.updated"
        and payload["todo_id"] == "todo-operate"
    ]
    assert run_todo_statuses == ["in_progress", "completed"]


def test_runtime_tool_request_runner_records_verification_failure_recovery_context() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    operate_todo = {
        "todo_id": "todo-operate",
        "title": "Click Export",
        "status": "pending",
        "step_id": "operate-foreground-ui",
        "tool_name": "app.open_and_click_ui_element",
    }
    operate_checkpoint = {
        "checkpoint_id": "checkpoint-operate",
        "title": "Verify Export",
        "status": "planned",
        "after_step_id": "operate-foreground-ui",
    }

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if str(tool_request.get("tool") or "") == "desktop.ui_elements":
            return {
                "ok": False,
                "verification_failed": True,
                "summary": "Export dialog is still not visible",
                "blocking_condition": "ui_inspection_failed",
            }
        return {"ok": True, "summary": "clicked"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "task_todo": operate_todo,
                "task_checkpoints": [operate_checkpoint],
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "PixelForge", "role_filter": "text", "limit": 80},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "capability_id": "desktop.visual_verification",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "depends_on": ["operate-foreground-ui"],
                "replan_signal_ids": ["signal-verify-export-failed"],
                "replan_triggers": ["verification_failed"],
                "task_verification_targets": [
                    {
                        "step_id": "operate-foreground-ui",
                        "todo": operate_todo,
                        "checkpoints": [operate_checkpoint],
                    }
                ],
            },
        ],
        ["app.open_and_click_ui_element", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-failed",
        budget=FakeBudget(),
    )

    todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert todo_statuses == ["in_progress", "blocked"]
    assert checkpoint_statuses == ["ready", "blocked"]

    replan_event = next(
        event for event in timeline if event["event"] == "agent.replan.requested"
    )
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_step_id"] == "verify-desktop-result"
    assert payload["source_tool_name"] == "desktop.ui_elements"
    assert payload["verification_targets"][0]["step_id"] == "operate-foreground-ui"
    assert payload["verification_targets"][0]["todo_id"] == "todo-operate"
    assert payload["action_target"]["action"] == "verify_after_action"
    assert payload["action_target"]["step_id"] == "operate-foreground-ui"
    assert payload["action_target"]["todo_id"] == "todo-operate"
    assert payload["action_target"]["app_name"] == "PixelForge"
    assert payload["observation_evidence"]["source_tool"] == "desktop.ui_elements"
    assert payload["observation_evidence"]["verification_failed"] is True
    assert payload["observation_retry"]["tool"] == "desktop.ui_elements"
    assert payload["observation_retry"]["input"]["app_name"] == "PixelForge"
    assert payload["metadata"]["verification_targets"] == payload["verification_targets"]
    assert payload["metadata"]["action_target"] == payload["action_target"]
    assert payload["metadata"]["recovery_actions"][0]["tool"] == "desktop.ui_elements"
    assert (
        payload["metadata"]["recovery_actions"][0]["action_target"]["step_id"]
        == "operate-foreground-ui"
    )

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == payload["request_id"]
    assert run_replan_event["metadata"]["action_target"] == payload["action_target"]

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {"reason": "re-observe failed verification target"},
                "source": "runtime_planner",
                "planning_reason": "planner_replan_runtime_recovery_action",
                "step_id": "verify-desktop-result",
                "replan_request_id": payload["request_id"],
                "replan_trigger": "verification_failed",
                "verification_targets": payload["verification_targets"],
                "action_target": payload["action_target"],
                "observation_evidence": payload["observation_evidence"],
                "observation_retry": payload["observation_retry"],
                "recovery_action_label": "Re-observe failed verification target",
            }
        ],
        ["desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-verify-failed",
        budget=FakeBudget(),
    )

    recovery_update = next(
        event for event in timeline if event["event"] == "agent.replan.recovery.updated"
    )
    assert recovery_update["request_id"] == payload["request_id"]
    assert recovery_update["verification_targets"] == payload["verification_targets"]
    assert recovery_update["action_target"] == payload["action_target"]
    recovered_todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    recovered_checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert recovered_todo_statuses == ["in_progress", "blocked", "completed"]
    assert recovered_checkpoint_statuses == ["ready", "blocked", "completed"]
    recovered_todo = next(
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
        and event["status"] == "completed"
    )
    assert recovered_todo["previous_status"] == "blocked"
    assert recovered_todo["verified_by_step_id"] == "verify-desktop-result"
    run_recovery_update = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.recovery.updated"
    )
    assert run_recovery_update["verification_targets"] == payload["verification_targets"]
    run_recovered_todo_statuses = [
        payload["status"]
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.todo.updated"
        and payload["todo_id"] == "todo-operate"
    ]
    assert run_recovered_todo_statuses == ["in_progress", "blocked", "completed"]


def test_runtime_tool_request_runner_records_replan_request_for_failed_planned_step() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "unsupported chart type",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_id": "task-1",
                "group_run_id": "group-run-1",
                "workflow_run_id": "workflow-run-1",
                "replan_signal_ids": ["signal-analyze-failed"],
                "replan_triggers": ["tool_failure"],
                "fallback_tools": ["terminal.run"],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    replan_event = next(
        event for event in timeline if event["event"] == "workflow.run.replan.requested"
    )
    assert replan_event["task_id"] == "task-1"
    assert replan_event["group_run_id"] == "group-run-1"
    assert replan_event["workflow_run_id"] == "workflow-run-1"
    assert replan_event["payload"]["planner_event_type"] == "agent.replan.requested"
    assert replan_event["payload"]["planner_scope"] == "workflow.run"
    assert replan_event["payload"]["trigger"] == "tool_failure"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    assert replan_event["payload"]["source_tool_name"] == "data.analyze"
    assert replan_event["payload"]["target_capability_id"] == "data.analysis"
    assert replan_event["payload"]["input_preview"] == {"path": "data/sales.csv"}
    assert replan_event["payload"]["metadata"]["input_preview"] == {
        "path": "data/sales.csv"
    }
    assert replan_event["payload"]["fallback_tools"] == ["terminal.run"]
    assert "unsupported chart type" in replan_event["payload"]["failure_detail"]

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "workflow.run.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]
    assert run_replan_event["replan_signal_ids"] == ["signal-analyze-failed"]


def test_runtime_tool_request_runner_uses_capability_recovery_for_generic_media_tool() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "media bridge unavailable",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "media.spotify_open_and_play",
                "input": {"app_name": "Spotify", "query": "lofi study"},
                "source": "runtime_planner",
                "step_id": "play-media",
                "capability_id": "media.playback",
            }
        ],
        ["media.spotify_open_and_play", "desktop.list_apps", "app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "play lofi in Spotify"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-generic-media-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "tool_unavailable"
    assert payload["source_tool_name"] == "media.spotify_open_and_play"
    assert payload["target_capability_id"] == "media.playback"
    assert payload["fallback_tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    recovery_actions = payload["metadata"]["recovery_actions"]
    assert [action["tool"] for action in recovery_actions] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert recovery_actions[0]["input"] == {"query": "lofi study", "limit": 20}
    assert recovery_actions[1]["input"] == {"app_name": "Spotify"}
    assert recovery_actions[2]["input"] == {}
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["fallback_tools"] == payload["fallback_tools"]


def test_runtime_tool_request_runner_projects_data_analysis_python_recovery_action() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "built-in parser could not parse file",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "replan_triggers": ["tool_failure"],
            }
        ],
        ["data.analyze", "python.run", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data/sales.csv"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-data-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["fallback_tools"] == ["python.run", "terminal.run"]
    assert payload["recovery_actions"] == payload["metadata"]["recovery_actions"]
    recovery_actions = payload["metadata"]["recovery_actions"]
    assert len(recovery_actions) == 1
    python_action = recovery_actions[0]
    assert python_action["tool"] == "python.run"
    assert python_action["permission_target"] == "terminal_execution"
    assert python_action["risk_level"] == "high"
    assert python_action["approval_required"] is True
    assert "data/sales.csv" in python_action["input"]["code"]
    assert "pd.read_csv" in python_action["input"]["code"]
    assert python_action["metadata"] == {
        "runtime_replan_auto_start_eligible": False,
        "runtime_replan_auto_start_reason": "manual_runtime_replan_recovery_required",
        "runtime_replan_auto_start_blockers": [
            "approval_required",
            "high_risk",
            "tool_not_auto_safe",
        ],
    }
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["recovery_actions"] == payload["recovery_actions"]


def test_runtime_tool_request_runner_records_group_scoped_replan_request() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "group analysis failed",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "group_run_id": "group-run-1",
                "replan_triggers": ["tool_failure"],
                "fallback_tools": ["terminal.run"],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="group-run-1",
        budget=FakeBudget(),
    )

    replan_event = next(
        event for event in timeline if event["event"] == "group.run.replan.requested"
    )
    assert replan_event["group_run_id"] == "group-run-1"
    assert replan_event["payload"]["planner_event_type"] == "agent.replan.requested"
    assert replan_event["payload"]["planner_scope"] == "group.run"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "group.run.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]


def test_runtime_tool_request_runner_records_explicit_verification_failure_replan() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "verification_failed": True,
            "summary": "The generated report did not include the requested chart.",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_id": "task-1",
                "replan_signal_ids": ["signal-analyze-verify-failed"],
                "replan_triggers": ["verification_failed"],
                "fallback_tools": ["terminal.run"],
                "task_todo": {
                    "todo_id": "todo-analyze-data",
                    "title": "Analyze data",
                    "status": "pending",
                    "step_id": "analyze-data-file",
                    "tool_name": "data.analyze",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-analyze-data",
                        "title": "Verify analysis",
                        "status": "planned",
                        "after_step_id": "analyze-data-file",
                    }
                ],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-1",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    assert replan_event["payload"]["trigger"] == "verification_failed"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    assert replan_event["payload"]["source_tool_name"] == "data.analyze"
    assert replan_event["payload"]["target_capability_id"] == "data.analysis"
    assert replan_event["payload"]["fallback_tools"] == ["terminal.run"]
    assert (
        replan_event["payload"]["failure_detail"]
        == "The generated report did not include the requested chart."
    )
    todo_event = next(
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-analyze-data"
    )
    checkpoint_event = next(
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-analyze-data"
    )
    assert todo_event["status"] == "blocked"
    assert todo_event["todo"]["status"] == "blocked"
    assert checkpoint_event["status"] == "blocked"
    assert checkpoint_event["checkpoint"]["status"] == "blocked"

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]
    assert run_replan_event["replan_signal_ids"] == ["signal-analyze-verify-failed"]


def test_runtime_tool_request_runner_synthesizes_observation_retry_recovery_action() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    observation_retry = {
        "from_tool": "desktop.active_window",
        "tool": "desktop.active_window",
        "input": {
            "app_name": "PixelForge",
            "query": "PixelForge",
            "selection_source": "desktop.list_apps",
        },
        "reason": "verification_failed",
    }
    action_target = {
        "kind": "desktop_app",
        "action": "verify_after_action",
        "app_name": "PixelForge",
        "step_id": "verify-desktop-result",
    }
    observation_evidence = {
        "source_tool": "desktop.active_window",
        "app_name": "PixelForge",
    }

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "verification_failed": True,
            "summary": "Active app was not PixelForge.",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "capability_id": "desktop.visual_verification",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
                "action_target": action_target,
                "observation_evidence": observation_evidence,
                "observation_retry": observation_retry,
            }
        ],
        ["desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open PixelForge"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-observation-retry",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["fallback_tools"] == ["desktop.active_window"]
    assert payload["action_target"] == action_target
    assert payload["observation_evidence"] == observation_evidence
    assert payload["observation_retry"] == observation_retry
    assert payload["recovery_actions"] == payload["metadata"]["recovery_actions"]
    assert payload["metadata"]["recovery_actions"] == [
        {
            "label": "Re-run runtime observation",
            "tool": "desktop.active_window",
            "input": {
                "app_name": "PixelForge",
                "query": "PixelForge",
                "selection_source": "desktop.list_apps",
            },
            "permission_target": "runtime_observation",
            "risk_level": "low",
            "observation_retry": observation_retry,
            "action_target": action_target,
            "observation_evidence": observation_evidence,
            "metadata": {
                "runtime_replan_auto_start_eligible": True,
                "runtime_replan_auto_start_reason": (
                    "safe_low_risk_runtime_replan_recovery"
                ),
                "runtime_replan_auto_start_blockers": [],
            },
        }
    ]
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["metadata"]["recovery_actions"] == payload["metadata"][
        "recovery_actions"
    ]
    assert run_replan_event["recovery_actions"] == payload["recovery_actions"]


def test_runtime_tool_request_runner_marks_unsafe_recovery_actions_manual() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "terminal retry failed",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data",
                "capability_id": "data.analysis",
                "requires_observation": True,
                "replan_triggers": ["tool_failure"],
                "recovery_actions": [
                    {
                        "label": "Run fallback script",
                        "tool": "terminal.run",
                        "input": {"command": "python analyze_sales.py"},
                        "risk_level": "high",
                        "approval_required": True,
                    }
                ],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Analyze sales.csv"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-unsafe-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    action_metadata = replan_event["payload"]["metadata"]["recovery_actions"][0]["metadata"]
    assert action_metadata["runtime_replan_auto_start_eligible"] is False
    assert action_metadata["runtime_replan_auto_start_reason"] == (
        "manual_runtime_replan_recovery_required"
    )
    assert action_metadata["runtime_replan_auto_start_blockers"] == [
        "approval_required",
        "high_risk",
        "tool_not_auto_safe",
    ]


def test_runtime_tool_request_runner_records_explicit_desktop_verification_target() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(tool_request)
        return {
            "ok": False,
            "verification_failed": True,
            "error": "foreground_focus_unverified",
            "blocking_condition": "foreground_focus_unverified",
            "blocking_conditions": ["foreground_focus_unverified"],
            "summary": "Chrome is active",
            "expected_app_name": "PixelForge",
            "active_app_name": "Chrome",
            "data": {
                "app_name": "Chrome",
                "title": "Search",
                "expected_app_name": "PixelForge",
                "active_app_name": "Chrome",
                "focus_verified": False,
            },
        }

    runner = _runner(
        call_agent_tool=call_agent_tool,
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {},
                "source": "runtime_verification",
                "planning_reason": "runtime_desktop_app_foreground_verification",
                "capability_id": "desktop.visual_verification",
                "runtime_doctrine": "discover_operate_verify",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
                "target_app_name": "PixelForge",
                "verification_target": {"app_name": "PixelForge"},
            }
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open PixelForge"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-explicit-desktop-verification-target",
        budget=FakeBudget(),
    )

    assert seen_requests[0]["verification_target"] == {"app_name": "PixelForge"}
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_tool_name"] == "desktop.active_window"
    assert payload["target_app_name"] == "PixelForge"
    assert payload["metadata"]["target_app_name"] == "PixelForge"
    assert payload["verification_targets"] == [
        {
            "kind": "desktop_verification_target",
            "tool_name": "desktop.active_window",
            "app_name": "PixelForge",
            "target_app_name": "PixelForge",
        }
    ]
    assert payload["action_target"] == {
        "kind": "desktop_verification_target",
        "action": "verify_after_action",
        "verification_tool": "desktop.active_window",
        "tool_name": "desktop.active_window",
        "app_name": "PixelForge",
    }
    actions = payload["metadata"]["recovery_actions"]
    assert actions[0]["tool"] == "app.open"
    assert actions[0]["input"] == {"app_name": "PixelForge"}
    assert actions[0]["selected"] is True
    assert actions[0]["observation_retry"]["reason"] == "foreground_focus_unverified"
    assert actions[0]["deferred_continuation"][0]["tool"] == "desktop.active_window"
    assert actions[0]["deferred_continuation"][0]["verification_target"] == {
        "app_name": "PixelForge",
        "source_tool": "desktop.active_window",
    }
    assert (
        actions[0]["action_target"]
        == payload["action_target"]
    )
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["target_app_name"] == "PixelForge"
    assert run_replan_event["metadata"]["target_app_name"] == "PixelForge"


def test_runtime_tool_request_runner_synthesizes_default_desktop_failure_replan() -> None:
    calls: list[str] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(str(tool_request.get("tool") or ""))
        return {
            "ok": False,
            "error": "foreground input failed",
        }

    runner = _runner(
        call_agent_tool=call_agent_tool,
        run_events=run_events,
    )
    messages = [{"role": "user", "content": "type into the current app"}]

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
            },
            {
                "tool": "desktop.safe_key",
                "input": {"action": "return"},
            },
        ],
        ["desktop.safe_type_text", "desktop.safe_key"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-default-desktop-replan",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]

    assert payload["trigger"] == "tool_failure"
    assert payload["source_tool_name"] == "desktop.safe_type_text"
    assert payload["fallback_tools"] == [
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
    ]
    assert [
        action["tool"] for action in payload["metadata"]["recovery_actions"]
    ] == [
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
    ]
    assert calls == ["desktop.safe_type_text"]
    assert len([event for event in timeline if event["event"] == "agent.replan.requested"]) == 1
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["fallback_tools"] == payload["fallback_tools"]
    assert "recovery_actions" in messages[-1]["content"]


def test_runtime_tool_call_executor_denies_unallowed_tools_before_broker_call() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {"tool": "terminal.run", "input": {"command": "echo hi"}},
            ["workspace.read"],
            broker,
            timeline,
            run_id="run-1",
            budget=budget,
        )

    assert budget.claims == [("terminal.run", False)]
    assert broker.calls == []
    assert timeline == [
        {
            "event": "agent.tool.denied",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
        }
    ]
    assert [call[0] for call in events.calls] == ["denied"]


def test_runtime_tool_call_executor_uses_injected_policy_gate() -> None:
    events = FakeToolCallEvents()
    policy_calls: list[tuple[str, list[str]]] = []
    executor = _executor(
        tool_call_events=events,
        allows_tool=lambda tool_name, allowed_tools: policy_calls.append(
            (tool_name, allowed_tools)
        )
        or False,
    )
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {"tool": "workspace.read", "input": {"path": "README.md"}},
            ["workspace.read"],
            broker,
            [],
            budget=FakeBudget(),
        )

    assert policy_calls == [("workspace.read", ["workspace.read"])]
    assert broker.calls == []


def test_runtime_tool_call_executor_validates_active_window_target_before_projection() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []

    result = executor.execute(
        {
            "tool": "desktop.active_window",
            "input": {},
            "verification_target": {"app_name": "Safari"},
        },
        ["desktop.active_window"],
        FakeBroker({"ok": True, "data": {"app_name": "Google Chrome", "title": "Search"}}),
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["verification_failed"] is True
    assert result["error"] == "foreground_focus_unverified"
    assert result["data"]["expected_app_name"] == "Safari"
    assert result["data"]["active_app_name"] == "Google Chrome"
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"]["ok"] is False
    assert events.calls[-1][0] == "agent_tool_call"
    assert events.calls[-1][1][3]["ok"] is False

    matching_timeline: list[dict[str, Any]] = []
    matching = executor.execute(
        {
            "tool": "desktop.active_window",
            "input": {},
            "verification_target": {"app_name": "Chrome"},
        },
        ["desktop.active_window"],
        FakeBroker({"ok": True, "data": {"app_name": "Google Chrome", "title": "Search"}}),
        matching_timeline,
        run_id="run-2",
        budget=FakeBudget(),
    )

    assert matching["ok"] is True
    assert matching["data"]["focus_verified"] is True


def test_runtime_tool_call_executor_projects_workspace_failure_as_tool_result() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker(AgentRuntimeError("outside workspace"))

    result = executor.execute(
        {"tool": "workspace.read", "input": {"path": "../secret.txt"}},
        ["workspace.read", "terminal.run"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["tool"] == "workspace.read"
    assert result["suggested_tool"] == "terminal.run"
    assert "relative paths" in result["hint"]
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"] == result
    assert [call[0] for call in events.calls] == [
        "requested",
        "started",
        "result",
        "agent_tool_call",
    ]


def test_runtime_tool_call_executor_routes_sandbox_ready_tool_to_provider() -> None:
    events = FakeToolCallEvents()
    adapter = FakeSandboxDesktopAdapter()
    registry = DesktopExecutionProviderRegistry([adapter])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
                "supported_tools": ["desktop.safe_type_text"],
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == "sandbox_desktop"
    assert result["desktop_execution_route"]["status"] == "sandbox_ready"
    assert result["sandbox_provider"]["provider_id"] == "sandbox-1"
    assert adapter.calls == [
        {
            "tool": "desktop.safe_type_text",
            "payload": {"text": "hello"},
            "route": result["desktop_execution_route"],
            "approved": False,
        }
    ]
    assert broker.calls == []
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"]["desktop_execution_provider_routed"] is True


def test_runtime_tool_call_executor_blocks_provider_route_until_approved() -> None:
    events = FakeToolCallEvents()
    adapter = FakeSandboxDesktopAdapter()
    registry = DesktopExecutionProviderRegistry([adapter])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})
    broker.approvals = {"desktop.safe_type_text": True}

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "approval_required": True,
            "risk_level": "high",
            "policy_reason": "Provider-routed foreground input requires approval.",
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
                "supported_tools": ["desktop.safe_type_text"],
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["approval_required"] is True
    assert result["risk_level"] == "high"
    assert result["policy_reason"] == (
        "Provider-routed foreground input requires approval."
    )
    assert adapter.calls == []
    assert broker.calls == []
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"]["approval_required"] is True


def test_runtime_tool_call_executor_fails_closed_when_provider_adapter_is_missing() -> None:
    events = FakeToolCallEvents()
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(),
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_provider"] is True
    assert result["error"] == "desktop_execution_provider_unavailable"
    assert result["blocking_conditions"] == ["desktop_execution_provider_unavailable"]
    assert result["desktop_execution_provider"]["adapter_registered"] is False
    assert result["desktop_execution_route"]["status"] == "sandbox_ready"
    assert broker.calls == []
    assert timeline[-1]["result"]["blocked_by_desktop_execution_provider"] is True


def test_runtime_tool_call_executor_preserves_planner_trace_on_tool_call_events() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "data": {"app_name": "PixelForge"}})

    result = executor.execute(
        {
            "tool": "desktop.open_path",
            "input": {"path": "legacy-report.xls"},
            "source": "runtime_planner",
            "planning_reason": "planner_replan_fallback_recovery",
            "step_id": "inspect-data-source",
            "capability_id": "file.workspace_read",
            "capability_title": "Read workspace file",
            "capability_status": "selected",
            "capability_reason": "The task needs to inspect a local source file.",
            "capability_selected_tools": ["workspace.read", "desktop.open_path"],
            "capability_planned_step_ids": ["inspect-data-source", "open-source-file"],
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "replan_request_id": "replan-1",
            "replan_trigger": "tool_failure",
            "target_app_name": "Figma",
            "target_app_query": "design",
            "target_search_text": "logo 模板",
        },
        ["desktop.open_path"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert timeline[0]["event"] == "agent.tool.started"
    assert timeline[0]["status"] == "running"
    assert timeline[0]["step_id"] == "inspect-data-source"
    assert timeline[0]["capability_id"] == "file.workspace_read"
    assert timeline[0]["capability_title"] == "Read workspace file"
    assert timeline[0]["capability_selected_tools"] == ["workspace.read", "desktop.open_path"]
    assert timeline[0]["capability_planned_step_ids"] == [
        "inspect-data-source",
        "open-source-file",
    ]
    assert timeline[0]["core_id"] == "core-1"
    assert timeline[0]["target_app_name"] == "Figma"
    assert timeline[0]["replan_request_id"] == "replan-1"
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["step_id"] == "inspect-data-source"
    assert timeline[-1]["capability_id"] == "file.workspace_read"
    assert timeline[-1]["capability_title"] == "Read workspace file"
    assert timeline[-1]["capability_reason"] == "The task needs to inspect a local source file."
    assert timeline[-1]["core_id"] == "core-1"
    assert timeline[-1]["target_app_name"] == "Figma"
    assert timeline[-1]["replan_request_id"] == "replan-1"
    agent_call = [call for call in events.calls if call[0] == "agent_tool_call"][0]
    assert agent_call[2]["trace"] == {
        "source": "runtime_planner",
        "planning_reason": "planner_replan_fallback_recovery",
        "step_id": "inspect-data-source",
        "capability_id": "file.workspace_read",
        "capability_title": "Read workspace file",
        "capability_status": "selected",
        "capability_reason": "The task needs to inspect a local source file.",
        "capability_selected_tools": ["workspace.read", "desktop.open_path"],
        "capability_planned_step_ids": ["inspect-data-source", "open-source-file"],
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "replan_request_id": "replan-1",
        "replan_trigger": "tool_failure",
        "target_app_name": "Figma",
        "target_app_query": "design",
        "target_search_text": "logo 模板",
    }
    lifecycle_trace = {
        call[0]: call[2]["trace"]
        for call in events.calls
        if call[0] in {"requested", "started", "result"}
    }
    assert lifecycle_trace == {
        "requested": agent_call[2]["trace"],
        "started": agent_call[2]["trace"],
        "result": agent_call[2]["trace"],
    }


def test_runtime_tool_call_executor_records_non_workspace_failures() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)

    with pytest.raises(AgentRuntimeError, match="boom"):
        executor.execute(
            {"tool": "terminal.run", "input": {"command": "echo hi"}},
            ["terminal.run"],
            FakeBroker(AgentRuntimeError("boom")),
            [],
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert [call[0] for call in events.calls] == ["requested", "started", "failed"]


def test_runtime_tool_call_executor_counts_approved_python_run_as_terminal_execution() -> None:
    executor = _executor(tool_call_events=FakeToolCallEvents())
    budget = FakeBudget()

    result = executor.execute(
        {"tool": "python.run", "input": {"code": "print('ok')"}},
        ["python.run"],
        FakeBroker({"ok": True}),
        [],
        approved=True,
        run_id="run-1",
        budget=budget,
    )

    assert result["ok"] is True
    assert budget.claims == [("python.run", True)]


def test_runtime_tool_call_executor_projects_trace_and_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []

    artifact_result = executor.execute(
        {"tool": "artifact.write", "input": {"path": "notes.md", "content": "body"}},
        ["artifact.write"],
        FakeBroker({"ok": True, "path": "notes.md", "content": "body"}),
        [],
        artifacts=artifacts,
        run_id="run-1",
        budget=FakeBudget(),
    )
    memory_result = executor.execute(
        {"tool": "memory.add", "input": {"content": "remember"}},
        ["memory.add"],
        FakeBroker({"ok": True, "memory_id": "mem-1"}),
        [],
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert artifact_result["ok"] is True
    assert memory_result["ok"] is True
    assert artifacts == [{"kind": "tool_artifact", **artifact_result}]
    assert ("run-1", "artifact.created", {"run_id": "run-1", "path": "notes.md", "source_tool": "artifact.write"}) in run_events
    assert ("run-1", "memory.write.add", {"tool": "memory.add", "input_preview": {"content": "remember"}, "ok": True}) in run_events


def test_runtime_tool_call_executor_preserves_scope_on_memory_skill_trace_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)

    result = executor.execute(
        {
            "tool": "memory.add",
            "input": {"content": "remember"},
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "group_run_id": "group-run-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_node_id": "remember",
        },
        ["memory.add"],
        FakeBroker({"ok": True, "memory_id": "mem-1"}),
        [],
        run_id="run-memory",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    memory_payload = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "memory.write.add"
    )
    for key, value in {
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "group_run_id": "group-run-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "remember",
    }.items():
        assert memory_payload[key] == value
        assert memory_payload["input_preview"][key] == value


def test_runtime_tool_call_executor_projects_structured_tool_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    screen_artifact = {
        "path": "screenshots/current-screen.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": 321,
        "width": 800,
        "height": 600,
    }

    result = executor.execute(
        {"tool": "screen.capture", "input": {"display": "main"}},
        ["screen.capture"],
        FakeBroker({"ok": True, "summary": "Captured screen", "artifact": screen_artifact}),
        [],
        artifacts=artifacts,
        run_id="run-screen",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [{**screen_artifact, "source_tool": "screen.capture"}]
    assert (
        "run-screen",
        "artifact.created",
        {
            "run_id": "run-screen",
            "path": "screenshots/current-screen.png",
            "source_tool": "screen.capture",
            "artifact": {**screen_artifact, "source_tool": "screen.capture"},
        },
    ) in run_events


def test_runtime_tool_call_executor_preserves_scope_on_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    report_artifact = {
        "path": "reports/analysis.md",
        "kind": "markdown",
        "mime_type": "text/markdown",
    }
    request_context = {
        "source": "runtime_planner",
        "decision_id": "decision-1",
        "plan_id": "plan-1",
        "step_id": "write-analysis",
        "capability_id": "data.analysis",
        "capability_title": "Analyze data",
        "capability_status": "selected",
        "capability_reason": "The user asked for a data-backed report artifact.",
        "capability_selected_tools": ["data.analyze", "artifact.write"],
        "capability_planned_step_ids": ["analyze-data", "write-analysis"],
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "group_id": "group-1",
        "run_group_id": "run-group-1",
        "group_run_id": "group-run-1",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "node-analyze",
        "workflow_node_label": "Analyze data",
    }

    result = executor.execute(
        {
            "tool": "data.analyze",
            "input": {"path": "sales.csv"},
            **request_context,
        },
        ["data.analyze"],
        FakeBroker({"ok": True, "summary": "Analyzed data", "artifact": report_artifact}),
        [],
        artifacts=artifacts,
        run_id="run-data",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [
        {
            **report_artifact,
            "source_tool": "data.analyze",
            **request_context,
        }
    ]
    artifact_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "artifact.created"
    )
    for key, value in request_context.items():
        assert artifact_event[key] == value
        assert artifact_event["artifact"][key] == value
    assert artifact_event["path"] == "reports/analysis.md"
    assert artifact_event["source_tool"] == "data.analyze"


def test_runtime_tool_call_executor_projects_multiple_structured_artifacts() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    markdown_artifact = {
        "path": "analysis-report.md",
        "kind": "markdown",
        "mime_type": "text/markdown",
        "size_bytes": 120,
    }
    chart_artifact = {
        "path": "analysis-chart.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": 321,
        "width": 640,
        "height": 360,
    }

    result = executor.execute(
        {"tool": "data.analyze", "input": {"path": "sales.csv"}},
        ["data.analyze"],
        FakeBroker(
            {
                "ok": True,
                "summary": "Analyzed data",
                "artifact": markdown_artifact,
                "artifacts": [markdown_artifact, chart_artifact],
            }
        ),
        [],
        artifacts=artifacts,
        run_id="run-data",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [
        {**markdown_artifact, "source_tool": "data.analyze"},
        {**chart_artifact, "source_tool": "data.analyze"},
    ]
    assert (
        "run-data",
        "artifact.created",
        {
            "run_id": "run-data",
            "path": "analysis-chart.png",
            "source_tool": "data.analyze",
            "artifact": {**chart_artifact, "source_tool": "data.analyze"},
        },
    ) in run_events


def test_runtime_tool_call_executor_routes_restricted_plugin_tools_through_timeline(
    tmp_path,
) -> None:
    clear_restricted_tool_plugins()

    def echo_tool(payload, context):
        return {
            "ok": True,
            "summary": f"Echoed {payload['text']}",
            "context_tool": context.tool_name,
        }

    try:
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="notes",
                tools=(
                    RestrictedPluginTool(
                        tool_id="echo",
                        description="Echo text through a restricted plugin.",
                        properties={"text": {"type": "string"}},
                        required=("text",),
                        risk_level="low",
                        execute=echo_tool,
                    ),
                ),
            )
        )
        tool_name = "plugin.notes.echo"
        events = FakeToolCallEvents()
        executor = RuntimeToolCallExecutor(
            normalize_tool_name=lambda value: str(value or "").strip(),
            input_preview=lambda value: value,
            run_budget=lambda _run_id, _timeline: FakeBudget(),
            validate_tool_payload=ToolDescriptorRegistry.validate_payload,
            limit_tool_result=lambda result: result,
            timeline_factory=_timeline,
            tool_call_events=events,
            trace_events=FakeTraceEvents(),
            append_run_event=lambda _run_id, _event_type, _payload: None,
        )
        broker = ToolBroker(
            {
                "default_workdir": str(tmp_path),
                "readable_scopes": ["."],
                "writable_scopes": [],
            },
            tmp_path / "artifacts",
        )
        timeline: list[dict[str, Any]] = []

        result = executor.execute(
            {"tool": tool_name, "input": {"text": "hello"}},
            [tool_name],
            broker,
            timeline,
            run_id="run-1",
            budget=FakeBudget(),
        )

        assert result["ok"] is True
        assert result["summary"] == "Echoed hello"
        assert result["plugin_id"] == "notes"
        assert result["risk_level"] == "low"
        assert timeline[-1]["event"] == "agent.tool.call"
        assert timeline[-1]["detail"] == tool_name
        assert timeline[-1]["result"] == result
        assert [call[0] for call in events.calls] == [
            "requested",
            "started",
            "result",
            "agent_tool_call",
        ]
    finally:
        clear_restricted_tool_plugins()


def test_runtime_tool_request_runner_pauses_for_high_risk_restricted_plugin(
    tmp_path,
) -> None:
    clear_restricted_tool_plugins()

    def destructive_tool(payload, context):
        return {"ok": True, "approved": context.approved, "target": payload["target"]}

    try:
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="ops",
                tools=(
                    RestrictedPluginTool(
                        tool_id="delete_file",
                        description="High-risk restricted plugin test tool.",
                        properties={"target": {"type": "string"}},
                        required=("target",),
                        risk_level="high",
                        execute=destructive_tool,
                    ),
                ),
            )
        )
        tool_name = "plugin.ops.delete_file"
        events = FakeToolCallEvents()
        executor = RuntimeToolCallExecutor(
            normalize_tool_name=lambda value: str(value or "").strip(),
            input_preview=lambda value: value,
            run_budget=lambda _run_id, _timeline: FakeBudget(),
            validate_tool_payload=ToolDescriptorRegistry.validate_payload,
            limit_tool_result=lambda result: result,
            timeline_factory=_timeline,
            tool_call_events=events,
            trace_events=FakeTraceEvents(),
            append_run_event=lambda _run_id, _event_type, _payload: None,
        )
        runner = _runner(
            call_agent_tool=executor.execute,
            pending_approval_builder=FakePendingApprovalBuilder(),
        )
        broker = ToolBroker(
            {
                "default_workdir": str(tmp_path),
                "readable_scopes": ["."],
                "writable_scopes": [],
            },
            tmp_path / "artifacts",
        )
        timeline: list[dict[str, Any]] = []
        messages = [{"role": "user", "content": "delete the file"}]

        with pytest.raises(AgentApprovalRequired) as exc_info:
            runner.run(
                [{"tool": tool_name, "input": {"target": "notes.md"}}],
                [tool_name],
                broker,
                messages,
                timeline,
                [],
                next_iteration=4,
                run_id="run-1",
                budget=FakeBudget(),
            )

        assert exc_info.value.pending_approval["tool"] == tool_name
        assert timeline[-1]["event"] == "agent.tool.call"
        assert timeline[-1]["result"]["approval_required"] is True
        assert timeline[-1]["result"]["risk_level"] == "high"
        assert [call[0] for call in events.calls] == [
            "requested",
            "started",
            "result",
            "agent_tool_call",
        ]
    finally:
        clear_restricted_tool_plugins()


def test_native_runtime_uses_split_tool_call_executor(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolCallExecutor is RuntimeToolCallExecutor
        assert isinstance(service.tool_call_executor, RuntimeToolCallExecutor)
    finally:
        service.close()


def test_runtime_tool_request_runner_blocks_tools_disallowed_by_user_goal() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "no commands please"}]
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: calls.append("call_agent_tool") or {"ok": True},
        run_events=run_events,
    )

    runner.run(
        [{"tool": "terminal.run", "input": {"command": "echo hi"}}],
        ["terminal.run"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert calls == []
    assert budget.claims == [("terminal.run", False)]
    assert timeline == [
        {
            "event": "agent.tool.skipped",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
            "result": {
                "ok": False,
                "blocked_by_user_goal": True,
                "tool": "terminal.run",
                "error": "no terminal",
                "hint": (
                    "Do not ask for approval. Continue with an inline answer "
                    "that follows the user's stated constraint."
                ),
            },
        }
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert "blocked_by_user_goal" in messages[-1]["content"]


def test_runtime_tool_request_runner_previews_live_foreground_tools_by_policy() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在当前应用里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: calls.append("call_agent_tool") or {"ok": True},
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "preview"},
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert calls == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["status"] == "preview_required"
    assert result["execution_mode"] == "supervised_live"
    assert result["keyboard_mouse_capture"] is True
    assert result["desktop_execution_policy"] == {"mode": "preview"}
    assert result["sandbox_provider"]["status"] == "provider_required"
    assert result["sandbox_provider"]["blocking_conditions"] == [
        "sandbox_desktop_provider_required"
    ]
    assert result["desktop_execution_route"]["status"] == "provider_required"
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["desktop_execution_route"]["fallback_mode"] == "supervised_live"
    assert result["blocking_conditions"] == ["desktop_execution_preview_required"]
    assert [action["tool"] for action in result["recovery_actions"]] == [
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
        "desktop.safe_type_text",
    ]
    assert [action["recovery_action_kind"] for action in result["recovery_actions"]] == [
        "observe_desktop_state",
        "observe_desktop_controls",
        "sandbox_desktop_handoff",
        "supervised_live_retry",
    ]
    sandbox_action = result["recovery_actions"][2]
    assert sandbox_action["desktop_execution_policy"]["mode"] == "sandbox_preferred"
    assert sandbox_action["desktop_execution_route"]["status"] == "provider_required"
    assert sandbox_action["sandbox_provider"]["status"] == "provider_required"
    assert sandbox_action["metadata"]["sandbox_desktop_handoff"] is True
    assert sandbox_action["metadata"]["desktop_execution_route"]["status"] == (
        "provider_required"
    )
    assert sandbox_action["metadata"]["sandbox_provider"]["status"] == "provider_required"
    assert sandbox_action["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert sandbox_action["metadata"]["runtime_replan_auto_start_blockers"] == [
        "sandbox_desktop_provider_required"
    ]
    assert sandbox_action["deferred_continuation"][0]["tool"] == "desktop.safe_type_text"
    assert sandbox_action["deferred_continuation"][0]["input"] == {"text": "hello"}
    assert (
        sandbox_action["deferred_continuation"][0]["desktop_execution_policy"]["mode"]
        == "sandbox_preferred"
    )
    supervised_action = result["recovery_actions"][3]
    assert supervised_action["desktop_execution_policy"]["mode"] == "supervised_live"
    assert supervised_action["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert supervised_action["metadata"]["runtime_replan_auto_start_blockers"] == [
        "desktop_execution_policy",
        "keyboard_mouse_capture",
        "foreground_control",
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert run_events[0][2]["result"]["blocked_by_desktop_execution_policy"] is True
    assert "blocked_by_desktop_execution_policy" in messages[-1]["content"]


def test_runtime_tool_request_runner_allows_sandbox_ready_provider_route() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "sandbox_preferred"},
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": "sandbox_desktop",
                    "provider_id": "sandbox-1",
                    "status": "available",
                    "supported_tools": ["desktop.safe_type_text"],
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert budget.claims == []
    assert len(captured_requests) == 1
    routed_request = captured_requests[0]
    assert routed_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert routed_request["desktop_execution_route"]["selected_provider_kind"] == (
        "sandbox_desktop"
    )
    assert routed_request["sandbox_provider"]["provider_id"] == "sandbox-1"
    assert not [event for event in timeline if event["event"] == "agent.tool.skipped"]


def test_runtime_tool_request_runner_preview_input_policy_allows_media_but_blocks_typing() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "播放音乐，然后在当前应用里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = {"ok": True, "action": tool_name, "summary": "done"}
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    policy = {"mode": "preview_input", "allow_media_control": True}

    runner.run(
        [
            {
                "tool": "media.music_app_open_and_play",
                "input": {"app_name": "Music"},
                "desktop_execution_policy": policy,
            },
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": policy,
            },
        ],
        ["media.music_app_open_and_play", "desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    assert calls == [("media.music_app_open_and_play", {"app_name": "Music"})]
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert skipped["detail"] == "desktop.safe_type_text"
    assert skipped["result"]["blocked_by_desktop_execution_policy"] is True
    assert skipped["result"]["desktop_execution_policy"] == policy
    supervised_action = skipped["result"]["recovery_actions"][3]
    assert supervised_action["tool"] == "desktop.safe_type_text"
    assert supervised_action["input"] == {"text": "hello"}
    assert supervised_action["desktop_execution_policy"]["mode"] == "supervised_live"
    assert "blocked_by_desktop_execution_policy" in messages[-1]["content"]


def test_runtime_tool_request_runner_uses_discovered_app_name_for_followup_tool() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Apple Music"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Apple Music", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Apple Music"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        ("app.open", {"app_name": "Music"}),
    ]


def test_runtime_tool_request_runner_skips_foreground_mutation_after_inspect_not_ready() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = {
            "ok": False,
            "action": "desktop.inspect_app",
            "summary": "No installed app matched PixelForge",
            "error": "app_not_found",
            "recommended_tools": ["desktop.list_apps", "app.open"],
            "recovery_actions": [
                {
                    "label": "重新发现应用",
                    "tool": "desktop.list_apps",
                    "input": {"query": "PixelForge", "limit": 20},
                    "permission_target": "app_discovery",
                    "risk_level": "low",
                }
            ],
            "data": {
                "app_name": "PixelForge",
                "requested_app_name": "PixelForge",
                "app_found": False,
                "running": False,
                "focus_verified": False,
                "ui_element_count": 0,
                "control_like_count": 0,
                "ready_for_foreground_action": False,
                "checks": {
                    "discovered_app": False,
                    "status_running": False,
                    "focus_verified": False,
                    "named_ui_elements_nonempty": False,
                    "control_like_ui_visible": False,
                    "ready_for_foreground_action": False,
                },
            },
        }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]
    budget = FakeBudget()

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=budget,
    )

    assert calls == [("desktop.inspect_app", {"app_name": "PixelForge"})]
    assert budget.claims == [("app.open_and_click_ui_element", False)]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.replan.requested",
        "agent.tool.skipped",
        "agent.replan.requested",
    ]
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")["result"]
    assert skipped["blocked_by_runtime_readiness"] is True
    assert skipped["tool"] == "app.open_and_click_ui_element"
    assert skipped["blocking_conditions"] == [
        "app_not_found",
        "app_not_running",
        "foreground_focus_unverified",
        "ui_elements_empty",
        "no_actionable_controls",
        "foreground_not_ready",
    ]
    assert skipped["recommended_tools"] == ["desktop.list_apps", "app.open"]
    assert skipped["recovery_actions"][0]["tool"] == "desktop.list_apps"
    skipped_run_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "agent.tool.skipped"
    )
    assert skipped_run_event["result"]["blocked_by_runtime_readiness"] is True
    replan_events = [
        event for event in timeline if event["event"] == "agent.replan.requested"
    ]
    assert [event["payload"]["source_tool_name"] for event in replan_events] == [
        "desktop.inspect_app",
        "app.open_and_click_ui_element",
    ]
    assert all(event["payload"]["trigger"] == "tool_unavailable" for event in replan_events)
    assert replan_events[0]["payload"]["fallback_tools"] == ["desktop.list_apps", "app.open"]
    assert replan_events[0]["payload"]["metadata"]["recovery_actions"][0]["tool"] == "desktop.list_apps"
    assert replan_events[1]["payload"]["fallback_tools"] == ["desktop.list_apps", "app.open"]
    assert replan_events[1]["payload"]["metadata"]["recovery_actions"][0]["tool"] == "desktop.list_apps"
    run_replan_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_events[0]["payload"]["request_id"]
    assert "blocked_by_runtime_readiness" in messages[-1]["content"]


def test_runtime_tool_request_runner_continues_planned_recovery_after_inspect_not_ready() -> None:
    calls: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "recommended_tools": ["desktop.list_apps"],
                "recovery_actions": [
                    {
                        "label": "重新发现应用",
                        "tool": "desktop.list_apps",
                        "input": {"query": "PixelForge", "limit": 20},
                        "permission_target": "app_discovery",
                        "risk_level": "low",
                    }
                ],
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload.get("query"),
                    "apps": [{"name": "PixelForge", "path": "/Applications/PixelForge.app"}],
                },
            }
        elif tool_name == "app.open_and_click_ui_element":
            result = {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload.get("app_name"),
                    "target": payload.get("target"),
                },
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        "desktop.inspect_app",
        "desktop.list_apps",
        "app.open_and_click_ui_element",
    ]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.replan.requested",
        "agent.tool.call",
        "agent.desktop.readiness_recovered",
        "agent.tool.call",
    ]
    assert timeline[1]["payload"]["source_tool_name"] == "desktop.inspect_app"
    assert timeline[1]["payload"]["fallback_tools"] == ["desktop.list_apps"]
    assert timeline[3]["recovery_tool"] == "desktop.list_apps"
    assert "blocked_by_runtime_readiness" not in messages[-1]["content"]


def test_runtime_tool_request_runner_keeps_readiness_blocker_after_failed_recovery() -> None:
    calls: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "app.open":
            result = {
                "ok": False,
                "action": "app.open",
                "summary": "Application not found",
                "error": "app_not_found",
                "data": {"app_name": payload.get("app_name")},
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]
    budget = FakeBudget()

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "app.open", "input": {"app_name": "PixelForge"}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "app.open", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=budget,
    )

    assert calls == ["desktop.inspect_app", "app.open"]
    skipped = next(
        event
        for event in timeline
        if event["event"] == "agent.tool.skipped"
        and event["detail"] == "app.open_and_click_ui_element"
    )
    assert skipped["result"]["blocked_by_runtime_readiness"] is True
    assert any(event["event"] == "agent.replan.requested" for event in timeline)
    assert budget.claims == [("app.open_and_click_ui_element", False)]


def test_runtime_tool_request_runner_replans_failed_recovery_with_parent_context() -> None:
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        result = {
            "ok": False,
            "error": "script failed",
            "returncode": 1,
        }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    request = {
        "tool": "terminal.run",
        "input": {"command": "python analyze_sales.py"},
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

    with pytest.raises(AgentRuntimeError):
        runner.run(
            [request],
            ["terminal.run"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Analyze sales.csv"}],
            timeline,
            [],
            next_iteration=1,
            run_id="workflow-run-1",
            budget=FakeBudget(),
        )

    replan_event = next(
        event
        for event in timeline
        if event["event"] == "workflow.run.replan.requested"
    )
    payload = replan_event["payload"]
    assert payload["source"] == "runtime_tool_request_runner"
    assert payload["trigger"] == "tool_failure"
    assert payload["source_tool_name"] == "terminal.run"
    assert payload["target_capability_id"] == "data.analysis"
    metadata = payload["metadata"]
    assert metadata["replan_recovery_failed"] is True
    assert metadata["parent_replan_request_id"] == "replan-parent-1"
    assert metadata["parent_replan_trigger"] == "tool_failure"
    assert metadata["failed_recovery_action_id"] == (
        "replan-parent-1:action:1:terminal.run"
    )
    assert metadata["failed_recovery_action_label"] == "Run fallback analysis script"
    assert metadata["failed_recovery_tool"] == "terminal.run"
    assert metadata["failed_recovery_input"] == {"command": "python analyze_sales.py"}
    assert metadata["failed_recovery_source"] == "agent_studio_replan_recovery"
    assert metadata["original_source_tool_name"] == "data.analyze"
    assert metadata["replan_signal_ids"] == ["signal-analyze"]
    assert metadata["failed_recovery_verification_targets"][0]["step_id"] == (
        "analyze-data-file"
    )
    assert metadata["failed_recovery_result_preview"]["error"] == "script failed"
    run_replan_event = next(
        event for event in run_events if event[1] == "workflow.run.replan.requested"
    )
    assert run_replan_event[2]["metadata"]["parent_replan_request_id"] == "replan-parent-1"


def test_runtime_tool_request_runner_clears_app_not_found_blocker_after_discovery() -> None:
    calls: list[str] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload.get("query"),
                    "apps": [{"name": "PixelForge", "path": "/Applications/PixelForge.app"}],
                },
            }
        elif tool_name == "app.open_and_click_ui_element":
            result = {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload.get("app_name"),
                    "target": payload.get("target"),
                },
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        "desktop.inspect_app",
        "desktop.list_apps",
        "app.open_and_click_ui_element",
    ]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.tool.call",
        "agent.desktop.readiness_recovered",
        "agent.tool.call",
    ]
    recovered = timeline[2]
    assert recovered["detail"] == "desktop.list_apps"
    assert recovered["tool"] == "desktop.list_apps"
    assert recovered["recovery_tool"] == "desktop.list_apps"
    assert recovered["status"] == "recovered"
    assert recovered["app_name"] == "PixelForge"
    assert recovered["blocking_conditions"] == [
        "app_not_found",
        "app_not_running",
        "foreground_not_ready",
    ]
    assert run_events[-1][1] == "agent.desktop.readiness_recovered"
    assert run_events[-1][2]["recovery_tool"] == "desktop.list_apps"
    assert "blocked_by_runtime_readiness" not in messages[-1]["content"]


def test_runtime_tool_request_runner_records_discovered_app_name_resolution() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 Apple Music"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Apple Music", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Apple Music"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        ("app.open", {"app_name": "Music"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "Apple Music",
        "resolved_app_name": "Music",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Music.app",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert ("run-1", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_named_app_marked_from_discovery() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixel Forge Pro",
                        "path": "/Applications/Pixel Forge Pro.app",
                        "match_score": 91,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open",
                "input": {
                    "app_name": "PixelForge",
                    "selection_source": "desktop.list_apps",
                    "query": "PixelForge",
                },
            },
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-named-discovered-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "PixelForge", "limit": 20}),
        ("app.open", {"app_name": "Pixel Forge Pro"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "PixelForge",
        "resolved_app_name": "Pixel Forge Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixel Forge Pro.app",
        "app_resolution_score": "91",
        "app_resolution_confidence": "high",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert ("run-named-discovered-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_discovered_app_placeholder() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixelmator Pro",
                        "path": "/Applications/Pixelmator Pro.app",
                        "match_score": 94,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": payload["app_name"],
                    "target": payload["target"],
                },
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开一个能编辑图片的应用，然后点击导出"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "image", "limit": 20}},
            {
                "tool": "app.focus_and_click_ui_element",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "image",
                    "target": "导出",
                    "limit": 80,
                },
            },
        ],
        ["desktop.list_apps", "app.focus_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "image", "limit": 20}),
        (
            "app.focus_and_click_ui_element",
            {
                "app_name": "Pixelmator Pro",
                "target": "导出",
                "limit": 80,
            },
        ),
    ]
    resolution_payload = {
        "tool": "app.focus_and_click_ui_element",
        "field": "app_name",
        "requested_app_name": "image",
        "resolved_app_name": "Pixelmator Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixelmator Pro.app",
        "app_resolution_score": "94",
        "app_resolution_confidence": "high",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.focus_and_click_ui_element",
            **resolution_payload,
        }
    ]
    assert ("run-selected-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_app_without_query_for_media_playback() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Music",
                        "path": "/Applications/Music.app",
                        "match_score": 96,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "找个音乐应用播放超时空辉夜姬"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "music", "limit": 20}},
            {
                "tool": "media.music_app_open_and_play",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                },
            },
        ],
        ["desktop.list_apps", "media.music_app_open_and_play"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-media-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "music", "limit": 20}),
        ("media.music_app_open_and_play", {"app_name": "Music"}),
    ]
    resolution_payload = {
        "tool": "media.music_app_open_and_play",
        "field": "app_name",
        "requested_app_name": "<selected app from desktop.list_apps>",
        "resolved_app_name": "Music",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Music.app",
        "app_resolution_score": "96",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "latest_desktop.list_apps_selection",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "media.music_app_open_and_play",
            **resolution_payload,
        }
    ]
    assert ("run-selected-media-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_running_app_placeholder(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop._installed_app_match_candidates",
        lambda query: [
            {
                "name": "Numbers",
                "path": "/System/Applications/Numbers.app",
                "match_score": 92,
                "match_confidence": "high",
                "match_reason": f"capability_{query}",
            }
        ],
    )

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.running_apps":
            result = {
                "ok": True,
                "action": "desktop.running_apps",
                "data": {
                    "apps": [
                        {"name": "Finder", "frontmost": False},
                        {"name": "Numbers", "frontmost": True},
                    ],
                    "frontmost": "Numbers",
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "在当前打开的表格应用里粘贴结果"}]

    runner.run(
        [
            {"tool": "desktop.running_apps", "input": {}},
            {
                "tool": "app.focus_and_safe_shortcut",
                "input": {
                    "app_name": "<selected app from desktop.running_apps>",
                    "selection_source": "desktop.running_apps",
                    "query": "spreadsheet",
                    "action": "paste",
                },
            },
        ],
        ["desktop.running_apps", "app.focus_and_safe_shortcut"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-running-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.running_apps", {}),
        ("app.focus_and_safe_shortcut", {"app_name": "Numbers", "action": "paste"}),
    ]
    resolution_payload = {
        "tool": "app.focus_and_safe_shortcut",
        "field": "app_name",
        "requested_app_name": "spreadsheet",
        "resolved_app_name": "Numbers",
        "source_tool": "desktop.running_apps",
        "resolved_app_path": "/System/Applications/Numbers.app",
        "app_resolution_score": "92",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "capability_spreadsheet",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.focus_and_safe_shortcut",
            **resolution_payload,
        }
    ]
    assert ("run-selected-running-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_top_level_app_candidates() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "apps": [
                    {
                        "name": "Typora",
                        "path": "/Applications/Typora.app",
                        "score": 88,
                        "confidence": "high",
                        "reason": "document:markdown",
                    }
                ],
            }
        else:
            result = {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "markdown", "limit": 20}},
            {
                "tool": "app.open",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "markdown",
                },
            },
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "打开一个能写 markdown 的应用"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-top-level-app-candidates",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "markdown", "limit": 20}),
        ("app.open", {"app_name": "Typora"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "markdown",
        "resolved_app_name": "Typora",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Typora.app",
        "app_resolution_score": "88",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "document:markdown",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert (
        "run-top-level-app-candidates",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_resolves_selected_app_for_desktop_windows() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Arc Browser",
                        "path": "/Applications/Arc Browser.app",
                        "match_score": 100,
                        "match_confidence": "high",
                        "match_reason": "exact_name",
                        "matched_name": "Arc Browser",
                        "matched_name_source": "bundle_metadata",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": "desktop.windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {
                "tool": "desktop.windows",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "Arc Browser",
                },
            },
        ],
        ["desktop.list_apps", "desktop.windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "查看 Arc Browser 的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("desktop.windows", {"app_name": "Arc Browser"}),
    ]
    resolution_payload = {
        "tool": "desktop.windows",
        "field": "app_name",
        "requested_app_name": "Arc Browser",
        "resolved_app_name": "Arc Browser",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Arc Browser.app",
        "app_resolution_score": "100",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "exact_name",
        "app_resolution_matched_name": "Arc Browser",
        "app_resolution_matched_name_source": "bundle_metadata",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.windows",
            **resolution_payload,
        }
    ]
    assert (
        "run-selected-app-windows",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_scopes_windows_to_recent_foreground_app() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
            if tool_name == "app.open"
            else {
                "ok": True,
                "action": "desktop.windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {"tool": "app.open", "input": {"app_name": "Notes"}},
            {"tool": "desktop.windows", "input": {}},
        ],
        ["app.open", "desktop.windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "打开 Notes 后看它的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-foreground-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("app.open", {"app_name": "Notes"}),
        ("desktop.windows", {"app_name": "Notes"}),
    ]


def test_runtime_tool_request_runner_resolves_selected_app_for_desktop_verify() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixelmator Pro",
                        "path": "/Applications/Pixelmator Pro.app",
                        "match_score": 94,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": "desktop.verify",
                "data": {"app_name": payload["app_name"], "ready_for_foreground_action": True},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "image editor", "limit": 20}},
            {
                "tool": "desktop.verify",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "image editor",
                    "role_filter": "button",
                    "limit": 80,
                },
            },
        ],
        ["desktop.list_apps", "desktop.verify"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "找一个图片编辑应用并验证它的界面"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app-verify",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "image editor", "limit": 20}),
        (
            "desktop.verify",
            {"app_name": "Pixelmator Pro", "role_filter": "button", "limit": 80},
        ),
    ]
    resolution_payload = {
        "tool": "desktop.verify",
        "field": "app_name",
        "requested_app_name": "image editor",
        "resolved_app_name": "Pixelmator Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixelmator Pro.app",
        "app_resolution_score": "94",
        "app_resolution_confidence": "high",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.verify",
            **resolution_payload,
        }
    ]
    assert (
        "run-selected-app-verify",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_scopes_list_windows_to_recent_foreground_app() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": payload["app_name"], "focus_status": "frontmost"},
            }
            if tool_name == "app.focus"
            else {
                "ok": True,
                "action": "desktop.list_windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {"tool": "app.focus", "input": {"app_name": "Notes"}},
            {"tool": "desktop.list_windows", "input": {}},
        ],
        ["app.focus", "desktop.list_windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "聚焦 Notes 后看它的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-foreground-list-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("app.focus", {"app_name": "Notes"}),
        ("desktop.list_windows", {"app_name": "Notes"}),
    ]


def test_runtime_tool_request_runner_normalizes_discovered_app_open_path_input() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Preview",
                        "path": "/System/Applications/Preview.app",
                        "match_score": 100,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": "desktop.open_path_with_app",
                "data": {
                    "app_name": payload["app_name"],
                    "path": payload["path"],
                },
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开一个能编辑 PDF 的应用并打开 Downloads/report.pdf"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "pdf", "limit": 20}},
            {
                "tool": "desktop.open_path_with_app",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "pdf",
                    "target_path": "Downloads/report.pdf",
                    "action": "open_path_with_selected_app",
                },
            },
        ],
        ["desktop.list_apps", "desktop.open_path_with_app"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-open-path",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "pdf", "limit": 20}),
        (
            "desktop.open_path_with_app",
            {"app_name": "Preview", "path": "Downloads/report.pdf"},
        ),
    ]
    resolution_payload = {
        "tool": "desktop.open_path_with_app",
        "field": "app_name",
        "requested_app_name": "pdf",
        "resolved_app_name": "Preview",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/System/Applications/Preview.app",
        "app_resolution_score": "100",
        "app_resolution_confidence": "high",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.open_path_with_app",
            **resolution_payload,
        }
    ]
    assert ("run-selected-open-path", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_workspace_file_from_previous_list() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        result = (
            {
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "old.csv", "type": "file", "mtime": 10},
                    {"name": "latest.csv", "type": "file", "mtime": 20},
                ],
            }
            if tool_name == "workspace.list"
            else {"ok": True, "path": payload["path"], "artifact": {"path": "analysis-report.md"}}
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "include_metadata": True,
                },
            },
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "最近",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "source_kind": "csv",
                    "artifact_path": "analysis-report.md",
                },
                "source": "runtime_planner",
                "step_id": "analyze-discovered-data",
                "capability_id": "data.analysis",
            },
        ],
        ["workspace.list", "data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "分析 Downloads 里最新的 CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-workspace-file",
        budget=FakeBudget(),
    )

    assert calls == [
        (
            "workspace.list",
            {
                "path": "Downloads",
                "pattern": "*.csv",
                "file_type": "csv",
                "include_metadata": True,
            },
        ),
        (
            "data.analyze",
            {
                "path": "Downloads/latest.csv",
                "source_kind": "csv",
                "artifact_path": "analysis-report.md",
            },
        ),
    ]
    assert seen_requests[-1]["input_resolution"]["resolved_path"] == "Downloads/latest.csv"
    resolution_payload = {
        "tool": "data.analyze",
        "field": "path",
        "requested_path": "<selected file from workspace.list>",
        "resolved_path": "Downloads/latest.csv",
        "source_tool": "workspace.list",
        "source_path": "Downloads",
        "resolved_file_name": "latest.csv",
        "selection": "最近",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "data.analyze",
            **resolution_payload,
        }
    ]
    assert ("run-selected-workspace-file", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_workspace_files_from_previous_list() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        result = (
            {
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "east.csv", "type": "file", "mtime": 10},
                    {"name": "west.csv", "type": "file", "mtime": 20},
                ],
            }
            if tool_name == "workspace.list"
            else {"ok": True, "paths": payload["paths"], "artifact": {"path": "analysis-report.md"}}
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "selection": "all",
                },
            },
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected files from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "all",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "source_kind": "csv",
                    "artifact_path": "analysis-report.md",
                },
                "source": "runtime_planner",
                "step_id": "analyze-discovered-data",
                "capability_id": "data.analysis",
            },
        ],
        ["workspace.list", "data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "合并 Downloads 里的所有 CSV 并输出报告"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-workspace-files",
        budget=FakeBudget(),
    )

    assert calls == [
        (
            "workspace.list",
            {
                "path": "Downloads",
                "pattern": "*.csv",
                "file_type": "csv",
                "selection": "all",
            },
        ),
        (
            "data.analyze",
            {
                "paths": ["Downloads/east.csv", "Downloads/west.csv"],
                "source_kind": "csv",
                "artifact_path": "analysis-report.md",
            },
        ),
    ]
    assert seen_requests[-1]["input_resolution"]["resolved_paths"] == [
        "Downloads/east.csv",
        "Downloads/west.csv",
    ]
    resolution_payload = {
        "tool": "data.analyze",
        "field": "path",
        "requested_path": "<selected files from workspace.list>",
        "resolved_path": "Downloads/east.csv",
        "resolved_paths": ["Downloads/east.csv", "Downloads/west.csv"],
        "resolved_file_count": 2,
        "source_tool": "workspace.list",
        "source_path": "Downloads",
        "resolved_file_names": ["east.csv", "west.csv"],
        "resolved_file_name": "east.csv",
        "selection": "all",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "data.analyze",
            **resolution_payload,
        }
    ]
    assert ("run-selected-workspace-files", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_skips_unresolved_selected_workspace_file() -> None:
    calls: list[dict[str, Any]] = []
    timeline = [
        _timeline(
            "agent.tool.call",
            "workspace.list",
            input_preview={"path": "Downloads", "pattern": "*.csv", "file_type": "csv"},
            result={
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "sales.csv", "type": "file"},
                    {"name": "inventory.csv", "type": "file"},
                ],
            },
        )
    ]

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(tool_request)
        return {"ok": True}

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                },
            },
        ],
        ["data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "分析 Downloads 里的 CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-unresolved-file",
        budget=FakeBudget(),
    )

    assert calls == []
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    assert skipped["detail"] == "data.analyze"
    assert skipped["result"]["blocked_by_file_resolution"] is True
    assert skipped["result"]["recommended_tools"] == ["workspace.list"]
    assert skipped["result"]["recovery_actions"][0]["input"] == {
        "path": "Downloads",
        "pattern": "*.csv",
        "file_type": "csv",
    }


def test_runtime_tool_request_runner_resolves_selected_app_and_workspace_file() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        if tool_name == "workspace.list":
            result = {
                "ok": True,
                "path": "Downloads",
                "entries": [{"name": "report.pdf", "type": "file", "mtime": 100}],
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "Preview",
                            "path": "/System/Applications/Preview.app",
                            "match_score": 100,
                        }
                    ],
                },
            }
        else:
            result = {"ok": True, "action": tool_name, "data": payload}
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.pdf",
                    "file_type": "pdf",
                    "include_metadata": True,
                },
            },
            {"tool": "desktop.list_apps", "input": {"query": "pdf", "limit": 20}},
            {
                "tool": "desktop.open_path_with_app",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "query": "pdf",
                    "target_path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "最近",
                    "source_scope": "Downloads",
                    "pattern": "*.pdf",
                    "file_type": "pdf",
                },
            },
        ],
        ["workspace.list", "desktop.list_apps", "desktop.open_path_with_app"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "用能打开 PDF 的应用打开最新 PDF"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-app-file-resolution",
        budget=FakeBudget(),
    )

    assert calls[-1] == (
        "desktop.open_path_with_app",
        {"app_name": "Preview", "path": "Downloads/report.pdf"},
    )
    open_resolution = seen_requests[-1]["input_resolution"]
    assert open_resolution["source_tool"] == "desktop.list_apps"
    assert open_resolution["file_resolution_source_tool"] == "workspace.list"
    assert open_resolution["resolved_path"] == "Downloads/report.pdf"
    assert [
        event["field"]
        for event in timeline
        if event["event"] == "agent.tool.input_resolved"
    ] == ["app_name", "target_path"]
    assert any(
        event_type == "agent.tool.input_resolved"
        and payload.get("resolved_path") == "Downloads/report.pdf"
        for _run_id, event_type, payload in run_events
    )


def test_runtime_tool_request_runner_records_best_match_resolution_evidence() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "Archive Utility",
                            "path": "/System/Applications/Utilities/Archive Utility.app",
                            "match_score": 80,
                            "match_confidence": "medium",
                        }
                    ],
                    "best_match": {
                        "name": "Arc Browser",
                        "path": "/Applications/Arc Browser.app",
                        "match_score": 100,
                        "match_confidence": "high",
                        "match_reason": "exact_name",
                        "matched_name": "Arc Browser",
                        "matched_name_source": "bundle_metadata",
                    },
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc Browser"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]
    resolution = next(event for event in timeline if event["event"] == "agent.tool.input_resolved")
    assert resolution["resolved_app_name"] == "Arc Browser"
    assert resolution["app_resolution_score"] == "100"
    assert resolution["app_resolution_confidence"] == "high"
    assert resolution["app_resolution_reason"] == "exact_name"
    assert resolution["app_resolution_matched_name"] == "Arc Browser"
    assert resolution["app_resolution_matched_name_source"] == "bundle_metadata"
    assert resolution["resolved_app_path"] == "/Applications/Arc Browser.app"


def test_runtime_tool_request_runner_uses_related_discovered_app_match_name() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "matches": [{"name": "Arc Browser", "path": "/Applications/Arc Browser.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]


def test_runtime_tool_request_runner_prefers_related_app_match_over_first_candidate() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {"name": "Archive Utility", "path": "/System/Applications/Utilities/Archive Utility.app"},
                        {"name": "Arc Browser", "path": "/Applications/Arc Browser.app"},
                    ],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]


def test_runtime_tool_request_runner_does_not_rewrite_low_confidence_app_match() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "企业微信",
                            "path": "/Applications/企业微信.app",
                            "match_score": 80,
                        },
                    ],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": payload["app_name"]},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "在微信搜索文件传输助手"}]
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "微信", "limit": 20}},
            {"tool": "app.focus", "input": {"app_name": "微信"}},
        ],
        ["desktop.list_apps", "app.focus"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "微信", "limit": 20}),
        ("app.focus", {"app_name": "微信"}),
    ]
    assert not any(event["event"] == "agent.tool.input_resolved" for event in timeline)


def test_runtime_tool_request_runner_uses_discovered_app_name_for_combined_app_tool() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload["app_name"],
                    "target": payload["target"],
                    "launch_verified": True,
                },
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Apple Music 并点击资料库"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Apple Music", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {
                    "app_name": "Apple Music",
                    "target": "资料库",
                    "role_filter": "button",
                    "limit": 80,
                    "click_count": 1,
                },
            },
        ],
        ["desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        (
            "app.open_and_click_ui_element",
            {
                "app_name": "Music",
                "target": "资料库",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        ),
    ]


def test_runtime_tool_request_runner_raises_pending_approval_with_remaining_requests() -> None:
    pending_builder = FakePendingApprovalBuilder()
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "terminal.run",
            "risk_level": "high",
            "policy_reason": "Terminal commands need review.",
            "plugin_id": "ops",
        },
    )
    messages = [{"role": "user", "content": "run command"}]
    requests = [
        {"tool": "terminal.run", "input": {"command": "echo hi"}},
        {"tool": "workspace.read", "input": {"path": "README.md"}},
    ]

    with pytest.raises(AgentApprovalRequired) as exc:
        runner.run(
            requests,
            ["terminal.run", "workspace.read"],
            FakeBroker({"ok": True}),
            messages,
            [],
            [],
            next_iteration=7,
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert exc.value.pending_approval["approval_id"] == "approval-1"
    assert exc.value.pending_approval["next_iteration"] == 7
    assert exc.value.pending_approval["remaining_tool_requests"] == [requests[1]]
    assert exc.value.pending_approval["risk_level"] == "high"
    assert exc.value.pending_approval["policy_reason"] == "Terminal commands need review."
    assert exc.value.pending_approval["plugin_id"] == "ops"


def test_runtime_tool_request_runner_adds_active_window_target_after_app_control() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "app.open":
            return {
                "ok": True,
                "data": {"app_name": str(tool_request["input"].get("app_name") or "")},
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Safari"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "open safari"}]

    runner.run(
        [
            {"tool": "app.open", "input": {"app_name": "Safari"}},
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Safari",
        "source_tool": "app.open",
    }


def test_runtime_tool_request_runner_adds_active_window_target_after_open_path_with_app() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "desktop.open_path_with_app":
            return {
                "ok": True,
                "data": {
                    "app_name": str(tool_request["input"].get("app_name") or ""),
                    "path": str(tool_request["input"].get("path") or ""),
                },
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Preview"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "desktop.open_path_with_app",
                "input": {"app_name": "Preview", "path": "Downloads/report.pdf"},
            },
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["desktop.open_path_with_app", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open pdf"}],
        [],
        [],
        next_iteration=1,
        run_id="run-open-path-target",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Preview",
        "source_tool": "desktop.open_path_with_app",
    }


def test_runtime_tool_request_runner_tracks_app_open_path_with_app_alias() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "app.open_path_with_app":
            return {
                "ok": True,
                "data": {
                    "app_name": str(tool_request["input"].get("app_name") or ""),
                    "path": str(tool_request["input"].get("path") or ""),
                },
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Preview"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "app.open_path_with_app",
                "input": {"app_name": "Preview", "path": "Downloads/report.pdf"},
            },
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["app.open_path_with_app", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open pdf"}],
        [],
        [],
        next_iteration=1,
        run_id="run-open-path-alias-target",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Preview",
        "source_tool": "app.open_path_with_app",
    }


def test_runtime_tool_request_runner_projects_fatal_failures_and_success_messages() -> None:
    first_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "returncode": 1,
            "error": "failed",
        },
    )
    fatal_timeline: list[dict[str, Any]] = []
    with pytest.raises(AgentRuntimeError, match="terminal.run 执行失败"):
        first_runner.run(
            [{"tool": "terminal.run", "input": {"command": "npm test"}}],
            ["terminal.run"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "run command"}],
            fatal_timeline,
            [],
            next_iteration=1,
            run_id="run-1",
            budget=FakeBudget(),
        )
    assert fatal_timeline == [
        {
            "event": "agent.tool.failed",
            "detail": "terminal.run",
            "input_preview": {"command": "npm test"},
            "result": {"ok": False, "returncode": 1, "error": "failed"},
            "status": "failed",
        }
    ]

    messages = [{"role": "user", "content": "read file"}]
    second_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True, "content": "hello"},
    )
    second_runner.run(
        [{"tool": "workspace.read", "input": {"path": "README.md"}}],
        ["workspace.read"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=2,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert messages[-1] == {
        "role": "user",
        "content": 'Tool result for workspace.read: {"ok": true, "content": "hello"}',
    }


def test_native_runtime_uses_split_tool_request_runner(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolRequestRunner is RuntimeToolRequestRunner
        assert isinstance(service.tool_request_runner, RuntimeToolRequestRunner)
    finally:
        service.close()
