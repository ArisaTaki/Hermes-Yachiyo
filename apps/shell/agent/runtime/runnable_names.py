"""Runnable display-name lookup for run projections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeRunnableNameResolver:
    """Resolves Agent, Workflow, and main-chat runnable display names."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        main_chat_agent_id: str,
        main_chat_name: str = "Yachiyo",
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._main_chat_agent_id = main_chat_agent_id
        self._main_chat_name = main_chat_name

    def resolve(self, kind: str, runnable_id: str) -> str:
        self._ensure_row_factory()
        if kind == "main_chat_run" and runnable_id == self._main_chat_agent_id:
            return self._main_chat_name
        if kind == "agent_run":
            row = self._conn.execute("SELECT name FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        if kind == "workflow_run":
            row = self._conn.execute("SELECT name FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        return ""
