from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


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
        self._transaction_local = threading.local()

    @property
    def in_managed_transaction(self) -> bool:
        return int(getattr(self._transaction_local, "depth", 0) or 0) > 0

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[LockedConnection]:
        """Run one unit of work while excluding writes from other threads.

        Nested scopes join the outer transaction. Repository ``commit()`` calls
        are delayed until the outer scope exits; any nested rollback or exception
        marks the whole unit of work for rollback.
        """

        depth = int(getattr(self._transaction_local, "depth", 0) or 0)
        if depth > 0:
            self._transaction_local.depth = depth + 1
            try:
                yield self
            except BaseException:
                self._transaction_local.rollback_only = True
                raise
            finally:
                self._transaction_local.depth = depth
            return

        self._lock.acquire()
        try:
            if self._conn.in_transaction:
                raise RuntimeError(
                    "cannot start a managed transaction inside an unmanaged transaction"
                )
            self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            self._transaction_local.depth = 1
            self._transaction_local.rollback_only = False
            try:
                yield self
            except BaseException:
                self._transaction_local.rollback_only = True
                raise
            finally:
                rollback_only = bool(
                    getattr(self._transaction_local, "rollback_only", False)
                )
                if self._conn.in_transaction:
                    if rollback_only:
                        self._conn.rollback()
                    else:
                        self._conn.commit()
        finally:
            for attribute in ("depth", "rollback_only"):
                try:
                    delattr(self._transaction_local, attribute)
                except AttributeError:
                    pass
            self._lock.release()

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
            if self.in_managed_transaction:
                raise RuntimeError(
                    "executescript is not allowed inside a managed transaction"
                )
            return LockedCursor(self._conn.executescript(*args, **kwargs), self._lock)

    def commit(self) -> None:
        with self._lock:
            if self.in_managed_transaction:
                return
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            if self.in_managed_transaction:
                self._transaction_local.rollback_only = True
                return
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@contextmanager
def repository_transaction(conn: Any) -> Iterator[Any]:
    """Use the production UoW API while retaining raw sqlite test compatibility."""

    managed_transaction = getattr(conn, "transaction", None)
    if callable(managed_transaction):
        with managed_transaction():
            yield conn
        return
    if bool(getattr(conn, "in_transaction", False)):
        raise RuntimeError(
            "cannot start repository transaction inside a pre-existing raw sqlite transaction"
        )
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


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
