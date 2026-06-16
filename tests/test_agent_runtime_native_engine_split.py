"""Tests for NativeRunEngine composition split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.native_engine import NativeRunEngine


def test_native_run_engine_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.NativeRunEngine is NativeRunEngine
    assert agent_runtime.AgentRuntimeService is NativeRunEngine
