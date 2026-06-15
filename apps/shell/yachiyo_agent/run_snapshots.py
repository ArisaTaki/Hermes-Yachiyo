"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .approvals import approval_cards_from_payloads
from .artifacts import artifact_snapshots_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    ToolCallSnapshot,
)
from .events import public_run_event_from_payload


class RunSnapshotProjector:
    """Projects runtime-like run payloads into public Chat and Studio snapshots."""

    def task_snapshot_from_payload(
        self,
        payload: Mapping[str, Any] | AgentTaskSnapshot,
    ) -> AgentTaskSnapshot:
        if isinstance(payload, AgentTaskSnapshot):
            return payload

        task_id = _text(payload.get("task_id") or payload.get("run_id"))
        run_id = _text(payload.get("run_id") or task_id)
        recent_events = self.events_from_payload(
            payload,
            run_id=run_id,
            keys=("recent_events", "events", "timeline"),
        )
        approvals = self.approvals_from_payload(
            payload,
            run_id=run_id,
            keys=("pending_approvals", "pending_approval"),
        )

        return AgentTaskSnapshot(
            task_id=task_id,
            conversation_id=_optional_text(payload.get("conversation_id") or payload.get("session_id")),
            title=_text(payload.get("title") or payload.get("user_goal") or "Yachiyo task"),
            status=_task_status(payload.get("status")),
            summary=_optional_text(payload.get("summary") or payload.get("result")),
            current_step=_optional_text(payload.get("current_step")),
            progress_text=_optional_text(payload.get("progress_text")),
            needs_user_action=bool(payload.get("needs_user_action") or approvals),
            pending_approvals=approvals,
            recent_events=recent_events,
            artifacts=self.artifacts_from_payload(payload, run_id=run_id),
            open_in_studio_url=_optional_text(payload.get("open_in_studio_url")) or _studio_url(run_id),
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        )

    def task_snapshots_from_payloads(self, payloads: Any) -> list[AgentTaskSnapshot]:
        if not isinstance(payloads, list):
            return []
        return [self.task_snapshot_from_payload(item) for item in payloads]

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
            keys=("approvals", "pending_approval"),
        )
        pending_approval = None
        if isinstance(payload.get("pending_approval"), Mapping) and approvals:
            pending_approval = approvals[0]

        return RunTimelineSnapshot(
            run_id=run_id,
            parent_run_id=_optional_text(payload.get("parent_run_id")),
            group_run_id=group_run_id,
            run_group_id=legacy_run_group_id or group_run_id,
            workflow_run_id=_workflow_run_id(payload, run_id),
            agent_id=_optional_text(payload.get("agent_id") or _agent_id_from_run(payload)),
            status=_text(payload.get("status") or "unknown"),
            title=_optional_text(payload.get("title") or payload.get("user_goal")),
            events=events,
            tool_calls=self.tool_calls_from_payload(
                payload.get("tool_calls"),
                run_id=run_id,
                events=events,
            ),
            approvals=approvals,
            pending_approval=pending_approval,
            artifacts=self.artifacts_from_payload(payload, run_id=run_id),
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
        raw_events = []
        for key in keys:
            value = payload.get(key)
            if value:
                raw_events = value
                break
        return [
            public_run_event_from_payload(event, run_id=run_id, sequence=index + 1)
            for index, event in enumerate(raw_events if isinstance(raw_events, list) else [])
        ]

    def approvals_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        keys: tuple[str, ...],
    ):
        for key in keys:
            approvals = approval_cards_from_payloads(payload.get(key), run_id=run_id)
            if approvals:
                return approvals
        return []

    def artifacts_from_payload(self, payload: Mapping[str, Any], *, run_id: str):
        return artifact_snapshots_from_payloads(payload.get("artifacts"), run_id=run_id)

    def tool_calls_from_payload(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        events: list[PublicRunEvent] | None = None,
    ) -> list[ToolCallSnapshot]:
        if isinstance(payloads, list):
            return [self.tool_call_from_payload(item, run_id=run_id) for item in payloads]
        return self.tool_calls_from_events(events or [])

    def tool_call_from_payload(
        self,
        payload: Mapping[str, Any] | ToolCallSnapshot,
        *,
        run_id: str = "",
    ) -> ToolCallSnapshot:
        if isinstance(payload, ToolCallSnapshot):
            return payload
        tool_name = _text(payload.get("tool_name") or payload.get("tool") or "tool")
        tool_call_id = _text(payload.get("tool_call_id") or payload.get("id"))
        if not tool_call_id:
            tool_call_id = f"{run_id or 'run'}:{tool_name}:{payload.get('sequence') or 0}"
        return ToolCallSnapshot(
            tool_call_id=tool_call_id,
            run_id=_optional_text(payload.get("run_id") or run_id),
            tool_name=tool_name,
            status=_text(payload.get("status") or "completed"),
            risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
            input_preview=_mapping(payload.get("input_preview") or payload.get("input")),
            output_preview=_mapping(payload.get("output_preview") or payload.get("result")),
            approval_id=_optional_text(payload.get("approval_id")),
            started_at=_text(payload.get("started_at") or payload.get("created_at")),
            completed_at=_optional_text(payload.get("completed_at")),
        )

    def tool_calls_from_events(self, events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
        calls: list[ToolCallSnapshot] = []
        for event in events:
            if event.event_type != "agent.tool.call":
                continue
            payload = {
                **event.payload,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "tool_name": event.detail or event.payload.get("tool"),
                "created_at": event.created_at,
            }
            calls.append(self.tool_call_from_payload(payload, run_id=event.run_id))
        return calls

    def timeline_children_from_payloads(self, payloads: Any) -> list[RunTimelineChildSnapshot]:
        if not isinstance(payloads, list):
            return []
        children: list[RunTimelineChildSnapshot] = []
        for item in payloads:
            if isinstance(item, Mapping):
                children.append(
                    RunTimelineChildSnapshot(
                        run_id=_text(item.get("run_id")),
                        title=_optional_text(item.get("title") or item.get("user_goal")),
                        status=_text(item.get("status")),
                        kind=_optional_text(item.get("kind")),
                        agent_id=_optional_text(item.get("agent_id")),
                        workflow_id=_optional_text(item.get("workflow_id")),
                    )
                )
            else:
                children.append(RunTimelineChildSnapshot(run_id=_text(item)))
        return children


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


def _task_status(value: Any) -> str:
    status = _text(value)
    status_map = {
        "approval_required": "waiting_approval",
        "pending_approval": "waiting_approval",
        "processing": "running",
        "success": "completed",
        "succeeded": "completed",
        "done": "completed",
        "error": "failed",
        "canceled": "cancelled",
    }
    normalized = status_map.get(status, status)
    if normalized in {"queued", "running", "waiting_approval", "completed", "failed", "cancelled"}:
        return normalized
    return "running"


def _agent_id_from_run(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("kind")) == "agent_run":
        return _text(payload.get("runnable_id"))
    return ""


def _workflow_run_id(payload: Mapping[str, Any], run_id: str) -> str | None:
    explicit = _optional_text(payload.get("workflow_run_id"))
    if explicit:
        return explicit
    if _text(payload.get("kind")) == "workflow_run":
        return run_id or None
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _studio_url(run_id: str) -> str | None:
    return f"#/agents?run_id={run_id}" if run_id else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
