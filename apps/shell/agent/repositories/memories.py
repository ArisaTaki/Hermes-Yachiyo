"""Durable memory persistence for Agent runtime tools."""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4


class AgentMemoryStore:
    """Durable, explicit memories managed through controlled Agent tools."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        source_run_id: str = "",
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        redact_json_value: Callable[[Any], Any],
        redact_secrets: Callable[[Any], str],
        memory_scopes: set[str],
        memory_kinds: set[str],
        context_limit: int = 12,
        content_max_chars: int = 4000,
        error_type: type[Exception] = RuntimeError,
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self.source_run_id = str(source_run_id or "").strip()
        self._now = now
        self._json_dump = json_dump
        self._redact_json_value = redact_json_value
        self._redact_secrets = redact_secrets
        self._memory_scopes = memory_scopes
        self._memory_kinds = memory_kinds
        self._context_limit = context_limit
        self._content_max_chars = content_max_chars
        self._error_type = error_type

    def _normalize_scope(self, value: Any) -> str:
        scope = str(value or "global").strip().lower()
        return scope if scope in self._memory_scopes else "global"

    def _normalize_kind(self, value: Any) -> str:
        kind = str(value or "fact").strip().lower()
        return kind if kind in self._memory_kinds else "fact"

    def _clean_content(self, value: Any) -> str:
        content = self._redact_secrets(value).strip()
        if not content:
            raise self._error_type("memory 内容不能为空")
        if len(content) > self._content_max_chars:
            content = content[: self._content_max_chars].rstrip() + "\n\n[truncated]"
        return content

    @staticmethod
    def _row_to_memory(row: Any) -> dict[str, Any]:
        return {
            "memory_id": str(row["memory_id"]),
            "scope": str(row["scope"] or "global"),
            "kind": str(row["kind"] or "fact"),
            "content": str(row["content"] or ""),
            "source_session_id": str(row["source_session_id"] or ""),
            "source_message_id": str(row["source_message_id"] or ""),
            "source_task_id": str(row["source_task_id"] or ""),
            "source_run_id": str(row["source_run_id"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "pinned": bool(row["pinned"]),
            "user_confirmed": bool(row["user_confirmed"]),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "deleted_at": str(row["deleted_at"] or ""),
        }

    def _record_event(self, memory_id: str, action: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_events (
                event_id, memory_id, action, actor, payload_json, source_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"memory_event_{uuid4().hex[:16]}",
                str(memory_id or ""),
                str(action or ""),
                "agent_tool",
                self._json_dump(self._redact_json_value(payload)),
                self.source_run_id,
                self._now(),
            ),
        )

    def _active_row_by_reference(self, *, memory_id: str = "", content: str = "") -> Any | None:
        clean_memory_id = str(memory_id or "").strip()
        if clean_memory_id:
            return self._conn.execute(
                "SELECT * FROM memory_items WHERE memory_id=? AND deleted_at=''",
                (clean_memory_id,),
            ).fetchone()
        clean_content = str(content or "").strip().lower()
        if not clean_content:
            return None
        rows = self._conn.execute(
            """
            SELECT *
              FROM memory_items
             WHERE deleted_at=''
             ORDER BY pinned DESC, updated_at DESC
             LIMIT 200
            """
        ).fetchall()
        for row in rows:
            if str(row["content"] or "").strip().lower() == clean_content:
                return row
        return None

    def _available_memory_refs(self, *, limit: int = 20) -> list[dict[str, str]]:
        return [
            {
                "memory_id": str(row["memory_id"]),
                "scope": str(row["scope"] or "global"),
                "kind": str(row["kind"] or "fact"),
                "content_preview": str(row["content"] or "")[:160],
            }
            for row in self._conn.execute(
                """
                SELECT memory_id, scope, kind, content
                  FROM memory_items
                 WHERE deleted_at=''
                 ORDER BY pinned DESC, updated_at DESC
                 LIMIT ?
                """,
                (max(1, min(int(limit or 20), 100)),),
            ).fetchall()
        ]

    def add(self, *, content: str, kind: str = "", scope: str = "") -> dict[str, Any]:
        safe_content = self._clean_content(content)
        clean_kind = self._normalize_kind(kind)
        clean_scope = self._normalize_scope(scope)
        memory_id = f"memory_{uuid4().hex[:16]}"
        now = self._now()
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    """
                    INSERT INTO memory_items (
                        memory_id, scope, kind, content, source_run_id,
                        confidence, pinned, user_confirmed, created_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, 1.0, 0, 0, ?, ?, '')
                    """,
                    (memory_id, clean_scope, clean_kind, safe_content, self.source_run_id, now, now),
                )
                self._record_event(
                    memory_id,
                    "memory.add",
                    {
                        "scope": clean_scope,
                        "kind": clean_kind,
                        "content_preview": safe_content[:300],
                    },
                )
                row = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=?",
                    (memory_id,),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"ok": True, "action": "memory.add", "memory": self._row_to_memory(row)}

    def replace(
        self,
        *,
        content: str,
        memory_id: str = "",
        old_content: str = "",
        kind: str = "",
        scope: str = "",
    ) -> dict[str, Any]:
        safe_content = self._clean_content(content)
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._active_row_by_reference(memory_id=memory_id, content=old_content)
                if row is None:
                    self._conn.rollback()
                    return {
                        "ok": False,
                        "action": "memory.replace",
                        "error": "找不到要替换的长期记忆",
                        "available_memories": self._available_memory_refs(),
                    }
                clean_kind = self._normalize_kind(kind or row["kind"])
                clean_scope = self._normalize_scope(scope or row["scope"])
                now = self._now()
                self._conn.execute(
                    """
                    UPDATE memory_items
                       SET scope=?, kind=?, content=?, updated_at=?
                     WHERE memory_id=?
                    """,
                    (clean_scope, clean_kind, safe_content, now, row["memory_id"]),
                )
                self._record_event(
                    str(row["memory_id"]),
                    "memory.replace",
                    {
                        "scope": clean_scope,
                        "kind": clean_kind,
                        "old_content_preview": str(row["content"] or "")[:300],
                        "content_preview": safe_content[:300],
                    },
                )
                updated = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=?",
                    (row["memory_id"],),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"ok": True, "action": "memory.replace", "memory": self._row_to_memory(updated)}

    def remove(self, *, memory_id: str = "", content: str = "", reason: str = "") -> dict[str, Any]:
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._active_row_by_reference(memory_id=memory_id, content=content)
                if row is None:
                    self._conn.rollback()
                    return {
                        "ok": False,
                        "action": "memory.remove",
                        "error": "找不到要删除的长期记忆",
                        "available_memories": self._available_memory_refs(),
                    }
                now = self._now()
                self._conn.execute(
                    "UPDATE memory_items SET deleted_at=?, updated_at=? WHERE memory_id=?",
                    (now, now, row["memory_id"]),
                )
                self._record_event(
                    str(row["memory_id"]),
                    "memory.remove",
                    {
                        "reason": str(reason or "")[:300],
                        "content_preview": str(row["content"] or "")[:300],
                    },
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "ok": True,
            "action": "memory.remove",
            "memory_id": str(row["memory_id"]),
            "deleted_at": now,
        }

    def list_items(self, *, include_deleted: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE deleted_at=''"
        rows = self._conn.execute(
            f"""
            SELECT *
              FROM memory_items
              {where}
             ORDER BY pinned DESC, updated_at DESC
             LIMIT ?
            """,
            (max(1, min(int(limit or 100), 500)),),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def context_block(self, *, limit: int | None = None) -> str:
        memories = self.list_items(
            include_deleted=False,
            limit=self._context_limit if limit is None else limit,
        )
        if not memories:
            return "No durable memories yet."
        return "\n".join(
            f"- {item['kind']}/{item['scope']} [{item['memory_id']}]: {item['content']}"
            for item in memories
        )
