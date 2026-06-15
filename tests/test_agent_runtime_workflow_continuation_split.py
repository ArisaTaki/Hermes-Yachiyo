"""Tests for workflow continuation coordinator split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_continuation import WorkflowContinuationCoordinator
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowContinuationFailureProjection,
    WorkflowRunCompletionProjection,
)
from apps.shell.agent.runtime.workflow_run_outcomes import WorkflowRunOutcomeProjector


def test_workflow_continuation_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowContinuationCoordinator is WorkflowContinuationCoordinator
    assert agent_runtime.WorkflowRunOutcomeProjector is WorkflowRunOutcomeProjector


class FakeWorkflowOutcomeEngine:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.run_updates: list[tuple[str, dict[str, Any]]] = []
        self.group_updates: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[str] = []

    def _timeline(self, event: str, detail: str, **payload: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **payload}

    def append_run_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((run_id, event_type, payload))

    def _update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        self.run_updates.append((run_id, fields))
        return {"run_id": run_id, "run_group_id": "run_group", **fields}

    def _update_run_group(self, run_group_id: str, **fields: Any) -> None:
        self.group_updates.append((run_group_id, fields))

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.get_calls.append(run_id)
        return {
            "run_id": run_id,
            "run_group_id": "run_group",
            **self.run_updates[-1][1],
            "refetched": True,
        }


def test_workflow_run_outcome_projector_projects_completed_root_group() -> None:
    engine = FakeWorkflowOutcomeEngine()
    projector = WorkflowRunOutcomeProjector(engine)
    timeline: list[dict[str, Any]] = [{"event": "workflow.run.started"}]
    artifacts = [{"kind": "workflow_artifact", "path": "report.md"}]

    result = projector.completed(
        {"run_id": "workflow_run", "run_group_id": "run_group"},
        WorkflowRunCompletionProjection("Workflow result"),
        timeline=timeline,
        artifacts=artifacts,
        root_group=True,
    )

    assert timeline == [
        {"event": "workflow.run.started"},
        {"event": "workflow.run.completed", "detail": "Workflow run completed"},
    ]
    assert engine.events == [
        ("workflow_run", "workflow.run.completed", {"result": "Workflow result"})
    ]
    assert engine.run_updates == [
        (
            "workflow_run",
            {
                "status": "completed",
                "result": "Workflow result",
                "timeline": timeline,
                "artifacts": artifacts,
            },
        )
    ]
    assert engine.group_updates == [
        ("run_group", {"status": "completed", "summary": "Workflow result"})
    ]
    assert engine.get_calls == ["workflow_run"]
    assert result["refetched"] is True


def test_workflow_run_outcome_projector_projects_failed_root_group_with_redaction() -> None:
    engine = FakeWorkflowOutcomeEngine()
    projector = WorkflowRunOutcomeProjector(engine)
    timeline: list[dict[str, Any]] = []
    secret = "sk-workflow-secret123456"

    result = projector.failed(
        {"run_id": "workflow_run", "run_group_id": "run_group"},
        WorkflowContinuationFailureProjection.from_error(
            RuntimeError(f"failed with {secret}"),
            {"workflow_node_kind": f"tool {secret}"},
        ),
        timeline=timeline,
        artifacts=[],
        root_group=True,
    )

    assert secret not in str({"result": result, "events": engine.events, "timeline": timeline})
    assert timeline == [
        {
            "event": "workflow.run.failed",
            "detail": result["result"],
            "status": "failed",
            "workflow_node_kind": "tool [redacted]",
        }
    ]
    assert engine.events == [
        (
            "workflow_run",
            "workflow.run.failed",
            {
                "error": result["result"],
                "workflow_node_kind": "tool [redacted]",
            },
        )
    ]
    assert engine.group_updates == [
        ("run_group", {"status": "failed", "summary": result["result"]})
    ]
    assert result["refetched"] is True


def test_workflow_run_outcome_projector_projects_background_failure_without_mutating_source_timeline() -> None:
    engine = FakeWorkflowOutcomeEngine()
    projector = WorkflowRunOutcomeProjector(engine)
    timeline = [{"event": "workflow.run.started", "detail": "Start"}]

    result = projector.background_failed(
        {"run_id": "workflow_run", "run_group_id": "run_group"},
        timeline=timeline,
        error=RuntimeError("background failed"),
        root_group=False,
    )

    assert timeline == [{"event": "workflow.run.started", "detail": "Start"}]
    assert engine.run_updates == [
        (
            "workflow_run",
            {
                "status": "failed",
                "result": "background failed",
                "timeline": [
                    {"event": "workflow.run.started", "detail": "Start"},
                    {
                        "event": "workflow.run.failed",
                        "detail": "background failed",
                        "status": "failed",
                    },
                ],
                "artifacts": [],
                "pending_approval": None,
            },
        )
    ]
    assert engine.events == [
        ("workflow_run", "workflow.run.failed", {"error": "background failed"})
    ]
    assert engine.group_updates == []
    assert result["status"] == "failed"


def test_workflow_continuation_uses_injected_traversal_callbacks() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "start", "type": "start", "data": {"label": "Injected Start"}},
        ]
    }
    path = list(workflow["nodes"])
    calls: list[str] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: calls.append("path") or list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda _workflow: calls.append("nodes") or {"start": path[0]},
        workflow_next_node_id=lambda _workflow, _node, _context: calls.append("next") or "",
        workflow_parallel_plan=lambda _workflow, _node: calls.append("parallel") or {},
        node_kind=lambda node: calls.append(f"kind:{node['id']}") or str(node["type"]),
    )

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Run injected traversal"},
        workflow,
        context="Initial context",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert result["result"] == "Initial context"
    assert calls == ["path", "nodes", "kind:start", "next"]
    assert engine.events == [
        (
            "workflow_run",
            "workflow.node.start",
            {
                "workflow_node_id": "start",
                "workflow_node_kind": "start",
                "workflow_node_label": "Injected Start",
                "status": "completed",
            },
        ),
        ("workflow_run", "workflow.run.completed", {"result": "Initial context"}),
    ]


class FakeWorkflowTraversalEngine:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def _timeline(self, event: str, detail: str, **payload: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **payload}

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.events.append((run_id, event_type, payload))

    def _update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        return {"run_id": run_id, **fields}
