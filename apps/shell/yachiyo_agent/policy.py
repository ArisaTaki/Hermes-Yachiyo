"""Product-level helpers for approval-aware surfaces."""

from __future__ import annotations

from .contracts import AgentTaskSnapshot, ApprovalCardSnapshot


def approval_is_pending(approval: ApprovalCardSnapshot) -> bool:
    return approval.status == "pending"


def task_requires_user_action(task: AgentTaskSnapshot) -> bool:
    return task.needs_user_action or any(
        approval_is_pending(item) for item in task.pending_approvals
    )
