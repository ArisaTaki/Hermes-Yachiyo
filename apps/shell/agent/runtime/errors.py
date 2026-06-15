"""Runtime exception types shared across Agent runtime modules."""

from __future__ import annotations

from typing import Any


class AgentRuntimeError(RuntimeError):
    """Raised when an Agent Studio operation cannot be completed."""


class AgentApprovalRequired(AgentRuntimeError):  # noqa: N818 - existing runtime API name.
    """Raised internally when a run must pause for user approval."""

    def __init__(self, pending_approval: dict[str, Any]) -> None:
        self.pending_approval = pending_approval
        super().__init__(f"等待审批：{pending_approval.get('tool') or 'tool'}")
