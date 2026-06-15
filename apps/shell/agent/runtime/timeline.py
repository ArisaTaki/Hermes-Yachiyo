"""Runtime timeline projection helpers."""

from __future__ import annotations

from typing import Any


class RuntimeAgentTimelineBuilder:
    """Builds Agent runtime timeline entries without owning run state."""

    def __init__(self, *, timeline_factory: Any) -> None:
        self._timeline = timeline_factory

    def started(
        self,
        agent_name: str,
        *,
        backend: str,
        runtime: str,
    ) -> dict[str, Any]:
        return self._timeline(
            "agent.run.started",
            f"{agent_name} started",
            backend=backend,
            runtime=runtime,
        )

    def compiled(
        self,
        *,
        allowed_tools: list[str],
        detail: str = "Oha Agent Runtime compiled tools and workspace policy",
    ) -> dict[str, Any]:
        return self._timeline(
            "agent.runtime.compiled",
            detail,
            allowed_tools=list(allowed_tools or []),
        )

    def completed(self) -> dict[str, Any]:
        return self._timeline("agent.run.completed", "Agent run completed")

    def failed(self, error: Any) -> dict[str, Any]:
        return self._timeline("agent.run.failed", str(error or ""))
