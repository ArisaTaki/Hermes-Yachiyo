"""Run status lookup helpers for idempotent runtime continuations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeTerminalRunResolver:
    """Returns a Run snapshot only after it reaches a terminal status."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        final_statuses: set[str] | frozenset[str] | tuple[str, ...],
    ) -> None:
        self._get_run = get_run
        self._final_statuses = set(final_statuses)

    def terminal_run_or_none(self, run_id: str) -> dict[str, Any] | None:
        try:
            run = self._get_run(run_id)
        except KeyError:
            return None
        status = str(run.get("status") or "").strip()
        return run if status in self._final_statuses else None
