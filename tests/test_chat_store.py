"""ChatStore 测试 — SQLite 持久化层"""

import json
import sqlite3

import pytest

from apps.core.chat_store import ChatStore, StoredMessage, make_session_title


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
        assert sessions[0].session_id == "s2"

    def test_list_sessions_orders_by_latest_message_time(self, store: ChatStore):
        store.create_session("older")
        store.create_session("newer")
        store.save_message(StoredMessage(
            message_id="m1", session_id="newer", role="user",
            content="first", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        store.save_message(StoredMessage(
            message_id="m2", session_id="older", role="assistant",
            content="later", status="completed", task_id="t1",
            error=None, created_at="2026-01-01T00:00:05+00:00",
        ))

        sessions = store.list_sessions()

        assert [session.session_id for session in sessions] == ["older", "newer"]

    def test_list_sessions_limit_zero_returns_all(self, store: ChatStore):
        for index in range(25):
            session_id = f"s{index:02d}"
            store.create_session(session_id)
            store.save_message(StoredMessage(
                message_id=f"m{index:02d}",
                session_id=session_id,
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:{index:02d}+00:00",
            ))

        assert len(store.list_sessions()) == 20
        assert len(store.list_sessions(limit=0)) == 25

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

    def test_save_message_redacts_sensitive_content_error_and_json_payloads(self, store: ChatStore):
        store.create_session("s1")

        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="第一行\nOPENAI_API_KEY=sk-secret123456789\n第二行",
            status="failed",
            task_id="t1",
            error="Authorization: Bearer secret-value-123456",
            created_at="2026-01-01T00:00:00+00:00",
            attachments_json=json.dumps([{
                "kind": "image",
                "name": "截图\n原始",
                "token": "ghp_secretsecretsecret",
            }], ensure_ascii=False),
            metadata_json=json.dumps({
                "api_key": "sk-secret987654321",
                "nested": {
                    "safe": "保留\n换行",
                    "detail": "token=abc123456",
                },
            }, ensure_ascii=False),
        ))

        loaded = store.load_messages("s1")[0]
        attachments = json.loads(loaded.attachments_json)
        metadata = json.loads(loaded.metadata_json)
        raw = json.dumps(loaded.__dict__, ensure_ascii=False)

        assert "sk-secret" not in raw
        assert "ghp_secretsecretsecret" not in raw
        assert "secret-value-123456" not in raw
        assert loaded.content == "第一行\nOPENAI_API_KEY=[redacted]\n第二行"
        assert loaded.error == "Authorization=[redacted]"
        assert attachments[0]["name"] == "截图\n原始"
        assert attachments[0]["token"] == "[redacted]"
        assert metadata["api_key"] == "[redacted]"
        assert metadata["nested"]["safe"] == "保留\n换行"
        assert metadata["nested"]["detail"] == "token=[redacted]"

    def test_update_message_status_redacts_error(self, store: ChatStore):
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="test",
            status="pending",
            task_id="t1",
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))

        store.update_message_status("m1", "failed", error="password:secret123")

        assert store.load_messages("s1")[0].error == "password=[redacted]"

    def test_init_redacts_sensitive_legacy_rows_before_load(self, tmp_path):
        db_path = tmp_path / "legacy_chat.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    execution_session_id TEXT,
                    conversation_kind TEXT NOT NULL DEFAULT 'main',
                    runnable_id TEXT NOT NULL DEFAULT '',
                    runnable_name TEXT NOT NULL DEFAULT '',
                    run_group_id TEXT NOT NULL DEFAULT '',
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    avatar_url TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'completed',
                    task_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    session_id, title, created_at, execution_session_id, runnable_name,
                    participants_json, avatar_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "s1",
                    "OPENAI_API_KEY=sk-title-secret",
                    "2026-01-01T00:00:00+00:00",
                    "token=session-token-123456",
                    "Agent token=plain-agent-token",
                    json.dumps([{"name": "成员", "token": "ghp_secretsecretsecret"}], ensure_ascii=False),
                    "https://example.test/avatar.png?token=avatar-token-123456",
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    message_id, session_id, role, content, status, task_id, error,
                    created_at, attachments_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "m1",
                    "s1",
                    "user",
                    "第一行\napi_key=sk-legacy-secret\n第二行",
                    "failed",
                    "t1",
                    "password:legacy-password",
                    "2026-01-01T00:00:01+00:00",
                    json.dumps([{"kind": "image", "token": "ghp_oldoldoldoldold"}], ensure_ascii=False),
                    json.dumps({"nested": {"secret": "legacy-secret-value", "safe": "保留\n换行"}}, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        migrated = ChatStore(db_path=str(db_path))
        try:
            session = migrated.get_session("s1")
            message = migrated.load_messages("s1")[0]
            participants = json.loads(session.participants_json if session else "[]")
            attachments = json.loads(message.attachments_json)
            metadata = json.loads(message.metadata_json)
            raw_db = db_path.read_bytes().decode("utf-8", errors="ignore")

            assert session is not None
            assert "sk-title-secret" not in raw_db
            assert "sk-legacy-secret" not in raw_db
            assert "session-token-123456" not in raw_db
            assert "ghp_secretsecretsecret" not in raw_db
            assert "ghp_oldoldoldoldold" not in raw_db
            assert session.title == "OPENAI_API_KEY=[redacted]"
            assert session.execution_session_id == "token=[redacted]"
            assert session.runnable_name == "Agent token=[redacted]"
            assert participants[0]["token"] == "[redacted]"
            assert "avatar-token-123456" not in session.avatar_url
            assert message.content == "第一行\napi_key=[redacted]\n第二行"
            assert message.error == "password=[redacted]"
            assert attachments[0]["token"] == "[redacted]"
            assert metadata["nested"]["secret"] == "[redacted]"
            assert metadata["nested"]["safe"] == "保留\n换行"
        finally:
            migrated.close()

    def test_load_messages_limit_returns_latest_in_time_order(self, store: ChatStore):
        store.create_session("s1")
        for index in range(5):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id="s1",
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        loaded = store.load_messages("s1", limit=3)

        assert [message.message_id for message in loaded] == ["m2", "m3", "m4"]

    def test_load_messages_limit_zero_returns_all(self, store: ChatStore):
        store.create_session("s1")
        for index in range(5):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id="s1",
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        loaded = store.load_messages("s1", limit=0)

        assert [message.message_id for message in loaded] == ["m0", "m1", "m2", "m3", "m4"]

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

    def test_list_sessions_keeps_empty_group_sessions(self, store: ChatStore):
        store.create_session("empty")
        store.create_session("group", title="demo Channel")
        store.update_session_context(
            "group",
            conversation_kind="group",
            runnable_name="demo Channel",
            avatar_url="https://example.test/group.png",
            participants_json='[{"kind":"main","id":"main"},{"kind":"agent","id":"a1","name":"Agent One"}]',
        )

        sessions = store.list_sessions()

        assert [session.session_id for session in sessions] == ["group"]
        assert sessions[0].message_count == 0
        assert sessions[0].conversation_kind == "group"
        assert sessions[0].avatar_url == "https://example.test/group.png"

    def test_count_sessions_hides_empty_sessions(self, store: ChatStore):
        store.create_session("empty")
        store.create_session("visible")
        store.save_message(StoredMessage(
            message_id="m1", session_id="visible", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))

        assert store.count_sessions() == 1

    def test_count_sessions_includes_empty_group_sessions(self, store: ChatStore):
        store.create_session("group", title="demo Channel")
        store.update_session_context("group", conversation_kind="group", runnable_name="demo Channel")

        assert store.count_sessions() == 1

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

    def test_update_execution_session_id(self, store: ChatStore):
        store.create_session("s1")
        store.update_execution_session_id("s1", "native_abc")
        session = store.get_session("s1")
        assert session is not None
        assert session.execution_session_id == "native_abc"

    def test_execution_session_id_in_list_sessions(self, store: ChatStore):
        store.create_session("s1")
        store.save_message(StoredMessage(
            message_id="m1", session_id="s1", role="user",
            content="hi", status="completed", task_id=None,
            error=None, created_at="2026-01-01T00:00:00+00:00",
        ))
        store.update_execution_session_id("s1", "native_xyz")
        sessions = store.list_sessions()
        assert sessions[0].execution_session_id == "native_xyz"

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

    def test_search_sessions_matches_message_content(self, store: ChatStore):
        store.create_session("s1", title="普通标题")
        store.save_message(StoredMessage(
            message_id="m1",
            session_id="s1",
            role="user",
            content="这里提到了聊天记录搜索",
            status="completed",
            task_id=None,
            error=None,
            created_at="2026-01-01T00:00:00+00:00",
        ))
        store.create_session("s2", title="无关标题")
        store.save_message(StoredMessage(
            message_id="m2",
            session_id="s2",
            role="user",
            content="没有命中",
            status="completed",
            task_id=None,
            error=None,
            created_at="2026-01-01T00:00:01+00:00",
        ))

        results = store.search_sessions("聊天")

        assert [item.session.session_id for item in results] == ["s1"]
        assert results[0].match_message_id == "m1"
        assert results[0].match_content == "这里提到了聊天记录搜索"
        assert results[0].match_count == 1

    def test_search_sessions_limit_zero_returns_all_matches(self, store: ChatStore):
        for index in range(3):
            session_id = f"s{index}"
            store.create_session(session_id)
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id=session_id,
                role="user",
                content=f"共同关键词 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        assert len(store.search_sessions("共同关键词", limit=1)) == 1
        assert len(store.search_sessions("共同关键词", limit=0)) == 3

    def test_load_messages_around_returns_anchor_context(self, store: ChatStore):
        store.create_session("s1")
        for index in range(5):
            store.save_message(StoredMessage(
                message_id=f"m{index}",
                session_id="s1",
                role="user",
                content=f"消息 {index}",
                status="completed",
                task_id=None,
                error=None,
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            ))

        messages = store.load_messages_around("s1", "m2", before=1, after=1)

        assert [message.message_id for message in messages] == ["m1", "m2", "m3"]

    def test_make_session_title_uses_first_user_sentence(self):
        assert make_session_title("中午好，我点了一份潮汕牛肉饭哦") == "中午好，我点了一份潮汕牛肉饭哦"
        assert make_session_title("能否帮我打开v2ex？然后看一下热门帖子") == "能否帮我打开v2ex？"

    def test_make_session_title_ignores_leading_mentions(self):
        assert make_session_title('@Helper 做个总结') == "做个总结"
        assert make_session_title('@"Coding Agent" 你好') == "你好"
        assert make_session_title('@主模型：总结一下当前状态') == "总结一下当前状态"
