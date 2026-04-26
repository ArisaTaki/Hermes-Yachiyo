"""统一聊天摘要桥接层

为 Bubble / Live2D / Control Center 等非完整聊天 UI 提供轻量级会话摘要读取。
所有消息读写经由 ChatAPI → ChatSession → ChatStore，不引入独立状态。

职责：
  - get_recent_summary(): 最近 N 条消息摘要（含截断）
  - get_session_status(): 当前会话状态（空/处理中/就绪）
  - send_quick_message(): 快捷发送一条消息（委托 ChatAPI）

使用方：
  - BubbleWindowAPI
  - Live2DWindowAPI
  - MainWindowAPI（Control Center）

不使用方（直接用 ChatAPI）：
  - ChatWindowAPI（完整聊天窗口）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.shell.chat_api import ChatAPI

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)

# 摘要消息最大内容长度
_SUMMARY_MAX_CONTENT_LEN = 80


def _truncate(text: str, max_len: int = _SUMMARY_MAX_CONTENT_LEN) -> str:
    """截断文本，超长时追加省略号"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _normalize_count(count: int) -> int:
    """将外部传入的摘要条数规整为非负整数。"""
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


def _latest_notifiable_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """返回最近一条可触发桌面新消息提醒的 assistant 结果。"""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        status = str(message.get("status") or "")
        if not content or status not in {"completed", "failed"}:
            continue
        marker = str(
            message.get("id")
            or message.get("message_id")
            or message.get("task_id")
            or f"{status}:{content[:96]}"
        )
        return {
            "marker": marker,
            "id": str(message.get("id") or message.get("message_id") or ""),
            "task_id": str(message.get("task_id") or ""),
            "status": status,
            "content": _truncate(content),
        }
    return {}


def _latest_assistant_reply_content(messages: list[dict[str, Any]]) -> str:
    """返回最近一条 assistant 回复的完整内容，不做摘要截断。"""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


class ChatBridge:
    """轻量级聊天摘要桥接，供 bubble/live2d 使用。

    内部持有 ChatAPI 实例，避免各模式各写一份消息读取逻辑。
    """

    def __init__(self, runtime: "HermesRuntime") -> None:
        self._runtime = runtime
        self._chat_api = ChatAPI(runtime)

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        """快捷发送消息，委托 ChatAPI"""
        return self._chat_api.send_message(text)

    def get_recent_summary(self, count: int = 3) -> Dict[str, Any]:
        """获取最近 N 条消息的摘要。

        返回格式：
            {
                "ok": True,
                "session_id": str,
                "is_processing": bool,
                "messages": [
                    {"role": "user"|"assistant"|"system",
                     "content": str (截断),
                     "status": str,
                     "task_id": str|None}
                ],
                "empty": bool,
                "status_label": str,  # 空 / 处理中 / 就绪
            }
        """
        try:
            count = _normalize_count(count)
            result = self._chat_api.get_messages(limit=50)
            if not result.get("ok"):
                return result

            all_msgs = result["messages"]
            recent = all_msgs[-count:] if count and all_msgs else []
            latest_notifiable = _latest_notifiable_assistant_message(all_msgs)
            latest_reply_full = _latest_assistant_reply_content(all_msgs)

            is_processing = result.get("is_processing", False)
            empty = len(all_msgs) == 0

            if empty:
                status_label = "暂无对话"
            elif is_processing:
                status_label = "处理中…"
            else:
                status_label = "就绪"

            return {
                "ok": True,
                "session_id": result["session_id"],
                "is_processing": is_processing,
                "empty": empty,
                "status_label": status_label,
                "latest_notifiable_message": latest_notifiable,
                "latest_reply_full": latest_reply_full,
                "messages": [
                    {
                        "id": m.get("id", ""),
                        "role": m["role"],
                        "content": _truncate(m["content"]),
                        "status": m["status"],
                        "task_id": m.get("task_id"),
                        "created_at": m.get("created_at", ""),
                    }
                    for m in recent
                ],
            }
        except Exception as exc:
            logger.error("获取消息摘要失败: %s", exc)
            return {"ok": False, "error": str(exc), "messages": [], "empty": True, "status_label": "错误"}

    def get_session_status(self) -> Dict[str, Any]:
        """获取当前会话状态（不含消息内容）"""
        try:
            info = self._chat_api.get_session_info()
            count = info.get("message_count", 0)
            processing = info.get("is_processing", False)

            if count == 0:
                label = "暂无对话"
            elif processing:
                label = "处理中…"
            else:
                label = "就绪"

            return {
                "ok": True,
                "session_id": info["session_id"],
                "message_count": count,
                "is_processing": processing,
                "status_label": label,
            }
        except Exception as exc:
            logger.error("获取会话状态失败: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "session_id": "",
                "message_count": 0,
                "is_processing": False,
                "status_label": "错误",
            }

    def get_recent_sessions(self, limit: int = 4) -> Dict[str, Any]:
        """获取最近会话列表，供 Window/Bubble/Live2D 概览使用。"""
        try:
            from apps.core.chat_store import get_chat_store

            store = get_chat_store()
            current_session_id = self._runtime.chat_session.session_id
            sessions = store.list_sessions(limit=max(1, int(limit)))
            items = [
                {
                    "session_id": item.session_id,
                    "title": item.title or "新对话",
                    "created_at": item.created_at,
                    "message_count": item.message_count,
                    "is_current": item.session_id == current_session_id,
                }
                for item in sessions
            ]
            if not any(item["session_id"] == current_session_id for item in items):
                stored_current = store.get_session(current_session_id)
                items.insert(
                    0,
                    {
                        "session_id": current_session_id,
                        "title": (stored_current.title if stored_current else "") or "当前会话",
                        "created_at": stored_current.created_at if stored_current else "",
                        "message_count": stored_current.message_count if stored_current else 0,
                        "is_current": True,
                    },
                )
            return {
                "ok": True,
                "current_session_id": current_session_id,
                "sessions": items,
            }
        except Exception as exc:
            logger.error("获取最近会话失败: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "current_session_id": "",
                "sessions": [],
            }

    def get_conversation_overview(
        self,
        summary_count: int = 3,
        session_limit: int = 4,
    ) -> Dict[str, Any]:
        """获取供模式壳展示的统一会话概览。"""
        summary = self.get_recent_summary(summary_count)
        sessions = self.get_recent_sessions(session_limit)
        latest_reply = ""
        latest_reply_full = str(summary.get("latest_reply_full") or "")
        if summary.get("ok"):
            for message in reversed(summary.get("messages", [])):
                if message["role"] == "assistant":
                    latest_reply = message["content"]
                    break

        return {
            "ok": bool(summary.get("ok")) and bool(sessions.get("ok")),
            "session_id": summary.get("session_id", ""),
            "is_processing": summary.get("is_processing", False),
            "empty": summary.get("empty", True),
            "status_label": summary.get("status_label", "错误"),
            "messages": summary.get("messages", []),
            "latest_notifiable_message": summary.get("latest_notifiable_message", {}),
            "latest_reply": latest_reply,
            "latest_reply_full": latest_reply_full,
            "recent_sessions": sessions.get("sessions", []),
        }
