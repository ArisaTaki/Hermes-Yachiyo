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
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_DB_FILENAME = "chat.db"
_SESSION_TITLE_MAX_CHARS = 36


def _get_db_path() -> str:
    """获取数据库文件路径：~/.hermes/yachiyo/chat.db"""
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    yachiyo_dir = os.path.join(hermes_home, "yachiyo")
    os.makedirs(yachiyo_dir, exist_ok=True)
    return os.path.join(yachiyo_dir, _DB_FILENAME)


def make_session_title(content: str, max_chars: int = _SESSION_TITLE_MAX_CHARS) -> str:
    """从首条用户消息生成会话列表标题。"""
    title = " ".join((content or "").split())
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


@dataclass
class StoredSession:
    """持久化的会话记录"""
    session_id: str
    title: str
    created_at: str  # ISO 格式
    message_count: int = 0
    hermes_session_id: Optional[str] = None


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
                    hermes_session_id TEXT
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
                HAVING COUNT(m.message_id) > 0
                ORDER BY s.created_at DESC
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
                WHERE EXISTS (
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
                    (message_id, session_id, role, content, status, task_id, error, created_at, attachments_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def load_messages(
        self, session_id: str, limit: int = 100
    ) -> List[StoredMessage]:
        """加载会话消息（按时间正序）"""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """
                SELECT message_id, session_id, role, content, status, task_id, error, created_at, attachments_json
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
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
            )
            for r in rows
        ]

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn is not None:
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
