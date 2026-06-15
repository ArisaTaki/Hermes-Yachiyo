"""Workflow timeline projection snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.security import redact_sensitive_text


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


@dataclass(frozen=True)
class WorkflowStartNodeProjection:
    """Replay payload for a completed Workflow start node."""

    node_id: str
    node_kind: str
    node_label: str

    @classmethod
    def from_node(
        cls,
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
    ) -> "WorkflowStartNodeProjection":
        return cls(
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
        )

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
            "status": "completed",
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.start",
            self.node_label,
            workflow_node_id=self.node_id,
            status="completed",
        )


@dataclass(frozen=True)
class WorkflowConditionNodeProjection:
    """Replay payload for a completed Workflow condition node."""

    node_id: str
    node_kind: str
    node_label: str
    condition: str
    operator: str
    matched: bool
    branch: str
    target_node_id: str

    @classmethod
    def from_node(
        cls,
        engine: Any,
        workflow: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
    ) -> "WorkflowConditionNodeProjection":
        selection = engine._workflow_condition_selection(workflow, node, context)
        return cls(
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
            condition=str(selection.get("condition") or ""),
            operator=str(selection.get("operator") or "contains"),
            matched=bool(selection.get("matched")),
            branch=str(selection.get("branch") or ""),
            target_node_id=str(selection.get("target_node_id") or ""),
        )

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
            "workflow_node_condition": self.condition,
            "workflow_node_condition_operator": self.operator,
            "workflow_node_condition_matched": self.matched,
            "workflow_node_selected_branch": self.branch,
            "workflow_node_selected_target": self.target_node_id,
            "status": "completed",
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.condition",
            self.node_label,
            **self.event_payload(),
        )


@dataclass(frozen=True)
class WorkflowParallelNodeProjection:
    """Replay payload for a completed Workflow parallel fan-out node."""

    node_id: str
    node_kind: str
    node_label: str
    branch_count: int
    completed_count: int
    join_node_id: str
    branch_results: list[dict[str, str]]

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
            "workflow_node_branch_count": self.branch_count,
            "workflow_node_completed_branch_count": self.completed_count,
            "workflow_node_join_target": self.join_node_id,
            "workflow_node_branch_results": self.branch_results,
            "status": "completed",
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.parallel",
            self.node_label,
            **self.event_payload(),
        )


@dataclass(frozen=True)
class WorkflowLoopNodeProjection:
    """Replay payload for a completed Workflow loop routing decision."""

    node_id: str
    node_kind: str
    node_label: str
    condition: str
    operator: str
    matched: bool
    branch: str
    target_node_id: str
    previous_iterations: int
    iteration: int
    max_iterations: int
    limit_reached: bool

    @classmethod
    def from_node(
        cls,
        engine: Any,
        workflow: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        previous_iterations: int,
    ) -> "WorkflowLoopNodeProjection":
        selection = engine._workflow_loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )
        return cls(
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
            condition=str(selection.get("condition") or ""),
            operator=str(selection.get("operator") or "contains"),
            matched=bool(selection.get("matched")),
            branch=str(selection.get("branch") or ""),
            target_node_id=str(selection.get("target_node_id") or ""),
            previous_iterations=int(selection.get("previous_iterations") or 0),
            iteration=int(selection.get("iteration") or 0),
            max_iterations=int(selection.get("max_iterations") or 1),
            limit_reached=bool(selection.get("limit_reached")),
        )

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
            "workflow_node_condition": self.condition,
            "workflow_node_condition_operator": self.operator,
            "workflow_node_condition_matched": self.matched,
            "workflow_node_selected_branch": self.branch,
            "workflow_node_selected_target": self.target_node_id,
            "workflow_node_loop_previous_iterations": self.previous_iterations,
            "workflow_node_loop_iteration": self.iteration,
            "workflow_node_loop_max_iterations": self.max_iterations,
            "workflow_node_loop_limit_reached": self.limit_reached,
            "status": "completed",
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.loop",
            self.node_label,
            **self.event_payload(),
        )


@dataclass(frozen=True)
class WorkflowRunCompletionProjection:
    """Completed Workflow Run projection."""

    result_text: str

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory("workflow.run.completed", "Workflow run completed")

    def event_payload(self) -> dict[str, Any]:
        return {"result": self.result_text}

    def update_fields(
        self,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": "completed",
            "result": self.result_text,
            "timeline": timeline,
            "artifacts": artifacts,
        }


@dataclass(frozen=True)
class WorkflowContinuationFailureProjection:
    """Failed Workflow continuation projection."""

    safe_error: str
    node_info: dict[str, str]

    @classmethod
    def from_error(
        cls,
        error: Any,
        node_info: dict[str, str],
    ) -> "WorkflowContinuationFailureProjection":
        return cls(
            safe_error=_redact_secrets(error),
            node_info={key: _redact_secrets(value) for key, value in node_info.items()},
        )

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.run.failed",
            self.safe_error,
            status="failed",
            **self.node_info,
        )

    def event_payload(self) -> dict[str, Any]:
        return {"error": self.safe_error, **self.node_info}

    def update_fields(
        self,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": "failed",
            "result": self.safe_error,
            "timeline": timeline,
            "artifacts": artifacts,
        }
