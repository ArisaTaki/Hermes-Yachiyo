"""Fake-port tests for the Agent Studio facade."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import (
    AgentStudioService,
    SaveAgentGroupMemberRequest,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    StartAgentRunRequest,
    StartGroupRunRequest,
    StartWorkflowRunRequest,
)


class _FakeStudioPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def list_agents(self) -> dict[str, Any]:
        self.calls.append(("list_agents", None))
        return {"ok": True, "agents": [_agent_payload()]}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent", agent_id))
        return _agent_payload(agent_id=agent_id, name="Fetched")

    def save_agent(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_agent", request))
        return _agent_payload(agent_id=request.get("agent_id") or "agent-new", name=request["name"])

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("delete_agent", agent_id))
        return {"ok": True, "agent_id": agent_id}

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_agent_run", request))
        return _run_payload(
            run_id="agent-run-1",
            runnable_id=request["agent_id"],
            kind="agent_run",
            user_goal=request["objective"],
        )

    def list_groups(self) -> list[dict[str, Any]]:
        self.calls.append(("list_groups", None))
        return [_group_payload()]

    def get_group(self, group_id: str) -> dict[str, Any]:
        self.calls.append(("get_group", group_id))
        return _group_payload(group_id=group_id)

    def save_group(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_group", request))
        return _group_payload(group_id=request.get("group_id") or "group-new", name=request["name"])

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_group_run", request))
        return _group_run_payload(group_id=request["group_id"], objective=request["objective"])

    def list_group_runs(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append(("list_group_runs", limit))
        return {"ok": True, "group_runs": [_group_run_payload(group_run_id="group-run-listed")]}

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        self.calls.append(("get_group_run", group_run_id))
        return {
            "run_group_id": group_run_id,
            "title": "Legacy run group",
            "status": "running",
            "summary": "Legacy summary",
            "child_run_ids": ["child-run-1"],
        }

    def list_workflows(self) -> dict[str, Any]:
        self.calls.append(("list_workflows", None))
        return {"ok": True, "workflows": [_workflow_payload()]}

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("get_workflow", workflow_id))
        return _workflow_payload(workflow_id=workflow_id)

    def save_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_workflow", request))
        return _workflow_payload(
            workflow_id=request.get("workflow_id") or "workflow-new",
            name=request["name"],
        )

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("delete_workflow", workflow_id))
        return {"ok": True, "workflow_id": workflow_id}

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_workflow_run", request))
        return _run_payload(
            run_id="workflow-run-1",
            runnable_id=request["workflow_id"],
            kind="workflow_run",
            user_goal=request["objective"],
        )

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append(("list_run_timelines", limit))
        return {"ok": True, "runs": [_run_payload(run_id="run-listed")]}

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        return _run_payload(run_id=run_id)

    def rerun_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("rerun_run", run_id))
        return _run_payload(run_id=f"{run_id}-rerun", user_goal="Rerun task")

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_run", run_id))
        return _run_payload(run_id=run_id, user_goal="Cancelled task") | {"status": "cancelled"}

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", run_id))
        return _run_payload(run_id=run_id, user_goal="Approved task") | {"status": "completed"}

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.calls.append(("reject_run_approval", {"run_id": run_id, "reason": reason}))
        return _run_payload(run_id=run_id, user_goal="Rejected task") | {"status": "failed"}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(
            ("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path})
        )
        return {"ok": True, "run_id": run_id, "path": artifact_path, "content": "# Report"}

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_event_stream", run_id))
        return {
            "run_id": run_id,
            "after_sequence": 0,
            "limit": 200,
            "events": [
                {
                    "event_id": "event-stream-1",
                    "run_id": run_id,
                    "sequence": 10,
                    "event_type": "agent.started",
                    "payload": {"status": "running"},
                }
            ],
        }


def test_agent_studio_service_maps_agent_group_workflow_snapshots() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    agents = service.list_agents()
    agent = service.get_agent("agent-1")
    saved_agent = service.save_agent(
        SaveAgentRequest(
            agent_id="agent-2",
            name="Writer",
            model_config={"provider": "model_profile"},
            tool_policy={"allowed_tools": ["workspace.read"]},
            skill_ids=["skill-1"],
        )
    )
    deleted_agent = service.delete_agent("agent-2")
    groups = service.list_groups()
    group = service.get_group("group-1")
    saved_group = service.save_group(
        SaveAgentGroupRequest(
            group_id="group-2",
            name="Team",
            members=[
                SaveAgentGroupMemberRequest(
                    agent_id="agent-1",
                    role="planner",
                    sort_order=1,
                )
            ],
            mode="pipeline",
            memory_scope="hybrid",
        )
    )
    workflows = service.list_workflows()
    workflow = service.get_workflow("workflow-1")
    saved_workflow = service.save_workflow(
        SaveWorkflowRequest(
            workflow_id="workflow-2",
            name="Saved workflow",
            nodes=[{"id": "start", "type": "start"}],
            edges=[],
            default_input_schema={"type": "object"},
        )
    )
    deleted_workflow = service.delete_workflow("workflow-2")

    assert agents[0].agent_id == "agent-1"
    assert agent.name == "Fetched"
    assert saved_agent.agent_id == "agent-2"
    assert deleted_agent == {"ok": True, "agent_id": "agent-2"}
    assert groups[0].members[0].agent_id == "agent-1"
    assert group.mode == "debate"
    assert saved_group.name == "Team"
    assert workflows[0].nodes[0]["type"] == "start"
    assert workflow.workflow_id == "workflow-1"
    assert saved_workflow.name == "Saved workflow"
    assert deleted_workflow == {"ok": True, "workflow_id": "workflow-2"}
    assert (
        "save_agent",
        {
            "agent_id": "agent-2",
            "name": "Writer",
            "model_config": {"provider": "model_profile"},
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "skill_ids": ["skill-1"],
        },
    ) in port.calls
    assert ("delete_agent", "agent-2") in port.calls
    assert (
        "save_group",
        {
            "group_id": "group-2",
            "name": "Team",
            "members": [
                {
                    "agent_id": "agent-1",
                    "role": "planner",
                    "sort_order": 1,
                    "enabled": True,
                }
            ],
            "mode": "pipeline",
            "memory_scope": "hybrid",
        },
    ) in port.calls
    assert ("delete_workflow", "workflow-2") in port.calls
    assert (
        "save_workflow",
        {
            "workflow_id": "workflow-2",
            "name": "Saved workflow",
            "nodes": [{"id": "start", "type": "start"}],
            "edges": [],
            "default_input_schema": {"type": "object"},
        },
    ) in port.calls


def test_agent_studio_service_maps_group_run_workflow_run_timeline_and_events() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    agent_run = service.start_agent_run(
        StartAgentRunRequest(agent_id="agent-1", objective="Draft summary")
    )
    group_run = service.start_group_run(
        StartGroupRunRequest(
            group_id="group-1",
            objective="Compare designs",
            client_run_id="client-group-1",
        )
    )
    group_runs = service.list_group_runs(5)
    fetched_group_run = service.get_group_run("group-run-1")
    workflow_run = service.start_workflow_run(
        StartWorkflowRunRequest(workflow_id="workflow-1", objective="Build report")
    )
    timelines = service.list_run_timelines(10)
    timeline = service.get_run_timeline("run-1")
    events = list(service.get_run_event_stream("run-1"))

    assert agent_run.run_id == "agent-run-1"
    assert agent_run.agent_id == "agent-1"
    assert agent_run.title == "Draft summary"
    assert group_run.group_id == "group-1"
    assert group_run.run_group_id == "group-run-1"
    assert group_run.objective == "Compare designs"
    assert group_run.runs[0].events[0].event_type == "agent.tool.call"
    assert group_run.pending_approvals[0].approval_id == "approval-1"
    assert group_runs[0].group_run_id == "group-run-listed"
    assert fetched_group_run.group_run_id == "group-run-1"
    assert fetched_group_run.run_group_id == "group-run-1"
    assert fetched_group_run.child_run_ids == ["child-run-1"]
    assert workflow_run.workflow_run_id == "workflow-run-1"
    assert workflow_run.run_id == "workflow-run-1"
    assert workflow_run.title == "Build report"
    assert timelines[0].run_id == "run-listed"
    assert timeline.tool_calls[0].tool_name == "workspace.read"
    assert timeline.run_group_id == "group-run-1"
    assert timeline.approvals[0].tool_name == "terminal.run"
    assert timeline.pending_approval is not None
    assert timeline.artifacts[0].path == "report.md"
    assert timeline.children[0].run_id == "child-run-1"
    assert events[0].event_type == "agent.started"
    assert (
        "start_group_run",
        {
            "group_id": "group-1",
            "objective": "Compare designs",
            "client_run_id": "client-group-1",
        },
    ) in port.calls
    assert ("list_group_runs", 5) in port.calls
    assert ("list_run_timelines", 10) in port.calls


def test_agent_studio_service_run_actions_return_public_timeline_snapshots() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    rerun = service.rerun_run("run-1")
    cancelled = service.cancel_run("run-1")
    approved = service.approve_run_approval("run-1")
    rejected = service.reject_run_approval("run-1", "No")

    assert rerun.run_id == "run-1-rerun"
    assert cancelled.status == "cancelled"
    assert approved.status == "completed"
    assert rejected.status == "failed"
    assert ("rerun_run", "run-1") in port.calls
    assert ("cancel_run", "run-1") in port.calls
    assert ("approve_run_approval", "run-1") in port.calls
    assert ("reject_run_approval", {"run_id": "run-1", "reason": "No"}) in port.calls


def test_agent_studio_service_reads_run_artifact_through_port() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    artifact = service.read_run_artifact("run-1", "reports/final.md")

    assert artifact["content"] == "# Report"
    assert (
        "read_run_artifact",
        {"run_id": "run-1", "artifact_path": "reports/final.md"},
    ) in port.calls


def _agent_payload(agent_id: str = "agent-1", name: str = "Planner") -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "name": name,
        "model_mode": "profile",
        "execution_backend": "native_profile",
        "skill_ids": ["skill-1"],
        "enabled": True,
    }


def _group_payload(group_id: str = "group-1", name: str = "Research Team") -> dict[str, Any]:
    return {
        "group_id": group_id,
        "name": name,
        "members": [{"agent_id": "agent-1", "name": "Planner", "role": "planner"}],
        "mode": "debate",
        "memory_scope": "hybrid",
        "enabled": True,
    }


def _group_run_payload(
    group_run_id: str = "group-run-1",
    group_id: str = "group-1",
    objective: str = "Compare options",
) -> dict[str, Any]:
    return {
        "group_run_id": group_run_id,
        "group_id": group_id,
        "title": "Group run",
        "status": "running",
        "objective": objective,
        "participants": [{"agent_id": "agent-1", "name": "Planner"}],
        "runs": [_run_payload()],
        "shared_artifacts": [{"artifact_id": "shared-1", "kind": "markdown", "path": "team.md"}],
        "pending_approvals": [{"approval_id": "approval-1", "tool": "terminal.run"}],
    }


def _workflow_payload(
    workflow_id: str = "workflow-1",
    name: str = "Review workflow",
) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "name": name,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
        "default_input_schema": {"type": "object"},
        "enabled": True,
    }


def _run_payload(
    run_id: str = "run-1",
    runnable_id: str = "agent-1",
    kind: str = "agent_run",
    user_goal: str = "Read README",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_group_id": "group-run-1",
        "kind": kind,
        "runnable_id": runnable_id,
        "status": "approval_required",
        "user_goal": user_goal,
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "README.md"},
            }
        ],
        "pending_approval": {"approval_id": "approval-1", "tool": "terminal.run"},
        "artifacts": [{"artifact_id": "artifact-1", "kind": "markdown", "path": "report.md"}],
        "children": [{"run_id": "child-run-1", "status": "completed"}],
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }
