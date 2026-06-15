"""Runtime tool-loop setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder


@dataclass(frozen=True)
class RuntimeToolingBundle:
    tool_loop_projection: RuntimeToolLoopProjectionBuilder
    tool_call_executor: RuntimeToolCallExecutor
    tool_request_runner: RuntimeToolRequestRunner


def build_runtime_tooling(
    *,
    normalize_tool_name: Callable[[Any], str],
    input_preview: Callable[[Any], Any],
    run_budget: Callable[[str, list[dict[str, Any]]], Any],
    validate_tool_payload: Callable[[str, dict[str, Any]], None],
    limit_tool_result: Callable[[dict[str, Any]], dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    tool_call_events: Any,
    trace_events: Any,
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    user_goal_from_messages: Callable[[list[dict[str, Any]]], str],
    goal_disallows_tool: Callable[[str, str], str],
    pending_approval_builder: Any,
    call_agent_tool: Callable[..., dict[str, Any]],
    allows_tool: Callable[[str, list[str]], bool] | None = None,
) -> RuntimeToolingBundle:
    tool_loop_projection = RuntimeToolLoopProjectionBuilder()
    return RuntimeToolingBundle(
        tool_loop_projection=tool_loop_projection,
        tool_call_executor=RuntimeToolCallExecutor(
            normalize_tool_name=normalize_tool_name,
            input_preview=input_preview,
            run_budget=run_budget,
            validate_tool_payload=validate_tool_payload,
            limit_tool_result=limit_tool_result,
            timeline_factory=timeline_factory,
            tool_call_events=tool_call_events,
            trace_events=trace_events,
            append_run_event=append_run_event,
            allows_tool=allows_tool,
        ),
        tool_request_runner=RuntimeToolRequestRunner(
            normalize_tool_name=normalize_tool_name,
            input_preview=input_preview,
            run_budget=run_budget,
            user_goal_from_messages=user_goal_from_messages,
            goal_disallows_tool=goal_disallows_tool,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            tool_loop_projection=tool_loop_projection,
            pending_approval_builder=pending_approval_builder,
            call_agent_tool=call_agent_tool,
        ),
    )
