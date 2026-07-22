"""Durable memory persistence for Agent runtime tools."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4


@dataclass(frozen=True)
class MemoryQuery:
    """Authoritative recall boundary for one runtime context.

    Global memories are shared. Session and project memories are returned only
    for the exact bound identity; an absent identity never widens the query.
    """

    session_id: str = ""
    project_id: str = ""
    include_global: bool = True
    limit: int = 12


class AgentMemoryStore:
    """Durable, explicit memories managed through controlled Agent tools."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        source_run_id: str = "",
        source_session_id: str = "",
        source_message_id: str = "",
        source_task_id: str = "",
        project_id: str = "",
        actor: str = "agent_tool",
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
        self.source_session_id = str(source_session_id or "").strip()
        self.source_message_id = str(source_message_id or "").strip()
        self.source_task_id = str(source_task_id or "").strip()
        self.project_id = str(project_id or "").strip()
        self.actor = "user" if str(actor or "").strip() == "user" else "agent_tool"
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
        scope = str(value or "").strip().lower()
        if not scope:
            return "global"
        if scope not in self._memory_scopes:
            raise self._error_type("memory_scope_invalid")
        return scope

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
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        content = str(row["content"] or "")
        return {
            "memory_id": str(row["memory_id"]),
            "scope": str(row["scope"] or "global"),
            "kind": str(row["kind"] or "fact"),
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "project_id": str(row["project_id"] or ""),
            "source_session_id": str(row["source_session_id"] or ""),
            "source_message_id": str(row["source_message_id"] or ""),
            "source_task_id": str(row["source_task_id"] or ""),
            "source_run_id": str(row["source_run_id"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "pinned": bool(row["pinned"]),
            "user_confirmed": bool(row["user_confirmed"]),
            "enabled": bool(row["enabled"]) if "enabled" in keys else True,
            "actor": (
                str(row["actor"] or "agent_tool")
                if "actor" in keys
                else ("user" if str(row["source_run_id"] or "") == "manual" else "agent_tool")
            ),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "deleted_at": str(row["deleted_at"] or ""),
        }

    def _record_event(
        self,
        memory_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        actor: str | None = None,
    ) -> None:
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
                "user" if str(actor or self.actor) == "user" else "agent_tool",
                self._json_dump(self._redact_json_value(payload)),
                self.source_run_id,
                self._now(),
            ),
        )

    def _agent_visible_row_clause(self) -> tuple[str, tuple[Any, ...]]:
        scope_clauses = ["scope='global'"]
        parameters: list[Any] = []
        if self.source_session_id:
            scope_clauses.append("(scope='session' AND source_session_id=?)")
            parameters.append(self.source_session_id)
        if self.project_id:
            scope_clauses.append("(scope='project' AND project_id=?)")
            parameters.append(self.project_id)
        parameters.extend((self.source_run_id, self.source_run_id))
        return (
            "AND ((user_confirmed=1 AND enabled=1 AND ("
            + " OR ".join(scope_clauses)
            + ")) OR (user_confirmed=0 AND source_run_id=? AND ?<>''))",
            tuple(parameters),
        )

    def _active_row_by_reference(self, *, memory_id: str = "", content: str = "") -> Any | None:
        visibility_clause = ""
        visibility_parameters: tuple[Any, ...] = ()
        if self.actor == "agent_tool":
            visibility_clause, visibility_parameters = self._agent_visible_row_clause()
        clean_memory_id = str(memory_id or "").strip()
        if clean_memory_id:
            return self._conn.execute(
                f"""
                SELECT * FROM memory_items
                 WHERE memory_id=? AND deleted_at='' {visibility_clause}
                """,
                (clean_memory_id, *visibility_parameters),
            ).fetchone()
        clean_content = str(content or "").strip().lower()
        if not clean_content:
            return None
        rows = self._conn.execute(
            f"""
            SELECT *
              FROM memory_items
             WHERE deleted_at=''
               {visibility_clause}
             ORDER BY pinned DESC, updated_at DESC
             LIMIT 200
            """,
            visibility_parameters,
        ).fetchall()
        for row in rows:
            if str(row["content"] or "").strip().lower() == clean_content:
                return row
        return None

    def _available_memory_refs(self, *, limit: int = 20) -> list[dict[str, str]]:
        return [
            {
                "memory_id": str(item["memory_id"]),
                "scope": str(item["scope"] or "global"),
                "kind": str(item["kind"] or "fact"),
                "content_preview": str(item["content"] or "")[:160],
            }
            for item in self.query(
                MemoryQuery(
                    session_id=self.source_session_id,
                    project_id=self.project_id,
                    limit=max(1, min(int(limit or 20), 100)),
                )
            )
        ]

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()

    @classmethod
    def _memory_version(cls, row: Any) -> str:
        payload = {
            "memory_id": str(row["memory_id"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "content_hash": cls._content_hash(str(row["content"] or "")),
            "scope": str(row["scope"] or "global"),
            "project_id": str(row["project_id"] or ""),
            "source_session_id": str(row["source_session_id"] or ""),
            "run_id": str(row["source_run_id"] or ""),
            "source_message_id": str(row["source_message_id"] or ""),
        }
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def _consent_binding(
        cls,
        row: Any,
        *,
        capability_id: str,
        token: str,
    ) -> dict[str, str]:
        return {
            "actor": "user",
            "capability_id": str(capability_id or ""),
            "token": str(token or ""),
            "memory_id": str(row["memory_id"] or ""),
            "version": cls._memory_version(row),
            "run_id": str(row["source_run_id"] or ""),
            "source_message_id": str(row["source_message_id"] or ""),
            "content_hash": cls._content_hash(str(row["content"] or "")),
            "scope": str(row["scope"] or "global"),
            "project_id": str(row["project_id"] or ""),
            "source_session_id": str(row["source_session_id"] or ""),
        }

    @staticmethod
    def _invalid_consent_capability() -> dict[str, Any]:
        return {
            "ok": False,
            "action": "memory.confirm",
            "error": "consent_capability_invalid",
        }

    def issue_consent_capability(
        self,
        memory_id: str,
        *,
        ttl_seconds: int = 600,
    ) -> dict[str, Any]:
        """Issue one short-lived user-action capability without persisting its raw token."""

        clean_id = str(memory_id or "").strip()
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=? AND deleted_at=''",
                    (clean_id,),
                ).fetchone()
                if (
                    row is None
                    or bool(row["user_confirmed"])
                    or not bool(row["enabled"])
                    or str(row["actor"] or "") != "agent_tool"
                    or not str(row["source_run_id"] or "").strip()
                    or not str(row["source_message_id"] or "").strip()
                ):
                    self._conn.rollback()
                    return {
                        "ok": False,
                        "action": "memory.consent.issue",
                        "error": "memory_consent_candidate_invalid",
                    }
                capability_id = f"memory_consent_{uuid4().hex[:20]}"
                token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                issued_at = self._now()
                expires_at_epoch = time.time() + max(30, min(int(ttl_seconds), 3600))
                binding = self._consent_binding(
                    row,
                    capability_id=capability_id,
                    token=token,
                )
                self._conn.execute(
                    """
                    INSERT INTO memory_consent_capabilities (
                        capability_id, memory_id, token_hash, memory_version,
                        run_id, source_message_id, content_hash, scope,
                        project_id, source_session_id, issued_at, expires_at_epoch, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                    """,
                    (
                        capability_id,
                        clean_id,
                        token_hash,
                        binding["version"],
                        binding["run_id"],
                        binding["source_message_id"],
                        binding["content_hash"],
                        binding["scope"],
                        binding["project_id"],
                        binding["source_session_id"],
                        issued_at,
                        expires_at_epoch,
                    ),
                )
                self._record_event(
                    clean_id,
                    "memory.consent.issue",
                    {
                        key: value
                        for key, value in binding.items()
                        if key != "token"
                    },
                    actor="user",
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "ok": True,
            "action": "memory.consent.issue",
            "memory_id": clean_id,
            "expires_at_epoch": expires_at_epoch,
            "consent_receipt": binding,
        }

    def _validate_confirmed_scope_identity(self, scope: str) -> None:
        if self.actor != "user":
            return
        if scope == "session" and not self.source_session_id:
            raise self._error_type("session 记忆需要绑定 source_session_id")
        if scope == "project" and not self.project_id:
            raise self._error_type("project 记忆需要绑定 project_id")

    def add(self, *, content: str, kind: str = "", scope: str = "") -> dict[str, Any]:
        safe_content = self._clean_content(content)
        clean_kind = self._normalize_kind(kind)
        clean_scope = self._normalize_scope(scope)
        self._validate_confirmed_scope_identity(clean_scope)
        memory_id = f"memory_{uuid4().hex[:16]}"
        now = self._now()
        user_confirmed = self.actor == "user"
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    """
                    INSERT INTO memory_items (
                        memory_id, scope, kind, content, project_id,
                        source_session_id, source_message_id, source_task_id, source_run_id,
                        confidence, pinned, user_confirmed, enabled, actor,
                        created_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0, ?, 1, ?, ?, ?, '')
                    """,
                    (
                        memory_id,
                        clean_scope,
                        clean_kind,
                        safe_content,
                        self.project_id,
                        self.source_session_id,
                        self.source_message_id,
                        self.source_task_id,
                        self.source_run_id,
                        1 if user_confirmed else 0,
                        self.actor,
                        now,
                        now,
                    ),
                )
                self._record_event(
                    memory_id,
                    "memory.add",
                    {
                        "scope": clean_scope,
                        "kind": clean_kind,
                        "content_preview": safe_content[:300],
                        "content_hash": self._content_hash(safe_content),
                        "candidate": not user_confirmed,
                        "source_session_id": self.source_session_id,
                        "source_message_id": self.source_message_id,
                        "source_task_id": self.source_task_id,
                        "project_id": self.project_id,
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
        approved: bool = False,
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
                if self.actor == "agent_tool" and bool(row["user_confirmed"]) and not approved:
                    self._conn.rollback()
                    return {
                        "ok": False,
                        "action": "memory.replace",
                        "approval_required": True,
                        "tool": "memory.replace",
                        "policy_reason": "修改已确认的长期记忆需要用户确认。",
                    }
                clean_kind = self._normalize_kind(kind or row["kind"])
                clean_scope = self._normalize_scope(scope or row["scope"])
                confirmed_mutation = self.actor == "user" or (
                    self.actor == "agent_tool" and bool(row["user_confirmed"]) and approved
                )
                if confirmed_mutation:
                    if clean_scope == "session" and not (
                        self.source_session_id or str(row["source_session_id"] or "")
                    ):
                        raise self._error_type("session 记忆需要绑定 source_session_id")
                    if clean_scope == "project" and not (
                        self.project_id or str(row["project_id"] or "")
                    ):
                        raise self._error_type("project 记忆需要绑定 project_id")
                now = self._now()
                if self.actor == "agent_tool" and bool(row["user_confirmed"]):
                    target_memory_id = str(row["memory_id"])
                    supersedes_memory_id = ""
                    self._conn.execute(
                        """
                        UPDATE memory_items
                           SET scope=?, kind=?, content=?, project_id=?,
                               source_session_id=?, source_message_id=?, source_task_id=?,
                               source_run_id=?, user_confirmed=1, enabled=1, actor='agent_tool',
                               updated_at=?
                         WHERE memory_id=?
                        """,
                        (
                            clean_scope,
                            clean_kind,
                            safe_content,
                            self.project_id or str(row["project_id"] or ""),
                            self.source_session_id or str(row["source_session_id"] or ""),
                            self.source_message_id or str(row["source_message_id"] or ""),
                            self.source_task_id or str(row["source_task_id"] or ""),
                            self.source_run_id or str(row["source_run_id"] or ""),
                            now,
                            row["memory_id"],
                        ),
                    )
                else:
                    target_memory_id = str(row["memory_id"])
                    supersedes_memory_id = ""
                    self._conn.execute(
                        """
                        UPDATE memory_items
                           SET scope=?, kind=?, content=?, project_id=?,
                               source_session_id=?, source_message_id=?, source_task_id=?,
                               source_run_id=?, user_confirmed=?, enabled=1, actor=?, updated_at=?
                         WHERE memory_id=?
                        """,
                        (
                            clean_scope,
                            clean_kind,
                            safe_content,
                            self.project_id or str(row["project_id"] or ""),
                            self.source_session_id or str(row["source_session_id"] or ""),
                            self.source_message_id or str(row["source_message_id"] or ""),
                            self.source_task_id or str(row["source_task_id"] or ""),
                            (
                                str(row["source_run_id"] or "")
                                if self.source_run_id == "manual"
                                else self.source_run_id or str(row["source_run_id"] or "")
                            ),
                            1 if self.actor == "user" else 0,
                            self.actor,
                            now,
                            row["memory_id"],
                        ),
                    )
                self._record_event(
                    target_memory_id,
                    "memory.replace",
                    {
                        "scope": clean_scope,
                        "kind": clean_kind,
                        "old_content_preview": str(row["content"] or "")[:300],
                        "content_preview": safe_content[:300],
                        "content_hash": self._content_hash(safe_content),
                        "candidate": self.actor != "user" and not confirmed_mutation,
                        "supersedes_memory_id": supersedes_memory_id,
                        "user_action_authorized": bool(approved and confirmed_mutation),
                    },
                )
                updated = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=?",
                    (target_memory_id,),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"ok": True, "action": "memory.replace", "memory": self._row_to_memory(updated)}

    def confirm(self, memory_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Consume one server-issued capability and confirm its exact candidate version."""

        clean_id = str(memory_id or "").strip()
        capability_id = str(receipt.get("capability_id") or "").strip()
        token = str(receipt.get("token") or "").strip()
        if not clean_id or not capability_id or not token:
            return self._invalid_consent_capability()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                capability = self._conn.execute(
                    """
                    SELECT * FROM memory_consent_capabilities
                     WHERE capability_id=? AND memory_id=? AND token_hash=? AND consumed_at=''
                    """,
                    (capability_id, clean_id, token_hash),
                ).fetchone()
                if capability is None or float(capability["expires_at_epoch"] or 0.0) <= time.time():
                    self._conn.rollback()
                    return self._invalid_consent_capability()
                row = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=? AND deleted_at=''",
                    (clean_id,),
                ).fetchone()
                if (
                    row is None
                    or bool(row["user_confirmed"])
                    or not bool(row["enabled"])
                    or str(row["actor"] or "") != "agent_tool"
                ):
                    self._conn.rollback()
                    return self._invalid_consent_capability()
                expected = self._consent_binding(
                    row,
                    capability_id=capability_id,
                    token=token,
                )
                actual = {
                    key: str(receipt.get(key) or "").strip()
                    for key in expected
                }
                persisted = {
                    "memory_id": str(capability["memory_id"] or ""),
                    "version": str(capability["memory_version"] or ""),
                    "run_id": str(capability["run_id"] or ""),
                    "source_message_id": str(capability["source_message_id"] or ""),
                    "content_hash": str(capability["content_hash"] or ""),
                    "scope": str(capability["scope"] or ""),
                    "project_id": str(capability["project_id"] or ""),
                    "source_session_id": str(capability["source_session_id"] or ""),
                }
                expected_persisted = {
                    key: expected[key]
                    for key in persisted
                }
                if actual != expected or persisted != expected_persisted:
                    self._conn.rollback()
                    return self._invalid_consent_capability()
                now = self._now()
                consumed = self._conn.execute(
                    """
                    UPDATE memory_consent_capabilities
                       SET consumed_at=?
                     WHERE capability_id=? AND token_hash=? AND consumed_at=''
                    """,
                    (now, capability_id, token_hash),
                )
                if int(consumed.rowcount or 0) != 1:
                    self._conn.rollback()
                    return self._invalid_consent_capability()
                supersedes_memory_id = self._candidate_supersedes_memory_id(clean_id)
                if supersedes_memory_id:
                    self._conn.execute(
                        "UPDATE memory_items SET deleted_at=?, updated_at=? WHERE memory_id=? AND deleted_at=''",
                        (now, now, supersedes_memory_id),
                    )
                self._conn.execute(
                    "UPDATE memory_items SET user_confirmed=1, updated_at=? WHERE memory_id=?",
                    (now, clean_id),
                )
                self._record_event(
                    clean_id,
                    "memory.confirm",
                    {
                        **{
                            key: value
                            for key, value in expected.items()
                            if key != "token"
                        },
                        "supersedes_memory_id": supersedes_memory_id,
                    },
                    actor="user",
                )
                self._conn.execute(
                    """
                    UPDATE memory_consent_capabilities
                       SET consumed_at=?
                     WHERE memory_id=? AND consumed_at=''
                    """,
                    (now, clean_id),
                )
                updated = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=?",
                    (clean_id,),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "ok": True,
            "action": "memory.confirm",
            "memory": self._row_to_memory(updated),
            "consent_receipt": {
                key: value for key, value in expected.items() if key != "token"
            },
        }

    def _candidate_supersedes_memory_id(self, memory_id: str) -> str:
        rows = self._conn.execute(
            "SELECT payload_json FROM memory_events WHERE memory_id=? ORDER BY created_at DESC",
            (str(memory_id or ""),),
        ).fetchall()
        for event in rows:
            try:
                payload = json.loads(str(event["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            supersedes = str(payload.get("supersedes_memory_id") or "").strip()
            if supersedes:
                return supersedes
        return ""

    def set_enabled(self, memory_id: str, enabled: bool) -> dict[str, Any]:
        clean_id = str(memory_id or "").strip()
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=? AND deleted_at=''",
                    (clean_id,),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return {"ok": False, "action": "memory.disable", "error": "memory_not_found"}
                now = self._now()
                self._conn.execute(
                    "UPDATE memory_items SET enabled=?, updated_at=? WHERE memory_id=?",
                    (1 if enabled else 0, now, clean_id),
                )
                self._record_event(
                    clean_id,
                    "memory.enable" if enabled else "memory.disable",
                    {"enabled": bool(enabled)},
                    actor="user",
                )
                updated = self._conn.execute(
                    "SELECT * FROM memory_items WHERE memory_id=?",
                    (clean_id,),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {
            "ok": True,
            "action": "memory.enable" if enabled else "memory.disable",
            "memory": self._row_to_memory(updated),
        }

    def remove(
        self,
        *,
        memory_id: str = "",
        content: str = "",
        reason: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
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
                if self.actor == "agent_tool" and bool(row["user_confirmed"]) and not approved:
                    self._conn.rollback()
                    return {
                        "ok": False,
                        "action": "memory.remove",
                        "approval_required": True,
                        "tool": "memory.remove",
                        "policy_reason": "删除已确认的长期记忆需要用户确认。",
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
                        "user_action_authorized": bool(
                            self.actor == "user" or (approved and bool(row["user_confirmed"]))
                        ),
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

    def query(self, query: MemoryQuery | None = None) -> list[dict[str, Any]]:
        """Return only recall-eligible memories for an exact runtime scope."""

        request = query or MemoryQuery(limit=self._context_limit)
        session_id = str(request.session_id or "").strip()
        project_id = str(request.project_id or "").strip()
        if not project_id and session_id:
            project_row = self._conn.execute(
                "SELECT project_id FROM memory_project_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if project_row is not None:
                project_id = str(project_row["project_id"] or "").strip()
        clauses: list[str] = []
        parameters: list[Any] = []
        if request.include_global:
            clauses.append("scope='global'")
        if session_id:
            clauses.append("(scope='session' AND source_session_id=?)")
            parameters.append(session_id)
        if project_id:
            clauses.append("(scope='project' AND project_id=?)")
            parameters.append(project_id)
        if not clauses:
            return []
        parameters.append(max(1, min(int(request.limit or self._context_limit), 500)))
        rows = self._conn.execute(
            f"""
            SELECT *
              FROM memory_items
             WHERE deleted_at=''
               AND enabled=1
               AND user_confirmed=1
               AND ({' OR '.join(clauses)})
             ORDER BY pinned DESC, updated_at DESC
             LIMIT ?
            """,
            tuple(parameters),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def context_block(
        self,
        *,
        limit: int | None = None,
        query: MemoryQuery | None = None,
    ) -> str:
        request = query or MemoryQuery(
            limit=self._context_limit if limit is None else int(limit),
        )
        if limit is not None and query is not None:
            request = MemoryQuery(
                session_id=request.session_id,
                project_id=request.project_id,
                include_global=request.include_global,
                limit=int(limit),
            )
        memories = self.query(request)
        if not memories:
            return "No durable memories yet."
        return "\n".join(
            f"- {item['kind']}/{item['scope']} [{item['memory_id']}]"
            f" (actor={item['actor']}, source_run={item['source_run_id'] or 'manual'}): "
            f"{item['content']}"
            for item in memories
        )
