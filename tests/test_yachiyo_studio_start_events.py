"""AgentStudioService start-entrypoint planner event regressions."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import AgentStudioService


def test_studio_start_agent_run_enriches_bare_port_payload_with_planner_events() -> None:
    port = _BareStartPort()
    run = AgentStudioService(port).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
        }
    )

    assert run.run_id == "agent-run-1"
    assert [event.event_type for event in run.events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert run.task_core is not None
    assert run.task_core.todos
    assert run.events[0].payload["intent"]["kind"] == "data_analysis"
    start_payload = port.agent_run_payloads[0]
    assert "runtime_execution_envelope" in start_payload
    assert [request["tool"] for request in start_payload["direct_tool_requests"]] == [
        "data.analyze",
    ]
    assert start_payload["direct_tool_requests"][0]["step_id"] == "analyze-data-file"


def test_studio_start_group_run_enriches_bare_port_payload_with_group_scoped_events() -> None:
    port = _BareStartPort()
    group_run = AgentStudioService(port).start_group_run(
        {
            "group_id": "group-1",
            "objective": "请两位 agent 对比方案并产出总结",
        }
    )

    event_types = [event.event_type for event in group_run.events]

    assert group_run.group_run_id == "group-run-1"
    assert "group.run.started" in event_types
    assert "group.run.intent.selected" in event_types
    assert "group.run.plan.created" in event_types
    assert "group.run.task_core.created" in event_types
    assert group_run.task_core is not None
    assert group_run.task_core.todos
    start_payload = port.group_run_payloads[0]
    request_envelope = start_payload["metadata"]["yachiyo_execution_envelope"]
    assert request_envelope["requests"][0]["group_id"] == "group-1"
    assert start_payload["direct_tool_requests"][0]["group_id"] == "group-1"
    plan_event = next(event for event in group_run.events if event.event_type == "group.run.plan.created")
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["group_id"] == "group-1"
    assert event_request["group_run_id"] == "group-run-1"
    assert event_request["run_group_id"] == "group-run-1"


def test_studio_start_workflow_run_enriches_bare_port_payload_with_workflow_scoped_events() -> None:
    port = _BareStartPort()
    workflow_run = AgentStudioService(port).start_workflow_run(
        {
            "workflow_id": "workflow-1",
            "objective": "打开 PixelForge",
        }
    )

    event_types = [event.event_type for event in workflow_run.events]

    assert workflow_run.workflow_run_id == "workflow-run-1"
    assert "workflow.run.started" in event_types
    assert "workflow.run.intent.selected" in event_types
    assert "workflow.run.plan.created" in event_types
    assert "workflow.run.task_core.created" in event_types
    assert workflow_run.task_core is not None
    assert workflow_run.task_core.todos
    start_payload = port.workflow_run_payloads[0]
    request_envelope = start_payload["metadata"]["yachiyo_execution_envelope"]
    assert request_envelope["requests"][0]["workflow_id"] == "workflow-1"
    assert start_payload["direct_tool_requests"][0]["workflow_id"] == "workflow-1"
    plan_event = next(
        event for event in workflow_run.events if event.event_type == "workflow.run.plan.created"
    )
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert event_request["workflow_id"] == "workflow-1"
    assert event_request["workflow_run_id"] == "workflow-run-1"


def test_studio_start_agent_run_does_not_duplicate_existing_planner_events() -> None:
    run = AgentStudioService(_BareStartPort(existing_planner_events=True)).start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "请分析 data/sales.csv 并输出报告",
        }
    )

    assert [event.event_type for event in run.events].count("agent.intent.selected") == 1


class _BareStartPort:
    def __init__(self, *, existing_planner_events: bool = False) -> None:
        self.existing_planner_events = existing_planner_events
        self.agent_run_payloads: list[dict[str, Any]] = []
        self.group_run_payloads: list[dict[str, Any]] = []
        self.workflow_run_payloads: list[dict[str, Any]] = []

    def start_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.agent_run_payloads.append(payload)
        events = []
        if self.existing_planner_events:
            events.append(
                {
                    "event_type": "agent.intent.selected",
                    "payload": {"intent": {"kind": "data_analysis"}},
                }
            )
        return {
            "run_id": "agent-run-1",
            "agent_id": payload.get("agent_id") or "agent-1",
            "title": payload.get("title") or "Agent run",
            "status": "running",
            "events": events,
        }

    def start_group_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.group_run_payloads.append(payload)
        return {
            "group_run_id": "group-run-1",
            "run_group_id": "group-run-1",
            "group_id": payload.get("group_id") or "group-1",
            "title": payload.get("title") or "Group run",
            "objective": payload.get("objective") or "",
            "status": "running",
            "events": [],
            "participants": [],
            "runs": [],
            "child_run_ids": [],
        }

    def start_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.workflow_run_payloads.append(payload)
        return {
            "run_id": "workflow-run-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_id": payload.get("workflow_id") or "workflow-1",
            "title": payload.get("title") or "Workflow run",
            "objective": payload.get("objective") or "",
            "status": "running",
            "events": [],
        }
