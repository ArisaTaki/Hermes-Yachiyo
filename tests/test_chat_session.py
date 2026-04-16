"""ChatSession 测试 — 会话恢复与清空后的持久化闭环"""

from apps.core.chat_session import ChatSession, MessageStatus
from apps.core.chat_store import ChatStore, StoredMessage


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
