"""ChatSession 测试 — 会话恢复与清空后的持久化闭环"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from apps.core.chat_session import ChatSession, MessageRole, MessageStatus
from apps.core.chat_store import ChatStore, StoredMessage

import apps.core.chat_session as _cs_mod
import apps.core.chat_store as _store_mod


def test_chat_session_restores_messages(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("你好")
        session.link_message_to_task(user_id, "t1")
        session.add_assistant_message("你好，我是 Yachiyo", task_id="t1")

        restored = ChatSession(session_id="s1")
        restored.attach_store(store)

        assert len(restored.messages) == 2
        assert restored.messages[0].content == "你好"
        assert restored.messages[0].status == MessageStatus.COMPLETED
        assert restored.messages[1].content == "你好，我是 Yachiyo"
    finally:
        store.close()


def test_chat_session_restores_all_messages_beyond_default_window(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        store.create_session("s1")
        for index in range(130):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id="s1",
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
            ))

        restored = ChatSession(session_id="s1")
        restored.attach_store(store)

        assert len(restored.messages) == 130
        assert restored.messages[0].content == "消息 0"
        assert restored.messages[-1].content == "消息 129"
    finally:
        store.close()


def test_add_assistant_message_with_error_updates_user_error(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("会失败的任务")
        session.link_message_to_task(user_id, "t1")

        session.add_assistant_message("失败了", task_id="t1", error="boom")

        assert session.messages[0].status == MessageStatus.FAILED
        assert session.messages[0].error == "boom"
        assert store.load_messages("s1")[0].error == "boom"
    finally:
        store.close()


def test_chat_session_clear_creates_new_persisted_session(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.add_user_message("旧消息")

        session.clear()
        new_session_id = session.session_id
        session.add_user_message("新消息")

        assert new_session_id != "s1"
        assert len(store.load_messages(new_session_id)) == 1
        assert store.load_messages(new_session_id)[0].content == "新消息"
    finally:
        store.close()


def test_chat_session_marks_orphaned_processing_messages_failed(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="还在执行的旧任务",
            status="processing",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))

        restored = ChatSession(session_id="s1")
        restored.attach_store(store)

        assert restored.messages[0].status == MessageStatus.FAILED
        assert "不可恢复" in (restored.messages[0].error or "")
        assert store.load_messages("s1")[0].status == "failed"
    finally:
        store.close()


def test_chat_session_can_preserve_active_messages_during_live_switch(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="assistant",
            content="正在执行",
            status="processing",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))

        restored = ChatSession(session_id="s1")
        restored.attach_store(store, fail_active_messages=False)

        assert restored.messages[0].status == MessageStatus.PROCESSING
        assert restored.messages[0].error is None
        assert store.load_messages("s1")[0].status == "processing"
    finally:
        store.close()


def test_upsert_assistant_message_idempotent(tmp_path):
    """多次 upsert 同一 task_id 不产生重复消息"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("测试幂等")
        session.link_message_to_task(user_id, "t1")

        # 多次 upsert 同一 task_id
        id1 = session.upsert_assistant_message("t1", "", MessageStatus.PROCESSING)
        id2 = session.upsert_assistant_message("t1", "部分结果", MessageStatus.PROCESSING)
        id3 = session.upsert_assistant_message("t1", "最终结果", MessageStatus.COMPLETED)

        assert id1 == id2 == id3  # 始终是同一条消息
        assert len(session.messages) == 2  # user + assistant
        assert session.messages[1].content == "最终结果"
        assert session.messages[1].status == MessageStatus.COMPLETED

        # SQLite 中也只有一条 assistant 消息
        db_msgs = store.load_messages("s1")
        assistant_msgs = [m for m in db_msgs if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "最终结果"
        assert assistant_msgs[0].status == "completed"
    finally:
        store.close()


def test_upsert_reuses_persisted_assistant_across_session_instances(tmp_path):
    """跨实例流式写入不会创建第二条 assistant。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        foreground = ChatSession(session_id="s1")
        foreground.attach_store(store, load_existing=False)
        user_id = foreground.add_user_message("跨实例流式")
        foreground.link_message_to_task(user_id, "t1")

        background = ChatSession(session_id="s1")
        background.attach_store(store, load_existing=True, fail_active_messages=False)
        placeholder_id = background.upsert_assistant_message("t1", "", MessageStatus.PROCESSING)

        streaming_id = foreground.upsert_assistant_message(
            "t1",
            "部分输出",
            MessageStatus.PROCESSING,
        )
        completed_id = foreground.upsert_assistant_message(
            "t1",
            "最终结果",
            MessageStatus.COMPLETED,
        )

        db_msgs = store.load_messages("s1")
        assistant_msgs = [m for m in db_msgs if m.role == "assistant" and m.task_id == "t1"]
        assert placeholder_id == streaming_id == completed_id
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "最终结果"
        assert assistant_msgs[0].status == "completed"
        assert foreground.is_processing() is False
    finally:
        store.close()


def test_session_load_dedupes_stale_processing_assistant(tmp_path):
    """兼容旧库里同 task 同时存在 completed 和 processing 的脏数据。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="user",
            session_id="s1",
            role="user",
            content="早上好",
            status="completed",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))
        store.save_message(StoredMessage(
            message_id="assistant-done",
            session_id="s1",
            role="assistant",
            content="早上好呀",
            status="completed",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:01+00:00",
        ))
        store.save_message(StoredMessage(
            message_id="assistant-stale",
            session_id="s1",
            role="assistant",
            content="早上好呀",
            status="processing",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:02+00:00",
        ))

        restored = ChatSession(session_id="s1")
        restored.attach_store(store, load_existing=True, fail_active_messages=False)

        assistant_msgs = [m for m in restored.messages if m.role == MessageRole.ASSISTANT]
        db_assistant_msgs = [m for m in store.load_messages("s1") if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].message_id == "assistant-done"
        assert assistant_msgs[0].status == MessageStatus.COMPLETED
        assert len(db_assistant_msgs) == 1
        assert db_assistant_msgs[0].message_id == "assistant-done"
        assert restored.is_processing() is False
    finally:
        store.close()


