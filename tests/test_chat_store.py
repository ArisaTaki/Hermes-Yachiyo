"""ChatStore 测试 — SQLite 持久化层"""

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
        store.save_message(StoredMessage(
            message_id="m1", session_id="s1", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        store.save_message(StoredMessage(
            message_id="m2", session_id="s2", role="user",
            content="hello", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:01+00:00",
        ))
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
        session = store.get_session("s1")
        assert session is not None
        assert session.title == "first"

    def test_list_sessions_hides_empty_sessions(self, store: ChatStore):
        store.create_session("empty")
        assert store.list_sessions() == []

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

    def test_get_session(self, store: ChatStore):
        store.create_session("s1", title="test session")
        store.save_message(StoredMessage(
            message_id="m1", session_id="s1", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        result = store.get_session("s1")
        assert result is not None
        assert result.session_id == "s1"
        assert result.title == "test session"
        assert result.message_count == 1

    def test_get_session_nonexistent(self, store: ChatStore):
        result = store.get_session("nonexistent")
        assert result is None

    def test_update_hermes_session_id(self, store: ChatStore):
        store.create_session("s1")
        store.update_hermes_session_id("s1", "hermes_abc")
        session = store.get_session("s1")
        assert session is not None
        assert session.hermes_session_id == "hermes_abc"

    def test_hermes_session_id_in_list_sessions(self, store: ChatStore):
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1", session_id="s1", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        store.update_hermes_session_id("s1", "hermes_xyz")
        sessions = store.list_sessions()
        assert sessions[0].hermes_session_id == "hermes_xyz"

    def test_set_session_title_if_empty(self, store: ChatStore):
        store.create_session("s1")

        assert store.set_session_title_if_empty("s1", "first title") is True
        assert store.set_session_title_if_empty("s1", "second title") is False

        session = store.get_session("s1")
        assert session is not None
        assert session.title == "first title"

    def test_list_sessions_uses_first_user_message_as_title_fallback(self, store: ChatStore):
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="请帮我总结这个项目的功能点",
            status="completed",
            task_id=None,
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))

        sessions = store.list_sessions()

        assert sessions[0].title == "请帮我总结这个项目的功能点"
