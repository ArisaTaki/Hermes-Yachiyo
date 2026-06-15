"""Approval reject and timeout transition service."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.tool_approvals import ToolApprovalTransitionContext
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalTransitionContext


class RuntimeApprovalTransitionService:
    """Projects approval rejection and timeout transitions for runs."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        pending_approval_private: Callable[[str], dict[str, Any] | None],
        approvals: Any,
        project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
        project_cancelled_workflow_group_if_root: Callable[
            [dict[str, Any], dict[str, Any]],
            dict[str, Any],
        ],
        cancel_run: Callable[[str], dict[str, Any]],
    ) -> None:
        self._get_run = get_run
        self._pending_approval_private = pending_approval_private
        self._approvals = approvals
        self._project_child_run_transition = project_child_run_transition
        self._project_cancelled_workflow_group_if_root = project_cancelled_workflow_group_if_root
        self._cancel_run = cancel_run

    def reject(self, run_id: str, reason: str = "") -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self._pending_approval_private(run_id)
            approval_context = WorkflowApprovalTransitionContext.from_pending(pending)
            result = self._approvals.reject_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=approval_context.workflow_node_id,
                label=approval_context.label,
                criteria=approval_context.criteria,
                input_preview=approval_context.input_preview,
            )
            return self._project_cancelled_workflow_group_if_root(run, result)
        pending = self._pending_approval_private(run_id)
        approval_context = ToolApprovalTransitionContext.from_pending(pending)
        result = self._approvals.reject_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=approval_context.tool_name,
            input_preview=approval_context.input_preview,
        )
        return self._project_child_run_transition(result)

    def timeout(self, run_id: str, reason: str = "approval_wait_timeout") -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            pending = self._pending_approval_private(run_id)
            if not pending or str(pending.get("tool") or "") != "workflow.approval":
                return self._cancel_run(run_id)
            approval_context = WorkflowApprovalTransitionContext.from_pending(pending)
            result = self._approvals.timeout_workflow_node(
                run_id,
                timeline=[*run["timeline"]],
                reason=reason,
                workflow_node_id=approval_context.workflow_node_id,
                label=approval_context.label,
                criteria=approval_context.criteria,
                input_preview=approval_context.input_preview,
            )
            return self._project_cancelled_workflow_group_if_root(run, result)
        pending = self._pending_approval_private(run_id)
        approval_context = ToolApprovalTransitionContext.from_pending(pending)
        result = self._approvals.timeout_tool_run(
            run_id,
            timeline=[*run["timeline"]],
            reason=reason,
            tool_name=approval_context.tool_name,
            input_preview=approval_context.input_preview,
        )
        return self._project_child_run_transition(result)
