import sqlite3
import threading

from apps.shell import agent_runtime
from apps.shell.agent.repositories.sqlite import (
    LockedConnection,
    LockedCursor,
    coerce_named_row,
    named_row_factory,
    open_locked_runtime_connection,
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

    assert conn.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()["timeout"] == 5000
    assert conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"] == "wal"
    conn.close()
