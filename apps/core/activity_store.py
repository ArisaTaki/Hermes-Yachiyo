"""Persistent activity log for agent/tool execution events.

Activity events are intentionally separate from chat messages. Chat messages
capture the conversation; this store captures the operational timeline that the
dashboard and chat progress UI can query.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_DB_FILENAME = "activity.db"
_DETAIL_MAX_CHARS = 600
_TITLE_MAX_CHARS = 140
_METADATA_MAX_CHARS = 4000
_NOISY_PHASES = ("thinking", "reasoning", "tool_progress")
_KEY_PHASES = (
    "task_start",
    "task_complete",
    "task_failed",
    "task_cancelled",
    "tool_start",
    "tool_complete",
    "subagent",
)
_TERMINAL_STATUSES = ("completed", "success", "failed", "error", "cancelled")
_STATUS_FILTER_ALIASES = {
    "running": ("running", "progress", "pending"),
    "completed": ("completed", "success"),
    "failed": ("failed", "error"),
    "cancelled": ("cancelled",),
}
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|bearer)\b"
        r"\s*[:=]\s*([^\s,;\"']{6,})"
    ),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{12,})\b"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_db_path() -> str:
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    yachiyo_dir = os.path.join(hermes_home, "yachiyo")
    os.makedirs(yachiyo_dir, exist_ok=True)
    return os.path.join(yachiyo_dir, _DB_FILENAME)


def redact_sensitive_text(value: Any, *, limit: int = _DETAIL_MAX_CHARS) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\s+", " ", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=[redacted]" if match.lastindex and match.lastindex > 1 else "[redacted]", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return redact_sensitive_text(value, limit=160)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            key_text = redact_sensitive_text(key, limit=80)
            if re.search(r"(?i)(key|token|password|secret|authorization)", key_text):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = _sanitize_metadata(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(item, depth=depth + 1) for item in list(value)[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_sensitive_text(value, limit=300)


def _metadata_json(value: Any) -> str:
    try:
        text = json.dumps(_sanitize_metadata(value or {}), ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = json.dumps({"value": redact_sensitive_text(value)}, ensure_ascii=False)
    if len(text) > _METADATA_MAX_CHARS:
        return text[: _METADATA_MAX_CHARS - 1] + "…"
    return text


@dataclass
class StoredActivity:
    event_id: str
    session_id: str
    task_id: str
    tool_name: str
    phase: str
    title: str
    detail: str
    status: str
    duration_seconds: float | None
    created_at: str
    metadata_json: str = "{}"

    def to_dict(self) -> dict[str, Any]:
        try:
            metadata = json.loads(self.metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "phase": self.phase,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
            "metadata": metadata,
        }


class ActivityStore:
    """SQLite-backed activity event log."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_activity_created_at
                    ON activity_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_activity_session_task
                    ON activity_events(session_id, task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_activity_tool_status
                    ON activity_events(tool_name, status, created_at DESC);
                """
            )
            conn.commit()
        logger.info("ActivityStore 初始化完成: %s", self._db_path)

    def record_event(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        tool_name: str = "",
        phase: str = "",
        title: str = "",
        detail: str = "",
        status: str = "running",
        duration_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        event_id: str | None = None,
    ) -> StoredActivity:
        event = StoredActivity(
            event_id=event_id or uuid4().hex[:12],
            session_id=redact_sensitive_text(session_id, limit=80),
            task_id=redact_sensitive_text(task_id, limit=80),
            tool_name=redact_sensitive_text(tool_name, limit=80),
            phase=redact_sensitive_text(phase, limit=80),
            title=redact_sensitive_text(title or detail or tool_name or "Hermes 活动", limit=_TITLE_MAX_CHARS),
            detail=redact_sensitive_text(detail, limit=_DETAIL_MAX_CHARS),
            status=redact_sensitive_text(status or "running", limit=40),
            duration_seconds=duration_seconds if isinstance(duration_seconds, (int, float)) else None,
            created_at=created_at or _now(),
            metadata_json=_metadata_json(metadata or {}),
        )
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO activity_events
                    (event_id, session_id, task_id, tool_name, phase, title, detail, status,
                     duration_seconds, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.task_id,
                    event.tool_name,
                    event.phase,
                    event.title,
                    event.detail,
                    event.status,
                    event.duration_seconds,
                    event.created_at,
                    event.metadata_json,
                ),
            )
            conn.commit()
        return event

    def list_events(
        self,
        *,
        limit: int = 50,
        query: str = "",
        status: str = "",
        tool: str = "",
        phase: str = "",
        session_id: str = "",
        task_id: str = "",
        key_only: bool = False,
    ) -> list[StoredActivity]:
        clauses: list[str] = []
        args: list[Any] = []
        if query:
            clauses.append("(title LIKE ? OR detail LIKE ? OR tool_name LIKE ?)")
            needle = f"%{query}%"
            args.extend([needle, needle, needle])
        if status:
            status_values = _STATUS_FILTER_ALIASES.get(status, (status,))
            if len(status_values) == 1:
                clauses.append("status = ?")
                args.append(status_values[0])
            else:
                placeholders = ", ".join("?" for _ in status_values)
                clauses.append(f"status IN ({placeholders})")
                args.extend(status_values)
        if tool:
            clauses.append("tool_name = ?")
            args.append(tool)
        if phase:
            clauses.append("phase = ?")
            args.append(phase)
        if session_id:
            clauses.append("session_id = ?")
            args.append(session_id)
        if task_id:
            clauses.append("task_id = ?")
            args.append(task_id)
        if key_only:
            phase_placeholders = ", ".join("?" for _ in _KEY_PHASES)
            status_placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
            noisy_placeholders = ", ".join("?" for _ in _NOISY_PHASES)
            clauses.append(
                f"(phase IN ({phase_placeholders}) "
                f"OR (status IN ({status_placeholders}) AND phase NOT IN ({noisy_placeholders})))"
            )
            args.extend(_KEY_PHASES)
            args.extend(_TERMINAL_STATUSES)
            args.extend(_NOISY_PHASES)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            rows = self._get_conn().execute(
                f"""
                SELECT event_id, session_id, task_id, tool_name, phase, title, detail, status,
                       duration_seconds, created_at, metadata_json
                FROM activity_events
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()
        return [_activity_from_row(row) for row in rows]

    def latest_for_task(self, task_id: str, limit: int = 5, *, key_only: bool = False) -> list[StoredActivity]:
        return self.list_events(task_id=task_id, limit=limit, key_only=key_only)

    def get_event(self, event_id: str) -> StoredActivity | None:
        event_id = redact_sensitive_text(event_id, limit=80)
        if not event_id:
            return None
        with self._lock:
            row = self._get_conn().execute(
                """
                SELECT event_id, session_id, task_id, tool_name, phase, title, detail, status,
                       duration_seconds, created_at, metadata_json
                FROM activity_events
                WHERE event_id = ?
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
        return _activity_from_row(row) if row is not None else None

    def delete_event(self, event_id: str) -> bool:
        event_id = redact_sensitive_text(event_id, limit=80)
        if not event_id:
            return False
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM activity_events WHERE event_id = ?",
                (event_id,),
            )
            self._get_conn().commit()
            return int(cursor.rowcount or 0) > 0

    def delete_events(self, event_ids: list[str]) -> int:
        ids = [redact_sensitive_text(event_id, limit=80) for event_id in event_ids if event_id]
        unique_ids = sorted(set(event_id for event_id in ids if event_id))
        if not unique_ids:
            return 0
        placeholders = ", ".join("?" for _ in unique_ids)
        with self._lock:
            cursor = self._get_conn().execute(
                f"DELETE FROM activity_events WHERE event_id IN ({placeholders})",
                unique_ids,
            )
            self._get_conn().commit()
            return int(cursor.rowcount or 0)

    def latest_by_task(
        self,
        task_ids: list[str],
        limit_per_task: int = 5,
        *,
        key_only: bool = False,
    ) -> dict[str, list[StoredActivity]]:
        result: dict[str, list[StoredActivity]] = {}
        for task_id in task_ids:
            if task_id:
                result[task_id] = self.latest_for_task(task_id, limit_per_task, key_only=key_only)
        return result

    def finalize_task_events(self, task_id: str, *, status: str = "completed") -> int:
        """Move all non-terminal activity rows for a task into a terminal state."""
        task_id = redact_sensitive_text(task_id, limit=80)
        if not task_id:
            return 0
        terminal_status = redact_sensitive_text(status or "completed", limit=40)
        if terminal_status not in set(_TERMINAL_STATUSES):
            terminal_status = "completed"
        with self._lock:
            cursor = self._get_conn().execute(
                """
                UPDATE activity_events
                SET status = ?
                WHERE task_id = ?
                  AND status NOT IN ('completed', 'success', 'failed', 'error', 'cancelled')
                """,
                (terminal_status, task_id),
            )
            self._get_conn().commit()
            return int(cursor.rowcount or 0)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    logger.debug("ActivityStore WAL checkpoint failed", exc_info=True)
                self._conn.close()
                self._conn = None


def _activity_from_row(row: sqlite3.Row) -> StoredActivity:
    return StoredActivity(
        event_id=row["event_id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        tool_name=row["tool_name"],
        phase=row["phase"],
        title=row["title"],
        detail=row["detail"],
        status=row["status"],
        duration_seconds=row["duration_seconds"],
        created_at=row["created_at"],
        metadata_json=row["metadata_json"] or "{}",
    )


_global_store: ActivityStore | None = None
_global_store_lock = threading.RLock()


def get_activity_store() -> ActivityStore:
    global _global_store
    store = _global_store
    if store is not None:
        return store
    with _global_store_lock:
        if _global_store is None:
            _global_store = ActivityStore()
        return _global_store


def close_activity_store() -> None:
    global _global_store
    with _global_store_lock:
        if _global_store is not None:
            _global_store.close()
            _global_store = None
