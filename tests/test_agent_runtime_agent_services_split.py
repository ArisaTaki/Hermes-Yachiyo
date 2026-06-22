"""Tests for Agent service setup split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_context import AgentContextBuilder
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent.runtime.agent_preparation import RuntimeAgentRunPreparer
from apps.shell.agent.runtime.agent_services import (
    RuntimeAgentServiceBundle,
    build_runtime_agent_services,
)
from apps.shell.agent.runtime.agent_skills import RuntimeAgentSkillLoader
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_agent_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeAgentServiceBundle is RuntimeAgentServiceBundle


def test_build_runtime_agent_services_wires_skill_context_preparation_and_outcomes(
    tmp_path: Path,
) -> None:
    runtime_agent_timeline = object()
    runtime_agent_run_events = object()
    runtime_trace_events = object()
    runtime_task_model_events = object()
    tool_brokers = object()

    def compile_agent_runtime(_agent: dict[str, Any]) -> dict[str, Any]:
        return {
            "runtime": "oha_agent",
            "tool_policy": {"allowed_tools": []},
            "workspace_policy": {},
        }

    bundle = build_runtime_agent_services(
        get_skill=lambda skill_id: {"skill_id": skill_id, "name": "Skill"},
        error_type=agent_runtime.AgentRuntimeError,
        compile_agent_runtime=compile_agent_runtime,
        load_agent_skills=lambda _skill_ids: [],
        long_term_memory_context=lambda: "",
        operating_doctrine="Follow approval gates.",
        agent_artifacts_dir=tmp_path / "artifacts",
        normalize_execution_backend=lambda value, **_kwargs: str(value or "native_profile"),
        agent_context=lambda *_args, **_kwargs: "context",
        memory_store=lambda **_kwargs: object(),
        future_task_store=lambda **_kwargs: object(),
        runtime_agent_timeline=runtime_agent_timeline,
        runtime_agent_run_events=runtime_agent_run_events,
        runtime_trace_events=runtime_trace_events,
        append_run_event=lambda _run_id, _event_type, _payload: None,
        timeline_factory=lambda event, detail="", **extra: {"event": event, "detail": detail, **extra},
        memory_context_limit=12,
        runtime_task_model_events=runtime_task_model_events,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        model_output_metadata=lambda _value: {},
        redact_secrets=lambda value: str(value),
        tool_brokers=tool_brokers,
        agent_desk_context=lambda _agent: "Desk",
    )

    assert isinstance(bundle, RuntimeAgentServiceBundle)
    assert isinstance(bundle.agent_skill_loader, RuntimeAgentSkillLoader)
    assert isinstance(bundle.agent_context_builder, AgentContextBuilder)
    assert isinstance(bundle.agent_run_preparer, RuntimeAgentRunPreparer)
    assert isinstance(bundle.agent_run_outcomes, RuntimeAgentRunOutcomeProjector)
    assert bundle.agent_context_builder._operating_doctrine == "Follow approval gates."
    assert bundle.agent_context_builder._agent_desk_context is not None
    assert bundle.agent_run_preparer._agent_artifacts_dir == tmp_path / "artifacts"
    assert bundle.agent_run_preparer._runtime_agent_timeline is runtime_agent_timeline
    assert bundle.agent_run_preparer._runtime_agent_run_events is runtime_agent_run_events
    assert bundle.agent_run_preparer._runtime_trace_events is runtime_trace_events
    assert bundle.agent_run_preparer._memory_context_limit == 12
    assert bundle.agent_run_preparer._tool_brokers is tool_brokers
    assert bundle.agent_run_preparer._tool_broker_factory is None
    assert bundle.agent_run_outcomes._runtime_task_model_events is runtime_task_model_events
    assert bundle.agent_run_outcomes._runtime_agent_timeline is runtime_agent_timeline
    assert bundle.agent_run_outcomes._runtime_agent_run_events is runtime_agent_run_events


def test_native_runtime_installs_agent_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.agent_skill_loader, RuntimeAgentSkillLoader)
        assert isinstance(service.agent_context_builder, AgentContextBuilder)
        assert isinstance(service.agent_run_preparer, RuntimeAgentRunPreparer)
        assert isinstance(service.agent_run_outcomes, RuntimeAgentRunOutcomeProjector)
        assert service.agent_run_preparer._runtime_agent_timeline is service.runtime_agent_timeline
        assert service.agent_run_preparer._runtime_agent_run_events is service.runtime_agent_run_events
        assert service.agent_run_preparer._runtime_trace_events is service.runtime_trace_events
        assert service.agent_run_preparer._tool_brokers is service.tool_brokers
        assert service.agent_run_preparer._tool_broker_factory is None
        assert service.agent_run_outcomes._runtime_task_model_events is service.runtime_task_model_events
        assert service.agent_run_outcomes._runtime_agent_timeline is service.runtime_agent_timeline
        assert service.agent_run_outcomes._runtime_agent_run_events is service.runtime_agent_run_events
    finally:
        service.close()
