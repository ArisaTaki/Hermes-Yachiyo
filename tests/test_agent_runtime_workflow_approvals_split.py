"""Tests for workflow approval projections split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseCoordinator,
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)


def test_workflow_approval_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowApprovalTransitionContext is WorkflowApprovalTransitionContext
    assert agent_runtime.WorkflowApprovalResumeContext is WorkflowApprovalResumeContext
    assert agent_runtime.WorkflowApprovalResumeCoordinator is WorkflowApprovalResumeCoordinator
    assert agent_runtime.WorkflowApprovalPauseCoordinator is WorkflowApprovalPauseCoordinator
    assert agent_runtime.WorkflowApprovalPauseProjection is WorkflowApprovalPauseProjection


def test_workflow_approval_pause_projection_accepts_prepared_criteria() -> None:
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="  Review output  ",
        context="Draft ready",
        next_index=3,
        next_node_id="report",
    )

    pending = projection.pending_approval()
    assert pending["approval_id"].startswith("approval_")
    assert pending["workflow_node_id"] == "gate"
    assert pending["workflow_node_approval_criteria"] == "Review output"
    assert pending["workflow_next_index"] == 3
    assert pending["workflow_next_node_id"] == "report"
    assert projection.event_payload()["pending_approval"] == projection.public_pending_approval()


def test_workflow_approval_pause_coordinator_applies_projection_side_effects() -> None:
    timeline_events: list[dict[str, object]] = []
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    run_updates: list[tuple[str, dict[str, object]]] = []
    group_updates: list[tuple[str, dict[str, object]]] = []
    get_calls: list[str] = []

    def get_run(run_id: str) -> dict[str, object]:
        get_calls.append(run_id)
        if not run_updates:
            return {
                "run_id": run_id,
                "run_group_id": "run_group",
                "status": "running",
                "pending_approval": {},
                "updated_at": "2026-07-11T10:00:00+00:00",
                "project_root_group": True,
            }
        return {"run_id": run_id, "refetched": True, **run_updates[-1][1]}

    coordinator = WorkflowApprovalPauseCoordinator(
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
    )
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="Review output",
        context="Draft ready",
        next_index=2,
        next_node_id="report",
    )
    timeline: list[dict[str, object]] = []
    artifacts = [{"kind": "workflow_artifact", "path": "draft.md"}]

    result = coordinator.pause(
        {"run_id": "workflow_run"},
        projection,
        run_group_id="run_group",
        timeline=timeline,
        artifacts=artifacts,
        root_group=True,
    )

    assert result["refetched"] is True
    assert result["status"] == "approval_required"
    assert timeline == timeline_events
    assert appended_events[0] == (
        "workflow_run",
        "workflow.node.approval_required",
        projection.event_payload(),
    )
    assert appended_events[1][0:2] == (
        "workflow_run",
        "group.run.approval_required",
    )
    assert appended_events[1][2]["run_group_id"] == "run_group"
    assert appended_events[1][2]["pending_approval"] == (
        projection.public_pending_approval()
    )
    assert run_updates[-1][0] == "workflow_run"
    assert run_updates[-1][1]["status"] == "approval_required"
    assert run_updates[-1][1]["artifacts"] is artifacts
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


def test_workflow_approval_pause_cas_loser_emits_no_event_or_group_projection() -> None:
    current = {
        "run_id": "workflow-run-race",
        "status": "running",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    group_updates: list[tuple[str, dict[str, object]]] = []

    def update_run(_run_id: str, **fields: object):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert fields["expected_pending_approval_absent"] is True
        current.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    coordinator = WorkflowApprovalPauseCoordinator(
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(current),
    )
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="Review output",
        context="Draft ready",
        next_index=2,
        next_node_id="report",
    )
    timeline: list[dict[str, object]] = []

    result = coordinator.pause(
        dict(current),
        projection,
        run_group_id="run-group-race",
        timeline=timeline,
        artifacts=[],
        root_group=True,
    )

    assert result["status"] == "cancelled"
    assert result["result"] == "cancelled by user"
    assert timeline == []
    assert appended_events == []
    assert group_updates == []


def test_workflow_approval_pause_post_cas_cancel_fences_event_and_group() -> None:
    current = {
        "run_id": "workflow-pause-post-cas",
        "status": "running",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "run-version-1",
    }
    group = {
        "run_group_id": "workflow-pause-group",
        "status": "running",
        "updated_at": "group-version-1",
    }
    event_attempts: list[dict[str, object]] = []
    group_updates: list[dict[str, object]] = []

    def update_run(_run_id: str, **fields: object) -> dict[str, object]:
        current.update(fields)
        current["updated_at"] = "run-version-2"
        return dict(current)

    def append_event(
        _run_id: str,
        _event_type: str,
        _payload: dict[str, object],
        **kwargs: object,
    ) -> None:
        event_attempts.append(kwargs)
        current.update(status="cancelled", updated_at="run-version-3")
        group.update(status="cancelled", updated_at="group-version-2")
        return None

    coordinator = WorkflowApprovalPauseCoordinator(
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=append_event,
        update_run=update_run,
        update_run_group=lambda _run_group_id, **fields: group_updates.append(fields),
        get_run=lambda _run_id: dict(current),
        get_run_group=lambda _run_group_id: dict(group),
    )
    projection = WorkflowApprovalPauseProjection.from_criteria(
        {"id": "gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="Review output",
        context="Draft ready",
        next_index=2,
    )

    with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
        coordinator.pause(
            dict(current),
            projection,
            run_group_id=group["run_group_id"],
            timeline=[],
            artifacts=[],
            root_group=True,
        )

    assert current["status"] == "cancelled"
    assert group["status"] == "cancelled"
    assert event_attempts == [
        {
            "expected_status": "approval_required",
            "expected_updated_at": "run-version-2",
        }
    ]
    assert group_updates == []
