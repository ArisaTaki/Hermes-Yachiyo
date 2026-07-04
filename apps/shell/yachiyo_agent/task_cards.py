"""Chat-facing task card mapping compatibility exports."""

from __future__ import annotations

from .contracts import AgentTaskLightSnapshot, AgentTaskSnapshot, ApprovalCardSnapshot
from .policy import task_requires_user_action
from .task_snapshots import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads


def agent_task_light_snapshot_from_task(task: AgentTaskSnapshot) -> AgentTaskLightSnapshot:
    pending_approval = _pending_task_approval(task)
    return AgentTaskLightSnapshot(
        task_id=task.task_id,
        conversation_id=task.conversation_id,
        title=task.title,
        status=task.status,
        detail=task.current_step or task.progress_text or task.summary,
        needs_user_action=task_requires_user_action(task),
        pending_approval=pending_approval,
        task_progress=task.task_progress,
        open_in_studio_url=task.open_in_studio_url,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _pending_task_approval(task: AgentTaskSnapshot) -> ApprovalCardSnapshot | None:
    for approval in task.pending_approvals:
        if approval.status == "pending":
            return approval
    return task.pending_approvals[0] if task.pending_approvals else None


__all__ = [
    "agent_task_light_snapshot_from_task",
    "agent_task_snapshot_from_payload",
    "agent_task_snapshots_from_payloads",
]
