"""Task-core progress projections for runtime tool execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from apps.shell.agent.runtime.event_scopes import (
    runtime_progress_base_event_type as _runtime_progress_base_event_type,
    runtime_progress_event_payload as _runtime_progress_event_payload,
    runtime_progress_event_type as _runtime_progress_event_type,
)


def append_task_progress_events_for_tool_result(
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None = None,
    run_id: str = "",
) -> None:
    explicit_step_id = str(
        tool_request.get("step_id") or tool_request.get("planner_step_id") or ""
    ).strip()
    replan_request_id = str(tool_request.get("replan_request_id") or "").strip()
    step_id = explicit_step_id or _replan_recovery_projection_step_id(
        tool_request,
        replan_request_id,
    )
    tool_name = str(tool_request.get("tool") or tool_request.get("tool_name") or "").strip()
    if not step_id or not tool_name:
        return

    todo = tool_request.get("task_todo") if isinstance(tool_request.get("task_todo"), Mapping) else {}
    checkpoints = _mapping_items(tool_request.get("task_checkpoints"))
    workspace_items = _mapping_items(tool_request.get("task_workspace_items"))
    verification_targets = _mapping_items(tool_request.get("task_verification_targets"))
    if (
        not todo
        and not checkpoints
        and not workspace_items
        and not verification_targets
        and not replan_request_id
    ):
        return

    result = _tool_event_result(tool_event)
    todo_status = _task_todo_status_for_tool_result(
        str(tool_event.get("event") or ""),
        result,
        tool_request=tool_request,
    )
    checkpoint_status = _task_checkpoint_status_for_todo_status(
        todo_status,
        result,
        tool_request=tool_request,
    )
    skip_statuses = {todo_status}
    if todo_status != "completed":
        skip_statuses.add("completed")
    task_update_already_recorded = bool(explicit_step_id) and (
        _runtime_planner_step_has_status(
            timeline,
            decision_id=str(tool_request.get("decision_id") or ""),
            step_id=explicit_step_id,
            statuses=skip_statuses,
        )
    )

    source_event = {
        "event": str(tool_event.get("event") or ""),
        "detail": str(tool_event.get("detail") or tool_name),
    }
    base_payload = {
        "source": str(tool_request.get("source") or "runtime_planner"),
        "core_id": str(tool_request.get("core_id") or ""),
        "workspace_id": str(tool_request.get("workspace_id") or ""),
        "decision_id": str(tool_request.get("decision_id") or ""),
        "plan_id": str(tool_request.get("plan_id") or ""),
        "step_id": step_id,
        "tool": tool_name,
        "source_event": source_event,
        "result_preview": _task_progress_result_preview(result),
    }
    base_payload.update(
        _task_progress_verification_context(
            tool_request,
            result,
            verification_targets=verification_targets,
        )
    )
    for key in (
        "task_id",
        "run_group_id",
        "group_run_id",
        "group_id",
        "workflow_run_id",
        "workflow_id",
        "workflow_node_id",
    ):
        value = str(tool_request.get(key) or "").strip()
        if value:
            base_payload[key] = value

    if explicit_step_id and not task_update_already_recorded:
        for workspace_item in workspace_items:
            item_payload = dict(workspace_item)
            item_payload["status"] = todo_status
            _apply_workspace_item_verification_context(
                item_payload,
                base_payload,
            )
            payload = {
                **base_payload,
                "workspace_item_id": str(workspace_item.get("item_id") or "").strip(),
                "status": todo_status,
                "previous_status": str(workspace_item.get("status") or "planned"),
                "workspace_item": item_payload,
            }
            _append_task_progress_event(
                "agent.task.workspace_item.updated",
                str(workspace_item.get("title") or step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )

    if explicit_step_id and todo and not task_update_already_recorded:
        todo_payload = dict(todo)
        todo_payload["status"] = todo_status
        _apply_todo_verification_context(todo_payload, base_payload)
        payload = {
            **base_payload,
            "todo_id": str(todo.get("todo_id") or "").strip(),
            "status": todo_status,
            "previous_status": str(todo.get("status") or "pending"),
            "todo": todo_payload,
        }
        _append_task_progress_event(
            "agent.task.todo.updated",
            str(todo.get("title") or step_id),
            payload,
            timeline=timeline,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            run_id=run_id,
        )

    if explicit_step_id and not task_update_already_recorded:
        for checkpoint in checkpoints:
            checkpoint_payload = dict(checkpoint)
            checkpoint_payload["status"] = checkpoint_status
            _apply_checkpoint_verification_context(checkpoint_payload, base_payload)
            payload = {
                **base_payload,
                "checkpoint_id": str(checkpoint.get("checkpoint_id") or "").strip(),
                "status": checkpoint_status,
                "previous_status": str(checkpoint.get("status") or "planned"),
                "checkpoint": checkpoint_payload,
            }
            _append_task_progress_event(
                "agent.task.checkpoint.updated",
                str(checkpoint.get("title") or step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )

    _append_verification_target_progress_events(
        tool_request,
        verification_targets,
        base_payload,
        result,
        timeline=timeline,
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        run_id=run_id,
    )

    if replan_request_id:
        _append_replan_recovery_update_event(
            tool_request,
            base_payload,
            status=checkpoint_status,
            todo_status=todo_status,
            checkpoint_status=checkpoint_status,
            timeline=timeline,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            run_id=run_id,
        )
        _append_verification_target_progress_events(
            tool_request,
            _verification_targets_from_replan_recovery(tool_request, result),
            base_payload,
            result,
            timeline=timeline,
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            run_id=run_id,
        )


def _append_verification_target_progress_events(
    tool_request: Mapping[str, Any],
    verification_targets: list[Mapping[str, Any]],
    base_payload: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if not verification_targets:
        return
    target_todo_status = _verification_target_todo_status(result)
    target_checkpoint_status = _verification_target_checkpoint_status(result)
    verify_step_id = _first_text(
        tool_request.get("step_id"),
        tool_request.get("planner_step_id"),
        base_payload.get("step_id"),
    )
    verify_tool = str(tool_request.get("tool") or tool_request.get("tool_name") or "").strip()
    for target in verification_targets:
        target_step_id = str(target.get("step_id") or "").strip()
        if not target_step_id:
            continue
        target_base_payload = {
            **dict(base_payload),
            "step_id": target_step_id,
            "verified_by_step_id": verify_step_id,
            "verification_tool": verify_tool,
            "verification_status": _verification_target_status(result),
            "verification_result": _task_progress_result_preview(result),
        }
        todo = target.get("todo") if isinstance(target.get("todo"), Mapping) else {}
        if todo and not _runtime_planner_step_has_status(
            timeline,
            decision_id=str(tool_request.get("decision_id") or ""),
            step_id=target_step_id,
            statuses={target_todo_status},
        ):
            todo_payload = dict(todo)
            todo_payload["status"] = target_todo_status
            _apply_todo_verification_context(todo_payload, target_base_payload)
            payload = {
                **target_base_payload,
                "todo_id": str(todo.get("todo_id") or "").strip(),
                "status": target_todo_status,
                "previous_status": _latest_task_update_status(
                    timeline,
                    "agent.task.todo.updated",
                    "todo_id",
                    str(todo.get("todo_id") or "").strip(),
                    decision_id=str(tool_request.get("decision_id") or ""),
                )
                or str(todo.get("status") or "pending"),
                "todo": todo_payload,
            }
            _append_task_progress_event(
                "agent.task.todo.updated",
                str(todo.get("title") or target_step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )
        for checkpoint in _mapping_items(target.get("checkpoints")):
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "").strip()
            checkpoint_payload = dict(checkpoint)
            checkpoint_payload["status"] = target_checkpoint_status
            _apply_checkpoint_verification_context(checkpoint_payload, target_base_payload)
            payload = {
                **target_base_payload,
                "checkpoint_id": checkpoint_id,
                "status": target_checkpoint_status,
                "previous_status": _latest_task_update_status(
                    timeline,
                    "agent.task.checkpoint.updated",
                    "checkpoint_id",
                    checkpoint_id,
                    decision_id=str(tool_request.get("decision_id") or ""),
                )
                or str(checkpoint.get("status") or "planned"),
                "checkpoint": checkpoint_payload,
            }
            _append_task_progress_event(
                "agent.task.checkpoint.updated",
                str(checkpoint.get("title") or target_step_id),
                payload,
                timeline=timeline,
                timeline_factory=timeline_factory,
                append_run_event=append_run_event,
                run_id=run_id,
            )


def _verification_target_todo_status(result: Mapping[str, Any]) -> str:
    if not isinstance(result, Mapping):
        return "blocked"
    if result.get("approval_required"):
        return "blocked"
    if result.get("verification_failed") is True:
        return "blocked"
    return "completed" if result.get("ok") is True else "blocked"


def _verification_target_checkpoint_status(result: Mapping[str, Any]) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if isinstance(result, Mapping) and result.get("verification_failed") is True:
        return "blocked"
    return "completed" if isinstance(result, Mapping) and result.get("ok") is True else "blocked"


def _task_progress_verification_context(
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    verification_targets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    requires_post_action_verification = bool(
        tool_request.get("requires_post_action_verification")
    )
    runtime_stage = str(tool_request.get("runtime_stage") or "").strip()
    if (
        not requires_post_action_verification
        and runtime_stage != "verify"
        and not verification_targets
    ):
        return {}
    context: dict[str, Any] = {
        "verification_status": _tool_result_verification_status(
            result,
            requires_post_action_verification=requires_post_action_verification,
            runtime_stage=runtime_stage,
        ),
        "verification_result": _task_progress_result_preview(result),
        "verification_target_count": len(verification_targets),
    }
    if requires_post_action_verification:
        context["requires_post_action_verification"] = True
    return context


def _tool_result_verification_status(
    result: Mapping[str, Any],
    *,
    requires_post_action_verification: bool,
    runtime_stage: str,
) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if isinstance(result, Mapping) and result.get("verification_failed") is True:
        return "verification_failed"
    if isinstance(result, Mapping) and result.get("ok") is True:
        if requires_post_action_verification and runtime_stage != "verify":
            return "pending_verification"
        return "verified" if runtime_stage == "verify" else "completed"
    return "verification_failed" if runtime_stage == "verify" else "blocked"


def _verification_target_status(result: Mapping[str, Any]) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if isinstance(result, Mapping) and result.get("verification_failed") is True:
        return "verification_failed"
    return (
        "verified"
        if isinstance(result, Mapping) and result.get("ok") is True
        else "verification_failed"
    )


def _apply_workspace_item_verification_context(
    item_payload: dict[str, Any],
    source: Mapping[str, Any],
) -> None:
    context = _nested_verification_context(source)
    if not context:
        return
    metadata = (
        item_payload.get("metadata")
        if isinstance(item_payload.get("metadata"), Mapping)
        else {}
    )
    item_payload["metadata"] = {**dict(metadata), **context}


def _apply_todo_verification_context(
    todo_payload: dict[str, Any],
    source: Mapping[str, Any],
) -> None:
    context = _nested_verification_context(source)
    if not context:
        return
    metadata = (
        todo_payload.get("metadata")
        if isinstance(todo_payload.get("metadata"), Mapping)
        else {}
    )
    todo_payload["metadata"] = {**dict(metadata), **context}


def _apply_checkpoint_verification_context(
    checkpoint_payload: dict[str, Any],
    source: Mapping[str, Any],
) -> None:
    context = _nested_verification_context(source)
    if not context:
        return
    payload = (
        checkpoint_payload.get("payload")
        if isinstance(checkpoint_payload.get("payload"), Mapping)
        else {}
    )
    checkpoint_payload["payload"] = {**dict(payload), **context}


def _nested_verification_context(source: Mapping[str, Any]) -> dict[str, Any]:
    status = str(source.get("verification_status") or "").strip()
    if not status:
        return {}
    context: dict[str, Any] = {"verification_status": status}
    for key in (
        "requires_post_action_verification",
        "verification_target_count",
        "verified_by_step_id",
        "verification_tool",
    ):
        value = source.get(key)
        if value not in (None, "", [], {}):
            context[key] = value
    result = source.get("verification_result")
    if isinstance(result, Mapping) and result:
        context["verification_result"] = dict(result)
    return context


def _verification_targets_from_replan_recovery(
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if result.get("ok") is not True or result.get("verification_failed") is True:
        return []
    targets: list[dict[str, Any]] = []
    raw_targets = [
        *_mapping_items(tool_request.get("verification_targets")),
        *_mapping_items(tool_request.get("task_verification_targets")),
    ]
    if not raw_targets:
        fallback_target = _replan_recovery_target_from_task_context(tool_request)
        if fallback_target:
            raw_targets = [fallback_target]
    for target in raw_targets:
        step_id = str(target.get("step_id") or "").strip()
        if not step_id:
            continue
        todo = target.get("todo") if isinstance(target.get("todo"), Mapping) else {}
        if not todo:
            todo_id = str(target.get("todo_id") or "").strip()
            todo_title = str(target.get("todo_title") or target.get("title") or "").strip()
            tool_name = str(target.get("tool_name") or target.get("tool") or "").strip()
            if todo_id:
                todo = {
                    key: value
                    for key, value in {
                        "todo_id": todo_id,
                        "title": todo_title or step_id,
                        "status": str(target.get("status") or "blocked").strip(),
                        "step_id": step_id,
                        "tool_name": tool_name,
                    }.items()
                    if value
                }
        checkpoints = _mapping_items(target.get("checkpoints"))
        if not checkpoints:
            checkpoint_ids = _string_list(target.get("checkpoint_ids"))
            checkpoint_titles = _string_list(target.get("checkpoint_titles"))
            checkpoints = [
                {
                    "checkpoint_id": checkpoint_id,
                    "title": (
                        checkpoint_titles[index]
                        if index < len(checkpoint_titles)
                        else checkpoint_id
                    ),
                    "status": "blocked",
                    "after_step_id": step_id,
                }
                for index, checkpoint_id in enumerate(checkpoint_ids)
            ]
        targets.append(
            {
                "step_id": step_id,
                "todo": dict(todo) if isinstance(todo, Mapping) else {},
                "checkpoints": [dict(checkpoint) for checkpoint in checkpoints],
            }
        )
    return targets


def _replan_recovery_target_from_task_context(
    tool_request: Mapping[str, Any],
) -> dict[str, Any]:
    todo = (
        tool_request.get("task_todo")
        if isinstance(tool_request.get("task_todo"), Mapping)
        else {}
    )
    checkpoints = _mapping_items(tool_request.get("task_checkpoints"))
    workspace_items = _mapping_items(tool_request.get("task_workspace_items"))
    step_id = _first_text(
        todo.get("step_id") if isinstance(todo, Mapping) else "",
        *(checkpoint.get("after_step_id") for checkpoint in checkpoints),
        *(item.get("source_step_id") for item in workspace_items),
        tool_request.get("source_step_id"),
        tool_request.get("planner_step_id"),
        tool_request.get("step_id"),
    )
    if not step_id or (not todo and not checkpoints):
        return {}
    target: dict[str, Any] = {"step_id": step_id}
    if todo:
        target["todo"] = dict(todo)
    if checkpoints:
        target["checkpoints"] = [dict(checkpoint) for checkpoint in checkpoints]
    return target


def _tool_event_result(tool_event: Mapping[str, Any]) -> dict[str, Any]:
    raw_result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
    result = dict(raw_result)
    if tool_event.get("verification_failed") is True:
        result["verification_failed"] = True
    return result


def _append_replan_recovery_update_event(
    tool_request: Mapping[str, Any],
    base_payload: Mapping[str, Any],
    *,
    status: str,
    todo_status: str,
    checkpoint_status: str,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    request_id = str(tool_request.get("replan_request_id") or "").strip()
    if not request_id:
        return
    task_todo = (
        tool_request.get("task_todo")
        if isinstance(tool_request.get("task_todo"), Mapping)
        else {}
    )
    trigger = _replan_recovery_trigger(tool_request)
    replan_triggers = _string_list(tool_request.get("replan_triggers"))
    if trigger and trigger not in replan_triggers:
        replan_triggers.append(trigger)
    replan_signal_ids = _string_list(tool_request.get("replan_signal_ids"))
    action_id = _first_text(
        tool_request.get("replan_recovery_action_id"),
        tool_request.get("action_id"),
    )
    payload: dict[str, Any] = {
        **dict(base_payload),
        "request_id": request_id,
        "replan_request_id": request_id,
        "trigger": trigger,
        "replan_trigger": trigger,
        "status": status,
        "source_step_id": str(
            tool_request.get("source_step_id")
            or tool_request.get("planner_step_id")
            or tool_request.get("step_id")
            or ""
        ).strip(),
        "source_tool_name": _first_text(
            tool_request.get("source_tool_name"),
            task_todo.get("tool_name") if isinstance(task_todo, Mapping) else "",
        ),
        "selected_step_id": _first_text(
            tool_request.get("step_id"),
            tool_request.get("planner_step_id"),
            base_payload.get("step_id"),
        ),
        "selected_tool_name": str(
            tool_request.get("tool") or tool_request.get("tool_name") or ""
        ).strip(),
        "target_capability_id": str(
            tool_request.get("capability_id")
            or tool_request.get("target_capability_id")
            or ""
        ).strip(),
        "planning_reason": str(tool_request.get("planning_reason") or "").strip(),
        "tool_status": status,
        "todo_status": todo_status,
        "checkpoint_status": checkpoint_status,
    }
    if action_id:
        payload["replan_recovery_action_id"] = action_id
    if replan_triggers:
        payload["replan_triggers"] = replan_triggers
    if replan_signal_ids:
        payload["replan_signal_ids"] = replan_signal_ids
    for key in ("task_id", "group_run_id", "workflow_run_id"):
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in ("recovery_action_label", "permission_target", "risk_level"):
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    fallback_tools = _string_list(tool_request.get("fallback_tools"))
    selected_tool = str(payload.get("selected_tool_name") or "").strip()
    if selected_tool and selected_tool not in fallback_tools:
        fallback_tools.append(selected_tool)
    if fallback_tools:
        payload["fallback_tools"] = fallback_tools
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = tool_request.get(key)
        if isinstance(value, Mapping) and value:
            payload[key] = dict(value)
    verification_targets = _mapping_items(tool_request.get("verification_targets"))
    if verification_targets:
        payload["verification_targets"] = [dict(target) for target in verification_targets]
    task_verification_targets = _mapping_items(tool_request.get("task_verification_targets"))
    if task_verification_targets:
        payload["task_verification_targets"] = [
            dict(target) for target in task_verification_targets
        ]
        payload.setdefault(
            "verification_targets",
            [dict(target) for target in task_verification_targets],
        )
    action_record = _replan_recovery_update_action_record(
        tool_request,
        payload,
        action_id=action_id,
        selected_tool=selected_tool,
        verification_targets=verification_targets or task_verification_targets,
    )
    if action_record:
        payload["recovery_actions"] = [action_record]
    _append_replan_progress_event(
        "agent.replan.recovery.updated",
        str(payload.get("recovery_action_label") or selected_tool or request_id),
        payload,
        timeline=timeline,
        timeline_factory=timeline_factory,
        append_run_event=append_run_event,
        run_id=run_id,
    )


def _replan_recovery_update_action_record(
    tool_request: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    action_id: str,
    selected_tool: str,
    verification_targets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not selected_tool:
        return {}
    action_input = (
        tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    )
    metadata: dict[str, Any] = {}
    for key in (
        "replan_request_id",
        "replan_trigger",
        "replan_triggers",
        "replan_signal_ids",
        "source_step_id",
        "source_tool_name",
        "runtime_stage",
        "target_capability_id",
        "replan_recovery_action_id",
    ):
        value = payload.get(key) or tool_request.get(key)
        if value not in (None, "", [], {}):
            metadata[key] = list(value) if isinstance(value, list) else value
    target_step_ids: list[str] = []
    for target in verification_targets:
        step_id = str(target.get("step_id") or "").strip()
        if step_id and step_id not in target_step_ids:
            target_step_ids.append(step_id)
    if target_step_ids:
        metadata["verification_target_step_ids"] = target_step_ids
    action: dict[str, Any] = {
        "action_id": action_id or f"{payload.get('request_id')}:action:1:{selected_tool}",
        "label": str(payload.get("recovery_action_label") or selected_tool).strip(),
        "tool": selected_tool,
        "input": dict(action_input),
        "planning_reason": str(payload.get("planning_reason") or "").strip(),
        "permission_target": str(payload.get("permission_target") or "").strip(),
        "risk_level": str(payload.get("risk_level") or "").strip(),
        "approval_required": bool(tool_request.get("approval_required")),
        "selected": True,
        "metadata": metadata,
    }
    if verification_targets:
        action["verification_targets"] = [dict(target) for target in verification_targets]
        action["task_verification_targets"] = [
            dict(target) for target in verification_targets
        ]
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = payload.get(key)
        if isinstance(value, Mapping) and value:
            action[key] = dict(value)
    return action


def _replan_recovery_trigger(tool_request: Mapping[str, Any]) -> str:
    trigger = str(tool_request.get("replan_trigger") or "").strip()
    if trigger:
        return trigger
    triggers = _string_list(tool_request.get("replan_triggers"))
    return triggers[0] if triggers else "tool_failure"


def _replan_recovery_projection_step_id(
    tool_request: Mapping[str, Any],
    request_id: str,
) -> str:
    if not request_id:
        return ""
    action_id = _first_text(
        tool_request.get("action_id"),
        tool_request.get("replan_recovery_action_id"),
    )
    if action_id:
        return f"replan-recovery:{request_id}:{action_id}"
    return f"replan-recovery:{request_id}"


def _append_replan_progress_event(
    event_type: str,
    detail: str,
    payload: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if _runtime_replan_recovery_update_exists(timeline, event_type, payload):
        return
    scoped_event_type = _runtime_progress_event_type(event_type, payload)
    event_payload = _runtime_progress_event_payload(payload, event_type, scoped_event_type)
    timeline.append(timeline_factory(scoped_event_type, detail, **event_payload))
    if run_id and append_run_event is not None:
        append_run_event(run_id, scoped_event_type, event_payload)


def _runtime_replan_recovery_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    request_id = str(payload.get("request_id") or payload.get("replan_request_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    selected_tool = str(payload.get("selected_tool_name") or payload.get("tool") or "").strip()
    return any(
        isinstance(event, Mapping)
        and _runtime_progress_base_event_type(str(event.get("event") or "").strip())
        == event_type
        and _first_text(
            event.get("request_id"),
            event.get("replan_request_id"),
            _event_payload(event).get("request_id"),
            _event_payload(event).get("replan_request_id"),
        )
        == request_id
        and (
            not status
            or str(event.get("status") or _event_payload(event).get("status") or "").strip()
            == status
        )
        and (
            not selected_tool
            or _first_text(
                event.get("selected_tool_name"),
                event.get("tool"),
                _event_payload(event).get("selected_tool_name"),
                _event_payload(event).get("tool"),
            )
            == selected_tool
        )
        for event in timeline
    )


def _first_text(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _append_task_progress_event(
    event_type: str,
    detail: str,
    payload: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None,
    run_id: str,
) -> None:
    if _runtime_task_update_exists(timeline, event_type, payload):
        return
    scoped_event_type = _runtime_progress_event_type(event_type, payload)
    event_payload = _runtime_progress_event_payload(payload, event_type, scoped_event_type)
    timeline.append(timeline_factory(scoped_event_type, detail, **event_payload))
    if run_id and append_run_event is not None:
        append_run_event(run_id, scoped_event_type, event_payload)


def _task_todo_status_for_tool_result(
    event_type: str,
    result: Mapping[str, Any],
    *,
    tool_request: Mapping[str, Any] | None = None,
) -> str:
    if not isinstance(result, Mapping):
        return "blocked"
    if result.get("approval_required"):
        return "blocked"
    if str(event_type or "").strip() == "agent.tool.skipped":
        return "skipped" if result.get("blocked_by_user_goal") else "blocked"
    if (
        result.get("ok") is True
        and isinstance(tool_request, Mapping)
        and bool(tool_request.get("requires_post_action_verification"))
    ):
        return "in_progress"
    return "blocked" if _tool_result_requests_replan(result) else "completed"


def _task_checkpoint_status_for_todo_status(
    todo_status: str,
    result: Mapping[str, Any],
    *,
    tool_request: Mapping[str, Any] | None = None,
) -> str:
    if isinstance(result, Mapping) and result.get("approval_required"):
        return "waiting_approval"
    if (
        todo_status == "in_progress"
        and isinstance(tool_request, Mapping)
        and bool(tool_request.get("requires_post_action_verification"))
    ):
        return "ready"
    if todo_status == "completed":
        return "completed"
    return "blocked"


def _tool_result_requests_replan(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return True
    if result.get("verification_failed") is True:
        return True
    if result.get("ok") is True and not result.get("approval_required"):
        return False
    return True


def _task_progress_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "action",
        "summary",
        "error",
        "hint",
        "returncode",
        "exit_code",
        "blocked_by_user_goal",
        "approval_required",
        "verification_failed",
    ):
        if key in result:
            preview[key] = result.get(key)
    stderr = str(result.get("stderr") or "").strip()
    if stderr:
        preview["stderr"] = stderr[:500]
    return preview


def _runtime_task_update_exists(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: Mapping[str, Any],
) -> bool:
    identity_key = (
        "todo_id"
        if event_type == "agent.task.todo.updated"
        else "workspace_item_id"
        if event_type == "agent.task.workspace_item.updated"
        else "checkpoint_id"
        if event_type == "agent.task.checkpoint.updated"
        else ""
    )
    identity = str(payload.get(identity_key) or "").strip() if identity_key else ""
    status = str(payload.get("status") or "").strip()
    decision_id = str(payload.get("decision_id") or "").strip()
    return any(
        isinstance(event, Mapping)
        and _runtime_progress_base_event_type(str(event.get("event") or "").strip())
        == event_type
        and (
            not decision_id
            or str(event.get("decision_id") or "").strip() == decision_id
            or str(_event_payload(event).get("decision_id") or "").strip() == decision_id
        )
        and (
            not identity
            or str(event.get(identity_key) or "").strip() == identity
            or str(_event_payload(event).get(identity_key) or "").strip() == identity
        )
        and (
            not status
            or str(event.get("status") or "").strip() == status
            or str(_event_payload(event).get("status") or "").strip() == status
        )
        and not _plan_seed_event_should_allow_runtime_update(event, payload)
        for event in timeline
    )


def _plan_seed_event_should_allow_runtime_update(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    existing_source = _task_update_source_event_name(event)
    next_source = _task_update_source_event_name(payload)
    return existing_source == "agent.plan.created" and bool(
        next_source and next_source != "agent.plan.created"
    )


def _task_update_source_event_name(value: Mapping[str, Any]) -> str:
    source = value.get("source_event")
    if not isinstance(source, Mapping):
        source = _event_payload(value).get("source_event")
    if not isinstance(source, Mapping):
        return ""
    return str(source.get("event") or "").strip()


def _runtime_planner_step_has_status(
    timeline: list[dict[str, Any]],
    *,
    decision_id: str,
    step_id: str,
    statuses: set[str],
) -> bool:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id:
        return False
    clean_decision_id = str(decision_id or "").strip()
    expected_statuses = {
        str(status or "").strip()
        for status in statuses
        if str(status or "").strip()
    }
    if not expected_statuses:
        return False
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        payload = _event_payload(event)
        if (
            _runtime_progress_base_event_type(str(event.get("event") or "").strip())
            != "agent.task.todo.updated"
        ):
            continue
        event_step_id = str(event.get("step_id") or payload.get("step_id") or "").strip()
        if event_step_id != clean_step_id:
            continue
        event_decision_id = str(
            event.get("decision_id") or payload.get("decision_id") or ""
        ).strip()
        if clean_decision_id and event_decision_id != clean_decision_id:
            continue
        event_status = str(event.get("status") or payload.get("status") or "").strip()
        if event_status in expected_statuses:
            return True
    return False


def _latest_task_update_status(
    timeline: list[dict[str, Any]],
    event_type: str,
    identity_key: str,
    identity: str,
    *,
    decision_id: str,
) -> str:
    clean_identity = str(identity or "").strip()
    if not clean_identity:
        return ""
    clean_decision_id = str(decision_id or "").strip()
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        if _runtime_progress_base_event_type(str(event.get("event") or "").strip()) != event_type:
            continue
        payload = _event_payload(event)
        event_identity = str(
            event.get(identity_key) or payload.get(identity_key) or ""
        ).strip()
        if event_identity != clean_identity:
            continue
        event_decision_id = str(
            event.get("decision_id") or payload.get("decision_id") or ""
        ).strip()
        if clean_decision_id and event_decision_id != clean_decision_id:
            continue
        return str(event.get("status") or payload.get("status") or "").strip()
    return ""


def _mapping_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}
