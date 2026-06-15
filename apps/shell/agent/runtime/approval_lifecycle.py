"""Approval lifecycle projections for replayable Run facts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from packages.security import redact_sensitive_text


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


class ApprovalCoordinator:
    """Coordinates approval lifecycle transitions and replayable facts."""

    def __init__(self, *, timeline_factory: Any, append_run_event: Any, update_run: Any) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run

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
    ) -> dict[str, Any]:
        display_tool = str(tool_name or "tool").strip() or "tool"
        preview_snapshot = deepcopy(input_preview)
        event_payload = {
            "tool": display_tool,
            "input_preview": preview_snapshot,
            "status": "completed",
        }
        timeline.append(
            self._timeline(
                "agent.tool.approval_approved",
                display_tool,
                input_preview=preview_snapshot,
                status="completed",
            )
        )
        self._append_run_event(run_id, "agent.tool.approval_approved", event_payload)
        timeline.append(
            self._timeline(
                "agent.run.resumed",
                resumed_detail,
                status="running",
            )
        )
        return self._update_run(
            run_id,
            status="running",
            result=running_result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

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
    ) -> dict[str, Any]:
        preview_snapshot = deepcopy(input_preview)
        event_payload = {
            "workflow_node_id": workflow_node_id,
            "workflow_node_kind": "approval",
            "workflow_node_label": label,
            "workflow_node_approval_criteria": criteria,
            "input_preview": preview_snapshot,
            "status": "completed",
        }
        timeline.append(
            self._timeline(
                "workflow.node.approval_approved",
                label,
                **event_payload,
            )
        )
        self._append_run_event(run_id, "workflow.node.approval_approved", event_payload)
        return self._update_run(
            run_id,
            status="running",
            result=result_context,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

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
    ) -> dict[str, Any]:
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
        timeline.append(
            self._timeline(
                "workflow.node.approval_rejected",
                detail,
                **timeline_payload,
            )
        )
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
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
    ) -> dict[str, Any]:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = _redact_secrets(reason).strip() or "Tool approval rejected"
        preview_snapshot = deepcopy(input_preview)
        timeline.append(
            self._timeline(
                "agent.tool.approval_rejected",
                detail,
                tool=timeline_tool,
                input_preview=preview_snapshot,
                status="cancelled",
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已拒绝：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
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
    ) -> dict[str, Any]:
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
        timeline.append(
            self._timeline(
                "workflow.node.approval_timeout",
                detail,
                **timeline_payload,
            )
        )
        timeline.append(
            self._timeline(
                "workflow.run.cancelled",
                detail,
                **timeline_payload,
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"Workflow 审批已超时：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
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
    ) -> dict[str, Any]:
        timeline_tool = str(tool_name or "").strip()
        display_tool = timeline_tool or "tool"
        detail = _redact_secrets(reason).strip() or "approval_wait_timeout"
        preview_snapshot = deepcopy(input_preview)
        timeline.append(
            self._timeline(
                "agent.tool.approval_timeout",
                detail,
                tool=timeline_tool,
                input_preview=preview_snapshot,
                status="cancelled",
            )
        )
        result = self._update_run(
            run_id,
            status="cancelled",
            result=f"工具审批已超时：{detail}",
            timeline=timeline,
            pending_approval=None,
        )
        self._append_run_event(
            run_id,
            "approval.timeout",
            {
                "tool": display_tool,
                "input_preview": preview_snapshot,
                "reason": detail,
                "status": "cancelled",
            },
        )
        return result
