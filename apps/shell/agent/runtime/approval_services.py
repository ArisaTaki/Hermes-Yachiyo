"""Approval service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.approval_execution import (
    RuntimeApprovalExecutionService,
    RuntimeApprovalRunDispatcher,
)
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_transitions import RuntimeApprovalTransitionService
from apps.shell.agent.runtime.config import MAIN_CHAT_AGENT_ID
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.tool_approval_resume import RuntimeToolApprovalResumeService


@dataclass(frozen=True)
class RuntimeApprovalServiceBundle:
    approval_pause: ApprovalPauseProjectionCoordinator
    approvals: ApprovalCoordinator
    approval_resume: ApprovalResumeCoordinator


@dataclass(frozen=True)
class RuntimeApprovalRuntimeServiceBundle:
    approval_transitions: RuntimeApprovalTransitionService
    tool_approval_resume: RuntimeToolApprovalResumeService
    approval_resume_dispatcher: RuntimeApprovalRunDispatcher
    approval_execution: RuntimeApprovalExecutionService


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
            append_run_event=append_run_event,
        ),
    )


def build_runtime_approval_runtime_services(
    *,
    get_run: Callable[[str], dict[str, Any]],
    pending_approval_private: Callable[[str], dict[str, Any] | None],
    approvals: Any,
    project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
    project_cancelled_workflow_group_if_root: Callable[
        [dict[str, Any], dict[str, Any]],
        dict[str, Any],
    ],
    cancel_run: Callable[[str], dict[str, Any]],
    get_agent_private: Callable[[str], dict[str, Any]],
    compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
    load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
    tool_brokers: Any,
    run_budget: Callable[[str, list[dict[str, Any]]], Any],
    resume_approved_tool_run: Callable[..., dict[str, Any]],
    main_chat_agent_config: Callable[..., dict[str, Any]],
    main_chat_pending_approval: Callable[..., dict[str, Any]],
    default_chat_profile_id: Callable[[], str],
    project_agent_running: Callable[[dict[str, Any]], dict[str, Any]],
    project_agent_completed: Callable[..., dict[str, Any]],
    project_main_chat_completed: Callable[..., dict[str, Any]],
    approve_workflow_run: Callable[[dict[str, Any]], dict[str, Any]],
    approve_main_chat_run: Callable[[dict[str, Any]], dict[str, Any]],
    execution_lock: Any,
    execution_in_progress: set[str],
) -> RuntimeApprovalRuntimeServiceBundle:
    approval_transitions = RuntimeApprovalTransitionService(
        get_run=get_run,
        pending_approval_private=pending_approval_private,
        approvals=approvals,
        project_child_run_transition=project_child_run_transition,
        project_cancelled_workflow_group_if_root=project_cancelled_workflow_group_if_root,
        cancel_run=cancel_run,
    )
    tool_approval_resume = RuntimeToolApprovalResumeService(
        pending_approval_private=pending_approval_private,
        get_agent_private=get_agent_private,
        compile_agent_runtime=compile_agent_runtime,
        load_agent_skills=load_agent_skills,
        tool_brokers=tool_brokers,
        run_budget=run_budget,
        resume_approved_tool_run=resume_approved_tool_run,
        main_chat_agent_config=main_chat_agent_config,
        main_chat_pending_approval=main_chat_pending_approval,
        default_chat_profile_id=default_chat_profile_id,
        project_agent_running=project_agent_running,
        project_agent_completed=project_agent_completed,
        project_main_chat_completed=project_main_chat_completed,
        project_child_run_transition=project_child_run_transition,
        redact_agent_error=redact_secrets,
        main_chat_agent_id=MAIN_CHAT_AGENT_ID,
        error_type=AgentRuntimeError,
    )
    approval_resume_dispatcher = RuntimeApprovalRunDispatcher(
        approve_workflow_run=approve_workflow_run,
        approve_main_chat_run=approve_main_chat_run,
        approve_agent_run=tool_approval_resume.approve_agent_run,
        error_type=AgentRuntimeError,
    )
    return RuntimeApprovalRuntimeServiceBundle(
        approval_transitions=approval_transitions,
        tool_approval_resume=tool_approval_resume,
        approval_resume_dispatcher=approval_resume_dispatcher,
        approval_execution=RuntimeApprovalExecutionService(
            execution_lock=execution_lock,
            execution_in_progress=execution_in_progress,
            get_run=get_run,
            approve_once=approval_resume_dispatcher.approve_once,
        ),
    )
