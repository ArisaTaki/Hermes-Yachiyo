"""Tests for FutureTask trigger scheduler split out of the legacy runtime."""

from __future__ import annotations

from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_native_runtime_uses_split_future_task_trigger_scheduler(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        assert isinstance(service.future_task_scheduler, FutureTaskTriggerScheduler)
    finally:
        service.close()
