"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .approvals import approval_card_from_payload, approval_cards_from_payloads
from .artifacts import artifact_snapshot_from_payload, artifact_snapshots_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    MemoryTraceSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    SkillTraceSnapshot,
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
        group_run_id = _group_run_id(payload)
        recent_events = self.events_from_payload(
            payload,
            run_id=run_id,
            keys=("recent_events", "events", "timeline"),
        )
        approvals = [
            approval
            for approval in self.approvals_from_payload(
                payload,
                run_id=run_id,
                group_run_id=group_run_id,
                keys=("pending_approvals", "pending_approval"),
                events=recent_events,
            )
            if approval.status == "pending"
        ]

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
            open_in_studio_url=_optional_text(payload.get("open_in_studio_url"))
            or _studio_url(run_id, group_run_id),
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
            group_run_id=group_run_id or "",
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
                return _merge_approvals(
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
        return _merge_artifacts(
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
        approvals = []
        active_by_key: dict[str, int] = {}
        for event in events:
            approval_payload = _approval_payload_from_event(event)
            if approval_payload:
                if group_run_id:
                    _merge_trace_context_into_approval(
                        approval_payload,
                        {"group_run_id": group_run_id},
                    )
                approval = approval_card_from_payload(
                    approval_payload,
                    run_id=event.run_id,
                    group_run_id=group_run_id or _group_run_id(event.payload),
                )
                key = _approval_correlation_key(approval_payload, approval)
                active_index = active_by_key.get(key) if key else None
                if active_index is None:
                    active_index = len(approvals)
                    approvals.append(approval)
                else:
                    approvals[active_index] = _merge_approval_snapshots(
                        approvals[active_index],
                        approval,
                    )
                if key:
                    if approval.status == "pending":
                        active_by_key[key] = active_index
                    else:
                        active_by_key.pop(key, None)
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
        input_preview = _mapping(payload.get("input_preview") or payload.get("input"))
        return ToolCallSnapshot(
            tool_call_id=tool_call_id,
            run_id=_optional_text(payload.get("run_id") or run_id),
            source_run_id=_optional_text(
                payload.get("source_run_id") or input_preview.get("source_run_id")
            ),
            source_runnable_id=_optional_text(
                payload.get("source_runnable_id")
                or payload.get("source_agent_id")
                or payload.get("member_agent_id")
                or payload.get("agent_id")
                or input_preview.get("source_runnable_id")
                or input_preview.get("member_agent_id")
                or input_preview.get("agent_id")
            ),
            source_runnable_name=_optional_text(
                payload.get("source_runnable_name")
                or payload.get("source_agent_name")
                or payload.get("member_agent_name")
                or payload.get("agent_name")
                or input_preview.get("source_runnable_name")
                or input_preview.get("member_agent_name")
                or input_preview.get("agent_name")
            ),
            workflow_id=_optional_text(payload.get("workflow_id") or input_preview.get("workflow_id")),
            workflow_run_id=_optional_text(
                payload.get("workflow_run_id") or input_preview.get("workflow_run_id")
            ),
            workflow_node_id=_optional_text(
                payload.get("workflow_node_id") or input_preview.get("workflow_node_id")
            ),
            workflow_node_label=_optional_text(
                payload.get("workflow_node_label") or input_preview.get("workflow_node_label")
            ),
            group_id=_optional_text(payload.get("group_id") or input_preview.get("group_id")),
            group_run_id=_optional_text(
                payload.get("group_run_id")
                or payload.get("run_group_id")
                or input_preview.get("group_run_id")
                or input_preview.get("run_group_id")
            ),
            tool_name=tool_name,
            status=_text(payload.get("status") or "completed"),
            risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
            input_preview=input_preview,
            output_preview=_tool_output_preview(payload),
            approval_id=_optional_text(payload.get("approval_id")),
            started_at=_text(payload.get("started_at") or payload.get("created_at")),
            completed_at=_optional_text(payload.get("completed_at")),
        )

    def tool_calls_from_events(self, events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
        calls: list[ToolCallSnapshot] = []
        active_by_key: dict[str, int] = {}
        for event in events:
            if not _is_tool_event(event.event_type):
                continue
            payload = _tool_call_payload_from_event(event)
            call = self.tool_call_from_payload(payload, run_id=event.run_id)
            key = _tool_call_correlation_key(payload, call)
            active_index = active_by_key.get(key) if key else None
            if active_index is None:
                active_index = len(calls)
                calls.append(call)
            else:
                calls[active_index] = _merge_tool_call_snapshots(calls[active_index], call)
            if key:
                if _tool_call_status_is_terminal(call.status):
                    active_by_key.pop(key, None)
                else:
                    active_by_key[key] = active_index
        return calls

    def memory_traces_from_events(self, events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
        traces: list[MemoryTraceSnapshot] = []
        for event in events:
            trace = _memory_trace_from_event(event)
            if trace is not None:
                traces.append(trace)
        return traces

    def skill_traces_from_events(self, events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
        traces: list[SkillTraceSnapshot] = []
        for event in events:
            trace = _skill_trace_from_event(event)
            if trace is not None:
                traces.append(trace)
        return traces

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


def memory_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
    return _PROJECTOR.memory_traces_from_events(events)


def skill_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
    return _PROJECTOR.skill_traces_from_events(events)


def _memory_trace_from_event(event: PublicRunEvent) -> MemoryTraceSnapshot | None:
    if not event.event_type.startswith("memory."):
        return None
    payload = dict(event.payload)
    result = _nested_mapping(payload, "result")
    memories = _mapping_items(payload.get("memories"))
    first_memory = memories[0] if memories else {}
    action = _memory_trace_action(event.event_type)
    memory_id = _optional_text(
        result.get("memory_id")
        or payload.get("memory_id")
        or first_memory.get("memory_id")
    )
    memory_kind = _optional_text(
        result.get("kind")
        or payload.get("memory_kind")
        or first_memory.get("kind")
    )
    memory_scope = _optional_text(
        result.get("scope")
        or payload.get("scope")
        or first_memory.get("scope")
    )
    count = _optional_int(payload.get("count"))
    if count is None:
        count = len(memories)
    detail_parts = [
        _optional_text(result.get("action")) or action,
        memory_kind,
        memory_scope,
    ]
    return MemoryTraceSnapshot(
        trace_id=_trace_id(event),
        run_id=event.run_id,
        event_id=_optional_text(event.event_id),
        sequence=event.sequence,
        event_type=event.event_type,
        status=_trace_status(payload.get("status") or result.get("status")),
        action=action,
        memory_id=memory_id,
        memory_kind=memory_kind,
        memory_scope=memory_scope,
        count=count,
        title=_memory_trace_title(event.event_type, action),
        detail=" · ".join(part for part in detail_parts if part),
        payload_preview=_trace_payload_preview(payload),
        created_at=event.created_at,
        **_trace_context_kwargs(payload),
    )


def _skill_trace_from_event(event: PublicRunEvent) -> SkillTraceSnapshot | None:
    if not event.event_type.startswith("skill."):
        return None
    payload = dict(event.payload)
    result = _nested_mapping(payload, "result")
    skill_id = _optional_text(result.get("skill_id") or payload.get("skill_id"))
    skill_name = _optional_text(result.get("name") or payload.get("skill_name"))
    source_ref = _optional_text(result.get("source_ref") or payload.get("source_ref"))
    source_type = _optional_text(result.get("source_type") or payload.get("source_type"))
    detail_parts = [
        _optional_text(result.get("description")),
        source_ref,
        source_type,
    ]
    return SkillTraceSnapshot(
        trace_id=_trace_id(event),
        run_id=event.run_id,
        event_id=_optional_text(event.event_id),
        sequence=event.sequence,
        event_type=event.event_type,
        status=_trace_status(payload.get("status") or result.get("status")),
        skill_id=skill_id,
        skill_name=skill_name,
        source_ref=source_ref,
        source_type=source_type,
        tool_name=_optional_text(payload.get("tool")),
        title=skill_name or _skill_trace_title(event.event_type),
        detail=" · ".join(part for part in detail_parts if part),
        payload_preview=_trace_payload_preview(payload),
        created_at=event.created_at,
        **_trace_context_kwargs(payload),
    )


def _trace_context_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_run_id": _optional_text(payload.get("source_run_id")),
        "source_runnable_id": _optional_text(
            payload.get("source_runnable_id")
            or payload.get("source_agent_id")
            or payload.get("member_agent_id")
            or payload.get("agent_id")
        ),
        "source_runnable_name": _optional_text(
            payload.get("source_runnable_name")
            or payload.get("source_agent_name")
            or payload.get("member_agent_name")
            or payload.get("agent_name")
        ),
        "workflow_id": _optional_text(payload.get("workflow_id")),
        "workflow_run_id": _optional_text(payload.get("workflow_run_id")),
        "workflow_node_id": _optional_text(payload.get("workflow_node_id")),
        "workflow_node_label": _optional_text(payload.get("workflow_node_label")),
        "group_id": _optional_text(payload.get("group_id")),
        "group_run_id": _optional_text(payload.get("group_run_id") or payload.get("run_group_id")),
    }


def _trace_id(event: PublicRunEvent) -> str:
    return _text(event.event_id) or f"{event.run_id}:{event.event_type}:{event.sequence}"


def _memory_trace_action(event_type: str) -> str:
    if event_type == "memory.retrieved":
        return "retrieved"
    if event_type.startswith("memory.write."):
        return event_type.rsplit(".", 1)[-1]
    return event_type


def _memory_trace_title(event_type: str, action: str) -> str:
    titles = {
        "memory.retrieved": "Memory retrieved",
        "memory.write.add": "Memory added",
        "memory.write.replace": "Memory updated",
        "memory.write.remove": "Memory removed",
    }
    return titles.get(event_type, f"Memory {action}")


def _skill_trace_title(event_type: str) -> str:
    if event_type == "skill.selected":
        return "Skill selected"
    if event_type.startswith("skill.dispatch."):
        return "Skill dispatched"
    return event_type


def _trace_status(value: Any) -> str:
    status = _text(value)
    if status == "ok":
        return "completed"
    return status or "completed"


def _trace_payload_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(payload)


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _approval_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    if event.event_type in {
        "agent.tool.approval_required",
        "group.approval_required",
        "group.member.approval_required",
        "tool.approval_required",
        "workflow.node.approval_required",
        "workflow.run.approval_required",
    }:
        return _approval_required_payload_from_event(event)
    if event.event_type in {
        "agent.tool.approval_approved",
        "agent.tool.approval_rejected",
        "agent.tool.approval_timeout",
        "approval.approved",
        "approval.rejected",
        "approval.timeout",
        "tool.approved",
        "tool.rejected",
        "workflow.node.approval_approved",
        "workflow.node.approval_rejected",
        "workflow.node.approval_timeout",
    }:
        return _approval_resolution_payload_from_event(event)
    return {}


def _approval_required_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    pending = payload.get("pending_approval") or payload.get("approval")
    source = dict(pending) if isinstance(pending, Mapping) else payload
    if not source and event.detail:
        source = {"tool": event.detail}
    if not source:
        return {}
    _normalize_approval_payload_for_event(source, event, payload)
    source.setdefault("approval_id", f"{event.run_id}:{event.event_type}:{event.sequence}")
    source.setdefault("status", "pending")
    source.setdefault("created_at", event.created_at)
    source.setdefault("run_id", event.run_id)
    return source


def _approval_resolution_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    pending = payload.get("pending_approval") or payload.get("approval")
    source = dict(pending) if isinstance(pending, Mapping) else payload
    if not source and event.detail:
        source = {"tool": event.detail}
    if not source:
        return {}
    _normalize_approval_payload_for_event(source, event, payload)
    source["status"] = _approval_status_from_event_type(event.event_type)
    source.setdefault("resolved_at", event.created_at)
    source.setdefault("run_id", event.run_id)
    if payload.get("reason") and not source.get("reason") and not source.get("description"):
        source["reason"] = payload.get("reason")
    if not source.get("approval_id"):
        source["approval_id"] = f"{event.run_id}:{event.event_type}:{event.sequence}"
    return source


def _normalize_approval_payload_for_event(
    source: dict[str, Any],
    event: PublicRunEvent,
    payload: dict[str, Any],
) -> None:
    if event.event_type.startswith("group.") and not source.get("tool"):
        source["tool"] = "group.approval"
    if (
        event.event_type.startswith("workflow.")
        or payload.get("workflow_node_id")
        or payload.get("workflow_run_id")
    ) and not source.get("tool"):
        source["tool"] = "workflow.approval"
    if not source.get("tool") and payload.get("tool"):
        source["tool"] = payload.get("tool")
    if not source.get("tool") and event.detail:
        source["tool"] = event.detail
    if not source.get("title") and payload.get("workflow_node_label"):
        source["title"] = f"Approve {payload['workflow_node_label']}"
    if not source.get("title") and payload.get("member_agent_name"):
        source["title"] = f"Approve {payload['member_agent_name']}"
    _merge_trace_context_into_approval(source, payload)


def _approval_status_from_event_type(event_type: str) -> str:
    if event_type.endswith("approval_approved") or event_type in {"approval.approved", "tool.approved"}:
        return "approved"
    if event_type.endswith("approval_rejected") or event_type in {"approval.rejected", "tool.rejected"}:
        return "rejected"
    if event_type.endswith("approval_timeout") or event_type == "approval.timeout":
        return "expired"
    return "pending"


def _tool_call_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    approval = _nested_mapping(payload, "pending_approval") or _nested_mapping(payload, "approval")
    approval_id = (
        _text(payload.get("approval_id"))
        or _text(approval.get("approval_id"))
        or _text(approval.get("id"))
    )
    risk_level = (
        _text(payload.get("risk_level"))
        or _text(payload.get("risk"))
        or _text(approval.get("risk_level"))
        or _text(approval.get("risk"))
    )
    policy_reason = (
        _text(payload.get("policy_reason"))
        or _text(approval.get("policy_reason"))
        or _text(approval.get("reason"))
    )
    normalized = {
        **payload,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "tool_name": _tool_name_from_event(event),
        "status": payload.get("status") or _tool_status_from_event_type(event.event_type),
        "created_at": event.created_at,
    }
    if approval_id:
        normalized.setdefault("approval_id", approval_id)
    if risk_level:
        normalized.setdefault("risk_level", risk_level)
    _merge_tool_trace_context(normalized, payload)
    _merge_tool_trace_into_input_preview(
        normalized,
        {
            "approval_id": approval_id,
            "risk_level": risk_level,
            "policy_reason": policy_reason,
            "group_id": payload.get("group_id"),
            "group_run_id": payload.get("group_run_id") or payload.get("run_group_id"),
            "member_agent_id": payload.get("member_agent_id"),
            "member_agent_name": payload.get("member_agent_name"),
            "workflow_id": payload.get("workflow_id"),
            "workflow_run_id": payload.get("workflow_run_id"),
            "workflow_node_id": payload.get("workflow_node_id"),
            "workflow_node_label": payload.get("workflow_node_label"),
        },
    )
    return normalized


def _merge_tool_trace_context(source: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in (
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
    ):
        if payload.get(key):
            source.setdefault(key, payload.get(key))
    if payload.get("run_group_id"):
        source.setdefault("group_run_id", payload.get("run_group_id"))
    if payload.get("member_agent_id"):
        source.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        source.setdefault("source_runnable_name", payload.get("member_agent_name"))
    if payload.get("agent_id"):
        source.setdefault("source_runnable_id", payload.get("agent_id"))
    if payload.get("agent_name"):
        source.setdefault("source_runnable_name", payload.get("agent_name"))


def _merge_tool_trace_into_input_preview(
    source: dict[str, Any],
    context: dict[str, Any],
) -> None:
    clean_context = {key: value for key, value in context.items() if value}
    if not clean_context:
        return
    input_preview = source.get("input_preview") or source.get("input")
    preview = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    for key, value in clean_context.items():
        preview.setdefault(key, value)
    source["input_preview"] = preview


def _artifact_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type == "artifact.created":
        artifact_payload = payload
    elif event.event_type in {"group.artifact.created", "group.shared_artifact.created"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        artifact_payload.setdefault("kind", "group_artifact")
        artifact_payload.setdefault("group_id", payload.get("group_id"))
        artifact_payload.setdefault(
            "group_run_id",
            payload.get("group_run_id") or payload.get("run_group_id") or event.run_id,
        )
        if payload.get("member_agent_name"):
            artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
        if payload.get("member_agent_id"):
            artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
        if payload.get("member_agent_name") and not artifact_payload.get("title"):
            artifact_path = _text(artifact_payload.get("path") or artifact_payload.get("artifact_path"))
            artifact_payload["title"] = (
                f"{payload['member_agent_name']} / {artifact_path or 'Artifact'}"
            )
    elif event.event_type == "workflow.node.artifact" and isinstance(payload.get("artifact"), Mapping):
        artifact_payload = {
            "kind": "workflow_artifact",
            "title": payload.get("workflow_node_label") or "Workflow Artifact",
            "workflow_id": payload.get("workflow_id"),
            "workflow_run_id": payload.get("workflow_run_id") or event.run_id,
            "workflow_node_id": payload.get("workflow_node_id"),
            "workflow_node_label": payload.get("workflow_node_label"),
            **dict(payload["artifact"]),
        }
    else:
        return {}
    _merge_artifact_trace_context(artifact_payload, payload)
    artifact_payload.setdefault("source_run_id", event.run_id)
    artifact_payload.setdefault("run_id", event.run_id)
    artifact_payload.setdefault("created_at", event.created_at)
    return artifact_payload


def _merge_artifact_trace_context(
    artifact_payload: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    for key in (
        "group_id",
        "group_run_id",
        "run_group_id",
        "source_tool",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        if payload.get(key):
            artifact_payload.setdefault(key, payload.get(key))
    if payload.get("member_agent_id"):
        artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))


def _merge_trace_context_into_approval(source: dict[str, Any], payload: dict[str, Any]) -> None:
    context = {
        key: payload.get(key)
        for key in (
            "group_id",
            "group_run_id",
            "run_group_id",
            "member_agent_id",
            "member_agent_name",
            "workflow_id",
            "workflow_run_id",
            "workflow_node_id",
            "workflow_node_label",
        )
        if payload.get(key)
    }
    if not context:
        return
    for key, value in context.items():
        source.setdefault(key, value)
    input_preview = source.get("input_preview")
    preview = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    for key, value in context.items():
        preview.setdefault(key, value)
    if preview:
        source["input_preview"] = preview


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


def _merge_approval_snapshots(
    current: ApprovalCardSnapshot,
    next_approval: ApprovalCardSnapshot,
) -> ApprovalCardSnapshot:
    return ApprovalCardSnapshot(
        approval_id=current.approval_id or next_approval.approval_id,
        run_id=current.run_id or next_approval.run_id,
        title=current.title or next_approval.title,
        description=next_approval.description or current.description,
        status=next_approval.status or current.status,
        tool_name=current.tool_name or next_approval.tool_name,
        risk_level=current.risk_level or next_approval.risk_level,
        input_preview={**current.input_preview, **next_approval.input_preview},
        policy_reason=current.policy_reason or next_approval.policy_reason,
        requested_at=current.requested_at or next_approval.requested_at,
        resolved_at=next_approval.resolved_at or current.resolved_at,
        open_in_studio_url=current.open_in_studio_url or next_approval.open_in_studio_url,
    )


def _approval_correlation_key(
    payload: Mapping[str, Any],
    approval: ApprovalCardSnapshot,
) -> str:
    run_id = approval.run_id or _text(payload.get("run_id"))
    tool_name = approval.tool_name or _text(payload.get("tool") or payload.get("tool_name"))
    preview = _approval_correlation_preview(approval.input_preview)
    workflow_node_id = _text(payload.get("workflow_node_id") or approval.input_preview.get("workflow_node_id"))
    group_run_id = _text(
        payload.get("group_run_id")
        or payload.get("run_group_id")
        or approval.input_preview.get("group_run_id")
        or approval.input_preview.get("run_group_id")
    )
    member_agent_id = _text(payload.get("member_agent_id") or approval.input_preview.get("member_agent_id"))
    if tool_name or workflow_node_id or group_run_id or member_agent_id or preview:
        return ":".join(
            [
                run_id,
                "approval",
                tool_name,
                workflow_node_id,
                group_run_id,
                member_agent_id,
                _stable_json(preview),
            ]
        )

    explicit_id = _text(
        payload.get("approval_id")
        or payload.get("id")
        or payload.get("approval_signature")
        or approval.approval_id
    )
    return f"{run_id}:approval_id:{explicit_id}" if explicit_id else ""


def _approval_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "approval_id",
        "group_id",
        "group_run_id",
        "member_agent_id",
        "member_agent_name",
        "policy_reason",
        "risk_level",
        "run_group_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_label",
        "workflow_run_id",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _merge_tool_call_snapshots(
    current: ToolCallSnapshot,
    next_call: ToolCallSnapshot,
) -> ToolCallSnapshot:
    output_preview = dict(current.output_preview)
    output_preview.update(next_call.output_preview)
    completed_at = next_call.completed_at or current.completed_at
    if _tool_call_status_is_terminal(next_call.status) and not completed_at:
        completed_at = next_call.started_at or current.completed_at
    return ToolCallSnapshot(
        tool_call_id=current.tool_call_id or next_call.tool_call_id,
        run_id=current.run_id or next_call.run_id,
        source_run_id=current.source_run_id or next_call.source_run_id,
        source_runnable_id=current.source_runnable_id or next_call.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_call.source_runnable_name,
        workflow_id=current.workflow_id or next_call.workflow_id,
        workflow_run_id=current.workflow_run_id or next_call.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_call.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_call.workflow_node_label,
        group_id=current.group_id or next_call.group_id,
        group_run_id=current.group_run_id or next_call.group_run_id,
        tool_name=current.tool_name or next_call.tool_name,
        status=next_call.status or current.status,
        risk_level=current.risk_level or next_call.risk_level,
        input_preview={**current.input_preview, **next_call.input_preview},
        output_preview=output_preview,
        approval_id=current.approval_id or next_call.approval_id,
        started_at=current.started_at or next_call.started_at,
        completed_at=completed_at,
    )


def _tool_call_correlation_key(
    payload: Mapping[str, Any],
    call: ToolCallSnapshot,
) -> str:
    explicit_id = _text(payload.get("tool_call_id") or payload.get("id"))
    run_id = call.run_id or _text(payload.get("run_id"))
    if explicit_id:
        return f"{run_id}:id:{explicit_id}"
    preview = _tool_call_correlation_preview(call.input_preview)
    return f"{run_id}:tool:{call.tool_name}:{_stable_json(preview)}"


def _tool_call_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "approval_id",
        "group_id",
        "group_run_id",
        "member_agent_id",
        "member_agent_name",
        "policy_reason",
        "risk_level",
        "run_group_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_label",
        "workflow_run_id",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _tool_call_status_is_terminal(status: str) -> bool:
    return status in {"completed", "failed", "denied", "skipped"}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


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


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
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
        "tool.approved",
        "tool.requested",
        "tool.started",
        "tool.approval_required",
        "tool.rejected",
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
    if event_type in {"agent.tool.approval_approved", "tool.approved"}:
        return "approved"
    if event_type in {"agent.tool.approval_rejected", "agent.tool.denied", "tool.rejected"}:
        return "denied"
    if event_type in {"tool.completed", "agent.tool.call", "agent.tool.completed"}:
        return "completed"
    if event_type in {"tool.failed", "agent.tool.failed"}:
        return "failed"
    if event_type in {"agent.tool.skipped"}:
        return "skipped"
    return "completed"


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _studio_url(run_id: str, group_run_id: str = "") -> str | None:
    return studio_run_url(run_id, group_run_id=group_run_id)


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
