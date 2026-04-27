"""Launcher notification state helpers.

Bubble / Live2D 只应在“新消息未读”时提醒，不应把历史回复或就绪状态
当作桌面提醒。该模块提供进程内的轻量 ack 状态，避免两个模式重复实现。
"""

from __future__ import annotations

from typing import Any

_NOTIFIABLE_STATUSES = {"completed", "failed"}


def latest_notifiable_message(chat: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest assistant result that can produce a user notification."""
    candidate = chat.get("latest_notifiable_message")
    if (
        isinstance(candidate, dict)
        and candidate.get("marker")
        and str(candidate.get("status") or "") in _NOTIFIABLE_STATUSES
        and str(candidate.get("content") or "").strip()
    ):
        return candidate

    for message in reversed(chat.get("messages", []) or []):
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        status = str(message.get("status") or "")
        if status not in _NOTIFIABLE_STATUSES:
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
            "content": content,
        }
    return None


class LauncherNotificationTracker:
    """Track unread launcher notifications for a single Bubble/Live2D window."""

    def __init__(self) -> None:
        self._initialized = False
        self._last_seen_marker = ""
        self._unread_marker = ""

    def update(self, chat: dict[str, Any], *, external_attention: bool = False) -> dict[str, Any]:
        latest = latest_notifiable_message(chat)
        marker = str((latest or {}).get("marker") or "")

        if not self._initialized:
            self._initialized = True
            self._last_seen_marker = marker
        elif marker and marker != self._last_seen_marker:
            self._unread_marker = marker

        has_chat_unread = bool(self._unread_marker)
        has_unread = has_chat_unread or bool(external_attention)
        source = ""
        if bool(external_attention):
            source = "proactive"
        elif has_chat_unread:
            source = "chat"

        return {
            "has_unread": has_unread,
            "source": source,
            "message_marker": marker,
            "unread_marker": self._unread_marker,
            "latest_message": latest or {},
        }

    def acknowledge(self, chat: dict[str, Any] | None = None) -> None:
        latest = latest_notifiable_message(chat or {}) if chat is not None else None
        marker = str((latest or {}).get("marker") or self._unread_marker or "")
        if marker:
            self._last_seen_marker = marker
        self._unread_marker = ""
        self._initialized = True
