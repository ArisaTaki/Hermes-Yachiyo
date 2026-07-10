"""Domain result for automatic replan continuation attempts."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AgentTaskSnapshot,
    ReplanContinuationSnapshot,
    RunTimelineSnapshot,
)


@dataclass(frozen=True, slots=True)
class ReplanContinuationStartResult:
    item: AgentTaskSnapshot | RunTimelineSnapshot | None = None
    continuation: ReplanContinuationSnapshot | None = None

    @property
    def started(self) -> bool:
        return self.item is not None
