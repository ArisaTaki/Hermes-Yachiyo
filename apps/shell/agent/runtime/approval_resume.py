"""Approved-tool resume orchestration."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalClaimProjection,
    ToolApprovalContinuationHandoff,
    ToolApprovalContinuationOutcome,
    ToolApprovalCustomApiContinuationRequest,
    ToolApprovalExecutionFailureProjection,
    ToolApprovalExecutionFollowup,
    ToolApprovalExecutionRequest,
    ToolApprovalResumeContext,
)
from packages.security import redact_api_error_text


class ApprovalResumeCoordinator:
    """Executes the approved tool portion of a paused run resume."""

    def __init__(
        self,
        *,
        call_agent_tool: Any,
        fatal_tool_failure_detail: Any,
        append_tool_result_message: Any,
        run_tool_requests: Any,
        timeline_factory: Any,
        claim_pending_approval: Any | None = None,
        approve_tool_run: Any | None = None,
        continue_custom_api_agent: Any | None = None,
    ) -> None:
        self._call_agent_tool = call_agent_tool
        self._fatal_tool_failure_detail = fatal_tool_failure_detail
        self._append_tool_result_message = append_tool_result_message
        self._run_tool_requests = run_tool_requests
        self._timeline = timeline_factory
        self._claim_pending_approval = claim_pending_approval
        self._approve_tool_run = approve_tool_run
        self._continue_custom_api_agent = continue_custom_api_agent

    def claim_and_project_approved_tool(
        self,
        run_id: str,
        pending: dict[str, Any],
        context: ToolApprovalResumeContext,
        *,
        resumed_detail: str,
        running_result: str,
    ) -> dict[str, Any] | None:
        if self._claim_pending_approval is None or self._approve_tool_run is None:
            raise AgentRuntimeError(
                "Approval resume coordinator is missing approval projection callbacks"
            )
        if not self._claim_pending_approval(run_id, pending):
            return None
        projection = ToolApprovalClaimProjection.from_context(
            run_id,
            context,
            resumed_detail=resumed_detail,
            running_result=running_result,
        )
        return projection.project(self._approve_tool_run)

    def execute_approved_tool(self, context: ToolApprovalResumeContext) -> None:
        request = ToolApprovalExecutionRequest.from_context(context)
        tool_result = request.execute(self._call_agent_tool)
        fatal_failure = self._fatal_tool_failure_detail(
            context.tool_name,
            context.tool_request,
            tool_result,
        )
        if fatal_failure:
            failure = ToolApprovalExecutionFailureProjection.from_context(
                context,
                tool_result,
                fatal_failure,
            )
            context.timeline.append(failure.timeline_event(self._timeline))
            raise AgentRuntimeError(failure.detail)
        followup = ToolApprovalExecutionFollowup.from_context(
            context,
            tool_result,
        )
        followup.apply(
            self._append_tool_result_message,
            self._run_tool_requests,
        )

    def continue_custom_api_agent_after_approved_tool(
        self,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> str:
        if self._continue_custom_api_agent is None:
            raise AgentRuntimeError(
                "Approval resume coordinator is missing custom API continuation"
            )
        handoff = self.continuation_handoff_after_approved_tool(agent, context)
        request = ToolApprovalCustomApiContinuationRequest.from_handoff(handoff)
        return request.execute(self._continue_custom_api_agent)

    def continuation_handoff_after_approved_tool(
        self,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> ToolApprovalContinuationHandoff:
        self.execute_approved_tool(context)
        return ToolApprovalContinuationHandoff.from_context(agent, context)

    def continue_and_project_after_approved_tool(
        self,
        *,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
        project_completed: Any,
        project_required: Any,
        project_failed: Any,
        prepare_required: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        try:
            result_text = self.continue_custom_api_agent_after_approved_tool(
                agent,
                context,
            )
            outcome = ToolApprovalContinuationOutcome.completed(result_text)
        except AgentApprovalRequired as exc:
            outcome = ToolApprovalContinuationOutcome.approval_required(
                exc.pending_approval,
                prepare_required=prepare_required,
            )
        except Exception as exc:
            outcome = ToolApprovalContinuationOutcome.failed(
                exc,
                redact_error=redact_error,
            )
        return outcome.project(
            context,
            project_completed=project_completed,
            project_required=project_required,
            project_failed=project_failed,
        )

    def resume_approved_tool_run(
        self,
        *,
        run_id: str,
        pending: dict[str, Any],
        context: ToolApprovalResumeContext,
        agent: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        project_completed: Any,
        project_required: Any,
        project_failed: Any,
        get_current_run: Any,
        project_running: Any | None = None,
        prepare_required: Any | None = None,
        project_result: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        running = self.claim_and_project_approved_tool(
            run_id,
            pending,
            context,
            resumed_detail=resumed_detail,
            running_result=running_result,
        )
        if running is None:
            return get_current_run(run_id)
        if project_running is not None:
            running = project_running(running)
        result = self.continue_and_project_after_approved_tool(
            agent=agent,
            context=context,
            project_completed=project_completed,
            project_required=project_required,
            project_failed=project_failed,
            prepare_required=prepare_required,
            redact_error=redact_error,
        )
        return project_result(result) if project_result is not None else result
