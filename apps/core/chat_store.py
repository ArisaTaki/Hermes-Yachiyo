"""聊天持久化层

SQLite 存储聊天会话与消息，供 ChatSession 消费。
数据库位置：~/.hermes/yachiyo/chat.db

表结构：
  - chat_sessions: 会话元信息（id、创建时间、标题）
  - chat_messages: 消息记录（关联 session_id）

职责边界：
  - ChatStore 只做 CRUD，不含业务逻辑
  - ChatSession 调用 ChatStore 完成持久化
  - UI 层不直接接触 ChatStore
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_DB_FILENAME = "chat.db"
_SESSION_TITLE_MAX_CHARS = 36
_TITLE_SENTENCE_BOUNDARY_RE = re.compile(r"[。.!！?？\n\r]")
_LEADING_MENTION_RE = re.compile(
    r"^\s*@(?:\"[^\"]+\"|'[^']+'|“[^”]+”|‘[^’]+’|[^\s@:：，。！？、；;,.!?]+)"
    r"[\s:：,，、;；-]*"
)


def _get_db_path() -> str:
    """获取数据库文件路径：~/.hermes/yachiyo/chat.db"""
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    yachiyo_dir = os.path.join(hermes_home, "yachiyo")
    os.makedirs(yachiyo_dir, exist_ok=True)
    return os.path.join(yachiyo_dir, _DB_FILENAME)


def make_session_title(content: str, max_chars: int = _SESSION_TITLE_MAX_CHARS) -> str:
    """从首条用户消息生成会话列表标题。"""
    title = _first_user_sentence_title(content)
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


def _first_user_sentence_title(content: str) -> str:
    title = strip_leading_session_mentions(" ".join((content or "").split()).strip())
    if not title:
        return ""
    boundary = _TITLE_SENTENCE_BOUNDARY_RE.search(title)
    if boundary and boundary.start() > 0:
        title = title[:boundary.end()]
    return title.strip(" \t\r\n\"'“”‘’`*_#")


def strip_leading_session_mentions(value: str) -> str:
    title = value
    while True:
        next_title = _LEADING_MENTION_RE.sub("", title, count=1).strip()
        if next_title == title:
            return title
        title = next_title


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class StoredSession:
    """持久化的会话记录"""
    session_id: str
    title: str
    created_at: str  # ISO 格式
    message_count: int = 0
    hermes_session_id: Optional[str] = None
    conversation_kind: str = "main"
    runnable_id: str = ""
    runnable_name: str = ""
    run_group_id: str = ""
    participants_json: str = "[]"


@dataclass
class StoredSessionSearchResult:
    """会话搜索结果，包含第一条命中的消息上下文。"""
    session: StoredSession
    match_message_id: Optional[str] = None
    match_role: str = ""
    match_content: str = ""
    match_created_at: str = ""
    match_count: int = 0


@dataclass
class StoredMessage:
    """持久化的消息记录"""
    message_id: str
    session_id: str
    role: str       # user / assistant / system
    content: str
    status: str     # pending / processing / completed / failed
    task_id: Optional[str]
    error: Optional[str]
    created_at: str  # ISO 格式
    attachments_json: str = "[]"
    metadata_json: str = "{}"


class ChatStore:
    """SQLite 聊天持久化"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        """创建表结构（幂等）"""
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title      TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    hermes_session_id TEXT,
                    conversation_kind TEXT NOT NULL DEFAULT 'main',
                    runnable_id TEXT NOT NULL DEFAULT '',
                    runnable_name TEXT NOT NULL DEFAULT '',
                    run_group_id TEXT NOT NULL DEFAULT '',
                    participants_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'completed',
                    task_id    TEXT,
                    error      TEXT,
                    created_at TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON chat_messages(session_id, created_at);
            """)
            # 兼容旧表结构升级
            try:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN hermes_session_id TEXT")
            except sqlite3.OperationalError:
                pass  # 列已存在
            try:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass  # 列已存在
            for name, definition in (
                ("conversation_kind", "TEXT NOT NULL DEFAULT 'main'"),
                ("runnable_id", "TEXT NOT NULL DEFAULT ''"),
                ("runnable_name", "TEXT NOT NULL DEFAULT ''"),
                ("run_group_id", "TEXT NOT NULL DEFAULT ''"),
                ("participants_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                try:
                    conn.execute(f"ALTER TABLE chat_sessions ADD COLUMN {name} {definition}")
                except sqlite3.OperationalError:
                    pass  # 列已存在
            try:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass  # 列已存在
            conn.commit()
        logger.info("ChatStore 初始化完成: %s", self._db_path)

    # ── 会话 CRUD ─────────────────────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "") -> None:
        """创建新会话"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO chat_sessions (session_id, title, created_at) VALUES (?, ?, ?)",
                (session_id, title, now),
            )
            conn.commit()

    def list_sessions(self, limit: int = 20) -> List[StoredSession]:
        """列出最近的会话"""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                SELECT s.session_id, s.title, s.created_at, s.hermes_session_id,
                       s.conversation_kind, s.runnable_id, s.runnable_name,
                       s.run_group_id, s.participants_json,
                       MAX(m.created_at) AS last_message_at,
                       (
                           SELECT um.content
                           FROM chat_messages um
                           WHERE um.session_id = s.session_id
                             AND um.role = 'user'
                           ORDER BY um.created_at ASC
                           LIMIT 1
                       ) AS first_user_content,
                       COUNT(m.message_id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                GROUP BY s.session_id
                HAVING COUNT(m.message_id) > 0 OR s.conversation_kind = 'group'
                ORDER BY COALESCE(last_message_at, s.created_at) DESC, s.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            StoredSession(
                session_id=r["session_id"],
                title=r["title"] or make_session_title(r["first_user_content"] or ""),
                created_at=r["created_at"],
                message_count=r["message_count"],
                hermes_session_id=r["hermes_session_id"],
                conversation_kind=r["conversation_kind"] or "main",
                runnable_id=r["runnable_id"] or "",
                runnable_name=r["runnable_name"] or "",
                run_group_id=r["run_group_id"] or "",
                participants_json=r["participants_json"] or "[]",
            )
            for r in rows
        ]

    def search_sessions(self, query: str, limit: int = 50) -> List[StoredSessionSearchResult]:
        """按标题、会话 ID、Hermes ID 或消息内容搜索会话。"""
        normalized_query = " ".join((query or "").split()).strip()
        if not normalized_query:
            return [
                StoredSessionSearchResult(session=session)
                for session in self.list_sessions(limit=limit)
            ]
        like = f"%{_escape_like(normalized_query)}%"
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                WITH visible_sessions AS (
                    SELECT s.session_id, s.title, s.created_at, s.hermes_session_id,
                           s.conversation_kind, s.runnable_id, s.runnable_name,
                           s.run_group_id, s.participants_json,
                           MAX(m.created_at) AS last_message_at,
                           (
                               SELECT um.content
                               FROM chat_messages um
                               WHERE um.session_id = s.session_id
                                 AND um.role = 'user'
                               ORDER BY um.created_at ASC
                               LIMIT 1
                           ) AS first_user_content,
                           COUNT(m.message_id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.session_id
                    GROUP BY s.session_id
                    HAVING COUNT(m.message_id) > 0 OR s.conversation_kind = 'group'
                )
                SELECT vs.session_id, vs.title, vs.created_at, vs.hermes_session_id,
                       vs.conversation_kind, vs.runnable_id, vs.runnable_name,
                       vs.run_group_id, vs.participants_json,
                       vs.first_user_content, vs.message_count, vs.last_message_at,
                       mm.message_id AS match_message_id,
                       mm.role AS match_role,
                       mm.content AS match_content,
                       mm.created_at AS match_created_at,
                       (
                           SELECT COUNT(*)
                           FROM chat_messages mc
                           WHERE mc.session_id = vs.session_id
                             AND mc.content LIKE ? ESCAPE '\\'
                       ) AS match_count
                FROM visible_sessions vs
                LEFT JOIN chat_messages mm ON mm.message_id = (
                    SELECT m2.message_id
                    FROM chat_messages m2
                    WHERE m2.session_id = vs.session_id
                      AND m2.content LIKE ? ESCAPE '\\'
                    ORDER BY m2.created_at DESC, m2.message_id DESC
                    LIMIT 1
                )
                WHERE vs.session_id LIKE ? ESCAPE '\\'
                   OR COALESCE(vs.title, '') LIKE ? ESCAPE '\\'
                   OR COALESCE(vs.hermes_session_id, '') LIKE ? ESCAPE '\\'
                   OR COALESCE(vs.runnable_name, '') LIKE ? ESCAPE '\\'
                   OR EXISTS (
                       SELECT 1
                       FROM chat_messages mx
                       WHERE mx.session_id = vs.session_id
                         AND mx.content LIKE ? ESCAPE '\\'
                   )
                ORDER BY COALESCE(mm.created_at, vs.last_message_at, vs.created_at) DESC,
                         vs.created_at DESC
                LIMIT ?
                """,
                (like, like, like, like, like, like, like, limit),
            ).fetchall()
        return [
            StoredSessionSearchResult(
                session=StoredSession(
                    session_id=r["session_id"],
                    title=r["title"] or make_session_title(r["first_user_content"] or ""),
                    created_at=r["created_at"],
                    message_count=r["message_count"],
                    hermes_session_id=r["hermes_session_id"],
                    conversation_kind=r["conversation_kind"] or "main",
                    runnable_id=r["runnable_id"] or "",
                    runnable_name=r["runnable_name"] or "",
                    run_group_id=r["run_group_id"] or "",
                    participants_json=r["participants_json"] or "[]",
                ),
                match_message_id=r["match_message_id"],
                match_role=r["match_role"] or "",
                match_content=r["match_content"] or "",
                match_created_at=r["match_created_at"] or "",
                match_count=int(r["match_count"] or 0),
            )
            for r in rows
        ]

    def count_sessions(self) -> int:
        """统计可见历史会话数（不包含无消息的空白工作会话）。"""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM chat_sessions s
                WHERE s.conversation_kind = 'group'
                   OR EXISTS (
                       SELECT 1
                       FROM chat_messages m
                       WHERE m.session_id = s.session_id
                   )
                """
            ).fetchone()
        return int(row["count"])

    def get_session(self, session_id: str) -> Optional[StoredSession]:
        """获取单个会话信息"""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """
                SELECT s.session_id, s.title, s.created_at, s.hermes_session_id,
                       s.conversation_kind, s.runnable_id, s.runnable_name,
                       s.run_group_id, s.participants_json,
                       COUNT(m.message_id) AS message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                WHERE s.session_id = ?
                GROUP BY s.session_id
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredSession(
            session_id=row["session_id"],
            title=row["title"],
            created_at=row["created_at"],
            message_count=row["message_count"],
            hermes_session_id=row["hermes_session_id"],
            conversation_kind=row["conversation_kind"] or "main",
            runnable_id=row["runnable_id"] or "",
            runnable_name=row["runnable_name"] or "",
            run_group_id=row["run_group_id"] or "",
            participants_json=row["participants_json"] or "[]",
        )

    def update_hermes_session_id(self, session_id: str, hermes_session_id: str) -> None:
        """更新会话的 Hermes session ID"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE chat_sessions SET hermes_session_id = ? WHERE session_id = ?",
                (hermes_session_id, session_id),
            )
            conn.commit()

    def update_session_title(self, session_id: str, title: str) -> None:
        """更新会话标题。"""
        title = (title or "").strip()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE chat_sessions SET title = ? WHERE session_id = ?",
                (title, session_id),
            )
            conn.commit()

    def update_session_context(
        self,
        session_id: str,
        *,
        conversation_kind: str = "main",
        runnable_id: str = "",
        runnable_name: str = "",
        run_group_id: str = "",
        participants_json: str = "[]",
    ) -> None:
        """Persist the conversation identity used by the desktop chat shell."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                UPDATE chat_sessions
                   SET conversation_kind = ?,
                       runnable_id = ?,
                       runnable_name = ?,
                       run_group_id = ?,
                       participants_json = ?
                 WHERE session_id = ?
                """,
                (
                    (conversation_kind or "main").strip() or "main",
                    (runnable_id or "").strip(),
                    (runnable_name or "").strip(),
                    (run_group_id or "").strip(),
                    participants_json or "[]",
                    session_id,
                ),
            )
            conn.commit()

    def set_session_title_if_empty(self, session_id: str, title: str) -> bool:
        """仅当标题为空时写入标题，返回是否发生更新。"""
        title = (title or "").strip()
        if not title:
            return False
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?
                WHERE session_id = ?
                  AND title = ''
                """,
                (title, session_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> None:
        """删除会话及其所有消息"""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    # ── 消息 CRUD ─────────────────────────────────────────────────────────────

    def save_message(self, msg: StoredMessage) -> None:
        """保存单条消息（INSERT OR REPLACE）"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_messages
                    (message_id, session_id, role, content, status, task_id, error, created_at, attachments_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_id,
                    msg.session_id,
                    msg.role,
                    msg.content,
                    msg.status,
                    msg.task_id,
                    msg.error,
                    msg.created_at,
                    msg.attachments_json,
                    msg.metadata_json,
                ),
            )
            conn.commit()

    def update_message_status(
        self, message_id: str, status: str, error: Optional[str] = None
    ) -> None:
        """更新消息状态"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE chat_messages SET status = ?, error = ? WHERE message_id = ?",
                (status, error, message_id),
            )
            conn.commit()

    def load_assistant_messages_by_task(
        self, session_id: str, task_id: str
    ) -> List[StoredMessage]:
        """加载某个任务对应的 assistant 消息，用于跨实例 upsert 去重。"""
        if not session_id or not task_id:
            return []
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                SELECT message_id, session_id, role, content, status, task_id, error,
                       created_at, attachments_json, metadata_json
                FROM chat_messages
                WHERE session_id = ?
                  AND task_id = ?
                  AND role = 'assistant'
                ORDER BY created_at ASC, message_id ASC
                """,
                (session_id, task_id),
            ).fetchall()
        return [
            StoredMessage(
                message_id=r["message_id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                status=r["status"],
                task_id=r["task_id"],
                error=r["error"],
                created_at=r["created_at"],
                attachments_json=r["attachments_json"] or "[]",
                metadata_json=r["metadata_json"] or "{}",
            )
            for r in rows
        ]

    def delete_messages(self, message_ids: list[str]) -> int:
        """按 message_id 批量删除消息，返回删除数量。"""
        ids = [message_id for message_id in message_ids if message_id]
        if not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            cursor = conn.executemany(
                "DELETE FROM chat_messages WHERE message_id = ?",
                [(message_id,) for message_id in ids],
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def load_messages(
        self, session_id: str, limit: int = 100
    ) -> List[StoredMessage]:
        """加载会话消息（按时间正序）。

        limit > 0 时返回最近 N 条；limit <= 0 时返回全部消息。
        """
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError):
            normalized_limit = 100
        with self._lock:
            conn = self._get_conn()
            if normalized_limit <= 0:
                rows = conn.execute(
                    """
                    SELECT message_id, session_id, role, content, status, task_id, error, created_at, attachments_json, metadata_json
                    FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT message_id, session_id, role, content, status, task_id, error, created_at, attachments_json, metadata_json
                    FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (session_id, normalized_limit),
                ).fetchall()
                rows = list(reversed(rows))
        return [
            StoredMessage(
                message_id=r["message_id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                status=r["status"],
                task_id=r["task_id"],
                error=r["error"],
                created_at=r["created_at"],
                attachments_json=r["attachments_json"] or "[]",
                metadata_json=r["metadata_json"] or "{}",
            )
            for r in rows
        ]

    def load_messages_around(
        self,
        session_id: str,
        message_id: str,
        *,
        before: int = 80,
        after: int = 40,
    ) -> List[StoredMessage]:
        """加载某条消息附近的上下文，按时间正序返回。"""
        session_id = (session_id or "").strip()
        message_id = (message_id or "").strip()
        if not session_id or not message_id:
            return []
        before = max(0, min(int(before or 0), 400))
        after = max(0, min(int(after or 0), 400))
        with self._lock:
            conn = self._get_conn()
            anchor = conn.execute(
                """
                SELECT rowid
                FROM chat_messages
                WHERE session_id = ?
                  AND message_id = ?
                LIMIT 1
                """,
                (session_id, message_id),
            ).fetchone()
            if anchor is None:
                return []
            anchor_rowid = int(anchor["rowid"])
            before_rows = conn.execute(
                """
                SELECT message_id, session_id, role, content, status, task_id, error,
                       created_at, attachments_json, metadata_json
                FROM chat_messages
                WHERE session_id = ?
                  AND rowid <= ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (session_id, anchor_rowid, before + 1),
            ).fetchall()
            after_rows = conn.execute(
                """
                SELECT message_id, session_id, role, content, status, task_id, error,
                       created_at, attachments_json, metadata_json
                FROM chat_messages
                WHERE session_id = ?
                  AND rowid > ?
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (session_id, anchor_rowid, after),
            ).fetchall()
        rows = list(reversed(before_rows)) + list(after_rows)
        return [
            StoredMessage(
                message_id=r["message_id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                status=r["status"],
                task_id=r["task_id"],
                error=r["error"],
                created_at=r["created_at"],
                attachments_json=r["attachments_json"] or "[]",
                metadata_json=r["metadata_json"] or "{}",
            )
            for r in rows
        ]

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    logger.debug("ChatStore WAL checkpoint failed", exc_info=True)
                self._conn.close()
                self._conn = None


# ── 全局实例 ──────────────────────────────────────────────────────────────────

_global_store: Optional[ChatStore] = None
_global_store_lock = threading.RLock()


def get_chat_store() -> ChatStore:
    """获取全局 ChatStore 单例"""
    global _global_store
    store = _global_store
    if store is not None:
        return store

    with _global_store_lock:
        if _global_store is None:
            _global_store = ChatStore()
    return _global_store


def close_chat_store() -> None:
    """Close the global ChatStore without creating a new one."""
    global _global_store
    with _global_store_lock:
        if _global_store is not None:
            _global_store.close()
            _global_store = None
