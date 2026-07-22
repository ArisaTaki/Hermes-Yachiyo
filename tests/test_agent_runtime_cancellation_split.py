"""Tests for cancellation projections split out of the legacy agent runtime module."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import threading
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_cancellation import (
    RuntimeRunCancellationCoordinator,
    RuntimeRunCancellationService,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _record_event(events: list[Any], value: Any, event_type: str) -> dict[str, Any]:
    events.append(value)
    return {"event_type": event_type}


def test_runtime_cancellation_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowCancellationTarget is WorkflowCancellationTarget
    assert agent_runtime.RunCancellationProjection is RunCancellationProjection
    assert agent_runtime.RuntimeRunCancellationService is RuntimeRunCancellationService
    assert agent_runtime.RuntimeRunCancellationCoordinator is RuntimeRunCancellationCoordinator
    assert (
        agent_runtime.WorkflowCancellationProjectionCoordinator
        is WorkflowCancellationProjectionCoordinator
    )


@pytest.mark.parametrize(
    ("run_kind", "expected_event_type"),
    [
        ("agent_run", "agent.run.cancelled"),
        ("main_chat_run", "run.cancelled"),
    ],
)
def test_runtime_run_cancellation_service_cancels_plain_run(
    run_kind: str,
    expected_event_type: str,
) -> None:
    runs = {
        "run-agent": {
            "run_id": "run-agent",
            "kind": run_kind,
            "status": "running",
            "updated_at": "2026-07-16T00:00:00Z",
            "result": "",
            "timeline": [{"event": "run.started", "detail": "Run started"}],
        }
    }
    updates: list[dict[str, Any]] = []
    events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        expected_status = kwargs.pop("expected_status")
        expected_updated_at = kwargs.pop("expected_updated_at")
        updates.append(
            {
                "run_id": run_id,
                **kwargs,
                "expected_status": expected_status,
                "expected_updated_at": expected_updated_at,
            }
        )
        assert runs[run_id]["status"] == expected_status
        assert runs[run_id]["updated_at"] == expected_updated_at
        runs[run_id] = {
            **runs[run_id],
            **kwargs,
            "updated_at": "2026-07-16T00:00:01Z",
        }
        return runs[run_id]

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any]:
        return _record_event(
            events,
            (run_id, event_type, payload, fence),
            event_type,
        )

    service = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=append_run_event,
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
            "expected_status": "running",
            "expected_updated_at": "2026-07-16T00:00:00Z",
        }
    ]
    assert events == [
        (
            "run-agent",
            expected_event_type,
            {"kind": run_kind, "result": "Run cancelled", "status": "cancelled"},
            {
                "expected_status": "cancelled",
                "expected_updated_at": "2026-07-16T00:00:01Z",
            },
        )
    ]


def test_runtime_run_cancellation_service_records_pending_approval_cancelled_fact() -> None:
    runs = {
        "run-approval": {
            "run_id": "run-approval",
            "kind": "agent_run",
            "status": "approval_required",
            "result": "等待审批：terminal.run",
            "timeline": [{"event": "agent.tool.approval_required"}],
            "pending_approval": {
                "approval_id": "approval-cancel",
                "tool": "terminal.run",
                "input_preview": {"command": "npm test"},
                "requested_at": "2026-06-16T00:00:00Z",
            },
        }
    }
    events: list[tuple[str, str, dict[str, Any]]] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **kwargs}
        return runs[run_id]

    service = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=lambda run_id, event_type, payload, **_fence: _record_event(
            events,
            (run_id, event_type, payload),
            event_type,
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
        project_child_run_transition=lambda result: result,
        final_statuses={"completed", "failed", "cancelled"},
    )

    result = service.cancel_once("run-approval")

    assert result["status"] == "cancelled"
    assert result["pending_approval"] is None
    assert [event_type for _, event_type, _ in events] == [
        "approval.cancelled",
        "agent.run.cancelled",
    ]
    approval_payload = events[0][2]
    assert approval_payload["approval_id"] == "approval-cancel"
    assert approval_payload["tool"] == "terminal.run"
    assert approval_payload["input_preview"] == {"command": "npm test"}
    assert approval_payload["status"] == "cancelled"
    assert approval_payload["previous_status"] == "approval_required"
    assert approval_payload["reason"] == "Run cancelled"


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


def test_cancelled_child_retries_post_commit_parent_projection() -> None:
    run = {
        "run_id": "run-cancelled-child-retry",
        "kind": "agent_run",
        "status": "running",
        "updated_at": "version-1",
        "result": "",
        "timeline": [],
    }
    projection_attempts: list[str] = []
    events: list[str] = []

    def update_run(_run_id: str, **fields: Any) -> dict[str, Any]:
        fields.pop("expected_status")
        fields.pop("expected_updated_at")
        run.update(fields, updated_at="version-2")
        return dict(run)

    def project_child(result: dict[str, Any]) -> dict[str, Any]:
        projection_attempts.append(str(result.get("status") or ""))
        if len(projection_attempts) == 1:
            raise RuntimeError("parent projection temporarily unavailable")
        return {**result, "parent_projection_repaired": True}

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: dict(run),
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, _payload, **_fence: _record_event(
            events,
            event_type,
            event_type,
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: pytest.fail(
            "non-workflow child must not project a root Workflow Group"
        ),
        resume_parent_workflows_after_child_update=lambda *_args: pytest.fail(
            "agent child projection owns parent notification"
        ),
        project_child_run_transition=project_child,
        final_statuses={"completed", "failed", "cancelled"},
    )

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        service.cancel_once(run["run_id"])

    assert run["status"] == "cancelled"
    repaired = service.cancel_once(run["run_id"])

    assert repaired["status"] == "cancelled"
    assert repaired["parent_projection_repaired"] is True
    assert projection_attempts == ["cancelled", "cancelled"]
    assert events == ["agent.run.cancelled"]


def test_cancelled_root_workflow_retries_post_commit_parent_projection_without_events() -> None:
    run = {
        "run_id": "workflow-cancelled-root-retry",
        "run_group_id": "workflow-cancelled-group-retry",
        "kind": "workflow_run",
        "project_root_group": True,
        "status": "running",
        "updated_at": "version-1",
        "result": "",
        "timeline": [],
        "artifacts": [],
    }
    updates: list[str] = []
    events: list[str] = []
    group_projections: list[str] = []
    parent_projections: list[str] = []

    def update_run(_run_id: str, **fields: Any) -> dict[str, Any]:
        fields.pop("expected_status")
        fields.pop("expected_updated_at")
        updates.append(str(fields.get("status") or ""))
        run.update(fields, updated_at="version-2")
        return dict(run)

    class WorkflowCancellation:
        @staticmethod
        def project_cancelled_workflow_run(
            _run_id: str,
            _run: dict[str, Any],
            timeline: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            return timeline, [], "Workflow cancelled"

    def project_root(
        _source: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        group_projections.append(str(result.get("status") or ""))
        return dict(run)

    def project_parent(result: dict[str, Any]) -> None:
        parent_projections.append(str(result.get("status") or ""))
        if len(parent_projections) == 1:
            raise RuntimeError("parent projection temporarily unavailable")

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: dict(run),
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, _payload, **_fence: _record_event(
            events,
            event_type,
            event_type,
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=WorkflowCancellation(),
        workflow_run_is_group_root=lambda candidate: (
            candidate.get("project_root_group") is True
        ),
        project_cancelled_workflow_group_if_root=project_root,
        resume_parent_workflows_after_child_update=project_parent,
        project_child_run_transition=lambda _result: pytest.fail(
            "root Workflow cancellation must not use the child projection"
        ),
        final_statuses={"completed", "failed", "cancelled"},
    )

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        service.cancel_once(run["run_id"])

    assert run["status"] == "cancelled"
    repaired = service.cancel_once(run["run_id"])

    assert repaired["status"] == "cancelled"
    assert updates == ["cancelled"]
    assert events == ["workflow.run.cancelled"]
    assert group_projections == ["cancelled", "cancelled"]
    assert parent_projections == ["cancelled", "cancelled"]


def test_runtime_run_cancellation_cas_loss_returns_fresh_winner_without_side_effects() -> None:
    source = {
        "run_id": "run-race",
        "kind": "agent_run",
        "status": "running",
        "updated_at": "2026-07-16T00:00:00Z",
        "timeline": [],
    }
    winner = {
        **source,
        "status": "completed",
        "updated_at": "2026-07-16T00:00:01Z",
        "result": "completed by worker",
    }
    snapshots = iter((source, winner))
    update_attempts: list[dict[str, Any]] = []

    def update_run(run_id: str, **kwargs: Any) -> None:
        update_attempts.append({"run_id": run_id, **kwargs})
        return None

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: next(snapshots),
        update_run=update_run,
        append_run_event=lambda *_args, **_kwargs: pytest.fail(
            "CAS loser must not append cancellation events"
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: pytest.fail(
            "CAS loser must not inspect workflow group projection"
        ),
        project_cancelled_workflow_group_if_root=lambda *_args: pytest.fail(
            "CAS loser must not project workflow groups"
        ),
        resume_parent_workflows_after_child_update=lambda *_args: pytest.fail(
            "CAS loser must not resume workflow parents"
        ),
        project_child_run_transition=lambda _result: pytest.fail(
            "CAS loser must not project child transitions"
        ),
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda _run: pytest.fail(
            "CAS loser must not clean up the winner's resources"
        ),
    )

    result = service.cancel_once("run-race")

    assert result is winner
    assert len(update_attempts) == 1
    assert update_attempts[0]["expected_status"] == "running"
    assert update_attempts[0]["expected_updated_at"] == "2026-07-16T00:00:00Z"


def test_root_workflow_group_cas_loss_rolls_back_run_cancellation() -> None:
    stored_run = {
        "run_id": "workflow-root-race",
        "run_group_id": "workflow-group-race",
        "kind": "workflow_run",
        "status": "running",
        "updated_at": "run-version-1",
        "result": "",
        "timeline": [],
        "artifacts": [],
    }
    transaction_active = False
    group_projection_calls: list[str] = []
    stored_events: list[str] = []

    @contextmanager
    def transaction_scope():
        nonlocal transaction_active
        snapshot = deepcopy(stored_run)
        events_snapshot = list(stored_events)
        transaction_active = True
        try:
            yield
        except BaseException:
            stored_run.clear()
            stored_run.update(snapshot)
            stored_events[:] = events_snapshot
            raise
        finally:
            transaction_active = False

    def update_run(run_id: str, **fields: Any) -> dict[str, Any]:
        assert transaction_active is True
        assert run_id == stored_run["run_id"]
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "run-version-1"
        stored_run.update(fields)
        stored_run["updated_at"] = "run-version-2"
        return dict(stored_run)

    class WorkflowCancellation:
        @staticmethod
        def project_cancelled_workflow_run(
            _run_id: str,
            _run: dict[str, Any],
            timeline: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            return timeline, [], "Workflow cancelled"

    def lose_group_cas(
        _run: dict[str, Any],
        _result: dict[str, Any],
    ) -> None:
        assert transaction_active is True
        group_projection_calls.append("attempted")
        return None

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: dict(stored_run),
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, _payload, **_kwargs: _record_event(
            stored_events,
            event_type,
            event_type,
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=WorkflowCancellation(),
        workflow_run_is_group_root=lambda _run: transaction_active,
        project_cancelled_workflow_group_if_root=lose_group_cas,
        resume_parent_workflows_after_child_update=lambda _run: pytest.fail(
            "group CAS loser must not resume parents"
        ),
        project_child_run_transition=lambda _run: pytest.fail(
            "root group CAS loser must not project child transitions"
        ),
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda _run: pytest.fail(
            "rolled-back cancellation must not clean browser resources"
        ),
        transaction_scope=transaction_scope,
    )

    result = service.cancel_once(stored_run["run_id"])

    assert group_projection_calls == ["attempted"]
    assert result["status"] == "running"
    assert result["updated_at"] == "run-version-1"
    assert stored_run["status"] == "running"
    assert stored_events == []


def test_runtime_run_cancellation_closes_browser_target_once_after_durable_update() -> None:
    runs = {
        "run-browser": {
            "run_id": "run-browser",
            "kind": "agent_run",
            "status": "running",
            "result": "",
            "timeline": [],
        }
    }
    order: list[str] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **kwargs}
        order.append(f"updated:{runs[run_id]['status']}")
        return runs[run_id]

    service = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, _payload, **_kwargs: {
            "event_type": event_type
        },
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: {},
        resume_parent_workflows_after_child_update=lambda *_args: None,
        project_child_run_transition=lambda result: result,
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda _run: order.append(
            f"closed:{runs['run-browser']['status']}"
        ),
    )

    first = service.cancel_once("run-browser")
    second = service.cancel_once("run-browser")

    assert first["status"] == "cancelled"
    assert second["status"] == "cancelled"
    assert order == ["updated:cancelled", "closed:cancelled"]


def test_runtime_run_cancellation_cleanup_failure_preserves_durable_cancel() -> None:
    run = {
        "run_id": "run-browser",
        "kind": "agent_run",
        "status": "running",
        "result": "",
        "timeline": [],
    }
    events: list[str] = []

    def update_run(_run_id: str, **kwargs: Any) -> dict[str, Any]:
        run.update(kwargs)
        return run

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: run,
        update_run=update_run,
        append_run_event=lambda _run_id, event_type, _payload, **_fence: _record_event(
            events,
            event_type,
            event_type,
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: {},
        resume_parent_workflows_after_child_update=lambda *_args: None,
        project_child_run_transition=lambda result: result,
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda _run: (_ for _ in ()).throw(
            RuntimeError("CDP unavailable")
        ),
    )

    result = service.cancel_once("run-browser")

    assert result["status"] == "cancelled"
    assert events == ["agent.run.cancelled"]


def test_cancellation_rolls_back_row_and_events_when_second_event_fails() -> None:
    run = {
        "run_id": "run-cancel-atomic",
        "kind": "agent_run",
        "status": "approval_required",
        "updated_at": "version-1",
        "result": "waiting",
        "timeline": [],
        "pending_approval": {
            "approval_id": "approval-1",
            "tool": "terminal.run",
        },
    }
    events: list[str] = []

    @contextmanager
    def transaction_scope():
        run_snapshot = deepcopy(run)
        events_snapshot = list(events)
        try:
            yield
        except BaseException:
            run.clear()
            run.update(run_snapshot)
            events[:] = events_snapshot
            raise

    def update_run(_run_id: str, **fields: Any) -> dict[str, Any] | None:
        if run["status"] != fields.pop("expected_status"):
            return None
        if run["updated_at"] != fields.pop("expected_updated_at"):
            return None
        run.update(fields)
        run["updated_at"] = "version-2"
        return dict(run)

    def append_run_event(
        _run_id: str,
        event_type: str,
        _payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        assert fence == {
            "expected_status": "cancelled",
            "expected_updated_at": "version-2",
        }
        events.append(event_type)
        if len(events) == 2:
            return None
        return {"event_type": event_type}

    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: dict(run),
        update_run=update_run,
        append_run_event=append_run_event,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: {},
        resume_parent_workflows_after_child_update=lambda *_args: pytest.fail(
            "rolled-back cancellation must not resume parents"
        ),
        project_child_run_transition=lambda _result: pytest.fail(
            "rolled-back cancellation must not project child state"
        ),
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda _run: pytest.fail(
            "rolled-back cancellation must not clean up resources"
        ),
        transaction_scope=transaction_scope,
    )

    with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
        service.cancel_once(run["run_id"])

    assert run["status"] == "approval_required"
    assert run["updated_at"] == "version-1"
    assert run["pending_approval"]["approval_id"] == "approval-1"
    assert events == []


def test_runtime_run_cancellation_does_not_cleanup_before_update_succeeds() -> None:
    cleanup_calls: list[str] = []
    run = {
        "run_id": "run-browser",
        "kind": "agent_run",
        "status": "running",
        "timeline": [],
    }
    service = RuntimeRunCancellationService(
        get_run=lambda _run_id: run,
        update_run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("write failed")
        ),
        append_run_event=lambda *_args, **_kwargs: None,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: {},
        resume_parent_workflows_after_child_update=lambda *_args: None,
        project_child_run_transition=lambda result: result,
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda current: cleanup_calls.append(
            str(current["run_id"])
        ),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        service.cancel_once("run-browser")

    assert cleanup_calls == []


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
        append_run_event=lambda run_id, event_type, payload, **_fence: _record_event(
            events,
            (run_id, event_type, payload),
            event_type,
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


def test_workflow_cancellation_records_child_pending_approval_cancelled_fact() -> None:
    runs = {
        "child-run": {
            "run_id": "child-run",
            "kind": "agent_run",
            "status": "approval_required",
            "result": "等待审批：terminal.run",
            "timeline": [{"event": "agent.tool.approval_required"}],
            "pending_approval": {
                "approval_id": "approval-child-cancel",
                "tool": "terminal.run",
                "input_preview": {"command": "npm test"},
            },
        }
    }
    parent_timeline = [
        {
            "event": "workflow.node.agent",
            "detail": "Build",
            "workflow_node_id": "build",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Build",
            "child_run_id": "child-run",
        },
        {
            "event": "workflow.run.approval_required",
            "child_run_id": "child-run",
        },
    ]
    events: list[tuple[str, str, dict[str, Any]]] = []
    merged_children: list[tuple[str, str]] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **kwargs}
        return runs[run_id]

    coordinator = WorkflowCancellationProjectionCoordinator(
        pending_approval_private=lambda _run_id: None,
        get_run=lambda run_id: runs[run_id],
        merge_workflow_child_run_outcome=lambda timeline, _artifacts, child, label: (
            merged_children.append((child["run_id"], label)),
            timeline.append({"event": "workflow.child.merged", "child_run_id": child["run_id"]}),
        ),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
    )

    timeline, artifacts, result_text = coordinator.project_cancelled_workflow_run(
        "parent-run",
        {"run_id": "parent-run", "artifacts": []},
        parent_timeline,
    )

    assert result_text == "Workflow 已取消：Build"
    assert artifacts == []
    assert timeline[-1]["event"] == "workflow.run.cancelled"
    assert runs["child-run"]["status"] == "cancelled"
    assert runs["child-run"]["pending_approval"] is None
    assert [event_type for _, event_type, _ in events] == [
        "approval.cancelled",
        "run.cancelled",
    ]
    assert events[0][0] == "child-run"
    assert events[0][2]["approval_id"] == "approval-child-cancel"
    assert events[0][2]["parent_run_id"] == "parent-run"
    assert events[0][2]["previous_status"] == "approval_required"
    assert merged_children == [("child-run", "Build")]


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


def _insert_native_root_agent_run(
    service: AgentRuntimeService,
) -> tuple[dict[str, Any], dict[str, Any]]:
    group = service._insert_run_group(title="Atomic cancellation", source="agent")
    run = service._insert_run(
        kind="agent_run",
        runnable_id="agent-cancel-atomic",
        user_goal="cancel atomically",
        run_group_id=group["run_group_id"],
        project_root_group=True,
    )
    running = service._update_run(run["run_id"], status="running")
    assert running is not None
    return running, service.get_run_group(group["run_group_id"])


def _insert_native_root_workflow_run(
    service: AgentRuntimeService,
    *,
    kind: str = "workflow_run",
) -> tuple[dict[str, Any], dict[str, Any]]:
    group = service._insert_run_group(
        title="Atomic workflow cancellation",
        source="workflow",
    )
    run = service._insert_run(
        kind=kind,
        runnable_id="workflow-cancel-atomic",
        user_goal="cancel workflow atomically",
        run_group_id=group["run_group_id"],
    )
    running = service._update_run(run["run_id"], status="running")
    assert running is not None
    return running, service.get_run_group(group["run_group_id"])


def test_native_root_workflow_cancellation_orders_terminal_facts_after_run_cas(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "workflow-cancel-ordering.db",
        workspace_dir=tmp_path / "workflow-cancel-ordering",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_workflow_run(service)

        first = service.cancel_run(run["run_id"])
        first_group = service.get_run_group(group["run_group_id"])
        first_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        assert first["status"] == "cancelled"
        assert first_group["status"] == "cancelled"
        assert first_group["summary"] == first["result"]
        event_types = [event["event_type"] for event in first_events]
        assert event_types.index("workflow.run.cancelled") < event_types.index(
            "workflow.cancelled"
        ) < event_types.index("group.run.cancelled")
        group_event = next(
            event for event in first_events if event["event_type"] == "group.run.cancelled"
        )
        assert group_event["payload"] == {
            "child_run_ids": first_group["child_run_ids"],
            "group_run_id": first_group["run_group_id"],
            "objective": first["result"],
            "participant_count": len(first_group["child_run_ids"]),
            "run_group_id": first_group["run_group_id"],
            "source": first_group["source"],
            "status": first_group["status"],
            "summary": first_group["summary"],
            "title": first_group["title"],
        }

        second = service.cancel_run(run["run_id"])
        assert second == first
        assert service.get_run_group(group["run_group_id"]) == first_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == first_events
    finally:
        service.close()


@pytest.mark.parametrize("run_kind", ["workflow", "workflow-run"])
def test_native_workflow_cancellation_accepts_kind_aliases_but_emits_canonical_fact(
    tmp_path,
    run_kind: str,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / f"workflow-cancel-{run_kind}.db",
        workspace_dir=tmp_path / f"workflow-cancel-{run_kind}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_workflow_run(service, kind=run_kind)

        cancelled = service.cancel_run(run["run_id"])
        events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        assert cancelled["status"] == "cancelled"
        assert service.get_run_group(group["run_group_id"])["status"] == "cancelled"
        canonical = next(
            event for event in events if event["event_type"] == "workflow.run.cancelled"
        )
        assert canonical["payload"]["kind"] == "workflow_run"
        assert any(event["event_type"] == "workflow.cancelled" for event in events)
        assert any(event["event_type"] == "group.run.cancelled" for event in events)
    finally:
        service.close()


@pytest.mark.parametrize("fault", ["run_event", "group_event", "group_cas"])
def test_native_root_workflow_cancellation_fault_rolls_back_whole_terminal_uow(
    tmp_path,
    monkeypatch,
    fault: str,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / f"workflow-cancel-fault-{fault}.db",
        workspace_dir=tmp_path / f"workflow-cancel-fault-{fault}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_workflow_run(service)
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        if fault in {"run_event", "group_event"}:
            original_append = service.append_run_event
            failed_event_type = (
                "workflow.run.cancelled"
                if fault == "run_event"
                else "group.run.cancelled"
            )

            def fail_terminal_event(
                run_id: str,
                event_type: str,
                payload: dict[str, Any],
                **kwargs: Any,
            ) -> Any:
                if event_type == failed_event_type:
                    return None
                return original_append(run_id, event_type, payload, **kwargs)

            monkeypatch.setattr(service, "append_run_event", fail_terminal_event)
            expected_error = (
                "run_event_fence_mismatch"
                if fault == "run_event"
                else "run_group_event_fence_mismatch"
            )
        else:
            monkeypatch.setattr(
                service.run_transition_projection,
                "_update_run_group",
                lambda _run_group_id, **_kwargs: None,
            )
            expected_error = "run_group_projection_cas_lost"

        with pytest.raises(AgentRuntimeError, match=expected_error):
            service.cancel_run(run["run_id"])

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_root_workflow_cancellation_cross_connection_cas_loser_is_clean(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "workflow-cancel-cross-connection.db"
    service_a = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=tmp_path / "workflow-cancel-cross-connection-a",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    service_b = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=tmp_path / "workflow-cancel-cross-connection-b",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_workflow_run(service_a)
        original_get = service_a.run_cancellation._get_run
        winner: dict[str, Any] = {}
        first_read = True

        def stale_read_then_other_connection_wins(run_id: str) -> dict[str, Any]:
            nonlocal first_read
            snapshot = original_get(run_id)
            if first_read:
                first_read = False
                winner.update(service_b.cancel_run(run_id))
            return snapshot

        monkeypatch.setattr(
            service_a.run_cancellation,
            "_get_run",
            stale_read_then_other_connection_wins,
        )

        result = service_a.cancel_run(run["run_id"])
        winner_group = service_b.get_run_group(group["run_group_id"])
        winner_events = service_b.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        assert result == winner
        assert result["status"] == "cancelled"
        assert winner_group["status"] == "cancelled"
        assert [
            event["event_type"] for event in winner_events
        ].count("workflow.run.cancelled") == 1
        assert [
            event["event_type"] for event in winner_events
        ].count("group.run.cancelled") == 1
        assert service_a.get_run_group(group["run_group_id"]) == winner_group
        assert service_a.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == winner_events
    finally:
        service_b.close()
        service_a.close()


def test_native_root_workflow_cancellation_rejects_different_group_terminal_winner(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "workflow-cancel-group-winner.db",
        workspace_dir=tmp_path / "workflow-cancel-group-winner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_workflow_run(service)
        completed_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="another terminal writer won",
        )
        assert completed_group is not None
        before_run = service.get_run(run["run_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            service.cancel_run(run["run_id"])

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == completed_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_root_agent_cancellation_commits_group_and_terminal_facts_together(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_agent_run(service)

        first = service.cancel_run(run["run_id"])
        first_group = service.get_run_group(group["run_group_id"])
        first_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        assert first["status"] == "cancelled"
        assert first_group["status"] == "cancelled"
        assert first_group["summary"] == first["result"]
        event_types = [event["event_type"] for event in first_events]
        assert "agent.run.cancelled" in event_types
        assert "run.cancelled" in event_types
        assert "group.run.cancelled" in event_types
        assert event_types.index("agent.run.cancelled") < event_types.index(
            "run.cancelled"
        ) < event_types.index("group.run.cancelled")

        # A repeated request observes the committed winner without duplicating
        # either the group terminal row or its canonical facts.
        second = service.cancel_run(run["run_id"])
        assert second == first
        assert service.get_run_group(group["run_group_id"]) == first_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == first_events
    finally:
        service.close()


@pytest.mark.parametrize("fault", ["group_event", "group_cas"])
def test_native_root_agent_cancellation_group_fault_rolls_back_every_terminal_fact(
    tmp_path,
    monkeypatch,
    fault: str,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-{fault}.db",
        workspace_dir=tmp_path / f"runtime-{fault}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_agent_run(service)
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        if fault == "group_event":
            original_append = service.append_run_event

            def fail_group_event(
                run_id: str,
                event_type: str,
                payload: dict[str, Any],
                **kwargs: Any,
            ) -> Any:
                if event_type == "group.run.cancelled":
                    return None
                return original_append(run_id, event_type, payload, **kwargs)

            monkeypatch.setattr(service, "append_run_event", fail_group_event)
            expected_error = "run_group_event_fence_mismatch"
        else:
            monkeypatch.setattr(
                service.agent_run_group_projection,
                "_update_run_group",
                lambda _run_group_id, **_kwargs: None,
            )
            expected_error = "run_group_projection_cas_lost"

        with pytest.raises(AgentRuntimeError, match=expected_error):
            service.cancel_run(run["run_id"])

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_root_agent_cancellation_run_cas_loser_writes_no_group_or_events(
    tmp_path,
    monkeypatch,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-cas-loser.db",
        workspace_dir=tmp_path / "runtime-cas-loser",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_agent_run(service)
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        group_calls: list[str] = []
        monkeypatch.setattr(
            service.run_cancellation,
            "_update_run",
            lambda _run_id, **_kwargs: None,
        )
        monkeypatch.setattr(
            service.run_cancellation,
            "_project_agent_run_group_if_root",
            lambda _run: group_calls.append("projected"),
        )

        result = service.cancel_run(run["run_id"])

        assert result == before_run
        assert group_calls == []
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_root_agent_cancellation_rejects_different_terminal_group_winner(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-group-winner.db",
        workspace_dir=tmp_path / "runtime-group-winner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run, group = _insert_native_root_agent_run(service)
        completed_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="another terminal writer won",
        )
        assert completed_group is not None
        before_run = service.get_run(run["run_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            service.cancel_run(run["run_id"])

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == completed_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_nested_workflow_cancellation_projects_group_only_for_persisted_owner(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "workflow-cancel-owner.db",
        workspace_dir=tmp_path / "workflow-cancel-owner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Nested workflow", source="workflow")
        parent = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-parent",
            user_goal="own cancellation",
            run_group_id=group["run_group_id"],
        )
        child = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-child",
            user_goal="share cancellation",
            run_group_id=group["run_group_id"],
        )
        parent = service._update_run(parent["run_id"], status="running")
        child = service._update_run(child["run_id"], status="running")
        assert parent is not None and child is not None
        before_group = service.get_run_group(group["run_group_id"])

        cancelled_child = service.cancel_run(child["run_id"])

        assert cancelled_child["status"] == "cancelled"
        assert service.get_run_group(group["run_group_id"]) == before_group
        child_event_types = [
            event["event_type"]
            for event in service.list_run_events(
                child["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert "workflow.run.cancelled" in child_event_types
        assert "group.run.cancelled" not in child_event_types

        cancelled_parent = service.cancel_run(parent["run_id"])

        assert cancelled_parent["status"] == "cancelled"
        assert service.get_run_group(group["run_group_id"])["status"] == "cancelled"
        parent_event_types = [
            event["event_type"]
            for event in service.list_run_events(
                parent["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert "group.run.cancelled" in parent_event_types
    finally:
        service.close()
