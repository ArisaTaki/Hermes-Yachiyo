"""聊天 WebView API

为主窗口（及后续 bubble/live2d）提供统一的聊天消息接口。
通过 ChatSession 管理消息状态，通过 AppState 创建任务。

职责：
  - send_message(): 发送用户消息并创建任务
  - get_messages(): 获取消息列表（含任务状态同步）
  - get_session_info(): 获取会话元信息
  - clear_session(): 清空会话
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.core.chat_session import (
    ChatSession,
    MessageRole,
    MessageStatus,
)
from packages.protocol.enums import TaskStatus, TaskType

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)


class ChatAPI:
    """聊天 API（供 WebView JavaScript 调用）"""

    def __init__(self, runtime: "HermesRuntime") -> None:
        self._runtime = runtime

    @property
    def _session(self) -> ChatSession:
        return self._runtime.chat_session

    @property
    def _state(self):
        return self._runtime.state

    def send_message(self, text: str) -> Dict[str, Any]:
        """发送用户消息并创建对应任务

        流程：
          1. 添加用户消息到 ChatSession
          2. 创建任务到 AppState（触发 TaskRunner 执行）
          3. 关联消息与任务
          4. 返回 message_id 和 task_id

        Args:
            text: 用户消息内容

        Returns:
            {"ok": True, "message_id": str, "task_id": str, "status": "pending"}
            或 {"ok": False, "error": str}
        """
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "消息内容不能为空"}

        try:
            # 1. 添加用户消息
            message_id = self._session.add_user_message(text)

            # 2. 创建任务
            task = self._state.create_task(
                task_type=TaskType.GENERAL,
                description=text,
            )
            task_id = task.task_id

            # 3. 关联消息与任务
            self._session.link_message_to_task(message_id, task_id)

            logger.info(
                "消息已发送: message_id=%s, task_id=%s, len=%d",
                message_id,
                task_id,
                len(text),
            )

            return {
                "ok": True,
                "message_id": message_id,
                "task_id": task_id,
                "status": "pending",
            }

        except Exception as exc:
            logger.error("发送消息失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_messages(self, limit: int = 50) -> Dict[str, Any]:
        """获取消息列表，同时同步任务状态到消息

        此方法会检查每条 user 消息关联的任务状态：
          - 任务 COMPLETED → 若无对应 assistant 回复，自动添加
          - 任务 FAILED → 标记消息失败
          - 任务 RUNNING → 更新消息状态为 processing

        Returns:
            {"ok": True, "session_id": str, "messages": [...], "is_processing": bool}
        """
        try:
            # 同步任务状态到消息
            self._sync_task_status_to_messages()

            messages = self._session.get_messages(limit)
            return {
                "ok": True,
                "session_id": self._session.session_id,
                "is_processing": self._session.is_processing(),
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
                    for m in messages
                ],
            }

        except Exception as exc:
            logger.error("获取消息列表失败: %s", exc)
            return {"ok": False, "error": str(exc), "messages": []}

    def _sync_task_status_to_messages(self) -> None:
        """将任务状态同步到关联的消息

        遍历所有 user 消息，检查其关联任务的状态：
          - COMPLETED: 添加 assistant 回复（如果尚未添加）
          - FAILED: 标记消息失败
          - RUNNING: 更新消息状态为 processing
        """
        for msg in self._session.get_all_messages():
            if msg.role != MessageRole.USER:
                continue
            if msg.task_id is None:
                continue
            if msg.status in (MessageStatus.COMPLETED, MessageStatus.FAILED):
                continue

            task = self._state.get_task(msg.task_id)
            if task is None:
                continue

            if task.status == TaskStatus.COMPLETED:
                # 检查是否已有对应的 assistant 回复
                if not self._session.has_assistant_reply(msg.task_id):
                    result = task.result or "[任务已完成，无输出]"
                    self._session.add_assistant_message(result, task_id=msg.task_id)
                    logger.debug("自动添加 assistant 回复: task=%s", msg.task_id)

            elif task.status == TaskStatus.FAILED:
                error = task.error or "任务执行失败"
                self._session.mark_message_failed(msg.message_id, error)
                # 同时添加一条 assistant 错误消息
                if not self._session.has_assistant_reply(msg.task_id):
                    self._session.add_assistant_message(
                        f"❌ {error}",
                        task_id=msg.task_id,
                        error=error,
                    )

            elif task.status == TaskStatus.RUNNING:
                if msg.status != MessageStatus.PROCESSING:
                    self._session.mark_message_processing(msg.message_id)

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话元信息"""
        return {
            "session_id": self._session.session_id,
            "message_count": self._session.message_count(),
            "is_processing": self._session.is_processing(),
            "pending_message_id": self._session.get_pending_message_id(),
        }

    def clear_session(self) -> Dict[str, Any]:
        """清空会话"""
        try:
            self._session.clear()
            logger.info("会话已清空")
            return {"ok": True, "session_id": self._session.session_id}
        except Exception as exc:
            logger.error("清空会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}
