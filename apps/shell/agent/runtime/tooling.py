"""Runtime tool-loop setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.agent_context import (
    agent_goal_disallows_tool,
    user_goal_from_agent_messages,
)
from apps.shell.agent.runtime.budget import tool_result_limiter
from apps.shell.agent.runtime.config import MARKET_AGENT_OPERATING_DOCTRINE
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value, tool_input_preview
from apps.shell.agent.runtime.model_messages import (
    ModelOutputText,
    coalesce_model_message,
    message_visible_content_text,
    model_message_metadata,
)
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_requests import (
    MAX_AGENT_TOOL_ITERATIONS,
    normalize_tool_iteration,
    normalize_tool_name,
)
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    MEMORY_TOOL_NAMES,
    PolicyGate,
)


@dataclass(frozen=True)
class RuntimeToolingBundle:
    tool_loop_projection: RuntimeToolLoopProjectionBuilder
    tool_call_executor: RuntimeToolCallExecutor
    tool_request_runner: RuntimeToolRequestRunner


@dataclass(frozen=True)
class RuntimeToolingStack:
    tooling: RuntimeToolingBundle
    tool_operations: RuntimeToolOperations
    custom_api_agent_loop: RuntimeCustomApiAgentLoop


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


def build_runtime_tooling_stack(
    *,
    runtime_limits: Callable[[], Any],
    runtime_run_budget: Callable[[str, list[dict[str, Any]]], Any],
    runtime_timeline_factory: Callable[..., dict[str, Any]],
    runtime_context_budget_checker: Callable[[Any, list[dict[str, Any]]], None],
    runtime_model_output_limiter: Callable[[Any], tuple[str, bool]],
    tool_call_events: Any,
    trace_events: Any,
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    pending_approval_builder: Any,
    call_agent_tool: Callable[..., dict[str, Any]],
    agent_model_config_private: Callable[[dict[str, Any]], dict[str, Any]],
    compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
    call_model: Callable[..., Any],
    tool_requests_from_message: Callable[[dict[str, Any], str], list[dict[str, Any]]],
    run_tool_requests: Callable[..., None],
) -> RuntimeToolingStack:
    tooling = build_runtime_tooling(
        normalize_tool_name=normalize_tool_name,
        input_preview=tool_input_preview,
        run_budget=runtime_run_budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=tool_result_limiter(
            limits=runtime_limits,
            redact_json_value=redact_json_value,
        ),
        timeline_factory=runtime_timeline_factory,
        tool_call_events=tool_call_events,
        trace_events=trace_events,
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
        user_goal_from_messages=user_goal_from_agent_messages,
        goal_disallows_tool=agent_goal_disallows_tool,
        pending_approval_builder=pending_approval_builder,
        call_agent_tool=call_agent_tool,
    )
    tool_operations = RuntimeToolOperations(
        tool_request_runner=tooling.tool_request_runner,
        tool_call_executor=tooling.tool_call_executor,
    )
    return RuntimeToolingStack(
        tooling=tooling,
        tool_operations=tool_operations,
        custom_api_agent_loop=RuntimeCustomApiAgentLoop(
            agent_model_config_private=agent_model_config_private,
            compile_agent_runtime=compile_agent_runtime,
            run_budget=runtime_run_budget,
            check_context_budget=runtime_context_budget_checker,
            tool_schemas=RuntimeToolOperations.model_tool_schemas,
            normalize_tool_iteration=normalize_tool_iteration,
            max_tool_iterations=MAX_AGENT_TOOL_ITERATIONS,
            operating_doctrine=MARKET_AGENT_OPERATING_DOCTRINE,
            memory_tool_names=MEMORY_TOOL_NAMES,
            future_task_tool_names=FUTURE_TASK_TOOL_NAMES,
            call_model=call_model,
            coalesce_model_message=coalesce_model_message,
            message_visible_content_text=message_visible_content_text,
            model_message_metadata=model_message_metadata,
            tool_requests_from_message=tool_requests_from_message,
            timeline_factory=runtime_timeline_factory,
            limit_model_output=runtime_model_output_limiter,
            model_output_text_factory=ModelOutputText,
            tool_loop_projection=tooling.tool_loop_projection,
            run_tool_requests=run_tool_requests,
            error_type=AgentRuntimeError,
        ),
    )
