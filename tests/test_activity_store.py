import apps.shell.activity_api as activity_api_mod
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


def test_activity_store_key_only_filters_noisy_reasoning(tmp_path):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    try:
        store.record_event(task_id="t1", phase="reasoning", title="Hermes 正在推理", status="running")
        store.record_event(task_id="t1", phase="reasoning", title="Hermes 已整理推理", status="completed")
        store.record_event(task_id="t1", phase="tool_progress", title="正在执行终端", status="running")
        store.record_event(task_id="t1", phase="task_complete", title="Yachiyo 回复完成", status="completed")

        events = store.list_events(task_id="t1", key_only=True)

        assert len(events) == 1
        assert events[0].phase == "task_complete"
    finally:
        store.close()


def test_activity_detail_returns_unfiltered_task_trace(tmp_path, monkeypatch):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    monkeypatch.setattr(activity_api_mod, "get_activity_store", lambda: store)
    try:
        reasoning = store.record_event(
            task_id="t1",
            phase="reasoning",
            title="Hermes 正在推理",
            status="running",
        )
        complete = store.record_event(
            task_id="t1",
            phase="task_complete",
            title="Yachiyo 回复完成",
            status="completed",
        )

        listed = activity_api_mod.list_activity_events()
        detail = activity_api_mod.get_activity_event_detail(complete.event_id)

        assert [event["event_id"] for event in listed["events"]] == [complete.event_id]
        assert detail["ok"] is True
        assert detail["event"]["event_id"] == complete.event_id
        assert [event["event_id"] for event in detail["trace"]] == [
            reasoning.event_id,
            complete.event_id,
        ]
    finally:
        store.close()


def test_activity_api_normalizes_status_filters_and_deletes_event(tmp_path, monkeypatch):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    monkeypatch.setattr(activity_api_mod, "get_activity_store", lambda: store)
    try:
        success = store.record_event(
            task_id="t1",
            phase="tool_complete",
            title="工具成功",
            status="success",
        )
        failed = store.record_event(
            task_id="t2",
            phase="task_failed",
            title="任务异常",
            status="error",
        )
        store.record_event(
            task_id="t3",
            phase="tool_start",
            title="工具运行中",
            status="progress",
        )

        listed = activity_api_mod.list_activity_events()
        completed = activity_api_mod.list_activity_events(status="completed")
        failed_result = activity_api_mod.list_activity_events(status="failed")

        assert set(listed["statuses"]) == {"running", "completed", "failed"}
        assert completed["events"][0]["event_id"] == success.event_id
        assert completed["events"][0]["status"] == "completed"
        assert completed["events"][0]["raw_status"] == "success"
        assert failed_result["events"][0]["event_id"] == failed.event_id
        assert failed_result["events"][0]["status"] == "failed"
        assert failed_result["events"][0]["raw_status"] == "error"

        deleted = activity_api_mod.delete_activity_event(success.event_id)
        missing = activity_api_mod.get_activity_event_detail(success.event_id)

        assert deleted == {"ok": True, "deleted": True, "event_id": success.event_id}
        assert missing["ok"] is False

        bulk = activity_api_mod.delete_activity_events([failed.event_id, "missing"])
        remaining = activity_api_mod.list_activity_events()

        assert bulk == {"ok": True, "deleted": 1, "requested": 2}
        assert all(event["event_id"] != failed.event_id for event in remaining["events"])
    finally:
        store.close()
