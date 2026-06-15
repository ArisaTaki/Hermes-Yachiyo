"""Tests for cancellation projections split out of the legacy agent runtime module."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)
from apps.shell.agent.runtime.run_cancellation import (
    RuntimeRunCancellationCoordinator,
    RuntimeRunCancellationService,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_cancellation_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowCancellationTarget is WorkflowCancellationTarget
    assert agent_runtime.RunCancellationProjection is RunCancellationProjection
    assert agent_runtime.RuntimeRunCancellationService is RuntimeRunCancellationService
    assert agent_runtime.RuntimeRunCancellationCoordinator is RuntimeRunCancellationCoordinator
    assert (
        agent_runtime.WorkflowCancellationProjectionCoordinator
        is WorkflowCancellationProjectionCoordinator
    )


def test_runtime_run_cancellation_service_cancels_plain_run() -> None:
    runs = {
        "run-agent": {
            "run_id": "run-agent",
            "kind": "agent_run",
            "status": "running",
            "result": "",
            "timeline": [{"event": "run.started", "detail": "Run started"}],
        }
    }
    updates: list[dict[str, Any]] = []
    events: list[tuple[str, str, dict[str, Any]]] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        updates.append({"run_id": run_id, **kwargs})
        runs[run_id] = {**runs[run_id], **kwargs}
        return runs[run_id]

    service = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: pytest.fail(
            "plain run cancellation should not project workflow groups"
        ),
        resume_parent_workflows_after_child_update=lambda *_args: pytest.fail(
            "plain run cancellation should not resume workflow parents"
        ),
        project_child_run_transition=lambda result: {"projected_child": result},
        final_statuses={"completed", "failed", "cancelled"},
    )

    result = service.cancel_once("run-agent")

    assert result == {"projected_child": runs["run-agent"]}
    assert updates == [
        {
            "run_id": "run-agent",
            "status": "cancelled",
            "result": "Run cancelled",
            "timeline": [
                {"event": "run.started", "detail": "Run started"},
                {"event": "run.cancelled", "detail": "Run cancelled"},
            ],
            "artifacts": None,
            "pending_approval": None,
        }
    ]
    assert events == [
        (
            "run-agent",
            "run.cancelled",
            {"kind": "agent_run", "result": "Run cancelled", "status": "cancelled"},
        )
    ]


def test_runtime_run_cancellation_service_returns_terminal_run_without_events() -> None:
    run = {
        "run_id": "run-done",
        "kind": "agent_run",
        "status": "completed",
        "timeline": [],
    }
    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: run,
        update_run=lambda *_args, **_kwargs: pytest.fail(
            "terminal run cancellation should not update"
        ),
        append_run_event=lambda *_args, **_kwargs: pytest.fail(
            "terminal run cancellation should not append events"
        ),
        timeline_factory=lambda *_args, **_kwargs: {},
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: pytest.fail(
            "terminal run cancellation should not project workflow groups"
        ),
        resume_parent_workflows_after_child_update=lambda *_args: pytest.fail(
            "terminal run cancellation should not resume parents"
        ),
        project_child_run_transition=lambda _result: pytest.fail(
            "terminal run cancellation should not project child transitions"
        ),
        final_statuses={"completed", "failed", "cancelled"},
    )

    assert service.cancel_once("run-done") is run


def test_runtime_run_cancellation_service_cancels_workflow_root_and_resumes_parents() -> None:
    class FakeWorkflowCancellation:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def project_cancelled_workflow_run(
            self,
            run_id: str,
            run: dict[str, Any],
            timeline: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            self.calls.append({"run_id": run_id, "run": run, "timeline": timeline})
            timeline.append(
                {
                    "event": "workflow.run.cancelled",
                    "detail": "Human Gate cancelled",
                    "status": "cancelled",
                }
            )
            return (
                timeline,
                [{"kind": "workflow_child_artifact"}],
                "Workflow 已取消：Human Gate",
            )

    workflow_cancellation = FakeWorkflowCancellation()
    runs = {
        "run-workflow": {
            "run_id": "run-workflow",
            "kind": "workflow_run",
            "status": "approval_required",
            "result": "",
            "timeline": [{"event": "workflow.approval.required"}],
            "artifacts": [],
        }
    }
    projected_groups: list[tuple[dict[str, Any], dict[str, Any]]] = []
    resumed_parents: list[dict[str, Any]] = []
    events: list[tuple[str, str, dict[str, Any]]] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **kwargs}
        return runs[run_id]

    def project_group(run: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        projected_groups.append((run, result))
        return {**result, "group_projected": True}

    service = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=workflow_cancellation,
        workflow_run_is_group_root=lambda _run: True,
        project_cancelled_workflow_group_if_root=project_group,
        resume_parent_workflows_after_child_update=lambda projected: resumed_parents.append(
            projected
        ),
        project_child_run_transition=lambda _result: pytest.fail(
            "workflow root cancellation should return group projection"
        ),
        final_statuses={"completed", "failed", "cancelled"},
    )

    result = service.cancel_once("run-workflow")

    assert result == {**runs["run-workflow"], "group_projected": True}
    assert workflow_cancellation.calls[0]["run_id"] == "run-workflow"
    assert runs["run-workflow"]["status"] == "cancelled"
    assert runs["run-workflow"]["result"] == "Workflow 已取消：Human Gate"
    assert runs["run-workflow"]["artifacts"] == [{"kind": "workflow_child_artifact"}]
    assert events == [
        (
            "run-workflow",
            "workflow.run.cancelled",
            {
                "kind": "workflow_run",
                "result": "Workflow 已取消：Human Gate",
                "status": "cancelled",
            },
        )
    ]
    assert projected_groups == [
        (workflow_cancellation.calls[0]["run"], runs["run-workflow"])
    ]
    assert resumed_parents == [result]


def test_run_cancellation_coordinator_serializes_and_cleans_locks() -> None:
    calls: list[str] = []
    locks: dict[str, threading.RLock] = {}
    coordinator = RuntimeRunCancellationCoordinator(
        cancel_once=lambda run_id: calls.append(run_id) or {"run_id": run_id, "status": "cancelled"},
        run_cancel_locks=locks,
        run_cancel_locks_guard=threading.RLock(),
    )

    result = coordinator.cancel(" run-1 ")

    assert result == {"run_id": "run-1", "status": "cancelled"}
    assert calls == ["run-1"]
    assert locks == {}


def test_native_runtime_installs_run_cancellation_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.run_cancellation, RuntimeRunCancellationService)
        assert isinstance(service.run_cancellation_coordinator, RuntimeRunCancellationCoordinator)
        assert service.run_cancellation_coordinator._cancel_once.__self__ is service.run_cancellation
    finally:
        service.close()
