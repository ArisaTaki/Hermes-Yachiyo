"""Studio-facing RunTimeline public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .approval_event_snapshots import (
    approval_snapshots_from_events,
    merge_approval_snapshot_lists,
)
from .approvals import approval_cards_from_payloads
from .artifact_event_snapshots import (
    artifact_snapshots_from_events,
    merge_artifact_snapshot_lists,
)
from .artifacts import artifact_snapshots_from_payloads as _artifact_snapshots_from_payloads
from .contracts import (
    ApprovalCardSnapshot,
    ArtifactSnapshot,
    PublicRunEvent,
    RunTimelineSnapshot,
)
from .task_snapshots import (
    run_events_from_payload,
    runtime_execution_envelope_from_payload,
    task_status_from_value,
)
from .task_core_snapshots import task_core_snapshot_from_payload
from .task_progress_snapshots import task_progress_summary_from_task_core
from .replan_event_projection import run_events_with_replan_requests
from .replan_recovery_snapshots import (
    merge_replan_recovery_snapshot_lists,
    replan_recovery_snapshots_from_events,
    replan_recovery_snapshots_from_runtime_execution_envelope,
)
from .runtime_debug_snapshots import runtime_debug_summary_from_runtime_objects
from .timeline_metadata_snapshots import (
    merge_timeline_child_snapshots,
    planner_trace_summary_from_payload,
    run_timeline_agent_id_from_payload,
    run_timeline_recovery_source_from_payload,
    timeline_child_snapshots_from_events,
    run_timeline_rerun_provenance_from_payload,
    timeline_child_snapshots_from_payloads,
    workflow_run_id_from_payload,
)
from .tool_call_snapshots import tool_call_snapshots_from_payloads
from .trace_snapshots import memory_trace_snapshots_from_events, skill_trace_snapshots_from_events


def run_timeline_snapshot_from_payload(
    payload: Mapping[str, Any] | RunTimelineSnapshot,
) -> RunTimelineSnapshot:
    if isinstance(payload, RunTimelineSnapshot):
        return payload

    run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
    events = run_events_from_payload(
        payload,
        run_id=run_id,
        keys=("events", "run_events", "timeline"),
    )
    events = run_events_with_replan_requests(
        payload,
        events,
        run_id=run_id,
        task_id=_text(payload.get("task_id")),
    )
    legacy_run_group_id = _optional_text(payload.get("run_group_id"))
    group_run_id = _optional_text(payload.get("group_run_id")) or legacy_run_group_id
    approvals = approval_snapshots_from_payload(
        payload,
        run_id=run_id,
        group_run_id=group_run_id or "",
        keys=("approvals", "pending_approval"),
        events=events,
    )
    pending_approval = _pending_timeline_approval(payload, approvals)
    rerun_provenance = run_timeline_rerun_provenance_from_payload(payload, events)
    recovery_source = run_timeline_recovery_source_from_payload(payload, events)
    task_core = task_core_snapshot_from_payload(payload, events=events)
    task_progress = task_progress_summary_from_task_core(
        task_core,
        events=events,
        needs_user_action=pending_approval is not None,
    )
    workflow_run_id = workflow_run_id_from_payload(payload, run_id)
    runtime_execution_envelope = runtime_execution_envelope_from_payload(
        payload,
        events=events,
    )
    replan_recoveries = merge_replan_recovery_snapshot_lists(
        replan_recovery_snapshots_from_events(
            events,
            run_id=run_id,
            task_id=_text(payload.get("task_id")),
            group_run_id=group_run_id or "",
            workflow_run_id=workflow_run_id,
        ),
        replan_recovery_snapshots_from_runtime_execution_envelope(
            runtime_execution_envelope,
            run_id=run_id,
            task_id=_text(payload.get("task_id")),
            group_run_id=group_run_id or "",
            workflow_run_id=workflow_run_id,
            task_progress=task_progress,
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        ),
    )
    tool_calls = tool_call_snapshots_from_payloads(
        payload.get("tool_calls"),
        run_id=run_id,
        events=events,
    )
    memory_traces = memory_trace_snapshots_from_events(events)
    skill_traces = skill_trace_snapshots_from_events(events)
    artifacts = artifact_snapshots_from_timeline_payload(
        payload,
        run_id=run_id,
        events=events,
    )
    children = merge_timeline_child_snapshots(
        timeline_child_snapshots_from_payloads(
            payload.get("children") or payload.get("child_run_ids")
        ),
        timeline_child_snapshots_from_events(events),
    )

    return RunTimelineSnapshot(
        run_id=run_id,
        parent_run_id=_optional_text(payload.get("parent_run_id")),
        group_run_id=group_run_id,
        run_group_id=legacy_run_group_id or group_run_id,
        workflow_run_id=workflow_run_id_from_payload(payload, run_id),
        agent_id=_optional_text(payload.get("agent_id") or run_timeline_agent_id_from_payload(payload)),
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
        planner_summary=planner_trace_summary_from_payload(payload),
        runtime_debug=runtime_debug_summary_from_runtime_objects(
            run_id=run_id,
            task_id=_text(payload.get("task_id")),
            group_run_id=group_run_id or "",
            workflow_run_id=workflow_run_id,
            events=events,
            tool_calls=tool_calls,
            approvals=approvals,
            pending_approval=pending_approval,
            artifacts=artifacts,
            memory_traces=memory_traces,
            skill_traces=skill_traces,
            children=children,
            replan_recoveries=replan_recoveries,
            needs_user_action=pending_approval is not None,
            needs_replan=bool(task_progress and task_progress.needs_replan),
        ),
        runtime_execution_envelope=runtime_execution_envelope,
        task_core=task_core,
        task_progress=task_progress,
        replan_recoveries=replan_recoveries,
        recovery_source=recovery_source,
        events=events,
        tool_calls=tool_calls,
        memory_traces=memory_traces,
        skill_traces=skill_traces,
        approvals=approvals,
        pending_approval=pending_approval,
        artifacts=artifacts,
        children=children,
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def approval_snapshots_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    group_run_id: str = "",
    keys: tuple[str, ...],
    events: list[PublicRunEvent] | None = None,
) -> list[ApprovalCardSnapshot]:
    for key in keys:
        approvals = approval_cards_from_payloads(
            payload.get(key),
            run_id=run_id,
            group_run_id=group_run_id,
        )
        if approvals:
            return merge_approval_snapshot_lists(
                approvals,
                approval_snapshots_from_events(events or [], group_run_id=group_run_id),
            )
    return approval_snapshots_from_events(events or [], group_run_id=group_run_id)


def approval_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
    group_run_id: str = "",
) -> list[ApprovalCardSnapshot]:
    return approval_cards_from_payloads(
        payloads,
        run_id=run_id,
        group_run_id=group_run_id,
    )


def artifact_snapshots_from_timeline_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    events: list[PublicRunEvent] | None = None,
) -> list[ArtifactSnapshot]:
    return merge_artifact_snapshot_lists(
        artifact_snapshots_from_payloads(payload.get("artifacts"), run_id=run_id),
        artifact_snapshots_from_events(events or []),
    )


def artifact_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
) -> list[ArtifactSnapshot]:
    return _artifact_snapshots_from_payloads(payloads, run_id=run_id)


def _pending_timeline_approval(
    payload: Mapping[str, Any],
    approvals: list[ApprovalCardSnapshot],
) -> ApprovalCardSnapshot | None:
    if (
        isinstance(payload.get("pending_approval"), Mapping)
        and payload.get("pending_approval")
        and approvals
    ):
        return next(
            (approval for approval in approvals if approval.status == "pending"),
            None,
        )
    if task_status_from_value(payload.get("status")) == "waiting_approval" and approvals:
        return next(
            (approval for approval in approvals if approval.status == "pending"),
            None,
        )
    return None


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
