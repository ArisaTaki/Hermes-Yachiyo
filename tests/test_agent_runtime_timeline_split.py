"""Tests for timeline projections split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder, runtime_timeline_factory
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def test_runtime_timeline_factory_redacts_detail_and_payload() -> None:
    factory = runtime_timeline_factory(
        now=lambda: "2026-06-16T00:00:00+00:00",
        redact_detail=lambda value: str(value).replace("secret", "[redacted]"),
        redact_payload=lambda value: {
            key: str(item).replace("secret", "[redacted]")
            for key, item in value.items()
        },
    )

    assert factory("agent.tool.call", "secret detail", path="secret.txt") == {
        "time": "2026-06-16T00:00:00+00:00",
        "event": "agent.tool.call",
        "detail": "[redacted] detail",
        "path": "[redacted].txt",
    }


def test_runtime_agent_timeline_builder_projects_agent_timeline_entries() -> None:
    builder = RuntimeAgentTimelineBuilder(timeline_factory=_timeline)

    assert builder.started(
        "Researcher",
        backend="native_profile",
        runtime="oha_agent",
    ) == {
        "event": "agent.run.started",
        "detail": "Researcher started",
        "backend": "native_profile",
        "runtime": "oha_agent",
    }
    assert builder.compiled(allowed_tools=["workspace.read"]) == {
        "event": "agent.runtime.compiled",
        "detail": "Oha Agent Runtime compiled tools and workspace policy",
        "allowed_tools": ["workspace.read"],
    }
    assert builder.compiled(
        detail="Main chat NativeRunEngine compiled tools and workspace policy",
        allowed_tools=[],
    ) == {
        "event": "agent.runtime.compiled",
        "detail": "Main chat NativeRunEngine compiled tools and workspace policy",
        "allowed_tools": [],
    }
    assert builder.completed() == {
        "event": "agent.run.completed",
        "detail": "Agent run completed",
    }
    assert builder.failed("safe failure") == {
        "event": "agent.run.failed",
        "detail": "safe failure",
    }


def test_agent_runtime_service_uses_runtime_agent_timeline_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeAgentTimelineBuilder is RuntimeAgentTimelineBuilder
        assert isinstance(service.runtime_agent_timeline, RuntimeAgentTimelineBuilder)
        assert getattr(service.runtime_agent_timeline._timeline, "__self__", None) is not service
    finally:
        service.close()
