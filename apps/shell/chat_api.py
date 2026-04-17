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
from typing import TYPE_CHECKING, Any, Dict, List

from apps.core.chat_session import (
    ChatMessage,
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

        消息排序：保证每条 user 消息紧跟其关联的 assistant 回复，
        避免并发任务完成顺序不一致导致消息错位。

        Returns:
            {"ok": True, "session_id": str, "messages": [...], "is_processing": bool}
        """
        try:
            # 同步任务状态到消息
            self._sync_task_status_to_messages()

            messages = self._session.get_messages(limit)
            sorted_msgs = self._sort_messages_by_task(messages)
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
                    for m in sorted_msgs
                ],
            }

        except Exception as exc:
            logger.error("获取消息列表失败: %s", exc)
            return {"ok": False, "error": str(exc), "messages": []}

    @staticmethod
    def _sort_messages_by_task(messages: List[ChatMessage]) -> List[ChatMessage]:
        """按 task 关联重排消息，保证 user 消息紧跟其 assistant 回复。

        算法：遍历消息列表，将 assistant 消息按 task_id 索引。
        输出时，每条 user 消息后立即插入对应 assistant 消息。
        system 消息和无 task_id 的消息保持原始顺序。
        """
        # 建立 task_id → assistant 消息的映射
        assistant_by_task: dict[str, ChatMessage] = {}
        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id:
                assistant_by_task[msg.task_id] = msg

        result: list[ChatMessage] = []

        for msg in messages:
            if msg.role == MessageRole.ASSISTANT and msg.task_id:
                # assistant 消息由 user 消息触发插入，跳过
                continue
            result.append(msg)
            # user 消息后紧跟其关联的 assistant 回复
            if msg.role == MessageRole.USER and msg.task_id:
                assistant = assistant_by_task.get(msg.task_id)
                if assistant is not None:
                    result.append(assistant)

        # 兜底：无 task_id 的 assistant 消息追加末尾
        for msg in messages:
            if (
                msg.role == MessageRole.ASSISTANT
                and not msg.task_id
            ):
                result.append(msg)

        return result

    def _sync_task_status_to_messages(self) -> None:
        """将任务状态同步到关联的消息

        使用 upsert_assistant_message() 保证幂等：
          - RUNNING: 创建/更新 assistant 占位消息（PROCESSING）
          - COMPLETED: 更新 assistant 消息为最终结果
          - FAILED: 更新 assistant 消息为错误信息
          - CANCELLED: 更新 assistant 消息为取消提示

        同一个 task_id 永远只对应一条 assistant 消息，
        无论此方法被并发调用多少次都不会产生重复。
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
                result = task.result or "[任务已完成，无输出]"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=result,
                    status=MessageStatus.COMPLETED,
                )

            elif task.status == TaskStatus.FAILED:
                error = task.error or "任务执行失败"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=f"❌ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

            elif task.status == TaskStatus.CANCELLED:
                error = "任务已取消"
                self._session.upsert_assistant_message(
                    task_id=msg.task_id,
                    content=f"⚠️ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

            elif task.status == TaskStatus.RUNNING:
                assistant = self._session.get_assistant_message_for_task(msg.task_id)
                if assistant is None:
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content="",
                        status=MessageStatus.PROCESSING,
                    )
                elif assistant.status != MessageStatus.PROCESSING:
                    self._session.upsert_assistant_message(
                        task_id=msg.task_id,
                        content=assistant.content,
                        status=MessageStatus.PROCESSING,
                        error=assistant.error,
                    )

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
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks()
            self._session.clear()
            logger.info("会话已清空，已取消旧会话任务数=%d", cancelled_count)
            return {
                "ok": True,
                "session_id": self._session.session_id,
                "cancelled_tasks": cancelled_count,
            }
        except Exception as exc:
            logger.error("清空会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def delete_current_session(self) -> Dict[str, Any]:
        """删除当前会话，并切换到剩余最近会话或新建空会话。"""
        try:
            self._sync_task_status_to_messages()
            cancelled_count = self._cancel_active_session_tasks()
            deleted_session_id = self._session.session_id

            from apps.core.chat_store import get_chat_store

            store = get_chat_store()
            store.delete_session(deleted_session_id)
            remaining = store.list_sessions(limit=1)

            if remaining:
                next_session_id = remaining[0].session_id
                switch_session = getattr(self._runtime, "switch_session", None)
                if not callable(switch_session):
                    raise RuntimeError("runtime 不支持切换会话")
                switch_session(next_session_id)
            else:
                self._session.clear()
                next_session_id = self._session.session_id

            logger.info(
                "当前会话已删除: %s -> %s，已取消任务数=%d",
                deleted_session_id,
                next_session_id,
                cancelled_count,
            )
            return {
                "ok": True,
                "deleted_session_id": deleted_session_id,
                "session_id": next_session_id,
                "cancelled_tasks": cancelled_count,
                "remaining_sessions": len(remaining),
            }
        except Exception as exc:
            logger.error("删除当前会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _cancel_active_session_tasks(self) -> int:
        """取消当前会话中仍在等待/执行的任务，并持久化取消提示。"""
        active_task_ids: list[str] = []
        seen: set[str] = set()

        for msg in self._session.get_all_messages():
            if msg.role != MessageRole.USER:
                continue
            if msg.status not in (MessageStatus.PENDING, MessageStatus.PROCESSING):
                continue
            if not msg.task_id or msg.task_id in seen:
                continue
            seen.add(msg.task_id)
            active_task_ids.append(msg.task_id)

        cancelled = 0
        for task_id in active_task_ids:
            task = self._state.get_task(task_id)
            if task is None:
                continue
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                try:
                    self._state.cancel_task(task_id)
                    cancel_runner_task = getattr(
                        self._runtime, "cancel_task_runner_task", None
                    )
                    if callable(cancel_runner_task):
                        cancel_runner_task(task_id)
                    cancelled += 1
                except (KeyError, ValueError):
                    logger.debug("任务取消跳过: %s", task_id, exc_info=True)

            task = self._state.get_task(task_id)
            if task is not None and task.status == TaskStatus.CANCELLED:
                error = "任务已取消"
                self._session.upsert_assistant_message(
                    task_id=task_id,
                    content=f"⚠️ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )

        return cancelled
