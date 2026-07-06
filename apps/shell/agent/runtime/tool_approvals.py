"""Tool approval resume contexts and projections."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.budget import RunBudget
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_requests import (
    MAX_AGENT_TOOL_ITERATIONS,
    normalize_tool_iteration,
    normalize_tool_name,
)
from apps.shell.agent.runtime.events import tool_input_preview as _tool_input_preview
from packages.security import redact_api_error_text

_PENDING_APPROVAL_CONTEXT_TEXT_KEYS = (
    "source_run_id",
    "source_runnable_id",
    "source_runnable_name",
    "member_agent_id",
    "member_agent_name",
    "agent_id",
    "agent_name",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
    "group_id",
    "group_run_id",
    "run_group_id",
    "core_id",
    "workspace_id",
    "task_id",
    "source",
    "planning_reason",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "replan_request_id",
    "replan_trigger",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
)
_PENDING_APPROVAL_CONTEXT_BOOL_KEYS = (
    "requires_observation",
    "requires_post_action_verification",
)
_PENDING_APPROVAL_CONTEXT_LIST_KEYS = (
    "replan_triggers",
    "replan_signal_ids",
)
_PENDING_APPROVAL_CONTEXT_MAPPING_KEYS = (
    "runtime_execution_envelope",
    "yachiyo_execution_envelope",
    "runtime_execution_metadata",
)


class ToolPendingApprovalBuilder:
    """Builds private pending-approval payloads for tool approvals."""

    def __init__(self, *, approval_id_factory: Any, now: Any) -> None:
        self._approval_id_factory = approval_id_factory
        self._now = now

    def build(
        self,
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        context = _pending_approval_context(tool_request)
        input_preview = _pending_approval_input_preview(
            _tool_input_preview(raw_input),
            context,
        )
        return {
            "approval_id": str(self._approval_id_factory()),
            "tool": normalize_tool_name(tool_request.get("tool")),
            "input": deepcopy(raw_input),
            "input_preview": input_preview,
            "requested_at": str(self._now()),
            "messages": deepcopy(messages),
            "tool_request": deepcopy(tool_request),
            "remaining_tool_requests": deepcopy(remaining_tool_requests),
            "next_iteration": normalize_tool_iteration(next_iteration),
            **context,
        }


@dataclass
class ToolApprovalResumeContext:
    """Private execution context needed to resume an approved tool call."""

    run_id: str
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    broker: Any
    allowed_tools: list[str]
    budget: RunBudget
    messages: list[dict[str, Any]]
    tool_request: dict[str, Any]
    tool_name: str
    input_preview: dict[str, Any]
    remaining_requests: list[dict[str, Any]]
    next_iteration: int

    @classmethod
    def from_run(
        cls,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        broker: Any,
        allowed_tools: list[str],
        budget: RunBudget | None = None,
        budget_factory: Any | None = None,
    ) -> "ToolApprovalResumeContext":
        run_id = str(run["run_id"])
        messages = (
            deepcopy(pending.get("messages"))
            if isinstance(pending.get("messages"), list)
            else []
        )
        tool_request = (
            deepcopy(pending.get("tool_request"))
            if isinstance(pending.get("tool_request"), dict)
            else {}
        )
        if not messages or not tool_request:
            raise AgentRuntimeError("Run 待审批上下文不完整，无法恢复")
        timeline = [
            deepcopy(event)
            for event in run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [
            deepcopy(item)
            for item in run.get("artifacts") or []
            if isinstance(item, dict)
        ]
        remaining = pending.get("remaining_tool_requests")
        remaining_requests = (
            [
                deepcopy(item)
                for item in remaining
                if isinstance(item, dict)
            ]
            if isinstance(remaining, list)
            else []
        )
        allowed_tool_names = list(allowed_tools)
        next_iteration = normalize_tool_iteration(pending.get("next_iteration"))
        tool_name = str(tool_request.get("tool") or pending.get("tool") or "").strip()
        run_budget = budget
        if run_budget is None:
            if budget_factory is None:
                raise AgentRuntimeError("Run 待审批预算上下文不完整，无法恢复")
            run_budget = budget_factory(run_id, timeline)
        return cls(
            run_id=run_id,
            timeline=timeline,
            artifacts=artifacts,
            broker=broker,
            allowed_tools=allowed_tool_names,
            budget=run_budget,
            messages=messages,
            tool_request=tool_request,
            tool_name=tool_name,
            input_preview=_pending_approval_resume_input_preview(pending, tool_request),
            remaining_requests=remaining_requests,
            next_iteration=next_iteration,
        )


def _pending_approval_context(tool_request: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in _PENDING_APPROVAL_CONTEXT_TEXT_KEYS:
        value = str(tool_request.get(key) or "").strip()
        if value:
            context[key] = value
    for key in _PENDING_APPROVAL_CONTEXT_BOOL_KEYS:
        value = tool_request.get(key)
        if isinstance(value, bool):
            context[key] = value
    for key in _PENDING_APPROVAL_CONTEXT_LIST_KEYS:
        value = tool_request.get(key)
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                context[key] = items
    for key in _PENDING_APPROVAL_CONTEXT_MAPPING_KEYS:
        value = tool_request.get(key)
        if isinstance(value, dict):
            context[key] = deepcopy(value)
    return context


def _pending_approval_input_preview(
    input_preview: Any,
    context: dict[str, Any],
) -> Any:
    if not isinstance(input_preview, dict) or not context:
        return input_preview
    preview = dict(input_preview)
    for key, value in context.items():
        preview_value = _tool_input_preview(value) if isinstance(value, dict) else value
        preview.setdefault(key, deepcopy(preview_value))
    return preview


def _pending_approval_resume_input_preview(
    pending: dict[str, Any],
    tool_request: dict[str, Any],
) -> dict[str, Any]:
    pending_preview = pending.get("input_preview")
    if isinstance(pending_preview, dict):
        computed = deepcopy(pending_preview)
    else:
        raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        computed = _tool_input_preview(raw_input)
    computed = _pending_approval_input_preview(
        computed,
        _pending_approval_context(tool_request),
    )
    return dict(computed) if isinstance(computed, dict) else {}


@dataclass(frozen=True)
class ToolApprovalClaimProjection:
    """Running projection after an approved tool claim succeeds."""

    run_id: str
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    tool_name: str
    input_preview: dict[str, Any]
    resumed_detail: str
    running_result: str

    @classmethod
    def from_context(
        cls,
        run_id: str,
        context: ToolApprovalResumeContext,
        *,
        resumed_detail: str,
        running_result: str,
    ) -> "ToolApprovalClaimProjection":
        return cls(
            run_id=run_id,
            timeline=context.timeline,
            artifacts=context.artifacts,
            tool_name=context.tool_name,
            input_preview=context.input_preview,
            resumed_detail=resumed_detail,
            running_result=running_result,
        )

    def project(self, approve_tool_run: Any) -> dict[str, Any]:
        return approve_tool_run(
            self.run_id,
            timeline=self.timeline,
            artifacts=self.artifacts,
            tool_name=self.tool_name,
            input_preview=self.input_preview,
            resumed_detail=self.resumed_detail,
            running_result=self.running_result,
        )


@dataclass(frozen=True)
class ToolApprovalExecutionRequest:
    """Approved tool call request assembled from resume context."""

    tool_request: dict[str, Any]
    allowed_tools: list[str]
    broker: Any
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    run_id: str
    budget: RunBudget

    @classmethod
    def from_context(
        cls,
        context: ToolApprovalResumeContext,
    ) -> "ToolApprovalExecutionRequest":
        return cls(
            tool_request=context.tool_request,
            allowed_tools=context.allowed_tools,
            broker=context.broker,
            timeline=context.timeline,
            artifacts=context.artifacts,
            run_id=context.run_id,
            budget=context.budget,
        )

    def execute(self, call_agent_tool: Any) -> Any:
        return call_agent_tool(
            self.tool_request,
            self.allowed_tools,
            self.broker,
            self.timeline,
            artifacts=self.artifacts,
            approved=True,
            run_id=self.run_id,
            budget=self.budget,
        )


@dataclass(frozen=True)
class ToolApprovalContinuationHandoff:
    """Continuation payload after an approved tool call has been executed."""

    agent: dict[str, Any]
    user_goal: str
    broker: Any
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    start_iteration: int
    run_id: str
    budget: RunBudget

    @classmethod
    def from_context(
        cls,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> "ToolApprovalContinuationHandoff":
        return cls(
            agent=agent,
            user_goal="",
            broker=context.broker,
            timeline=context.timeline,
            artifacts=context.artifacts,
            messages=context.messages,
            start_iteration=context.next_iteration,
            run_id=context.run_id,
            budget=context.budget,
        )


@dataclass(frozen=True)
class ToolApprovalCustomApiContinuationRequest:
    """Custom API continuation call assembled from approved-tool handoff."""

    handoff: ToolApprovalContinuationHandoff

    @classmethod
    def from_handoff(
        cls,
        handoff: ToolApprovalContinuationHandoff,
    ) -> "ToolApprovalCustomApiContinuationRequest":
        return cls(handoff=handoff)

    def execute(self, continue_custom_api_agent: Any) -> str:
        return continue_custom_api_agent(
            self.handoff.agent,
            self.handoff.user_goal,
            self.handoff.broker,
            self.handoff.timeline,
            self.handoff.artifacts,
            messages=self.handoff.messages,
            start_iteration=self.handoff.start_iteration,
            run_id=self.handoff.run_id,
            budget=self.handoff.budget,
        )


@dataclass(frozen=True)
class ToolApprovalContinuationOutcome:
    """Projection outcome after continuing a run with an approved tool result."""

    kind: str
    result_text: str = ""
    pending_approval: Any = None
    safe_error: str = ""

    @classmethod
    def completed(cls, result_text: str) -> "ToolApprovalContinuationOutcome":
        return cls(kind="completed", result_text=result_text)

    @classmethod
    def approval_required(
        cls,
        pending_approval: dict[str, Any],
        *,
        prepare_required: Any | None = None,
    ) -> "ToolApprovalContinuationOutcome":
        pending_next = pending_approval
        if prepare_required is not None:
            pending_next = prepare_required(pending_next)
        return cls(kind="approval_required", pending_approval=pending_next)

    @classmethod
    def failed(
        cls,
        error: Any,
        *,
        redact_error: Any = redact_api_error_text,
    ) -> "ToolApprovalContinuationOutcome":
        return cls(kind="failed", safe_error=redact_error(error))

    def project(
        self,
        context: ToolApprovalResumeContext,
        *,
        project_completed: Any,
        project_required: Any,
        project_failed: Any,
    ) -> dict[str, Any]:
        if self.kind == "completed":
            return project_completed(context, self.result_text)
        if self.kind == "approval_required":
            return project_required(context, self.pending_approval)
        if self.kind == "failed":
            return project_failed(context, self.safe_error)
        raise AgentRuntimeError(f"Unknown approved-tool continuation outcome: {self.kind}")


@dataclass(frozen=True)
class ToolApprovalExecutionFailureProjection:
    """Fatal failure projection for an approved tool execution."""

    tool_name: str
    input_preview: dict[str, Any]
    tool_result: Any
    detail: str

    @classmethod
    def from_context(
        cls,
        context: ToolApprovalResumeContext,
        tool_result: Any,
        detail: str,
    ) -> "ToolApprovalExecutionFailureProjection":
        return cls(
            tool_name=context.tool_name or "tool",
            input_preview=context.input_preview,
            tool_result=tool_result,
            detail=detail,
        )

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "agent.tool.failed",
            self.tool_name,
            input_preview=self.input_preview,
            result=self.tool_result,
            status="failed",
        )


@dataclass(frozen=True)
class ToolApprovalExecutionFollowup:
    """Follow-up execution after an approved tool succeeds."""

    messages: list[dict[str, Any]]
    tool_request: dict[str, Any]
    tool_result: Any
    remaining_requests: list[dict[str, Any]]
    allowed_tools: list[str]
    broker: Any
    timeline: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    next_iteration: int
    run_id: str
    budget: RunBudget

    @classmethod
    def from_context(
        cls,
        context: ToolApprovalResumeContext,
        tool_result: Any,
    ) -> "ToolApprovalExecutionFollowup":
        return cls(
            messages=context.messages,
            tool_request=context.tool_request,
            tool_result=tool_result,
            remaining_requests=context.remaining_requests,
            allowed_tools=context.allowed_tools,
            broker=context.broker,
            timeline=context.timeline,
            artifacts=context.artifacts,
            next_iteration=context.next_iteration,
            run_id=context.run_id,
            budget=context.budget,
        )

    def apply(
        self,
        append_tool_result_message: Any,
        run_tool_requests: Any,
    ) -> None:
        append_tool_result_message(self.messages, self.tool_request, self.tool_result)
        run_tool_requests(
            self.remaining_requests,
            self.allowed_tools,
            self.broker,
            self.messages,
            self.timeline,
            self.artifacts,
            next_iteration=self.next_iteration,
            run_id=self.run_id,
            budget=self.budget,
        )


@dataclass(frozen=True)
class ToolApprovalTransitionContext:
    """Shared public context for tool approval reject/timeout transitions."""

    tool_name: str
    input_preview: Any

    @classmethod
    def from_pending(cls, pending: dict[str, Any]) -> "ToolApprovalTransitionContext":
        tool_request = pending.get("tool_request") if isinstance(pending.get("tool_request"), dict) else {}
        return cls(
            tool_name=str(tool_request.get("tool") or pending.get("tool") or "").strip(),
            input_preview=_tool_input_preview(
                tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
            ),
        )
