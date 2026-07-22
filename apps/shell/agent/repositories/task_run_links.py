"""Product task to native run link persistence."""

from __future__ import annotations

from typing import Any, Callable


class TaskRunLinkRepository:
    """Persistence boundary for product Task to native Run links."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        get_run: Callable[[str], dict[str, Any]],
        now: Callable[[], str],
        error_type: type[Exception] = RuntimeError,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._get_run = get_run
        self._now = now
        self._error_type = error_type

    def link(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        clean_task_id = str(task_id or "").strip()
        clean_run_id = str(run_id or "").strip()
        if not clean_task_id or not clean_run_id:
            raise self._error_type("Task 与 Run 映射缺少 task_id 或 run_id")
        run = self._get_run(clean_run_id)
        latest_sequence = self.latest_event_sequence(clean_run_id)
        now = self._now()
        self._conn.execute(
            """
            INSERT INTO task_run_links (
                task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                run_id=excluded.run_id,
                session_id=excluded.session_id,
                run_status=excluded.run_status,
                last_event_sequence=excluded.last_event_sequence,
                updated_at=excluded.updated_at
            """,
            (
                clean_task_id,
                clean_run_id,
                str(session_id or ""),
                str(run.get("status") or ""),
                latest_sequence,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get(clean_task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
              FROM task_run_links
             WHERE task_id=?
            """,
            (str(task_id or "").strip(),),
        ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_link(row)

    def for_run(self, run_id: str) -> dict[str, Any] | None:
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT task_id, run_id, session_id, run_status, last_event_sequence, created_at, updated_at
              FROM task_run_links
             WHERE run_id=?
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (str(run_id or "").strip(),),
        ).fetchone()
        return self._row_to_link(row) if row is not None else None

    def latest_awaiting_user_main_chat_for_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest canonical Main Chat Run awaiting this session."""
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return None
        self._ensure_row_factory()
        row = self._conn.execute(
            """
            SELECT links.task_id, links.run_id, links.session_id
              FROM task_run_links AS links
              JOIN runs ON runs.run_id=links.run_id
             WHERE links.session_id=?
               AND runs.kind='main_chat_run'
               AND runs.status='awaiting_user'
             ORDER BY runs.updated_at DESC,
                      runs.created_at DESC,
                      links.updated_at DESC,
                      links.created_at DESC,
                      links.run_id DESC,
                      links.task_id DESC
             LIMIT 1
            """,
            (clean_session_id,),
        ).fetchone()
        if row is None:
            return None

        run = dict(self._get_run(str(row["run_id"] or "")))
        if (
            str(run.get("kind") or "") != "main_chat_run"
            or str(run.get("status") or "") != "awaiting_user"
        ):
            return None
        run.update(
            {
                "task_id": str(row["task_id"] or ""),
                "session_id": str(row["session_id"] or ""),
            }
        )
        return run

    def projections_for_tasks(
        self,
        task_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Return canonical Run state for durable product task links."""
        clean_task_ids = list(
            dict.fromkeys(
                str(task_id or "").strip()
                for task_id in task_ids
                if str(task_id or "").strip()
            )
        )
        if not clean_task_ids:
            return {}
        self._ensure_row_factory()
        projections: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(clean_task_ids), 400):
            batch = clean_task_ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"""
                SELECT links.task_id, links.run_id, links.session_id,
                       runs.status, runs.result, runs.updated_at
                  FROM task_run_links AS links
                  JOIN runs ON runs.run_id=links.run_id
                 WHERE links.task_id IN ({placeholders})
                """,
                tuple(batch),
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"] or "")
                projections[task_id] = {
                    "task_id": task_id,
                    "run_id": str(row["run_id"] or ""),
                    "session_id": str(row["session_id"] or ""),
                    "status": str(row["status"] or ""),
                    "result": str(row["result"] or ""),
                    "updated_at": str(row["updated_at"] or ""),
                }
        return projections

    def latest_event_sequence(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM run_events WHERE run_id=?",
            (str(run_id or "").strip(),),
        ).fetchone()
        return int(row["last_sequence"] if row is not None else 0)

    def sync_projection(
        self,
        run_id: str,
        *,
        status: str | None = None,
        last_event_sequence: int | None = None,
    ) -> None:
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("run_status=?")
            params.append(str(status or ""))
        if last_event_sequence is not None:
            updates.append("last_event_sequence=MAX(last_event_sequence, ?)")
            params.append(max(0, int(last_event_sequence or 0)))
        if not updates:
            return
        updates.append("updated_at=?")
        params.append(self._now())
        params.append(clean_run_id)
        self._conn.execute(
            f"UPDATE task_run_links SET {', '.join(updates)} WHERE run_id=?",
            tuple(params),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_link(row: Any) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "run_id": str(row["run_id"]),
            "session_id": str(row["session_id"] or ""),
            "run_status": str(row["run_status"] or ""),
            "last_event_sequence": int(row["last_event_sequence"] or 0),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"] or row["created_at"]),
        }
