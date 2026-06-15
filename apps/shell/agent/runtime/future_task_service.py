"""FutureTask public runtime operations for scheduling and management."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler


class RuntimeFutureTaskService:
    """Coordinates FutureTask store operations around runnable resolution."""

    def __init__(
        self,
        *,
        future_task_store: Callable[..., AgentFutureTaskStore],
        resolve_runnable: Callable[..., dict[str, Any] | None],
        trigger_scheduler: FutureTaskTriggerScheduler,
        default_runnable_id: str,
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._future_task_store = future_task_store
        self._resolve_runnable = resolve_runnable
        self._trigger_scheduler = trigger_scheduler
        self._default_runnable_id = default_runnable_id
        self._error_type = error_type

    def schedule(self, payload: dict[str, Any], *, source_run_id: str = "") -> dict[str, Any]:
        runnable_name = str(payload.get("runnable_name") or payload.get("name") or "").strip()
        runnable_id = str(
            payload.get("runnable_id") or ("" if runnable_name else self._default_runnable_id)
        ).strip()
        if self._resolve_runnable(runnable_id=runnable_id, name=runnable_name) is None:
            raise self._error_type("FutureTask 指向的 Agent 或 Workflow 不存在")
        return self._future_task_store(
            source_run_id=source_run_id or "manual",
            default_runnable_id=runnable_id,
        ).schedule(
            title=str(payload.get("title") or ""),
            prompt=str(payload.get("prompt") or payload.get("user_goal") or payload.get("goal") or ""),
            runnable_id=runnable_id,
            runnable_name=runnable_name,
            delay_seconds=payload.get("delay_seconds"),
            scheduled_at_epoch=payload.get("scheduled_at_epoch"),
            cron=str(payload.get("cron") or ""),
        )

    def list(self, *, include_finished: bool = True, limit: int = 100) -> dict[str, Any]:
        return {
            "ok": True,
            "future_tasks": self._future_task_store().list_tasks(
                include_finished=include_finished,
                limit=limit,
            ),
        }

    def cancel(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._future_task_store(source_run_id="manual").cancel(future_task_id, reason=reason)

    def trigger_due(self, *, now_epoch: float | None = None, limit: int = 20) -> dict[str, Any]:
        return self._trigger_scheduler.trigger_due_future_tasks(
            now_epoch=now_epoch,
            limit=limit,
        )
