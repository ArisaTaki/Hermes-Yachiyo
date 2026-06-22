"""Tests for workflow outcome projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import tool_input_preview
from apps.shell.agent.runtime.workflow_outcomes import (
    _tool_input_preview,
    WorkflowChildExecutionStatusProjection,
    WorkflowChildOutcomeCoordinator,
    WorkflowChildRunProjection,
    WorkflowChildStatusProjection,
    WorkflowParentResumeFailureProjection,
)


def test_workflow_outcome_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowChildOutcomeCoordinator is WorkflowChildOutcomeCoordinator
    assert (
        agent_runtime.WorkflowChildExecutionStatusProjection
        is WorkflowChildExecutionStatusProjection
    )
    assert agent_runtime.WorkflowChildRunProjection is WorkflowChildRunProjection
    assert agent_runtime.WorkflowChildStatusProjection is WorkflowChildStatusProjection
    assert (
        agent_runtime.WorkflowParentResumeFailureProjection
        is WorkflowParentResumeFailureProjection
    )
    assert _tool_input_preview is tool_input_preview


class FakeChildExecution:
    def __init__(self, *, status: str, next_context: str) -> None:
        self.status = status
        self.next_context = next_context

    def status_event_payload(self) -> dict[str, str]:
        return {
            "workflow_node_id": "review",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Review",
            "child_run_id": "child_run",
            "status": self.status,
        }


def test_workflow_child_execution_status_projection_skips_completed_child() -> None:
    assert (
        WorkflowChildExecutionStatusProjection.from_execution(
            FakeChildExecution(status="completed", next_context="done"),
            label="Review",
        )
        is None
    )


def test_workflow_child_execution_status_projection_preserves_approval_shape() -> None:
    projection = WorkflowChildExecutionStatusProjection.from_execution(
        FakeChildExecution(status="approval_required", next_context="Waiting for approval"),
        label="Review",
    )
    assert projection is not None

    timeline_event = projection.timeline_event(
        lambda event, detail, **payload: {"event": event, "detail": detail, **payload}
    )

    assert projection.event_type == "workflow.run.approval_required"
    assert timeline_event == {
        "event": "workflow.run.approval_required",
        "detail": "Review",
        "workflow_node_id": "review",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Review",
        "child_run_id": "child_run",
        "status": "approval_required",
    }
    assert projection.run_event_payload() == {
        "workflow_node_id": "review",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Review",
        "child_run_id": "child_run",
        "status": "approval_required",
    }
    assert projection.update_fields(timeline=[timeline_event], artifacts=[]) == {
        "status": "approval_required",
        "result": "Waiting for approval",
        "timeline": [timeline_event],
        "artifacts": [],
    }
    assert projection.run_group_update_fields() == {
        "status": "approval_required",
        "summary": "Waiting for approval",
    }


def test_workflow_child_execution_status_projection_preserves_failed_shape() -> None:
    projection = WorkflowChildExecutionStatusProjection.from_execution(
        FakeChildExecution(status="error", next_context="Tool failed"),
        label="Review",
    )
    assert projection is not None

    timeline_event = projection.timeline_event(
        lambda event, detail, **payload: {"event": event, "detail": detail, **payload}
    )

    assert projection.event_type == "workflow.run.failed"
    assert timeline_event == {
        "event": "workflow.run.failed",
        "detail": "Review: Tool failed",
        "workflow_node_id": "review",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Review",
        "child_run_id": "child_run",
        "status": "error",
    }
    assert projection.run_event_payload() == {
        "workflow_node_id": "review",
        "workflow_node_kind": "agent",
        "workflow_node_label": "Review",
        "child_run_id": "child_run",
        "status": "error",
        "result": "Tool failed",
    }


def test_workflow_child_execution_status_projection_maps_cancelled_status() -> None:
    projection = WorkflowChildExecutionStatusProjection.from_execution(
        FakeChildExecution(status="cancelled", next_context=""),
        label="Review",
    )
    assert projection is not None

    assert projection.event_type == "workflow.run.cancelled"
    assert projection.detail == "Review: cancelled"
    assert projection.run_event_payload()["result"] == "cancelled"
    assert projection.update_fields(timeline=[], artifacts=[]) == {
        "status": "cancelled",
        "result": "",
        "timeline": [],
        "artifacts": [],
    }
