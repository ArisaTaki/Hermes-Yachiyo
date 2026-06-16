"""Tests for NativeRunEngine facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.repositories.sqlite import named_row_factory
from apps.shell.agent.runtime.engine_facade import RuntimeEngineFacadeMixin
from apps.shell.agent.runtime.schema import RuntimeSchemaMigrator
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_engine_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeEngineFacadeMixin is RuntimeEngineFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeEngineFacadeMixin)
    assert "close" not in agent_runtime.NativeRunEngine.__dict__
    assert "list_memory_items" not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_facade_methods_available_after_split(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service._conn.row_factory = None
        service._ensure_row_factory()

        memory_store = service._memory_store(source_run_id="run-memory")
        future_task_store = service._future_task_store(
            source_run_id="run-future",
            default_runnable_id="agent-1",
        )
        deletion_key = service._skill_deletion_key("npx_skills", str(tmp_path / "skill-root"))

        assert service._conn.row_factory is named_row_factory
        assert isinstance(service._schema_migrator(), RuntimeSchemaMigrator)
        assert isinstance(memory_store, AgentMemoryStore)
        assert isinstance(future_task_store, AgentFutureTaskStore)
        assert memory_store.source_run_id == "run-memory"
        assert future_task_store.source_run_id == "run-future"
        assert future_task_store.default_runnable_id == "agent-1"
        assert deletion_key.startswith("installed:")
        assert str((tmp_path / "skill-root").resolve()) in deletion_key
    finally:
        service.close()
