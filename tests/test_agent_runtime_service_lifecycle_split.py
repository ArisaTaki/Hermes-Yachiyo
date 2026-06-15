"""Tests for runtime service lifecycle split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.service_lifecycle import RuntimeServiceLifecycle


class FakeRuntimeService:
    def __init__(self) -> None:
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


def test_runtime_service_lifecycle_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeServiceLifecycle is RuntimeServiceLifecycle


def test_runtime_service_lifecycle_lazily_creates_and_closes_once() -> None:
    created: list[FakeRuntimeService] = []

    def factory() -> FakeRuntimeService:
        service = FakeRuntimeService()
        created.append(service)
        return service

    lifecycle = RuntimeServiceLifecycle(factory=factory)

    first = lifecycle.get()
    second = lifecycle.get()
    lifecycle.close()
    lifecycle.close()

    assert first is second
    assert created == [first]
    assert first.closes == 1
    assert lifecycle.current is None


def test_legacy_runtime_accessors_use_lifecycle(monkeypatch) -> None:
    created: list[FakeRuntimeService] = []

    def factory() -> FakeRuntimeService:
        service = FakeRuntimeService()
        created.append(service)
        return service

    lifecycle = RuntimeServiceLifecycle(factory=factory)
    monkeypatch.setattr(agent_runtime, "_runtime_service_lifecycle", lifecycle)
    monkeypatch.setattr(agent_runtime, "_global_agent_runtime_service", None)

    first = agent_runtime.get_native_run_engine()
    second = agent_runtime.get_agent_runtime_service()

    assert first is second
    assert created == [first]
    assert agent_runtime._global_agent_runtime_service is first

    agent_runtime.close_agent_runtime_service()

    assert first.closes == 1
    assert lifecycle.current is None
    assert agent_runtime._global_agent_runtime_service is None


def test_legacy_runtime_accessors_preserve_global_injection(monkeypatch) -> None:
    injected = FakeRuntimeService()
    lifecycle = RuntimeServiceLifecycle(
        factory=lambda: (_ for _ in ()).throw(AssertionError("factory should not run"))
    )
    monkeypatch.setattr(agent_runtime, "_runtime_service_lifecycle", lifecycle)
    monkeypatch.setattr(agent_runtime, "_global_agent_runtime_service", injected)

    assert agent_runtime.get_native_run_engine() is injected
    assert lifecycle.current is injected

    agent_runtime.close_agent_runtime_service()

    assert injected.closes == 1
    assert lifecycle.current is None
    assert agent_runtime._global_agent_runtime_service is None
