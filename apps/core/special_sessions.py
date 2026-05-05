"""Shared identifiers for built-in chat sessions."""

from __future__ import annotations

PROACTIVE_CHAT_SESSION_ID = "0120ace0"
PROACTIVE_CHAT_SESSION_TITLE = "主动关怀"


def is_proactive_chat_session(session_id: str | None) -> bool:
    return str(session_id or "") == PROACTIVE_CHAT_SESSION_ID
