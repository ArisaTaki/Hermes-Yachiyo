"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import (
    AgentTaskSnapshot,
    MemoryTraceSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    SkillTraceSnapshot,
    ToolCallSnapshot,
)
from .task_snapshots import (
    agent_task_snapshot_from_payload as _agent_task_snapshot_from_payload,
    agent_task_snapshots_from_payloads as _agent_task_snapshots_from_payloads,
    run_events_from_payload as _run_events_from_payload,
)
from .run_timeline_snapshots import (
    approval_snapshots_from_events as _approval_snapshots_from_events,
    approval_snapshots_from_payload as _approval_snapshots_from_payload,
    approval_snapshots_from_payloads as _approval_snapshots_from_payloads,
    artifact_snapshots_from_events as _artifact_snapshots_from_events,
    artifact_snapshots_from_payloads as _artifact_snapshots_from_payloads,
    artifact_snapshots_from_timeline_payload as _artifact_snapshots_from_timeline_payload,
    run_timeline_snapshot_from_payload as _run_timeline_snapshot_from_payload,
)
from .trace_snapshots import (
    memory_trace_snapshots_from_events as _memory_trace_snapshots_from_events,
    skill_trace_snapshots_from_events as _skill_trace_snapshots_from_events,
)
from .tool_call_snapshots import (
    tool_call_snapshot_from_payload as _tool_call_snapshot_from_payload,
    tool_call_snapshots_from_events as _tool_call_snapshots_from_events,
    tool_call_snapshots_from_payloads as _tool_call_snapshots_from_payloads,
)
from .timeline_metadata_snapshots import (
    timeline_child_snapshots_from_payloads as _timeline_child_snapshots_from_payloads,
)


class RunSnapshotProjector:
    """Projects runtime-like run payloads into public Chat and Studio snapshots."""

    def task_snapshot_from_payload(
        self,
        payload: Mapping[str, Any] | AgentTaskSnapshot,
    ) -> AgentTaskSnapshot:
        return _agent_task_snapshot_from_payload(payload)

    def task_snapshots_from_payloads(self, payloads: Any) -> list[AgentTaskSnapshot]:
        return _agent_task_snapshots_from_payloads(payloads)

    def timeline_snapshot_from_payload(
        self,
        payload: Mapping[str, Any] | RunTimelineSnapshot,
    ) -> RunTimelineSnapshot:
        return _run_timeline_snapshot_from_payload(payload)

    def events_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        keys: tuple[str, ...],
    ) -> list[PublicRunEvent]:
        return _run_events_from_payload(payload, run_id=run_id, keys=keys)

    def approvals_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        group_run_id: str = "",
        keys: tuple[str, ...],
        events: list[PublicRunEvent] | None = None,
    ):
        return _approval_snapshots_from_payload(
            payload,
            run_id=run_id,
            group_run_id=group_run_id,
            keys=keys,
            events=events,
        )

    def artifacts_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        events: list[PublicRunEvent] | None = None,
    ):
        return _artifact_snapshots_from_timeline_payload(
            payload,
            run_id=run_id,
            events=events,
        )

    def approvals_from_payloads(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        group_run_id: str = "",
    ):
        return _approval_snapshots_from_payloads(
            payloads,
            run_id=run_id,
            group_run_id=group_run_id,
        )

    def artifacts_from_payloads(self, payloads: Any, *, run_id: str = ""):
        return _artifact_snapshots_from_payloads(payloads, run_id=run_id)

    def approvals_from_events(
        self,
        events: list[PublicRunEvent],
        *,
        group_run_id: str = "",
    ):
        return _approval_snapshots_from_events(events, group_run_id=group_run_id)

    def artifacts_from_events(self, events: list[PublicRunEvent]):
        return _artifact_snapshots_from_events(events)

    def tool_calls_from_payload(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        events: list[PublicRunEvent] | None = None,
    ) -> list[ToolCallSnapshot]:
        return _tool_call_snapshots_from_payloads(payloads, run_id=run_id, events=events)

    def tool_call_from_payload(
        self,
        payload: Mapping[str, Any] | ToolCallSnapshot,
        *,
        run_id: str = "",
    ) -> ToolCallSnapshot:
        return _tool_call_snapshot_from_payload(payload, run_id=run_id)

    def tool_calls_from_events(self, events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
        return _tool_call_snapshots_from_events(events)

    def memory_traces_from_events(self, events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
        return _memory_trace_snapshots_from_events(events)

    def skill_traces_from_events(self, events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
        return _skill_trace_snapshots_from_events(events)

    def timeline_children_from_payloads(self, payloads: Any) -> list[RunTimelineChildSnapshot]:
        return _timeline_child_snapshots_from_payloads(payloads)


_PROJECTOR = RunSnapshotProjector()


def agent_task_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentTaskSnapshot,
) -> AgentTaskSnapshot:
    return _PROJECTOR.task_snapshot_from_payload(payload)


def agent_task_snapshots_from_payloads(payloads: Any) -> list[AgentTaskSnapshot]:
    return _PROJECTOR.task_snapshots_from_payloads(payloads)


def run_timeline_snapshot_from_payload(
    payload: Mapping[str, Any] | RunTimelineSnapshot,
) -> RunTimelineSnapshot:
    return _PROJECTOR.timeline_snapshot_from_payload(payload)


def tool_call_snapshots_from_payloads(payloads: Any, *, run_id: str = "") -> list[ToolCallSnapshot]:
    return _PROJECTOR.tool_calls_from_payload(payloads, run_id=run_id)


def tool_call_snapshot_from_payload(
    payload: Mapping[str, Any] | ToolCallSnapshot,
    *,
    run_id: str = "",
) -> ToolCallSnapshot:
    return _PROJECTOR.tool_call_from_payload(payload, run_id=run_id)


def timeline_children_from_payloads(payloads: Any) -> list[RunTimelineChildSnapshot]:
    return _PROJECTOR.timeline_children_from_payloads(payloads)


def memory_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
    return _memory_trace_snapshots_from_events(events)


def skill_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
    return _skill_trace_snapshots_from_events(events)
