"""Project runtime failure observations into public replan events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    PlannerDecisionSnapshot,
    PublicRunEvent,
    ReplanSignalSnapshot,
    RuntimePlanSnapshot,
    TaskCoreSnapshot,
    TaskIntentSnapshot,
    TaskTodoItemSnapshot,
    TaskWorkspaceSnapshot,
    ToolPlanSnapshot,
    ToolPlanStepSnapshot,
)
from .events import public_run_event_from_payload
from .planner_projection import planner_replan_run_event_payload


def run_events_with_replan_requests(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
    *,
    run_id: str = "",
    task_id: str = "",
) -> list[PublicRunEvent]:
    """Append replayable replan requests after public failure observations."""
    event_list = list(events)
    if not event_list or _has_replan_request(event_list):
        return event_list
    decision_event = _planner_decision_from_events(event_list)
    if decision_event is None:
        return event_list
    decision, scope = decision_event
    clean_run_id = _text(run_id or payload.get("run_id") or payload.get("workflow_run_id"))
    clean_task_id = _text(task_id or payload.get("task_id"))
    next_sequence = max([int(event.sequence or 0) for event in event_list] or [0]) + 1
    projected: list[PublicRunEvent] = []
    seen_requests: set[str] = set()
    for event in event_list:
        if not _is_public_failure_event(event):
            continue
        request_event = _replan_event_from_failure(
            decision,
            event,
            run_id=clean_run_id,
            task_id=clean_task_id,
            sequence=next_sequence,
            scope=scope,
        )
        if request_event is None:
            continue
        request_id = _text(request_event.payload.get("request_id"))
        if request_id and request_id in seen_requests:
            continue
        if request_id:
            seen_requests.add(request_id)
        projected.append(request_event)
        next_sequence += 1
    return [*event_list, *projected]


def _planner_decision_from_events(
    events: list[PublicRunEvent],
) -> tuple[PlannerDecisionSnapshot, str] | None:
    plan_event = next(
        (
            event
            for event in events
            if _planner_event_type(event) == "agent.plan.created"
            and isinstance(event.payload.get("plan"), Mapping)
        ),
        None,
    )
    if plan_event is None:
        return None
    intent_event = next(
        (
            event
            for event in events
            if _planner_event_type(event) == "agent.intent.selected"
            and isinstance(event.payload.get("intent"), Mapping)
        ),
        None,
    )
    try:
        intent = (
            TaskIntentSnapshot.model_validate(intent_event.payload.get("intent"))
            if intent_event is not None and isinstance(intent_event.payload.get("intent"), Mapping)
            else _intent_from_plan_event(plan_event)
        )
        if intent is None:
            return None
        plan = _runtime_plan_from_event(plan_event, intent, events)
        if plan is None:
            return None
        candidates = (
            [
                TaskIntentSnapshot.model_validate(candidate)
                for candidate in intent_event.payload.get("candidate_intents", [])
                if isinstance(candidate, Mapping)
            ]
            if intent_event is not None
            else [intent]
        )
        decision = PlannerDecisionSnapshot(
            decision_id=_text(
                plan_event.payload.get("decision_id")
                or (intent_event.payload.get("decision_id") if intent_event else "")
                or plan.plan_id
            ),
            prompt=_text(intent.user_goal),
            selected_intent=intent,
            candidate_intents=candidates,
            plan=plan,
            source=_text(plan_event.payload.get("source") or plan.source or "runtime_planner"),
        )
    except ValueError:
        return None
    return decision, _planner_scope(plan_event)


def _intent_from_plan_event(plan_event: PublicRunEvent) -> TaskIntentSnapshot | None:
    plan_payload = plan_event.payload.get("plan")
    if not isinstance(plan_payload, Mapping):
        return None
    intent_payload = plan_payload.get("intent")
    if not isinstance(intent_payload, Mapping):
        return None
    try:
        return TaskIntentSnapshot.model_validate(intent_payload)
    except ValueError:
        return None


def _runtime_plan_from_event(
    plan_event: PublicRunEvent,
    intent: TaskIntentSnapshot,
    events: list[PublicRunEvent],
) -> RuntimePlanSnapshot | None:
    plan_payload = plan_event.payload.get("plan")
    if isinstance(plan_payload, Mapping):
        try:
            plan = RuntimePlanSnapshot.model_validate(plan_payload)
            if plan.task_core is None:
                task_core = _minimal_task_core_from_events(
                    intent,
                    events,
                    list(plan.tool_plan.steps),
                )
                if task_core is not None:
                    return plan.model_copy(update={"task_core": task_core})
            return plan
        except ValueError:
            pass
    steps = _tool_plan_steps_from_events(events)
    if not steps:
        return None
    plan_id = _text(
        plan_event.payload.get("plan_id")
        or (plan_payload.get("plan_id") if isinstance(plan_payload, Mapping) else "")
        or "runtime-plan-public"
    )
    tool_plan_payload = (
        plan_payload.get("tool_plan")
        if isinstance(plan_payload, Mapping) and isinstance(plan_payload.get("tool_plan"), Mapping)
        else {}
    )
    tool_plan = ToolPlanSnapshot(
        plan_id=_text(tool_plan_payload.get("plan_id") or f"{plan_id}:tools"),
        title=_text(tool_plan_payload.get("title") or "Runtime Tool Plan"),
        steps=steps,
        required_capabilities=_list_or_default(
            tool_plan_payload.get("required_capabilities"),
            [step.capability_id for step in steps if step.capability_id],
        ),
        missing_capabilities=_list_or_default(tool_plan_payload.get("missing_capabilities"), []),
        approvals_required=_list_or_default(tool_plan_payload.get("approvals_required"), []),
        artifacts_expected=_list_or_default(tool_plan_payload.get("artifacts_expected"), []),
        open_questions=_list_or_default(tool_plan_payload.get("open_questions"), []),
    )
    return RuntimePlanSnapshot(
        plan_id=plan_id,
        intent=intent,
        capabilities=[],
        tool_plan=tool_plan,
        task_core=_minimal_task_core_from_events(intent, events, steps),
        route_to_studio=bool(
            plan_event.payload.get("route_to_studio")
            or (plan_payload.get("route_to_studio") if isinstance(plan_payload, Mapping) else False)
        ),
    )


def _tool_plan_steps_from_events(events: list[PublicRunEvent]) -> list[ToolPlanStepSnapshot]:
    steps: list[ToolPlanStepSnapshot] = []
    for event in events:
        if _planner_event_type(event) != "agent.plan.step":
            continue
        step_payload = event.payload.get("step")
        if not isinstance(step_payload, Mapping):
            continue
        try:
            steps.append(ToolPlanStepSnapshot.model_validate(step_payload))
        except ValueError:
            continue
    return steps


def _minimal_task_core_from_events(
    intent: TaskIntentSnapshot,
    events: list[PublicRunEvent],
    steps: list[ToolPlanStepSnapshot],
) -> TaskCoreSnapshot | None:
    core_event = next(
        (event for event in events if _planner_event_type(event) == "agent.task_core.created"),
        None,
    )
    core_payload = core_event.payload if core_event is not None else {}
    core_id = _text(core_payload.get("core_id"))
    task_core_payload = (
        core_payload.get("task_core")
        if isinstance(core_payload.get("task_core"), Mapping)
        else {}
    )
    workspace_payload = (
        task_core_payload.get("workspace")
        if isinstance(task_core_payload.get("workspace"), Mapping)
        else {}
    )
    if not core_id and not steps:
        return None
    workspace = TaskWorkspaceSnapshot(
        workspace_id=_text(
            workspace_payload.get("workspace_id") or f"task-workspace:{intent.intent_id}"
        ),
        title=_text(workspace_payload.get("title") or f"{intent.title} Workspace"),
        summary="Public task workspace reconstructed from planner events.",
        items=[],
        context={"intent_id": intent.intent_id, "intent_kind": intent.kind},
    )
    return TaskCoreSnapshot(
        core_id=core_id or f"task-core:{intent.intent_id}",
        workspace=workspace,
        todos=[
            TaskTodoItemSnapshot(
                todo_id=f"todo:{step.step_id}",
                title=step.title,
                capability_id=step.capability_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                approval_required=step.approval_required,
                depends_on=list(step.depends_on),
                reason=step.reason,
            )
            for step in steps
        ],
        replan_signals=[
            ReplanSignalSnapshot(
                signal_id=f"replan:{step.step_id}",
                trigger=(
                    "tool_unavailable"
                    if step.status == "unavailable" or not step.tool_name
                    else "tool_failure"
                ),
                source_step_id=step.step_id,
                condition="public runtime observation failed or contradicted the plan",
                target=step.capability_id,
                fallback_tools=list(step.fallback_tools),
                reason="Continue from the public task workspace and choose the next observable action.",
            )
            for step in steps
            if step.fallback_tools or step.status == "unavailable" or not step.tool_name
        ],
    )


def _replan_event_from_failure(
    decision: PlannerDecisionSnapshot,
    event: PublicRunEvent,
    *,
    run_id: str,
    task_id: str,
    sequence: int,
    scope: str,
) -> PublicRunEvent | None:
    failure = {
        **dict(event.payload),
        "event_type": event.event_type,
        "sequence": event.sequence,
    }
    step_id = _event_step_id(event)
    tool_name = _event_tool_name(event)
    trigger = _failure_trigger(event)
    run_event = planner_replan_run_event_payload(
        decision,
        failure,
        trigger=trigger,
        run_id=run_id,
        task_id=task_id,
        source_step_id=step_id,
        tool_name=tool_name,
    )
    if run_event is None:
        return None
    raw_event_type, replan_payload = run_event
    event_type = _scoped_replan_event_type(scope, raw_event_type)
    payload = dict(replan_payload)
    if event_type != raw_event_type:
        payload["planner_event_type"] = raw_event_type
        payload["planner_scope"] = scope
    return public_run_event_from_payload(
        {
            "run_id": run_id or event.run_id,
            "sequence": sequence,
            "event_type": event_type,
            "title": "Replan requested",
            "detail": payload.get("reason") or payload.get("failure_detail") or trigger,
            "payload": payload,
            "created_at": event.created_at,
        },
        run_id=run_id or event.run_id,
        sequence=sequence,
    )


def _has_replan_request(events: list[PublicRunEvent]) -> bool:
    return any(
        _planner_event_type(event) == "agent.replan.requested"
        or _text(event.event_type).endswith(".replan.requested")
        for event in events
    )


def _is_public_failure_event(event: PublicRunEvent) -> bool:
    if event.visibility != "user" or event.sensitivity != "public":
        return False
    if _planner_event_type(event).startswith("agent."):
        if _planner_event_type(event) in {
            "agent.intent.selected",
            "agent.plan.created",
            "agent.task_core.created",
            "agent.plan.step",
            "agent.plan.selection",
            "agent.replan.requested",
        }:
            return False
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    status = _text(
        payload.get("status")
        or payload.get("run_status")
        or payload.get("tool_status")
        or ""
    ).lower()
    result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    result_ok = result.get("ok") if isinstance(result, Mapping) else None
    event_type = _text(event.event_type).lower()
    if _approval_waiting_failure_placeholder(payload, result):
        return False
    if result_ok is False:
        return True
    if status in {"failed", "failure", "error", "unavailable", "cancelled", "rejected"}:
        return True
    return event_type.endswith(".failed") or event_type.endswith("_failed")


def _approval_waiting_failure_placeholder(
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    status = _text(
        payload.get("status")
        or payload.get("tool_status")
        or payload.get("run_status")
        or ""
    ).lower()
    if status in {"approval_required", "waiting_approval", "pending_approval"}:
        return True
    if bool(payload.get("approval_required")):
        return True
    if bool(result.get("approval_required")):
        return True
    pending_approval = payload.get("pending_approval")
    return isinstance(pending_approval, Mapping) and bool(pending_approval)


def _failure_trigger(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    status = _text(payload.get("status") or payload.get("tool_status") or event.event_type).lower()
    detail = " ".join(
        _text(item).lower()
        for item in (
            payload.get("detail"),
            payload.get("error"),
            (payload.get("result") or {}).get("error")
            if isinstance(payload.get("result"), Mapping)
            else "",
        )
        if _text(item)
    )
    if "unavailable" in status or "missing" in detail or "unavailable" in detail:
        return "tool_unavailable"
    if "verify" in status or "verification" in status or "verify" in detail:
        return "verification_failed"
    return "tool_failure"


def _planner_event_type(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    explicit = _text(payload.get("planner_event_type"))
    if explicit:
        return explicit
    return _canonical_planner_event_type(_text(event.event_type))


_SCOPED_PLANNER_EVENT_TYPES = {
    "group.run.intent.selected": "agent.intent.selected",
    "group.run.plan.created": "agent.plan.created",
    "group.run.task_core.created": "agent.task_core.created",
    "group.run.plan.step": "agent.plan.step",
    "group.run.plan.selection": "agent.plan.selection",
    "group.run.replan.requested": "agent.replan.requested",
    "group.run.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "group.run.task.todo.updated": "agent.task.todo.updated",
    "group.run.task.checkpoint.updated": "agent.task.checkpoint.updated",
    "workflow.intent.selected": "agent.intent.selected",
    "workflow.plan.created": "agent.plan.created",
    "workflow.task_core.created": "agent.task_core.created",
    "workflow.plan.step": "agent.plan.step",
    "workflow.plan.selection": "agent.plan.selection",
    "workflow.replan.requested": "agent.replan.requested",
    "workflow.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "workflow.task.todo.updated": "agent.task.todo.updated",
    "workflow.task.checkpoint.updated": "agent.task.checkpoint.updated",
    "workflow.run.intent.selected": "agent.intent.selected",
    "workflow.run.plan.created": "agent.plan.created",
    "workflow.run.task_core.created": "agent.task_core.created",
    "workflow.run.plan.step": "agent.plan.step",
    "workflow.run.plan.selection": "agent.plan.selection",
    "workflow.run.replan.requested": "agent.replan.requested",
    "workflow.run.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "workflow.run.task.todo.updated": "agent.task.todo.updated",
    "workflow.run.task.checkpoint.updated": "agent.task.checkpoint.updated",
}


def _canonical_planner_event_type(event_type: str) -> str:
    return _SCOPED_PLANNER_EVENT_TYPES.get(_text(event_type), _text(event_type))


def _planner_scope(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    explicit = _text(payload.get("planner_scope"))
    if explicit:
        return explicit
    event_type = _text(event.event_type)
    if event_type.startswith("workflow.run."):
        return "workflow_run"
    if event_type.startswith("group.run."):
        return "group_run"
    return "agent_run"


def _scoped_replan_event_type(scope: str, event_type: str) -> str:
    if scope == "workflow_run":
        return "workflow.run.replan.requested"
    if scope == "group_run":
        return "group.run.replan.requested"
    return event_type


def _event_step_id(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(
        payload.get("step_id") or payload.get("planner_step_id") or payload.get("source_step_id")
    )


def _event_tool_name(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("tool_name") or payload.get("tool") or payload.get("name"))


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    return [_text(item) for item in value if _text(item)]


def _text(value: Any) -> str:
    return str(value or "").strip()
