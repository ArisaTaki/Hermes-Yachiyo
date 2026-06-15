"""Memory and FutureTask store setup for the legacy runtime entrypoint."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.memories import AgentMemoryStore


class RuntimeMemoryService:
    """Builds durable memory-related stores with shared runtime dependencies."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        redact_json_value: Callable[[Any], Any],
        redact_secrets: Callable[[Any], str],
        memory_scopes: set[str],
        memory_kinds: set[str],
        context_limit: int,
        content_max_chars: int,
        error_type: type[Exception],
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._now = now
        self._json_dump = json_dump
        self._redact_json_value = redact_json_value
        self._redact_secrets = redact_secrets
        self._memory_scopes = memory_scopes
        self._memory_kinds = memory_kinds
        self._context_limit = context_limit
        self._content_max_chars = content_max_chars
        self._error_type = error_type

    def memory_store(self, *, source_run_id: str = "") -> AgentMemoryStore:
        return AgentMemoryStore(
            self._conn,
            self._db_lock,
            source_run_id=source_run_id,
            now=self._now,
            json_dump=self._json_dump,
            redact_json_value=self._redact_json_value,
            redact_secrets=self._redact_secrets,
            memory_scopes=self._memory_scopes,
            memory_kinds=self._memory_kinds,
            context_limit=self._context_limit,
            content_max_chars=self._content_max_chars,
            error_type=self._error_type,
        )

    def future_task_store(
        self,
        *,
        source_run_id: str = "",
        default_runnable_id: str = "",
    ) -> AgentFutureTaskStore:
        return AgentFutureTaskStore(
            self._conn,
            self._db_lock,
            source_run_id=source_run_id,
            default_runnable_id=default_runnable_id,
            now=self._now,
            json_dump=self._json_dump,
            redact_json_value=self._redact_json_value,
            redact_secrets=self._redact_secrets,
            error_type=self._error_type,
        )

    def list_items(self, *, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        memories = self.memory_store().list_items(include_deleted=include_deleted, limit=limit)
        return {"ok": True, "memories": memories}

    def create_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_store(source_run_id="manual").add(
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or ""),
            scope=str(payload.get("scope") or ""),
        )

    def update_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_store(source_run_id="manual").replace(
            memory_id=memory_id,
            old_content=str(payload.get("old_content") or ""),
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or ""),
            scope=str(payload.get("scope") or ""),
        )

    def delete_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.memory_store(source_run_id="manual").remove(memory_id=memory_id, reason=reason)

    def long_term_memory_context(self) -> str:
        return self.memory_store().context_block(limit=self._context_limit)
