import sqlite3
import threading

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.sqlite import (
    LockedConnection,
    LockedCursor,
    coerce_named_row,
    named_row_factory,
    open_locked_runtime_connection,
    repository_transaction,
)


def test_agent_runtime_exports_sqlite_repository_helpers_for_compatibility() -> None:
    assert agent_runtime._LockedConnection is LockedConnection
    assert agent_runtime._LockedCursor is LockedCursor
    assert agent_runtime._named_row_factory is named_row_factory
    assert agent_runtime._open_runtime_sqlite_connection is open_locked_runtime_connection


def test_locked_connection_preserves_named_rows_and_coercion() -> None:
    raw = sqlite3.connect(":memory:")
    conn = LockedConnection(raw, threading.RLock())
    conn.row_factory = named_row_factory
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("INSERT INTO items (name) VALUES (?)", ("Yachiyo",))
    row = conn.execute("SELECT id, name FROM items").fetchone()

    assert row == {"id": 1, "name": "Yachiyo"}
    assert coerce_named_row(row) == row

    raw.row_factory = sqlite3.Row
    sqlite_row = raw.execute("SELECT id, name FROM items").fetchone()
    assert coerce_named_row(sqlite_row) == {"id": 1, "name": "Yachiyo"}
    conn.close()


def test_open_locked_runtime_connection_applies_runtime_pragmas(tmp_path) -> None:
    conn = open_locked_runtime_connection(tmp_path / "runtime.db", threading.RLock())
    conn.row_factory = named_row_factory

    assert conn.isolation_level is None
    assert conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()["timeout"] == 5000
    assert conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"] == "wal"
    conn.close()


def test_open_locked_runtime_connection_does_not_leave_implicit_transactions(tmp_path) -> None:
    conn = open_locked_runtime_connection(tmp_path / "runtime.db", threading.RLock())

    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("INSERT INTO items (name) VALUES (?)", ("Yachiyo",))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO items (name) VALUES (?)", ("Runtime",))
        conn.commit()
    finally:
        if conn.in_transaction:
            conn.rollback()

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    conn.close()


def test_runtime_connection_allows_event_append_after_plain_write(tmp_path) -> None:
    lock = threading.RLock()
    conn = open_locked_runtime_connection(tmp_path / "runtime.db", lock)
    conn.row_factory = named_row_factory
    conn.execute("CREATE TABLE plain_writes (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            visibility TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute("INSERT INTO plain_writes (name) VALUES (?)", ("before-event",))
    repo = RunEventRepository(
        conn,
        lock,
        now=lambda: "2026-07-04T00:00:00Z",
        json_dump=lambda value: "{}",
        json_load=lambda _text, fallback: fallback,
    )

    event = repo.append("run-1", "agent.run.started", {"goal": "test"})

    assert event["sequence"] == 1
    assert conn.execute("SELECT COUNT(*) AS count FROM run_events").fetchone()["count"] == 1
    conn.close()


def test_run_event_append_rolls_back_event_and_cursor_when_cursor_projection_crashes(
    tmp_path,
) -> None:
    lock = threading.RLock()
    conn = open_locked_runtime_connection(tmp_path / "runtime-event-cursor-crash.db", lock)
    conn.row_factory = named_row_factory
    conn.executescript(
        """
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            visibility TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE event_cursors (
            run_id TEXT PRIMARY KEY,
            sequence INTEGER NOT NULL
        );
        """
    )

    def crash_after_cursor_write(run_id: str, *, sequence: int) -> None:
        conn.execute(
            "INSERT INTO event_cursors (run_id, sequence) VALUES (?, ?)",
            (run_id, sequence),
        )
        raise RuntimeError("injected_event_cursor_crash")

    repo = RunEventRepository(
        conn,
        lock,
        now=lambda: "2026-07-12T00:00:00Z",
        json_dump=lambda _value: "{}",
        json_load=lambda _text, fallback: fallback,
        sync_event_cursor=crash_after_cursor_write,
    )

    with pytest.raises(RuntimeError, match="injected_event_cursor_crash"):
        repo.append("run-cursor-crash", "agent.run.started", {"status": "running"})

    assert conn.execute(
        "SELECT COUNT(*) AS count FROM run_events"
    ).fetchone()["count"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS count FROM event_cursors"
    ).fetchone()["count"] == 0
    conn.close()


def test_run_event_repository_conditionally_appends_against_run_version(tmp_path) -> None:
    lock = threading.RLock()
    conn = open_locked_runtime_connection(tmp_path / "runtime-event-fence.db", lock)
    conn.row_factory = named_row_factory
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            schema_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            visibility TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO runs (run_id, status, updated_at) VALUES (?, ?, ?)",
        ("run-fenced-event", "cancelled", "version-2"),
    )
    repo = RunEventRepository(
        conn,
        lock,
        now=lambda: "2026-07-12T00:00:00Z",
        json_dump=lambda _value: "{}",
        json_load=lambda _text, fallback: fallback,
    )

    stale = repo.append(
        "run-fenced-event",
        "workflow.run.child_resumed",
        {"status": "running"},
        expected_status="running",
        expected_updated_at="version-1",
    )

    assert stale is None
    assert conn.execute("SELECT COUNT(*) AS count FROM run_events").fetchone()["count"] == 0
    conn.close()


