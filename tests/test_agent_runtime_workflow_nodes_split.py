"""Tests for workflow node handoffs split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowNodePortBundle,
    WorkflowSubworkflowNodeExecution,
)


class FakeWorkflowToolBrokers:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.writes: list[tuple[str, str]] = []

    def for_run(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def artifact_write(self, artifact_path: str, context: str) -> dict[str, object]:
        self.writes.append((artifact_path, context))
        return {"ok": True, "path": artifact_path, "bytes": len(context.encode("utf-8"))}


def test_workflow_node_handoffs_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowAgentNodeHandoff is WorkflowAgentNodeHandoff
    assert agent_runtime.WorkflowAgentNodeExecution is WorkflowAgentNodeExecution
    assert agent_runtime.WorkflowSubworkflowNodeExecution is WorkflowSubworkflowNodeExecution
    assert agent_runtime.WorkflowArtifactNodeWrite is WorkflowArtifactNodeWrite
    assert agent_runtime.WorkflowNodePortBundle is WorkflowNodePortBundle


def test_workflow_agent_node_handoff_accepts_prepared_agent_goal_and_task() -> None:
    agent = {"agent_id": "agent_research", "name": "Research Agent"}
    handoff = WorkflowAgentNodeHandoff.from_agent(
        {
            "id": "research",
            "type": "agent",
            "data": {"agentId": "fallback_agent"},
        },
        agent=agent,
        label="Research",
        kind="agent",
        step_task="Summarize launch risk.",
        child_goal="Ship release candidate\n\nStep: Summarize launch risk.",
        context="Previous result",
        has_agent_upstream=True,
        node_info_extra={"workflow_parent_node_id": "fanout"},
    )

    assert handoff.agent is agent
    assert handoff.agent_id == "agent_research"
    assert handoff.step_task == "Summarize launch risk."
    assert handoff.child_goal == "Ship release candidate\n\nStep: Summarize launch risk."
    assert handoff.upstream == "Previous result"
    assert handoff.node_info() == {
        "workflow_node_id": "research",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Research",
        "workflow_parent_node_id": "fanout",
    }
    assert (
        WorkflowAgentNodeHandoff.from_agent(
            {"id": "fallback", "data": {"agentId": "fallback_agent"}},
            agent={},
            label="Fallback",
            kind="agent",
            step_task="Task",
            child_goal="Goal",
            context="Previous result",
            has_agent_upstream=False,
        ).agent_id
        == "fallback_agent"
    )


def test_workflow_agent_node_execution_accepts_prepared_child_run() -> None:
    handoff = WorkflowAgentNodeHandoff.from_agent(
        {"id": "research", "type": "agent"},
        agent={"agent_id": "agent_research"},
        label="Research",
        kind="agent",
        step_task="Summarize launch risk.",
        child_goal="Ship release candidate\n\nStep: Summarize launch risk.",
        context="Previous result",
        has_agent_upstream=True,
    )
    child_run = {
        "run_id": "child_run",
        "status": "completed",
        "result": "Launch risk summary",
    }

    execution = WorkflowAgentNodeExecution.from_child_run(
        handoff,
        child_run,
        artifact_count=2,
    )

    assert execution.handoff is handoff
    assert execution.child_run is child_run
    assert execution.next_context == "Launch risk summary"
    assert execution.status == "completed"
    assert execution.artifact_count == 2
    assert execution.agent_event_payload() == {
        "workflow_node_id": "research",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Research",
        "workflow_node_task": "Summarize launch risk.",
        "child_run_id": "child_run",
        "status": "completed",
        "result": "Launch risk summary",
        "artifact_count": 2,
    }


def test_workflow_agent_node_legacy_helpers_accept_port_bundle() -> None:
    agent = {"agent_id": "agent_research", "name": "Research Agent"}
    child_run = {
        "run_id": "child_run",
        "status": "completed",
        "result": "Launch risk summary",
        "artifacts": [{"kind": "artifact", "path": "risk.md"}],
    }
    calls: list[tuple[str, str]] = []
    ports = WorkflowNodePortBundle(
        workflow_agent_for_node=lambda node: calls.append(("agent", str(node["id"]))) or agent,
        workflow_node_task=lambda node: calls.append(("task", str(node["id"])))
        or "Summarize launch risk.",
        workflow_child_goal=lambda workflow_goal, step_task: calls.append(("goal", step_task))
        or f"{workflow_goal}\n\nStep: {step_task}",
        insert_run=lambda **kwargs: calls.append(("insert", str(kwargs["runnable_id"])))
        or {"run_id": "child_run"},
        execute_agent_run=lambda run_id, _agent, _goal, *, upstream: calls.append(
            ("execute", f"{run_id}:{upstream}")
        )
        or child_run,
        workflow_child_artifact_refs=lambda run, label: calls.append(
            ("artifacts", f"{run['run_id']}:{label}")
        )
        or run.get("artifacts", []),
    )

    handoff = WorkflowAgentNodeHandoff.from_node(
        object(),
        {"id": "research", "type": "agent"},
        label="Research",
        kind="agent",
        workflow_goal="Ship release candidate",
        context="Previous result",
        has_agent_upstream=True,
        ports=ports,
    )
    execution = WorkflowAgentNodeExecution.from_handoff(
        object(),
        handoff,
        run_group_id="workflow_group",
        ports=ports,
    )

    assert handoff.agent is agent
    assert handoff.child_goal == "Ship release candidate\n\nStep: Summarize launch risk."
    assert execution.child_run is child_run
    assert execution.artifact_count == 1
    assert calls == [
        ("agent", "research"),
        ("task", "research"),
        ("goal", "Summarize launch risk."),
        ("insert", "agent_research"),
        ("execute", "child_run:Previous result"),
        ("artifacts", "child_run:Research"),
    ]


def test_workflow_subworkflow_node_execution_accepts_prepared_child_run() -> None:
    child_workflow = {"workflow_id": "workflow_child", "name": "Child Flow"}
    child_run = {
        "run_id": "child_workflow_run",
        "status": "completed",
        "result": "Child flow result",
    }

    execution = WorkflowSubworkflowNodeExecution.from_child_run(
        {"id": "child-flow", "type": "workflow"},
        child_workflow=child_workflow,
        child_run=child_run,
        label="Run Child Flow",
        kind="workflow",
        step_task="Run child flow first",
        child_goal="Run parent flow\n\nStep: Run child flow first",
        artifact_count=1,
    )

    assert execution.child_workflow is child_workflow
    assert execution.workflow_id == "workflow_child"
    assert execution.child_run is child_run
    assert execution.next_context == "Child flow result"
    assert execution.status == "completed"
    assert execution.event_payload() == {
        "workflow_node_id": "child-flow",
        "workflow_node_kind": "workflow",
        "workflow_node_label": "Run Child Flow",
        "workflow_node_task": "Run child flow first",
        "child_workflow_id": "workflow_child",
        "child_workflow_name": "Child Flow",
        "child_run_id": "child_workflow_run",
        "status": "completed",
        "result": "Child flow result",
        "artifact_count": 1,
    }


def test_workflow_subworkflow_node_legacy_helper_accepts_port_bundle() -> None:
    child_workflow = {"workflow_id": "workflow_child", "name": "Child Flow"}
    child_run = {
        "run_id": "child_workflow_run",
        "kind": "workflow_run",
        "status": "completed",
        "result": "Child flow result",
        "artifacts": [{"kind": "workflow_artifact", "path": "child.md"}],
    }
    calls: list[tuple[str, str]] = []
    ports = WorkflowNodePortBundle(
        workflow_for_node=lambda node: calls.append(("workflow", str(node["id"])))
        or child_workflow,
        workflow_node_task=lambda node: calls.append(("task", str(node["id"])))
        or "Run child flow",
        workflow_child_goal=lambda workflow_goal, step_task: calls.append(("goal", step_task))
        or f"{workflow_goal}\n\nStep: {step_task}",
        insert_run=lambda **kwargs: calls.append(("insert", str(kwargs["runnable_id"])))
        or {"run_id": "child_workflow_run"},
        workflow_run_started_projection=lambda workflow_id, _workflow: calls.append(
            ("started", workflow_id)
        )
        or ([{"event": "workflow.run.started"}], {"workflow_id": workflow_id}),
        append_run_event=lambda run_id, event_type, _payload: calls.append(
            ("event", f"{run_id}:{event_type}")
        ),
        continue_workflow_run=lambda run, _workflow, **kwargs: calls.append(
            ("continue", f"{run['run_id']}:{kwargs['context']}")
        )
        or child_run,
        workflow_child_artifact_refs=lambda run, label: calls.append(
            ("artifacts", f"{run['run_id']}:{label}")
        )
        or run.get("artifacts", []),
    )

    execution = WorkflowSubworkflowNodeExecution.from_node(
        object(),
        {"run_id": "parent"},
        {"id": "child-flow", "type": "workflow"},
        label="Run Child Flow",
        kind="workflow",
        workflow_goal="Run parent flow",
        run_group_id="workflow_group",
        ports=ports,
    )

    assert execution.child_workflow is child_workflow
    assert execution.child_run is child_run
    assert execution.artifact_count == 1
    assert calls == [
        ("workflow", "child-flow"),
        ("task", "child-flow"),
        ("goal", "Run child flow"),
        ("insert", "workflow_child"),
        ("started", "workflow_child"),
        ("event", "child_workflow_run:workflow.run.started"),
        ("continue", "child_workflow_run:Run parent flow\n\nStep: Run child flow"),
        ("artifacts", "child_workflow_run:Run Child Flow"),
    ]


def test_workflow_artifact_node_write_accepts_prepared_artifact() -> None:
    write = WorkflowArtifactNodeWrite.from_artifact(
        {
            "id": "report",
            "type": "artifact",
            "data": {"artifact_path": "reports/final.md"},
        },
        {"ok": True, "path": "reports/final.md", "bytes": 12},
        label="Final Report",
        kind="artifact",
        node_info_extra={"workflow_parent_node_id": "fanout"},
    )

    assert WorkflowArtifactNodeWrite.configured_path(
        {"data": {"artifactPath": "reports/alt.md"}}
    ) == "reports/alt.md"
    assert write.artifact_record() == {
        "kind": "workflow_artifact",
        "workflow_node_id": "report",
        "workflow_node_label": "Final Report",
        "ok": True,
        "path": "reports/final.md",
        "bytes": 12,
    }
    assert write.event_payload() == {
        "workflow_node_id": "report",
        "workflow_node_kind": "artifact",
        "workflow_node_label": "Final Report",
        "status": "completed",
        "artifact": {"ok": True, "path": "reports/final.md", "bytes": 12},
        "workflow_parent_node_id": "fanout",
    }


def test_workflow_artifact_node_legacy_helper_accepts_write_port() -> None:
    calls: list[tuple[str, str]] = []
    ports = WorkflowNodePortBundle(
        workflow_artifact_path=lambda label, _artifacts, requested: calls.append(
            ("path", f"{label}:{requested}")
        )
        or requested,
        workflow_artifact_write=lambda run, artifact_path, context: calls.append(
            ("write", f"{run['run_id']}:{artifact_path}:{context}")
        )
        or {"ok": True, "path": artifact_path, "bytes": len(context.encode("utf-8"))},
    )

    write = WorkflowArtifactNodeWrite.from_node(
        object(),
        {"run_id": "workflow_run"},
        {
            "id": "report",
            "type": "artifact",
            "data": {"artifact_path": "reports/final.md"},
        },
        label="Final Report",
        kind="artifact",
        context="Final workflow summary",
        artifacts=[],
        ports=ports,
    )

    assert write.artifact_record()["path"] == "reports/final.md"
    assert write.artifact_record()["bytes"] == len("Final workflow summary".encode("utf-8"))
    assert calls == [
        ("path", "Final Report:reports/final.md"),
        ("write", "workflow_run:reports/final.md:Final workflow summary"),
    ]


def test_workflow_artifact_node_legacy_helper_uses_engine_tool_brokers(tmp_path) -> None:
    tool_brokers = FakeWorkflowToolBrokers()

    class FakeEngine:
        workflow_artifacts_dir = tmp_path / "workflow-artifacts"

        def _default_workspace_policy(self):
            return {"default_workdir": str(tmp_path)}

        def _workflow_artifact_path(self, _label, _artifacts, requested):
            return requested

    FakeEngine.tool_brokers = tool_brokers

    write = WorkflowArtifactNodeWrite.from_node(
        FakeEngine(),
        {"run_id": "workflow_run"},
        {
            "id": "report",
            "type": "artifact",
            "data": {"artifact_path": "reports/final.md"},
        },
        label="Final Report",
        kind="artifact",
        context="Final workflow summary",
        artifacts=[],
    )

    assert write.artifact_record()["path"] == "reports/final.md"
    assert tool_brokers.calls == [
        {
            "run_id": "workflow_run",
            "workspace_policy": {"default_workdir": str(tmp_path)},
            "artifacts_dir": tmp_path / "workflow-artifacts",
        }
    ]
    assert tool_brokers.writes == [("reports/final.md", "Final workflow summary")]
