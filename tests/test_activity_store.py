from apps.core.activity_store import ActivityStore, redact_sensitive_text


def test_activity_store_persists_searches_and_redacts(tmp_path):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    try:
        event = store.record_event(
            session_id="s1",
            task_id="t1",
            tool_name="terminal",
            phase="tool_complete",
            title="运行脚本",
            detail="OPENAI_API_KEY=sk-secret123456789 command finished",
            status="completed",
            duration_seconds=1.25,
            metadata={"token": "ghp_secretsecretsecret", "safe": "value"},
        )

        assert event.detail == "OPENAI_API_KEY=[redacted] command finished"
        assert event.to_dict()["metadata"]["token"] == "[redacted]"
        assert store.list_events(query="脚本")[0].task_id == "t1"
        assert store.list_events(status="completed", tool="terminal")[0].session_id == "s1"
    finally:
        store.close()

    reopened = ActivityStore(db_path=str(db_path))
    try:
        events = reopened.latest_for_task("t1")
        assert len(events) == 1
        assert events[0].title == "运行脚本"
        assert events[0].duration_seconds == 1.25
    finally:
        reopened.close()


def test_redact_sensitive_text_handles_inline_tokens():
    assert redact_sensitive_text("token=abc123456 password:secret123") == "token=[redacted] password=[redacted]"
    assert redact_sensitive_text("sk-abc1234567890") == "[redacted]"


def test_activity_store_finalizes_in_flight_task_events(tmp_path):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    try:
        store.record_event(task_id="t1", title="Hermes 正在推理", status="running")
        store.record_event(task_id="t1", title="Hermes 正在整理推理", status="progress")
        store.record_event(task_id="t1", title="已失败的旧事件", status="failed")

        updated = store.finalize_task_events("t1", status="completed")
        events = store.latest_for_task("t1", limit=10)

        assert updated == 2
        assert [event.status for event in events].count("completed") == 2
        assert [event.status for event in events].count("failed") == 1
    finally:
        store.close()
