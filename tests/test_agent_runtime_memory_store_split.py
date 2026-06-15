"""Tests for Agent memory store split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.memories import AgentMemoryStore


def test_agent_memory_store_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.AgentMemoryStore is AgentMemoryStore
