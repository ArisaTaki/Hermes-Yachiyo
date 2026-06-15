"""Studio deletion tombstone persistence for Agent Studio managed items."""

from __future__ import annotations

from typing import Any, Callable


class StudioDeletionRepository:
    """Tracks user-deleted Studio items so sync jobs do not restore them."""

    def __init__(
        self,
        conn: Any,
        *,
        now: Callable[[], str],
    ) -> None:
        self._conn = conn
        self._now = now

    def record(self, item_type: str, item_key: str) -> None:
        clean_key = str(item_key or "").strip()
        if not clean_key:
            return
        self._conn.execute(
            """
            INSERT INTO studio_deletions (item_type, item_key, deleted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(item_type, item_key) DO UPDATE SET deleted_at=excluded.deleted_at
            """,
            (item_type, clean_key, self._now()),
        )

    def clear(self, item_type: str, item_key: str) -> None:
        self._conn.execute(
            "DELETE FROM studio_deletions WHERE item_type=? AND item_key=?",
            (item_type, str(item_key or "").strip()),
        )

    def has(self, item_type: str, item_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM studio_deletions WHERE item_type=? AND item_key=?",
            (item_type, str(item_key or "").strip()),
        ).fetchone()
        return row is not None
