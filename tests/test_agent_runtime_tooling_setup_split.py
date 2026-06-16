"""Tests for runtime tooling setup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tooling import (
    RuntimeToolingBundle,
    RuntimeToolingStack,
    build_runtime_tooling,
    build_runtime_tooling_stack,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_tooling_setup_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeToolingBundle is RuntimeToolingBundle
    assert agent_runtime.RuntimeToolingStack is RuntimeToolingStack
    assert agent_runtime._build_runtime_tooling_stack is build_runtime_tooling_stack


def test_build_runtime_tooling_wires_executor_runner_and_shared_loop_projection() -> None:
    pending_approval_builder = object()
    tool_call_events = object()
    trace_events = object()
    allows_tool = lambda _tool_name, _allowed_tools: True

    bundle = build_runtime_tooling(
        normalize_tool_name=lambda value: str(value or "").replace("_", "."),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: object(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=lambda event, detail="", **extra: {"event": event, "detail": detail, **extra},
        tool_call_events=tool_call_events,
        trace_events=trace_events,
        append_run_event=lambda _run_id, _event_type, _payload: None,
        user_goal_from_messages=lambda _messages: "",
        goal_disallows_tool=lambda _user_goal, _tool_name: "",
        pending_approval_builder=pending_approval_builder,
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True},
        allows_tool=allows_tool,
    )

    assert isinstance(bundle, RuntimeToolingBundle)
    assert isinstance(bundle.tool_loop_projection, RuntimeToolLoopProjectionBuilder)
    assert isinstance(bundle.tool_call_executor, RuntimeToolCallExecutor)
    assert isinstance(bundle.tool_request_runner, RuntimeToolRequestRunner)
    assert bundle.tool_request_runner._tool_loop_projection is bundle.tool_loop_projection
    assert bundle.tool_request_runner._pending_approval_builder is pending_approval_builder
    assert bundle.tool_call_executor._tool_call_events is tool_call_events
    assert bundle.tool_call_executor._trace_events is trace_events
    assert bundle.tool_call_executor._allows_tool is allows_tool


def test_build_runtime_tooling_stack_wires_policy_budget_and_custom_loop() -> None:
    stack = build_runtime_tooling_stack(
        runtime_limits=lambda: RunBudgetLimits(max_tool_output_chars=5),
        runtime_run_budget=lambda _run_id, _timeline: object(),
        runtime_timeline_factory=lambda event, detail="", **extra: {"event": event, "detail": detail, **extra},
        runtime_context_budget_checker=lambda _budget, _messages: None,
        runtime_model_output_limiter=lambda value: (str(value), False),
        tool_call_events=object(),
        trace_events=object(),
        append_run_event=lambda _run_id, _event_type, _payload: None,
        pending_approval_builder=object(),
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True},
        agent_model_config_private=lambda _agent: {},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": []},
            "workspace_policy": {},
        },
        call_model=lambda *_args, **_kwargs: {"role": "assistant", "content": "ok"},
        tool_requests_from_message=lambda _message, _content: [],
        run_tool_requests=lambda *_args, **_kwargs: None,
    )

    assert isinstance(stack, RuntimeToolingStack)
    assert isinstance(stack.tooling, RuntimeToolingBundle)
    assert isinstance(stack.tool_operations, RuntimeToolOperations)
    assert stack.tool_operations._tool_request_runner is stack.tooling.tool_request_runner
    assert stack.tool_operations._tool_call_executor is stack.tooling.tool_call_executor
    assert stack.custom_api_agent_loop._tool_loop_projection is stack.tooling.tool_loop_projection
    assert stack.custom_api_agent_loop._tool_schemas is RuntimeToolOperations.model_tool_schemas
    assert stack.tooling.tool_call_executor._validate_tool_payload is RuntimeToolOperations.validate_tool_payload
    assert getattr(stack.tooling.tool_call_executor._limit_tool_result, "__self__", None) is None


def test_native_runtime_installs_tooling_bundle_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.tool_loop_projection, RuntimeToolLoopProjectionBuilder)
        assert isinstance(service.tool_call_executor, RuntimeToolCallExecutor)
        assert isinstance(service.tool_request_runner, RuntimeToolRequestRunner)
        assert service.tool_request_runner._tool_loop_projection is service.tool_loop_projection
        assert service.tool_request_runner._pending_approval_builder is service.tool_pending_approvals
        assert getattr(service.tool_request_runner._run_budget, "__self__", None) is not service
        assert getattr(service.tool_call_executor._run_budget, "__self__", None) is not service
        assert service.tool_call_executor._tool_call_events is service.runtime_tool_call_events
        assert service.tool_call_executor._trace_events is service.runtime_trace_events
        assert service.tool_call_executor._allows_tool is agent_runtime.PolicyGate.allows_tool
        assert service.tool_call_executor._validate_tool_payload is RuntimeToolOperations.validate_tool_payload
        assert getattr(service.tool_call_executor._limit_tool_result, "__self__", None) is not service

        service.runtime_limits = RunBudgetLimits(max_tool_output_chars=5)
        limited = service.tool_call_executor._limit_tool_result({"ok": True, "content": "abcdefghi"})
        assert limited["truncated"] is True
        assert limited["content"] == "abcde"
    finally:
        service.close()
