from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


def named_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        column[0]: row[index]
        for index, column in enumerate(cursor.description or ())
        if index < len(row)
    }


class LockedCursor:
    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock) -> None:
        self._cursor = cursor
        self._lock = lock

    @property
    def description(self) -> Any:
        return self._cursor.description

    def fetchone(self) -> Any:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        with self._lock:
            return self._cursor.fetchall()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class LockedConnection:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    @property
    def row_factory(self) -> Any:
        with self._lock:
            return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        with self._lock:
            self._conn.row_factory = value

    def execute(self, *args: Any, **kwargs: Any) -> LockedCursor:
        with self._lock:
            return LockedCursor(self._conn.execute(*args, **kwargs), self._lock)

    def executescript(self, *args: Any, **kwargs: Any) -> LockedCursor:
        with self._lock:
            return LockedCursor(self._conn.executescript(*args, **kwargs), self._lock)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def open_locked_runtime_connection(
    db_path: Path | str,
    lock: threading.RLock,
) -> LockedConnection:
    raw_conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    raw_conn.execute("PRAGMA foreign_keys=ON")
    raw_conn.execute("PRAGMA journal_mode=WAL")
    raw_conn.execute("PRAGMA busy_timeout=5000")
    return LockedConnection(raw_conn, lock)


def coerce_named_row(row: Any, description: Any = None) -> Any:
    if row is None or isinstance(row, dict):
        return row
    if isinstance(row, sqlite3.Row):
        if description:
            return {
                column[0]: row[index]
                for index, column in enumerate(description)
                if index < len(row)
            }
        return {key: row[key] for key in row.keys()}
    if description:
        return {
            column[0]: row[index]
            for index, column in enumerate(description)
            if index < len(row)
        }
    return row
