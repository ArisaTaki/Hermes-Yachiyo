"""Tests for core runtime service setup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.core_services import (
    RuntimeCoreServiceBundle,
    build_runtime_core_services,
)
from apps.shell.agent.runtime.events import RuntimeRunEventRecorder
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder
from apps.shell.agent.tools.policy import RuntimePolicyCompiler
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_core_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeCoreServiceBundle is RuntimeCoreServiceBundle


def test_build_runtime_core_services_wires_recorders_policy_and_model_profiles() -> None:
    run_events = object()

    bundle = build_runtime_core_services(
        run_events=run_events,
        timeline_factory=lambda event, detail="", **extra: {"event": event, "detail": detail, **extra},
        profile_service_factory=lambda: object(),
        supports_openai_compatible_api=lambda _provider: True,
        default_agent_ids={"builtin:yachiyo-main"},
        error_type=agent_runtime.AgentRuntimeError,
    )

    assert isinstance(bundle, RuntimeCoreServiceBundle)
    assert isinstance(bundle.runtime_events, RuntimeRunEventRecorder)
    assert isinstance(bundle.runtime_agent_timeline, RuntimeAgentTimelineBuilder)
    assert isinstance(bundle.runtime_policy, RuntimePolicyCompiler)
    assert isinstance(bundle.model_profile_resolver, RuntimeModelProfileResolver)
    assert bundle.runtime_events._repository is run_events


def test_native_runtime_installs_core_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_events, RuntimeRunEventRecorder)
        assert isinstance(service.runtime_agent_timeline, RuntimeAgentTimelineBuilder)
        assert isinstance(service.runtime_policy, RuntimePolicyCompiler)
        assert isinstance(service.model_profile_resolver, RuntimeModelProfileResolver)
        assert service.runtime_events._repository is service.run_events
    finally:
        service.close()
