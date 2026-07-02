"""Tests for tool-call execution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
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

    todo_event = next(event for event in timeline if event["event"] == "agent.task.todo.updated")
    checkpoint_event = next(
        event for event in timeline if event["event"] == "agent.task.checkpoint.updated"
    )
    for event in (todo_event, checkpoint_event):
        assert event["task_id"] == "task-1"
        assert event["group_run_id"] == "group-run-1"
        assert event["workflow_run_id"] == "workflow-run-1"
        assert event["status"] == "completed"

    run_todo_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.todo.updated"
    )
    assert run_todo_event["task_id"] == "task-1"
    assert run_todo_event["group_run_id"] == "group-run-1"
    assert run_todo_event["workflow_run_id"] == "workflow-run-1"


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
    assert timeline[0]["core_id"] == "core-1"
    assert timeline[0]["target_app_name"] == "Figma"
    assert timeline[0]["replan_request_id"] == "replan-1"
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["step_id"] == "inspect-data-source"
    assert timeline[-1]["capability_id"] == "file.workspace_read"
    assert timeline[-1]["core_id"] == "core-1"
    assert timeline[-1]["target_app_name"] == "Figma"
    assert timeline[-1]["replan_request_id"] == "replan-1"
    agent_call = [call for call in events.calls if call[0] == "agent_tool_call"][0]
    assert agent_call[2]["trace"] == {
        "source": "runtime_planner",
        "planning_reason": "planner_replan_fallback_recovery",
        "step_id": "inspect-data-source",
        "capability_id": "file.workspace_read",
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
    assert [event["event"] for event in timeline] == ["agent.tool.call", "agent.tool.skipped"]
    skipped = timeline[-1]["result"]
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
    assert run_events[-1][1] == "agent.tool.skipped"
    assert run_events[-1][2]["result"]["blocked_by_runtime_readiness"] is True
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
        "agent.tool.call",
        "agent.desktop.readiness_recovered",
        "agent.tool.call",
    ]
    assert timeline[2]["recovery_tool"] == "desktop.list_apps"
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
    assert timeline[-1]["event"] == "agent.tool.skipped"
    assert timeline[-1]["detail"] == "app.open_and_click_ui_element"
    assert timeline[-1]["result"]["blocked_by_runtime_readiness"] is True
    assert budget.claims == [("app.open_and_click_ui_element", False)]


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
