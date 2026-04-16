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

会话不持久化到数据库（当前阶段），进程重启后清空。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

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
    
    线程安全性：当前假设单线程访问（pywebview 主线程 + asyncio）。
    如果需要多线程，后续可加锁。
    """
    session_id: str = field(default_factory=lambda: uuid4().hex[:8])
    messages: List[ChatMessage] = field(default_factory=list)
    _pending_message_id: Optional[str] = field(default=None, repr=False)
    
    def add_user_message(self, content: str) -> str:
        """添加用户消息，返回 message_id"""
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
        logger.info("用户消息已添加: %s (len=%d)", msg_id, len(content))
        return msg_id
    
    def link_message_to_task(self, message_id: str, task_id: str) -> bool:
        """将消息与任务关联"""
        for msg in self.messages:
            if msg.message_id == message_id:
                msg.task_id = task_id
                msg.status = MessageStatus.PROCESSING
                logger.debug("消息 %s 关联任务 %s", message_id, task_id)
                return True
        return False
    
    def add_assistant_message(
        self,
        content: str,
        task_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> str:
        """添加 assistant 回复消息"""
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
                    break
        
        self._pending_message_id = None
        logger.info("Assistant 回复已添加: %s (task=%s)", msg_id, task_id)
        return msg_id
    
    def add_system_message(self, content: str) -> str:
        """添加系统消息（提示、状态更新等）"""
        msg_id = uuid4().hex[:12]
        msg = ChatMessage(
            message_id=msg_id,
            role=MessageRole.SYSTEM,
            content=content,
            status=MessageStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
        )
        self.messages.append(msg)
        return msg_id
    
    def mark_message_failed(self, message_id: str, error: str) -> bool:
        """标记消息处理失败"""
        for msg in self.messages:
            if msg.message_id == message_id:
                msg.status = MessageStatus.FAILED
                msg.error = error
                self._pending_message_id = None
                return True
        return False
    
    def get_messages(self, limit: int = 50) -> List[ChatMessage]:
        """获取最近 N 条消息"""
        return self.messages[-limit:]
    
    def get_last_assistant_message(self) -> Optional[ChatMessage]:
        """获取最新一条 assistant 消息"""
        for msg in reversed(self.messages):
            if msg.role == MessageRole.ASSISTANT:
                return msg
        return None
    
    def is_processing(self) -> bool:
        """是否有消息正在处理中"""
        return self._pending_message_id is not None
    
    def get_pending_message_id(self) -> Optional[str]:
        """获取当前等待回复的消息 ID"""
        return self._pending_message_id
    
    def clear(self) -> None:
        """清空会话"""
        self.messages.clear()
        self._pending_message_id = None
        self.session_id = uuid4().hex[:8]
        logger.info("会话已清空，新 session_id=%s", self.session_id)
    
    def to_dict(self) -> dict:
        """序列化为字典（供 API 返回）"""
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "is_processing": self.is_processing(),
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


# 全局会话实例（单会话 MVP）
# 后续可扩展为多会话管理器
_global_session: Optional[ChatSession] = None


def get_chat_session() -> ChatSession:
    """获取全局聊天会话（单例）"""
    global _global_session
    if _global_session is None:
        _global_session = ChatSession()
        logger.info("初始化全局 ChatSession: %s", _global_session.session_id)
    return _global_session


def reset_chat_session() -> ChatSession:
    """重置全局会话（测试/清空用）"""
    global _global_session
    _global_session = ChatSession()
    logger.info("重置全局 ChatSession: %s", _global_session.session_id)
    return _global_session
