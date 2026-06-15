"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .approvals import approval_card_from_payload, approval_cards_from_payloads
from .artifacts import artifact_snapshot_from_payload, artifact_snapshots_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    ToolCallSnapshot,
)
from .events import public_run_event_from_payload
from .links import studio_run_url


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
            events=recent_events,
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
            artifacts=self.artifacts_from_payload(payload, run_id=run_id, events=recent_events),
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
            events=events,
        )
        pending_approval = None
        if isinstance(payload.get("pending_approval"), Mapping) and approvals:
            pending_approval = approvals[0]
        elif _task_status(payload.get("status")) == "waiting_approval" and approvals:
            pending_approval = next(
                (approval for approval in approvals if approval.status == "pending"),
                approvals[0],
            )

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
            events=events,
            tool_calls=self.tool_calls_from_payload(
                payload.get("tool_calls"),
                run_id=run_id,
                events=events,
            ),
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
        events: list[PublicRunEvent] | None = None,
    ):
        for key in keys:
            approvals = approval_cards_from_payloads(payload.get(key), run_id=run_id)
            if approvals:
                return _merge_approvals(approvals, self.approvals_from_events(events or []))
        return self.approvals_from_events(events or [])

    def artifacts_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        events: list[PublicRunEvent] | None = None,
    ):
        return _merge_artifacts(
            self.artifacts_from_payloads(payload.get("artifacts"), run_id=run_id),
            self.artifacts_from_events(events or []),
        )

    def approvals_from_payloads(self, payloads: Any, *, run_id: str = ""):
        return approval_cards_from_payloads(payloads, run_id=run_id)

    def artifacts_from_payloads(self, payloads: Any, *, run_id: str = ""):
        return artifact_snapshots_from_payloads(payloads, run_id=run_id)

    def approvals_from_events(self, events: list[PublicRunEvent]):
        approvals = []
        for event in events:
            approval_payload = _approval_payload_from_event(event)
            if approval_payload:
                approvals.append(approval_card_from_payload(approval_payload, run_id=event.run_id))
        return approvals

    def artifacts_from_events(self, events: list[PublicRunEvent]):
        artifacts = []
        for event in events:
            artifact_payload = _artifact_payload_from_event(event)
            if artifact_payload:
                artifacts.append(
                    artifact_snapshot_from_payload(artifact_payload, run_id=event.run_id)
                )
        return artifacts

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
            output_preview=_tool_output_preview(payload),
            approval_id=_optional_text(payload.get("approval_id")),
            started_at=_text(payload.get("started_at") or payload.get("created_at")),
            completed_at=_optional_text(payload.get("completed_at")),
        )

    def tool_calls_from_events(self, events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
        calls: list[ToolCallSnapshot] = []
        for event in events:
            if not _is_tool_event(event.event_type):
                continue
            payload = {
                **event.payload,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "tool_name": _tool_name_from_event(event),
                "status": event.payload.get("status") or _tool_status_from_event_type(
                    event.event_type
                ),
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


def _approval_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    if event.event_type not in {
        "agent.tool.approval_required",
        "group.approval_required",
        "group.member.approval_required",
        "tool.approval_required",
        "workflow.node.approval_required",
        "workflow.run.approval_required",
    }:
        return {}
    payload = dict(event.payload)
    pending = payload.get("pending_approval") or payload.get("approval")
    source = dict(pending) if isinstance(pending, Mapping) else payload
    if not source:
        return {}
    if event.event_type.startswith("group.") and not source.get("tool"):
        source["tool"] = "group.approval"
    if event.event_type.startswith("workflow.") and not source.get("tool"):
        source["tool"] = "workflow.approval"
    if not source.get("title") and payload.get("workflow_node_label"):
        source["title"] = f"Approve {payload['workflow_node_label']}"
    if not source.get("title") and payload.get("member_agent_name"):
        source["title"] = f"Approve {payload['member_agent_name']}"
    source.setdefault("approval_id", f"{event.run_id}:{event.event_type}:{event.sequence}")
    source.setdefault("status", "pending")
    source.setdefault("created_at", event.created_at)
    source.setdefault("run_id", event.run_id)
    return source


def _artifact_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type == "artifact.created":
        artifact_payload = payload
    elif event.event_type in {"group.artifact.created", "group.shared_artifact.created"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        artifact_payload.setdefault("kind", "group_artifact")
        if payload.get("member_agent_name"):
            artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
        if payload.get("member_agent_id"):
            artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
    elif event.event_type == "workflow.node.artifact" and isinstance(payload.get("artifact"), Mapping):
        artifact_payload = {
            "kind": "workflow_artifact",
            "title": payload.get("workflow_node_label") or "Workflow Artifact",
            "workflow_node_id": payload.get("workflow_node_id"),
            "workflow_node_label": payload.get("workflow_node_label"),
            **dict(payload["artifact"]),
        }
    else:
        return {}
    artifact_payload.setdefault("source_run_id", event.run_id)
    artifact_payload.setdefault("run_id", event.run_id)
    artifact_payload.setdefault("created_at", event.created_at)
    return artifact_payload


def _merge_approvals(*approval_lists):
    by_key = {}
    for approvals in approval_lists:
        for approval in approvals or []:
            key = approval.approval_id or approval.run_id or approval.title
            if key and key not in by_key:
                by_key[key] = approval
    return list(by_key.values())


def _merge_artifacts(*artifact_lists):
    by_key = {}
    for artifacts in artifact_lists:
        for artifact in artifacts or []:
            key = artifact.artifact_id or artifact.path or artifact.title
            if key and key not in by_key:
                by_key[key] = artifact
    return list(by_key.values())


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


def _tool_output_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _mapping(payload.get("output_preview") or payload.get("result"))
    if explicit:
        return explicit
    error = payload.get("error")
    return {"error": error} if error is not None else {}


def _is_tool_event(event_type: str) -> bool:
    return event_type in {
        "agent.tool.call",
        "agent.tool.denied",
        "agent.tool.failed",
        "agent.tool.skipped",
        "agent.tool.approval_required",
        "agent.tool.approval_approved",
        "agent.tool.approval_rejected",
        "agent.tool.completed",
        "tool.requested",
        "tool.started",
        "tool.approval_required",
        "tool.completed",
        "tool.failed",
    }


def _tool_name_from_event(event: PublicRunEvent) -> str:
    return _text(
        event.payload.get("tool_name")
        or event.payload.get("tool")
        or event.detail
        or "tool"
    )


def _tool_status_from_event_type(event_type: str) -> str:
    if event_type in {"tool.requested"}:
        return "requested"
    if event_type in {"tool.started"}:
        return "running"
    if event_type in {"tool.approval_required", "agent.tool.approval_required"}:
        return "waiting_approval"
    if event_type in {"agent.tool.approval_approved"}:
        return "approved"
    if event_type in {"agent.tool.approval_rejected", "agent.tool.denied"}:
        return "denied"
    if event_type in {"tool.completed", "agent.tool.call", "agent.tool.completed"}:
        return "completed"
    if event_type in {"tool.failed", "agent.tool.failed"}:
        return "failed"
    if event_type in {"agent.tool.skipped"}:
        return "skipped"
    return "completed"


def _studio_url(run_id: str) -> str | None:
    return studio_run_url(run_id)


def _text(value: Any) -> str:
    return str(value or "").strip()


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
