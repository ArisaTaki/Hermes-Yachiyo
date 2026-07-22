"""Runtime shutdown orchestration."""

from __future__ import annotations

from typing import Any, Callable


class RuntimeShutdownService:
    """Cancels active runs and closes runtime resources."""

    def __init__(
        self,
        *,
        conn: Any,
        credential_store: Any,
        is_closed: Callable[[], bool],
        mark_not_accepting: Callable[[], Any],
        mark_closed: Callable[[], Any],
        cancel_terminal_process_groups: Callable[[], Any],
        ensure_row_factory: Callable[[], Any],
        cancel_run: Callable[[str], dict[str, Any]],
        release_desktop_provider_session_owner: Callable[[], Any] | None = None,
        close_desktop_execution_providers: Callable[[], Any] | None = None,
    ) -> None:
        self._conn = conn
        self._credential_store = credential_store
        self._is_closed = is_closed
        self._mark_not_accepting = mark_not_accepting
        self._mark_closed = mark_closed
        self._cancel_terminal_process_groups = cancel_terminal_process_groups
        self._ensure_row_factory = ensure_row_factory
        self._cancel_run = cancel_run
        self._release_desktop_provider_session_owner = (
            release_desktop_provider_session_owner or (lambda: None)
        )
        self._close_desktop_execution_providers = (
            close_desktop_execution_providers or (lambda: None)
        )

    def shutdown(self, *, close_db: bool = True) -> None:
        if self._is_closed():
            return
        self._mark_not_accepting()
        self._cancel_terminal_process_groups()
        try:
            self._ensure_row_factory()
            for run_id in self._active_run_ids():
                try:
                    self._cancel_run(run_id)
                except Exception:
                    continue
            self._conn.commit()
        finally:
            if close_db:
                try:
                    self._release_desktop_provider_session_owner()
                except Exception:
                    # Shutdown remains best-effort; database and credential
                    # resources must still close if provider cleanup fails.
                    pass
                try:
                    self._close_desktop_execution_providers()
                except Exception:
                    # Provider cleanup must not prevent durable runtime resources
                    # from closing. Cua MCP proxies normally terminate on EOF.
                    pass
                finally:
                    self._conn.close()
                    self._credential_store.close()
                    self._mark_closed()

    def _active_run_ids(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT run_id
              FROM runs
             WHERE status NOT IN ('completed', 'failed', 'cancelled')
             ORDER BY updated_at DESC
            """
        ).fetchall()
        return [str(row["run_id"]) for row in rows]
