"""GroupRun public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import (
    AgentGroupMemberSnapshot,
    ApprovalCardSnapshot,
    ArtifactSnapshot,
    GroupRunSnapshot,
    MemoryTraceSnapshot,
    ReplanRecoverySnapshot,
    RunTimelineSnapshot,
    SkillTraceSnapshot,
    ToolCallSnapshot,
)
from .group_member_snapshots import group_run_participants_from_payload
from .replan_event_projection import run_events_with_replan_requests
from .replan_recovery_snapshots import (
    merge_replan_recovery_snapshot_lists,
    replan_recovery_snapshots_from_events,
    replan_recovery_snapshots_from_runtime_execution_envelope,
)
from .run_snapshots import RunSnapshotProjector
from .runtime_debug_snapshots import runtime_debug_summary_from_runtime_objects
from .runtime_execution import runtime_execution_envelope_payload_with_request_context
from .task_snapshots import runtime_execution_envelope_from_payload
from .task_core_snapshots import task_core_snapshot_from_payload
from .task_progress_snapshots import task_progress_summary_from_task_core
from .timeline_metadata_snapshots import planner_trace_summary_from_payload

_RUN_PROJECTOR = RunSnapshotProjector()


def group_run_snapshot_from_payload(
    payload: Mapping[str, Any] | GroupRunSnapshot,
) -> GroupRunSnapshot:
    if isinstance(payload, GroupRunSnapshot):
        return payload

    legacy_run_group_id = _optional_text(payload.get("run_group_id"))
    group_run_id = _text(payload.get("group_run_id") or legacy_run_group_id)
    group_id = _text(payload.get("group_id") or payload.get("agent_group_id"))
    runs_payload = payload.get("runs") or payload.get("child_runs") or []
    child_run_ids = [_text(item) for item in payload.get("child_run_ids") or [] if _text(item)]
    participants = group_run_participants_from_payload(payload)
    event_payload = dict(payload)
    event_payload["events"] = group_run_events_with_lifecycle(
        payload,
        group_run_id=group_run_id,
        group_id=group_id,
        objective=_text(payload.get("objective") or payload.get("user_goal")),
        child_run_ids=child_run_ids,
    )
    events = _RUN_PROJECTOR.events_from_payload(
        event_payload,
        run_id=group_run_id,
        keys=("events",),
    )
    events = run_events_with_replan_requests(
        payload,
        events,
        run_id=group_run_id,
        task_id=_text(payload.get("task_id")),
    )
    planner_summary = planner_trace_summary_from_payload({**dict(payload), "events": events})
    runs = [
        _RUN_PROJECTOR.timeline_snapshot_from_payload(
            group_run_child_payload(
                item,
                group_run_id=group_run_id,
                group_id=group_id,
            )
        )
        for item in runs_payload
        if isinstance(item, Mapping)
    ]
    tool_calls = _group_run_tool_calls(
        payload,
        runs,
        events,
        group_run_id=group_run_id,
        group_id=group_id,
    )
    shared_artifacts = _group_run_shared_artifacts(
        payload,
        runs,
        events,
        group_run_id=group_run_id,
        group_id=group_id,
    )
    pending_approvals = _group_run_pending_approvals(
        payload,
        runs,
        events,
        group_run_id=group_run_id,
        group_id=group_id,
    )
    task_core = task_core_snapshot_from_payload(payload, events=events)
    task_progress = task_progress_summary_from_task_core(
        task_core,
        events=events,
        needs_user_action=bool(pending_approvals),
    )
    runtime_execution_envelope = runtime_execution_envelope_from_payload(
        payload,
        events=events,
    )
    replan_recoveries = _group_run_replan_recoveries(
        runs,
        events,
        runtime_execution_envelope=runtime_execution_envelope,
        task_progress=task_progress,
        group_run_id=group_run_id,
        task_id=_text(payload.get("task_id")),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )
    memory_traces = _group_run_memory_traces(runs, events)
    skill_traces = _group_run_skill_traces(runs, events)
    return GroupRunSnapshot(
        group_run_id=group_run_id,
        run_group_id=legacy_run_group_id or group_run_id or None,
        group_id=group_id,
        title=_text(payload.get("title") or "Group run"),
        status=_text(payload.get("status") or "unknown"),
        objective=_text(payload.get("objective") or payload.get("user_goal")),
        participants=_participants_with_run_rollup(
            participants,
            runs,
            tool_calls,
            pending_approvals,
            shared_artifacts,
        ),
        active_speaker_agent_id=_optional_text(payload.get("active_speaker_agent_id")),
        task_core=task_core,
        task_progress=task_progress,
        planner_summary=planner_summary,
        runtime_execution_envelope=runtime_execution_envelope,
        runtime_debug=runtime_debug_summary_from_runtime_objects(
            run_id=group_run_id,
            group_id=group_id,
            group_run_id=group_run_id,
            events=events,
            tool_calls=tool_calls,
            approvals=pending_approvals,
            artifacts=shared_artifacts,
            memory_traces=memory_traces,
            skill_traces=skill_traces,
            children=runs,
            replan_recoveries=replan_recoveries,
            planner_summary=planner_summary,
            runtime_execution_envelope=runtime_execution_envelope,
            task_core=task_core,
            task_progress=task_progress,
            needs_user_action=bool(pending_approvals),
            needs_replan=bool(task_progress and task_progress.needs_replan),
        ),
        replan_recoveries=replan_recoveries,
        events=events,
        runs=runs,
        child_run_ids=child_run_ids,
        tool_calls=tool_calls,
        memory_traces=memory_traces,
        skill_traces=skill_traces,
        shared_artifacts=shared_artifacts,
        pending_approvals=pending_approvals,
        final_answer=_optional_text(payload.get("final_answer") or payload.get("summary")),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def group_run_events_with_lifecycle(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
    objective: str,
    child_run_ids: list[str],
) -> list[dict[str, Any]]:
    raw_events = _raw_events_from_payload(
        payload,
        ("events", "run_events", "recent_events", "timeline"),
    )
    if not group_run_id:
        return raw_events
    raw_events = _group_run_stream_events(
        raw_events,
        group_run_id=group_run_id,
        group_id=group_id,
    )
    raw_events = _group_scoped_planner_events(raw_events)

    existing_types = {_event_type(event) for event in raw_events}
    lifecycle_context = _group_run_lifecycle_context(
        payload,
        group_run_id=group_run_id,
        group_id=group_id,
        objective=objective,
        child_run_ids=child_run_ids,
    )
    events: list[dict[str, Any]] = []
    if "group.run.started" not in existing_types:
        events.append(
            _group_run_lifecycle_event(
                "group.run.started",
                payload,
                lifecycle_context,
                created_at=_text(payload.get("created_at")),
            )
        )
    events.extend(raw_events)

    terminal_event_type = _group_run_terminal_event_type(payload.get("status"))
    if terminal_event_type and terminal_event_type not in existing_types:
        events.append(
            _group_run_lifecycle_event(
                terminal_event_type,
                payload,
                {**lifecycle_context, "status": _text(payload.get("status"))},
                created_at=_text(payload.get("updated_at") or payload.get("created_at")),
            )
        )
    return events


def group_run_child_payload(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    child = dict(payload)
    if group_run_id:
        child.setdefault("group_run_id", group_run_id)
        child.setdefault("run_group_id", group_run_id)
    if group_id:
        child.setdefault("group_id", group_id)
    for key in ("events", "run_events", "recent_events", "timeline"):
        value = child.get(key)
        if isinstance(value, list):
            child[key] = [
                _group_run_child_event_context(
                    item,
                    group_run_id=group_run_id,
                    group_id=group_id,
                )
                for item in value
                if isinstance(item, Mapping)
            ]
    return child


def _group_run_tool_calls(
    payload: Mapping[str, Any],
    runs: list[RunTimelineSnapshot],
    events: list[Any],
    *,
    group_run_id: str,
    group_id: str,
) -> list[ToolCallSnapshot]:
    direct_tool_calls = (
        _RUN_PROJECTOR.tool_calls_from_payload(payload.get("tool_calls"), run_id=group_run_id)
        if isinstance(payload.get("tool_calls"), list)
        else []
    )
    child_tool_calls = [tool_call for run in runs for tool_call in run.tool_calls]
    event_tool_calls = (
        []
        if direct_tool_calls or child_tool_calls
        else _RUN_PROJECTOR.tool_calls_from_events(events)
    )
    return _unique_by(
        [
            _group_context_tool_call(
                tool_call,
                group_run_id=group_run_id,
                group_id=group_id,
            )
            for tool_call in [*direct_tool_calls, *child_tool_calls, *event_tool_calls]
        ],
        lambda tool_call: tool_call.tool_call_id,
    )


def _group_run_memory_traces(
    runs: list[RunTimelineSnapshot],
    events: list[Any],
) -> list[MemoryTraceSnapshot]:
    child_traces = [trace for run in runs for trace in run.memory_traces]
    event_traces = [] if child_traces else _RUN_PROJECTOR.memory_traces_from_events(events)
    return _unique_by(
        [*child_traces, *event_traces],
        lambda trace: trace.trace_id,
    )


def _group_run_skill_traces(
    runs: list[RunTimelineSnapshot],
    events: list[Any],
) -> list[SkillTraceSnapshot]:
    child_traces = [trace for run in runs for trace in run.skill_traces]
    event_traces = [] if child_traces else _RUN_PROJECTOR.skill_traces_from_events(events)
    return _unique_by(
        [*child_traces, *event_traces],
        lambda trace: trace.trace_id,
    )


def _group_run_shared_artifacts(
    payload: Mapping[str, Any],
    runs: list[RunTimelineSnapshot],
    events: list[Any],
    *,
    group_run_id: str,
    group_id: str,
) -> list[ArtifactSnapshot]:
    direct_artifacts = _RUN_PROJECTOR.artifacts_from_payload(
        {"artifacts": payload.get("shared_artifacts") or payload.get("artifacts")},
        run_id=group_run_id,
        events=events,
    )
    direct_artifacts = [
        _group_context_artifact(artifact, group_run_id=group_run_id, group_id=group_id)
        for artifact in direct_artifacts
    ]
    child_artifacts = [
        _group_context_artifact(artifact, group_run_id=group_run_id, group_id=group_id)
        for run in runs
        for artifact in run.artifacts
    ]
    return _unique_by(
        [*direct_artifacts, *child_artifacts],
        _artifact_identity,
    )


def _group_run_pending_approvals(
    payload: Mapping[str, Any],
    runs: list[RunTimelineSnapshot],
    events: list[Any],
    *,
    group_run_id: str,
    group_id: str,
) -> list[ApprovalCardSnapshot]:
    direct_and_event_approvals = [
        approval
        for approval in _RUN_PROJECTOR.approvals_from_payload(
            payload,
            run_id=group_run_id,
            group_run_id=group_run_id,
            keys=("pending_approvals", "pending_approval"),
            events=events,
        )
        if approval.status == "pending"
    ]
    child_approvals = [
        approval
        for run in runs
        for approval in [*run.approvals, *([run.pending_approval] if run.pending_approval else [])]
        if approval.status == "pending"
    ]
    return _unique_by(
        [
            _group_context_approval(
                approval,
                group_run_id=group_run_id,
                group_id=group_id,
            )
            for approval in [*direct_and_event_approvals, *child_approvals]
        ],
        lambda approval: approval.approval_id,
    )


def _group_run_replan_recoveries(
    runs: list[RunTimelineSnapshot],
    events: list[Any],
    *,
    runtime_execution_envelope: Any,
    task_progress: Any,
    group_run_id: str,
    task_id: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> list[ReplanRecoverySnapshot]:
    direct_recoveries = replan_recovery_snapshots_from_events(
        events,
        run_id=group_run_id,
        group_run_id=group_run_id,
    )
    runtime_recoveries = replan_recovery_snapshots_from_runtime_execution_envelope(
        runtime_execution_envelope,
        run_id=group_run_id,
        task_id=task_id,
        group_run_id=group_run_id,
        task_progress=task_progress,
        created_at=created_at,
        updated_at=updated_at,
    )
    child_recoveries = [
        _group_context_replan_recovery(recovery, group_run_id=group_run_id)
        for run in runs
        for recovery in run.replan_recoveries
    ]
    return merge_replan_recovery_snapshot_lists(
        direct_recoveries,
        runtime_recoveries,
        child_recoveries,
    )


def _group_context_replan_recovery(
    recovery: ReplanRecoverySnapshot,
    *,
    group_run_id: str,
) -> ReplanRecoverySnapshot:
    if recovery.group_run_id:
        return recovery
    return recovery.model_copy(update={"group_run_id": group_run_id or None})


def _group_context_tool_call(
    tool_call: ToolCallSnapshot,
    *,
    group_run_id: str,
    group_id: str,
) -> ToolCallSnapshot:
    return tool_call.model_copy(
        update={
            "source_run_id": tool_call.source_run_id or tool_call.run_id,
            "group_run_id": tool_call.group_run_id or group_run_id or None,
            "group_id": tool_call.group_id or group_id or None,
        }
    )


def _group_context_approval(
    approval: ApprovalCardSnapshot,
    *,
    group_run_id: str,
    group_id: str,
) -> ApprovalCardSnapshot:
    return approval.model_copy(
        update={
            "source_run_id": approval.source_run_id or approval.run_id,
            "group_run_id": approval.group_run_id or group_run_id or None,
            "group_id": approval.group_id or group_id or None,
        }
    )


def _group_context_artifact(
    artifact: ArtifactSnapshot,
    *,
    group_run_id: str,
    group_id: str,
) -> ArtifactSnapshot:
    return artifact.model_copy(
        update={
            "group_run_id": artifact.group_run_id or group_run_id or None,
            "group_id": artifact.group_id or group_id or None,
        }
    )


def _participants_with_run_rollup(
    participants: list[AgentGroupMemberSnapshot],
    runs: list[RunTimelineSnapshot],
    tool_calls: list[ToolCallSnapshot],
    approvals: list[ApprovalCardSnapshot],
    artifacts: list[ArtifactSnapshot],
) -> list[AgentGroupMemberSnapshot]:
    if not participants:
        return []
    by_agent_id: dict[str, list[RunTimelineSnapshot]] = {}
    for run in runs:
        agent_id = _text(run.agent_id)
        if agent_id:
            by_agent_id.setdefault(agent_id, []).append(run)
    all_member_run_ids = {
        _text(run.run_id)
        for member_runs in by_agent_id.values()
        for run in member_runs
        if _text(run.run_id)
    }
    single_participant = len(participants) == 1

    enriched: list[AgentGroupMemberSnapshot] = []
    for participant in participants:
        member_runs = by_agent_id.get(participant.agent_id, [])
        member_run_ids = {_text(run.run_id) for run in member_runs if _text(run.run_id)}
        primary_run = member_runs[0] if member_runs else None
        enriched.append(
            participant.model_copy(
                update={
                    "run_id": participant.run_id or (primary_run.run_id if primary_run else None),
                    "run_status": participant.run_status
                    or (primary_run.status if primary_run else None),
                    "tool_calls": _unique_by(
                        [
                            *participant.tool_calls,
                            *[
                                item
                                for item in tool_calls
                                if _snapshot_belongs_to_member(
                                    item,
                                    agent_id=participant.agent_id,
                                    run_ids=member_run_ids,
                                )
                            ],
                        ],
                        lambda item: item.tool_call_id,
                    ),
                    "pending_approvals": _unique_by(
                        [
                            *participant.pending_approvals,
                            *[
                                item
                                for item in approvals
                                if _snapshot_belongs_to_member(
                                    item,
                                    agent_id=participant.agent_id,
                                    run_ids=member_run_ids,
                                )
                                or (
                                    single_participant
                                    and _snapshot_is_group_scoped_without_member(
                                        item,
                                        child_run_ids=all_member_run_ids,
                                    )
                                )
                            ],
                        ],
                        lambda item: item.approval_id,
                    ),
                    "artifacts": _unique_by(
                        [
                            *participant.artifacts,
                            *[
                                item
                                for item in artifacts
                                if _snapshot_belongs_to_member(
                                    item,
                                    agent_id=participant.agent_id,
                                    run_ids=member_run_ids,
                                )
                            ],
                        ],
                        _artifact_identity,
                    ),
                }
            )
        )
    return enriched


def _snapshot_is_group_scoped_without_member(item: Any, *, child_run_ids: set[str]) -> bool:
    if _text(getattr(item, "source_runnable_id", "")):
        return False
    item_run_id = _text(getattr(item, "run_id", ""))
    source_run_id = _text(getattr(item, "source_run_id", ""))
    return item_run_id not in child_run_ids and source_run_id not in child_run_ids


def _snapshot_belongs_to_member(item: Any, *, agent_id: str, run_ids: set[str]) -> bool:
    if not agent_id:
        return False
    return (
        _text(getattr(item, "source_runnable_id", "")) == agent_id
        or _text(getattr(item, "run_id", "")) in run_ids
        or _text(getattr(item, "source_run_id", "")) in run_ids
    )


def _artifact_identity(artifact: ArtifactSnapshot) -> str:
    return _text(
        artifact.artifact_id
        or f"{artifact.source_run_id or artifact.run_id or ''}:{artifact.path or artifact.title}"
    )


def _unique_by(items: list[Any], key_fn: Any) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in items:
        key = _text(key_fn(item))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _group_run_stream_events(
    events: list[dict[str, Any]],
    *,
    group_run_id: str,
    group_id: str,
) -> list[dict[str, Any]]:
    return [
        _group_run_stream_event(
            event,
            group_run_id=group_run_id,
            group_id=group_id,
        )
        for event in events
    ]


def _group_run_stream_event(
    event: dict[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    payload.setdefault("group_run_id", group_run_id)
    if group_id:
        payload.setdefault("group_id", group_id)
    item["payload"] = payload

    event_run_id = _text(item.get("run_id"))
    if not event_run_id or event_run_id == group_run_id or "sequence" not in item:
        return item

    source_sequence = item.pop("sequence")
    payload.setdefault("source_run_id", event_run_id)
    payload.setdefault("source_sequence", source_sequence)
    item["payload"] = payload
    return item


def _group_run_child_event_context(
    event: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    timeline_payload = {
        key: item.get(key)
        for key in (
            "input_preview",
            "input",
            "output_preview",
            "result",
            "pending_approval",
            "approval",
            "artifact",
        )
        if key in item
    }
    payload = {**timeline_payload, **payload}
    if group_run_id:
        payload.setdefault("group_run_id", group_run_id)
        payload.setdefault("run_group_id", group_run_id)
    if group_id:
        payload.setdefault("group_id", group_id)
    if payload:
        item["payload"] = payload
    return item


def _raw_events_from_payload(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("event"))


_GROUP_PLANNER_EVENT_TYPES = {
    "agent.intent.selected": "group.run.intent.selected",
    "agent.plan.created": "group.run.plan.created",
    "agent.task_core.created": "group.run.task_core.created",
    "agent.plan.step": "group.run.plan.step",
    "agent.plan.selection": "group.run.plan.selection",
    "agent.replan.requested": "group.run.replan.requested",
    "agent.replan.recovery.updated": "group.run.replan.recovery.updated",
    "agent.desktop.intent_planned": "group.run.desktop.intent_planned",
    "agent.tool.approval_required": "group.run.tool.approval_required",
    "agent.desktop.intent_approval_required": "group.run.desktop.intent_approval_required",
    "agent.desktop.intent_completed": "group.run.desktop.intent_completed",
    "agent.desktop.intent_unavailable": "group.run.desktop.intent_unavailable",
    "agent.desktop.permission_recovery": "group.run.desktop.permission_recovery",
    "agent.desktop.readiness_recovered": "group.run.desktop.readiness_recovered",
    "agent.task.workspace_item.updated": "group.run.task.workspace_item.updated",
    "agent.task.todo.updated": "group.run.task.todo.updated",
    "agent.task.checkpoint.updated": "group.run.task.checkpoint.updated",
}


def _group_scoped_planner_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoped_events: list[dict[str, Any]] = []
    for event in events:
        event_type = _event_type(event)
        group_type = _GROUP_PLANNER_EVENT_TYPES.get(event_type)
        if not group_type:
            scoped_events.append(event)
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        scoped_payload = {
            **dict(payload),
            "planner_event_type": str(
                payload.get("planner_event_type") or event_type
            ),
            "planner_scope": str(payload.get("planner_scope") or "group_run"),
        }
        envelope = scoped_payload.get("runtime_execution_envelope")
        if isinstance(envelope, Mapping):
            group_run_id = _text(scoped_payload.get("group_run_id"))
            scoped_payload["runtime_execution_envelope"] = (
                runtime_execution_envelope_payload_with_request_context(
                    envelope,
                    {
                        "group_run_id": group_run_id,
                        "run_group_id": _text(scoped_payload.get("run_group_id")) or group_run_id,
                        "group_id": _text(scoped_payload.get("group_id")),
                    },
                )
            )
        scoped_events.append(
            {
                **event,
                "event_type": group_type,
                "payload": scoped_payload,
            }
        )
    return scoped_events


def _group_run_lifecycle_context(
    payload: Mapping[str, Any],
    *,
    group_run_id: str,
    group_id: str,
    objective: str,
    child_run_ids: list[str],
) -> dict[str, Any]:
    return {
        "group_run_id": group_run_id,
        "run_group_id": _text(payload.get("run_group_id") or group_run_id),
        "group_id": group_id,
        "objective": objective,
        "status": _text(payload.get("status") or "unknown"),
        "child_run_ids": child_run_ids,
        "participant_count": len(group_run_participants_from_payload(payload)),
    }


def _group_run_lifecycle_event(
    event_type: str,
    payload: Mapping[str, Any],
    lifecycle_context: dict[str, Any],
    *,
    created_at: str = "",
) -> dict[str, Any]:
    label = _text(payload.get("title") or payload.get("objective") or "Group run")
    event = {
        "event_type": event_type,
        "detail": label,
        "payload": dict(lifecycle_context),
    }
    if created_at:
        event["created_at"] = created_at
    return event


def _group_run_terminal_event_type(value: Any) -> str:
    status = _text(value)
    if status == "completed":
        return "group.run.completed"
    if status == "failed":
        return "group.run.failed"
    if status == "cancelled":
        return "group.run.cancelled"
    return ""


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