def test_upsert_assistant_message_can_attach_cached_audio(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.upsert_assistant_message(
            "t1",
            "主动关怀文本",
            MessageStatus.COMPLETED,
            attachments=[{
                "id": "audio1",
                "kind": "audio",
                "name": "主动关怀语音.wav",
                "mime_type": "audio/wav",
            }],
        )

        restored = ChatSession(session_id="s1")
        restored.attach_store(store, load_existing=True)
        message = restored.get_messages()[0]

        assert message.role == MessageRole.ASSISTANT
        assert message.attachments[0]["kind"] == "audio"
        assert message.attachments[0]["mime_type"] == "audio/wav"
    finally:
        store.close()


def test_upsert_processing_to_completed_updates_user_status(tmp_path):
    """processing → completed 时，user 消息状态也被同步更新"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("状态同步")
        session.link_message_to_task(user_id, "t1")

        session.upsert_assistant_message("t1", "", MessageStatus.PROCESSING)
        assert session.messages[0].status == MessageStatus.PROCESSING

        session.upsert_assistant_message("t1", "结果", MessageStatus.COMPLETED)
        assert session.messages[0].status == MessageStatus.COMPLETED
        assert session.is_processing() is False
    finally:
        store.close()


def test_upsert_does_not_downgrade_from_completed(tmp_path):
    """已完成的 assistant 消息不会被 PROCESSING 降级"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("降级测试")
        session.link_message_to_task(user_id, "t1")

        session.upsert_assistant_message("t1", "最终结果", MessageStatus.COMPLETED)
        session.upsert_assistant_message("t1", "", MessageStatus.PROCESSING)

        assert session.messages[1].status == MessageStatus.COMPLETED
        assert session.messages[1].content == "最终结果"
    finally:
        store.close()


def test_session_restore_no_duplicate_assistant(tmp_path):
    """会话恢复后不会把 assistant 消息重复渲染"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        # 创建原始会话并持久化
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("恢复测试")
        session.link_message_to_task(user_id, "t1")
        session.upsert_assistant_message("t1", "回复", MessageStatus.COMPLETED)

        # 模拟重启恢复
        restored = ChatSession(session_id="s1")
        restored.attach_store(store)

        assert len(restored.messages) == 2
        assistant_msgs = [
            m for m in restored.messages if m.role == MessageRole.ASSISTANT
        ]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "回复"
    finally:
        store.close()


def test_set_hermes_session_id_persists(tmp_path):
    """set_hermes_session_id 应同时更新内存和数据库"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.set_hermes_session_id("hermes_abc")
        assert session.hermes_session_id == "hermes_abc"

        # 从 DB 验证
        stored = store.get_session("s1")
        assert stored is not None
        assert stored.hermes_session_id == "hermes_abc"
    finally:
        store.close()


def test_hermes_session_id_restored_on_attach(tmp_path):
    """attach_store(load_existing=True) 恢复 hermes_session_id"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.set_hermes_session_id("hermes_xyz")

        restored = ChatSession(session_id="s1")
        restored.attach_store(store, load_existing=True)
        assert restored.hermes_session_id == "hermes_xyz"
    finally:
        store.close()


def test_clear_resets_hermes_session_id(tmp_path):
    """clear() 应重置 hermes_session_id"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.set_hermes_session_id("hermes_old")
        session.clear()
        assert session.hermes_session_id is None
    finally:
        store.close()


def test_user_message_sets_session_summary_title(tmp_path):
    """首条用户消息会作为会话列表标题摘要。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)

        session.add_user_message("  帮我分析这个项目\n并列出需要修复的问题  ")
        session.add_user_message("第二条不应覆盖标题")

        stored = store.get_session("s1")
        assert stored is not None
        assert stored.title == "帮我分析这个项目 并列出需要修复的问题"
    finally:
        store.close()


def test_chat_session_persists_user_attachments(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        session.add_user_message(
            "看图",
            attachments=[{
                "id": "a1",
                "kind": "image",
                "name": "screen.png",
                "mime_type": "image/png",
                "size": 8,
                "path": str(tmp_path / "screen.png"),
            }],
        )

        restored = ChatSession(session_id="s1")
        restored.attach_store(store)

        assert restored.messages[0].attachments[0]["id"] == "a1"
        assert restored.to_dict()["messages"][0]["attachments"][0]["name"] == "screen.png"
    finally:
        store.close()


def test_set_session_title_overrides_summary_title(tmp_path):
    """Hermes 自动标题可覆盖首条用户消息兜底标题。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)

        session.add_user_message("请帮我看看这个项目")
        session.set_session_title("Hermes 自动摘要标题")

        stored = store.get_session("s1")
        assert stored is not None
        assert stored.title == "Hermes 自动摘要标题"
    finally:
        store.close()


