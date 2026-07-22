"""Workflow child approval context projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowChildPendingApprovalProjection:
    """Adds parent Workflow trace context to a child Agent pending approval."""

    child_run_id: str
    pending_approval: dict[str, Any]

    @classmethod
    def from_child_run(
        cls,
        child: Mapping[str, Any],
        *,
        workflow_run_id: str,
        node_info: Mapping[str, Any],
        run_group_id: str = "",
        private_pending_approval: Mapping[str, Any] | None = None,
    ) -> "WorkflowChildPendingApprovalProjection | None":
        if str(child.get("status") or "") != "approval_required":
            return None
        pending = (
            private_pending_approval
            if private_pending_approval
            else child.get("pending_approval")
        )
        if not isinstance(pending, Mapping) or not pending:
            return None
        next_pending = dict(pending)
        for key, value in {
            "workflow_run_id": workflow_run_id,
            **dict(node_info),
            "group_run_id": run_group_id,
            "run_group_id": run_group_id,
        }.items():
            clean_value = str(value or "").strip()
            if clean_value and not str(next_pending.get(key) or "").strip():
                next_pending[key] = clean_value
        if next_pending == dict(pending):
            return None
        return cls(
            child_run_id=str(child.get("run_id") or ""),
            pending_approval=next_pending,
        )

    def project(self, update_run: Any) -> dict[str, Any] | None:
        expected_approval_id = str(self.pending_approval.get("approval_id") or "").strip()
        if not expected_approval_id:
            return None
        return update_run(
            self.child_run_id,
            pending_approval=self.pending_approval,
            expected_status="approval_required",
            expected_approval_id=expected_approval_id,
        )
