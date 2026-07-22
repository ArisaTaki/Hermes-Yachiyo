"""Lifecycle contracts for desktop-provider processes owned by the runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime import installation_facade as installation_facade_module
from apps.shell.agent.runtime import tool_execution as tool_execution_module
from apps.shell.agent.runtime.desktop_execution_providers import (
    DesktopExecutionProviderRegistry,
)
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeClosableAdapter:
    def __init__(self, provider_kind: str, provider_id: str) -> None:
        self.provider_kind = provider_kind
        self.provider_id = provider_id
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeClosableRegistry:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _executor(
    desktop_provider_registry: Any | None = None,
) -> RuntimeToolCallExecutor:
    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: object(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        tool_call_events=object(),
        trace_events=object(),
        append_run_event=lambda _run_id, _event_type, _payload: None,
        desktop_provider_registry=desktop_provider_registry,
    )


def test_registry_close_is_idempotent_and_closes_each_unique_adapter_once() -> None:
    background = FakeClosableAdapter("background_desktop", "cua-driver")
    isolated = FakeClosableAdapter("sandbox_desktop", "isolated-provider")
    registry = DesktopExecutionProviderRegistry()
    registry.register(background)
    registry.register(background)
    registry.register(isolated)

    registry.close()
    registry.close()

    assert background.close_calls == 1
    assert isolated.close_calls == 1


def test_tool_call_executor_closes_injected_registry_once() -> None:
    registry = FakeClosableRegistry()
    executor = _executor(registry)

    executor.close()
    executor.close()

    assert registry.close_calls == 1


def test_tool_call_executor_closes_its_default_registry_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeClosableRegistry()
    monkeypatch.setattr(
        tool_execution_module,
        "default_desktop_execution_provider_registry",
        lambda: registry,
    )
    executor = _executor()

    executor.close()
    executor.close()

    assert registry.close_calls == 1


def _runtime_with_fake_registry(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AgentRuntimeService, FakeClosableRegistry]:
    registry = FakeClosableRegistry()
    monkeypatch.setattr(
        installation_facade_module,
        "default_desktop_execution_provider_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        installation_facade_module,
        "cancel_terminal_process_groups",
        lambda: None,
    )
    monkeypatch.setattr(
        installation_facade_module,
        "_release_desktop_provider_session_owner",
        lambda _owner_token: {},
    )
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    assert service.tool_call_executor._desktop_provider_registry is registry
    return service, registry


def test_runtime_close_db_true_closes_desktop_provider_registry_once(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry = _runtime_with_fake_registry(tmp_path, monkeypatch)

    service.shutdown(close_db=True)
    service.shutdown(close_db=True)

    assert registry.close_calls == 1


def test_runtime_close_db_false_preserves_registry_until_final_close(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry = _runtime_with_fake_registry(tmp_path, monkeypatch)

    service.shutdown(close_db=False)

    assert registry.close_calls == 0

    service.shutdown(close_db=True)
    service.shutdown(close_db=True)

    assert registry.close_calls == 1
