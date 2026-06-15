"""Runtime timeline projection helpers."""

from __future__ import annotations

from typing import Any, Callable


def runtime_timeline_event(
    event: str,
    detail: str = "",
    *,
    now: Callable[[], str],
    redact_detail: Callable[[Any], str],
    redact_payload: Callable[[Any], Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "time": now(),
        "event": event,
        "detail": redact_detail(detail),
        **redact_payload(extra),
    }


def runtime_timeline_factory(
    *,
    now: Callable[[], str],
    redact_detail: Callable[[Any], str],
    redact_payload: Callable[[Any], Any],
) -> Callable[..., dict[str, Any]]:
    def build_runtime_timeline_event(
        event: str,
        detail: str = "",
        **extra: Any,
    ) -> dict[str, Any]:
        return runtime_timeline_event(
            event,
            detail,
            now=now,
            redact_detail=redact_detail,
            redact_payload=redact_payload,
            **extra,
        )

    return build_runtime_timeline_event


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
