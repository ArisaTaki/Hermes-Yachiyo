"""ChatStore 测试 — SQLite 持久化层"""

import os
import tempfile

import pytest

from apps.core.chat_store import ChatStore, StoredMessage


@pytest.fixture
def store(tmp_path):
    """使用临时数据库的 ChatStore"""
    db_path = str(tmp_path / "test_chat.db")
    s = ChatStore(db_path=db_path)
    yield s
    s.close()


class TestChatStore:
    def test_create_and_list_sessions(self, store: ChatStore):
        store.create_session("s1", title="测试会话")
        store.create_session("s2", title="另一个会话")
        sessions = store.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id in ("s1", "s2")

    def test_save_and_load_messages(self, store: ChatStore):
        store.create_session("s1")
        msg = StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="你好",
            status="completed",
            task_id=None,
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        )
        store.save_message(msg)
        loaded = store.load_messages("s1")
        assert len(loaded) == 1
        assert loaded[0].content == "你好"
        assert loaded[0].role == "user"

    def test_update_message_status(self, store: ChatStore):
        store.create_session("s1")
        msg = StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="test",
            status="pending",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        )
        store.save_message(msg)
        store.update_message_status("m1", "failed", error="超时")
        loaded = store.load_messages("s1")
        assert loaded[0].status == "failed"
        assert loaded[0].error == "超时"

    def test_delete_session(self, store: ChatStore):
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1", session_id="s1", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        store.delete_session("s1")
        assert len(store.list_sessions()) == 0
        assert len(store.load_messages("s1")) == 0

    def test_duplicate_session_ignored(self, store: ChatStore):
        store.create_session("s1", title="first")
        store.create_session("s1", title="second")  # INSERT OR IGNORE
        sessions = store.list_sessions()
        assert len(sessions) == 1

    def test_message_count_in_session_list(self, store: ChatStore):
        store.create_session("s1")
        for i in range(3):
            store.save_message(StoredMessage(
                message_id=f"m{i}", session_id="s1", role="user",
                content=f"msg {i}", status="completed", task_id=None,
                error=None, created_at=f"2026-01-01T00:00:0{i}+00:00",
            ))
        sessions = store.list_sessions()
        assert sessions[0].message_count == 3
