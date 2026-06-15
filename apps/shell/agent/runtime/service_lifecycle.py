"""Runtime service singleton lifecycle helpers."""

from __future__ import annotations

from typing import Any, Callable


class RuntimeServiceLifecycle:
    """Owns lazy construction and close semantics for a process-local service."""

    def __init__(self, *, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._service: Any | None = None

    @property
    def current(self) -> Any | None:
        return self._service

    def set_current(self, service: Any | None) -> None:
        self._service = service

    def get(self) -> Any:
        if self._service is None:
            self._service = self._factory()
        return self._service

    def close(self) -> None:
        if self._service is None:
            return
        self._service.close()
        self._service = None
