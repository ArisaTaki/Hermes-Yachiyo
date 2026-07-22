"""Approval lifecycle projections for replayable Run facts."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import Any
from uuid import uuid4

from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.approval_snapshots import ApprovalSnapshotBuilder
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_approvals import (
    ensure_pending_approval_request_fingerprint,
)
from packages.security import redact_sensitive_text


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


class ApprovalPauseProjectionCoordinator:
    """Projects a run into the public pending-approval state."""

    def __init__(
        self,
        *,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        get_run: Any,
        snapshots: ApprovalSnapshotBuilder | None = None,
        approval_generation_factory: Any | None = None,
        transaction_scope: Any | None = None,
        get_run_group: Any | None = None,
        update_run_group: Any | None = None,
    ) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._get_run = get_run
        self._snapshots = snapshots or ApprovalSnapshotBuilder()
        self._approval_generation_factory = (
            approval_generation_factory
            or (lambda: f"generation-{uuid4().hex[:12]}")
        )
        self._transaction_scope = transaction_scope
        self._get_run_group = get_run_group
        self._update_run_group = update_run_group

    def project_tool_required(
        self,
        run_id: str,
        *,
        pending_approval: dict[str, Any],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        private_pending = (
            deepcopy(pending_approval)
            if isinstance(pending_approval, dict)
            else {}
        )
        ensure_pending_approval_request_fingerprint(private_pending)
        approval_id = str(private_pending.get("approval_id") or "").strip()
        if approval_id and _approval_id_already_projected(timeline, approval_id):
            generation = str(self._approval_generation_factory() or "").strip()
            if generation:
                private_pending["approval_id"] = f"{approval_id}-{generation}"
        public_pending = self._snapshots.public_pending_approval(private_pending)
        internal_trace = self._snapshots.internal_pending_approval_trace(private_pending)
        tool_name = str(private_pending.get("tool") or "")
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "agent.tool.approval_required",
                tool_name,
                pending_approval=public_pending,
            )
        )
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._get_run(run_id)
            current_status = str(current.get("status") or "").strip().lower()
            if current_status in {
                "approval_required",
                "completed",
                "failed",
                "cancelled",
                "canceled",
            } or current.get("pending_approval"):
                return current
            root_group = _approval_root_group_snapshot(
                current,
                get_run_group=self._get_run_group,
                update_run_group=self._update_run_group,
            )
            result = self._update_run(
                run_id,
                status="approval_required",
                result=f"等待审批：{tool_name or 'tool'}",
                timeline=next_timeline,
                artifacts=artifacts,
                pending_approval=private_pending,
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
                "agent.tool.approval_required",
                public_pending,
                event_fence=event_fence,
            )
            if (
                internal_trace
                and supports_keyword(self._append_run_event, "visibility")
                and supports_keyword(self._append_run_event, "sensitivity")
            ):
                _append_required_pause_event(
                    self._append_run_event,
                    run_id,
                    "agent.tool.approval_trace",
                    internal_trace,
                    event_fence=event_fence,
                    visibility="internal",
                    sensitivity="private",
                )
            if root_group is not None:
                run_group_id, group = root_group
                summary = f"等待审批：{tool_name or 'tool'}"
                projected_group = _project_approval_root_group(
                    run_group_id,
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
                        run_group_id,
                        projected_group,
                        summary=summary,
                        public_pending=public_pending,
                    ),
                    event_fence=event_fence,
                )
        timeline[:] = next_timeline
        return result


def _append_required_pause_event(
    append_run_event: Any,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    event_fence: dict[str, str],
    **event_fields: Any,
) -> None:
    supported_fence = {
        key: value
        for key, value in event_fence.items()
        if supports_keyword(append_run_event, key)
    }
    event = append_run_event(
        run_id,
        event_type,
        payload,
        **supported_fence,
        **event_fields,
    )
    if supported_fence and event is None:
        raise AgentRuntimeError("run_event_fence_mismatch")


def _approval_root_group_snapshot(
    run: dict[str, Any],
    *,
    get_run_group: Any | None,
    update_run_group: Any | None,
) -> tuple[str, dict[str, Any]] | None:
    if run.get("project_root_group") is not True:
        return None
    run_group_id = str(run.get("run_group_id") or "").strip()
    if not run_group_id:
        raise AgentRuntimeError("approval_pause_root_group_id_required")
    if not callable(get_run_group) or not callable(update_run_group):
        raise AgentRuntimeError("approval_pause_root_group_projection_unavailable")
    try:
        group = get_run_group(run_group_id)
    except (AttributeError, KeyError) as exc:
        raise AgentRuntimeError("approval_pause_root_group_missing") from exc
    if _is_terminal_group_status(group.get("status")):
        raise AgentRuntimeError("run_group_terminal_outcome_conflict")
    return run_group_id, group


def _project_approval_root_group(
    run_group_id: str,
    group: dict[str, Any],
    *,
    summary: str,
    get_run_group: Any,
    update_run_group: Any,
) -> dict[str, Any]:
    if _approval_group_projection_matches(group, summary=summary):
        return group
    updated = update_run_group(
        run_group_id,
        status="approval_required",
        summary=summary,
        expected_status=str(group.get("status") or ""),
        expected_updated_at=str(group.get("updated_at") or ""),
    )
    if updated is not None:
        return updated
    try:
        winner = get_run_group(run_group_id)
    except (AttributeError, KeyError) as exc:
        raise AgentRuntimeError("approval_pause_root_group_missing") from exc
    if _approval_group_projection_matches(winner, summary=summary):
        return winner
    if _is_terminal_group_status(winner.get("status")):
        raise AgentRuntimeError("run_group_terminal_outcome_conflict")
    raise AgentRuntimeError("run_group_projection_cas_lost")


def _approval_root_group_event_payload(
    run_group_id: str,
    group: dict[str, Any],
    *,
    summary: str,
    public_pending: dict[str, Any],
) -> dict[str, Any]:
    return {
        "child_run_ids": [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item)
        ],
        "group_run_id": run_group_id,
        "run_group_id": run_group_id,
        "status": "approval_required",
        "summary": summary,
        "pending_approval": public_pending,
    }


def _approval_group_projection_matches(
    group: dict[str, Any],
    *,
    summary: str,
) -> bool:
    return (
        str(group.get("status") or "").strip().lower() == "approval_required"
        and str(group.get("summary") or "") == summary
    )


def _is_terminal_group_status(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "completed",
        "failed",
        "cancelled",
        "canceled",
    }


def _approval_id_already_projected(
    timeline: list[dict[str, Any]],
    approval_id: str,
) -> bool:
    expected = str(approval_id or "").strip()
    if not expected:
        return False
    for event in timeline:
        if not isinstance(event, dict):
            continue
        if str(event.get("event") or event.get("event_type") or "").strip() != (
            "agent.tool.approval_required"
        ):
            continue
        pending = (
            event.get("pending_approval")
            if isinstance(event.get("pending_approval"), dict)
            else {}
        )
        if str(pending.get("approval_id") or "").strip() == expected:
            return True
    return False


class ApprovalCoordinator:
    """Coordinates approval lifecycle transitions and replayable facts."""

    def __init__(
        self,
        *,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        transaction_scope: Any | None = None,
    ) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._transaction_scope = transaction_scope

    def approve_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        tool_name: str,
        input_preview: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        expected_approval_id: str = "",
    ) -> dict[str, Any] | None:
        display_tool = str(tool_name or "tool").strip() or "tool"
        preview_snapshot = deepcopy(input_preview)
        event_payload = {
            "tool": display_tool,
            "input_preview": preview_snapshot,
            "status": "completed",
        }
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "agent.tool.approval_approved",
                display_tool,
                input_preview=preview_snapshot,
                status="completed",
            )
        )
        next_timeline.append(
            self._timeline(
                "agent.run.resumed",
                resumed_detail,
                status="running",
            )
        )
        expected_id = str(expected_approval_id or "").strip()
        update_kwargs: dict[str, Any] = {}
        if expected_id:
            update_kwargs = {
                "expected_status": "approval_required",
                "expected_approval_id": expected_id,
            }
        scope = (
            self._transaction_scope()
            if self._transaction_scope is not None
            else nullcontext()
        )
        with scope:
            result = self._update_run(
                run_id,
                status="running",
                result=running_result,
                timeline=next_timeline,
                artifacts=artifacts,
                pending_approval=None,
                **update_kwargs,
            )
            if result is None:
                return None
            _append_fenced_run_event(
                self._append_run_event,
                run_id,
                "agent.tool.approval_approved",
                event_payload,
                _terminal_event_fence(result, status="running"),
            )
        timeline[:] = next_timeline
        return result

    def approve_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        result_context: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
        expected_approval_id: str,
    ) -> dict[str, Any] | None:
        expected_id = str(expected_approval_id or "").strip()
        if not expected_id:
            raise AgentRuntimeError("approval_expected_id_required")
        preview_snapshot = deepcopy(input_preview)
        event_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": preview_snapshot,
            "status": "completed",
        }
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "workflow.node.approval_approved",
                label,
                **event_payload,
            )
        )
        result = self._update_run(
            run_id,
            status="running",
            result=result_context,
            timeline=next_timeline,
            artifacts=artifacts,
            pending_approval=None,
            expected_status="approval_required",
            expected_approval_id=expected_id,
        )
        if result is None:
            return None
        timeline[:] = next_timeline
        self._append_run_event(run_id, "workflow.node.approval_approved", event_payload)
        return result

    def reject_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
        expected_approval_id: str = "",
    ) -> dict[str, Any] | None:
        detail = _redact_secrets(reason).strip() or f"{label} approval rejected"
        preview_snapshot = deepcopy(input_preview)
        timeline_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": preview_snapshot,
            "status": "cancelled",
        }
        event_payload = {**timeline_payload, "reason": detail}
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "workflow.node.approval_rejected",
                detail,
                **timeline_payload,
            )
        )
        next_timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        update_kwargs: dict[str, Any] = {}
        expected_id = str(expected_approval_id or "").strip()
        if expected_id:
            update_kwargs = {
                "expected_status": "approval_required",
                "expected_approval_id": expected_id,
            }
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已拒绝：{detail}",
            timeline=next_timeline,
            pending_approval=None,
            **update_kwargs,
        )
        if result is None:
            return None
        timeline[:] = next_timeline
        self._append_run_event(run_id, "workflow.node.approval_rejected", event_payload)
        self._append_run_event(run_id, "workflow.run.cancelled", event_payload)
        return result

    def reject_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        tool_name: str,
        input_preview: dict[str, Any],
        expected_approval_id: str = "",
    ) -> dict[str, Any] | None:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = _redact_secrets(reason).strip() or "Tool approval rejected"
        preview_snapshot = deepcopy(input_preview)
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "agent.tool.approval_rejected",
                detail,
                tool=timeline_tool,
                input_preview=preview_snapshot,
                status="cancelled",
            )
        )
        update_kwargs: dict[str, Any] = {}
        expected_id = str(expected_approval_id or "").strip()
        if expected_id:
            update_kwargs = {
                "expected_status": "approval_required",
                "expected_approval_id": expected_id,
            }
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已拒绝：{detail}",
            timeline=next_timeline,
            pending_approval=None,
            **update_kwargs,
        )
        if result is None:
            return None
        timeline[:] = next_timeline
        self._append_run_event(
            run_id,
            "agent.tool.approval_rejected",
            {
                "tool": display_tool,
                "input_preview": preview_snapshot,
                "reason": detail,
                "status": "cancelled",
            },
        )
        self._append_run_event(
            run_id,
            "agent.run.cancelled",
            {
                "reason": detail,
                "result": str(result.get("result") or ""),
            },
        )
        return result

    def timeout_workflow_node(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        workflow_node_id: str,
        label: str,
        criteria: str,
        input_preview: dict[str, Any],
        expected_approval_id: str = "",
    ) -> dict[str, Any] | None:
        detail = _redact_secrets(reason).strip() or "approval_wait_timeout"
        preview_snapshot = deepcopy(input_preview)
        timeline_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": preview_snapshot,
            "status": "cancelled",
        }
        event_payload = {
            **timeline_payload,
            "reason": detail,
            "tool": "workflow.approval",
        }
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "workflow.node.approval_timeout",
                detail,
                **timeline_payload,
            )
        )
        next_timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        update_kwargs: dict[str, Any] = {}
        expected_id = str(expected_approval_id or "").strip()
        if expected_id:
            update_kwargs = {
                "expected_status": "approval_required",
                "expected_approval_id": expected_id,
            }
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已超时：{detail}",
            timeline=next_timeline,
            pending_approval=None,
            **update_kwargs,
        )
        if result is None:
            return None
        timeline[:] = next_timeline
        self._append_run_event(run_id, "approval.timeout", event_payload)
        self._append_run_event(run_id, "workflow.run.cancelled", event_payload)
        return result

    def timeout_tool_run(
        self,
        run_id: str,
        *,
        timeline: list[dict[str, Any]],
        reason: str,
        tool_name: str,
        input_preview: dict[str, Any],
        expected_approval_id: str = "",
    ) -> dict[str, Any] | None:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = _redact_secrets(reason).strip() or "approval_wait_timeout"
        preview_snapshot = deepcopy(input_preview)
        next_timeline = list(timeline)
        next_timeline.append(
            self._timeline(
                "agent.tool.approval_timeout",
                detail,
                tool=timeline_tool,
                input_preview=preview_snapshot,
                status="cancelled",
            )
        )
        update_kwargs: dict[str, Any] = {}
        expected_id = str(expected_approval_id or "").strip()
        if expected_id:
            update_kwargs = {
                "expected_status": "approval_required",
                "expected_approval_id": expected_id,
            }
        scope = (
            self._transaction_scope()
            if self._transaction_scope is not None
            else nullcontext()
        )
        with scope:
            result = self._update_run(
                run_id,
                status="cancelled",
                result=f"工具审批已超时：{detail}",
                timeline=next_timeline,
                pending_approval=None,
                **update_kwargs,
            )
            if result is None:
                return None
            event_fence = _terminal_event_fence(result, status="cancelled")
            _append_fenced_run_event(
                self._append_run_event,
                run_id,
                "approval.timeout",
                {
                    "tool": display_tool,
                    "input_preview": preview_snapshot,
                    "reason": detail,
                    "status": "cancelled",
                },
                event_fence,
            )
            _append_fenced_run_event(
                self._append_run_event,
                run_id,
                "agent.run.cancelled",
                {
                    "reason": detail,
                    "result": str(result.get("result") or ""),
                },
                event_fence,
            )
        timeline[:] = next_timeline
        return result


def _terminal_event_fence(
    run: dict[str, Any],
    *,
    status: str,
) -> dict[str, str]:
    return {
        "expected_status": status,
        "expected_updated_at": str(run.get("updated_at") or ""),
    }


def _append_fenced_run_event(
    append_run_event: Any,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    fence: dict[str, str],
) -> None:
    supported_fence = {
        key: value
        for key, value in fence.items()
        if supports_keyword(append_run_event, key)
    }
    event = append_run_event(run_id, event_type, payload, **supported_fence)
    if supported_fence and event is None:
        raise AgentRuntimeError("run_event_fence_mismatch")
