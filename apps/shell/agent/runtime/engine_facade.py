"""Compatibility facade methods for the legacy NativeRunEngine entrypoint."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.repositories.sqlite import (
    coerce_named_row as _coerce_named_row_value,
    named_row_factory as _named_row_factory,
)
from apps.shell.agent.runtime.config import is_native_library_source_type
from apps.shell.agent.runtime.schema import RuntimeSchemaMigrator
from apps.shell.agent.runtime.skill_sources import skill_deletion_key as _runtime_skill_deletion_key


class RuntimeEngineFacadeMixin:
    """Keeps legacy NativeRunEngine method names while delegating to split services."""

    def close(self) -> None:
        self.shutdown()

    def shutdown(self, *, close_db: bool = True) -> None:
        self.runtime_shutdown.shutdown(close_db=close_db)

    def _ensure_row_factory(self) -> None:
        if self._conn.row_factory is not _named_row_factory:
            self._conn.row_factory = _named_row_factory

    def _coerce_named_row(self, row: Any, description: Any = None) -> Any:
        return _coerce_named_row_value(row, description)

    def _init_db(self) -> None:
        self.runtime_schema.init_db()

    def _schema_migrator(self) -> RuntimeSchemaMigrator:
        return self.runtime_schema.migrator()

    def _ensure_runtime_columns(self) -> bool:
        return self.runtime_schema.ensure_runtime_columns()

    def _vacuum_after_secret_scrub(self) -> None:
        self.runtime_schema.vacuum_after_secret_scrub()

    def _migrate_native_execution_and_skill_sources(self) -> None:
        self.runtime_schema.migrate_native_execution_and_skill_sources()

    def _migrate_run_group_secret_projections(self) -> bool:
        return self.runtime_schema.migrate_run_group_secret_projections()

    def _agent_model_credential_ref(self, agent_id: str) -> str:
        return self.runtime_credentials.agent_model_ref(agent_id)

    def _store_credential(self, ref: str, secret: str) -> None:
        self.runtime_credentials.store(ref, secret)

    def _read_credential(self, ref: str) -> str:
        return self.runtime_credentials.read(ref)

    def _delete_credential(self, ref: str) -> None:
        self.runtime_credentials.delete(ref)

    def _migrate_agent_model_credentials(self) -> bool:
        return self.runtime_schema.migrate_agent_model_credentials()

    def _record_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.record(item_type, item_key)

    def _clear_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.clear(item_type, item_key)

    def _has_studio_deletion(self, item_type: str, item_key: str) -> bool:
        return self.studio_deletions.has(item_type, item_key)

    @staticmethod
    def _skill_deletion_key(source_type: str, origin_path: str) -> str:
        return _runtime_skill_deletion_key(
            source_type,
            origin_path,
            is_native_library_source_type=is_native_library_source_type,
        )

    def _seed_templates(self) -> None:
        self.seed_template_service.seed()

    def _seed_workflow_templates(self) -> None:
        self.seed_template_service.seed_workflows()

    def _default_agent_workdir(self, agent_id: str) -> Path:
        return self.workspace_policy_service.default_agent_workdir(agent_id)

    def _assign_default_agent_workdir(
        self,
        agent_id: str,
        workspace_policy: dict[str, Any],
        tool_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return self.workspace_policy_service.assign_default_agent_workdir(
            agent_id,
            workspace_policy,
            tool_policy,
        )

    def trust_workspace(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        return self.workspace_policy_service.trust_workspace(path, source=source, commit=commit)

    def _trust_workspace_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        self.workspace_policy_service.trust_workspace_from_policy(
            workspace_policy,
            source=source,
            commit=commit,
        )

    def list_trusted_workspaces(self) -> dict[str, Any]:
        return self.workspace_policy_service.list_trusted_workspaces()

    def _migrate_agent_workspace_policies(self) -> None:
        self.workspace_policy_service.migrate_agent_workspace_policies()

    def _compile_tool_policy(self, category: str, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_tool_policy(category, policy)

    def _compile_workspace_policy(self, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_workspace_policy(policy)

    def _memory_store(self, *, source_run_id: str = "") -> AgentMemoryStore:
        return self.memory_services.memory_store(source_run_id=source_run_id)

    def _future_task_store(
        self,
        *,
        source_run_id: str = "",
        default_runnable_id: str = "",
    ) -> AgentFutureTaskStore:
        return self.memory_services.future_task_store(
            source_run_id=source_run_id,
            default_runnable_id=default_runnable_id,
        )

    def list_memory_items(self, *, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        return self.memory_services.list_items(include_deleted=include_deleted, limit=limit)

    def create_memory_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_services.create_item(payload)

    def update_memory_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_services.update_item(memory_id, payload)

    def delete_memory_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.memory_services.delete_item(memory_id, reason=reason)

    def _long_term_memory_context(self) -> str:
        return self.memory_services.long_term_memory_context()

    def schedule_future_task(self, payload: dict[str, Any], *, source_run_id: str = "") -> dict[str, Any]:
        return self.future_task_service.schedule(payload, source_run_id=source_run_id)

    def list_future_tasks(self, *, include_finished: bool = True, limit: int = 100) -> dict[str, Any]:
        return self.future_task_service.list(include_finished=include_finished, limit=limit)

    def cancel_future_task(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.future_task_service.cancel(future_task_id, reason=reason)

    def trigger_due_future_tasks(self, *, now_epoch: float | None = None, limit: int = 20) -> dict[str, Any]:
        return self.future_task_service.trigger_due(now_epoch=now_epoch, limit=limit)

    def _row_to_agent(self, row: Any) -> dict[str, Any]:
        return self.row_projector.agent(row)

    def _row_to_agent_private(self, row: Any) -> dict[str, Any]:
        return self.row_projector.agent_private(row)

    def _main_chat_virtual_agent(self) -> dict[str, Any]:
        return self.main_chat_virtual_agent_projector.virtual_agent()

    def _row_to_skill(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.row_projector.skill(row)

    def _row_to_skill_folder(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.row_projector.skill_folder(row)

    def _row_to_workflow(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.row_projector.workflow(row)

    def _row_to_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.row_projector.run(row)

    def _row_to_run_group(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.row_projector.run_group(row)

    def _runnable_name(self, kind: str, runnable_id: str) -> str:
        return self.runnable_name_resolver.resolve(kind, runnable_id)

    def _ensure_global_name_available(
        self,
        name: str,
        *,
        ignore_agent_id: str = "",
        ignore_workflow_id: str = "",
    ) -> None:
        self.definition_name_guard.ensure_available(
            name,
            ignore_agent_id=ignore_agent_id,
            ignore_workflow_id=ignore_workflow_id,
        )