def test_locked_connection_nested_transaction_delays_repository_commits(tmp_path) -> None:
    db_path = tmp_path / "nested-uow.db"
    conn = open_locked_runtime_connection(db_path, threading.RLock())
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    observer = sqlite3.connect(db_path)

    with conn.transaction():
        conn.execute("INSERT INTO items (name) VALUES (?)", ("outer",))
        conn.commit()
        with conn.transaction():
            conn.execute("INSERT INTO items (name) VALUES (?)", ("nested",))
            conn.commit()
        assert observer.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0

    assert observer.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    observer.close()
    conn.close()


def test_locked_connection_nested_rollback_marks_whole_unit_of_work(tmp_path) -> None:
    db_path = tmp_path / "nested-rollback-uow.db"
    conn = open_locked_runtime_connection(db_path, threading.RLock())
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")

    with conn.transaction():
        conn.execute("INSERT INTO items (name) VALUES (?)", ("outer",))
        with conn.transaction():
            conn.execute("INSERT INTO items (name) VALUES (?)", ("nested",))
            conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    conn.close()


def test_locked_connection_outer_exception_rolls_back_unit_of_work(tmp_path) -> None:
    conn = open_locked_runtime_connection(tmp_path / "exception-uow.db", threading.RLock())
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")

    with pytest.raises(RuntimeError, match="injected_outer_crash"):
        with conn.transaction():
            conn.execute("INSERT INTO items (name) VALUES (?)", ("uncommitted",))
            raise RuntimeError("injected_outer_crash")

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    conn.close()


def test_locked_connection_transaction_excludes_cross_thread_writes(tmp_path) -> None:
    conn = open_locked_runtime_connection(tmp_path / "thread-uow.db", threading.RLock())
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    attempted = threading.Event()
    finished = threading.Event()
    worker_errors: list[BaseException] = []

    def write_from_worker() -> None:
        attempted.set()
        try:
            conn.execute("INSERT INTO items (name) VALUES (?)", ("worker",))
            conn.commit()
        except BaseException as exc:  # pragma: no cover - asserted below
            worker_errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=write_from_worker)
    with conn.transaction():
        conn.execute("INSERT INTO items (name) VALUES (?)", ("outer-before",))
        worker.start()
        assert attempted.wait(timeout=1)
        assert not finished.wait(timeout=0.05)
        conn.execute("INSERT INTO items (name) VALUES (?)", ("outer-after",))

    worker.join(timeout=1)
    assert not worker.is_alive()
    assert worker_errors == []
    assert [
        row[0]
        for row in conn.execute("SELECT name FROM items ORDER BY id").fetchall()
    ] == ["outer-before", "outer-after", "worker"]
    conn.close()


def test_locked_connection_rejects_executescript_inside_managed_transaction(
    tmp_path,
) -> None:
    conn = open_locked_runtime_connection(
        tmp_path / "executescript-uow.db",
        threading.RLock(),
    )
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")

    with conn.transaction():
        conn.execute("INSERT INTO items (name) VALUES ('before-guard')")
        with pytest.raises(RuntimeError, match="executescript.*managed transaction"):
            conn.executescript("INSERT INTO items (name) VALUES ('must-not-commit');")

    assert [
        row[0]
        for row in conn.execute("SELECT name FROM items ORDER BY id").fetchall()
    ] == ["before-guard"]
    conn.close()


def test_raw_repository_transaction_rejects_preexisting_caller_transaction() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute("INSERT INTO items (name) VALUES ('caller-owned')")
    assert conn.in_transaction is True

    with pytest.raises(RuntimeError, match="pre-existing raw sqlite transaction"):
        with repository_transaction(conn):
            conn.execute("INSERT INTO items (name) VALUES ('repository-owned')")

    assert conn.in_transaction is True
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    conn.close()
