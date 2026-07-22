"""Approval reject and timeout transition service."""

from __future__ import annotations

from contextlib import nullcontext
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
        claim_pending_rejection: Callable[..., bool],
        claim_pending_timeout: Callable[..., bool],
        approvals: Any,
        project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
        project_cancelled_workflow_group_if_root: Callable[
            [dict[str, Any], dict[str, Any]],
            dict[str, Any],
        ],
        cancel_run: Callable[[str], dict[str, Any]],
        error_type: type[Exception] = RuntimeError,
        transaction_scope: Callable[..., Any] | None = None,
        close_run_owned_browser_target: Callable[[dict[str, Any]], Any] | None = None,
        project_agent_run_group_if_root: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._get_run = get_run
        self._pending_approval_private = pending_approval_private
        self._claim_pending_rejection = claim_pending_rejection
        self._claim_pending_timeout = claim_pending_timeout
        self._approvals = approvals
        self._project_child_run_transition = project_child_run_transition
        self._project_cancelled_workflow_group_if_root = project_cancelled_workflow_group_if_root
        self._cancel_run = cancel_run
        self._error_type = error_type
        self._transaction_scope = transaction_scope
        self._close_run_owned_browser_target = (
            close_run_owned_browser_target or (lambda _run: None)
        )
        self._project_agent_run_group_if_root = project_agent_run_group_if_root

    def reject(
        self,
        run_id: str,
        reason: str = "",
        *,
        expected_approval_id: str = "",
    ) -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] != "approval_required":
            return run
        pending = self._pending_approval_private(run_id)
        pending_id = _pending_approval_id(pending)
        expected_id = str(expected_approval_id or "").strip() or pending_id
        if not expected_id:
            raise self._error_type("approval_expected_id_required")
        if pending_id != expected_id:
            raise self._error_type("approval_generation_mismatch")
        result, should_project = self._project_transition(
            run,
            pending or {},
            expected_id=expected_id,
            reason=reason,
            claim=self._claim_pending_rejection,
            workflow_projection=self._approvals.reject_workflow_node,
            tool_projection=self._approvals.reject_tool_run,
        )
        if result is None:
            return self._get_run(run_id)
        if not should_project:
            return result
        self._close_run_owned_browser_target(result)
        if run["kind"] == "workflow_run":
            return self._project_cancelled_workflow_group_if_root(run, result)
        return self._project_child_run_transition(result)

    def timeout(
        self,
        run_id: str,
        reason: str = "approval_wait_timeout",
        *,
        expected_approval_id: str = "",
    ) -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] != "approval_required":
            return run
        pending = self._pending_approval_private(run_id)
        pending_id = _pending_approval_id(pending)
        expected_id = str(expected_approval_id or "").strip() or pending_id
        if not expected_id:
            raise self._error_type("approval_expected_id_required")
        if pending_id != expected_id:
            return run
        result, should_project = self._project_transition(
            run,
            pending or {},
            expected_id=expected_id,
            reason=reason,
            claim=self._claim_pending_timeout,
            workflow_projection=self._approvals.timeout_workflow_node,
            tool_projection=self._approvals.timeout_tool_run,
        )
        if result is None:
            return self._get_run(run_id)
        if not should_project:
            return result
        self._close_run_owned_browser_target(result)
        if run["kind"] == "workflow_run":
            return self._project_cancelled_workflow_group_if_root(run, result)
        return self._project_child_run_transition(result)

    def _project_transition(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        expected_id: str,
        reason: str,
        claim: Callable[..., bool],
        workflow_projection: Callable[..., dict[str, Any] | None],
        tool_projection: Callable[..., dict[str, Any] | None],
    ) -> tuple[dict[str, Any] | None, bool]:
        run_id = str(run["run_id"])
        scope = (
            self._transaction_scope()
            if self._transaction_scope is not None
            else nullcontext()
        )
        terminal: dict[str, Any] | None = None
        try:
            with scope:
                if not claim(
                    run_id,
                    pending,
                    expected_approval_id=expected_id,
                ):
                    return None, False
                if run["kind"] == "workflow_run" and str(
                    pending.get("tool") or ""
                ) == "workflow.approval":
                    approval_context = WorkflowApprovalTransitionContext.from_pending(pending)
                    result = workflow_projection(
                        run_id,
                        timeline=[*run["timeline"]],
                        reason=reason,
                        workflow_node_id=approval_context.workflow_node_id,
                        label=approval_context.label,
                        criteria=approval_context.criteria,
                        input_preview=approval_context.input_preview,
                        expected_approval_id=expected_id,
                    )
                else:
                    approval_context = ToolApprovalTransitionContext.from_pending(pending)
                    result = tool_projection(
                        run_id,
                        timeline=[*run["timeline"]],
                        reason=reason,
                        tool_name=approval_context.tool_name,
                        input_preview=approval_context.input_preview,
                        expected_approval_id=expected_id,
                    )
                if result is None:
                    current = self._get_run(run_id)
                    if str(current.get("status") or "") in {
                        "cancelled",
                        "canceled",
                        "completed",
                        "failed",
                    }:
                        terminal = current
                    else:
                        raise _ApprovalTransitionProjectionConflict
                elif (
                    run.get("kind") == "agent_run"
                    and self._project_agent_run_group_if_root is not None
                ):
                    self._project_agent_run_group_if_root(result)
        except _ApprovalTransitionProjectionConflict:
            return None, False
        if terminal is not None:
            return terminal, False
        return result, True


class _ApprovalTransitionProjectionConflict(Exception):
    pass


def _pending_approval_id(pending: dict[str, Any] | None) -> str:
    if not isinstance(pending, dict):
        return ""
    return str(pending.get("approval_id") or "").strip()
