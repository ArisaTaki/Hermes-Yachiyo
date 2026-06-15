"""Tests for memory service setup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.runtime.memory_services import RuntimeMemoryService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_memory_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeMemoryService is RuntimeMemoryService


def test_native_runtime_installs_memory_service_under_legacy_methods(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        memory_store = service._memory_store(source_run_id="run-memory")
        future_task_store = service._future_task_store(
            source_run_id="run-future",
            default_runnable_id="agent-1",
        )

        assert isinstance(service.memory_services, RuntimeMemoryService)
        assert isinstance(memory_store, AgentMemoryStore)
        assert isinstance(future_task_store, AgentFutureTaskStore)
        assert memory_store.source_run_id == "run-memory"
        assert future_task_store.source_run_id == "run-future"
        assert future_task_store.default_runnable_id == "agent-1"
        assert service._long_term_memory_context() == "No durable memories yet."

        result = service.create_memory_item(
            {
                "content": "Remember to keep Agent Studio, Groups, Workflow, and Timeline intact.",
                "kind": "fact",
                "scope": "global",
            }
        )

        assert result["ok"] is True
        assert "Remember to keep Agent Studio" in service._long_term_memory_context()
    finally:
        service.close()


def test_runtime_memory_service_exposes_public_crud_operations(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        created = service.memory_services.create_item(
            {
                "content": "User prefers concise progress reports.",
                "kind": "preference",
                "scope": "global",
            }
        )
        memory_id = created["memory"]["memory_id"]
        listed = service.memory_services.list_items()
        updated = service.memory_services.update_item(
            memory_id,
            {
                "old_content": "User prefers concise progress reports.",
                "content": "User prefers concise bilingual progress reports.",
                "kind": "preference",
                "scope": "global",
            },
        )
        deleted = service.memory_services.delete_item(memory_id, reason="manual cleanup")
        all_items = service.memory_services.list_items(include_deleted=True)

        assert listed["memories"][0]["memory_id"] == memory_id
        assert updated["memory"]["content"] == "User prefers concise bilingual progress reports."
        assert deleted["ok"] is True
        assert all_items["memories"][0]["deleted_at"]
        assert service.list_memory_items(include_deleted=True)["memories"][0]["memory_id"] == memory_id
    finally:
        service.close()
