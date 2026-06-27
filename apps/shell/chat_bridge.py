"""统一聊天摘要桥接层

为 Bubble / Live2D / Control Center 等非完整聊天 UI 提供轻量级会话摘要读取。
所有消息读写经由 ChatAPI → ChatSession → ChatStore，不引入独立状态。

职责：
  - get_recent_summary(): 最近 N 条消息摘要（含截断）
  - get_session_status(): 当前会话状态（空/处理中/就绪）
  - send_quick_message(): 快捷发送一条消息（委托 ChatAPI）

使用方：
  - Electron LauncherView（Bubble / Live2D）
  - MainWindowAPI（Control Center）
  - ChatView 以外的轻量摘要入口
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any, Dict

from apps.core.activity_store import get_activity_store
from apps.shell.chat_api import ChatAPI
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_allowed_tools,
    daily_desktop_entrypoint_requests,
    daily_desktop_planned_timeline,
    main_chat_entrypoint_allowed_tools,
)
from apps.shell.yachiyo_agent.planner_execution import planner_decision_and_tool_requests
from apps.shell.yachiyo_agent.planner_projection import (
    planner_selection_payload,
    planner_selection_timeline_event,
    planner_timeline_events,
    runtime_planner_metadata,
)
from apps.shell.yachiyo_agent.task_cards import agent_task_snapshot_from_payload
from packages.protocol.enums import TaskStatus
from packages.security import redact_api_error_text

if TYPE_CHECKING:
    from apps.core.runtime import AppRuntime

logger = logging.getLogger(__name__)

# 摘要消息最大内容长度
_SUMMARY_MAX_CONTENT_LEN = 80
_SESSION_SUMMARY_MAX_CONTENT_LEN = 132
_SESSION_SUMMARY_FRAGMENT_LEN = 58
_QUICK_DESKTOP_SNAPSHOT_ATTEMPTS = 4
_QUICK_DESKTOP_SNAPSHOT_DELAY_SECONDS = 0.05


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


def _message_field(message: Any, field: str) -> Any:
    """兼容 dict 与 StoredMessage/ChatMessage 对象读取字段。"""
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _clean_summary_text(text: str) -> str:
    """将 Markdown/日志式内容压缩成适合会话卡片展示的一行摘要。"""
    raw = str(text or "")
    lines: list[str] = []
    in_code_block = False

    for source_line in raw.replace("\r\n", "\n").split("\n"):
        line = source_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            continue
        line = re.sub(r"^\s*(?:#{1,6}|[-*+>]|\d+[.)])\s*", "", line)
        if re.fullmatch(r"[-*_=\s]{3,}", line):
            continue
        line = re.sub(r"[*_`~]+", "", line)
        lines.append(line)

    value = " ".join(lines) if lines else raw
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _latest_message(messages: list[Any]) -> Any | None:
    return messages[-1] if messages else None


def _latest_content_by_role(messages: list[Any], role: str) -> str:
    for message in reversed(messages):
        if _message_field(message, "role") == role:
            content = _clean_summary_text(str(_message_field(message, "content") or ""))
            if content:
                return content
    return ""


def _first_content_by_role(messages: list[Any], role: str) -> str:
    for message in messages:
        if _message_field(message, "role") == role:
            content = _clean_summary_text(str(_message_field(message, "content") or ""))
            if content:
                return content
    return ""


def _session_summary(messages: list[Any]) -> str:
    """生成会话列表摘要，避免只展示首条消息。"""
    if not messages:
        return "暂无消息"

    latest = _latest_message(messages)
    latest_status = str(_message_field(latest, "status") or "")
    first_user = _first_content_by_role(messages, "user")
    latest_user = _latest_content_by_role(messages, "user")
    latest_assistant = _latest_content_by_role(messages, "assistant")
    latest_system = _latest_content_by_role(messages, "system")

    if latest_status in {"pending", "processing"} and latest_user:
        return _truncate(f"处理中：{_truncate(latest_user, _SESSION_SUMMARY_FRAGMENT_LEN)}", _SESSION_SUMMARY_MAX_CONTENT_LEN)
    if latest_status == "failed":
        failed_content = latest_assistant or latest_user or latest_system or "任务失败"
        return _truncate(f"失败：{_truncate(failed_content, _SESSION_SUMMARY_FRAGMENT_LEN)}", _SESSION_SUMMARY_MAX_CONTENT_LEN)
    summary_user = latest_user or first_user
    if summary_user and latest_assistant:
        return _truncate(
            f"用户：{_truncate(summary_user, _SESSION_SUMMARY_FRAGMENT_LEN)}；回复：{_truncate(latest_assistant, _SESSION_SUMMARY_FRAGMENT_LEN)}",
            _SESSION_SUMMARY_MAX_CONTENT_LEN,
        )
    if latest_user:
        return _truncate(f"等待回复：{_truncate(latest_user, _SESSION_SUMMARY_FRAGMENT_LEN)}", _SESSION_SUMMARY_MAX_CONTENT_LEN)
    if latest_assistant:
        return _truncate(f"回复：{_truncate(latest_assistant, _SESSION_SUMMARY_FRAGMENT_LEN)}", _SESSION_SUMMARY_MAX_CONTENT_LEN)
    if latest_system:
        return _truncate(f"系统：{_truncate(latest_system, _SESSION_SUMMARY_FRAGMENT_LEN)}", _SESSION_SUMMARY_MAX_CONTENT_LEN)
    return "暂无可读内容"


def _session_activity(messages: list[Any], fallback: str = "") -> Dict[str, str]:
    latest = _latest_message(messages)
    if latest is None:
        return {"latest_role": "", "latest_status": "", "updated_at": fallback}
    return {
        "latest_role": str(_message_field(latest, "role") or ""),
        "latest_status": str(_message_field(latest, "status") or ""),
        "updated_at": str(_message_field(latest, "created_at") or fallback),
    }


def _latest_task_id(messages: list[Any]) -> str:
    for message in reversed(messages):
        task_id = str(_message_field(message, "task_id") or "").strip()
        if task_id:
            return task_id
    return ""


def _latest_activity_for_session(session_id: str) -> dict[str, Any]:
    try:
        events = get_activity_store().list_events(session_id=session_id, limit=1, key_only=True)
        return events[0].to_dict() if events else {}
    except Exception:
        logger.debug("读取最近活动失败: %s", session_id, exc_info=True)
        return {}


def _session_is_processing(runtime: "AppRuntime", session_id: str, messages: list[Any]) -> bool:
    for task in runtime.state.list_tasks():
        if getattr(task, "chat_session_id", None) != session_id:
            continue
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return True
    return False


def _session_updated_at(session_id: str, messages: list[Any], fallback: str = "") -> str:
    activity = _latest_activity_for_session(session_id)
    activity_time = str(activity.get("created_at") or "")
    latest_message_time = str(_message_field(_latest_message(messages), "created_at") or "")
    return max([value for value in (latest_message_time, activity_time, fallback) if value] or [""])


def _latest_agent_task_snapshot(
    runtime: "AppRuntime",
    sessions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for session in sessions:
        task_id = str(session.get("latest_task_id") or "").strip()
        if not task_id:
            continue
        snapshot = agent_task_snapshot_for_task(runtime, task_id)
        if snapshot is not None:
            return snapshot
    return None


def _runtime_agent_service(runtime: "AppRuntime") -> Any | None:
    service = getattr(runtime, "agent_runtime_service", None)
    if service is not None:
        return service
    getter = getattr(runtime, "get_agent_runtime_service", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


def _daily_desktop_candidates_for_quick_message(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    return daily_desktop_entrypoint_requests(
        text,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )


def _runtime_planner_candidates_for_quick_message(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests

        return planner_tool_requests(
            text,
            allowed_tools or daily_desktop_allowed_tools(),
            metadata=metadata,
        )
    except Exception:
        logger.debug("Launcher runtime planner quick-message candidates unavailable", exc_info=True)
    return []


def _desktop_candidates_for_quick_message(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return lightweight launcher candidates with Runtime Planner as the default.

    The legacy daily desktop parser remains a fallback for prompts the planner
    cannot project. Full task execution still records its planner/legacy
    selection event inside LegacyChatTaskStarter.
    """
    planner_candidates = _runtime_planner_candidates_for_quick_message(
        text,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )
    if planner_candidates:
        return planner_candidates
    return _daily_desktop_candidates_for_quick_message(
        text,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )


