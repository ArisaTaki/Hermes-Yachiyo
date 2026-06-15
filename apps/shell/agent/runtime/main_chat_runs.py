"""Main chat run lifecycle helpers for the legacy runtime entrypoint."""

from __future__ import annotations

from typing import Any, Callable


class MainChatRunLifecycle:
    """Starts and completes daily Chat runs while preserving task projections."""

    def __init__(
        self,
        *,
        main_chat_agent_id: str,
        insert_run: Callable[..., dict[str, Any]],
        link_task_run: Callable[..., Any],
        get_run: Callable[[str], dict[str, Any]],
        update_run: Callable[..., dict[str, Any]],
        task_run_links: Any,
        task_events: Any,
        timeline_factory: Callable[..., dict[str, Any]],
        redact_secrets: Callable[[Any], str],
        final_statuses: set[str],
    ) -> None:
        self._main_chat_agent_id = main_chat_agent_id
        self._insert_run = insert_run
        self._link_task_run = link_task_run
        self._get_run = get_run
        self._update_run = update_run
        self._task_run_links = task_run_links
        self._task_events = task_events
        self._timeline = timeline_factory
        self._redact_secrets = redact_secrets
        self._final_statuses = final_statuses

    def start(self, *, task_id: str, session_id: str, user_goal: str) -> dict[str, Any]:
        run = self._insert_run(
            kind="main_chat_run",
            runnable_id=self._main_chat_agent_id,
            user_goal=self._redact_secrets(user_goal),
        )
        self._link_task_run(task_id=task_id, run_id=run["run_id"], session_id=session_id)
        timeline = [
            self._timeline(
                "run.started",
                "Native main chat run started",
                task_id=str(task_id or ""),
                session_id=str(session_id or ""),
            ),
            self._timeline("task.created", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.started", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.linked", str(task_id or ""), task_id=str(task_id or "")),
        ]
        run = self._update_run(run["run_id"], timeline=timeline)
        self._task_events.started(
            run["run_id"],
            task_id=str(task_id or ""),
            session_id=str(session_id or ""),
        )
        return run

    def complete(self, run_id: str, result: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in self._final_statuses else None
        if terminal is not None:
            return terminal
        safe_result = self._redact_secrets(result)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.completed", "Native main chat run completed"),
        ]
        completed = self._update_run(
            run_id,
            status="completed",
            result=safe_result,
            timeline=timeline,
            pending_approval=None,
        )
        link = self._task_run_links.for_run(run_id)
        self._task_events.completed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            result=safe_result,
        )
        return completed

    def fail(self, run_id: str, error: Any) -> dict[str, Any]:
        run = self._get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in self._final_statuses else None
        if terminal is not None:
            return terminal
        safe_error = self._redact_secrets(error)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.failed", safe_error),
        ]
        failed = self._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=timeline,
            pending_approval=None,
        )
        link = self._task_run_links.for_run(run_id)
        self._task_events.failed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            error=safe_error,
        )
        return failed
