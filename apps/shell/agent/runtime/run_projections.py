"""Run state projection coordinators."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.approval_snapshots import public_pending_approval
from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalResumeContext,
    ensure_pending_approval_request_fingerprint,
)


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
        if run.get("project_root_group") is not True:
            return
        run_group_id = str(run.get("run_group_id") or "")
        if not run_group_id:
            return
        try:
            group = self._get_run_group(run_group_id)
        except KeyError:
            return
        target_status = str(run.get("status") or "").strip().lower()
        target_summary = str(run.get("result") or "")
        if _group_projection_matches(
            group,
            status=target_status,
            summary=target_summary,
        ):
            return
        if _is_terminal_group_status(group.get("status")):
            raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        group_status = str(group.get("status") or "")
        group_updated_at = str(group.get("updated_at") or "")
        group_cas = {}
        if group_status and group_updated_at:
            group_cas = {
                "expected_status": group_status,
                "expected_updated_at": group_updated_at,
            }
        updated = self._update_run_group(
            run_group_id,
            status=target_status,
            summary=target_summary,
            **group_cas,
        )
        if not group_cas or updated is not None:
            return
        try:
            winner = self._get_run_group(run_group_id)
        except KeyError as exc:
            raise AgentRuntimeError("run_group_projection_cas_lost") from exc
        if _group_projection_matches(
            winner,
            status=target_status,
            summary=target_summary,
        ):
            return
        if _is_terminal_group_status(winner.get("status")):
            raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        raise AgentRuntimeError("run_group_projection_cas_lost")


def _group_projection_matches(
    group: dict[str, Any],
    *,
    status: str,
    summary: str,
) -> bool:
    return (
        str(group.get("status") or "").strip().lower() == status
        and str(group.get("summary") or "") == summary
    )


def _is_terminal_group_status(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "completed",
        "failed",
        "cancelled",
        "canceled",
    }


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
        get_run: Any | None = None,
        complete_main_chat_run: Any | None = None,
        fail_main_chat_run: Any | None = None,
    ) -> None:
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._update_agent_run_group_if_root = update_agent_run_group_if_root
        self._mark_parent_workflows_child_running = mark_parent_workflows_child_running
        self._get_run = get_run
        self._complete_main_chat_run = complete_main_chat_run
        self._fail_main_chat_run = fail_main_chat_run

    def project_agent_running(self, running: dict[str, Any]) -> dict[str, Any]:
        self._update_agent_run_group_if_root(running)
        self._mark_parent_workflows_child_running(running)
        return running

    def project_agent_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        next_timeline = [
            *context.timeline,
            self._timeline("agent.run.completed", "Agent run completed"),
        ]
        return self._commit_resume_projection(
            context,
            event_type="agent.run.completed",
            event_payload={"result": result_text},
            status="completed",
            result=result_text,
            timeline=next_timeline,
            artifacts=context.artifacts,
            pending_approval=None,
            project_terminal_group=self._update_agent_run_group_if_root,
        )

    def project_main_chat_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        next_timeline = [
            *context.timeline,
            self._timeline(
                "model.output.ready",
                result_text[:500],
                output_chars=len(result_text),
            ),
        ]
        projected = self._commit_resume_projection(
            context,
            event_type="model.output.completed",
            event_payload={
                "content": result_text,
                "output_chars": len(result_text),
            },
            status="running",
            result=result_text,
            timeline=next_timeline,
            artifacts=context.artifacts,
            pending_approval=None,
        )
        if not _terminal_direct_approval_resume(context):
            return projected
        if str(projected.get("status") or "").strip().lower() != "running":
            return projected
        if self._complete_main_chat_run is None:
            raise AgentRuntimeError("main_chat_approval_completion_lifecycle_required")
        return self._complete_main_chat_run(context.run_id, result_text)

    def project_main_chat_failed(
        self,
        context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        if self._fail_main_chat_run is None:
            raise AgentRuntimeError("main_chat_approval_failure_lifecycle_required")
        return self._fail_main_chat_run(
            context.run_id,
            safe_error,
            timeline=context.timeline,
            artifacts=context.artifacts,
        )

    def project_required(
        self,
        context: ToolApprovalResumeContext,
        pending_approval: dict[str, Any],
    ) -> dict[str, Any]:
        private_pending = deepcopy(pending_approval)
        ensure_pending_approval_request_fingerprint(private_pending)
        public_pending = public_pending_approval(private_pending)
        tool_name = str(private_pending.get("tool") or "")
        next_timeline = [
            *context.timeline,
            self._timeline(
                "agent.tool.approval_required",
                tool_name,
                pending_approval=public_pending,
            ),
        ]
        return self._commit_resume_projection(
            context,
            event_type="agent.tool.approval_required",
            event_payload=public_pending,
            status="approval_required",
            result=f"等待审批：{tool_name or 'tool'}",
            timeline=next_timeline,
            artifacts=context.artifacts,
            pending_approval=private_pending,
        )

    def project_failed(
        self,
        context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        next_timeline = [
            *context.timeline,
            self._timeline("agent.run.failed", safe_error),
        ]
        return self._commit_resume_projection(
            context,
            event_type="agent.run.failed",
            event_payload={"error": safe_error},
            status="failed",
            result=safe_error,
            timeline=next_timeline,
            artifacts=context.artifacts,
            pending_approval=None,
            project_terminal_group=self._update_agent_run_group_if_root,
        )

    def _commit_resume_projection(
        self,
        context: ToolApprovalResumeContext,
        *,
        event_type: str,
        event_payload: dict[str, Any],
        project_terminal_group: Any | None = None,
        **update_fields: Any,
    ) -> dict[str, Any]:
        _set_resume_projection_state(context, "pending")
        approval_id = str(context.approval_id or "").strip()
        if not approval_id:
            if self._get_run is None:
                raise RuntimeError(
                    "legacy approval resume projection requires a fresh Run reader"
                )
            current = self._get_run(context.run_id)
            current_status = str(current.get("status") or "").strip().lower()
            if current_status in {
                "approval_required",
                "completed",
                "failed",
                "cancelled",
                "canceled",
            } or current.get("pending_approval"):
                _set_resume_projection_state(context, "cas_lost")
                return current
            result = self._update_run(
                context.run_id,
                **update_fields,
                expected_status=current_status,
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                _set_resume_projection_state(context, "cas_lost")
                return self._get_run(context.run_id)
            self._append_committed_run_event(
                context,
                event_type,
                event_payload,
                result,
            )
            _flush_buffered_resume_projection_events(context, result)
            if project_terminal_group is not None:
                project_terminal_group(result)
            _commit_resume_context_lists(context, update_fields)
            _set_resume_projection_state(context, "committed")
            return result
        result = self._update_run(
            context.run_id,
            **update_fields,
            expected_status="running",
            expected_approval_id=approval_id,
        )
        if result is None:
            if self._get_run is None:
                raise RuntimeError("approval resume projection lost its Run CAS")
            _set_resume_projection_state(context, "cas_lost")
            return self._get_run(context.run_id)
        self._append_committed_run_event(
            context,
            event_type,
            event_payload,
            result,
        )
        _flush_buffered_resume_projection_events(context, result)
        if project_terminal_group is not None:
            project_terminal_group(result)
        _commit_resume_context_lists(context, update_fields)
        _set_resume_projection_state(context, "committed")
        return result

    def _append_committed_run_event(
        self,
        context: ToolApprovalResumeContext,
        event_type: str,
        event_payload: dict[str, Any],
        run: dict[str, Any],
    ) -> None:
        pending_events = getattr(
            context,
            "_approval_resume_pending_events",
            None,
        )
        if isinstance(pending_events, list):
            pending_events.append(
                (
                    context.run_id,
                    event_type,
                    deepcopy(event_payload),
                    {},
                )
            )
            return
        fence: dict[str, str] = {}
        if supports_keyword(self._append_run_event, "expected_status"):
            fence["expected_status"] = str(run.get("status") or "")
        if supports_keyword(self._append_run_event, "expected_updated_at"):
            fence["expected_updated_at"] = str(run.get("updated_at") or "")
        event = self._append_run_event(
            context.run_id,
            event_type,
            event_payload,
            **fence,
        )
        if fence and event is None:
            raise AgentRuntimeError("run_event_fence_mismatch")


def _commit_resume_context_lists(
    context: ToolApprovalResumeContext,
    update_fields: dict[str, Any],
) -> None:
    timeline = update_fields.get("timeline")
    if isinstance(timeline, list):
        context.timeline[:] = timeline
    artifacts = update_fields.get("artifacts")
    if isinstance(artifacts, list):
        context.artifacts[:] = artifacts


def _set_resume_projection_state(
    context: ToolApprovalResumeContext,
    state: str,
) -> None:
    setattr(context, "_approval_resume_projection_state", state)


def _flush_buffered_resume_projection_events(
    context: ToolApprovalResumeContext,
    projected: dict[str, Any],
) -> None:
    flush_events = getattr(
        context,
        "_approval_resume_flush_events",
        None,
    )
    if callable(flush_events):
        flush_events(projected)


def _terminal_direct_approval_resume(context: ToolApprovalResumeContext) -> bool:
    """Return whether approval resume already produced a terminal runtime fact.

    Model-backed approval resumes intentionally remain ``running`` until the
    outer main-chat lifecycle commits them. Deterministic Runtime Planner
    actions have no later model callback; once their correlated intent
    completion exists, leaving the row running strands an otherwise finished
    task indefinitely.
    """

    source = str(context.tool_request.get("source") or "").strip()
    if source not in {
        "daily_desktop_intent",
        "daily_desktop_metadata",
        "runtime_planner",
    }:
        return False
    last_terminal_index = -1
    for index, event in enumerate(context.timeline):
        if not isinstance(event, dict):
            continue
        event_type = str(
            event.get("event") or event.get("event_type") or ""
        ).strip()
        if event_type == "agent.desktop.intent_completed":
            last_terminal_index = index
    if last_terminal_index < 0:
        return False
    for event in context.timeline[last_terminal_index + 1 :]:
        if not isinstance(event, dict):
            continue
        event_type = str(
            event.get("event") or event.get("event_type") or ""
        ).strip()
        if event_type in {
            "agent.desktop.intent_approval_required",
            "agent.replan.requested",
            "agent.tool.approval_required",
        }:
            return False
    return True
