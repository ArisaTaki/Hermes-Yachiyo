"""WorkflowRun public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import (
    ApprovalCardSnapshot,
    ArtifactSnapshot,
    PublicRunEvent,
    RunTimelineSnapshot,
    ToolCallSnapshot,
    WorkflowRunSnapshot,
)
from .run_snapshots import RunSnapshotProjector, run_timeline_snapshot_from_payload
from .runtime_debug_snapshots import runtime_debug_summary_from_runtime_objects
from .timeline_metadata_snapshots import merge_timeline_child_snapshots

_RUN_PROJECTOR = RunSnapshotProjector()


def workflow_run_snapshot_from_payload(
    payload: Mapping[str, Any] | WorkflowRunSnapshot,
) -> WorkflowRunSnapshot:
    if isinstance(payload, WorkflowRunSnapshot):
        return payload

    timeline = run_timeline_snapshot_from_payload(workflow_run_payload_with_lifecycle(payload))
    workflow_event_context = workflow_event_context_from_events(timeline.events)
    workflow_id = _optional_text(
        payload.get("workflow_id")
        or workflow_event_context.get("workflow_id")
        or payload.get("runnable_id")
    )
    workflow_run_id = _text(
        payload.get("workflow_run_id") or payload.get("run_id") or timeline.run_id
    )
    child_payloads = _workflow_child_run_payloads(
        payload,
        workflow_id=workflow_id or "",
        workflow_run_id=workflow_run_id,
    )
    child_runs = [
        run_timeline_snapshot_from_payload(item)
        for item in child_payloads
        if isinstance(item, Mapping)
    ]
    child_approvals = _child_approvals(child_runs)
    timeline_payload = timeline.model_dump(mode="python")
    timeline_payload.update(
        {
            "tool_calls": _unique_by(
                _workflow_context_tool_calls(
                    timeline.tool_calls,
                    workflow_id=workflow_id or "",
                    workflow_run_id=workflow_run_id,
                ),
                lambda item: item.tool_call_id,
            ),
            "approvals": _unique_by(
                _workflow_context_approvals(
                    timeline.approvals,
                    workflow_id=workflow_id or "",
                    workflow_run_id=workflow_run_id,
                ),
                lambda item: item.approval_id,
            ),
            "pending_approval": _workflow_context_approval(
                _preferred_workflow_pending_approval(
                    timeline.pending_approval,
                    child_approvals,
                ),
                workflow_id=workflow_id or "",
                workflow_run_id=workflow_run_id,
            ),
            "artifacts": _unique_by(
                _workflow_context_artifacts(
                    timeline.artifacts,
                    workflow_id=workflow_id or "",
                    workflow_run_id=workflow_run_id,
                ),
                _artifact_identity,
            ),
        }
    )
    if child_runs:
        workflow_tool_calls = _workflow_context_tool_calls(
            [*timeline.tool_calls, *_child_items(child_runs, "tool_calls")],
            workflow_id=workflow_id or "",
            workflow_run_id=workflow_run_id,
        )
        workflow_approvals = _workflow_context_approvals(
            [*timeline.approvals, *child_approvals],
            workflow_id=workflow_id or "",
            workflow_run_id=workflow_run_id,
        )
        workflow_artifacts = _workflow_context_artifacts(
            [*timeline.artifacts, *_child_items(child_runs, "artifacts")],
            workflow_id=workflow_id or "",
            workflow_run_id=workflow_run_id,
        )
        timeline_payload.update(
            {
                "children": merge_timeline_child_snapshots(
                    timeline.children,
                    _RUN_PROJECTOR.timeline_children_from_payloads(child_payloads),
                ),
                "tool_calls": _unique_by(
                    workflow_tool_calls,
                    lambda item: item.tool_call_id,
                ),
                "approvals": _unique_by(
                    workflow_approvals,
                    lambda item: item.approval_id,
                ),
                "pending_approval": _workflow_context_approval(
                    _preferred_workflow_pending_approval(
                        timeline.pending_approval,
                        child_approvals,
                    ),
                    workflow_id=workflow_id or "",
                    workflow_run_id=workflow_run_id,
                ),
                "artifacts": _unique_by(
                    workflow_artifacts,
                    _artifact_identity,
                ),
                "memory_traces": _unique_by(
                    [*timeline.memory_traces, *_child_items(child_runs, "memory_traces")],
                    lambda item: item.trace_id,
                ),
                "skill_traces": _unique_by(
                    [*timeline.skill_traces, *_child_items(child_runs, "skill_traces")],
                    lambda item: item.trace_id,
                ),
                "replan_recoveries": _unique_by(
                    [
                        *timeline.replan_recoveries,
                        *_child_items(child_runs, "replan_recoveries"),
                    ],
                    lambda item: item.request_id,
                ),
            }
        )
    task_progress = timeline_payload.get("task_progress")
    timeline_payload["runtime_debug"] = runtime_debug_summary_from_runtime_objects(
        run_id=workflow_run_id,
        task_id=_text(payload.get("task_id")),
        workflow_id=workflow_id or "",
        workflow_run_id=workflow_run_id,
        events=timeline_payload.get("events"),
        tool_calls=timeline_payload.get("tool_calls"),
        approvals=timeline_payload.get("approvals"),
        pending_approval=timeline_payload.get("pending_approval"),
        artifacts=timeline_payload.get("artifacts"),
        memory_traces=timeline_payload.get("memory_traces"),
        skill_traces=timeline_payload.get("skill_traces"),
        children=timeline_payload.get("children"),
        replan_recoveries=timeline_payload.get("replan_recoveries"),
        planner_summary=timeline_payload.get("planner_summary"),
        runtime_execution_envelope=timeline_payload.get("runtime_execution_envelope"),
        task_core=timeline_payload.get("task_core"),
        task_progress=task_progress,
        needs_user_action=timeline_payload.get("pending_approval") is not None,
        needs_replan=bool(
            task_progress.get("needs_replan")
            if isinstance(task_progress, Mapping)
            else getattr(task_progress, "needs_replan", False)
        ),
    )
    return WorkflowRunSnapshot(
        **timeline_payload,
        workflow_id=workflow_id,
        objective=_text(payload.get("objective") or payload.get("user_goal") or timeline.title),
        current_node_id=_optional_text(
            payload.get("current_node_id")
            or payload.get("workflow_node_id")
            or workflow_event_context.get("workflow_node_id")
        ),
        current_node_label=_optional_text(
            payload.get("current_node_label")
            or payload.get("workflow_node_label")
            or workflow_event_context.get("workflow_node_label")
        ),
        final_answer=_optional_text(payload.get("final_answer") or payload.get("result")),
    )


def is_workflow_run_payload(payload: Any) -> bool:
    if isinstance(payload, WorkflowRunSnapshot):
        return True
    if not isinstance(payload, Mapping):
        return False
    run_id = _text(payload.get("run_id"))
    workflow_run_id = _text(payload.get("workflow_run_id"))
    return (
        _text(payload.get("kind")) == "workflow_run"
        or bool(_text(payload.get("workflow_id")))
        or bool(workflow_run_id and workflow_run_id == run_id)
    )


def workflow_run_payload_with_lifecycle(payload: Mapping[str, Any]) -> dict[str, Any]:
    run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
    if not run_id:
        return dict(payload)

    lifecycle_context = _workflow_lifecycle_context(payload, run_id)
    raw_events = _workflow_stream_events(
        _raw_events_from_payload(
            payload,
            ("events", "run_events", "recent_events", "timeline"),
        ),
        lifecycle_context,
    )
    raw_events = _workflow_scoped_planner_events(raw_events)
    existing_types = {_event_type(event) for event in raw_events}
    events: list[dict[str, Any]] = []
    if not existing_types.intersection({"workflow.run.started", "workflow.started"}):
        events.append(
            _workflow_lifecycle_event(
                "workflow.run.started",
                payload,
                lifecycle_context,
                created_at=_text(payload.get("created_at")),
            )
        )
    events.extend(raw_events)

    terminal_event_type = _workflow_terminal_event_type(payload.get("status"))
    if (
        terminal_event_type
        and not existing_types.intersection(_workflow_terminal_event_aliases(terminal_event_type))
    ):
        events.append(
            _workflow_lifecycle_event(
                terminal_event_type,
                payload,
                {**lifecycle_context, "status": _text(payload.get("status"))},
                created_at=_text(payload.get("updated_at") or payload.get("created_at")),
            )
        )

    projected = dict(payload)
    projected["events"] = events
    return projected


def workflow_event_context_from_events(events: list[PublicRunEvent]) -> dict[str, str]:
    context: dict[str, str] = {}
    for event in events:
        workflow_id = _text(event.payload.get("workflow_id"))
        if workflow_id:
            context["workflow_id"] = workflow_id
        workflow_node_id = _text(event.payload.get("workflow_node_id"))
        if workflow_node_id:
            context["workflow_node_id"] = workflow_node_id
            context["workflow_node_label"] = _text(event.payload.get("workflow_node_label"))
    return context


def _raw_events_from_payload(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if value and isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _workflow_child_run_payloads(
    payload: Mapping[str, Any],
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> list[dict[str, Any]]:
    raw_children = (
        payload.get("runs") or payload.get("child_runs") or payload.get("children") or []
    )
    if not isinstance(raw_children, list):
        return []
    return [
        _workflow_child_run_payload(
            item,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        for item in raw_children
        if isinstance(item, Mapping)
    ]


def _workflow_child_run_payload(
    payload: Mapping[str, Any],
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    child = dict(payload)
    if workflow_id:
        child.setdefault("workflow_id", workflow_id)
    if workflow_run_id:
        child.setdefault("workflow_run_id", workflow_run_id)
        child.setdefault("parent_run_id", workflow_run_id)
    for key in ("events", "run_events", "recent_events", "timeline"):
        value = child.get(key)
        if isinstance(value, list):
            child[key] = [
                _workflow_child_event_context(
                    item,
                    workflow_id=workflow_id,
                    workflow_run_id=workflow_run_id,
                    workflow_node_id=_text(child.get("workflow_node_id")),
                    workflow_node_label=_text(child.get("workflow_node_label")),
                )
                for item in value
                if isinstance(item, Mapping)
            ]
    return child


def _workflow_child_event_context(
    event: Mapping[str, Any],
    *,
    workflow_id: str,
    workflow_run_id: str,
    workflow_node_id: str,
    workflow_node_label: str,
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    if workflow_id:
        payload.setdefault("workflow_id", workflow_id)
    if workflow_run_id:
        payload.setdefault("workflow_run_id", workflow_run_id)
    if workflow_node_id:
        payload.setdefault("workflow_node_id", workflow_node_id)
    if workflow_node_label:
        payload.setdefault("workflow_node_label", workflow_node_label)
    if payload:
        item["payload"] = payload
    return item


def _child_items(child_runs: list[RunTimelineSnapshot], attr: str) -> list[Any]:
    return [item for run in child_runs for item in getattr(run, attr)]


def _child_approvals(child_runs: list[RunTimelineSnapshot]) -> list[Any]:
    approvals = []
    for run in child_runs:
        approvals.extend(run.approvals)
        if run.pending_approval:
            approvals.append(run.pending_approval)
    return approvals


def _first_pending(items: list[Any]) -> Any | None:
    for item in items:
        if getattr(item, "status", "") == "pending":
            return item
    return None


def _preferred_workflow_pending_approval(
    timeline_pending: ApprovalCardSnapshot | None,
    child_approvals: list[Any],
) -> ApprovalCardSnapshot | None:
    if timeline_pending is None:
        return _first_pending(child_approvals)
    approval_id = _text(timeline_pending.approval_id)
    source_run_id = _text(timeline_pending.source_run_id)
    if not approval_id or not source_run_id:
        return timeline_pending
    for approval in child_approvals:
        if getattr(approval, "status", "") != "pending":
            continue
        if _text(getattr(approval, "approval_id", "")) != approval_id:
            continue
        if _text(getattr(approval, "run_id", "")) == source_run_id:
            return approval
    return timeline_pending


def _workflow_context_tool_calls(
    tool_calls: list[ToolCallSnapshot],
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> list[ToolCallSnapshot]:
    return [
        _workflow_context_tool_call(
            tool_call,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        for tool_call in tool_calls
    ]


def _workflow_context_tool_call(
    tool_call: ToolCallSnapshot,
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> ToolCallSnapshot:
    return tool_call.model_copy(
        update={
            "source_run_id": tool_call.source_run_id or tool_call.run_id,
            "workflow_id": tool_call.workflow_id or workflow_id or None,
            "workflow_run_id": tool_call.workflow_run_id or workflow_run_id or None,
        }
    )


def _workflow_context_approvals(
    approvals: list[ApprovalCardSnapshot],
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> list[ApprovalCardSnapshot]:
    return [
        _workflow_context_approval(
            approval,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        for approval in approvals
    ]


def _workflow_context_approval(
    approval: ApprovalCardSnapshot | None,
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> ApprovalCardSnapshot | None:
    if approval is None:
        return None
    return approval.model_copy(
        update={
            "source_run_id": approval.source_run_id or approval.run_id,
            "workflow_id": approval.workflow_id or workflow_id or None,
            "workflow_run_id": approval.workflow_run_id or workflow_run_id or None,
        }
    )


def _workflow_context_artifacts(
    artifacts: list[ArtifactSnapshot],
    *,
    workflow_id: str,
    workflow_run_id: str,
) -> list[ArtifactSnapshot]:
    return [
        artifact.model_copy(
            update={
                "workflow_id": artifact.workflow_id or workflow_id or None,
                "workflow_run_id": artifact.workflow_run_id or workflow_run_id or None,
            }
        )
        for artifact in artifacts
    ]


def _artifact_identity(artifact: Any) -> str:
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


_WORKFLOW_PLANNER_EVENT_TYPES = {
    "agent.intent.selected": "workflow.run.intent.selected",
    "agent.plan.created": "workflow.run.plan.created",
    "agent.task_core.created": "workflow.run.task_core.created",
    "agent.plan.step": "workflow.run.plan.step",
    "agent.plan.selection": "workflow.run.plan.selection",
    "agent.replan.requested": "workflow.run.replan.requested",
    "agent.replan.recovery.updated": "workflow.run.replan.recovery.updated",
    "agent.desktop.intent_planned": "workflow.run.desktop.intent_planned",
    "agent.tool.approval_required": "workflow.run.tool.approval_required",
    "agent.desktop.intent_approval_required": "workflow.run.desktop.intent_approval_required",
    "agent.desktop.intent_completed": "workflow.run.desktop.intent_completed",
    "agent.desktop.intent_unavailable": "workflow.run.desktop.intent_unavailable",
    "agent.desktop.permission_recovery": "workflow.run.desktop.permission_recovery",
    "agent.desktop.readiness_recovered": "workflow.run.desktop.readiness_recovered",
    "agent.task.workspace_item.updated": "workflow.run.task.workspace_item.updated",
    "agent.task.todo.updated": "workflow.run.task.todo.updated",
    "agent.task.checkpoint.updated": "workflow.run.task.checkpoint.updated",
}


def _workflow_scoped_planner_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scoped_events: list[dict[str, Any]] = []
    for event in events:
        event_type = _event_type(event)
        workflow_type = _WORKFLOW_PLANNER_EVENT_TYPES.get(event_type)
        if not workflow_type:
            scoped_events.append(event)
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        scoped_events.append(
            {
                **event,
                "event_type": workflow_type,
                "payload": {
                    **dict(payload),
                    "planner_event_type": str(
                        payload.get("planner_event_type") or event_type
                    ),
                    "planner_scope": str(payload.get("planner_scope") or "workflow_run"),
                },
            }
        )
    return scoped_events


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("event"))


def _workflow_lifecycle_context(payload: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "workflow_id": _text(payload.get("workflow_id") or payload.get("runnable_id")),
        "workflow_run_id": _text(payload.get("workflow_run_id") or run_id),
        "objective": _text(payload.get("objective") or payload.get("user_goal")),
        "status": _text(payload.get("status") or "unknown"),
        "workflow_node_id": _text(payload.get("current_node_id") or payload.get("workflow_node_id")),
        "workflow_node_label": _text(
            payload.get("current_node_label") or payload.get("workflow_node_label")
        ),
    }


def _workflow_lifecycle_event(
    event_type: str,
    payload: Mapping[str, Any],
    lifecycle_context: dict[str, Any],
    *,
    created_at: str = "",
) -> dict[str, Any]:
    label = _text(
        payload.get("title")
        or payload.get("objective")
        or payload.get("user_goal")
        or "Workflow run"
    )
    event = {
        "event_type": event_type,
        "detail": label,
        "payload": {
            key: value
            for key, value in lifecycle_context.items()
            if value or key in {"status"}
        },
    }
    if created_at:
        event["created_at"] = created_at
    return event


def _workflow_stream_events(
    events: list[dict[str, Any]],
    lifecycle_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        _workflow_stream_event(event, lifecycle_context)
        for event in events
    ]


def _workflow_stream_event(
    event: dict[str, Any],
    lifecycle_context: Mapping[str, Any],
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), Mapping) else {}
    for key in (
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        value = lifecycle_context.get(key)
        if value:
            payload.setdefault(key, value)
    if payload:
        item["payload"] = payload
    return item


def _workflow_terminal_event_type(value: Any) -> str:
    status = _text(value)
    if status in {"completed", "success", "succeeded", "done"}:
        return "workflow.run.completed"
    if status in {"failed", "error"}:
        return "workflow.run.failed"
    if status in {"cancelled", "canceled"}:
        return "workflow.run.cancelled"
    return ""


def _workflow_terminal_event_aliases(event_type: str) -> set[str]:
    aliases = {
        "workflow.run.completed": {"workflow.run.completed", "workflow.completed"},
        "workflow.run.failed": {"workflow.run.failed", "workflow.failed"},
        "workflow.run.cancelled": {"workflow.run.cancelled", "workflow.cancelled"},
    }
    return aliases.get(event_type, {event_type})


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
