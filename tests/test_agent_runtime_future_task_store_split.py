"""Tests for FutureTask store split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore


def test_agent_future_task_store_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.AgentFutureTaskStore is AgentFutureTaskStore
