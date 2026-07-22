"""Memory and FutureTask store setup for the legacy runtime entrypoint."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.memories import AgentMemoryStore, MemoryQuery


_USER_MEMORY_CONSENT_ISSUE_AUTHORITY = object()


def issue_user_memory_consent_capability(
    service: "RuntimeMemoryService",
    memory_id: str,
) -> dict[str, Any]:
    """Bridge-only explicit user action boundary for issuing a one-time capability."""

    return service.issue_consent_capability(
        memory_id,
        authority=_USER_MEMORY_CONSENT_ISSUE_AUTHORITY,
    )


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

    def memory_store(
        self,
        *,
        source_run_id: str = "",
        source_session_id: str = "",
        source_message_id: str = "",
        source_task_id: str = "",
        project_id: str = "",
        actor: str = "agent_tool",
    ) -> AgentMemoryStore:
        source = self._source_context_for_run(source_run_id) if source_run_id else {}
        return AgentMemoryStore(
            self._conn,
            self._db_lock,
            source_run_id=source_run_id,
            source_session_id=(source_session_id or str(source.get("session_id") or "")),
            source_message_id=(source_message_id or str(source.get("message_id") or "")),
            source_task_id=(source_task_id or str(source.get("task_id") or "")),
            project_id=(project_id or str(source.get("project_id") or "")),
            actor=actor,
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

    def _source_context_for_run(self, run_id: str) -> dict[str, str]:
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return {}
        link = self._conn.execute(
            "SELECT task_id, session_id FROM task_run_links WHERE run_id=?",
            (clean_run_id,),
        ).fetchone()
        task_id = str(link["task_id"] or "") if link is not None else ""
        session_id = str(link["session_id"] or "") if link is not None else ""
        message_id = ""
        event = self._conn.execute(
            """
            SELECT payload_json
              FROM run_events
             WHERE run_id=? AND event_type='run.started'
             ORDER BY sequence ASC
             LIMIT 1
            """,
            (clean_run_id,),
        ).fetchone()
        if event is not None:
            try:
                payload = json.loads(str(event["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            message_id = str(metadata.get("source_message_id") or "").strip()
        if not message_id:
            run_row = self._conn.execute(
                "SELECT timeline_json FROM runs WHERE run_id=?",
                (clean_run_id,),
            ).fetchone()
            if run_row is not None:
                try:
                    timeline = json.loads(str(run_row["timeline_json"] or "[]"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    timeline = []
                for item in timeline if isinstance(timeline, list) else []:
                    if not isinstance(item, dict) or str(item.get("event") or "") != "run.started":
                        continue
                    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    message_id = str(metadata.get("source_message_id") or "").strip()
                    if message_id:
                        break
        project_id = ""
        if session_id:
            project = self._conn.execute(
                "SELECT project_id FROM memory_project_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if project is not None:
                project_id = str(project["project_id"] or "")
        return {
            "task_id": task_id,
            "session_id": session_id,
            "message_id": message_id,
            "project_id": project_id,
        }

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
        return self.memory_store(
            source_run_id="manual",
            source_session_id=str(payload.get("source_session_id") or ""),
            source_message_id=str(payload.get("source_message_id") or ""),
            source_task_id=str(payload.get("source_task_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            actor="user",
        ).add(
            content=str(payload.get("content") or ""),
            kind=str(payload.get("kind") or ""),
            scope=str(payload.get("scope") or ""),
        )

    def update_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        receipt = payload.get("consent_receipt")
        if payload.get("user_confirmed") is True and isinstance(receipt, Mapping):
            return self.confirm_item(memory_id, receipt)
        store = self.memory_store(
            source_run_id="manual",
            source_session_id=str(payload.get("source_session_id") or ""),
            source_message_id=str(payload.get("source_message_id") or ""),
            source_task_id=str(payload.get("source_task_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            actor="user",
        )
        result: dict[str, Any] | None = None
        if "content" in payload:
            result = store.replace(
                memory_id=memory_id,
                old_content=str(payload.get("old_content") or ""),
                content=str(payload.get("content") or ""),
                kind=str(payload.get("kind") or ""),
                scope=str(payload.get("scope") or ""),
            )
        if "enabled" in payload:
            result = store.set_enabled(memory_id, bool(payload.get("enabled")))
        if result is None:
            raise self._error_type("请提供 content、enabled 或有效的 consent_receipt")
        return result

    def delete_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.memory_store(source_run_id="manual", actor="user").remove(
            memory_id=memory_id,
            reason=reason,
        )

    def confirm_item(
        self,
        memory_id: str,
        consent_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.memory_store(source_run_id="manual", actor="user").confirm(
            memory_id,
            consent_receipt,
        )

    def issue_consent_capability(
        self,
        memory_id: str,
        *,
        authority: object | None = None,
    ) -> dict[str, Any]:
        if authority is not _USER_MEMORY_CONSENT_ISSUE_AUTHORITY:
            raise self._error_type("memory_consent_user_action_required")
        return self.memory_store(source_run_id="manual", actor="user").issue_consent_capability(
            memory_id
        )

    def query_items(self, query: MemoryQuery | None = None) -> list[dict[str, Any]]:
        return self.memory_store().query(query)

    def context_for(
        self,
        *,
        session_id: str = "",
        project_id: str = "",
        limit: int | None = None,
    ) -> str:
        return self.memory_store().context_block(
            query=MemoryQuery(
                session_id=str(session_id or ""),
                project_id=str(project_id or ""),
                limit=self._context_limit if limit is None else int(limit),
            )
        )

    def long_term_memory_context(self) -> str:
        return self.context_for(limit=self._context_limit)
