"""Tests for task-run link repository split out of the legacy runtime."""

from __future__ import annotations

import sqlite3

from apps.shell import agent_runtime
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository


def test_task_run_link_repository_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.TaskRunLinkRepository is TaskRunLinkRepository


def _pending_link_repository() -> tuple[sqlite3.Connection, TaskRunLinkRepository]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE task_run_links (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            run_status TEXT NOT NULL DEFAULT '',
            last_event_sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )

    def get_run(run_id: str) -> dict[str, object]:
        row = conn.execute(
            "SELECT run_id, kind, status, created_at, updated_at FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {
            **dict(row),
            "user_goal": f"goal:{run_id}",
            "result": f"question:{run_id}",
            "timeline": [{"event": "agent.plan.clarification_required"}],
        }

    return conn, TaskRunLinkRepository(
        conn,
        ensure_row_factory=lambda: None,
        get_run=get_run,
        now=lambda: "2026-07-20T00:00:00Z",
    )


def _insert_run_link(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    session_id: str,
    kind: str = "main_chat_run",
    status: str = "awaiting_user",
    link_status: str = "",
    created_at: str = "2026-07-20T00:00:00Z",
    updated_at: str = "2026-07-20T00:00:00Z",
) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, kind, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, kind, status, created_at, updated_at),
    )
    conn.execute(
        """
        INSERT INTO task_run_links (
            task_id, run_id, session_id, run_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, run_id, session_id, link_status, created_at, updated_at),
    )
    conn.commit()


def test_latest_awaiting_user_main_chat_for_session_returns_canonical_run() -> None:
    conn, repo = _pending_link_repository()
    try:
        _insert_run_link(
            conn,
            run_id="run-stale-completed",
            task_id="task-stale-completed",
            session_id="session-a",
            status="completed",
            link_status="awaiting_user",
            updated_at="2026-07-20T04:00:00Z",
        )
        _insert_run_link(
            conn,
            run_id="run-not-main-chat",
            task_id="task-not-main-chat",
            session_id="session-a",
            kind="agent_run",
            link_status="awaiting_user",
            updated_at="2026-07-20T03:00:00Z",
        )
        _insert_run_link(
            conn,
            run_id="run-a",
            task_id="task-a",
            session_id="session-a",
            link_status="failed",
            updated_at="2026-07-20T02:00:00Z",
        )
        _insert_run_link(
            conn,
            run_id="run-z",
            task_id="task-z",
            session_id="session-a",
            link_status="running",
            updated_at="2026-07-20T02:00:00Z",
        )
        _insert_run_link(
            conn,
            run_id="run-other-session",
            task_id="task-other-session",
            session_id="session-b",
            updated_at="2026-07-20T05:00:00Z",
        )

        pending = repo.latest_awaiting_user_main_chat_for_session(" session-a ")

        assert pending is not None
        assert pending["run_id"] == "run-z"
        assert pending["task_id"] == "task-z"
        assert pending["session_id"] == "session-a"
        assert pending["kind"] == "main_chat_run"
        assert pending["status"] == "awaiting_user"
        assert pending["timeline"] == [
            {"event": "agent.plan.clarification_required"}
        ]
    finally:
        conn.close()


def test_latest_awaiting_user_main_chat_for_session_rejects_empty_or_unknown_session() -> None:
    conn, repo = _pending_link_repository()
    try:
        _insert_run_link(
            conn,
            run_id="run-a",
            task_id="task-a",
            session_id="session-a",
        )

        assert repo.latest_awaiting_user_main_chat_for_session("") is None
        assert repo.latest_awaiting_user_main_chat_for_session("   ") is None
        assert repo.latest_awaiting_user_main_chat_for_session("session-b") is None
    finally:
        conn.close()
