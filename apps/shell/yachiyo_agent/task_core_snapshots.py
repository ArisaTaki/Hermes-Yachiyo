"""Task core projection helpers for Chat and Agent Studio snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_json_value

from .contracts import (
    PublicRunEvent,
    ReplanSignalSnapshot,
    TaskCheckpointSnapshot,
    TaskCoreSnapshot,
    TaskTodoItemSnapshot,
    TaskWorkspaceItemSnapshot,
    TaskWorkspaceSnapshot,
    ToolPlanStepSnapshot,
)


def task_core_snapshot_from_payload(
    payload: Mapping[str, Any],
    *,
    events: Iterable[PublicRunEvent] | None = None,
) -> TaskCoreSnapshot | None:
    """Project the DeepAgent-style task core from planner metadata or events."""
    event_list = list(events or [])
    blocked_requests = _blocked_runtime_requests_from_payload(payload)
    for candidate in _task_core_candidates(payload, event_list):
        snapshot = _task_core_snapshot_from_candidate(candidate)
        if snapshot is not None:
            return _task_core_with_blocked_runtime_requests(
                _task_core_with_event_progress(snapshot, event_list),
                blocked_requests,
            )
    fallback = _task_core_from_public_events(payload, event_list)
    if fallback is None:
        return None
    return _task_core_with_blocked_runtime_requests(
        _task_core_with_event_progress(fallback, event_list),
        blocked_requests,
    )


def _task_core_candidates(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
) -> Iterable[Any]:
    yield payload.get("task_core")
    yield payload.get("planner_task_core")

    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata.get("yachiyo_task_core")
        yield metadata.get("task_core")

    yield _task_core_from_plan(payload.get("plan"))
    yield _task_core_from_plan(payload.get("runtime_plan"))

    planner_decision = payload.get("planner_decision")
    if isinstance(planner_decision, Mapping):
        yield _task_core_from_plan(planner_decision.get("plan"))

    for event_payload in _raw_public_event_payloads(payload):
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))

    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        event_payload = event.payload
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))


def _task_core_from_plan(plan: Any) -> Any:
    if not isinstance(plan, Mapping):
        return None
    return plan.get("task_core")


def _raw_public_event_payloads(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            if _raw_event_is_private(item):
                continue
            event_payload = item.get("payload")
            if isinstance(event_payload, Mapping):
                yield event_payload
            else:
                yield {
                    str(raw_key): raw_value
                    for raw_key, raw_value in item.items()
                    if raw_key
                    not in {
                        "event_id",
                        "run_id",
                        "sequence",
                        "schema_version",
                        "event_type",
                        "event",
                        "title",
                        "detail",
                        "actor",
                        "visibility",
                        "sensitivity",
                        "created_at",
                    }
                }


def _raw_event_is_private(event: Mapping[str, Any]) -> bool:
    return (
        str(event.get("visibility") or "").strip() == "internal"
        or str(event.get("sensitivity") or "").strip() == "secret"
    )


def _task_core_snapshot_from_candidate(candidate: Any) -> TaskCoreSnapshot | None:
    if isinstance(candidate, TaskCoreSnapshot):
        return candidate
    if not isinstance(candidate, Mapping):
        return None
    redacted = redact_json_value(dict(candidate))
    if not isinstance(redacted, Mapping):
        return None
    try:
        return TaskCoreSnapshot.model_validate(redacted)
    except ValueError:
        return None


def _task_core_from_public_events(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
) -> TaskCoreSnapshot | None:
    event_list = [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]
    if not event_list:
        return None
    steps = _tool_plan_steps_from_raw_payload(payload)
    _extend_unique_tool_plan_steps(steps, _tool_plan_steps_from_events(event_list))
    task_updates = _explicit_task_update_maps(event_list)
    replan_signals = _replan_signals_from_events(event_list)
    if not steps and not _has_explicit_task_updates(task_updates) and not replan_signals:
        return None

    base_id = _task_core_base_id(payload, event_list)
    core_id = _text(payload.get("core_id") or f"task-core:{base_id}")
    title = _task_core_title(payload, event_list)
    workspace = TaskWorkspaceSnapshot(
        workspace_id=_text(payload.get("workspace_id") or f"task-workspace:{base_id}"),
        title=f"{title} Workspace" if title else "Task Workspace",
        summary="Public task workspace reconstructed from planner and runtime events.",
        items=_workspace_items_from_updates(task_updates),
        context={
            key: value
            for key, value in {
                "task_id": _text(payload.get("task_id")),
                "run_id": _text(payload.get("run_id")),
                "source": "public_run_events",
            }.items()
            if value
        },
        source="public_run_events",
    )
    return TaskCoreSnapshot(
        core_id=core_id,
        workspace=workspace,
        todos=_todos_from_steps_and_updates(steps, task_updates),
        checkpoints=_checkpoints_from_steps_and_updates(steps, task_updates),
        replan_signals=[
            *replan_signals,
            *_replan_signals_from_steps(steps, replan_signals),
        ],
        source="public_run_events",
    )


def _tool_plan_steps_from_events(events: Iterable[PublicRunEvent]) -> list[ToolPlanStepSnapshot]:
    steps: list[ToolPlanStepSnapshot] = []
    seen_step_ids: set[str] = set()
    for event in events:
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if _planner_event_type(event) == "agent.plan.created":
            plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else {}
            tool_plan = (
                plan.get("tool_plan")
                if isinstance(plan.get("tool_plan"), Mapping)
                else {}
            )
            raw_steps = tool_plan.get("steps")
            if isinstance(raw_steps, list):
                for raw_step in raw_steps:
                    _append_tool_plan_step(steps, seen_step_ids, raw_step)
        if _planner_event_type(event) != "agent.plan.step":
            continue
        raw_step = payload.get("step") if isinstance(payload.get("step"), Mapping) else payload
        _append_tool_plan_step(steps, seen_step_ids, raw_step)
    return steps


def _tool_plan_steps_from_raw_payload(payload: Mapping[str, Any]) -> list[ToolPlanStepSnapshot]:
    steps: list[ToolPlanStepSnapshot] = []
    seen_step_ids: set[str] = set()
    for event_payload in _raw_public_event_payloads(payload):
        plan = event_payload.get("plan") if isinstance(event_payload.get("plan"), Mapping) else {}
        tool_plan = (
            plan.get("tool_plan")
            if isinstance(plan.get("tool_plan"), Mapping)
            else {}
        )
        raw_steps = tool_plan.get("steps")
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                _append_tool_plan_step(steps, seen_step_ids, raw_step)
        raw_step = event_payload.get("step")
        if isinstance(raw_step, Mapping):
            _append_tool_plan_step(steps, seen_step_ids, raw_step)
    return steps


def _extend_unique_tool_plan_steps(
    target: list[ToolPlanStepSnapshot],
    source: list[ToolPlanStepSnapshot],
) -> None:
    seen = {_text(step.step_id) for step in target if _text(step.step_id)}
    for step in source:
        step_id = _text(step.step_id)
        if step_id and step_id in seen:
            continue
        if step_id:
            seen.add(step_id)
        target.append(step)


def _task_core_base_id(payload: Mapping[str, Any], events: Iterable[PublicRunEvent]) -> str:
    for event in events:
        event_payload = event.payload if isinstance(event.payload, Mapping) else {}
        if _planner_event_type(event) == "agent.replan.requested":
            core_id = _text(event_payload.get("core_id"))
            if core_id.startswith("task-core:"):
                return core_id.removeprefix("task-core:")
            if core_id:
                return core_id
        if _planner_event_type(event) == "agent.plan.created":
            plan = event_payload.get("plan") if isinstance(event_payload.get("plan"), Mapping) else {}
            intent = plan.get("intent") if isinstance(plan.get("intent"), Mapping) else {}
            intent_id = _text(intent.get("intent_id"))
            if intent_id:
                return intent_id
        if _planner_event_type(event) == "agent.intent.selected":
            intent = (
                event_payload.get("intent")
                if isinstance(event_payload.get("intent"), Mapping)
                else {}
            )
            intent_id = _text(intent.get("intent_id"))
            if intent_id:
                return intent_id
    return _text(payload.get("task_id") or payload.get("run_id") or "events")


def _append_tool_plan_step(
    steps: list[ToolPlanStepSnapshot],
    seen_step_ids: set[str],
    raw_step: Any,
) -> None:
    if not isinstance(raw_step, Mapping):
        return
    try:
        step = ToolPlanStepSnapshot.model_validate(raw_step)
    except ValueError:
        return
    step_id = _text(step.step_id)
    if step_id and step_id in seen_step_ids:
        return
    if step_id:
        seen_step_ids.add(step_id)
    steps.append(step)


def _task_core_title(payload: Mapping[str, Any], events: Iterable[PublicRunEvent]) -> str:
    title = _text(payload.get("title") or payload.get("user_goal") or payload.get("objective"))
    if title:
        return title
    for event in events:
        event_payload = event.payload if isinstance(event.payload, Mapping) else {}
        if _planner_event_type(event) != "agent.intent.selected":
            continue
        intent = event_payload.get("intent") if isinstance(event_payload.get("intent"), Mapping) else {}
        title = _text(intent.get("title") or intent.get("user_goal"))
        if title:
            return title
    return "Yachiyo Task"


def _workspace_items_from_updates(
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[TaskWorkspaceItemSnapshot]:
    items: list[TaskWorkspaceItemSnapshot] = []
    seen: set[str] = set()
    for update in _unique_task_updates(
        task_updates.get("workspace_by_id", {}),
        task_updates.get("workspace_by_step", {}),
    ):
        item_id = _text(
            update.get("item_id")
            or update.get("workspace_item_id")
            or update.get("path")
            or update.get("source_step_id")
        )
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        items.append(
            TaskWorkspaceItemSnapshot(
                item_id=item_id,
                title=_text(update.get("title") or update.get("path") or item_id),
                kind=_text(update.get("kind") or "other"),
                path=_optional_text(update.get("path")),
                description=_text(update.get("description")),
                source_step_id=_optional_text(update.get("source_step_id")),
                status=_text(update.get("status") or "planned"),
                metadata=_mapping(update.get("metadata")),
            )
        )
    return items


def _todos_from_steps_and_updates(
    steps: list[ToolPlanStepSnapshot],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[TaskTodoItemSnapshot]:
    todos: list[TaskTodoItemSnapshot] = []
    seen: set[str] = set()
    seen_steps: set[str] = set()
    for step in steps:
        step_id = _text(step.step_id)
        todo_id = f"todo:{step_id or len(todos) + 1}"
        seen.add(todo_id)
        if step_id:
            seen_steps.add(step_id)
        todos.append(
            TaskTodoItemSnapshot(
                todo_id=todo_id,
                title=step.title,
                capability_id=step.capability_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                approval_required=step.approval_required,
                depends_on=list(step.depends_on),
                reason=step.reason,
                metadata={
                    "action": step.action,
                    "risk_level": step.risk_level,
                    "source": "plan_step",
                },
            )
        )
    for update in _unique_task_updates(
        task_updates.get("todo_by_id", {}),
        task_updates.get("todo_by_step", {}),
    ):
        todo_id = _text(update.get("todo_id") or update.get("step_id"))
        step_id = _text(update.get("step_id"))
        if not todo_id or todo_id in seen or (step_id and step_id in seen_steps):
            continue
        seen.add(todo_id)
        todos.append(
            TaskTodoItemSnapshot(
                todo_id=todo_id,
                title=_text(update.get("title") or update.get("tool_name") or todo_id),
                status=_text(update.get("status") or "pending"),
                capability_id=_text(update.get("capability_id")),
                step_id=_optional_text(update.get("step_id")),
                tool_name=_optional_text(update.get("tool_name")),
                approval_required=bool(update.get("approval_required", False)),
                depends_on=_string_list(update.get("depends_on")),
                reason=_text(update.get("reason")),
                metadata=_mapping(update.get("metadata")),
            )
        )
    return todos


def _checkpoints_from_steps_and_updates(
    steps: list[ToolPlanStepSnapshot],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[TaskCheckpointSnapshot]:
    checkpoints: list[TaskCheckpointSnapshot] = []
    seen: set[str] = set()
    seen_steps: set[str] = set()
    for step in steps:
        step_id = _text(step.step_id)
        checkpoint_id = f"checkpoint:{step_id or len(checkpoints) + 1}"
        seen.add(checkpoint_id)
        if step_id:
            seen_steps.add(step_id)
        checkpoints.append(
            TaskCheckpointSnapshot(
                checkpoint_id=checkpoint_id,
                title=f"Verify {step.title}",
                after_step_id=step.step_id,
                depends_on=list(step.depends_on),
                verifies=_string_list(step.input_preview.get("expected_outputs")),
                payload={
                    "tool_name": step.tool_name or "",
                    "capability_id": step.capability_id,
                    "source": "plan_step",
                },
            )
        )
    for update in _unique_task_updates(
        task_updates.get("checkpoint_by_id", {}),
        task_updates.get("checkpoint_by_step", {}),
    ):
        checkpoint_id = _text(update.get("checkpoint_id") or update.get("after_step_id"))
        after_step_id = _text(update.get("after_step_id"))
        if (
            not checkpoint_id
            or checkpoint_id in seen
            or (after_step_id and after_step_id in seen_steps)
        ):
            continue
        seen.add(checkpoint_id)
        checkpoints.append(
            TaskCheckpointSnapshot(
                checkpoint_id=checkpoint_id,
                title=_text(update.get("title") or checkpoint_id),
                status=_text(update.get("status") or "planned"),
                after_step_id=_optional_text(update.get("after_step_id")),
                depends_on=_string_list(update.get("depends_on")),
                verifies=_string_list(update.get("verifies")),
                replan_on_failure=bool(update.get("replan_on_failure", True)),
                payload=_mapping(update.get("payload")),
            )
        )
    return checkpoints


def _replan_signals_from_events(
    events: Iterable[PublicRunEvent],
) -> list[ReplanSignalSnapshot]:
    signals: list[ReplanSignalSnapshot] = []
    seen: set[str] = set()
    for event in events:
        if _planner_event_type(event) != "agent.replan.requested":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        request = payload.get("request") if isinstance(payload.get("request"), Mapping) else payload
        source_step_id = _text(request.get("source_step_id"))
        signal_id = _text(
            request.get("signal_id")
            or request.get("request_id")
            or f"replan:{source_step_id or event.sequence}"
        )
        if not signal_id or signal_id in seen:
            continue
        seen.add(signal_id)
        signals.append(
            ReplanSignalSnapshot(
                signal_id=signal_id,
                trigger=_text(request.get("trigger") or "tool_failure"),
                source_step_id=_optional_text(source_step_id),
                condition=_text(request.get("condition") or request.get("failure_detail")),
                target=_text(request.get("target") or request.get("target_capability_id")),
                fallback_tools=_string_list(request.get("fallback_tools")),
                reason=_text(request.get("reason")),
            )
        )
    return signals


def _replan_signals_from_steps(
    steps: list[ToolPlanStepSnapshot],
    existing_signals: list[ReplanSignalSnapshot],
) -> list[ReplanSignalSnapshot]:
    existing_by_step = {
        _text(signal.source_step_id)
        for signal in existing_signals
        if _text(signal.source_step_id)
    }
    signals: list[ReplanSignalSnapshot] = []
    for step in steps:
        step_id = _text(step.step_id)
        if not step_id or step_id in existing_by_step:
            continue
        if not step.fallback_tools and step.status != "unavailable" and step.tool_name:
            continue
        signals.append(
            ReplanSignalSnapshot(
                signal_id=f"replan:{step_id}",
                trigger="tool_unavailable" if step.status == "unavailable" else "tool_failure",
                source_step_id=step_id,
                condition="public runtime observation failed or contradicted the plan",
                target=step.capability_id,
                fallback_tools=list(step.fallback_tools),
                reason="Continue from the reconstructed task workspace.",
            )
        )
    return signals


def _unique_task_updates(
    *maps: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    updates: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for update_map in maps:
        for key, update in update_map.items():
            identity = _text(
                update.get("item_id")
                or update.get("todo_id")
                or update.get("checkpoint_id")
                or update.get("source_step_id")
                or update.get("step_id")
                or update.get("after_step_id")
                or key
            )
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            updates.append(update)
    return updates


def _task_core_with_event_progress(
    snapshot: TaskCoreSnapshot,
    events: Iterable[PublicRunEvent],
) -> TaskCoreSnapshot:
    event_list = list(events)
    if not event_list:
        return snapshot
    progress_by_step, progress_by_tool = _runtime_progress_by_step(event_list)
    progress_by_artifact_path = _runtime_progress_by_artifact_path(event_list)
    task_updates = _explicit_task_update_maps(event_list)
    if (
        not progress_by_step
        and not progress_by_tool
        and not progress_by_artifact_path
        and not _has_explicit_task_updates(task_updates)
    ):
        return snapshot

    updated_workspace = _workspace_with_progress(
        snapshot.workspace,
        progress_by_step,
        progress_by_tool,
        progress_by_artifact_path,
        task_updates,
        event_list,
    )
    updated_todos = [
        _todo_with_progress(todo, progress_by_step, progress_by_tool, task_updates)
        for todo in snapshot.todos
    ]
    todo_status_by_step = {
        str(todo.step_id or "").strip(): str(todo.status or "").strip()
        for todo in updated_todos
        if str(todo.step_id or "").strip()
    }
    updated_checkpoints = [
        _checkpoint_with_progress(
            checkpoint,
            todo_status_by_step,
            progress_by_step,
            task_updates,
        )
        for checkpoint in snapshot.checkpoints
    ]
    return snapshot.model_copy(
        update={
            "workspace": updated_workspace,
            "todos": updated_todos,
            "checkpoints": updated_checkpoints,
        }
    )


def _task_core_with_blocked_runtime_requests(
    snapshot: TaskCoreSnapshot,
    blocked_requests: Iterable[Mapping[str, Any]],
) -> TaskCoreSnapshot:
    blocked = [
        request
        for request in blocked_requests
        if isinstance(request, Mapping) and _runtime_request_is_blocked(request)
    ]
    if not blocked:
        return snapshot

    snapshot = _task_core_with_event_progress(
        snapshot,
        _blocked_runtime_request_events(blocked),
    )
    return snapshot.model_copy(
        update={
            "replan_signals": _replan_signals_with_blocked_requests(
                snapshot.replan_signals,
                blocked,
            )
        }
    )


def _blocked_runtime_request_events(
    blocked_requests: list[Mapping[str, Any]],
) -> list[PublicRunEvent]:
    events: list[PublicRunEvent] = []
    sequence = 1
    for request in blocked_requests:
        base_payload = _blocked_request_event_payload(request)
        events.append(
            _blocked_request_event(
                "agent.tool.failed",
                base_payload,
                sequence=sequence,
            )
        )
        sequence += 1
        for event_type, payload in _blocked_request_task_update_payloads(
            request,
            base_payload,
        ):
            events.append(_blocked_request_event(event_type, payload, sequence=sequence))
            sequence += 1
    return events


def _blocked_request_event(
    event_type: str,
    payload: Mapping[str, Any],
    *,
    sequence: int,
) -> PublicRunEvent:
    return PublicRunEvent(
        run_id="",
        sequence=sequence,
        event_type=event_type,
        payload=dict(payload),
    )


def _blocked_request_event_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    tool_name = _blocked_request_tool_name(request)
    step_id = _blocked_request_step_id(request)
    payload = {
        "source": "runtime_blocked_direct_request",
        "status": "blocked",
        "tool": tool_name,
        "tool_name": tool_name,
        "step_id": step_id,
        "planner_step_id": step_id,
        "request_id": _text(request.get("request_id")),
        "capability_id": _text(request.get("capability_id")),
        "reason": _blocked_request_reason(request),
        "blocking_conditions": _blocked_request_blocking_conditions(request),
        "result": {"ok": False},
    }
    return {key: value for key, value in payload.items() if value not in ("", [], None)}


def _blocked_request_task_update_payloads(
    request: Mapping[str, Any],
    base_payload: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    step_id = _blocked_request_step_id(request)
    if not step_id:
        return []
    tool_name = _blocked_request_tool_name(request)
    capability_id = _text(request.get("capability_id"))
    payloads: list[tuple[str, dict[str, Any]]] = []
    for item in _blocked_request_workspace_update_records(request, step_id):
        payloads.append(
            (
                "agent.task.workspace_item.updated",
                {
                    **dict(base_payload),
                    "workspace_item_id": _text(item.get("item_id")),
                    "step_id": _text(item.get("source_step_id") or step_id),
                    "workspace_item": item,
                },
            )
        )
    todo = _blocked_request_update_record(
        request.get("task_todo"),
        "metadata",
        request,
        defaults={
            "step_id": step_id,
            "tool_name": tool_name,
            "capability_id": capability_id,
        },
    )
    payloads.append(
        (
            "agent.task.todo.updated",
            {
                **dict(base_payload),
                "todo_id": _text(todo.get("todo_id")),
                "step_id": step_id,
                "todo": todo,
            },
        )
    )
    for checkpoint in _blocked_request_checkpoint_update_records(request, step_id):
        payloads.append(
            (
                "agent.task.checkpoint.updated",
                {
                    **dict(base_payload),
                    "checkpoint_id": _text(checkpoint.get("checkpoint_id")),
                    "step_id": step_id,
                    "checkpoint": checkpoint,
                },
            )
        )
    return payloads


def _blocked_request_workspace_update_records(
    request: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    raw_items = request.get("task_workspace_items")
    items = [item for item in raw_items if isinstance(item, Mapping)] if isinstance(raw_items, list) else []
    if not items:
        items = [{"source_step_id": step_id}]
    return [
        _blocked_request_update_record(
            item,
            "metadata",
            request,
            defaults={"source_step_id": step_id},
        )
        for item in items
    ]


def _blocked_request_checkpoint_update_records(
    request: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    raw_checkpoints = request.get("task_checkpoints")
    checkpoints = [
        checkpoint
        for checkpoint in raw_checkpoints
        if isinstance(checkpoint, Mapping)
    ] if isinstance(raw_checkpoints, list) else []
    if not checkpoints:
        checkpoints = [{"after_step_id": step_id}]
    return [
        _blocked_request_update_record(
            checkpoint,
            "payload",
            request,
            defaults={"after_step_id": step_id},
        )
        for checkpoint in checkpoints
    ]


def _blocked_request_update_record(
    value: Any,
    metadata_key: str,
    request: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    metadata = _mapping(raw.get(metadata_key))
    return {
        **dict(defaults),
        **raw,
        "status": "blocked",
        metadata_key: {
            **metadata,
            **_blocked_request_metadata(request),
        },
    }


def _replan_signals_with_blocked_requests(
    signals: Iterable[ReplanSignalSnapshot],
    blocked_requests: list[Mapping[str, Any]],
) -> list[ReplanSignalSnapshot]:
    updated = list(signals)
    seen_ids = {_text(signal.signal_id) for signal in updated if _text(signal.signal_id)}
    seen_pairs = {
        (_text(signal.trigger), _text(signal.source_step_id))
        for signal in updated
        if _text(signal.trigger) and _text(signal.source_step_id)
    }
    for request in blocked_requests:
        signal = _blocked_request_replan_signal(request)
        if signal is None:
            continue
        signal_id = _text(signal.signal_id)
        pair = (_text(signal.trigger), _text(signal.source_step_id))
        if (signal_id and signal_id in seen_ids) or (
            pair[0] and pair[1] and pair in seen_pairs
        ):
            continue
        if signal_id:
            seen_ids.add(signal_id)
        if pair[0] and pair[1]:
            seen_pairs.add(pair)
        updated.append(signal)
    return updated


def _blocked_runtime_requests_from_payload(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    requests: list[Mapping[str, Any]] = []
    _extend_blocked_runtime_requests(requests, payload)
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        _extend_blocked_runtime_requests(requests, metadata)
        tool_names = _string_list(metadata.get("yachiyo_blocked_execution_requests"))
        reasons = _string_list(metadata.get("yachiyo_blocked_execution_reasons"))
        reason = reasons[0] if reasons else ""
        for tool_name in tool_names:
            if any(_blocked_request_tool_name(request) == tool_name for request in requests):
                continue
            requests.append(
                {
                    "tool": tool_name,
                    "tool_name": tool_name,
                    "status": "blocked",
                    "blocked_by": "runtime_blocked",
                    "policy_reason": reason,
                }
            )
    return _unique_blocked_runtime_requests(requests)


def _extend_blocked_runtime_requests(
    requests: list[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> None:
    for key in ("yachiyo_blocked_direct_tool_requests", "blocked_direct_tool_requests"):
        raw_requests = payload.get(key)
        if not isinstance(raw_requests, list):
            continue
        for request in raw_requests:
            if isinstance(request, Mapping):
                requests.append(request)


def _unique_blocked_runtime_requests(
    requests: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    unique: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for request in requests:
        key = (
            _text(request.get("request_id")),
            _blocked_request_step_id(request),
            _blocked_request_tool_name(request),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(request)
    return unique


def _blocked_request_replan_signal(
    request: Mapping[str, Any],
) -> ReplanSignalSnapshot | None:
    step_id = _blocked_request_step_id(request)
    tool_name = _blocked_request_tool_name(request)
    if not step_id and not tool_name:
        return None
    signal_ids = _string_list(request.get("replan_signal_ids"))
    signal_id = (
        f"{signal_ids[0]}:runtime-blocked"
        if signal_ids
        else f"replan:runtime-blocked:{step_id or tool_name}"
    )
    condition = _blocked_request_reason(request) or _blocked_request_status(request)
    return ReplanSignalSnapshot(
        signal_id=signal_id,
        trigger="runtime_blocked",
        source_step_id=_optional_text(step_id),
        condition=condition,
        target=_text(request.get("capability_id")),
        fallback_tools=_blocked_request_fallback_tools(request),
        reason="Runtime route blocked this planned tool request; replan from the task workspace.",
    )


def _blocked_request_fallback_tools(request: Mapping[str, Any]) -> list[str]:
    values = _string_list(request.get("fallback_tools"))
    if values:
        return values
    task_todo = request.get("task_todo")
    if isinstance(task_todo, Mapping):
        metadata = task_todo.get("metadata")
        if isinstance(metadata, Mapping):
            return _string_list(metadata.get("fallback_tools"))
    return []


def _runtime_request_is_blocked(request: Mapping[str, Any]) -> bool:
    status = _text(request.get("status")).lower()
    if status == "blocked" or _text(request.get("blocked_by")):
        return True
    route = request.get("desktop_execution_route")
    if isinstance(route, Mapping) and route.get("can_execute") is False:
        return True
    return bool(_string_list(request.get("blocking_conditions")))


def _blocked_request_step_id(request: Mapping[str, Any]) -> str:
    task_todo = request.get("task_todo")
    task_todo_step_id = (
        task_todo.get("step_id")
        if isinstance(task_todo, Mapping)
        else ""
    )
    return _text(
        request.get("step_id")
        or request.get("planner_step_id")
        or request.get("source_step_id")
        or task_todo_step_id
    )


def _blocked_request_tool_name(request: Mapping[str, Any]) -> str:
    task_todo = request.get("task_todo")
    task_todo_tool_name = (
        task_todo.get("tool_name")
        if isinstance(task_todo, Mapping)
        else ""
    )
    return _text(
        request.get("tool_name")
        or request.get("tool")
        or request.get("name")
        or task_todo_tool_name
    )


def _blocked_request_status(request: Mapping[str, Any]) -> str:
    route = request.get("desktop_execution_route")
    route_status = route.get("status") if isinstance(route, Mapping) else ""
    return _text(request.get("blocked_by") or route_status or request.get("status"))


def _blocked_request_reason(request: Mapping[str, Any]) -> str:
    route = request.get("desktop_execution_route")
    route_reason = route.get("reason") if isinstance(route, Mapping) else ""
    return _text(
        request.get("policy_reason")
        or route_reason
        or request.get("reason")
        or request.get("blocked_by")
    )


def _blocked_request_blocking_conditions(request: Mapping[str, Any]) -> list[str]:
    conditions = _string_list(request.get("blocking_conditions"))
    route = request.get("desktop_execution_route")
    if isinstance(route, Mapping):
        conditions.extend(_string_list(route.get("blocking_conditions")))
    return list(dict.fromkeys(conditions))


def _blocked_request_metadata(request: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {
        "runtime_status": _blocked_request_status(request),
        "runtime_event_type": "runtime.blocked_direct_request",
        "runtime_blocked": True,
        "runtime_blocked_request_id": _text(request.get("request_id")),
        "runtime_blocked_tool_name": _blocked_request_tool_name(request),
        "runtime_blocked_reason": _blocked_request_reason(request),
        "runtime_blocking_conditions": _blocked_request_blocking_conditions(request),
    }
    return {key: value for key, value in metadata.items() if value not in ("", [], None)}


def _explicit_task_update_maps(
    events: Iterable[PublicRunEvent],
) -> dict[str, dict[str, dict[str, Any]]]:
    updates: dict[str, dict[str, dict[str, Any]]] = {
        "workspace_by_id": {},
        "workspace_by_step": {},
        "todo_by_id": {},
        "todo_by_step": {},
        "checkpoint_by_id": {},
        "checkpoint_by_step": {},
    }
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        event_type = str(event.event_type or "").strip()
        if event_type.endswith(".task.workspace_item.updated"):
            _store_task_update(
                updates,
                event_type,
                payload,
                nested_key="workspace_item",
                id_key="workspace_item_id",
                nested_id_key="item_id",
                step_key="source_step_id",
                by_id_key="workspace_by_id",
                by_step_key="workspace_by_step",
                update_fields={
                    "item_id",
                    "title",
                    "kind",
                    "path",
                    "description",
                    "source_step_id",
                    "status",
                    "metadata",
                },
            )
        elif event_type.endswith(".task.todo.updated"):
            _store_task_update(
                updates,
                event_type,
                payload,
                nested_key="todo",
                id_key="todo_id",
                nested_id_key="todo_id",
                step_key="step_id",
                by_id_key="todo_by_id",
                by_step_key="todo_by_step",
                update_fields={
                    "todo_id",
                    "title",
                    "status",
                    "capability_id",
                    "step_id",
                    "tool_name",
                    "approval_required",
                    "depends_on",
                    "reason",
                    "metadata",
                },
            )
        elif event_type.endswith(".task.checkpoint.updated"):
            _store_task_update(
                updates,
                event_type,
                payload,
                nested_key="checkpoint",
                id_key="checkpoint_id",
                nested_id_key="checkpoint_id",
                step_key="after_step_id",
                by_id_key="checkpoint_by_id",
                by_step_key="checkpoint_by_step",
                update_fields={
                    "checkpoint_id",
                    "title",
                    "status",
                    "after_step_id",
                    "depends_on",
                    "verifies",
                    "replan_on_failure",
                    "payload",
                },
            )
    return updates


def _has_explicit_task_updates(updates: Mapping[str, Mapping[str, Any]]) -> bool:
    return any(bool(value) for value in updates.values())


def _store_task_update(
    updates: dict[str, dict[str, dict[str, Any]]],
    event_type: str,
    payload: Mapping[str, Any],
    *,
    nested_key: str,
    id_key: str,
    nested_id_key: str,
    step_key: str,
    by_id_key: str,
    by_step_key: str,
    update_fields: set[str],
) -> None:
    nested = payload.get(nested_key) if isinstance(payload.get(nested_key), Mapping) else {}
    raw_update = dict(nested) if isinstance(nested, Mapping) else {}
    status = str(payload.get("status") or raw_update.get("status") or "").strip()
    if status:
        raw_update["status"] = status

    update = {
        key: value
        for key, value in raw_update.items()
        if key in update_fields
    }
    if not update and not status:
        return

    _attach_task_update_runtime_metadata(update, event_type, payload, nested_key)
    identity = str(
        payload.get(id_key)
        or raw_update.get(nested_id_key)
        or raw_update.get(id_key)
        or ""
    ).strip()
    step_id = str(
        payload.get("step_id")
        or payload.get("planner_step_id")
        or payload.get("source_step_id")
        or raw_update.get(step_key)
        or ""
    ).strip()
    if identity:
        updates[by_id_key][identity] = update
    elif step_id:
        updates[by_step_key][step_id] = update


def _attach_task_update_runtime_metadata(
    update: dict[str, Any],
    event_type: str,
    payload: Mapping[str, Any],
    nested_key: str,
) -> None:
    source_event = (
        payload.get("source_event")
        if isinstance(payload.get("source_event"), Mapping)
        else {}
    )
    runtime_event_type = str(source_event.get("event") or event_type).strip()
    runtime_status = str(payload.get("status") or update.get("status") or "").strip()
    runtime_metadata = {
        "runtime_status": runtime_status,
        "runtime_event_type": runtime_event_type,
        "runtime_update_event_type": event_type,
    }
    if nested_key == "checkpoint":
        checkpoint_payload = (
            update.get("payload") if isinstance(update.get("payload"), Mapping) else {}
        )
        update["payload"] = {
            **dict(checkpoint_payload),
            **runtime_metadata,
        }
        return
    metadata = update.get("metadata") if isinstance(update.get("metadata"), Mapping) else {}
    update["metadata"] = {
        **dict(metadata),
        **runtime_metadata,
    }


def _runtime_progress_by_step(
    events: Iterable[PublicRunEvent],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_step: dict[str, dict[str, Any]] = {}
    by_tool: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        progress = _runtime_progress_from_event(event.event_type, payload)
        if not progress:
            continue
        step_ids = _event_step_ids(payload)
        tool_name = _event_tool_name(payload)
        for step_id in step_ids:
            by_step[step_id] = progress
        if tool_name:
            by_tool[tool_name] = progress
    return by_step, by_tool


def _runtime_progress_by_artifact_path(
    events: Iterable[PublicRunEvent],
) -> dict[str, dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        progress = _runtime_progress_from_event(event.event_type, payload)
        if not progress:
            continue
        if not _event_can_update_artifact_path(event.event_type, payload):
            continue
        for path in _event_artifact_paths(payload):
            by_path[path] = progress
    return by_path


def _runtime_progress_from_event(
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    event_name = str(event_type or "").strip()
    status = str(
        payload.get("status")
        or payload.get("run_status")
        or payload.get("tool_status")
        or ""
    ).strip().lower()
    result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    result_ok = result.get("ok") if isinstance(result, Mapping) else None
    if (
        "approval_required" in event_name
        or status in {"approval_required", "waiting_approval", "requires_approval"}
    ):
        return {
            "todo_status": "blocked",
            "checkpoint_status": "waiting_approval",
            "runtime_status": status or "approval_required",
            "event_type": event_name,
        }
    if (
        result_ok is True
        or status in {"completed", "complete", "success", "succeeded", "ok"}
        or event_name.endswith(".completed")
        or _is_desktop_intent_event(event_name, "completed")
        or _event_is_artifact_created(event_name)
    ):
        return {
            "todo_status": "completed",
            "checkpoint_status": "completed",
            "runtime_status": status or "completed",
            "event_type": event_name,
        }
    if (
        result_ok is False
        or status in {"failed", "failure", "error", "unavailable", "cancelled", "rejected"}
        or event_name.endswith(".failed")
        or _is_desktop_intent_event(event_name, "unavailable")
    ):
        return {
            "todo_status": "blocked",
            "checkpoint_status": "blocked",
            "runtime_status": status or "failed",
            "event_type": event_name,
        }
    if status in {"running", "started", "in_progress"} or event_name in {
        "agent.tool.call",
        "tool.call",
    }:
        return {
            "todo_status": "in_progress",
            "checkpoint_status": "ready",
            "runtime_status": status or "in_progress",
            "event_type": event_name,
        }
    return {}


def _event_is_artifact_created(event_type: str) -> bool:
    return event_type in {
        "artifact.created",
        "agent.artifact.write",
        "group.artifact.created",
        "group.shared_artifact.created",
        "workflow.node.artifact",
    } or event_type.endswith(".artifact.created")


def _is_desktop_intent_event(event_type: str, suffix: str) -> bool:
    return event_type in {
        f"agent.desktop.intent_{suffix}",
        f"group.run.desktop.intent_{suffix}",
        f"workflow.desktop.intent_{suffix}",
        f"workflow.run.desktop.intent_{suffix}",
    }


def _workspace_with_progress(
    workspace: TaskWorkspaceSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
    events: Iterable[PublicRunEvent],
) -> TaskWorkspaceSnapshot:
    updated_items = [
        _workspace_item_with_progress(
            item,
            progress_by_step,
            progress_by_tool,
            progress_by_artifact_path,
            task_updates,
        )
        for item in workspace.items
    ]
    updated_items.extend(
        _runtime_artifact_workspace_items(
            events,
            updated_items,
            progress_by_artifact_path,
        )
    )
    return workspace.model_copy(update={"items": updated_items})


def _runtime_artifact_workspace_items(
    events: Iterable[PublicRunEvent],
    existing_items: list[TaskWorkspaceItemSnapshot],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
) -> list[TaskWorkspaceItemSnapshot]:
    existing_paths = {
        path
        for item in existing_items
        for path in _workspace_item_path_candidates(item)
    }
    existing_ids = {str(item.item_id or "").strip() for item in existing_items}
    items: list[TaskWorkspaceItemSnapshot] = []
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if not _event_can_update_artifact_path(event.event_type, payload):
            continue
        progress = _runtime_progress_from_event(event.event_type, payload)
        step_ids = _event_step_ids(payload)
        for path in _event_artifact_paths(payload):
            item_id = f"artifact:{path}"
            if path in existing_paths or item_id in existing_ids:
                continue
            existing_paths.add(path)
            existing_ids.add(item_id)
            item_progress = progress_by_artifact_path.get(path) or progress
            metadata = _runtime_artifact_workspace_item_metadata(event, payload, item_progress)
            items.append(
                TaskWorkspaceItemSnapshot(
                    item_id=item_id,
                    title=_runtime_artifact_workspace_item_title(path, payload),
                    kind="artifact",
                    path=path,
                    description=_text(payload.get("detail") or event.detail),
                    source_step_id=step_ids[0] if step_ids else None,
                    status=_workspace_item_status_from_progress(item_progress, "completed"),
                    metadata=metadata,
                )
            )
    return items


def _runtime_artifact_workspace_item_metadata(
    event: PublicRunEvent,
    payload: Mapping[str, Any],
    progress: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = {
        "source": "runtime_artifact_event",
        "runtime_status": str(progress.get("runtime_status") or "completed"),
        "runtime_event_type": str(progress.get("event_type") or event.event_type or ""),
    }
    for key, value in {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "tool_name": _event_tool_name(payload),
        "artifact_kind": _runtime_artifact_kind(payload),
        "source_run_id": payload.get("source_run_id") or event.run_id,
    }.items():
        clean = str(value or "").strip()
        if clean:
            metadata[key] = clean
    return metadata


def _runtime_artifact_workspace_item_title(path: str, payload: Mapping[str, Any]) -> str:
    for artifact_payload in _artifact_payload_candidates(payload):
        title = _text(
            artifact_payload.get("title")
            or artifact_payload.get("label")
            or artifact_payload.get("path")
            or artifact_payload.get("artifact_path")
        )
        if title:
            return title
    return path


def _runtime_artifact_kind(payload: Mapping[str, Any]) -> str:
    for artifact_payload in _artifact_payload_candidates(payload):
        kind = _text(artifact_payload.get("kind"))
        if kind:
            return kind
    return ""


def _artifact_payload_candidates(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    artifact = payload.get("artifact")
    if isinstance(artifact, Mapping):
        candidates.append(artifact)
    result = payload.get("result")
    if isinstance(result, Mapping):
        result_artifact = result.get("artifact")
        if isinstance(result_artifact, Mapping):
            candidates.append(result_artifact)
        result_artifacts = result.get("artifacts")
        if isinstance(result_artifacts, list):
            candidates.extend(item for item in result_artifacts if isinstance(item, Mapping))
        data = result.get("data")
        if isinstance(data, Mapping):
            data_artifact = data.get("artifact")
            if isinstance(data_artifact, Mapping):
                candidates.append(data_artifact)
    return candidates


def _workspace_item_with_progress(
    item: TaskWorkspaceItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> TaskWorkspaceItemSnapshot:
    progress = _workspace_item_progress(
        item,
        progress_by_step,
        progress_by_tool,
        progress_by_artifact_path,
    )
    updated = item
    update = _workspace_item_explicit_update(updated, task_updates)
    if update:
        updated = _apply_workspace_item_update(updated, update)
    if progress:
        metadata = {
            **dict(updated.metadata or {}),
            "runtime_status": str(progress.get("runtime_status") or ""),
            "runtime_event_type": str(progress.get("event_type") or ""),
        }
        updated = updated.model_copy(
            update={
                "status": _workspace_item_status_from_progress(progress, updated.status),
                "metadata": metadata,
            }
        )
    return updated


def _workspace_item_explicit_update(
    item: TaskWorkspaceItemSnapshot,
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> Mapping[str, Any]:
    item_id = str(item.item_id or "").strip()
    source_step_id = str(
        item.source_step_id or (item.metadata or {}).get("source_step_id") or ""
    ).strip()
    return (
        task_updates.get("workspace_by_id", {}).get(item_id)
        or task_updates.get("workspace_by_step", {}).get(source_step_id)
        or {}
    )


def _apply_workspace_item_update(
    item: TaskWorkspaceItemSnapshot,
    update: Mapping[str, Any],
) -> TaskWorkspaceItemSnapshot:
    fields = {
        key: value
        for key, value in dict(update).items()
        if key
        in {
            "item_id",
            "title",
            "kind",
            "path",
            "description",
            "source_step_id",
            "status",
        }
    }
    metadata = update.get("metadata") if isinstance(update.get("metadata"), Mapping) else {}
    if metadata:
        fields["metadata"] = {
            **dict(item.metadata or {}),
            **dict(metadata),
        }
    return item.model_copy(update=fields) if fields else item


def _workspace_item_progress(
    item: TaskWorkspaceItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    source_step_id = str(
        item.source_step_id or (item.metadata or {}).get("source_step_id") or ""
    ).strip()
    if source_step_id and source_step_id in progress_by_step:
        return progress_by_step[source_step_id]

    if str(item.kind or "").strip() == "artifact":
        for path in _workspace_item_path_candidates(item):
            progress = progress_by_artifact_path.get(path)
            if progress:
                return progress

    tool_name = str((item.metadata or {}).get("tool_name") or "").strip()
    if tool_name and tool_name in progress_by_tool:
        return progress_by_tool[tool_name]
    return {}


def _workspace_item_status_from_progress(
    progress: Mapping[str, Any],
    fallback: Any,
) -> str:
    status = str(progress.get("todo_status") or "").strip()
    if status in {"completed", "blocked", "in_progress", "pending", "skipped"}:
        return status
    checkpoint_status = str(progress.get("checkpoint_status") or "").strip()
    if checkpoint_status == "completed":
        return "completed"
    if checkpoint_status in {"blocked", "waiting_approval"}:
        return "blocked"
    if checkpoint_status == "ready":
        return "in_progress"
    return str(fallback or "planned")


def _todo_with_progress(
    todo: TaskTodoItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> TaskTodoItemSnapshot:
    progress = progress_by_step.get(str(todo.step_id or "").strip()) or progress_by_tool.get(
        str(todo.tool_name or "").strip()
    )
    updated = todo
    update = _todo_explicit_update(updated, task_updates)
    if update:
        updated = _apply_todo_update(updated, update)
    if progress:
        metadata = {
            **dict(updated.metadata or {}),
            "runtime_status": str(progress.get("runtime_status") or ""),
            "runtime_event_type": str(progress.get("event_type") or ""),
        }
        updated = updated.model_copy(
            update={
                "status": str(progress.get("todo_status") or updated.status),
                "metadata": metadata,
            }
        )
    return updated


def _todo_explicit_update(
    todo: TaskTodoItemSnapshot,
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> Mapping[str, Any]:
    todo_id = str(todo.todo_id or "").strip()
    step_id = str(todo.step_id or "").strip()
    return (
        task_updates.get("todo_by_id", {}).get(todo_id)
        or task_updates.get("todo_by_step", {}).get(step_id)
        or {}
    )


def _apply_todo_update(
    todo: TaskTodoItemSnapshot,
    update: Mapping[str, Any],
) -> TaskTodoItemSnapshot:
    fields = {
        key: value
        for key, value in dict(update).items()
        if key
        in {
            "todo_id",
            "title",
            "status",
            "capability_id",
            "step_id",
            "tool_name",
            "approval_required",
            "depends_on",
            "reason",
        }
    }
    metadata = update.get("metadata") if isinstance(update.get("metadata"), Mapping) else {}
    if metadata:
        fields["metadata"] = {
            **dict(todo.metadata or {}),
            **dict(metadata),
        }
    return todo.model_copy(update=fields) if fields else todo


def _checkpoint_with_progress(
    checkpoint: TaskCheckpointSnapshot,
    todo_status_by_step: Mapping[str, str],
    progress_by_step: Mapping[str, Mapping[str, Any]],
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> TaskCheckpointSnapshot:
    step_id = str(checkpoint.after_step_id or "").strip()
    progress = (progress_by_step.get(step_id) if step_id else {}) or {}
    checkpoint_status = str(progress.get("checkpoint_status") or "").strip()
    if not checkpoint_status:
        todo_status = todo_status_by_step.get(step_id)
        checkpoint_status = (
            "completed"
            if todo_status == "completed"
            else ("blocked" if todo_status == "blocked" else "")
        )
    updated = checkpoint
    update = _checkpoint_explicit_update(updated, task_updates)
    if update:
        updated = _apply_checkpoint_update(updated, update)
    if checkpoint_status:
        payload = {
            **dict(updated.payload or {}),
            "runtime_status": str(progress.get("runtime_status") or checkpoint_status),
            "runtime_event_type": str(progress.get("event_type") or ""),
        }
        updated = updated.model_copy(
            update={
                "status": checkpoint_status,
                "payload": payload,
            }
        )
    return updated


def _checkpoint_explicit_update(
    checkpoint: TaskCheckpointSnapshot,
    task_updates: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> Mapping[str, Any]:
    checkpoint_id = str(checkpoint.checkpoint_id or "").strip()
    after_step_id = str(checkpoint.after_step_id or "").strip()
    return (
        task_updates.get("checkpoint_by_id", {}).get(checkpoint_id)
        or task_updates.get("checkpoint_by_step", {}).get(after_step_id)
        or {}
    )


def _apply_checkpoint_update(
    checkpoint: TaskCheckpointSnapshot,
    update: Mapping[str, Any],
) -> TaskCheckpointSnapshot:
    fields = {
        key: value
        for key, value in dict(update).items()
        if key
        in {
            "checkpoint_id",
            "title",
            "status",
            "after_step_id",
            "depends_on",
            "verifies",
            "replan_on_failure",
        }
    }
    payload = update.get("payload") if isinstance(update.get("payload"), Mapping) else {}
    if payload:
        fields["payload"] = {
            **dict(checkpoint.payload or {}),
            **dict(payload),
        }
    return checkpoint.model_copy(update=fields) if fields else checkpoint


def _workspace_item_path_candidates(item: TaskWorkspaceItemSnapshot) -> list[str]:
    candidates: list[str] = []
    for value in (
        item.path,
        item.title,
        (item.metadata or {}).get("planned_artifact"),
        (item.metadata or {}).get("artifact_path"),
    ):
        clean = str(value or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
    return candidates


def _event_artifact_paths(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    _extend_artifact_paths(values, payload)
    for artifact_payload in _artifact_payload_candidates(payload):
        _extend_artifact_paths(values, artifact_payload)
    result = payload.get("result")
    if isinstance(result, Mapping):
        _extend_artifact_paths(values, result)
        data = result.get("data")
        if isinstance(data, Mapping):
            _extend_artifact_paths(values, data)
    return values


def _event_can_update_artifact_path(event_type: str, payload: Mapping[str, Any]) -> bool:
    event_name = str(event_type or "").strip()
    if "artifact" in event_name:
        return True
    tool_name = _event_tool_name(payload)
    if tool_name == "artifact.write":
        return True
    result = payload.get("result")
    payloads: list[Mapping[str, Any]] = [payload]
    if isinstance(result, Mapping):
        payloads.append(result)
        data = result.get("data")
        if isinstance(data, Mapping):
            payloads.append(data)
    return any(
        any(key in item for key in ("artifact_path", "artifact_paths", "artifact_manifest"))
        for item in payloads
    )


def _extend_artifact_paths(values: list[str], payload: Mapping[str, Any]) -> None:
    for key in ("artifact_path", "path"):
        clean = str(payload.get(key) or "").strip()
        if clean and clean not in values:
            values.append(clean)
    for key in ("artifact_paths", "paths"):
        raw_paths = payload.get(key)
        if not isinstance(raw_paths, list):
            continue
        for path in raw_paths:
            clean = str(path or "").strip()
            if clean and clean not in values:
                values.append(clean)
    artifact_manifest = payload.get("artifact_manifest")
    if isinstance(artifact_manifest, list):
        for item in artifact_manifest:
            if not isinstance(item, Mapping):
                continue
            clean = str(item.get("path") or "").strip()
            if clean and clean not in values:
                values.append(clean)


def _event_step_ids(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("step_id", "planner_step_id", "source_step_id"):
        clean = str(payload.get(key) or "").strip()
        if clean and clean not in values:
            values.append(clean)
    return values


def _event_tool_name(payload: Mapping[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("tool") or "").strip()


_SCOPED_PLANNER_EVENT_TYPES = {
    "group.run.plan.created": "agent.plan.created",
    "group.run.plan.step": "agent.plan.step",
    "group.run.task_core.created": "agent.task_core.created",
    "group.run.replan.requested": "agent.replan.requested",
    "group.run.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "group.run.task.todo.updated": "agent.task.todo.updated",
    "group.run.task.checkpoint.updated": "agent.task.checkpoint.updated",
    "workflow.plan.created": "agent.plan.created",
    "workflow.plan.step": "agent.plan.step",
    "workflow.task_core.created": "agent.task_core.created",
    "workflow.replan.requested": "agent.replan.requested",
    "workflow.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "workflow.task.todo.updated": "agent.task.todo.updated",
    "workflow.task.checkpoint.updated": "agent.task.checkpoint.updated",
    "workflow.run.plan.created": "agent.plan.created",
    "workflow.run.plan.step": "agent.plan.step",
    "workflow.run.task_core.created": "agent.task_core.created",
    "workflow.run.replan.requested": "agent.replan.requested",
    "workflow.run.task.workspace_item.updated": "agent.task.workspace_item.updated",
    "workflow.run.task.todo.updated": "agent.task.todo.updated",
    "workflow.run.task.checkpoint.updated": "agent.task.checkpoint.updated",
}


def _planner_event_type(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    explicit = _text(payload.get("planner_event_type"))
    if explicit:
        return explicit
    event_type = _text(event.event_type)
    return _SCOPED_PLANNER_EVENT_TYPES.get(event_type, event_type)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return str(value or "").strip()
