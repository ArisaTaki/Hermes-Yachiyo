"""Run state projection coordinators."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext
from packages.security import redact_sensitive_text


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


def _public_pending_approval(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    if not raw:
        return {}
    input_preview = raw.get("input_preview")
    if input_preview:
        public_input_preview = _tool_input_preview(input_preview)
    else:
        public_input_preview = _tool_input_preview(raw.get("input") or {})
    return {
        "approval_id": str(raw.get("approval_id") or ""),
        "tool": str(raw.get("tool") or ""),
        "input_preview": public_input_preview,
        "requested_at": str(raw.get("requested_at") or ""),
    }


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
        public_pending = _public_pending_approval(private_pending)
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
