"""Tests for Workflow parallel execution helpers split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_parallel import (
    WorkflowParallelExecutionPortBundle,
    WorkflowParallelNodeExecution,
)


def test_workflow_parallel_execution_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowParallelExecutionPortBundle is WorkflowParallelExecutionPortBundle
    assert agent_runtime.WorkflowParallelNodeExecution is WorkflowParallelNodeExecution


def test_workflow_parallel_execution_runs_agent_and_artifact_branch_with_metadata() -> None:
    calls: list[tuple[str, str, str, str, str]] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    ports = WorkflowParallelExecutionPortBundle(
        node_kind=lambda node: str(node["type"]),
        completed_agent_context=lambda *_args, **_kwargs: None,
        completed_artifact_exists=lambda *_args, **_kwargs: False,
        run_agent_node=lambda _run, node, **kwargs: calls.append(
            (
                "agent",
                str(node["id"]),
                str(kwargs["context"]),
                str(kwargs["node_info_extra"]["workflow_parent_node_id"]),
                str(kwargs["node_info_extra"]["workflow_parallel_branch_label"]),
            )
        )
        or {"done": False, "context": "Design ready"},
        write_artifact_node=lambda _run, node, **kwargs: calls.append(
            (
                "artifact",
                str(node["id"]),
                str(kwargs["context"]),
                str(kwargs["node_info_extra"]["workflow_parent_node_id"]),
                str(kwargs["node_info_extra"]["workflow_parallel_branch_label"]),
            )
        ),
    )

    execution = WorkflowParallelNodeExecution.from_plan(
        run={"run_id": "workflow_run"},
        node={"id": "fanout", "type": "parallel"},
        plan={
            "join_node_id": "join",
            "branches": [
                {
                    "entry_node_id": "design",
                    "label": "Design",
                    "node_ids": ["design", "report"],
                }
            ],
        },
        nodes_by_id={
            "design": {"id": "design", "type": "agent", "data": {"label": "Design Agent"}},
            "report": {"id": "report", "type": "artifact", "data": {"label": "Report"}},
        },
        label="Parallel Work",
        kind="parallel",
        workflow_goal="Ship release",
        context="Parent context",
        parallel_context="Resume context",
        has_agent_upstream=True,
        run_group_id="workflow_group",
        timeline=timeline,
        artifacts=artifacts,
        root_group=False,
        ports=ports,
    )

    assert execution.done is False
    assert execution.branch_results == [
        {"entry_node_id": "design", "label": "Design", "result": "Design ready"}
    ]
    assert execution.aggregate_context == "Parallel Parallel Work results:\n- Design: Design ready"
    assert calls == [
        ("agent", "design", "Resume context", "fanout", "Design"),
        ("artifact", "report", "Design ready", "fanout", "Design"),
    ]


def test_workflow_parallel_execution_reuses_completed_branch_state() -> None:
    calls: list[tuple[str, str]] = []
    ports = WorkflowParallelExecutionPortBundle(
        node_kind=lambda node: str(node["type"]),
        completed_agent_context=lambda _timeline, *, parallel_node_id, branch_node_id: calls.append(
            ("completed-agent", f"{parallel_node_id}:{branch_node_id}")
        )
        or "Cached branch result",
        completed_artifact_exists=lambda _timeline, *, parallel_node_id, branch_node_id: calls.append(
            ("completed-artifact", f"{parallel_node_id}:{branch_node_id}")
        )
        or True,
        run_agent_node=lambda *_args, **_kwargs: calls.append(("agent", "unexpected")),
        write_artifact_node=lambda *_args, **_kwargs: calls.append(("artifact", "unexpected")),
    )

    execution = WorkflowParallelNodeExecution.from_plan(
        run={"run_id": "workflow_run"},
        node={"id": "fanout", "type": "parallel"},
        plan={
            "branches": [
                {"entry_node_id": "design", "label": "Design", "node_ids": ["design", "report"]}
            ]
        },
        nodes_by_id={
            "design": {"id": "design", "type": "agent"},
            "report": {"id": "report", "type": "artifact"},
        },
        label="Parallel Work",
        kind="parallel",
        workflow_goal="Ship release",
        context="Parent context",
        parallel_context="Resume context",
        has_agent_upstream=True,
        run_group_id="workflow_group",
        timeline=[],
        artifacts=[],
        root_group=False,
        ports=ports,
    )

    assert execution.branch_results == [
        {"entry_node_id": "design", "label": "Design", "result": "Cached branch result"}
    ]
    assert calls == [
        ("completed-agent", "fanout:design"),
        ("completed-artifact", "fanout:report"),
    ]


def test_workflow_parallel_execution_returns_early_child_result() -> None:
    child_result = {"done": True, "run": {"run_id": "workflow_run", "status": "approval_required"}}
    ports = WorkflowParallelExecutionPortBundle(
        node_kind=lambda node: str(node["type"]),
        completed_agent_context=lambda *_args, **_kwargs: None,
        completed_artifact_exists=lambda *_args, **_kwargs: False,
        run_agent_node=lambda *_args, **_kwargs: child_result,
        write_artifact_node=lambda *_args, **_kwargs: None,
    )

    execution = WorkflowParallelNodeExecution.from_plan(
        run={"run_id": "workflow_run"},
        node={"id": "fanout", "type": "parallel"},
        plan={"branches": [{"entry_node_id": "design", "node_ids": ["design"]}]},
        nodes_by_id={"design": {"id": "design", "type": "agent"}},
        label="Parallel Work",
        kind="parallel",
        workflow_goal="Ship release",
        context="Parent context",
        parallel_context="Resume context",
        has_agent_upstream=True,
        run_group_id="workflow_group",
        timeline=[],
        artifacts=[],
        root_group=False,
        ports=ports,
    )

    assert execution.done is True
    assert execution.early_result is child_result
    assert execution.branch_results == []


def test_workflow_parallel_execution_rejects_unsupported_branch_node() -> None:
    ports = WorkflowParallelExecutionPortBundle(
        node_kind=lambda node: str(node["type"]),
        completed_agent_context=lambda *_args, **_kwargs: None,
        completed_artifact_exists=lambda *_args, **_kwargs: False,
        run_agent_node=lambda *_args, **_kwargs: {"done": False, "context": ""},
        write_artifact_node=lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AgentRuntimeError, match="Parallel 分支暂不支持 workflow 节点：Child"):
        WorkflowParallelNodeExecution.from_plan(
            run={"run_id": "workflow_run"},
            node={"id": "fanout", "type": "parallel"},
            plan={"branches": [{"entry_node_id": "child", "node_ids": ["child"]}]},
            nodes_by_id={"child": {"id": "child", "type": "workflow", "data": {"label": "Child"}}},
            label="Parallel Work",
            kind="parallel",
            workflow_goal="Ship release",
            context="Parent context",
            parallel_context="Resume context",
            has_agent_upstream=True,
            run_group_id="workflow_group",
            timeline=[],
            artifacts=[],
            root_group=False,
            ports=ports,
        )

