"""Runtime recorder and parser setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from apps.shell.agent.runtime.events import (
    RuntimeAgentRunEventRecorder,
    RuntimeTaskEventRecorder,
    RuntimeTaskModelEventBuilder,
    RuntimeToolCallEventRecorder,
    RuntimeTraceEventBuilder,
    ToolEventPayloadBuilder,
)
from apps.shell.agent.runtime.tool_approvals import ToolPendingApprovalBuilder
from apps.shell.agent.runtime.tool_requests import ToolRequestParser


@dataclass(frozen=True)
class RuntimeRecorderBundle:
    """Parser and event-recorder collaborators used by NativeRunEngine."""

    tool_request_parser: ToolRequestParser
    runtime_agent_run_events: RuntimeAgentRunEventRecorder
    tool_event_payloads: ToolEventPayloadBuilder
    runtime_tool_call_events: RuntimeToolCallEventRecorder
    runtime_task_model_events: RuntimeTaskModelEventBuilder
    runtime_task_events: RuntimeTaskEventRecorder
    runtime_trace_events: RuntimeTraceEventBuilder
    tool_pending_approvals: ToolPendingApprovalBuilder


def _default_approval_id() -> str:
    return f"approval_{uuid4().hex[:12]}"


def build_runtime_recorders(
    *,
    append_run_event: Callable[[str, str, dict[str, Any]], None],
    now: Callable[[], str],
    approval_id_factory: Callable[[], str] | None = None,
) -> RuntimeRecorderBundle:
    tool_event_payloads = ToolEventPayloadBuilder()
    runtime_task_model_events = RuntimeTaskModelEventBuilder()
    return RuntimeRecorderBundle(
        tool_request_parser=ToolRequestParser(),
        runtime_agent_run_events=RuntimeAgentRunEventRecorder(
            append_run_event=append_run_event,
        ),
        tool_event_payloads=tool_event_payloads,
        runtime_tool_call_events=RuntimeToolCallEventRecorder(
            append_run_event=append_run_event,
            payload_builder=tool_event_payloads,
        ),
        runtime_task_model_events=runtime_task_model_events,
        runtime_task_events=RuntimeTaskEventRecorder(
            append_run_event=append_run_event,
            payload_builder=runtime_task_model_events,
        ),
        runtime_trace_events=RuntimeTraceEventBuilder(),
        tool_pending_approvals=ToolPendingApprovalBuilder(
            approval_id_factory=approval_id_factory or _default_approval_id,
            now=now,
        ),
    )


def build_tool_pending_approval(
    tool_request: dict[str, Any],
    *,
    messages: list[dict[str, Any]],
    next_iteration: int,
    remaining_tool_requests: list[dict[str, Any]],
    now: Callable[[], str],
    approval_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    return ToolPendingApprovalBuilder(
        approval_id_factory=approval_id_factory or _default_approval_id,
        now=now,
    ).build(
        tool_request,
        messages=messages,
        next_iteration=next_iteration,
        remaining_tool_requests=remaining_tool_requests,
    )
