"""Approval service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator


@dataclass(frozen=True)
class RuntimeApprovalServiceBundle:
    approval_pause: ApprovalPauseProjectionCoordinator
    approvals: ApprovalCoordinator
    approval_resume: ApprovalResumeCoordinator


def build_runtime_approval_services(
    *,
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    update_run: Callable[..., dict[str, Any]],
    snapshots: Any,
    call_agent_tool: Callable[..., dict[str, Any]],
    fatal_tool_failure_detail: Callable[..., str],
    append_tool_result_message: Callable[..., None],
    run_tool_requests: Callable[..., None],
    claim_pending_approval: Callable[..., bool],
    continue_custom_api_agent: Callable[..., str],
) -> RuntimeApprovalServiceBundle:
    approvals = ApprovalCoordinator(
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        update_run=update_run,
    )
    return RuntimeApprovalServiceBundle(
        approval_pause=ApprovalPauseProjectionCoordinator(
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            update_run=update_run,
            snapshots=snapshots,
        ),
        approvals=approvals,
        approval_resume=ApprovalResumeCoordinator(
            call_agent_tool=call_agent_tool,
            fatal_tool_failure_detail=fatal_tool_failure_detail,
            append_tool_result_message=append_tool_result_message,
            run_tool_requests=run_tool_requests,
            timeline_factory=timeline_factory,
            claim_pending_approval=claim_pending_approval,
            approve_tool_run=approvals.approve_tool_run,
            continue_custom_api_agent=continue_custom_api_agent,
        ),
    )
