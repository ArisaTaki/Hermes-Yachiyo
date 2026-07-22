"""Tests for projecting public task terminal state into legacy Chat state."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from apps.core.chat_session import ChatSession, MessageStatus
from apps.core.chat_store import ChatStore
from apps.shell.yachiyo_agent import ChatTaskLifecycleProjector
from packages.protocol.enums import TaskStatus


class _RecordingState:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        **kwargs: Any,
    ) -> None:
        self.calls.append({"task_id": task_id, "status": status, **kwargs})


class _RecordingSession:
    session_id = "chat-1"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.assistant = SimpleNamespace(
            metadata={
                "pending_approval": {"approval_id": "approval-1"},
                "run_progress_title": "Running",
                "run_progress_detail": "Step 1",
                "preserved": True,
            }
        )

    def get_assistant_message_for_task(self, _task_id: str) -> Any:
        return self.assistant

    def upsert_assistant_message(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_chat_task_lifecycle_projector_projects_cancelled_task() -> None:
    state = _RecordingState()
    session = _RecordingSession()
    projector = ChatTaskLifecycleProjector(
        SimpleNamespace(state=state, chat_session=session)
    )

    projector.project_terminal_task(
        "task-1",
        SimpleNamespace(status="cancelled", summary="", conversation_id="chat-1"),
    )

    assert state.calls == [
        {
            "task_id": "task-1",
            "status": TaskStatus.CANCELLED,
            "error": "任务已取消",
            "progress_label": "已取消",
        }
    ]
    assert session.calls == [
        {
            "task_id": "task-1",
            "content": "任务已取消",
            "status": MessageStatus.FAILED,
            "error": "任务已取消",
            "metadata": {
                "pending_approval": {},
                "run_status": "cancelled",
                "preserved": True,
            },
        }
    ]


def test_chat_task_lifecycle_projector_ignores_non_terminal_task() -> None:
    state = _RecordingState()
    session = _RecordingSession()
    projector = ChatTaskLifecycleProjector(
        SimpleNamespace(state=state, chat_session=session)
    )

    projector.project_terminal_task(
        "task-1",
        SimpleNamespace(status="running", summary="Working", conversation_id="chat-1"),
    )

    assert state.calls == []
    assert session.calls == []


def test_chat_task_lifecycle_projector_does_not_fall_back_or_recreate_deleted_target(
    tmp_path,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    current = ChatSession(session_id="current-chat")
    current.attach_store(store, load_existing=False)
    target = ChatSession(session_id="deleted-chat")
    target.attach_store(store, load_existing=False)
    store.delete_session(target.session_id)
    state = _RecordingState()
    projector = ChatTaskLifecycleProjector(
        SimpleNamespace(state=state, chat_session=current, store=store)
    )

    try:
        projector.project_terminal_task(
            "task-deleted-chat",
            SimpleNamespace(
                status="completed",
                summary="late result",
                conversation_id=target.session_id,
            ),
        )

        assert state.calls != []
        assert store.get_session(target.session_id) is None
        assert store.load_messages(target.session_id, limit=0) == []
        assert store.load_messages(current.session_id, limit=0) == []
    finally:
        store.close()


def test_chat_task_routes_do_not_own_lifecycle_projection() -> None:
    source = (
        Path(__file__).parents[1]
        / "apps"
        / "bridge"
        / "routes"
        / "yachiyo_chat_handlers.py"
    ).read_text(encoding="utf-8")

    assert "app_runtime_from_request" not in source
    assert "_sync_terminal_task_snapshot_to_chat" not in source
    assert "update_task_status" not in source
