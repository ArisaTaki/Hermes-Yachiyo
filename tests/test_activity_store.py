from datetime import datetime, timedelta, timezone
import sqlite3

import apps.shell.activity_api as activity_api_mod
from apps.core.activity_store import ActivityRetentionPolicy, ActivityStore, redact_sensitive_text


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
        assert store.list_events(query="s1")[0].event_id == event.event_id
        assert store.list_events(query="value")[0].event_id == event.event_id
        assert store.list_events(status="completed", tool="terminal")[0].session_id == "s1"
    finally:
        store.close()

    reopened = ActivityStore(db_path=str(db_path))
    try:
        events = reopened.latest_for_task("t1")
        assert len(events) == 1
        assert events[0].title == "运行脚本"
        assert events[0].duration_seconds == 1.25
        assert events[0].visibility == "user"
    finally:
        reopened.close()


def test_activity_store_persists_internal_visibility_and_migrates_legacy_rows(tmp_path):
    db_path = tmp_path / "activity.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE activity_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                tool_name TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                duration_seconds REAL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            INSERT INTO activity_events (
                event_id, task_id, tool_name, phase, title, status, created_at
            ) VALUES (
                'legacy-event', 'task-1', 'terminal', 'tool_start', 'Legacy', 'running',
                '2026-07-12T00:00:00+00:00'
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    store = ActivityStore(db_path=str(db_path))
    try:
        internal = store.record_event(
            task_id="task-1",
            tool_name="desktop.verify",
            phase="tool_complete",
            title="Verifier",
            status="completed",
            visibility="internal",
        )
        events = {event.event_id: event for event in store.list_events(limit=10)}

        assert events["legacy-event"].visibility == "user"
        assert events[internal.event_id].visibility == "internal"
        assert events[internal.event_id].to_dict()["visibility"] == "internal"
    finally:
        store.close()


def test_redact_sensitive_text_handles_inline_tokens():
    assert redact_sensitive_text("token=abc123456 password:secret123") == "token=[redacted] password=[redacted]"
    assert redact_sensitive_text("sk-abc1234567890") == "[redacted]"


def test_redact_sensitive_text_hides_raw_tool_call_drafts():
    text = (
        "我检查一下 <tool_call><function=browser_cdp>"
        "<parameter=method>Runtime.evaluate</parameter></function></tool_call>"
    )

    redacted = redact_sensitive_text(text)

    assert "tool_call" not in redacted
    assert "browser_cdp" not in redacted
    assert "工具调用草稿已隐藏" in redacted


def test_activity_store_finalizes_in_flight_task_events(tmp_path):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    try:
        store.record_event(task_id="t1", title="Native Agent 正在推理", status="running")
        store.record_event(task_id="t1", title="Native Agent 正在整理推理", status="progress")
        store.record_event(task_id="t1", title="已失败的旧事件", status="failed")

        updated = store.finalize_task_events("t1", status="completed")
        events = store.latest_for_task("t1", limit=10)

        assert updated == 2
        assert [event.status for event in events].count("completed") == 2
        assert [event.status for event in events].count("failed") == 1
    finally:
        store.close()


def test_activity_store_reconciles_only_authoritative_interrupted_tasks(tmp_path):
    store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    cutoff = "2026-07-12T00:00:00+00:00"
    try:
        for event_id, task_id, status, created_at in (
            ("linked-completed", "task-completed", "running", "2026-07-11T23:00:00+00:00"),
            ("linked-failed", "task-failed", "progress", "2026-07-11T23:01:00+00:00"),
            ("linked-approval", "task-approval", "running", "2026-07-11T23:02:00+00:00"),
            ("orphan", "task-orphan", "pending", "2026-07-11T23:03:00+00:00"),
            ("future", "task-future", "running", "2026-07-12T01:00:00+00:00"),
        ):
            store.record_event(
                event_id=event_id,
                task_id=task_id,
                phase="tool_progress",
                status=status,
                created_at=created_at,
            )

        assert set(store.list_interrupted_task_ids(cutoff)) == {
            "task-completed",
            "task-failed",
            "task-approval",
            "task-orphan",
        }
        assert store.reconcile_interrupted_tasks(
            cutoff,
            terminal_status_by_task={
                "task-completed": "completed",
                "task-failed": "failed",
            },
            orphan_task_ids={"task-orphan"},
        ) == 3

        events = {event.event_id: event for event in store.list_events(limit=20)}
        assert events["linked-completed"].status == "completed"
        assert events["linked-failed"].status == "failed"
        assert events["linked-approval"].status == "running"
        assert events["orphan"].status == "failed"
        assert events["future"].status == "running"
        assert events["linked-completed"].to_dict()["metadata"][
            "recovery_reason"
        ] == "runtime_status_reconciled"
        assert events["orphan"].to_dict()["metadata"]["recovery_reason"] == (
            "runtime_restarted"
        )
        assert store.reconcile_interrupted_tasks(
            cutoff,
            terminal_status_by_task={
                "task-completed": "completed",
                "task-failed": "failed",
            },
            orphan_task_ids={"task-orphan"},
        ) == 0
    finally:
        store.close()


def test_activity_store_key_only_filters_noisy_reasoning(tmp_path):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    try:
        store.record_event(task_id="t1", phase="reasoning", title="Native Agent 正在推理", status="running")
        store.record_event(task_id="t1", phase="reasoning", title="Native Agent 已整理推理", status="completed")
        store.record_event(task_id="t1", phase="tool_progress", title="正在执行终端", status="running")
        store.record_event(task_id="t1", phase="task_complete", title="Yachiyo 回复完成", status="completed")

        events = store.list_events(task_id="t1", key_only=True)

        assert len(events) == 1
        assert events[0].phase == "task_complete"
    finally:
        store.close()


def test_activity_store_retention_keeps_key_and_trace_budgets_separate(tmp_path):
    db_path = tmp_path / "activity.db"
    policy = ActivityRetentionPolicy(
        key_event_limit=2,
        trace_event_limit=3,
        key_retention_days=90,
        trace_retention_days=30,
        cleanup_interval_writes=0,
    )
    store = ActivityStore(db_path=str(db_path), retention_policy=policy)
    base_time = datetime.now(timezone.utc)
    try:
        for index in range(5):
            store.record_event(
                task_id="trace",
                phase="reasoning",
                title=f"trace {index}",
                status="running",
                created_at=(base_time + timedelta(seconds=index)).isoformat(),
            )
        for index in range(4):
            store.record_event(
                task_id="key",
                phase="task_complete",
                title=f"key {index}",
                status="completed",
                created_at=(base_time + timedelta(minutes=1, seconds=index)).isoformat(),
            )

        result = store.prune_retention()
        events = store.list_events(limit=20, key_only=False)

        assert result["deleted"] == 4
        assert [event.title for event in events if event.task_id == "key"] == ["key 3", "key 2"]
        assert [event.title for event in events if event.task_id == "trace"] == ["trace 4", "trace 3", "trace 2"]
        assert result["total"] == 5
        assert result["used_bytes"] > 0
    finally:
        store.close()


def test_activity_store_retention_removes_old_trace_before_key_events(tmp_path):
    db_path = tmp_path / "activity.db"
    policy = ActivityRetentionPolicy(
        key_event_limit=100,
        trace_event_limit=100,
        key_retention_days=90,
        trace_retention_days=30,
        cleanup_interval_writes=0,
    )
    store = ActivityStore(db_path=str(db_path), retention_policy=policy)
    now = datetime.now(timezone.utc)
    try:
        old_trace = store.record_event(
            task_id="t1",
            phase="reasoning",
            title="旧详细过程",
            status="running",
            created_at=(now - timedelta(days=31)).isoformat(),
        )
        old_but_kept_key = store.record_event(
            task_id="t2",
            phase="task_failed",
            title="仍需保留的失败任务",
            status="failed",
            created_at=(now - timedelta(days=60)).isoformat(),
        )
        too_old_key = store.record_event(
            task_id="t3",
            phase="task_complete",
            title="过期关键事件",
            status="completed",
            created_at=(now - timedelta(days=91)).isoformat(),
        )

        result = store.prune_retention()
        remaining_ids = {event.event_id for event in store.list_events(limit=20, key_only=False)}

        assert result["deleted"] == 2
        assert old_trace.event_id not in remaining_ids
        assert too_old_key.event_id not in remaining_ids
        assert old_but_kept_key.event_id in remaining_ids
    finally:
        store.close()


def test_activity_store_auto_prunes_after_write_interval(tmp_path):
    db_path = tmp_path / "activity.db"
    policy = ActivityRetentionPolicy(
        key_event_limit=100,
        trace_event_limit=1,
        key_retention_days=90,
        trace_retention_days=30,
        cleanup_interval_writes=2,
    )
    store = ActivityStore(db_path=str(db_path), retention_policy=policy)
    base_time = datetime.now(timezone.utc)
    try:
        store.record_event(
            task_id="trace",
            phase="reasoning",
            title="trace 1",
            status="running",
            created_at=(base_time + timedelta(seconds=1)).isoformat(),
        )
        store.record_event(
            task_id="trace",
            phase="reasoning",
            title="trace 2",
            status="running",
            created_at=(base_time + timedelta(seconds=2)).isoformat(),
        )

        events = store.list_events(task_id="trace", limit=10, key_only=False)

        assert [event.title for event in events] == ["trace 2"]
    finally:
        store.close()


def test_activity_store_prunes_on_startup(tmp_path):
    db_path = tmp_path / "activity.db"
    policy = ActivityRetentionPolicy(
        key_event_limit=100,
        trace_event_limit=100,
        key_retention_days=90,
        trace_retention_days=30,
        cleanup_interval_writes=0,
    )
    store = ActivityStore(db_path=str(db_path), retention_policy=policy)
    try:
        store.record_event(
            task_id="trace",
            phase="reasoning",
            title="启动时应清理",
            status="running",
            created_at=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        )
    finally:
        store.close()

    reopened = ActivityStore(db_path=str(db_path), retention_policy=policy)
    try:
        assert reopened.list_events(limit=10, key_only=False) == []
    finally:
        reopened.close()


def test_activity_detail_returns_unfiltered_task_trace(tmp_path, monkeypatch):
    db_path = tmp_path / "activity.db"
    store = ActivityStore(db_path=str(db_path))
    monkeypatch.setattr(activity_api_mod, "get_activity_store", lambda: store)
    try:
        reasoning = store.record_event(
            task_id="t1",
            phase="reasoning",
            title="Native Agent 正在推理",
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
