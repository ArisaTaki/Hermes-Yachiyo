"""Workflow approval execution facade for runtime approval resumes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
)


class RuntimeWorkflowApprovalExecutionService:
    """Builds Workflow approval resume context before handing off to the coordinator."""

    def __init__(
        self,
        *,
        pending_approval_private: Callable[[str], dict[str, Any] | None],
        workflow_for_run_resume: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_run_is_group_root: Callable[[dict[str, Any]], bool],
        workflow_approval_resume: WorkflowApprovalResumeCoordinator,
    ) -> None:
        self._pending_approval_private = pending_approval_private
        self._workflow_for_run_resume = workflow_for_run_resume
        self._workflow_run_is_group_root = workflow_run_is_group_root
        self._workflow_approval_resume = workflow_approval_resume

    def approve_workflow_run(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        pending = self._pending_approval_private(run_id)
        resume_context = WorkflowApprovalResumeContext.from_run(
            run,
            pending,
            workflow=self._workflow_for_run_resume(run),
            root_group=self._workflow_run_is_group_root(run),
        )
        return self._workflow_approval_resume.resume_after_approval(
            run,
            pending,
            resume_context,
        )
