"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .approval_event_snapshots import (
    approval_snapshots_from_events as _approval_snapshots_from_events,
    merge_approval_snapshot_lists as _merge_approval_snapshot_lists,
)
from .approvals import approval_cards_from_payloads
from .artifact_event_snapshots import (
    artifact_snapshots_from_events as _artifact_snapshots_from_events,
    merge_artifact_snapshot_lists as _merge_artifact_snapshot_lists,
)
from .artifacts import artifact_snapshots_from_payloads
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
    task_status_from_value as _task_status,
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
    run_timeline_agent_id_from_payload as _agent_id_from_run,
    run_timeline_rerun_provenance_from_payload as _rerun_provenance_from_payload,
    timeline_child_snapshots_from_payloads as _timeline_child_snapshots_from_payloads,
    workflow_run_id_from_payload as _workflow_run_id,
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
        if isinstance(payload, RunTimelineSnapshot):
            return payload

        run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
        events = self.events_from_payload(
            payload,
            run_id=run_id,
            keys=("events", "run_events", "timeline"),
        )
        legacy_run_group_id = _optional_text(payload.get("run_group_id"))
        group_run_id = _optional_text(payload.get("group_run_id")) or legacy_run_group_id
        approvals = self.approvals_from_payload(
            payload,
            run_id=run_id,
            group_run_id=group_run_id or "",
            keys=("approvals", "pending_approval"),
            events=events,
        )
        pending_approval = None
        if (
            isinstance(payload.get("pending_approval"), Mapping)
            and payload.get("pending_approval")
            and approvals
        ):
            pending_approval = next(
                (approval for approval in approvals if approval.status == "pending"),
                None,
            )
        elif _task_status(payload.get("status")) == "waiting_approval" and approvals:
            pending_approval = next(
                (approval for approval in approvals if approval.status == "pending"),
                None,
            )
        rerun_provenance = _rerun_provenance_from_payload(payload, events)

        return RunTimelineSnapshot(
            run_id=run_id,
            parent_run_id=_optional_text(payload.get("parent_run_id")),
            group_run_id=group_run_id,
            run_group_id=legacy_run_group_id or group_run_id,
            workflow_run_id=_workflow_run_id(payload, run_id),
            agent_id=_optional_text(payload.get("agent_id") or _agent_id_from_run(payload)),
            status=_text(payload.get("status") or "unknown"),
            title=_optional_text(payload.get("title") or payload.get("user_goal")),
            task_id=_optional_text(payload.get("task_id")),
            session_id=_optional_text(payload.get("session_id")),
            task_run_link_created_at=_optional_text(payload.get("task_run_link_created_at")),
            task_run_link_updated_at=_optional_text(payload.get("task_run_link_updated_at")),
            task_run_link_run_status=_optional_text(payload.get("task_run_link_run_status")),
            task_run_link_last_event_sequence=_optional_int(
                payload.get("task_run_link_last_event_sequence")
            ),
            rerun_of_run_id=rerun_provenance.get("rerun_of_run_id"),
            rerun_of_kind=rerun_provenance.get("rerun_of_kind"),
            rerun_of_status=rerun_provenance.get("rerun_of_status"),
            rerun_of_runnable_id=rerun_provenance.get("rerun_of_runnable_id"),
            rerun_of_runnable_name=rerun_provenance.get("rerun_of_runnable_name"),
            rerun_original_created_at=rerun_provenance.get("rerun_original_created_at"),
            rerun_original_updated_at=rerun_provenance.get("rerun_original_updated_at"),
            events=events,
            tool_calls=self.tool_calls_from_payload(
                payload.get("tool_calls"),
                run_id=run_id,
                events=events,
            ),
            memory_traces=self.memory_traces_from_events(events),
            skill_traces=self.skill_traces_from_events(events),
            approvals=approvals,
            pending_approval=pending_approval,
            artifacts=self.artifacts_from_payload(payload, run_id=run_id, events=events),
            children=self.timeline_children_from_payloads(
                payload.get("children") or payload.get("child_run_ids")
            ),
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        )

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
        for key in keys:
            approvals = approval_cards_from_payloads(
                payload.get(key),
                run_id=run_id,
                group_run_id=group_run_id,
            )
            if approvals:
                return _merge_approval_snapshot_lists(
                    approvals,
                    self.approvals_from_events(events or [], group_run_id=group_run_id),
                )
        return self.approvals_from_events(events or [], group_run_id=group_run_id)

    def artifacts_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        events: list[PublicRunEvent] | None = None,
    ):
        return _merge_artifact_snapshot_lists(
            self.artifacts_from_payloads(payload.get("artifacts"), run_id=run_id),
            self.artifacts_from_events(events or []),
        )

    def approvals_from_payloads(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        group_run_id: str = "",
    ):
        return approval_cards_from_payloads(
            payloads,
            run_id=run_id,
            group_run_id=group_run_id,
        )

    def artifacts_from_payloads(self, payloads: Any, *, run_id: str = ""):
        return artifact_snapshots_from_payloads(payloads, run_id=run_id)

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


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
