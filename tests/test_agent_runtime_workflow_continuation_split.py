"""Tests for workflow continuation coordinator split out of the legacy runtime."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.clock import iso_epoch
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_continuation import (
    WorkflowContinuationCoordinator,
    WorkflowContinuationPortBundle,
)
from apps.shell.agent.runtime.workflow_ports import (
    WorkflowContinuationPortBundle as WorkflowContinuationPortBundleContract,
)
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowContinuationFailureProjection,
    WorkflowRunCompletionProjection,
)
from apps.shell.agent.runtime.workflow_run_outcomes import WorkflowRunOutcomeProjector
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_workflow_continuation_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowContinuationCoordinator is WorkflowContinuationCoordinator
    assert agent_runtime.WorkflowContinuationPortBundle is WorkflowContinuationPortBundle
    assert WorkflowContinuationPortBundle is WorkflowContinuationPortBundleContract
    assert agent_runtime.WorkflowRunOutcomeProjector is WorkflowRunOutcomeProjector
    assert WorkflowContinuationCoordinator(object())._iso_epoch is iso_epoch


def test_workflow_event_wrappers_distinguish_legacy_none_from_fenced_cas_loss() -> None:
    legacy_calls: list[tuple[str, str]] = []
    fenced_calls: list[tuple[str, str, str, str]] = []

    def legacy_append(run_id: str, event_type: str, _payload: dict[str, Any]) -> None:
        legacy_calls.append((run_id, event_type))
        return None

    def fenced_append(
        run_id: str,
        event_type: str,
        _payload: dict[str, Any],
        *,
        expected_status: str | None = None,
        expected_updated_at: str | None = None,
    ) -> None:
        fenced_calls.append(
            (
                run_id,
                event_type,
                str(expected_status or ""),
                str(expected_updated_at or ""),
            )
        )
        return None

    legacy_continuation = WorkflowContinuationCoordinator(
        object(),
        append_run_event=legacy_append,
    )
    fenced_continuation = WorkflowContinuationCoordinator(
        object(),
        append_run_event=fenced_append,
    )
    legacy_outcomes = WorkflowRunOutcomeProjector(
        object(),
        append_run_event=legacy_append,
    )
    fenced_outcomes = WorkflowRunOutcomeProjector(
        object(),
        append_run_event=fenced_append,
    )
    kwargs = {
        "expected_status": "running",
        "expected_updated_at": "run-version-1",
    }

    assert legacy_continuation._append_run_event(
        "run-legacy-continuation",
        "workflow.run.resumed",
        {},
        **kwargs,
    ) is True
    assert fenced_continuation._append_run_event(
        "run-fenced-continuation",
        "workflow.run.resumed",
        {},
        **kwargs,
    ) is None
    assert legacy_outcomes._append_run_event(
        "run-legacy-outcome",
        "workflow.run.completed",
        {},
        **kwargs,
    ) is True
    assert fenced_outcomes._append_run_event(
        "run-fenced-outcome",
        "workflow.run.completed",
        {},
        **kwargs,
    ) is None
    assert len(legacy_calls) == 2
    assert fenced_calls == [
        (
            "run-fenced-continuation",
            "workflow.run.resumed",
            "running",
            "run-version-1",
        ),
        (
            "run-fenced-outcome",
            "workflow.run.completed",
            "running",
            "run-version-1",
        ),
    ]


def test_continuation_terminal_winner_blocks_late_child_approval_projection() -> None:
    current = {
        "run_id": "workflow-continuation-race",
        "run_group_id": "workflow-group-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }
    events: list[tuple[str, str, dict[str, Any]]] = []
    group_updates: list[tuple[str, dict[str, Any]]] = []

    def update_run(_run_id: str, **fields: Any):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert fields["expected_pending_approval_absent"] is True
        current.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    coordinator = WorkflowContinuationCoordinator(
        object(),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(current),
    )
    execution = SimpleNamespace(
        status="approval_required",
        next_context="waiting for child approval",
        status_event_payload=lambda: {
            "child_run_id": "workflow-child-race",
            "status": "approval_required",
        },
    )
    timeline: list[dict[str, Any]] = []

    outcome = coordinator._apply_child_execution_status(
        dict(current),
        execution,
        label="Desktop child",
        run_group_id="workflow-group-race",
        timeline=timeline,
        artifacts=[],
        root_group=True,
    )

    assert outcome["done"] is True
    assert outcome["run"]["status"] == "cancelled"
    assert outcome["run"]["result"] == "cancelled by user"
    assert timeline == []
    assert events == []
    assert group_updates == []


def _workflow_child_approval_execution() -> SimpleNamespace:
    return SimpleNamespace(
        status="approval_required",
        next_context="waiting for child approval",
        status_event_payload=lambda: {
            "child_run_id": "workflow-child-approval",
            "status": "approval_required",
            "workflow_node_id": "child-node",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Desktop child",
        },
    )


def _native_workflow_continuation_run(
    tmp_path,
    *,
    project_root_group: bool,
    group_id: str = "",
):
    service = AgentRuntimeService(
        db_path=tmp_path / "workflow-child-approval.db",
        workspace_dir=tmp_path / "workflow-child-approval-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    if group_id:
        group = service.get_run_group(group_id)
    else:
        group = service._insert_run_group(
            title="Workflow child approval",
            source="workflow",
        )
    run = service._insert_run(
        kind="workflow_run",
        runnable_id="workflow-child-approval",
        user_goal="wait for child approval",
        run_group_id=group["run_group_id"],
        project_root_group=project_root_group,
    )
    run = service._update_run(
        run["run_id"],
        status="running",
        timeline=[],
        artifacts=[],
        pending_approval=None,
    )
    assert run is not None
    return service, run, group


def test_native_child_approval_projection_rolls_back_on_workflow_alias_fault(
    tmp_path,
) -> None:
    service, run, group = _native_workflow_continuation_run(
        tmp_path,
        project_root_group=True,
    )
    try:
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        timeline: list[dict[str, Any]] = []
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "workflow.paused_for_approval":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_alias

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.workflow_continuation._apply_child_execution_status(
                run,
                _workflow_child_approval_execution(),
                label="Desktop child",
                run_group_id=group["run_group_id"],
                timeline=timeline,
                artifacts=[],
                root_group=True,
            )

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == []
    finally:
        service.close()


def test_nested_workflow_child_approval_cannot_project_owned_group_from_stale_hint(
    tmp_path,
) -> None:
    service, owner, group = _native_workflow_continuation_run(
        tmp_path,
        project_root_group=True,
    )
    try:
        nested = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-nested-child-approval",
            user_goal="nested wait",
            run_group_id=group["run_group_id"],
            project_root_group=False,
        )
        nested = service._update_run(
            nested["run_id"],
            status="running",
            timeline=[],
            artifacts=[],
            pending_approval=None,
        )
        assert nested is not None
        before_group = service.get_run_group(group["run_group_id"])

        outcome = service.workflow_continuation._apply_child_execution_status(
            nested,
            _workflow_child_approval_execution(),
            label="Desktop child",
            run_group_id=group["run_group_id"],
            timeline=[],
            artifacts=[],
            root_group=True,
        )

        assert outcome["done"] is True
        assert outcome["run"]["status"] == "approval_required"
        assert service.get_run_group(group["run_group_id"]) == before_group
        event_types = {
            event["event_type"]
            for event in service.list_run_events(
                nested["run_id"],
                include_internal=True,
            )["events"]
        }
        assert "group.run.approval_required" not in event_types
        assert owner["project_root_group"] is True
    finally:
        service.close()


def test_child_approval_projection_rolls_back_on_terminal_group_conflict(tmp_path) -> None:
    service, run, group = _native_workflow_continuation_run(
        tmp_path,
        project_root_group=True,
    )
    try:
        winner_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner",
        )
        assert winner_group is not None
        before_run = service.get_run(run["run_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        timeline: list[dict[str, Any]] = []

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            service.workflow_continuation._apply_child_execution_status(
                run,
                _workflow_child_approval_execution(),
                label="Desktop child",
                run_group_id=group["run_group_id"],
                timeline=timeline,
                artifacts=[],
                root_group=True,
            )

        assert service.get_run(run["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == winner_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == []
    finally:
        service.close()


def test_next_approval_node_event_fault_does_not_convert_atomic_pause_to_failure(
    tmp_path,
) -> None:
    service, run, group = _native_workflow_continuation_run(
        tmp_path,
        project_root_group=True,
    )
    try:
        workflow = {
            "workflow_id": "workflow-next-approval",
            "name": "Next approval",
            "nodes": [
                {"id": "start", "type": "start", "data": {"label": "Start"}},
                {
                    "id": "gate",
                    "type": "approval",
                    "data": {"label": "Human Gate", "criteria": "Review"},
                }
            ],
            "edges": [{"source": "start", "target": "gate"}],
        }
        before_run = service.get_run(run["run_id"])
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        timeline: list[dict[str, Any]] = []
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "workflow.paused_for_approval":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_alias

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.workflow_continuation.continue_run(
                run,
                workflow,
                context="draft ready",
                timeline=timeline,
                artifacts=[],
                start_index=1,
                root_group=True,
            )

        after_run = service.get_run(run["run_id"])
        for field in ("status", "result", "timeline", "artifacts", "pending_approval"):
            assert after_run[field] == before_run[field]
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == []
    finally:
        service.close()


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


def test_workflow_run_outcome_projector_accepts_side_effect_ports() -> None:
    timeline_events: list[dict[str, Any]] = []
    appended_events: list[tuple[str, str, dict[str, Any]]] = []
    run_updates: list[tuple[str, dict[str, Any]]] = []
    group_updates: list[tuple[str, dict[str, Any]]] = []
    get_calls: list[str] = []
    projector = WorkflowRunOutcomeProjector(
        object(),
        timeline_factory=lambda event, detail="", **payload: timeline_events.append(
            {"event": event, "detail": detail, **payload}
        )
        or timeline_events[-1],
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=lambda run_id, **fields: run_updates.append((run_id, fields))
        or {"run_id": run_id, "run_group_id": "run_group", **fields},
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda run_id: get_calls.append(run_id)
        or {
            "run_id": run_id,
            "run_group_id": "run_group",
            **run_updates[-1][1],
            "refetched": True,
        },
    )
    timeline: list[dict[str, Any]] = []
    artifacts = [{"kind": "workflow_artifact", "path": "report.md"}]

    result = projector.completed(
        {"run_id": "workflow_run", "run_group_id": "run_group"},
        WorkflowRunCompletionProjection("Workflow result"),
        timeline=timeline,
        artifacts=artifacts,
        root_group=True,
    )

    assert result["refetched"] is True
    assert timeline == timeline_events
    assert appended_events == [
        ("workflow_run", "workflow.run.completed", {"result": "Workflow result"})
    ]
    assert run_updates == [
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
    assert group_updates == [
        ("run_group", {"status": "completed", "summary": "Workflow result"})
    ]
    assert get_calls == ["workflow_run"]


@pytest.mark.parametrize(
    "failed_event_type",
    ("workflow.completed", "group.run.completed"),
)
def test_native_workflow_terminal_projection_rolls_back_row_group_and_events(
    tmp_path,
    failed_event_type: str,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(
            title="Atomic workflow",
            source="workflow",
        )
        created = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-atomic",
            user_goal="prove workflow terminal atomicity",
            run_group_id=group["run_group_id"],
        )
        service._append_run_to_group(group["run_group_id"], created["run_id"])
        running = service._update_run(created["run_id"], status="running")
        before_group = service.get_run_group(group["run_group_id"])
        before_events = service.list_run_events(created["run_id"])["events"]
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_terminal_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == failed_event_type:
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_terminal_event
        timeline = list(running.get("timeline") or [])

        with pytest.raises(
            AgentRuntimeError,
            match="run_(event|group_event)_fence_mismatch",
        ):
            service.workflow_continuation._outcomes.completed(
                running,
                WorkflowRunCompletionProjection("Workflow result"),
                timeline=timeline,
                artifacts=[],
                root_group=True,
                expected_updated_at=str(running.get("updated_at") or ""),
            )

        restored = service.get_run(created["run_id"])
        assert restored["status"] == "running"
        assert restored.get("result") in {None, ""}
        assert service.get_run_group(group["run_group_id"]) == before_group
        assert service.list_run_events(created["run_id"])["events"] == before_events
        assert timeline == list(running.get("timeline") or [])
    finally:
        service.close()


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_native_workflow_terminal_outcome_cannot_overwrite_cancelled_group_winner(
    tmp_path,
    outcome: str,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-{outcome}.db",
        workspace_dir=tmp_path / f"runtime-{outcome}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(
            title="Cancelled workflow winner",
            source="workflow",
        )
        created = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-terminal-winner",
            user_goal="preserve cancellation",
            run_group_id=group["run_group_id"],
        )
        running = service._update_run(created["run_id"], status="running")
        assert running is not None
        cancelled_group = service._update_run_group(
            group["run_group_id"],
            status="cancelled",
            summary="cancelled by user",
        )
        assert cancelled_group is not None
        before_run = service.get_run(created["run_id"])
        before_events = service.list_run_events(
            created["run_id"],
            include_internal=True,
        )["events"]
        timeline = list(running.get("timeline") or [])

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            if outcome == "completed":
                service.workflow_continuation._outcomes.completed(
                    running,
                    WorkflowRunCompletionProjection("late completion"),
                    timeline=timeline,
                    artifacts=[],
                    root_group=True,
                    expected_updated_at=str(running.get("updated_at") or ""),
                )
            else:
                service.workflow_continuation._outcomes.failed(
                    running,
                    WorkflowContinuationFailureProjection.from_error(
                        RuntimeError("late failure"),
                        {},
                    ),
                    timeline=timeline,
                    artifacts=[],
                    root_group=True,
                    expected_updated_at=str(running.get("updated_at") or ""),
                )

        assert service.get_run(created["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == cancelled_group
        assert service.list_run_events(
            created["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == list(running.get("timeline") or [])
    finally:
        service.close()


def test_native_workflow_terminal_outcome_accepts_same_group_winner_idempotently(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-same-winner.db",
        workspace_dir=tmp_path / "runtime-same-winner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Same workflow winner", source="workflow")
        created = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-same-winner",
            user_goal="accept same winner",
            run_group_id=group["run_group_id"],
        )
        running = service._update_run(created["run_id"], status="running")
        assert running is not None
        completed_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="same result",
        )
        assert completed_group is not None
        before_group_events = [
            event
            for event in service.list_run_events(
                created["run_id"],
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.completed"
        ]
        timeline = list(running.get("timeline") or [])

        result = service.workflow_continuation._outcomes.completed(
            running,
            WorkflowRunCompletionProjection("same result"),
            timeline=timeline,
            artifacts=[],
            root_group=True,
            expected_updated_at=str(running.get("updated_at") or ""),
        )

        assert result["status"] == "completed"
        assert service.get_run_group(group["run_group_id"]) == completed_group
        after_group_events = [
            event
            for event in service.list_run_events(
                created["run_id"],
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.completed"
        ]
        assert after_group_events == before_group_events
    finally:
        service.close()


def test_native_workflow_terminal_outcome_rejects_same_status_different_summary(
    tmp_path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-summary-winner.db",
        workspace_dir=tmp_path / "runtime-summary-winner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(
            title="Different workflow summary",
            source="workflow",
        )
        created = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-summary-winner",
            user_goal="preserve winner summary",
            run_group_id=group["run_group_id"],
        )
        running = service._update_run(created["run_id"], status="running")
        assert running is not None
        winner_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner summary",
        )
        assert winner_group is not None
        before_run = service.get_run(created["run_id"])
        before_events = service.list_run_events(
            created["run_id"],
            include_internal=True,
        )["events"]
        timeline = list(running.get("timeline") or [])

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            service.workflow_continuation._outcomes.completed(
                running,
                WorkflowRunCompletionProjection("different summary"),
                timeline=timeline,
                artifacts=[],
                root_group=True,
                expected_updated_at=str(running.get("updated_at") or ""),
            )

        assert service.get_run(created["run_id"]) == before_run
        assert service.get_run_group(group["run_group_id"]) == winner_group
        assert service.list_run_events(
            created["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert timeline == list(running.get("timeline") or [])
    finally:
        service.close()


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


def test_workflow_continuation_accepts_port_bundle_with_keyword_overrides() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "start", "type": "start", "data": {"label": "Bundled Start"}},
        ]
    }
    path = list(workflow["nodes"])
    calls: list[str] = []
    ports = WorkflowContinuationPortBundle(
        workflow_path=lambda current_workflow: calls.append("bundle:path")
        or list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda _workflow: calls.append("bundle:nodes") or {"start": path[0]},
        workflow_next_node_id=lambda _workflow, _node, _context: calls.append("bundle:next") or "",
        workflow_parallel_plan=lambda _workflow, _node: calls.append("bundle:parallel") or {},
        node_kind=lambda node: calls.append(f"bundle:kind:{node['id']}") or str(node["type"]),
    )
    coordinator = WorkflowContinuationCoordinator(
        engine,
        ports=ports,
        workflow_next_node_id=lambda _workflow, _node, _context: calls.append("override:next") or "",
    )

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Run bundled traversal"},
        workflow,
        context="Bundled context",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert calls == ["bundle:path", "bundle:nodes", "bundle:kind:start", "override:next"]


def test_workflow_continuation_uses_injected_condition_selection() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "route", "type": "condition", "data": {"label": "Route"}},
        ]
    }
    nodes_by_id = {str(node["id"]): node for node in workflow["nodes"]}
    selection_calls: list[dict[str, str]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda _workflow: nodes_by_id,
        workflow_next_node_id=lambda _workflow, node, _context: (
            "route" if node["id"] == "start" else ""
        ),
        workflow_parallel_plan=lambda _workflow, _node: {},
        workflow_condition_selection=lambda _workflow, node, context: selection_calls.append(
            {"node_id": str(node["id"]), "context": context}
        )
        or {
            "condition": "ship",
            "operator": "contains",
            "matched": False,
            "branch": "false",
            "target_node_id": "",
        },
        workflow_loop_selection=lambda *_args, **_kwargs: {},
        node_kind=lambda node: str(node["type"]),
    )

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Choose branch"},
        workflow,
        context="skip it",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    condition_event = next(event for event in engine.events if event[1] == "workflow.node.condition")
    assert result["status"] == "completed"
    assert selection_calls == [{"node_id": "route", "context": "skip it"}]
    assert condition_event[2]["workflow_node_selected_branch"] == "false"
    assert condition_event[2]["workflow_node_condition_matched"] is False


def test_workflow_continuation_uses_injected_loop_selection() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "repeat", "type": "loop", "data": {"label": "Repeat"}},
        ]
    }
    nodes_by_id = {str(node["id"]): node for node in workflow["nodes"]}
    selection_calls: list[dict[str, object]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda _workflow: nodes_by_id,
        workflow_next_node_id=lambda _workflow, node, _context: (
            "repeat" if node["id"] == "start" else ""
        ),
        workflow_parallel_plan=lambda _workflow, _node: {},
        workflow_condition_selection=lambda *_args, **_kwargs: {},
        workflow_loop_selection=lambda _workflow, node, context, *, previous_iterations: (
            selection_calls.append(
                {
                    "node_id": str(node["id"]),
                    "context": context,
                    "previous_iterations": previous_iterations,
                }
            )
            or {
                "condition": "again",
                "operator": "contains",
                "matched": False,
                "branch": "exit",
                "target_node_id": "",
                "previous_iterations": previous_iterations,
                "iteration": previous_iterations,
                "max_iterations": 1,
                "limit_reached": True,
            }
        ),
        node_kind=lambda node: str(node["type"]),
    )

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Loop once"},
        workflow,
        context="done",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    loop_event = next(event for event in engine.events if event[1] == "workflow.node.loop")
    assert result["status"] == "completed"
    assert selection_calls == [
        {"node_id": "repeat", "context": "done", "previous_iterations": 0}
    ]
    assert loop_event[2]["workflow_node_selected_branch"] == "exit"
    assert loop_event[2]["workflow_node_loop_limit_reached"] is True


def test_workflow_continuation_uses_injected_loop_budget_ports() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "repeat", "type": "loop", "data": {"label": "Repeat"}},
        ]
    }
    nodes_by_id = {str(node["id"]): node for node in workflow["nodes"]}
    budget_calls: list[str] = []
    selection_calls: list[dict[str, object]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda _workflow: nodes_by_id,
        workflow_next_node_id=lambda _workflow, node, _context: (
            "repeat" if node["id"] == "start" else ""
        ),
        workflow_condition_selection=lambda *_args, **_kwargs: {},
        workflow_loop_selection=lambda _workflow, node, context, *, previous_iterations: (
            selection_calls.append(
                {
                    "node_id": str(node["id"]),
                    "context": context,
                    "previous_iterations": previous_iterations,
                }
            )
            or {
                "condition": "again",
                "operator": "contains",
                "matched": False,
                "branch": "exit",
                "target_node_id": "",
                "previous_iterations": previous_iterations,
                "iteration": previous_iterations,
                "max_iterations": 5,
                "limit_reached": False,
            }
        ),
        runtime_limits=lambda: budget_calls.append("limits")
        or RunBudgetLimits(max_workflow_steps=5),
        workflow_loop_iterations_from_timeline=lambda timeline: budget_calls.append(
            f"iterations:{len(timeline)}"
        )
        or {"repeat": 2},
        workflow_loop_step_limit=lambda current_workflow: budget_calls.append(
            f"limit:{len(current_workflow['nodes'])}"
        )
        or 3,
        node_kind=lambda node: str(node["type"]),
    )
    timeline = [{"event": "workflow.node.loop", "workflow_node_id": "repeat"}]

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Loop again"},
        workflow,
        context="done",
        timeline=timeline,
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert budget_calls == ["iterations:1", "limit:2", "limits"]
    assert selection_calls == [
        {"node_id": "repeat", "context": "done", "previous_iterations": 2}
    ]


def test_workflow_continuation_uses_injected_approval_criteria() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {"id": "gate", "type": "approval", "data": {"label": "Human Gate"}},
        ]
    }
    criteria_calls: list[str] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "report",
        workflow_approval_criteria=lambda node: criteria_calls.append(str(node["id"]))
        or "Injected criteria",
        get_run=lambda run_id: {
            "run_id": run_id,
            "status": "running",
            "pending_approval": {},
            "timeline": [],
            "artifacts": [],
            "updated_at": "2026-07-11T10:00:00+00:00",
        },
        node_kind=lambda node: str(node["type"]),
    )

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Review"},
        workflow,
        context="Draft ready",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "approval_required"
    assert criteria_calls == ["gate"]
    assert result["pending_approval"]["workflow_node_approval_criteria"] == "Injected criteria"
    assert result["pending_approval"]["workflow_next_node_id"] == "report"
    approval_event = next(
        event for event in engine.events if event[1] == "workflow.node.approval_required"
    )
    assert approval_event[2]["workflow_node_approval_criteria"] == "Injected criteria"


def test_workflow_continuation_uses_injected_run_side_effect_ports() -> None:
    workflow = {
        "nodes": [
            {"id": "gate", "type": "approval", "data": {"label": "Human Gate"}},
        ]
    }
    timeline_events: list[dict[str, Any]] = []
    appended_events: list[tuple[str, str, dict[str, Any]]] = []
    run_updates: list[tuple[str, dict[str, Any]]] = []
    group_updates: list[tuple[str, dict[str, Any]]] = []
    get_calls: list[str] = []

    def get_run(run_id: str) -> dict[str, Any]:
        get_calls.append(run_id)
        if not run_updates:
            return {
                "run_id": run_id,
                "run_group_id": "run_group",
                "status": "running",
                "pending_approval": {},
                "timeline": [],
                "artifacts": [],
                "updated_at": "2026-07-11T10:00:00+00:00",
                "project_root_group": True,
            }
        return {
            "run_id": run_id,
            "run_group_id": "run_group",
            **run_updates[-1][1],
            "refetched": True,
        }

    coordinator = WorkflowContinuationCoordinator(
        object(),
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "report",
        workflow_approval_criteria=lambda _node: "Injected criteria",
        timeline_factory=lambda event, detail="", **payload: timeline_events.append(
            {"event": event, "detail": detail, **payload}
        )
        or timeline_events[-1],
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ) or {},
        update_run=lambda run_id, **fields: run_updates.append((run_id, fields))
        or {"run_id": run_id, "run_group_id": "run_group", **fields},
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ) or {"run_group_id": run_group_id, **fields, "updated_at": "group-version-2"},
        get_run=get_run,
        get_run_group=lambda run_group_id: {
            "run_group_id": run_group_id,
            "status": "running",
            "updated_at": "group-version-1",
            "child_run_ids": ["workflow_run"],
        },
        node_kind=lambda node: str(node["type"]),
    )
    timeline: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {
            "run_id": "workflow_run",
            "run_group_id": "run_group",
            "user_goal": "Review",
        },
        workflow,
        context="Draft ready",
        timeline=timeline,
        artifacts=[],
        start_index=0,
        root_group=True,
    )

    assert result["refetched"] is True
    assert result["status"] == "approval_required"
    assert timeline == timeline_events
    assert len(appended_events) == 2
    event_run_id, event_type, event_payload = appended_events[0]
    assert event_run_id == "workflow_run"
    assert event_type == "workflow.node.approval_required"
    assert event_payload["workflow_node_id"] == "gate"
    assert event_payload["workflow_node_kind"] == "approval"
    assert event_payload["workflow_node_label"] == "Human Gate"
    assert event_payload["workflow_node_approval_criteria"] == "Injected criteria"
    assert event_payload["status"] == "approval_required"
    assert "workflow_context" not in event_payload["pending_approval"]
    assert appended_events[1][0:2] == (
        "workflow_run",
        "group.run.approval_required",
    )
    assert appended_events[1][2]["run_group_id"] == "run_group"
    assert run_updates[-1][0] == "workflow_run"
    assert run_updates[-1][1]["status"] == "approval_required"
    assert run_updates[-1][1]["pending_approval"]["workflow_context"] == "Draft ready"
    assert group_updates == [
        (
            "run_group",
            {
                "status": "approval_required",
                "summary": "等待审批：Human Gate",
                "expected_status": "running",
                "expected_updated_at": "group-version-1",
            },
        )
    ]
    assert get_calls == ["workflow_run", "workflow_run"]


def test_workflow_continuation_uses_injected_artifact_io(tmp_path) -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {
                "id": "report",
                "type": "artifact",
                "data": {"label": "Final Report", "artifact_path": "reports/final.md"},
            },
        ]
    }
    artifacts_dir = tmp_path / "workflow-artifacts"
    artifact_path_calls: list[dict[str, object]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        default_workspace_policy=lambda: {
            "default_workdir": "",
            "readable_scopes": ["."],
            "writable_scopes": [],
        },
        workflow_artifacts_dir=lambda: artifacts_dir,
        workflow_artifact_path=lambda label, artifacts, requested: artifact_path_calls.append(
            {"label": label, "artifacts": list(artifacts), "requested": requested}
        )
        or requested,
        node_kind=lambda node: str(node["type"]),
    )
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Write report"},
        workflow,
        context="Final workflow summary",
        timeline=timeline,
        artifacts=artifacts,
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert (artifacts_dir / "workflow_run" / "reports" / "final.md").read_text(
        encoding="utf-8"
    ) == "Final workflow summary"
    assert artifact_path_calls == [
        {"label": "Final Report", "artifacts": [], "requested": "reports/final.md"}
    ]
    assert artifacts == [
        {
            "kind": "workflow_artifact",
            "workflow_node_id": "report",
            "workflow_node_label": "Final Report",
            "ok": True,
                "path": "reports/final.md",
                "bytes": len("Final workflow summary".encode("utf-8")),
                "postcondition_verified": True,
            }
        ]
    assert timeline[0]["event"] == "workflow.node.artifact"


def test_workflow_continuation_fallback_uses_engine_tool_brokers(tmp_path) -> None:
    engine = FakeWorkflowTraversalEngine()
    engine.tool_brokers = FakeWorkflowToolBrokers()
    workflow = {
        "nodes": [
            {
                "id": "report",
                "type": "artifact",
                "data": {"label": "Final Report", "artifact_path": "reports/final.md"},
            },
        ]
    }
    artifacts_dir = tmp_path / "workflow-artifacts"
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        default_workspace_policy=lambda: {"default_workdir": str(tmp_path)},
        workflow_artifacts_dir=lambda: artifacts_dir,
        workflow_artifact_path=lambda _label, _artifacts, requested: requested,
        node_kind=lambda node: str(node["type"]),
    )
    artifacts: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Write report"},
        workflow,
        context="Final workflow summary",
        timeline=[],
        artifacts=artifacts,
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert engine.tool_brokers.calls == [
        {
            "run_id": "workflow_run",
            "workspace_policy": {"default_workdir": str(tmp_path)},
            "artifacts_dir": artifacts_dir,
        }
    ]
    assert engine.tool_brokers.writes == [("reports/final.md", "Final workflow summary")]
    assert artifacts[0]["path"] == "reports/final.md"


def test_workflow_continuation_uses_injected_artifact_writer() -> None:
    engine = FakeWorkflowTraversalEngine()
    workflow = {
        "nodes": [
            {
                "id": "report",
                "type": "artifact",
                "data": {"label": "Final Report", "artifact_path": "reports/final.md"},
            },
        ]
    }
    writes: list[tuple[str, str, str]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        workflow_artifact_path=lambda _label, _artifacts, requested: requested,
        workflow_artifact_write=lambda run, artifact_path, context: writes.append(
            (str(run["run_id"]), artifact_path, context)
        )
        or {
            "ok": True,
            "path": artifact_path,
            "bytes": len(context.encode("utf-8")),
        },
        node_kind=lambda node: str(node["type"]),
    )
    artifacts: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {"run_id": "workflow_run", "user_goal": "Write report"},
        workflow,
        context="Final workflow summary",
        timeline=[],
        artifacts=artifacts,
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert writes == [
        ("workflow_run", "reports/final.md", "Final workflow summary")
    ]
    assert artifacts == [
        {
            "kind": "workflow_artifact",
            "workflow_node_id": "report",
            "workflow_node_label": "Final Report",
            "ok": True,
            "path": "reports/final.md",
            "bytes": len("Final workflow summary".encode("utf-8")),
        }
    ]


def test_workflow_continuation_uses_injected_agent_handoff_inputs() -> None:
    engine = FakeWorkflowAgentExecutionEngine()
    agent = {"agent_id": "agent_research", "name": "Research Agent"}
    child_run = {
        "run_id": "child_run",
        "status": "completed",
        "result": "Launch risk summary",
        "artifacts": [{"kind": "artifact", "path": "risk.md"}],
    }
    workflow = {
        "nodes": [
            {
                "id": "research",
                "type": "agent",
                "data": {"label": "Research", "agentId": "fallback_agent"},
            },
        ]
    }
    handoff_calls: list[tuple[str, str]] = []
    inserted: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    artifact_ref_calls: list[tuple[str, str]] = []
    merged: list[tuple[str, str]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        workflow_agent_for_node=lambda node: handoff_calls.append(("agent", str(node["id"])))
        or agent,
        workflow_node_task=lambda node: handoff_calls.append(("task", str(node["id"])))
        or "Summarize launch risk.",
        workflow_child_goal=lambda workflow_goal, step_task: handoff_calls.append(
            ("goal", step_task)
        )
        or f"{workflow_goal}\n\nStep: {step_task}",
        insert_run=lambda **kwargs: inserted.append(kwargs) or {"run_id": "child_run"},
        execute_agent_run=lambda run_id, received_agent, user_goal, *, upstream, run_group_id="": executed.append(
            {
                "run_id": run_id,
                "agent": received_agent,
                "user_goal": user_goal,
                "upstream": upstream,
                "run_group_id": run_group_id,
            }
        )
        or child_run,
        workflow_child_artifact_refs=lambda received_child_run, label: artifact_ref_calls.append(
            (str(received_child_run.get("run_id") or ""), label)
        )
        or [
            artifact
            for artifact in received_child_run.get("artifacts") or []
            if artifact.get("kind")
        ],
        merge_workflow_child_run_outcome=lambda _timeline, _artifacts, received_child_run, label: merged.append(
            (str(received_child_run.get("run_id") or ""), label)
        ),
        node_kind=lambda node: str(node["type"]),
    )
    timeline: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {
            "run_id": "workflow_run",
            "run_group_id": "workflow_group",
            "user_goal": "Ship release candidate",
        },
        workflow,
        context="Previous result",
        timeline=timeline,
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "completed"
    assert result["result"] == "Launch risk summary"
    assert handoff_calls == [
        ("agent", "research"),
        ("task", "research"),
        ("goal", "Summarize launch risk."),
    ]
    assert inserted == [
        {
            "kind": "agent_run",
            "runnable_id": "agent_research",
            "user_goal": "Summarize launch risk.",
            "run_group_id": "workflow_group",
        }
    ]
    assert executed == [
        {
            "run_id": "child_run",
            "agent": {
                **agent,
                "_runtime_planner_entrypoint": True,
                "_runtime_planner_entrypoint_context": "Summarize launch risk.",
                "_runtime_agent_goal_context": (
                    "Ship release candidate\n\nStep: Summarize launch risk."
                ),
            },
            "user_goal": "Summarize launch risk.",
            "upstream": "",
            "run_group_id": "workflow_group",
        }
    ]
    assert artifact_ref_calls == [("child_run", "Research")]
    assert merged == [("child_run", "Research")]
    agent_event = next(event for event in timeline if event["event"] == "workflow.node.agent")
    assert agent_event["workflow_node_task"] == "Summarize launch risk."
    assert agent_event["child_run_id"] == "child_run"
    assert agent_event["artifact_count"] == 1


def test_workflow_continuation_scopes_child_agent_approval_to_workflow_run() -> None:
    engine = FakeWorkflowAgentExecutionEngine()
    agent = {"agent_id": "agent_research", "name": "Research Agent"}
    child_run = {
        "run_id": "child_run",
        "kind": "agent_run",
        "status": "approval_required",
        "result": "Waiting for desktop tool approval",
        "pending_approval": {
            "approval_id": "approval-child",
            "tool": "desktop.type_text",
            "input": {"text": "hello"},
        },
    }
    workflow = {
        "nodes": [
            {
                "id": "desktop-node",
                "type": "agent",
                "data": {"label": "Type in app", "agentId": "fallback_agent"},
            },
        ]
    }
    executed: list[dict[str, Any]] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        workflow_agent_for_node=lambda _node: agent,
        workflow_node_task=lambda _node: "Type into the focused app.",
        workflow_child_goal=lambda workflow_goal, step_task: f"{workflow_goal}\n\nStep: {step_task}",
        insert_run=lambda **_kwargs: {"run_id": "child_run"},
        execute_agent_run=lambda run_id, received_agent, user_goal, *, upstream, workflow_run_id="": executed.append(
            {
                "run_id": run_id,
                "agent": received_agent,
                "user_goal": user_goal,
                "upstream": upstream,
                "workflow_run_id": workflow_run_id,
            }
        )
        or child_run,
        workflow_child_artifact_refs=lambda _child_run, _label: [],
        merge_workflow_child_run_outcome=lambda *_args: None,
        update_run=lambda run_id, **fields: updates.append((run_id, fields)) or {"run_id": run_id, **fields},
        get_run=lambda run_id: {
            "run_id": run_id,
            "status": "running",
            "pending_approval": {},
            "timeline": [],
            "artifacts": [],
            "updated_at": "2026-07-11T10:00:00+00:00",
        },
        node_kind=lambda node: str(node["type"]),
    )

    result = coordinator.continue_run(
        {
            "run_id": "workflow_run",
            "user_goal": "Ship release candidate",
        },
        workflow,
        context="Previous result",
        timeline=[],
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    assert result["status"] == "approval_required"
    assert executed[0]["workflow_run_id"] == "workflow_run"
    assert updates[0][0] == "child_run"
    pending = updates[0][1]["pending_approval"]
    assert pending["workflow_run_id"] == "workflow_run"
    assert pending["workflow_node_id"] == "desktop-node"
    assert pending["workflow_node_kind"] == "agent"
    assert pending["workflow_node_label"] == "Type in app"
    assert updates[-1][0] == "workflow_run"
    assert updates[-1][1]["status"] == "approval_required"


def test_workflow_continuation_uses_injected_subworkflow_execution_ports() -> None:
    engine = FakeWorkflowAgentExecutionEngine()
    child_workflow = {"workflow_id": "workflow_child", "name": "Child Flow"}
    child_run = {
        "run_id": "child_workflow_run",
        "kind": "workflow_run",
        "status": "completed",
        "result": "Child flow result",
        "artifacts": [{"kind": "workflow_artifact", "path": "reports/child.md"}],
    }
    workflow = {
        "nodes": [
            {
                "id": "child-flow",
                "type": "workflow",
                "data": {"label": "Run Child Flow", "workflow_id": "workflow_child"},
            },
        ]
    }
    inserted: list[dict[str, Any]] = []
    started_projection_calls: list[tuple[str, str]] = []
    continued: list[dict[str, Any]] = []
    artifact_ref_calls: list[tuple[str, str]] = []
    merged: list[tuple[str, str]] = []
    coordinator = WorkflowContinuationCoordinator(
        engine,
        workflow_path=lambda current_workflow: list(current_workflow["nodes"]),
        workflow_nodes_by_id=lambda current_workflow: {
            str(node["id"]): node for node in current_workflow["nodes"]
        },
        workflow_next_node_id=lambda _workflow, _node, _context: "",
        workflow_node_task=lambda _node: "Run child flow first",
        workflow_child_goal=lambda workflow_goal, step_task: (
            f"{workflow_goal}\n\nStep: {step_task}"
        ),
        insert_run=lambda **kwargs: inserted.append(kwargs)
        or {"run_id": "child_workflow_run"},
        workflow_for_node=lambda node: child_workflow
        if str(node.get("id") or "") == "child-flow"
        else {},
        workflow_run_started_projection=lambda workflow_id, received_workflow: started_projection_calls.append(
            (workflow_id, str(received_workflow.get("name") or ""))
        )
        or (
            [{"event": "workflow.run.started", "detail": "Child started"}],
            {"workflow_id": workflow_id, "status": "running"},
        ),
        continue_workflow_run=lambda run, received_workflow, **kwargs: continued.append(
            {
                "run_id": str(run.get("run_id") or ""),
                "workflow_id": str(received_workflow.get("workflow_id") or ""),
                "context": str(kwargs.get("context") or ""),
                "start_index": kwargs.get("start_index"),
                "root_group": kwargs.get("root_group"),
            }
        )
        or child_run,
        workflow_child_artifact_refs=lambda received_child_run, label: artifact_ref_calls.append(
            (str(received_child_run.get("run_id") or ""), label)
        )
        or [
            artifact
            for artifact in received_child_run.get("artifacts") or []
            if artifact.get("kind")
        ],
        merge_workflow_child_run_outcome=lambda _timeline, _artifacts, received_child_run, label: merged.append(
            (str(received_child_run.get("run_id") or ""), label)
        ),
        node_kind=lambda node: str(node["type"]),
    )
    timeline: list[dict[str, Any]] = []

    result = coordinator.continue_run(
        {
            "run_id": "workflow_run",
            "run_group_id": "workflow_group",
            "user_goal": "Run parent flow",
        },
        workflow,
        context="Run parent flow",
        timeline=timeline,
        artifacts=[],
        start_index=0,
        root_group=False,
    )

    child_goal = "Run parent flow\n\nStep: Run child flow first"
    assert result["status"] == "completed"
    assert result["result"] == "Child flow result"
    assert inserted == [
        {
            "kind": "workflow_run",
            "runnable_id": "workflow_child",
            "user_goal": child_goal,
            "run_group_id": "workflow_group",
        }
    ]
    assert started_projection_calls == [("workflow_child", "Child Flow")]
    assert continued == [
        {
            "run_id": "child_workflow_run",
            "workflow_id": "workflow_child",
            "context": child_goal,
            "start_index": 0,
            "root_group": False,
        }
    ]
    assert artifact_ref_calls == [("child_workflow_run", "Run Child Flow")]
    assert merged == [("child_workflow_run", "Run Child Flow")]
    workflow_event = next(
        event for event in timeline if event["event"] == "workflow.node.workflow"
    )
    assert workflow_event["child_workflow_id"] == "workflow_child"
    assert workflow_event["child_run_id"] == "child_workflow_run"
    assert workflow_event["artifact_count"] == 1


def test_workflow_continuation_execute_agent_run_forwards_runtime_context() -> None:
    received: list[dict[str, Any]] = []
    envelope = {"requests": [{"request_id": "open-music", "tool_name": "app.open"}]}
    metadata = {"yachiyo_runtime_planner": True}
    coordinator = WorkflowContinuationCoordinator(
        object(),
        execute_agent_run=lambda run_id, agent, user_goal, **kwargs: received.append(
            {
                "run_id": run_id,
                "agent": agent,
                "user_goal": user_goal,
                "kwargs": kwargs,
            }
        )
        or {"run_id": run_id, "status": "completed", "result": "done"},
    )

    result = coordinator._execute_agent_run(
        "child_run",
        {"agent_id": "agent_research"},
        "Open Music.",
        upstream="Previous step",
        run_group_id="workflow_group",
        workflow_run_id="workflow_run",
        runtime_execution_envelope=envelope,
        runtime_execution_metadata=metadata,
        daily_desktop_planning_context="Open Music.",
    )

    assert result["status"] == "completed"
    kwargs = received[0]["kwargs"]
    assert kwargs["runtime_execution_envelope"] is envelope
    assert kwargs["runtime_execution_metadata"] is metadata
    assert kwargs["workflow_run_id"] == "workflow_run"
    assert kwargs["daily_desktop_planning_context"] == "Open Music."


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


class FakeWorkflowAgentExecutionEngine:
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
