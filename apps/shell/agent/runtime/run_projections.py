"""Run state projection coordinators."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.approval_snapshots import public_pending_approval
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext


class RunProjectionCoordinator:
    """Synchronizes secondary projections after run rows or facts change."""

    def __init__(
        self,
        *,
        run_artifacts: Any,
        run_approvals: Any,
        task_run_links: Any,
    ) -> None:
        self._run_artifacts = run_artifacts
        self._run_approvals = run_approvals
        self._task_run_links = task_run_links

    def sync(
        self,
        run_id: str,
        *,
        status: str,
        artifacts: Any,
        pending_approval: dict[str, Any],
    ) -> None:
        artifact_snapshot = deepcopy(artifacts)
        pending_snapshot = (
            deepcopy(pending_approval)
            if isinstance(pending_approval, dict)
            else {}
        )
        self._run_artifacts.sync(run_id, artifact_snapshot)
        self._run_approvals.sync(run_id, status=status, pending_approval=pending_snapshot)
        self._task_run_links.sync_projection(run_id, status=status)

    def sync_event_cursor(self, run_id: str, *, sequence: int) -> None:
        self._task_run_links.sync_projection(
            run_id,
            last_event_sequence=int(sequence or 0),
        )


class AgentRunGroupProjectionCoordinator:
    """Synchronizes root Agent Run state back to its Run Group summary."""

    def __init__(
        self,
        *,
        get_run_group: Any,
        update_run_group: Any,
    ) -> None:
        self._get_run_group = get_run_group
        self._update_run_group = update_run_group

    def update_if_root(self, run: dict[str, Any]) -> None:
        run_group_id = str(run.get("run_group_id") or "")
        if not run_group_id:
            return
        try:
            group = self._get_run_group(run_group_id)
        except KeyError:
            return
        child_run_ids = [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item)
        ]
        if group.get("source") in {"agent", "delegation"} or child_run_ids == [run.get("run_id")]:
            self._update_run_group(
                run_group_id,
                status=str(run.get("status") or ""),
                summary=str(run.get("result") or ""),
            )


class ApprovalResumeProjectionCoordinator:
    """Projects Run state changes produced by approved-tool resume."""

    def __init__(
        self,
        *,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        update_agent_run_group_if_root: Any,
        mark_parent_workflows_child_running: Any,
    ) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._update_agent_run_group_if_root = update_agent_run_group_if_root
        self._mark_parent_workflows_child_running = mark_parent_workflows_child_running

    def project_agent_running(self, running: dict[str, Any]) -> dict[str, Any]:
        self._update_agent_run_group_if_root(running)
        self._mark_parent_workflows_child_running(running)
        return running

    def project_agent_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        context.timeline.append(self._timeline("agent.run.completed", "Agent run completed"))
        self._append_run_event(context.run_id, "agent.run.completed", {"result": result_text})
        return self._update_run(
            context.run_id,
            status="completed",
            result=result_text,
            timeline=context.timeline,
            artifacts=context.artifacts,
            pending_approval=None,
        )

    def project_main_chat_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        context.timeline.append(
            self._timeline(
                "model.output.ready",
                result_text[:500],
                output_chars=len(result_text),
            )
        )
        self._append_run_event(
            context.run_id,
            "model.output.completed",
            {"content": result_text, "output_chars": len(result_text)},
        )
        return self._update_run(
            context.run_id,
            status="running",
            result=result_text,
            timeline=context.timeline,
            artifacts=context.artifacts,
            pending_approval=None,
        )

    def project_required(
        self,
        context: ToolApprovalResumeContext,
        pending_approval: dict[str, Any],
    ) -> dict[str, Any]:
        private_pending = deepcopy(pending_approval)
        public_pending = public_pending_approval(private_pending)
        tool_name = str(private_pending.get("tool") or "")
        context.timeline.append(
            self._timeline(
                "agent.tool.approval_required",
                tool_name,
                pending_approval=public_pending,
            )
        )
        self._append_run_event(
            context.run_id,
            "agent.tool.approval_required",
            public_pending,
        )
        return self._update_run(
            context.run_id,
            status="approval_required",
            result=f"等待审批：{tool_name or 'tool'}",
            timeline=context.timeline,
            artifacts=context.artifacts,
            pending_approval=private_pending,
        )

    def project_failed(
        self,
        context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        context.timeline.append(self._timeline("agent.run.failed", safe_error))
        self._append_run_event(context.run_id, "agent.run.failed", {"error": safe_error})
        return self._update_run(
            context.run_id,
            status="failed",
            result=safe_error,
            timeline=context.timeline,
            artifacts=context.artifacts,
            pending_approval=None,
        )
