"""Tests for runtime recorder setup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import (
    RuntimeAgentRunEventRecorder,
    RuntimeTaskEventRecorder,
    RuntimeTaskModelEventBuilder,
    RuntimeToolCallEventRecorder,
    RuntimeTraceEventBuilder,
    ToolEventPayloadBuilder,
)
from apps.shell.agent.runtime.recorders import (
    RuntimeRecorderBundle,
    build_runtime_recorders,
    build_tool_pending_approval,
)
from apps.shell.agent.runtime.tool_approvals import ToolPendingApprovalBuilder
from apps.shell.agent.runtime.tool_requests import ToolRequestParser
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_recorder_setup_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRecorderBundle is RuntimeRecorderBundle


def test_build_runtime_recorders_wires_parser_events_and_approvals() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, object]) -> None:
        events.append((run_id, event_type, payload))

    bundle = build_runtime_recorders(
        append_run_event=append_run_event,
        now=lambda: "2026-06-15T10:00:00Z",
        approval_id_factory=lambda: "approval_fixed",
    )

    assert isinstance(bundle, RuntimeRecorderBundle)
    assert isinstance(bundle.tool_request_parser, ToolRequestParser)
    assert isinstance(bundle.runtime_agent_run_events, RuntimeAgentRunEventRecorder)
    assert isinstance(bundle.tool_event_payloads, ToolEventPayloadBuilder)
    assert isinstance(bundle.runtime_tool_call_events, RuntimeToolCallEventRecorder)
    assert isinstance(bundle.runtime_task_model_events, RuntimeTaskModelEventBuilder)
    assert isinstance(bundle.runtime_task_events, RuntimeTaskEventRecorder)
    assert isinstance(bundle.runtime_trace_events, RuntimeTraceEventBuilder)
    assert isinstance(bundle.tool_pending_approvals, ToolPendingApprovalBuilder)

    bundle.runtime_agent_run_events.started(
        "run-1",
        agent_id="agent-1",
        agent_name="Researcher",
        backend="native_profile",
        runtime="oha_agent",
    )

    pending = bundle.tool_pending_approvals.build(
        {"tool": "workspace_read", "input": {"path": "README.md"}},
        messages=[],
        next_iteration=1,
        remaining_tool_requests=[],
    )

    assert events[0][1] == "agent.run.started"
    assert pending["approval_id"] == "approval_fixed"
    assert pending["requested_at"] == "2026-06-15T10:00:00Z"
    assert pending["tool"] == "workspace.read"


def test_build_tool_pending_approval_uses_shared_defaults_and_overrides() -> None:
    pending = build_tool_pending_approval(
        {"tool": "terminal_run", "input": {"command": "printf ok"}},
        messages=[],
        next_iteration=1,
        remaining_tool_requests=[],
        now=lambda: "2026-06-15T10:00:00Z",
        approval_id_factory=lambda: "approval_fixed",
    )

    assert pending["approval_id"] == "approval_fixed"
    assert pending["tool"] == "terminal.run"
    assert pending["requested_at"] == "2026-06-15T10:00:00Z"


def test_native_runtime_installs_recorder_bundle_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.tool_request_parser, ToolRequestParser)
        assert isinstance(service.runtime_agent_run_events, RuntimeAgentRunEventRecorder)
        assert isinstance(service.tool_event_payloads, ToolEventPayloadBuilder)
        assert isinstance(service.runtime_tool_call_events, RuntimeToolCallEventRecorder)
        assert isinstance(service.runtime_task_model_events, RuntimeTaskModelEventBuilder)
        assert isinstance(service.runtime_task_events, RuntimeTaskEventRecorder)
        assert isinstance(service.runtime_trace_events, RuntimeTraceEventBuilder)
        assert isinstance(service.tool_pending_approvals, ToolPendingApprovalBuilder)

        pending = service._make_pending_approval(
            {"tool": "workspace_read", "input": {"path": "README.md"}},
            messages=[],
            next_iteration=1,
            remaining_tool_requests=[],
        )

        assert str(pending["approval_id"]).startswith("approval_")
        assert pending["tool"] == "workspace.read"
    finally:
        service.close()
