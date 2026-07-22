"""Workflow approval pause and resume projections."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apps.shell.agent.runtime.approval_snapshots import (
    approval_input_preview,
    public_pending_approval,
)
from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.approval_lifecycle import (
    _append_required_pause_event,
    _approval_root_group_event_payload,
    _approval_root_group_snapshot,
    _project_approval_root_group,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_WORKFLOW_PROJECTION_INTEGRITY_ERRORS = {
    "approval_pause_root_group_id_required",
    "approval_pause_root_group_missing",
    "approval_pause_root_group_projection_unavailable",
    "run_event_fence_mismatch",
    "run_group_event_fence_mismatch",
    "run_group_projection_cas_lost",
    "run_group_projection_missing",
    "run_group_terminal_outcome_conflict",
    "workflow_approval_projection_missing",
}


def is_workflow_projection_integrity_error(error: Exception) -> bool:
    """Return whether an atomic projection failure must escape orchestration."""

    return isinstance(error, AgentRuntimeError) and str(error) in (
        _WORKFLOW_PROJECTION_INTEGRITY_ERRORS
    )


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
    expected_approval_id: str = ""

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
            expected_approval_id=str(raw_pending.get("approval_id") or "").strip(),
        )


class WorkflowApprovalResumeCoordinator:
    """Claims and resumes a Workflow approval node."""

    def __init__(
        self,
        *,
        claim_pending_approval: Any,
        get_current_run: Any,
        resume_after_approval_node: Any,
        project_approved_node: Any | None = None,
        continue_after_approval_node: Any | None = None,
        transaction_scope: Any | None = None,
    ) -> None:
        self._claim_pending_approval = claim_pending_approval
        self._get_current_run = get_current_run
        self._resume_after_approval_node = resume_after_approval_node
        self._project_approved_node = project_approved_node
        self._continue_after_approval_node = continue_after_approval_node
        self._transaction_scope = transaction_scope

    def resume_after_approval(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        context: WorkflowApprovalResumeContext,
        *,
        expected_approval_id: str = "",
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending_id = str(pending.get("approval_id") or "").strip()
        expected_id = str(expected_approval_id or "").strip() or pending_id
        if not expected_id:
            raise AgentRuntimeError("approval_expected_id_required")
        if pending_id != expected_id:
            raise AgentRuntimeError("approval_generation_mismatch")
        context_expected_id = str(context.expected_approval_id or "").strip()
        if context_expected_id and context_expected_id != expected_id:
            raise AgentRuntimeError("approval_generation_mismatch")
        claim_kwargs = (
            {"expected_approval_id": expected_id}
            if supports_keyword(self._claim_pending_approval, "expected_approval_id")
            else {}
        )
        if (
            self._project_approved_node is not None
            and self._continue_after_approval_node is not None
        ):
            return self._resume_with_atomic_projection(
                run,
                pending,
                context,
                expected_id=expected_id,
                claim_kwargs=claim_kwargs,
            )
        if not self._claim_pending_approval(run_id, pending, **claim_kwargs):
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
            expected_approval_id=expected_id,
        )

    def _resume_with_atomic_projection(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        context: WorkflowApprovalResumeContext,
        *,
        expected_id: str,
        claim_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        timeline_start = len(context.timeline)
        scope = (
            self._transaction_scope()
            if self._transaction_scope is not None
            else nullcontext()
        )
        running: dict[str, Any] | None = None
        terminal: dict[str, Any] | None = None
        try:
            with scope:
                if not self._claim_pending_approval(run_id, pending, **claim_kwargs):
                    return self._get_current_run(run_id)
                running = self._project_approved_node(
                    run,
                    context=context.result_context,
                    timeline=context.timeline,
                    artifacts=context.artifacts,
                    workflow_node_id=context.approval.workflow_node_id,
                    label=context.approval.label,
                    criteria=context.approval.criteria,
                    input_preview=context.approval.input_preview,
                    expected_approval_id=expected_id,
                )
                if running is None:
                    current = self._get_current_run(run_id)
                    if str(current.get("status") or "") in {
                        "cancelled",
                        "canceled",
                        "completed",
                        "failed",
                    }:
                        terminal = current
                    else:
                        raise _WorkflowApprovalProjectionConflict
        except _WorkflowApprovalProjectionConflict:
            del context.timeline[timeline_start:]
            return self._get_current_run(run_id)
        except BaseException:
            del context.timeline[timeline_start:]
            raise
        if terminal is not None:
            return terminal
        if running is None:
            raise AgentRuntimeError("workflow_approval_projection_missing")
        return self._continue_after_approval_node(
            running,
            context.workflow,
            context=context.result_context,
            timeline=context.timeline,
            artifacts=context.artifacts,
            start_index=context.start_index,
            start_node_id=context.start_node_id,
            root_group=context.root_group,
        )


class _WorkflowApprovalProjectionConflict(Exception):
    pass


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
    def from_criteria(
        cls,
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        criteria: str,
        context: str,
        next_index: int,
        next_node_id: str = "",
    ) -> "WorkflowApprovalPauseProjection":
        return cls(
            approval_id=f"approval_{uuid4().hex[:12]}",
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            label=label,
            criteria=str(criteria or "").strip(),
            context=context,
            next_index=next_index,
            next_node_id=next_node_id,
            requested_at=_now(),
        )

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
        return cls.from_criteria(
            node,
            label=label,
            kind=kind,
            criteria=engine._workflow_approval_criteria(node),
            context=context,
            next_index=next_index,
            next_node_id=next_node_id,
        )

    def pending_approval(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool": "workflow.approval",
            "input_preview": {
                "checkpoint": self.label,
                "context": approval_input_preview(self.context),
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
        return public_pending_approval(self.pending_approval())

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


class WorkflowApprovalPauseCoordinator:
    """Applies Workflow approval pause projections to run state and root groups."""

    def __init__(
        self,
        *,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        update_run_group: Any,
        get_run: Any,
        get_run_group: Any | None = None,
        transaction_scope: Any | None = None,
    ) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._update_run_group = update_run_group
        self._get_run = get_run
        self._get_run_group = get_run_group
        self._transaction_scope = transaction_scope

    def pause(
        self,
        run: dict[str, Any],
        projection: WorkflowApprovalPauseProjection,
        *,
        run_group_id: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        next_timeline = list(timeline)
        next_timeline.append(projection.timeline_event(self._timeline))
        # ``root_group`` and ``run_group_id`` are legacy caller hints. Only the
        # fresh persisted Run row may authorize a root Group projection.
        projected_root_group = False
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._get_run(run_id)
            current_status = str(current.get("status") or "").strip().lower()
            caller_version = str(run.get("updated_at") or "").strip()
            if caller_version and str(current.get("updated_at") or "") != caller_version:
                return current
            if current_status in {
                "approval_required",
                "completed",
                "failed",
                "cancelled",
                "canceled",
            } or current.get("pending_approval"):
                return current
            root_group_snapshot = _approval_root_group_snapshot(
                current,
                get_run_group=self._get_run_group,
                update_run_group=self._update_run_group,
            )
            result = self._update_run(
                run_id,
                **projection.update_fields(timeline=next_timeline, artifacts=artifacts),
                expected_status=current_status,
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                return self._get_run(run_id)
            event_fence = {
                "expected_status": "approval_required",
                "expected_updated_at": str(result.get("updated_at") or ""),
            }
            _append_required_pause_event(
                self._append_run_event,
                run_id,
                "workflow.node.approval_required",
                projection.event_payload(),
                event_fence=event_fence,
            )
            if root_group_snapshot is not None:
                owned_run_group_id, group = root_group_snapshot
                summary = projection.result_text()
                projected_group = _project_approval_root_group(
                    owned_run_group_id,
                    group,
                    summary=summary,
                    get_run_group=self._get_run_group,
                    update_run_group=self._update_run_group,
                )
                _append_required_pause_event(
                    self._append_run_event,
                    run_id,
                    "group.run.approval_required",
                    _approval_root_group_event_payload(
                        owned_run_group_id,
                        projected_group,
                        summary=summary,
                        public_pending=projection.public_pending_approval(),
                    ),
                    event_fence=event_fence,
                )
                projected_root_group = True
        timeline[:] = next_timeline
        if projected_root_group:
            result = self._get_run(result["run_id"])
        return result

    def pause_for_child(
        self,
        run: dict[str, Any],
        *,
        result_text: str,
        timeline_event: dict[str, Any],
        event_type: str,
        event_payload: dict[str, Any],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_event_type: str = "",
        child_event_payload: dict[str, Any] | None = None,
        child_pending_approval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically pauses a parent while its child owns the approval."""

        run_id = str(run["run_id"])
        next_timeline = [
            deepcopy(event)
            for event in timeline
            if isinstance(event, dict)
        ]
        next_timeline.append(deepcopy(timeline_event))
        next_artifacts = [
            deepcopy(item)
            for item in artifacts
            if isinstance(item, dict)
        ]
        projected_root_group = False
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._get_run(run_id) if callable(self._get_run) else run
            current_status = str(current.get("status") or "").strip().lower()
            caller_version = str(run.get("updated_at") or "").strip()
            if caller_version and str(current.get("updated_at") or "") != caller_version:
                return current
            if current_status in {
                "approval_required",
                "completed",
                "failed",
                "cancelled",
                "canceled",
            } or current.get("pending_approval"):
                return current
            root_group_snapshot = _approval_root_group_snapshot(
                current,
                get_run_group=self._get_run_group,
                update_run_group=self._update_run_group,
            )
            result = self._update_run(
                run_id,
                status="approval_required",
                result=result_text,
                timeline=next_timeline,
                artifacts=next_artifacts,
                pending_approval=None,
                expected_status=current_status,
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                return self._get_run(run_id) if callable(self._get_run) else run
            event_fence = {
                "expected_status": "approval_required",
                "expected_updated_at": str(result.get("updated_at") or ""),
            }
            if child_event_type and isinstance(child_event_payload, dict):
                _append_required_pause_event(
                    self._append_run_event,
                    run_id,
                    child_event_type,
                    child_event_payload,
                    event_fence=event_fence,
                )
            _append_required_pause_event(
                self._append_run_event,
                run_id,
                event_type,
                event_payload,
                event_fence=event_fence,
            )
            if root_group_snapshot is not None:
                owned_run_group_id, group = root_group_snapshot
                projected_group = _project_approval_root_group(
                    owned_run_group_id,
                    group,
                    summary=result_text,
                    get_run_group=self._get_run_group,
                    update_run_group=self._update_run_group,
                )
                _append_required_pause_event(
                    self._append_run_event,
                    run_id,
                    "group.run.approval_required",
                    _approval_root_group_event_payload(
                        owned_run_group_id,
                        projected_group,
                        summary=result_text,
                        public_pending=public_pending_approval(
                            child_pending_approval
                            if isinstance(child_pending_approval, dict)
                            else {}
                        ),
                    ),
                    event_fence=event_fence,
                )
                projected_root_group = True
        timeline[:] = next_timeline
        artifacts[:] = next_artifacts
        if projected_root_group:
            result = self._get_run(result["run_id"])
        return result
