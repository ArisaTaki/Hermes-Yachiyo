"""统一聊天/会话层

ChatSession 是三种显示模式（window / bubble / live2d）共享的消息状态容器。

职责：
  - 管理当前会话的消息列表（user / assistant / system）
  - 追踪发送中状态（pending message）
  - 追踪最近任务 ID（关联 task 结果）
  - 不直接执行任务，只维护消息状态

消息流：
  1. UI 调用 add_user_message(text) → 返回 message_id
  2. UI 创建 task（通过 AppState.create_task）
  3. UI 调用 link_message_to_task(message_id, task_id) → 关联消息与任务
  4. TaskRunner 执行完毕后，调用 add_assistant_message(text, task_id)
  5. UI 轮询 get_messages() 获取最新消息列表

消息会通过 ChatStore 持久化到 SQLite。进程重启时默认恢复最近会话。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from apps.core.chat_store import ChatStore

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """消息状态"""
    PENDING = "pending"      # 用户消息已发送，等待 agent 回复
    PROCESSING = "processing"  # 任务正在执行
    COMPLETED = "completed"  # 已收到回复
    FAILED = "failed"        # 处理失败


@dataclass
class ChatMessage:
    """单条聊天消息"""
    message_id: str
    role: MessageRole
    content: str
    status: MessageStatus
    created_at: datetime
    task_id: Optional[str] = None  # 关联的任务 ID（仅 user 消息）
    error: Optional[str] = None    # 失败原因


@dataclass
class ChatSession:
    """聊天会话状态容器
    
    线程安全性：多窗口 WebView API 和 TaskRunner 可能并发读写同一会话，
    所有公开读写方法都通过内部 RLock 保护。
    """
    session_id: str = field(default_factory=lambda: uuid4().hex[:8])
    messages: List[ChatMessage] = field(default_factory=list)
    hermes_session_id: Optional[str] = field(default=None)
    _pending_message_id: Optional[str] = field(default=None, repr=False)
    _store: Optional["ChatStore"] = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def attach_store(self, store: "ChatStore", load_existing: bool = True) -> None:
        """绑定持久化层，并创建/加载会话。"""
        with self._lock:
            self._store = store
            store.create_session(self.session_id)
            if load_existing:
                self._load_messages_from_store()
                # 恢复 hermes_session_id
                stored_session = store.get_session(self.session_id)
                if stored_session and stored_session.hermes_session_id:
                    self.hermes_session_id = stored_session.hermes_session_id

    def _load_messages_from_store(self) -> None:
        """从持久化层恢复当前会话消息。"""
        if self._store is None:
            return

        restored: list[ChatMessage] = []
        for stored in self._store.load_messages(self.session_id):
            try:
                role = MessageRole(stored.role)
                status = MessageStatus(stored.status)
                created_at = datetime.fromisoformat(stored.created_at)
            except ValueError:
                logger.warning("跳过无法恢复的聊天消息: %s", stored.message_id)
                continue

            error = stored.error
            if status in (MessageStatus.PENDING, MessageStatus.PROCESSING):
                status = MessageStatus.FAILED
                error = error or "应用已重启，原任务状态不可恢复"
                self._store.update_message_status(stored.message_id, status.value, error)

            restored.append(ChatMessage(
                message_id=stored.message_id,
                role=role,
                content=stored.content,
                status=status,
                created_at=created_at,
                task_id=stored.task_id,
                error=error,
            ))

        self.messages = restored
        self._pending_message_id = None

    def _persist_message(self, msg: ChatMessage) -> None:
        """将消息写入持久化层（若已绑定）"""
        if self._store is None:
            return
        from apps.core.chat_store import StoredMessage
        self._store.save_message(StoredMessage(
            message_id=msg.message_id,
            session_id=self.session_id,
            role=msg.role.value,
            content=msg.content,
            status=msg.status.value,
            task_id=msg.task_id,
            error=msg.error,
            created_at=msg.created_at.isoformat(),
        ))

    def _ensure_summary_title_locked(self, content: str) -> None:
        """为无标题会话写入首条用户消息摘要。调用方需持有 _lock。"""
        if self._store is None:
            return
        from apps.core.chat_store import make_session_title

        title = make_session_title(content)
        if title:
            self._store.set_session_title_if_empty(self.session_id, title)
    
    def add_user_message(self, content: str) -> str:
        """添加用户消息，返回 message_id"""
        with self._lock:
            msg_id = uuid4().hex[:12]
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.USER,
                content=content,
                status=MessageStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            self.messages.append(msg)
            self._pending_message_id = msg_id
            self._persist_message(msg)
            self._ensure_summary_title_locked(content)
        logger.info("用户消息已添加: %s (len=%d)", msg_id, len(content))
        return msg_id
    
    def link_message_to_task(self, message_id: str, task_id: str) -> bool:
        """将消息与任务关联。

        这里只建立关联，不代表任务已经开始运行。用户消息保持 PENDING，
        直到 TaskStatus.RUNNING 同步过来后再切换为 PROCESSING。
        """
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.task_id = task_id
                    self._persist_message(msg)
                    logger.debug("消息 %s 关联任务 %s", message_id, task_id)
                    return True
        return False
    
    def add_assistant_message(
        self,
        content: str,
        task_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> str:
        """添加 assistant 回复消息（向后兼容）

        注意：对于 task 关联的 assistant 消息，应优先使用
        upsert_assistant_message() 以保证幂等性。
        """
        with self._lock:
            msg_id = uuid4().hex[:12]
            status = MessageStatus.FAILED if error else MessageStatus.COMPLETED
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.ASSISTANT,
                content=content,
                status=status,
                created_at=datetime.now(timezone.utc),
                task_id=task_id,
                error=error,
            )
            self.messages.append(msg)

            # 更新对应 user 消息状态
            if task_id:
                for m in self.messages:
                    if m.task_id == task_id and m.role == MessageRole.USER:
                        m.status = status
                        if error:
                            m.error = error
                        self._persist_message(m)
                        break

            self._pending_message_id = self._find_active_message_id_locked()
            self._persist_message(msg)
        logger.info("Assistant 回复已添加: %s (task=%s)", msg_id, task_id)
        return msg_id

    def upsert_assistant_message(
        self,
        task_id: str,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        error: Optional[str] = None,
    ) -> str:
        """原子性地创建或更新 task_id 对应的 assistant 消息。

        同一个 task_id 至多只有一条 assistant 消息。
        已存在则更新 content/status/error，否则创建。
        同时同步更新关联 user 消息的状态。

        幂等：多次调用相同参数不会产生重复消息。
        线程安全：check + create/update 在同一把锁内完成。
        """
        with self._lock:
            # ① 查找已有的 assistant 消息
            existing: Optional[ChatMessage] = None
            for msg in self.messages:
                if msg.role == MessageRole.ASSISTANT and msg.task_id == task_id:
                    existing = msg
                    break

            if existing is not None:
                # 不允许从终态回退到 PROCESSING
                if (
                    existing.status in (MessageStatus.COMPLETED, MessageStatus.FAILED)
                    and status == MessageStatus.PROCESSING
                ):
                    return existing.message_id
                existing.content = content
                existing.status = status
                existing.error = error
                self._persist_message(existing)
                msg_id = existing.message_id
                logger.debug(
                    "Assistant 消息已更新: %s (task=%s, status=%s)",
                    msg_id, task_id, status.value,
                )
            else:
                # ② 不存在，创建新消息
                msg_id = uuid4().hex[:12]
                new_msg = ChatMessage(
                    message_id=msg_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    status=status,
                    created_at=datetime.now(timezone.utc),
                    task_id=task_id,
                    error=error,
                )
                self.messages.append(new_msg)
                self._persist_message(new_msg)
                logger.info(
                    "Assistant 消息已创建: %s (task=%s, status=%s)",
                    msg_id, task_id, status.value,
                )

            # ③ 同步更新关联 user 消息状态
            for m in self.messages:
                if m.task_id == task_id and m.role == MessageRole.USER:
                    m.status = status
                    if status == MessageStatus.FAILED and error:
                        m.error = error
                    self._persist_message(m)
                    break

            self._pending_message_id = self._find_active_message_id_locked()
            return msg_id
    
    def add_system_message(self, content: str) -> str:
        """添加系统消息（提示、状态更新等）"""
        with self._lock:
            msg_id = uuid4().hex[:12]
            msg = ChatMessage(
                message_id=msg_id,
                role=MessageRole.SYSTEM,
                content=content,
                status=MessageStatus.COMPLETED,
                created_at=datetime.now(timezone.utc),
            )
            self.messages.append(msg)
            self._persist_message(msg)
            return msg_id
    
    def mark_message_failed(self, message_id: str, error: str) -> bool:
        """标记消息处理失败"""
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.status = MessageStatus.FAILED
                    msg.error = error
                    self._pending_message_id = self._find_active_message_id_locked()
                    self._persist_message(msg)
                    return True
        return False

    def mark_message_processing(self, message_id: str) -> bool:
        """标记用户消息进入执行中状态。"""
        with self._lock:
            for msg in self.messages:
                if msg.message_id == message_id:
                    msg.status = MessageStatus.PROCESSING
                    self._pending_message_id = message_id
                    self._persist_message(msg)
                    return True
        return False
    
    def get_messages(self, limit: int = 50) -> List[ChatMessage]:
        """获取最近 N 条消息"""
        with self._lock:
            return list(self.messages[-limit:])

    def get_all_messages(self) -> List[ChatMessage]:
        """获取当前会话全部消息的快照。"""
        with self._lock:
            return list(self.messages)

    def has_assistant_reply(self, task_id: str) -> bool:
        """是否已经存在某个任务对应的 assistant 回复。"""
        with self._lock:
            return any(
                m.role == MessageRole.ASSISTANT and m.task_id == task_id
                for m in self.messages
            )

    def get_assistant_message_for_task(self, task_id: str) -> Optional[ChatMessage]:
        """获取某个任务对应的 assistant 消息。"""
        with self._lock:
            for msg in self.messages:
                if msg.role == MessageRole.ASSISTANT and msg.task_id == task_id:
                    return msg
        return None

    def message_count(self) -> int:
        """当前会话消息数量。"""
        with self._lock:
            return len(self.messages)
    
    def get_last_assistant_message(self) -> Optional[ChatMessage]:
        """获取最新一条 assistant 消息"""
        with self._lock:
            for msg in reversed(self.messages):
                if msg.role == MessageRole.ASSISTANT:
                    return msg
        return None
    
    def is_processing(self) -> bool:
        """是否有消息正在处理中"""
        with self._lock:
            return self._find_active_message_id_locked() is not None
    
    def get_pending_message_id(self) -> Optional[str]:
        """获取当前等待回复的消息 ID"""
        with self._lock:
            self._pending_message_id = self._find_active_message_id_locked()
            return self._pending_message_id
    
    def clear(self) -> None:
        """清空会话"""
        with self._lock:
            self.messages.clear()
            self._pending_message_id = None
            self.hermes_session_id = None
            self.session_id = uuid4().hex[:8]
            if self._store is not None:
                self._store.create_session(self.session_id)
        logger.info("会话已清空，新 session_id=%s", self.session_id)

    def set_hermes_session_id(self, hermes_id: str) -> None:
        """记录 Hermes CLI 返回的 session ID，用于后续 --resume。"""
        with self._lock:
            self.hermes_session_id = hermes_id
            if self._store is not None:
                self._store.update_hermes_session_id(self.session_id, hermes_id)
        logger.info("Hermes session ID 已设置: %s", hermes_id)

    def set_session_title(self, title: str) -> None:
        """更新当前会话标题。"""
        title = (title or "").strip()
        if not title:
            return
        with self._lock:
            if self._store is not None:
                self._store.update_session_title(self.session_id, title)
        logger.info("会话标题已更新: %s", title)
    
    def to_dict(self) -> dict:
        """序列化为字典（供 API 返回）"""
        with self._lock:
            return {
                "session_id": self.session_id,
                "message_count": len(self.messages),
                "is_processing": self._find_active_message_id_locked() is not None,
                "messages": [
                    {
                        "id": m.message_id,
                        "role": m.role.value,
                        "content": m.content,
                        "status": m.status.value,
                        "task_id": m.task_id,
                        "error": m.error,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in self.messages
                ],
            }

    def _find_active_message_id_locked(self) -> Optional[str]:
        """查找仍在等待或执行中的用户消息。调用方需持有 _lock。"""
        for msg in self.messages:
            if (
                msg.role == MessageRole.USER
                and msg.status in (MessageStatus.PENDING, MessageStatus.PROCESSING)
            ):
                return msg.message_id
        return None


# 全局会话实例（单会话 MVP）
# 后续可扩展为多会话管理器
_global_session: Optional[ChatSession] = None


def get_chat_session() -> ChatSession:
    """获取全局聊天会话（单例），自动绑定持久化层"""
    global _global_session
    if _global_session is None:
        from apps.core.chat_store import get_chat_store
        store = get_chat_store()
        sessions = store.list_sessions(limit=1)
        if sessions:
            _global_session = ChatSession(session_id=sessions[0].session_id)
        else:
            _global_session = ChatSession()
        _global_session.attach_store(store)
        logger.info("初始化全局 ChatSession: %s", _global_session.session_id)
    return _global_session


def switch_chat_session(session_id: str) -> ChatSession:
    """切换到指定历史会话，返回新的 ChatSession 实例。

    会从数据库加载该会话的消息和 hermes_session_id。
    若 session_id 不存在则创建空会话。
    """
    global _global_session
    from apps.core.chat_store import get_chat_store
    _global_session = ChatSession(session_id=session_id)
    _global_session.attach_store(get_chat_store(), load_existing=True)
    logger.info("切换到会话: %s (messages=%d)", session_id, _global_session.message_count())
    return _global_session


def reset_chat_session() -> ChatSession:
    """重置全局会话（测试/清空用）"""
    global _global_session
    from apps.core.chat_store import get_chat_store
    _global_session = ChatSession()
    _global_session.attach_store(get_chat_store(), load_existing=False)
    logger.info("重置全局 ChatSession: %s", _global_session.session_id)
    return _global_session
