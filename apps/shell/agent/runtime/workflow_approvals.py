"""Workflow approval pause and resume projections."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apps.shell.agent.runtime.errors import AgentRuntimeError
from packages.security import redact_sensitive_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def _public_pending_approval(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    if not raw:
        return {}
    input_preview = raw.get("input_preview")
    if input_preview:
        public_input_preview = _tool_input_preview(input_preview)
    else:
        public_input_preview = _tool_input_preview(raw.get("input") or {})
    return {
        "approval_id": str(raw.get("approval_id") or ""),
        "tool": str(raw.get("tool") or ""),
        "input_preview": public_input_preview,
        "requested_at": str(raw.get("requested_at") or ""),
    }


@dataclass(frozen=True)
class WorkflowApprovalTransitionContext:
    """Shared public context for Workflow approval approve/reject/timeout transitions."""

    label: str
    workflow_node_id: str
    criteria: str
    input_preview: dict[str, Any]

    @classmethod
    def from_pending(cls, pending: dict[str, Any] | None) -> "WorkflowApprovalTransitionContext":
        if not pending or str(pending.get("tool") or "") != "workflow.approval":
            raise AgentRuntimeError("Workflow Run 缺少待审批节点信息")
        return cls(
            label=str(pending.get("workflow_node_label") or "Approval"),
            workflow_node_id=str(pending.get("workflow_node_id") or ""),
            criteria=str(pending.get("workflow_node_approval_criteria") or "").strip(),
            input_preview=(
                deepcopy(pending.get("input_preview"))
                if isinstance(pending.get("input_preview"), dict)
                else {}
            ),
        )


@dataclass(frozen=True)
class WorkflowApprovalResumeContext:
    """Shared context needed to resume a Workflow approval node."""

    approval: WorkflowApprovalTransitionContext
    workflow: dict[str, Any]
    result_context: str
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    start_index: int
    root_group: bool
    start_node_id: str = ""

    @classmethod
    def from_run(
        cls,
        run: dict[str, Any],
        pending: dict[str, Any] | None,
        *,
        workflow: dict[str, Any],
        root_group: bool,
    ) -> "WorkflowApprovalResumeContext":
        approval = WorkflowApprovalTransitionContext.from_pending(pending)
        raw_pending = pending if isinstance(pending, dict) else {}
        try:
            start_index = int(raw_pending.get("workflow_next_index") or 0)
        except (TypeError, ValueError):
            raise AgentRuntimeError("Workflow Run 待审批恢复位置无效")
        if start_index < 0:
            raise AgentRuntimeError("Workflow Run 待审批恢复位置无效")
        return cls(
            approval=approval,
            workflow=deepcopy(workflow),
            result_context=str(
                raw_pending.get("workflow_context")
                or run.get("result")
                or run.get("user_goal")
                or ""
            ),
            timeline=[
                deepcopy(event)
                for event in run.get("timeline") or []
                if isinstance(event, dict)
            ],
            artifacts=[
                deepcopy(item)
                for item in run.get("artifacts") or []
                if isinstance(item, dict)
            ],
            start_index=start_index,
            root_group=root_group,
            start_node_id=str(raw_pending.get("workflow_next_node_id") or "").strip(),
        )


class WorkflowApprovalResumeCoordinator:
    """Claims and resumes a Workflow approval node."""

    def __init__(
        self,
        *,
        claim_pending_approval: Any,
        get_current_run: Any,
        resume_after_approval_node: Any,
    ) -> None:
        self._claim_pending_approval = claim_pending_approval
        self._get_current_run = get_current_run
        self._resume_after_approval_node = resume_after_approval_node

    def resume_after_approval(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        context: WorkflowApprovalResumeContext,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        if not self._claim_pending_approval(run_id, pending):
            return self._get_current_run(run_id)
        return self._resume_after_approval_node(
            run,
            context.workflow,
            context=context.result_context,
            timeline=context.timeline,
            artifacts=context.artifacts,
            start_index=context.start_index,
            start_node_id=context.start_node_id,
            root_group=context.root_group,
            workflow_node_id=context.approval.workflow_node_id,
            label=context.approval.label,
            criteria=context.approval.criteria,
            input_preview=context.approval.input_preview,
        )


@dataclass(frozen=True)
class WorkflowApprovalPauseProjection:
    """Pending approval and replay payload for a Workflow approval node pause."""

    approval_id: str
    node_id: str
    node_kind: str
    label: str
    criteria: str
    context: str
    next_index: int
    next_node_id: str
    requested_at: str

    @classmethod
    def from_node(
        cls,
        engine: Any,
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        next_index: int,
        next_node_id: str = "",
    ) -> "WorkflowApprovalPauseProjection":
        return cls(
            approval_id=f"approval_{uuid4().hex[:12]}",
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            label=label,
            criteria=engine._workflow_approval_criteria(node),
            context=context,
            next_index=next_index,
            next_node_id=next_node_id,
            requested_at=_now(),
        )

    def pending_approval(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool": "workflow.approval",
            "input_preview": {
                "checkpoint": self.label,
                "context": _tool_input_preview(self.context),
                **({"criteria": self.criteria} if self.criteria else {}),
            },
            "requested_at": self.requested_at,
            "workflow_context": self.context,
            "workflow_next_index": self.next_index,
            "workflow_next_node_id": self.next_node_id,
            "workflow_node_id": self.node_id,
            "workflow_node_label": self.label,
            "workflow_node_approval_criteria": self.criteria,
        }

    def public_pending_approval(self) -> dict[str, Any]:
        return _public_pending_approval(self.pending_approval())

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.label,
            "workflow_node_approval_criteria": self.criteria,
            "status": "approval_required",
            "pending_approval": self.public_pending_approval(),
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.approval_required",
            self.label,
            **self.event_payload(),
        )

    def result_text(self) -> str:
        return f"等待审批：{self.label}"

    def update_fields(
        self,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": "approval_required",
            "result": self.result_text(),
            "timeline": timeline,
            "artifacts": artifacts,
            "pending_approval": self.pending_approval(),
        }
