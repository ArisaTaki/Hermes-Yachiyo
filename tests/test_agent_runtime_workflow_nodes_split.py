"""Tests for workflow node handoffs split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowSubworkflowNodeExecution,
)


def test_workflow_node_handoffs_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowAgentNodeHandoff is WorkflowAgentNodeHandoff
    assert agent_runtime.WorkflowAgentNodeExecution is WorkflowAgentNodeExecution
    assert agent_runtime.WorkflowSubworkflowNodeExecution is WorkflowSubworkflowNodeExecution
    assert agent_runtime.WorkflowArtifactNodeWrite is WorkflowArtifactNodeWrite


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
