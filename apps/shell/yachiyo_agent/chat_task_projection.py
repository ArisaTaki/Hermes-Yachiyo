"""Project terminal Yachiyo task state into the legacy Chat product surface."""

from __future__ import annotations

from typing import Any


class ChatTaskLifecycleProjector:
    """Keep legacy app task and Chat message state aligned with public tasks."""

    def __init__(self, app_runtime: Any) -> None:
        self._app_runtime = app_runtime

    def project_terminal_task(self, task_id: str, task_snapshot: Any) -> None:
        status = str(getattr(task_snapshot, "status", "") or "").strip()
        if status not in {"completed", "failed", "cancelled"}:
            return

        summary = str(getattr(task_snapshot, "summary", "") or "").strip()
        if not summary:
            summary = {
                "completed": "任务已完成",
                "cancelled": "任务已取消",
            }.get(status, "任务未完成")
        self._project_app_task(task_id, status, summary)
        self._project_chat_message(task_id, task_snapshot, status, summary)

    def _project_app_task(self, task_id: str, status: str, summary: str) -> None:
        state = getattr(self._app_runtime, "state", None)
        update_task_status = getattr(state, "update_task_status", None)
        if not callable(update_task_status):
            return
        try:
            from packages.protocol.enums import TaskStatus

            if status == "completed":
                update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result=summary,
                    progress_label="已完成",
                )
            elif status == "cancelled":
                update_task_status(
                    task_id,
                    TaskStatus.CANCELLED,
                    error=summary,
                    progress_label="已取消",
                )
            else:
                update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error=summary,
                    progress_label="执行失败",
                )
        except Exception:
            return

    def _project_chat_message(
        self,
        task_id: str,
        task_snapshot: Any,
        status: str,
        summary: str,
    ) -> None:
        session = self._chat_session_for_task(task_snapshot)
        upsert = getattr(session, "upsert_assistant_message", None)
        if session is None or not callable(upsert):
            return
        try:
            from apps.core.chat_session import MessageStatus

            assistant = session.get_assistant_message_for_task(task_id)
            metadata = dict(getattr(assistant, "metadata", {}) or {}) if assistant else {}
            metadata["pending_approval"] = {}
            metadata["run_status"] = status
            metadata.pop("run_progress_title", None)
            metadata.pop("run_progress_detail", None)
            message_status = (
                MessageStatus.COMPLETED if status == "completed" else MessageStatus.FAILED
            )
            upsert(
                task_id=task_id,
                content=summary,
                status=message_status,
                error=None if status == "completed" else summary,
                metadata=metadata,
            )
        except Exception:
            return

    def _chat_session_for_task(self, task_snapshot: Any) -> Any:
        conversation_id = str(
            getattr(task_snapshot, "conversation_id", "") or ""
        ).strip()
        current = getattr(self._app_runtime, "chat_session", None)
        if not conversation_id:
            return current
        try:
            from apps.core.chat_session import load_existing_chat_session
            from apps.core.chat_store import get_chat_store

            store = getattr(self._app_runtime, "store", None) or get_chat_store()
            return load_existing_chat_session(
                store,
                conversation_id,
                current=current,
                fail_active_messages=False,
            )
        except Exception:
            return None