def test_set_session_title_ignores_prompt_echo_title(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)

        session.add_user_message("请帮我看看这个项目")
        session.set_session_title("首先，用户要求为这段持续对话生成一个会话列表标题。")

        stored = store.get_session("s1")
        assert stored is not None
        assert stored.title == "请帮我看看这个项目"
    finally:
        store.close()


def test_get_assistant_message_for_task(tmp_path):
    """可按 task_id 取回已存在的 assistant 消息。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        session = ChatSession(session_id="s1")
        session.attach_store(store, load_existing=False)
        user_id = session.add_user_message("流式测试")
        session.link_message_to_task(user_id, "t1")
        session.upsert_assistant_message("t1", "部分输出", MessageStatus.PROCESSING)

        assistant = session.get_assistant_message_for_task("t1")

        assert assistant is not None
        assert assistant.content == "部分输出"
        assert session.get_assistant_message_for_task("missing") is None
    finally:
        store.close()


def test_switch_chat_session(tmp_path):
    """switch_chat_session 切换到已有会话并加载消息"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        # 创建两个会话
        s1 = ChatSession(session_id="s1")
        s1.attach_store(store, load_existing=False)
        s1.add_user_message("会话1消息")
        s1.set_hermes_session_id("hid_1")

        s2 = ChatSession(session_id="s2")
        s2.attach_store(store, load_existing=False)
        s2.add_user_message("会话2消息A")
        s2.add_user_message("会话2消息B")

        # monkeypatch get_chat_store 返回相同 store
        original = _store_mod.get_chat_store
        _store_mod.get_chat_store = lambda: store
        try:
            switched = _cs_mod.switch_chat_session("s1")
            assert switched.session_id == "s1"
            assert switched.message_count() == 1
            assert switched.hermes_session_id == "hid_1"

            switched2 = _cs_mod.switch_chat_session("s2")
            assert switched2.session_id == "s2"
            assert switched2.message_count() == 2
        finally:
            _store_mod.get_chat_store = original
    finally:
        store.close()


def test_switch_chat_session_preserves_live_processing_messages(tmp_path):
    """同进程切换会话时不应误判为应用重启。"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="assistant",
            content="Hermes 正在推理",
            status="processing",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))

        original = _store_mod.get_chat_store
        _store_mod.get_chat_store = lambda: store
        try:
            switched = _cs_mod.switch_chat_session("s1")
            assert switched.messages[0].status == MessageStatus.PROCESSING
            assert store.load_messages("s1")[0].status == "processing"
        finally:
            _store_mod.get_chat_store = original
    finally:
        store.close()


def test_get_chat_session_initializes_global_once_under_concurrency(monkeypatch):
    """多线程首次访问全局会话时只应初始化并 attach 一次。"""

    class SlowStore:
        def __init__(self) -> None:
            self.list_calls = 0
            self.create_calls = 0
            self._lock = threading.Lock()

        def list_sessions(self, limit: int = 1):
            with self._lock:
                self.list_calls += 1
            time.sleep(0.02)
            return []

        def create_session(self, session_id: str, title: str = "") -> None:
            with self._lock:
                self.create_calls += 1

        def load_messages(self, session_id: str, limit: int = 100):
            return []

        def get_session(self, session_id: str):
            return None

    store = SlowStore()
    monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(_cs_mod, "_global_session", None)

    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            sessions = list(executor.map(lambda _: _cs_mod.get_chat_session(), range(24)))

        assert len({id(session) for session in sessions}) == 1
        assert store.list_calls == 1
        assert store.create_calls == 1
    finally:
        _cs_mod._global_session = None
