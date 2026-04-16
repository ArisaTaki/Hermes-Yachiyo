"""ChatSession 测试 — 会话恢复与清空后的持久化闭环"""

from apps.core.chat_session import ChatSession, MessageRole, MessageStatus
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
