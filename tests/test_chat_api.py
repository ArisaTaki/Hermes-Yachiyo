"""ChatAPI 测试 — 消息发送与任务状态同步"""

import base64
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from apps.core.activity_store import ActivityStore
from apps.core.chat_session import ChatMessage, ChatSession, MessageRole, MessageStatus
from apps.core.chat_store import ChatStore, StoredMessage
import apps.core.chat_store as _store_mod
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
import apps.shell.chat_api as chat_api_mod
from apps.shell.agent_runtime import AgentRuntimeService
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
        self.chat_session.attach_store(
            self.store,
            load_existing=True,
            fail_active_messages=False,
        )

    def start_new_session(self) -> str:
        self.chat_session = ChatSession()
        self.chat_session.attach_store(self.store, load_existing=False)
        return self.chat_session.session_id


def _make_api(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    return ChatAPI(runtime), runtime, store


def _chat_message(
    message_id: str,
    role: MessageRole,
    content: str = "",
    task_id: str | None = None,
    status: MessageStatus = MessageStatus.COMPLETED,
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        role=role,
        content=content,
        status=status,
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


def test_send_message_rejects_when_hermes_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    runtime.task_runner = SimpleNamespace(
        executor=SimpleNamespace(
            name="HermesUnavailableExecutor",
            reason="Hermes Agent 当前不可用",
        )
    )
    try:
        result = api.send_message("你好")

        assert result == {"ok": False, "error": "Hermes Agent 当前不可用"}
        assert runtime.state.list_tasks() == []
        assert runtime.chat_session.get_messages() == []
    finally:
        store.close()


def test_agent_mention_creates_agent_run_without_general_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Helper",
            "description": "test helper",
            "instructions": "Summarize requests.",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat", lambda *_args, **_kwargs: "Agent result")
    try:
        result = api.send_message("@Helper 做个总结")
        assert result["ok"] is True
        assert result["runnable_command"] is True
        assert result["agent_run_id"]
        assert result["run_group_id"]
        assert runtime.state.list_tasks() == []
        run = service.get_run(result["agent_run_id"])
        assert run["status"] == "completed"
        assert run["run_group_id"] == result["run_group_id"]
        assert run["runnable_id"] == agent["agent_id"]
        messages = runtime.chat_session.get_messages()
        assert messages[0].status == MessageStatus.COMPLETED
        assert messages[1].role == MessageRole.ASSISTANT
    finally:
        service.close()
        store.close()


def test_get_messages_limit_zero_returns_complete_current_session(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        for index in range(90):
            runtime.chat_session.add_system_message(f"系统消息 {index}")

        messages = api.get_messages(limit=0)["messages"]

        assert len(messages) == 90
        assert messages[0]["content"] == "系统消息 0"
        assert messages[-1]["content"] == "系统消息 89"
    finally:
        store.close()


def test_selected_runnable_creates_agent_run_without_mention(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Draft Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat", lambda *_args, **_kwargs: "Agent result")
    try:
        result = api.send_message("整理需求", runnable_id=agent["agent_id"])
        assert result["ok"] is True
        assert result["runnable_command"] is True
        assert result["agent_run_id"]
        assert runtime.state.list_tasks() == []
    finally:
        service.close()
        store.close()


def test_agent_mention_supports_multiword_names(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        seed_templates=False,
    )
    agent = service.create_agent(
        {
            "name": "Draft Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat", lambda *_args, **_kwargs: "Agent result")
    try:
        result = api.send_message("@Draft Agent 整理需求")
        assert result["ok"] is True
        assert result["agent_run_id"]
        run = service.get_run(result["agent_run_id"])
        assert run["runnable_id"] == agent["agent_id"]
        assert runtime.state.list_tasks() == []
    finally:
        service.close()
        store.close()


def test_get_messages_and_sessions_include_activity_events(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        result = api.send_message("跑一下脚本")
        task_id = result["task_id"]
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="terminal",
            phase="tool_start",
            title="正在运行脚本",
            detail="python build.py",
            status="running",
        )
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content="",
            status=MessageStatus.PROCESSING,
        )

        messages = api.get_messages()["messages"]
        user = messages[0]
        assistant = messages[1]
        assert user["progress_label"] == ""
        assert user["activity_events"] == []
        assert assistant["activity_events"][0]["title"] == "正在运行脚本"

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == runtime.chat_session.session_id)
        assert current["is_processing"] is True
        assert current["latest_activity"]["tool_name"] == "terminal"
        assert current["latest_activity"]["title"] == "正在运行脚本"
        assert current["latest_message_preview"] == "跑一下脚本"
        assert current["latest_message_status"] == "processing"
    finally:
        activity_store.close()
        store.close()


def test_get_messages_hides_internal_reasoning_activity(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        result = api.send_message("普通回复")
        task_id = result["task_id"]
        runtime.state.update_task_progress(task_id, "Hermes 正在推理")
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="",
            phase="reasoning",
            title="Hermes 正在推理",
            detail="内部思考片段",
            status="running",
        )
        activity_store.record_event(
            session_id=runtime.chat_session.session_id,
            task_id=task_id,
            tool_name="hermes",
            phase="task_start",
            title="Yachiyo 开始处理",
            detail="普通回复",
            status="running",
        )
        runtime.chat_session.upsert_assistant_message(
            task_id=task_id,
            content="",
            status=MessageStatus.PROCESSING,
        )

        assistant = api.get_messages()["messages"][1]

        assert assistant["activity_events"] == []
        assert assistant["progress_label"] == ""
    finally:
        activity_store.close()
        store.close()


def test_list_sessions_ignores_stale_stored_processing_without_live_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("已经完成的问题")
        runtime.chat_session.upsert_assistant_message(
            task_id="stale-task",
            content="旧的处理中占位",
            status=MessageStatus.PROCESSING,
        )

        sessions = api.list_sessions()["sessions"]
        current = next(item for item in sessions if item["session_id"] == session_id)

        assert current["is_processing"] is False
        assert current["latest_message_preview"] == "已经完成的问题"
        assert current["latest_message_status"] == "processing"
    finally:
        store.close()


def test_session_title_ignores_prompt_echo_stored_title():
    messages = [
        SimpleNamespace(role=MessageRole.USER.value, content="测试1"),
        SimpleNamespace(role=MessageRole.ASSISTANT.value, content="收到"),
    ]

    assert ChatAPI._session_title("首先，用户要求为这段持续对话生成一个会话列表标题。", messages) == "测试1"


def test_list_sessions_search_includes_message_match(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        runtime.chat_session.add_user_message("这里有聊天搜索关键词")

        sessions = api.list_sessions(query="聊天")["sessions"]

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == session_id
        assert sessions[0]["search_match"]["message_id"]
        assert "聊天" in sessions[0]["search_match"]["snippet"]
    finally:
        store.close()


def test_get_messages_can_load_around_search_anchor(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    try:
        session_id = runtime.chat_session.session_id
        for index in range(6):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id=session_id,
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        messages = api.get_messages(limit=3, anchor_message_id="m3")["messages"]

        assert "m3" in [message["id"] for message in messages]
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


def test_sort_messages_dedupes_repeated_assistant_for_same_user_task():
    user = _chat_message("user", MessageRole.USER, "早上好", task_id="t1")
    completed = _chat_message("assistant-done", MessageRole.ASSISTANT, "早上好呀", task_id="t1")
    stale_processing = _chat_message(
        "assistant-stale",
        MessageRole.ASSISTANT,
        "早上好呀",
        task_id="t1",
        status=MessageStatus.PROCESSING,
    )

    sorted_messages = ChatAPI._sort_messages_by_task([user, completed, stale_processing])

    assert [message.message_id for message in sorted_messages] == ["user", "assistant-done"]


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


def test_user_requested_desktop_snapshot_attaches_in_normal_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-screen-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("帮我看看我的桌面情况")

        assert result["ok"] is True
        assert len(captures) == 1
        assert result["attachments"][0]["source"] == "user_requested_desktop_snapshot"
        user = runtime.chat_session.get_messages()[0]
        assert user.content == "帮我看看我的桌面情况"
        assert user.attachments[0]["source"] == "user_requested_desktop_snapshot"
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments[0]["source"] == "user_requested_desktop_snapshot"
        assert "附加当前桌面截图" in task.description
    finally:
        store.close()


def test_user_implicit_current_activity_request_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-current-activity-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("你能看看我现在在做什么不")

        assert result["ok"] is True
        assert captures == []
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == "你能看看我现在在做什么不"
    finally:
        store.close()


def test_design_feedback_with_plain_screen_word_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chat_api_mod,
        "capture_screenshot_to_file",
        lambda _target_path: (_ for _ in ()).throw(AssertionError("should not capture")),
    )
    api, runtime, store = _make_api(tmp_path)
    try:
        text = (
            '我看了一下当前桌面，class="plan-dropdown-item" 的显示有问题，'
            "plan 的名字的显示区域被挤压到显示不出来文字，需要修改成能够显示每个 plan 的名字。\n\n"
            "除功能以外，设计风格想要麻烦再出一版新的设计看一下。要求：\n"
            "1. 仅对画面元素和 UI 进行调整，保持现有功能 100% 不变。\n"
            "2. 风格修改为多巴胺风格，通过高饱和度、鲜艳明亮的色彩搭配以营造愉悦、快乐情绪和氛围的风格\n"
            "3. 请不要覆盖原文件，生成一个新的 html 文件"
        )

        result = api.send_message(text)

        assert result["ok"] is True
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == text.strip()
    finally:
        store.close()


def test_explicit_agent_desktop_request_still_attaches_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    captures = []

    def fake_capture(target_path: Path):
        captures.append(target_path)
        target_path.write_bytes(b"fake-explicit-screen-png")
        return {"width": 1920, "height": 1080, "size": target_path.stat().st_size}

    monkeypatch.setattr(chat_api_mod, "capture_screenshot_to_file", fake_capture)
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("请你看一下当前桌面，帮我判断窗口里有什么问题")

        assert result["ok"] is True
        assert len(captures) == 1
        assert result["attachments"][0]["source"] == "user_requested_desktop_snapshot"
    finally:
        store.close()


def test_plain_message_does_not_attach_desktop_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        chat_api_mod,
        "capture_screenshot_to_file",
        lambda _target_path: (_ for _ in ()).throw(AssertionError("should not capture")),
    )
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("你好，今天聊点别的")

        assert result["ok"] is True
        assert result["attachments"] == []
        task = runtime.state.get_task(result["task_id"])
        assert task is not None
        assert task.attachments == []
        assert task.description == "你好，今天聊点别的"
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


def test_retry_failed_message_reuses_saved_image_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    api, runtime, store = _make_api(tmp_path)
    try:
        data_url = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")
        sent = api.send_message("再看一下这张图", attachments=[{"name": "screen.png", "data_url": data_url}])
        original_task = runtime.state.get_task(sent["task_id"])
        assert original_task is not None
        original_path = original_task.attachments[0]["path"]
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(sent["task_id"], TaskStatus.FAILED, error="vision failed")
        failed_messages = api.get_messages()["messages"]

        retry = api.retry_message(failed_messages[1]["id"])

        assert retry["ok"] is True
        retried_task = runtime.state.get_task(retry["task_id"])
        assert retried_task is not None
        assert retried_task.description == "再看一下这张图"
        assert retried_task.attachments[0]["path"] == original_path
        assert retried_task.chat_session_id == runtime.chat_session.session_id
        retried_user = runtime.chat_session.get_messages()[-1]
        assert retried_user.content == "再看一下这张图"
        assert retried_user.attachments[0]["path"] == original_path
        assert retried_user.status == MessageStatus.PENDING
    finally:
        store.close()


def test_retry_failed_message_rejects_when_hermes_unavailable(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        sent = api.send_message("失败任务")
        runtime.state.update_task_status(sent["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(sent["task_id"], TaskStatus.FAILED, error="boom")
        failed_messages = api.get_messages()["messages"]
        runtime.task_runner = SimpleNamespace(
            executor=SimpleNamespace(
                name="HermesUnavailableExecutor",
                reason="Hermes Agent 当前不可用",
            )
        )

        retry = api.retry_message(failed_messages[1]["id"])

        assert retry == {"ok": False, "error": "Hermes Agent 当前不可用"}
        assert len(runtime.state.list_tasks()) == 1
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


def test_clear_session_starts_new_session_and_preserves_active_task(tmp_path):
    api, runtime, store = _make_api(tmp_path)
    try:
        result = api.send_message("清空前仍在执行")
        task_id = result["task_id"]
        old_session_id = runtime.chat_session.session_id
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
        old_session_object = runtime.chat_session

        cleared = api.clear_session()

        assert cleared["ok"] is True
        assert cleared["cancelled_tasks"] == 0
        assert cleared["session_id"] != old_session_id
        assert runtime.state.get_task(task_id).status == TaskStatus.RUNNING
        assert runtime.cancelled_runner_tasks == []
        assert runtime.chat_session is not old_session_object
        assert old_session_object.session_id == old_session_id
        assert api.get_messages()["messages"] == []

        old_messages = store.load_messages(old_session_id)
        assert len(old_messages) == 2
        assert old_messages[0].status == "processing"
        assert old_messages[0].error is None
        assert old_messages[1].role == "assistant"
        assert old_messages[1].status == "processing"
        assert old_messages[1].error is None

        old_session_object.upsert_assistant_message(task_id, "旧任务完成", MessageStatus.COMPLETED)
        old_messages = store.load_messages(old_session_id)
        assert old_messages[1].content == "旧任务完成"
        assert old_messages[1].status == "completed"
    finally:
        store.close()


def test_delete_current_session_removes_session_and_cancels_active_task(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
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
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        cancel_events = [event for event in events if event.phase == "task_cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0].detail == "删除会话前取消仍在执行的任务"
        assert "删除前仍在执行" not in cancel_events[0].detail
    finally:
        _store_mod.get_chat_store = original_get_store
        activity_store.close()
        store.close()


def test_cancel_current_tasks_records_neutral_activity_detail(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    try:
        result = api.send_message("删除这张图")
        task_id = result["task_id"]
        runtime.state.update_task_status(task_id, TaskStatus.RUNNING)

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 1
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        cancel_events = [event for event in events if event.phase == "task_cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0].detail == "用户停止生成"
        assert "删除这张图" not in cancel_events[0].detail
    finally:
        activity_store.close()
        store.close()


def test_cancel_current_tasks_does_not_log_already_cancelled_stale_message(tmp_path, monkeypatch):
    api, runtime, store = _make_api(tmp_path)
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(api, "_sync_task_status_to_messages", lambda: None)
    try:
        result = api.send_message("已经取消但消息状态还没刷新")
        task_id = result["task_id"]
        runtime.state.cancel_task(task_id)

        cancelled = api.cancel_current_tasks()

        assert cancelled["ok"] is True
        assert cancelled["cancelled_tasks"] == 0
        events = activity_store.list_events(task_id=task_id, limit=5, key_only=False)
        assert [event for event in events if event.phase == "task_cancelled"] == []
        assert runtime.cancelled_runner_tasks == []
    finally:
        activity_store.close()
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