def agent_task_snapshot_for_task(
    runtime: "AppRuntime",
    task_id: str,
) -> dict[str, Any] | None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return None
    service = _runtime_agent_service(runtime)
    if service is None:
        return None

    try:
        from apps.shell.yachiyo_agent import YachiyoAgentService
        from apps.shell.yachiyo_agent.legacy_ports import LegacyRuntimePort

        facade = YachiyoAgentService(LegacyRuntimePort(service))
        return facade.get_task_snapshot(task_id).model_dump(mode="json")
    except Exception:
        logger.debug("Launcher agent task snapshot unavailable: %s", task_id, exc_info=True)
    return None


def planned_agent_task_snapshot_for_quick_message(
    *,
    text: str,
    task_id: str,
    session_id: str,
    candidates: list[dict[str, Any]] | None = None,
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return None
    candidates = (
        candidates
        if candidates is not None
        else _desktop_candidates_for_quick_message(text)
    )
    if not candidates:
        return None
    request = candidates[0]
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return None
    planner_timeline, planner_metadata = _planner_trace_for_quick_message(
        text,
        candidates,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    timeline = [
        *planner_timeline,
        *daily_desktop_planned_timeline(text, requests=candidates),
    ]
    if not timeline:
        return None
    task_metadata = {**dict(metadata or {}), **planner_metadata}
    snapshot = agent_task_snapshot_from_payload(
        {
            "task_id": task_id,
            "conversation_id": str(session_id or "").strip(),
            "title": text,
            "status": "queued",
            "current_step": "",
            "progress_text": "",
            "timeline": timeline,
            "metadata": task_metadata,
        }
    ).model_dump(mode="json")
    snapshot["open_in_studio_url"] = None
    return snapshot


def _planner_trace_for_quick_message(
    text: str,
    candidates: list[dict[str, Any]],
    *,
    allowed_tools: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not any(
        str(candidate.get("source") or "") == "runtime_planner"
        for candidate in candidates
    ):
        return [], {}
    try:
        decision, planned_requests = planner_decision_and_tool_requests(
            text,
            allowed_tools or daily_desktop_allowed_tools(),
            metadata=metadata,
        )
    except Exception:
        logger.debug("Launcher planner trace preview unavailable", exc_info=True)
        return [], {}
    if not planned_requests:
        return [], {}
    candidate_tools = [
        str(candidate.get("tool") or "").strip()
        for candidate in candidates
        if str(candidate.get("tool") or "").strip()
    ]
    planned_tools = [
        str(candidate.get("tool") or "").strip()
        for candidate in planned_requests
        if str(candidate.get("tool") or "").strip()
    ]
    if candidate_tools != planned_tools:
        return [], {}
    selection_payload = planner_selection_payload(
        decision=decision,
        planner_requests=planned_requests,
        legacy_requests=[],
        selected_requests=planned_requests,
        selected_source="runtime_planner",
        selected_reason="runtime_planner_direct",
    )
    return [
        *planner_timeline_events(decision),
        planner_selection_timeline_event(selection_payload),
    ], runtime_planner_metadata(decision)


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

    def __init__(self, runtime: "AppRuntime") -> None:
        self._runtime = runtime
        self._chat_api = ChatAPI(runtime)

    def _get_store(self) -> Any:
        store = getattr(self._runtime.chat_session, "_store", None)
        if store is not None:
            return store
        from apps.core.chat_store import get_chat_store

        return get_chat_store()

    def send_quick_message(
        self,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """快捷发送消息，委托 ChatAPI"""
        result = self._chat_api.send_message(text, metadata=metadata)
        if result.get("ok") is False:
            return result
        task_id = str(result.get("task_id") or "").strip()
        if not task_id:
            return result
        if isinstance(result.get("agent_task"), dict):
            return result
        planner_allowed_tools = main_chat_entrypoint_allowed_tools(
            _runtime_agent_service(self._runtime),
        )
        desktop_candidates = _desktop_candidates_for_quick_message(
            text,
            metadata=metadata,
            allowed_tools=planner_allowed_tools,
        )
        if desktop_candidates:
            executed_task = self._execute_yachiyo_desktop_quick_task(
                task_id,
                text,
                metadata=metadata,
            )
            if executed_task is not None:
                return {**result, "agent_task": executed_task}
        agent_task = self._agent_task_snapshot_for_quick_message(
            task_id,
            has_desktop_intent=bool(desktop_candidates),
        )
        if agent_task is None:
            planned_task = planned_agent_task_snapshot_for_quick_message(
                text=text,
                task_id=task_id,
                session_id=str(getattr(self._runtime.chat_session, "session_id", "") or ""),
                candidates=desktop_candidates,
                allowed_tools=planner_allowed_tools,
                metadata=metadata,
            )
            if planned_task is None:
                return result
            return {**result, "agent_task": planned_task}
        return {**result, "agent_task": agent_task}

    def _execute_yachiyo_desktop_quick_task(
        self,
        task_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        service = _runtime_agent_service(self._runtime)
        if service is None:
            return None
        try:
            from apps.shell.yachiyo_agent.legacy_ports import LegacyChatTaskStarter

            starter = LegacyChatTaskStarter(self._runtime, service)
            payload = starter.execute_existing_main_chat_task(
                task_id=task_id,
                conversation_id=str(getattr(self._runtime.chat_session, "session_id", "") or ""),
                prompt=text,
                metadata=metadata,
            )
            if payload is not None:
                return agent_task_snapshot_from_payload(payload).model_dump(mode="json")
        except Exception:
            logger.debug("Launcher daily desktop quick task execution failed: %s", task_id, exc_info=True)
            snapshot = agent_task_snapshot_for_task(self._runtime, task_id)
            if snapshot is not None:
                return snapshot
        return None

    def _agent_task_snapshot_for_quick_message(
        self,
        task_id: str,
        *,
        has_desktop_intent: bool,
    ) -> dict[str, Any] | None:
        attempts = _QUICK_DESKTOP_SNAPSHOT_ATTEMPTS if has_desktop_intent else 1
        for attempt in range(max(1, attempts)):
            snapshot = agent_task_snapshot_for_task(self._runtime, task_id)
            if snapshot is not None:
                return snapshot
            if not has_desktop_intent or attempt >= attempts - 1:
                break
            time.sleep(max(0.0, _QUICK_DESKTOP_SNAPSHOT_DELAY_SECONDS))
        return None

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
            return {
                "ok": False,
                "error": redact_api_error_text(exc),
                "messages": [],
                "empty": True,
                "status_label": "错误",
            }

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
                "error": redact_api_error_text(exc),
                "session_id": "",
                "message_count": 0,
                "is_processing": False,
                "status_label": "错误",
            }

    def get_recent_sessions(self, limit: int = 4) -> Dict[str, Any]:
        """获取最近会话列表，供 Window/Bubble/Live2D 概览使用。"""
        try:
            store = self._get_store()
            current_session_id = self._runtime.chat_session.session_id
            normalized_limit = max(1, _normalize_count(limit) or 1)
            sessions = store.list_sessions(limit=normalized_limit)
            items = []
            for item in sessions:
                messages = store.load_messages(item.session_id, limit=240)
                latest_activity = _latest_activity_for_session(item.session_id)
                updated_at = _session_updated_at(item.session_id, messages, item.created_at)
                items.append(
                    {
                        "session_id": item.session_id,
                        "title": item.title or "新对话",
                        "created_at": item.created_at,
                        "updated_at": updated_at,
                        "message_count": item.message_count,
                        "is_current": item.session_id == current_session_id,
                        "is_processing": _session_is_processing(self._runtime, item.session_id, messages),
                        "latest_activity": latest_activity,
                        "latest_task_id": _latest_task_id(messages),
                        "summary": _session_summary(messages),
                        **_session_activity(messages, updated_at),
                    }
                )
            if not any(item["session_id"] == current_session_id for item in items):
                stored_current = store.get_session(current_session_id)
                current_messages = store.load_messages(current_session_id, limit=240)
                created_at = stored_current.created_at if stored_current else ""
                latest_activity = _latest_activity_for_session(current_session_id)
                updated_at = _session_updated_at(current_session_id, current_messages, created_at)
                items.insert(
                    0,
                    {
                        "session_id": current_session_id,
                        "title": (stored_current.title if stored_current else "") or "当前会话",
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "message_count": stored_current.message_count if stored_current else len(current_messages),
                        "is_current": True,
                        "is_processing": _session_is_processing(self._runtime, current_session_id, current_messages),
                        "latest_activity": latest_activity,
                        "latest_task_id": _latest_task_id(current_messages),
                        "summary": _session_summary(current_messages),
                        **_session_activity(current_messages, updated_at),
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
                "error": redact_api_error_text(exc),
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
            "agent_task": _latest_agent_task_snapshot(self._runtime, sessions.get("sessions", [])),
            "recent_sessions": sessions.get("sessions", []),
        }
