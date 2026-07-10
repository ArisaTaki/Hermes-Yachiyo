"""Tests for projecting public task terminal state into legacy Chat state."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from apps.core.chat_session import MessageStatus
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
