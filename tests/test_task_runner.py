import asyncio

import pytest

import apps.core.activity_store as activity_store_mod
import apps.core.chat_store as chat_store_mod
from apps.core.activity_store import ActivityStore
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.core.task_runner import TaskRunner
from packages.protocol.enums import TaskStatus, TaskType


class _InstantExecutor:
    @property
    def name(self) -> str:
        return "InstantExecutor"

    async def run(self, task):
        return f"done:{task.description}"


@pytest.mark.asyncio
async def test_stop_awaits_in_progress_task_cancellation():
    runner = TaskRunner(AppState())
    child = asyncio.create_task(asyncio.sleep(60))
    runner._in_progress["task1"] = child

    await runner.stop()

    assert child.done()
    assert runner._in_progress == {}


@pytest.mark.asyncio
async def test_task_runner_writes_final_reply_to_original_background_session(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    state = AppState()
    task = state.create_task(
        task_type=TaskType.GENERAL,
        description="后台任务",
        chat_session_id="background-session",
    )
    runner = TaskRunner(state, executor=_InstantExecutor())  # type: ignore[arg-type]
    try:
        await runner._execute_with_state(task.task_id)

        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        messages = store.load_messages("background-session", limit=10)
        assistant = next(message for message in messages if message.role == "assistant")
        assert assistant.task_id == task.task_id
        assert assistant.status == "completed"
        assert assistant.content == "done:后台任务"
        activity_titles = [event.title for event in activity_store.latest_for_task(task.task_id, limit=5)]
        assert "Yachiyo 回复完成" in activity_titles
    finally:
        activity_store.close()
        store.close()
