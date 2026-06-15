"""FutureTask trigger orchestration for scheduled Agent runs."""

from __future__ import annotations

import time
from typing import Any, Callable

from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.runtime.errors import AgentRuntimeError


_FUTURE_TASK_STATUSES = {"scheduled", "triggered", "cancelled", "failed"}


class FutureTaskTriggerScheduler:
    """Projects due FutureTasks into runnable Agent or Workflow runs."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        create_run_for_runnable: Callable[..., dict[str, Any]],
        future_task_store: Callable[..., AgentFutureTaskStore],
        now: Callable[[], str],
        redact_secrets: Callable[[Any], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._create_run_for_runnable = create_run_for_runnable
        self._future_task_store = future_task_store
        self._now = now
        self._redact_secrets = redact_secrets
        self._error_type = error_type

    def trigger_due_future_tasks(
        self,
        *,
        now_epoch: float | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        current = time.time() if now_epoch is None else float(now_epoch)
        rows = self._conn.execute(
            """
            SELECT *
              FROM future_tasks
             WHERE status='scheduled' AND scheduled_at_epoch<=?
             ORDER BY scheduled_at_epoch ASC
             LIMIT ?
            """,
            (current, max(1, min(int(limit or 20), 100))),
        ).fetchall()
        triggered: list[dict[str, Any]] = []
        for row in rows:
            future_task = AgentFutureTaskStore._row_to_future_task(row)
            future_task_id = future_task["future_task_id"]
            next_run_number = int(future_task.get("run_count") or 0) + 1
            try:
                run = self._create_run_for_runnable(
                    runnable_id=str(future_task.get("runnable_id") or ""),
                    name=str(future_task.get("runnable_name") or ""),
                    user_goal=str(future_task.get("prompt") or ""),
                    client_run_id=f"future-task-{future_task_id}-{next_run_number}",
                )
                run_id = str(run.get("run_id") or "")
                cron = str(future_task.get("cron") or "").strip()
                if cron:
                    next_epoch = AgentFutureTaskStore._next_cron_epoch(cron, current)
                    status = "scheduled"
                    error_text = ""
                    cancelled_at = ""
                else:
                    next_epoch = float(future_task.get("scheduled_at_epoch") or current)
                    status = "triggered"
                    error_text = ""
                    cancelled_at = ""
                updated = self._persist_future_task_trigger(
                    future_task_id,
                    status=status,
                    scheduled_at_epoch=next_epoch,
                    last_run_id=run_id,
                    run_count=next_run_number,
                    error=error_text,
                    cancelled_at=cancelled_at,
                    event_action="future_task.trigger",
                    event_payload={
                        "run_id": run_id,
                        "cron": cron,
                        "scheduled_at_epoch": next_epoch,
                    },
                )
                triggered.append({"ok": True, "future_task": updated, "run": run})
            except Exception as exc:
                safe_error = self._redact_secrets(exc)
                updated = self._persist_future_task_trigger(
                    future_task_id,
                    status="failed",
                    scheduled_at_epoch=float(future_task.get("scheduled_at_epoch") or current),
                    last_run_id=str(future_task.get("last_run_id") or ""),
                    run_count=int(future_task.get("run_count") or 0),
                    error=safe_error,
                    cancelled_at="",
                    event_action="future_task.failed",
                    event_payload={"error": safe_error},
                )
                triggered.append({"ok": False, "future_task": updated, "error": safe_error})
        return {"ok": True, "triggered": triggered}

    def _persist_future_task_trigger(
        self,
        future_task_id: str,
        *,
        status: str,
        scheduled_at_epoch: float,
        last_run_id: str,
        run_count: int,
        error: str,
        cancelled_at: str,
        event_action: str,
        event_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in _FUTURE_TASK_STATUSES:
            raise self._error_type("FutureTask 状态无效")
        store = self._future_task_store(source_run_id=last_run_id or "future_task_scheduler")
        now = self._now()
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    """
                    UPDATE future_tasks
                       SET status=?, scheduled_at_epoch=?, last_run_id=?, run_count=?,
                           error=?, updated_at=?, cancelled_at=?
                     WHERE future_task_id=?
                    """,
                    (
                        status,
                        scheduled_at_epoch,
                        last_run_id,
                        run_count,
                        error,
                        now,
                        cancelled_at,
                        future_task_id,
                    ),
                )
                store._record_event(future_task_id, event_action, event_payload)
                row = self._conn.execute(
                    "SELECT * FROM future_tasks WHERE future_task_id=?",
                    (future_task_id,),
                ).fetchone()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return AgentFutureTaskStore._row_to_future_task(row)
