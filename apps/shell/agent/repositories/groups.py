"""Run group persistence for multi-agent and workflow executions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4


class RunGroupRepository:
    """Lifecycle store for run groups and their child run membership."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_run_group: Callable[[Any], dict[str, Any]],
        row_to_run: Callable[[Any], dict[str, Any]],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        redact_secrets: Callable[[Any], str],
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_run_group = row_to_run_group
        self._row_to_run = row_to_run
        self._now = now
        self._json_dump = json_dump
        self._redact_secrets = redact_secrets

    def list(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM run_groups ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit or 50), 200)),),
        ).fetchall()
        return {"ok": True, "run_groups": [self._row_to_run_group(row) for row in rows]}

    def get(self, run_group_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT * FROM run_groups WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_group_id)
        return self._row_to_run_group(row)

    def source(self, run_group_id: str) -> str:
        if not run_group_id:
            return ""
        row = self._conn.execute(
            "SELECT source FROM run_groups WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if row is None:
            return ""
        return str(row["source"] or "")

    def insert(self, *, title: str, source: str, workspace_dir: str = "") -> dict[str, Any]:
        run_group_id = f"run_group_{uuid4().hex[:12]}"
        now = self._now()
        self._conn.execute(
            """
            INSERT INTO run_groups (
                run_group_id, title, source, workspace_dir, status, summary,
                child_run_ids_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_group_id,
                self._redact_secrets(title)[:180],
                self._redact_secrets(source)[:80],
                self._redact_secrets(workspace_dir),
                "running",
                "",
                "[]",
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get(run_group_id)

    def append_run(self, run_group_id: str, run_id: str) -> None:
        if not run_group_id:
            return
        group = self.get(run_group_id)
        child_run_ids = [str(item) for item in group.get("child_run_ids") or [] if str(item)]
        if run_id not in child_run_ids:
            child_run_ids.append(run_id)
        self._conn.execute(
            """
            UPDATE run_groups
               SET child_run_ids_json=?, updated_at=?
             WHERE run_group_id=?
            """,
            (self._json_dump(child_run_ids), self._now(), run_group_id),
        )
        self._conn.commit()

    def update(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
    ) -> None:
        if not run_group_id:
            return
        current = self.get(run_group_id)
        self._conn.execute(
            """
            UPDATE run_groups
               SET status=?, summary=?, updated_at=?
             WHERE run_group_id=?
            """,
            (
                status or current["status"],
                self._redact_secrets(summary) if summary is not None else current["summary"],
                self._now(),
                run_group_id,
            ),
        )
        self._conn.commit()

    def runs(self, run_group_id: str) -> list[dict[str, Any]]:
        if not run_group_id:
            return []
        self._ensure_row_factory()
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE run_group_id=? ORDER BY created_at ASC",
            (run_group_id,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def remove_run_ids(self, run_group_id: str, run_ids: set[str]) -> None:
        if not run_group_id or not run_ids:
            return
        try:
            group = self.get(run_group_id)
        except KeyError:
            return
        child_run_ids = [
            str(item)
            for item in group.get("child_run_ids") or []
            if str(item) and str(item) not in run_ids
        ]
        remaining_count = self._conn.execute(
            "SELECT COUNT(*) AS count FROM runs WHERE run_group_id=?",
            (run_group_id,),
        ).fetchone()
        if not child_run_ids or int(remaining_count["count"] if remaining_count else 0) <= 0:
            self.delete(run_group_id)
            return
        self._conn.execute(
            """
            UPDATE run_groups
               SET child_run_ids_json=?, updated_at=?
             WHERE run_group_id=?
            """,
            (self._json_dump(child_run_ids), self._now(), run_group_id),
        )

    def delete(self, run_group_id: str) -> None:
        if not run_group_id:
            return
        self._conn.execute("DELETE FROM run_groups WHERE run_group_id=?", (run_group_id,))
