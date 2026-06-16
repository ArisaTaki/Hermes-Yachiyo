"""Runtime service access helpers."""

from __future__ import annotations

from typing import TypeVar

from apps.shell.agent.runtime.service_lifecycle import RuntimeServiceLifecycle


RuntimeServiceT = TypeVar("RuntimeServiceT")


def resolve_runtime_service(
    *,
    lifecycle: RuntimeServiceLifecycle,
    current: RuntimeServiceT | None,
) -> RuntimeServiceT:
    """Resolve a runtime service while preserving legacy global injection."""
    if current is not None:
        lifecycle.set_current(current)
        return current
    return lifecycle.get()


def close_runtime_service(
    *,
    lifecycle: RuntimeServiceLifecycle,
    current: RuntimeServiceT | None,
) -> None:
    """Close the lifecycle after syncing any legacy global injection."""
    if current is not None:
        lifecycle.set_current(current)
    lifecycle.close()
