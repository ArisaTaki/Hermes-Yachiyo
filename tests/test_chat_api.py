"""ChatAPI 测试 — 消息发送与任务状态同步"""

import base64
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from apps.core.chat_session import ChatMessage, ChatSession, MessageRole, MessageStatus
from apps.core.chat_store import ChatStore
import apps.core.chat_store as _store_mod
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
import apps.shell.chat_api as chat_api_mod
from apps.shell.chat_api import ChatAPI
from packages.protocol.enums import TaskStatus


class _RuntimeStub:
    def __init__(self, store: ChatStore) -> None:
        self.store = store
        self.state = AppState()
        self.chat_session = ChatSession(session_id="s1")
        self.chat_session.attach_store(store, load_existing=False)
        self.cancelled_runner_tasks: list[str] = []

    def cancel_task_runner_task(self, task_id: str) -> bool:
        self.cancelled_runner_tasks.append(task_id)
        return True

    def switch_session(self, session_id: str) -> None:
        self.chat_session = ChatSession(session_id=session_id)
        self.chat_session.attach_store(self.store, load_existing=True)


def _make_api(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    return ChatAPI(runtime), runtime, store


def _chat_message(
    message_id: str,
    role: MessageRole,
    content: str = "",
    task_id: str | None = None,
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        role=role,
        content=content,
        status=MessageStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        task_id=task_id,
    )


def test_send_message_creates_task_and_links_user_message(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("  你好  ")

        assert result["ok"] is True
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.description == "你好"
        assert task.chat_session_id == runtime.chat_session.session_id

        user = runtime.chat_session.get_messages()[0]
        assert user.role == MessageRole.USER
        assert user.content == "你好"
        assert user.task_id == task.task_id
        assert user.status == MessageStatus.PENDING
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_sort_messages_keeps_assistant_only_task_in_timeline():
    proactive = _chat_message("proactive", MessageRole.ASSISTANT, "主动提醒", task_id="tp")
    user = _chat_message("user", MessageRole.USER, "收到", task_id="tu")
    assistant = _chat_message("assistant", MessageRole.ASSISTANT, "继续回复", task_id="tu")

    sorted_messages = ChatAPI._sort_messages_by_task([proactive, user, assistant])

    assert [message.message_id for message in sorted_messages] == [
        "proactive",
        "user",
        "assistant",
    ]


def test_send_message_accepts_pasted_image_attachment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")

        result = api.send_message(
            "看一下这张图",
            attachments=[{
                "name": "screen.png",
                "data_url": data_url,
            }],
        )

        assert result["ok"] is True
        assert len(result["attachments"]) == 1
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["kind"] == "image"
        assert task.attachments[0]["path"].endswith(".png")

        messages = api.get_messages()["messages"]
        assert messages[0]["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in messages[0]["attachments"][0]
    finally:
        store.close()


def test_proactive_session_followup_attaches_fresh_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-proactive-png")
        return {"width": 3024, "height": 1964, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    runtime.chat_session = ChatSession(session_id=PROACTIVE_CHAT_SESSION_ID)
    runtime.chat_session.attach_store(store, load_existing=False)
    try:
        result = api.send_message("你可以主动看一下桌面吗？")

        assert result["ok"] is True
        assert len(captures) == 1
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["source"] == "proactive_desktop_followup"
        user = runtime.chat_session.get_messages()[0]
        assert user.content == "你可以主动看一下桌面吗？"
        assert user.attachments[0]["source"] == "proactive_desktop_followup"
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["source"] == "proactive_desktop_followup"
        assert "附加当前桌面截图" in task.description
    finally:
        store.close()


def test_attachment_cache_cleanup_prunes_old_files(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_AGE_SECONDS", 1)
    monkeypatch.setattr("apps.shell.chat_api._MAX_ATTACHMENT_CACHE_BYTES", 1024 * 1024)
    old_dir = hermes_home / "yachiyo" / "attachments" / "deadbeef"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "old.png"
    old_file.write_bytes(b"old")
    old_time = time.time() - 10
    os.utime(old_file, (old_time, old_time))

    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"new-png").decode("ascii")

        result = api.send_message("看一下这张图", attachments=[{"name": "screen.png", "data_url": data_url}])

        assert result["ok"] is True
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        new_path = Path(task.attachments[0]["path"])
        assert new_path.exists()
        assert not old_file.exists()
    finally:
        store.close()


def test_delete_current_session_removes_attachment_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    api, runtime, store = _make_api(tmp_path)
    runtime.chat_session = ChatSession(session_id="deadbeef")
    runtime.chat_session.attach_store(store, load_existing=False)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
        result = api.send_message("删除这张图", attachments=[{"name": "screen.png", "data_url": data_url}])
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        attachment_dir = Path(task.attachments[0]["path"]).parent
        assert attachment_dir.exists()

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == "deadbeef"
        assert not attachment_dir.exists()
    finally:
        _store_mod.get_chat_store = original_get_store
        store.close()


def test_running_task_marks_message_processing(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("执行任务")
        runtime.state.update_task_status(result["task_id"], TaskStatus.RUNNING)

        messages = api.get_messages()["messages"]

        assert len(messages) == 2  # user + assistant placeholder
        assert messages[0]["status"] == "processing"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "processing"
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_completed_task_adds_single_assistant_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("完成任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="完成输出")

        first = api.get_messages()["messages"]
        second = api.get_messages()["messages"]

        assert len(first) == 2
        assert len(second) == 2
        assert first[0]["status"] == "completed"
        assert first[1]["role"] == "assistant"
        assert first[1]["content"] == "完成输出"
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_failed_task_marks_user_failed_and_adds_error_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("失败任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.FAILED, error="boom")

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[0]["status"] == "failed"
        assert messages[0]["error"] == "boom"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "failed"
        assert "boom" in messages[1]["content"]
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_cancelled_task_marks_user_failed_and_adds_cancel_reply(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("取消任务")
        task_id = result["task_id"]
        runtime.state.cancel_task(task_id)

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[0]["status"] == "failed"
        assert messages[0]["error"] == "任务已取消"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "failed"
        assert "任务已取消" in messages[1]["content"]
        assert api.get_session_info()["is_processing"] is False
    finally:
        store.close()


def test_clear_session_cancels_active_task_and_persists_cancel(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("清空前仍在执行")
        task_id = result["task_id"]
        old_session_id = runtime.chat_session.session_id
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)

        cleared = api.clear_session()

        assert cleared["ok"] is True
        assert cleared["cancelled_tasks"] == 1
        assert cleared["session_id"] != old_session_id
        assert runtime.state.get_task(task_id).status == TaskStatus.CANCELLED
        assert runtime.cancelled_runner_tasks == [task_id]
        assert api.get_messages()["messages"] == []

        old_messages = store.load_messages(old_session_id)
        assert len(old_messages) == 2
        assert old_messages[0].status == "failed"
        assert old_messages[0].error == "任务已取消"
        assert old_messages[1].role == "assistant"
        assert old_messages[1].status == "failed"
        assert old_messages[1].error == "任务已取消"
    finally:
        store.close()


def test_delete_current_session_removes_session_and_cancels_active_task(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        result = api.send_message("删除前仍在执行")
        task_id = result["task_id"]
        old_session_id = runtime.chat_session.session_id
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == old_session_id
        assert deleted["session_id"] != old_session_id
        assert deleted["cancelled_tasks"] == 1
        assert deleted["remaining_sessions"] == 0
        assert deleted["empty"] is True
        assert runtime.state.get_task(task_id).status == TaskStatus.CANCELLED
        assert runtime.cancelled_runner_tasks == [task_id]
        assert store.get_session(old_session_id) is None
        assert store.load_messages(old_session_id) == []
        assert api.get_messages()["messages"] == []
    finally:
        _store_mod.get_chat_store = original_get_store
        store.close()


def test_delete_current_session_switches_to_remaining_recent_session(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    original_get_store = _store_mod.get_chat_store
    _store_mod.get_chat_store = lambda: store
    try:
        other = ChatSession(session_id="s2")
        other.attach_store(store, load_existing=False)
        other.add_user_message("保留的会话")
        another = ChatSession(session_id="s3")
        another.attach_store(store, load_existing=False)
        another.add_user_message("另一个保留会话")

        deleted = api.delete_current_session()

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == "s1"
        assert deleted["session_id"] in {"s2", "s3"}
        assert deleted["remaining_sessions"] == 2
        assert deleted["empty"] is False
        assert runtime.chat_session.session_id == deleted["session_id"]
        assert api.get_messages()["messages"][0]["content"] in {
            "保留的会话",
            "另一个保留会话",
        }
    finally:
        _store_mod.get_chat_store = original_get_store
        store.close()


def test_completing_one_of_multiple_messages_keeps_processing_true(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        first = api.send_message("任务一")
        second = api.send_message("任务二")
        runtime.state.update_task_status(first["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(
            first["task_id"], TaskStatus.COMPLETED, result="任务一完成"
        )

        messages = api.get_messages()["messages"]

        # 排序后: user1(completed) → assistant1(completed) → user2(pending)
        assert len(messages) == 3
        assert messages[0]["status"] == "completed"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "任务一完成"
        assert messages[2]["task_id"] == second["task_id"]
        assert messages[2]["status"] == "pending"
        assert api.get_session_info()["is_processing"] is True
    finally:
        store.close()


def test_get_messages_idempotent_no_duplicate_assistant(tmp_path):
    """多次 get_messages 不会生成重复 assistant 消息"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("幂等测试")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="结果")

        # 调用多次 get_messages
        for _ in range(5):
            msgs = api.get_messages()["messages"]

        assert len(msgs) == 2
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "结果"
    finally:
        store.close()


def test_processing_to_completed_updates_same_message(tmp_path):
    """processing 占位 → completed 应更新同一条消息，而非新增"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("状态迁移")
        task_id = result["task_id"]

        # RUNNING → 产生 processing placeholder
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        msgs_processing = api.get_messages()["messages"]
        assert len(msgs_processing) == 2
        placeholder_id = msgs_processing[1]["id"]
        assert msgs_processing[1]["status"] == "processing"

        # COMPLETED → 更新同一条 assistant 消息
        runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result="最终回复")
        msgs_completed = api.get_messages()["messages"]
        assert len(msgs_completed) == 2
        assert msgs_completed[1]["id"] == placeholder_id  # 同一条消息
        assert msgs_completed[1]["status"] == "completed"
        assert msgs_completed[1]["content"] == "最终回复"
    finally:
        store.close()


def test_processing_to_failed_updates_same_message(tmp_path):
    """processing 占位 → failed 应更新同一条消息"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("失败迁移")
        task_id = result["task_id"]

        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        msgs_processing = api.get_messages()["messages"]
        placeholder_id = msgs_processing[1]["id"]

        runtime.state.update_task_status(task_id, TaskStatus.FAILED, error="崩溃")
        msgs_failed = api.get_messages()["messages"]
        assert len(msgs_failed) == 2
        assert msgs_failed[1]["id"] == placeholder_id
        assert msgs_failed[1]["status"] == "failed"
        assert "崩溃" in msgs_failed[1]["content"]
    finally:
        store.close()


def test_running_task_preserves_streamed_assistant_content(tmp_path):
    """RUNNING 状态轮询不应清空执行器已经写入的流式内容。"""
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("流式任务")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        runtime.chat_session.upsert_assistant_message(
            task_id,
            "部分流式输出",
            MessageStatus.PROCESSING,
        )

        messages = api.get_messages()["messages"]

        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["status"] == "processing"
        assert messages[1]["content"] == "部分流式输出"
    finally:
        store.close()


def test_assistant_only_task_syncs_without_visible_user_prompt(tmp_path):
    """主动关怀这类内部任务可以只显示 assistant 状态消息。"""
    api, runtime, store = _make_api(tmp_path)
    try:
        task = runtime.state.create_task("主动桌面观察：内部执行 prompt")
        runtime.chat_session.upsert_assistant_message(
            task.task_id,
            "正在查看当前状态。",
            MessageStatus.PROCESSING,
        )

        runtime.state.update_task_status(task.task_id, TaskStatus.COMPLETED, result="周末上午过得怎么样？")
        messages = api.get_messages()["messages"]

        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["task_id"] == task.task_id
        assert messages[0]["status"] == "completed"
        assert messages[0]["content"] == "周末上午过得怎么样？"
        assert "主动桌面观察" not in messages[0]["content"]
    finally:
        store.close()


def test_message_sorting_pairs_user_with_assistant(tmp_path):
    """消息排序：user 消息后紧跟其关联的 assistant 回复"""
    api, runtime, store = _make_api(tmp_path)
    try:
        r1 = api.send_message("任务一")
        r2 = api.send_message("任务二")

        # 任务二先完成
        runtime.state.update_task_status(r2["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r2["task_id"], TaskStatus.COMPLETED, result="二完成")
        # 任务一后完成
        runtime.state.update_task_status(r1["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r1["task_id"], TaskStatus.COMPLETED, result="一完成")

        msgs = api.get_messages()["messages"]
        assert len(msgs) == 4  # 2 user + 2 assistant

        # user1 → assistant1, user2 → assistant2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["task_id"] == r1["task_id"]
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "一完成"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["task_id"] == r2["task_id"]
        assert msgs[3]["role"] == "assistant"
        assert msgs[3]["content"] == "二完成"
    finally:
        store.close()


def test_message_sorting_keeps_unpaired_task_assistant():
    """分页截断 user 消息时，带 task_id 的 assistant 仍应返回给前端。"""
    assistant = _chat_message(
        "a1",
        MessageRole.ASSISTANT,
        content="分页截断后仍可见的回复",
        task_id="t1",
    )

    sorted_msgs = ChatAPI._sort_messages_by_task([assistant])

    assert sorted_msgs == [assistant]


def test_message_sorting_does_not_duplicate_untracked_assistant():
    """无 task_id 的 assistant 消息保持原始位置且不会被重复追加。"""
    system = _chat_message("s1", MessageRole.SYSTEM, content="系统提示")
    assistant = _chat_message("a1", MessageRole.ASSISTANT, content="旧回复")

    sorted_msgs = ChatAPI._sort_messages_by_task([system, assistant])

    assert [msg.message_id for msg in sorted_msgs] == ["s1", "a1"]
