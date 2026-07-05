"""Legacy Agent Studio runtime port tests."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort


def test_legacy_studio_agent_run_appends_runtime_planner_events() -> None:
    runtime = _FakeStudioRunRuntime()

    run = LegacyStudioPort(runtime).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
            "client_run_id": "client-agent-run-1",
        }
    )

    assert run["run_id"] == "agent-run-1"
    assert runtime.agent_run_payload is not None
    assert runtime.agent_run_payload["agent_id"] == "agent-1"
    assert runtime.agent_run_payload["user_goal"] == "请分析 data/sales.csv 并输出报告"
    assert runtime.agent_run_payload["source"] == "yachiyo_studio"
    assert runtime.agent_run_payload["client_run_id"] == "client-agent-run-1"
    assert runtime.agent_run_payload["run_group_id"] is None
    assert runtime.agent_run_payload["daily_desktop_policy_overlay"] is True
    assert runtime.agent_run_payload["runtime_planner_entrypoint"] is True
    assert runtime.agent_run_payload["daily_desktop_planning_context"] == (
        "请分析 data/sales.csv 并输出报告"
    )
    direct_requests = runtime.agent_run_payload["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == ["data.analyze"]
    assert direct_requests[0]["input"]["path"] == "data/sales.csv"
    assert direct_requests[0]["step_id"] == "analyze-data-file"
    events = runtime.events["agent-run-1"]
    assert [event["event_type"] for event in events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert events[0]["payload"]["intent"]["kind"] == "data_analysis"
    plan_steps = events[1]["payload"]["plan"]["tool_plan"]["steps"]
    assert [step["tool_name"] for step in plan_steps[:2]] == ["workspace.read", "data.analyze"]
    execution_requests = events[1]["payload"]["runtime_execution_envelope"]["requests"]
    assert execution_requests[1]["tool_name"] == "data.analyze"
    assert execution_requests[1]["step_id"] == "analyze-data-file"
    assert events[2]["payload"]["task_core"]["workspace"]["title"] == "Data Analysis Workspace"


def test_legacy_studio_agent_run_does_not_duplicate_runtime_planner_events() -> None:
    runtime = _FakeStudioRunRuntime()
    runtime.events["agent-run-1"] = [
        {
            "event_type": "agent.intent.selected",
            "payload": {
                "source": "runtime_planner",
                "intent": {"kind": "data_analysis"},
            },
            "run_id": "agent-run-1",
        }
    ]

    run = LegacyStudioPort(runtime).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
            "client_run_id": "client-agent-run-1",
        }
    )

    assert run["run_id"] == "agent-run-1"
    assert runtime.agent_run_payload["runtime_planner_entrypoint"] is True
    assert [event["event_type"] for event in runtime.events["agent-run-1"]] == [
        "agent.intent.selected"
    ]


def test_legacy_studio_agent_run_forwards_direct_tool_requests() -> None:
    runtime = _FakeStudioRunRuntime()

    run = LegacyStudioPort(runtime).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "执行恢复动作：Find Apple Music",
            "direct_tool_requests": [
                {
                    "tool": "desktop.list_apps",
                    "input": {"query": "Apple Music"},
                    "source": "agent_studio_replan_recovery",
                }
            ],
            "daily_desktop_planning_context": "执行恢复动作：Find Apple Music",
        }
    )

    assert run["run_id"] == "agent-run-1"
    assert runtime.agent_run_payload is not None
    assert runtime.agent_run_payload["direct_tool_requests"] == [
        {
            "tool": "desktop.list_apps",
            "input": {"query": "Apple Music"},
            "source": "agent_studio_replan_recovery",
        }
    ]
    assert runtime.agent_run_payload["daily_desktop_planning_context"] == (
        "执行恢复动作：Find Apple Music"
    )


def test_legacy_studio_workflow_run_appends_runtime_planner_events() -> None:
    runtime = _FakeStudioRunRuntime()

    run = LegacyStudioPort(runtime).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "打开 PixelForge",
            "client_run_id": "client-workflow-run-1",
        }
    )

    assert run["workflow_run_id"] == "workflow-run-1"
    assert runtime.workflow_run_payload is not None
    assert runtime.workflow_run_payload["workflow_id"] == "workflow-1"
    assert runtime.workflow_run_payload["user_goal"] == "打开 PixelForge"
    assert runtime.workflow_run_payload["source"] == "yachiyo_studio"
    assert runtime.workflow_run_payload["client_run_id"] == "client-workflow-run-1"
    assert runtime.workflow_run_payload["run_group_id"] is None
    assert runtime.workflow_run_payload["daily_desktop_planning_context"] == "打开 PixelForge"
    metadata = runtime.workflow_run_payload["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "desktop_operation"
    assert metadata["yachiyo_execution_envelope"]["requests"][0]["workflow_id"] == "workflow-1"
    envelope = runtime.workflow_run_payload["runtime_execution_envelope"]
    assert envelope["intent_kind"] == "desktop_operation"
    assert [request["tool_name"] for request in envelope["requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert [request["tool"] for request in runtime.workflow_run_payload["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    events = runtime.events["workflow-run-1"]
    assert [event["event_type"] for event in events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert events[0]["payload"]["intent"]["kind"] == "desktop_operation"
    assert events[0]["payload"]["intent"]["inputs"]["app_name_hint"] == "PixelForge"
    assert events[1]["payload"]["plan"]["tool_plan"]["steps"][0]["action"] == "list_apps"
    assert events[1]["payload"]["workflow_id"] == "workflow-1"
    assert events[1]["payload"]["workflow_run_id"] == "workflow-run-1"
    assert events[1]["payload"]["runtime_execution_envelope"]["task_core"]["core_id"]
    assert events[2]["payload"]["task_core"]["workspace"]["title"] == "Desktop Operation Workspace"


def test_legacy_studio_workflow_run_forwards_direct_tool_requests() -> None:
    runtime = _FakeStudioRunRuntime()
    envelope = {
        "decision_id": "decision-workflow",
        "plan_id": "plan-workflow",
        "requests": [
            {
                "request_id": "request-open",
                "tool": "desktop.list_apps",
                "input": {"query": "PixelForge"},
            }
        ],
    }

    run = LegacyStudioPort(runtime).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "打开 PixelForge",
            "runtime_execution_envelope": envelope,
            "direct_tool_requests": [
                {
                    "tool": "desktop.list_apps",
                    "input": {"query": "PixelForge"},
                    "source": "agent_studio_runtime_plan",
                }
            ],
        }
    )

    assert run["workflow_run_id"] == "workflow-run-1"
    assert runtime.workflow_run_payload is not None
    assert runtime.workflow_run_payload["runtime_execution_envelope"] == envelope
    assert runtime.workflow_run_payload["direct_tool_requests"] == [
        {
            "tool": "desktop.list_apps",
            "input": {"query": "PixelForge"},
            "source": "agent_studio_runtime_plan",
        }
    ]
    assert runtime.workflow_run_payload["daily_desktop_planning_context"] == "打开 PixelForge"


def test_legacy_studio_group_run_records_group_run_started_event() -> None:
    runtime = _FakeGroupRuntime()

    group_run = LegacyStudioPort(runtime).start_group_run(
        {
            "group_id": "group-1",
            "objective": "Compare options",
            "client_run_id": "client-group-run-1",
        }
    )

    assert group_run["group_run_id"] == "group-run-1"
    assert group_run["child_run_ids"] == ["run-1", "run-2"]
    assert [
        payload["runtime_planner_entrypoint"]
        for payload in runtime.runnable_run_payloads
    ] == [True, True]
    assert [event["event_type"] for event in group_run["events"]] == [
        "group.run.started",
        "group.run.plan",
        "group.run.intent.selected",
        "group.run.plan.created",
        "group.run.task_core.created",
        "group.run.plan.step",
        "group.run.task.todo.updated",
        "group.run.task.todo.updated",
        "group.run.task.checkpoint.updated",
        "group.run.task.checkpoint.updated",
        "group.member.started",
        "group.member.started",
    ]
    child_event_types = [event["event_type"] for event in runtime.events["run-1"]]
    first_planner_index = child_event_types.index("agent.intent.selected")
    assert child_event_types[first_planner_index - 1] == "group.member.started"
    assert runtime.events["run-1"][first_planner_index]["payload"]["source"] == "runtime_planner"
    assert runtime.events["run-1"][first_planner_index + 1]["event_type"] == "agent.plan.created"
    assert runtime.events["run-1"][first_planner_index + 2]["event_type"] == "agent.task_core.created"
    assert runtime.events["run-1"][first_planner_index + 3]["event_type"] == "agent.plan.step"
    started = group_run["events"][0]
    assert started["run_id"] == "run-1"
    assert started["payload"]["group_run_id"] == "group-run-1"
    assert started["payload"]["group_id"] == "group-1"
    assert started["payload"]["objective"] == "Compare options"
    assert started["payload"]["participant_count"] == 2
    assert started["payload"]["client_run_id"] == "client-group-run-1"
    plan = group_run["events"][1]
    assert plan["payload"]["group_execution_mode"] == "parallel"
    assert plan["payload"]["group_execution_strategy"] == "fan_out"
    assert plan["payload"]["group_parallel"] is True
    assert plan["payload"]["group_member_order"] == ["agent-1", "agent-2"]
    group_intent = group_run["events"][2]
    assert group_intent["payload"]["source"] == "runtime_planner"
    assert group_intent["payload"]["planner_scope"] == "group_run"
    assert group_intent["payload"]["planner_event_type"] == "agent.intent.selected"
    assert group_intent["payload"]["intent"]["kind"] == "general"
    assert group_intent["payload"]["group_run_id"] == "group-run-1"
    group_plan = group_run["events"][3]
    assert group_plan["payload"]["planner_event_type"] == "agent.plan.created"
    assert group_plan["payload"]["plan"]["tool_plan"]["title"] == "General Task Tool Plan"
    group_task_core = group_run["events"][4]
    assert group_task_core["payload"]["planner_event_type"] == "agent.task_core.created"
    assert group_task_core["payload"]["task_core"]["workspace"]["title"] == "General Task Workspace"
    group_step_tools = [
        event["payload"]["step"]["tool_name"]
        for event in group_run["events"]
        if event["event_type"] == "group.run.plan.step"
    ]
    assert group_step_tools == ["workspace.list"]


def test_legacy_studio_group_run_scopes_planner_execution_envelope_to_group_run() -> None:
    runtime = _FakeGroupRuntime()

    group_run = LegacyStudioPort(runtime).start_group_run(
        {
            "group_id": "group-1",
            "objective": "请分析 data/sales.csv 并输出报告",
        }
    )

    plan_event = next(
        event for event in group_run["events"] if event["event_type"] == "group.run.plan.created"
    )
    group_request = plan_event["payload"]["runtime_execution_envelope"]["requests"][0]
    assert plan_event["payload"]["group_id"] == "group-1"
    assert plan_event["payload"]["group_run_id"] == "group-run-1"
    assert plan_event["payload"]["run_group_id"] == "group-run-1"
    assert group_request["group_id"] == "group-1"
    assert group_request["group_run_id"] == "group-run-1"
    assert group_request["run_group_id"] == "group-run-1"


def test_legacy_studio_group_run_records_member_failed_and_cancelled_events() -> None:
    runtime = _FakeGroupRuntime(
        statuses={
            "agent-1": "failed",
            "agent-2": "cancelled",
        }
    )

    group_run = LegacyStudioPort(runtime).start_group_run(
        {
            "group_id": "group-1",
            "objective": "Compare options",
        }
    )

    event_types = [event["event_type"] for event in group_run["events"]]
    assert event_types[:6] == [
        "group.run.started",
        "group.run.plan",
        "group.run.intent.selected",
        "group.run.plan.created",
        "group.run.task_core.created",
        "group.run.plan.step",
    ]
    assert event_types[6:10] == [
        "group.run.task.todo.updated",
        "group.run.task.todo.updated",
        "group.run.task.checkpoint.updated",
        "group.run.task.checkpoint.updated",
    ]
    assert event_types[10:] == [
        "group.member.started",
        "group.member.failed",
        "group.member.started",
        "group.member.cancelled",
    ]
    assert [event["event_type"] for event in runtime.events["run-1"]].count(
        "agent.intent.selected"
    ) == 1
    assert [event["event_type"] for event in runtime.events["run-2"]].count(
        "agent.intent.selected"
    ) == 1
    failed_event = next(
        event for event in group_run["events"] if event["event_type"] == "group.member.failed"
    )
    cancelled_event = next(
        event for event in group_run["events"] if event["event_type"] == "group.member.cancelled"
    )
    assert failed_event["payload"]["status"] == "failed"
    assert cancelled_event["payload"]["status"] == "cancelled"


def test_legacy_studio_port_forwards_run_event_page_cursor_to_runtime() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    page = port.get_run_event_page("run-1", after_sequence=4, limit=2)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 4
    assert page["limit"] == 2
    assert runtime.last_event_page_request == {
        "run_id": "run-1",
        "after_sequence": 4,
        "limit": 2,
    }


def test_legacy_studio_port_accepts_reject_decision_payload() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    rejected = port.reject_run_approval(
        "run-1",
        {
            "approved": False,
            "reason": "No",
            "metadata": {"approval_id": "approval-1"},
        },
    )

    assert rejected["status"] == "failed"
    assert runtime.last_reject_request == {"run_id": "run-1", "reason": "No"}


def test_legacy_studio_port_accepts_approve_decision_payload() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    approved = port.approve_run_approval(
        "run-1",
        {
            "approved": True,
            "reason": "Looks safe",
            "metadata": {"approval_id": "approval-1"},
        },
    )

    assert approved["status"] == "completed"
    assert runtime.last_approve_request == {"run_id": "run-1"}


def test_legacy_studio_port_rejects_mismatched_approval_id() -> None:
    runtime = _FakeGroupRuntime()
    port = LegacyStudioPort(runtime)

    with pytest.raises(AgentRuntimeError, match="审批 ID 与当前待审批项不匹配"):
        port.approve_run_approval("run-1", {"approval_id": "wrong-approval"})

    assert runtime.last_approve_request is None


def test_legacy_studio_port_routes_workflow_parent_approval_to_child_run() -> None:
    runtime = _FakeGroupRuntime()
    runtime.child_run_ids = ["workflow-run-1", "workflow-child-1"]
    runtime.runs["workflow-run-1"] = {
        "kind": "workflow_run",
        "pending_approval": None,
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-run-1",
        "runnable_id": "workflow-1",
        "status": "approval_required",
        "timeline": [
            {
                "event_type": "workflow.node.agent",
                "payload": {
                    "child_run_id": "workflow-child-1",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "analyze",
                    "workflow_node_label": "Analyze data",
                },
            }
        ],
        "user_goal": "Build report",
    }
    runtime.runs["workflow-child-1"] = {
        "artifacts": [
            {
                "artifact_id": "artifact-child",
                "kind": "markdown",
                "path": "analysis.md",
            }
        ],
        "kind": "agent_run",
        "pending_approval": {"approval_id": "approval-child", "tool": "terminal.run"},
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-child-1",
        "status": "approval_required",
        "timeline": [],
        "user_goal": "Analyze data",
    }
    port = LegacyStudioPort(runtime)

    approved = port.approve_run_approval("workflow-run-1")
    rejected = port.reject_run_approval(
        "workflow-run-1",
        {"approval_id": "approval-child", "reason": "No"},
    )

    assert runtime.last_approve_request == {"run_id": "workflow-child-1"}
    assert runtime.last_reject_request == {"run_id": "workflow-child-1", "reason": "No"}
    assert approved["run_id"] == "workflow-run-1"
    assert rejected["run_id"] == "workflow-run-1"
    assert approved["runs"][0]["run_id"] == "workflow-child-1"


def test_legacy_studio_port_replays_workflow_child_events_in_parent_page() -> None:
    runtime = _FakeGroupRuntime()
    runtime.child_run_ids = ["workflow-run-1", "workflow-child-1"]
    runtime.runs["workflow-run-1"] = {
        "kind": "workflow_run",
        "pending_approval": None,
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-run-1",
        "runnable_id": "workflow-1",
        "status": "processing",
        "timeline": [],
        "user_goal": "Build report",
    }
    runtime.runs["workflow-child-1"] = {
        "artifacts": [],
        "kind": "agent_run",
        "pending_approval": None,
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-child-1",
        "status": "completed",
        "timeline": [],
        "user_goal": "Analyze data",
    }
    runtime.events["workflow-run-1"] = [
        {
            "event_type": "workflow.node.agent",
            "payload": {
                "child_run_id": "workflow-child-1",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "analyze",
                "workflow_node_label": "Analyze data",
            },
            "run_id": "workflow-run-1",
            "sequence": 1,
        }
    ]
    runtime.events["workflow-child-1"] = [
        {
            "event_id": "child-event-1",
            "event_type": "agent.tool.completed",
            "payload": {"tool_name": "data.analyze"},
            "run_id": "workflow-child-1",
            "sequence": 1,
        }
    ]
    port = LegacyStudioPort(runtime)

    page = port.get_run_event_page("workflow-run-1", after_sequence=0, limit=10)

    assert page["run_id"] == "workflow-run-1"
    assert [event["event_type"] for event in page["events"]] == [
        "workflow.node.agent",
        "agent.tool.completed",
    ]
    child_event = page["events"][1]
    assert child_event["run_id"] == "workflow-run-1"
    assert child_event["sequence"] == 2
    assert child_event["payload"]["source_run_id"] == "workflow-child-1"
    assert child_event["payload"]["source_sequence"] == "1"
    assert child_event["payload"]["source_event_id"] == "child-event-1"
    assert child_event["payload"]["workflow_id"] == "workflow-1"
    assert child_event["payload"]["workflow_run_id"] == "workflow-run-1"
    assert child_event["payload"]["workflow_node_id"] == "analyze"
    assert child_event["payload"]["workflow_node_label"] == "Analyze data"


def test_legacy_studio_port_reads_workflow_child_artifact_from_source_run() -> None:
    runtime = _FakeGroupRuntime()
    runtime.child_run_ids = ["workflow-run-1", "workflow-child-1"]
    runtime.runs["workflow-run-1"] = {
        "artifacts": [],
        "kind": "workflow_run",
        "pending_approval": None,
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-run-1",
        "runnable_id": "workflow-1",
        "status": "completed",
        "timeline": [
            {
                "event_type": "workflow.node.agent",
                "payload": {
                    "child_run_id": "workflow-child-1",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "analyze",
                    "workflow_node_label": "Analyze data",
                },
            }
        ],
        "user_goal": "Build report",
    }
    runtime.runs["workflow-child-1"] = {
        "artifacts": [
            {
                "artifact_id": "artifact-child",
                "kind": "markdown",
                "path": "analysis.md",
            }
        ],
        "kind": "agent_run",
        "pending_approval": None,
        "run_group_id": "workflow-group-1",
        "run_id": "workflow-child-1",
        "status": "completed",
        "timeline": [],
        "user_goal": "Analyze data",
    }
    port = LegacyStudioPort(runtime)

    artifact = port.read_run_artifact("workflow-run-1", "analysis.md")

    assert artifact["run_id"] == "workflow-child-1"
    assert artifact["workflow_run_id"] == "workflow-run-1"
    assert runtime.last_artifact_request == {
        "run_id": "workflow-child-1",
        "artifact_path": "analysis.md",
    }


class _FakeStudioRunRuntime:
    def __init__(self) -> None:
        self.agent_run_payload: dict[str, Any] | None = None
        self.workflow_run_payload: dict[str, Any] | None = None
        self.events: dict[str, list[dict[str, Any]]] = {}

    def create_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.agent_run_payload = dict(payload)
        return {
            "run_id": "agent-run-1",
            "status": "processing",
            "user_goal": payload.get("user_goal"),
        }

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.workflow_run_payload = dict(payload)
        return {
            "run_id": "workflow-run-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_id": payload.get("workflow_id"),
            "status": "processing",
            "user_goal": payload.get("user_goal"),
        }

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event_type": event_type,
            "payload": dict(payload),
            "run_id": run_id,
        }
        self.events.setdefault(run_id, []).append(event)
        return event

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "events": list(self.events.get(run_id, [])),
        }


class _FakeGroupRuntime:
    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.child_run_ids: list[str] = []
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.last_approve_request: dict[str, Any] | None = None
        self.last_artifact_request: dict[str, Any] | None = None
        self.last_event_page_request: dict[str, Any] | None = None
        self.last_reject_request: dict[str, Any] | None = None
        self.runs: dict[str, dict[str, Any]] = {}
        self.runnable_run_payloads: list[dict[str, Any]] = []
        self.statuses = statuses or {}
        self.group = {
            "group_id": "group-1",
            "name": "Review team",
            "mode": "parallel",
            "memory_scope": "shared",
            "members": [
                {"agent_id": "agent-1", "name": "Planner", "role": "planner"},
                {"agent_id": "agent-2", "name": "Reviewer", "role": "reviewer"},
            ],
        }

    def get_agent_group(self, group_id: str) -> dict[str, Any]:
        if group_id != "group-1":
            raise KeyError(group_id)
        return dict(self.group)

    def create_run_for_runnable_async(
        self,
        *,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        on_complete: Any | None = None,
        runtime_planner_entrypoint: bool = False,
        agent_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del on_complete
        self.runnable_run_payloads.append(
            {
                "runnable_id": runnable_id,
                "user_goal": user_goal,
                "run_group_id": run_group_id,
                "runtime_planner_entrypoint": runtime_planner_entrypoint,
                "agent_override": agent_override,
            }
        )
        clean_run_group_id = run_group_id or "group-run-1"
        run_id = f"run-{len(self.runs) + 1}"
        status = self.statuses.get(runnable_id, "processing")
        run = {
            "artifacts": [],
            "pending_approval": {},
            "run_group_id": clean_run_group_id,
            "run_id": run_id,
            "runnable_id": runnable_id,
            "runnable_name": runnable_id,
            "status": status,
            "user_goal": user_goal,
        }
        self.runs[run_id] = run
        self.child_run_ids.append(run_id)
        return dict(run)

    def get_run(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs and run_id == "run-1":
            return {
                "pending_approval": {"approval_id": "approval-1"},
                "run_id": "run-1",
                "status": "approval_required",
                "user_goal": "Approve me",
            }
        return dict(self.runs[run_id])

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event_type": event_type,
            "payload": dict(payload),
            "run_id": run_id,
        }
        self.events.setdefault(run_id, []).append(event)
        return event

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return {
            "child_run_ids": list(self.child_run_ids),
            "created_at": "2026-06-16T00:00:00Z",
            "run_group_id": run_group_id,
            "status": "running",
            "summary": "",
            "title": "Review team",
            "updated_at": "2026-06-16T00:00:00Z",
        }

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.last_event_page_request = {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
        }
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "events": list(self.events.get(run_id, [])),
        }

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.last_reject_request = {"run_id": run_id, "reason": reason}
        return {
            "run_id": run_id,
            "status": "failed",
            "user_goal": "Rejected",
        }

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.last_approve_request = {"run_id": run_id}
        return {
            "run_id": run_id,
            "status": "completed",
            "user_goal": "Approved",
        }

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.last_artifact_request = {
            "run_id": run_id,
            "artifact_path": artifact_path,
        }
        return {
            "ok": True,
            "run_id": run_id,
            "path": artifact_path,
            "content": "# Report",
        }
