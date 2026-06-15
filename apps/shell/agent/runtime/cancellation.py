"""Cancellation projections for Agent and Workflow runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class WorkflowCancellationTarget:
    """Workflow cancellation target rendered into timeline and result text."""

    label: str
    node_info: dict[str, str]
    child_run_id: str = ""

    @classmethod
    def workflow(cls) -> "WorkflowCancellationTarget":
        return cls(label="Workflow", node_info={})

    @classmethod
    def from_pending_approval(cls, pending: dict[str, Any]) -> "WorkflowCancellationTarget":
        label = str(pending.get("workflow_node_label") or "Approval")
        return cls(
            label=label,
            node_info={
                "workflow_node_id": str(pending.get("workflow_node_id") or ""),
                "workflow_node_kind": "approval",
                "workflow_node_label": label,
                "workflow_node_approval_criteria": str(
                    pending.get("workflow_node_approval_criteria") or ""
                ).strip(),
            },
        )

    @classmethod
    def from_child(
        cls,
        *,
        child_run_id: str,
        label: str,
        node_info: dict[str, str],
    ) -> "WorkflowCancellationTarget":
        return cls(label=label, node_info=dict(node_info), child_run_id=child_run_id)

    def event_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": "cancelled", **self.node_info}
        if self.child_run_id:
            payload["child_run_id"] = self.child_run_id
        return payload

    def event_detail(self) -> str:
        return f"{self.label} cancelled"

    def result_text(self) -> str:
        return f"Workflow 已取消：{self.label}"


@dataclass(frozen=True)
class RunCancellationProjection:
    """Run update fields produced by a cancellation request."""

    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] | None
    result_text: str

    @classmethod
    def plain(
        cls,
        timeline: list[dict[str, Any]],
        timeline_factory: Any,
    ) -> "RunCancellationProjection":
        return cls(
            timeline=[*timeline, timeline_factory("run.cancelled", "Run cancelled")],
            artifacts=None,
            result_text="Run cancelled",
        )

    @classmethod
    def workflow(
        cls,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        result_text: str,
    ) -> "RunCancellationProjection":
        return cls(timeline=timeline, artifacts=artifacts, result_text=result_text)

    def update_fields(self) -> dict[str, Any]:
        return {
            "status": "cancelled",
            "result": self.result_text,
            "timeline": self.timeline,
            "artifacts": self.artifacts,
            "pending_approval": None,
        }


class WorkflowCancellationProjectionCoordinator:
    """Builds Workflow cancellation projections, including waiting child Runs."""

    def __init__(
        self,
        *,
        pending_approval_private: Any,
        get_run: Any,
        merge_workflow_child_run_outcome: Any,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
    ) -> None:
        self._pending_approval_private = pending_approval_private
        self._get_run = get_run
        self._merge_workflow_child_run_outcome = merge_workflow_child_run_outcome
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run

    def project_cancelled_workflow_run(
        self,
        run_id: str,
        run: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        artifacts = [item for item in run.get("artifacts") or [] if isinstance(item, dict)]
        pending = self._pending_approval_private(run_id)
        if pending and str(pending.get("tool") or "") == "workflow.approval":
            target = WorkflowCancellationTarget.from_pending_approval(pending)
        else:
            target = self._cancel_waiting_child_run(
                run_id,
                timeline,
                artifacts,
            )
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                target.event_detail(),
                **target.event_payload(),
            )
        )
        return timeline, artifacts, target.result_text()

    def _cancel_waiting_child_run(
        self,
        parent_run_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> WorkflowCancellationTarget:
        child_run_id = self._latest_waiting_child_run_id(timeline)
        if not child_run_id:
            return WorkflowCancellationTarget.workflow()
        label, node_info = self._child_node_context(timeline, child_run_id)
        try:
            child_run = self._get_run(child_run_id)
        except KeyError:
            child_run = {}
        if child_run and str(child_run.get("status") or "") not in FINAL_RUN_STATUSES:
            child_run = self._cancel_child_run(parent_run_id, child_run)
        if child_run:
            self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
        return WorkflowCancellationTarget.from_child(
            child_run_id=child_run_id,
            label=label,
            node_info=node_info,
        )

    @staticmethod
    def _latest_waiting_child_run_id(timeline: list[dict[str, Any]]) -> str:
        for event in reversed(timeline):
            if not isinstance(event, dict):
                continue
            if event.get("event") != "workflow.run.approval_required":
                continue
            child_run_id = str(event.get("child_run_id") or "").strip()
            if child_run_id:
                return child_run_id
        return ""

    @staticmethod
    def _child_node_context(
        timeline: list[dict[str, Any]],
        child_run_id: str,
    ) -> tuple[str, dict[str, str]]:
        for event in timeline:
            if (
                isinstance(event, dict)
                and event.get("event") in {"workflow.node.agent", "workflow.node.workflow"}
                and str(event.get("child_run_id") or "") == child_run_id
            ):
                label = (
                    str(event.get("detail") or event.get("workflow_node_label") or "Run").strip()
                    or "Run"
                )
                return label, {
                    "workflow_node_id": str(event.get("workflow_node_id") or ""),
                    "workflow_node_kind": str(event.get("workflow_node_kind") or ""),
                    "workflow_node_label": str(event.get("workflow_node_label") or label),
                }
        return "Run", {}

    def _cancel_child_run(self, parent_run_id: str, child_run: dict[str, Any]) -> dict[str, Any]:
        child_run_id = str(child_run.get("run_id") or "")
        child_timeline = [
            event
            for event in child_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        child_timeline.append(self._timeline("run.cancelled", "Parent Workflow cancelled"))
        self._append_run_event(
            child_run_id,
            "run.cancelled",
            {"reason": "Parent Workflow cancelled", "parent_run_id": parent_run_id},
        )
        return self._update_run(
            child_run_id,
            status="cancelled",
            result="父 Workflow 已取消",
            timeline=child_timeline,
            pending_approval=None,
        )
