"""Replan request helpers for DeepAgent-style task core execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    PlannerDecisionSnapshot,
    ReplanSignalSnapshot,
    TaskReplanRequestSnapshot,
    ToolPlanStepSnapshot,
)

_REPLAN_TRIGGERS = {"tool_failure", "tool_unavailable", "verification_failed"}


def task_replan_request_from_failure(
    decision: PlannerDecisionSnapshot,
    failure: Mapping[str, Any] | None = None,
    *,
    trigger: str = "",
    run_id: str | None = None,
    task_id: str | None = None,
    source_step_id: str = "",
    tool_name: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> TaskReplanRequestSnapshot | None:
    """Build a replayable replan request from a failed runtime observation."""
    failure_payload = dict(failure or {})
    clean_trigger = _replan_trigger(trigger, failure_payload)
    clean_step_id = _text(
        source_step_id
        or failure_payload.get("source_step_id")
        or failure_payload.get("step_id")
        or failure_payload.get("planner_step_id")
    )
    clean_tool_name = _text(
        tool_name
        or failure_payload.get("tool_name")
        or failure_payload.get("tool")
        or failure_payload.get("detail")
    )
    signal = _matching_replan_signal(decision, clean_trigger, clean_step_id, clean_tool_name)
    step = _matching_plan_step(decision, clean_step_id, clean_tool_name, signal)
    if signal is None and step is None:
        return None

    target_capability = _text(getattr(signal, "target", "") if signal else "")
    if not target_capability and step is not None:
        target_capability = _text(step.capability_id)
    failure_event_type = _text(
        failure_payload.get("event_type") or failure_payload.get("event") or clean_trigger
    )
    failure_detail = _failure_detail(failure_payload)
    fallback_tools = _fallback_tools(signal, step)
    source_step = clean_step_id or _text(getattr(signal, "source_step_id", "") if signal else "")
    if not source_step and step is not None:
        source_step = _text(step.step_id)
    source_tool = clean_tool_name
    if not source_tool and step is not None:
        source_tool = _text(step.tool_name)
    condition = _text(getattr(signal, "condition", "") if signal else "") or failure_detail
    reason = _text(getattr(signal, "reason", "") if signal else "") or (
        "Runtime requested a replan after a failed or unverified step."
    )
    plan = decision.plan
    task_core = getattr(plan, "task_core", None)
    request_id = _stable_id(
        "replan-request",
        decision.decision_id,
        plan.plan_id,
        source_step,
        clean_trigger,
        failure_detail,
    )
    matched_step_id = _text(getattr(step, "step_id", "") if step is not None else "")
    task_context = _task_core_replan_context(
        decision,
        source_step,
        matched_step_id=matched_step_id,
    )
    if not fallback_tools:
        fallback_tools = _default_recovery_tools(
            target_capability,
            step,
            failure_payload,
        )
    desktop_loop_retry_tool = _desktop_loop_retry_tool(failure_payload)
    if desktop_loop_retry_tool and desktop_loop_retry_tool not in fallback_tools:
        fallback_tools = [desktop_loop_retry_tool, *fallback_tools]
    recovery_actions = _dedupe_recovery_actions(
        [
            *_desktop_loop_recovery_actions(
                failure_payload,
                source_step_id=source_step,
                target_capability_id=target_capability,
                task_context=task_context,
            ),
            *_fallback_recovery_actions(
                fallback_tools,
                step,
                failure_payload,
                source_step_id=source_step,
                target_capability_id=target_capability,
                task_context=task_context,
            ),
        ]
    )
    request_metadata = {
        **dict(metadata or {}),
        **_signal_metadata(signal),
        "original_intent_kind": _text(decision.selected_intent.kind),
    }
    if task_context:
        request_metadata["task_core_context"] = task_context
    if recovery_actions and "recovery_actions" not in request_metadata:
        request_metadata["recovery_actions"] = recovery_actions
    return TaskReplanRequestSnapshot(
        request_id=request_id,
        trigger=clean_trigger,
        run_id=_optional_text(run_id or failure_payload.get("run_id")),
        task_id=_optional_text(task_id or failure_payload.get("task_id")),
        decision_id=decision.decision_id,
        plan_id=plan.plan_id,
        core_id=_optional_text(getattr(task_core, "core_id", None)),
        source_step_id=_optional_text(source_step),
        source_tool_name=_optional_text(source_tool),
        target_capability_id=target_capability,
        condition=condition,
        reason=reason,
        failure_event_type=failure_event_type,
        failure_detail=failure_detail,
        fallback_tools=fallback_tools,
        recovery_actions=recovery_actions,
        replan_prompt=_replan_prompt(
            decision,
            trigger=clean_trigger,
            source_step_id=source_step,
            source_tool_name=source_tool,
            target_capability_id=target_capability,
            failure_detail=failure_detail,
            fallback_tools=fallback_tools,
            task_context=task_context,
        ),
        metadata=request_metadata,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def task_replan_run_event_payload(
    request: TaskReplanRequestSnapshot,
) -> tuple[str, dict[str, Any]]:
    return "agent.replan.requested", request.model_dump(mode="json")


def task_replan_timeline_event(
    request: TaskReplanRequestSnapshot,
) -> dict[str, Any]:
    event_type, payload = task_replan_run_event_payload(request)
    detail = request.reason or request.failure_detail or request.trigger
    return {
        "event": event_type,
        "detail": detail,
        "status": request.status,
        "source": request.source,
        "decision_id": request.decision_id or "",
        "plan_id": request.plan_id or "",
        "payload": payload,
    }


def _matching_replan_signal(
    decision: PlannerDecisionSnapshot,
    trigger: str,
    source_step_id: str,
    tool_name: str,
) -> ReplanSignalSnapshot | None:
    task_core = getattr(decision.plan, "task_core", None)
    signals = list(getattr(task_core, "replan_signals", []) or [])
    if source_step_id:
        for signal in signals:
            if _text(signal.source_step_id) == source_step_id and _text(signal.trigger) == trigger:
                return signal
        for signal in signals:
            if _text(signal.source_step_id) == source_step_id:
                return signal
    if tool_name:
        step = _matching_plan_step(decision, "", tool_name, None)
        step_id = _text(getattr(step, "step_id", "") if step else "")
        if step_id:
            for signal in signals:
                if _text(signal.source_step_id) == step_id and _text(signal.trigger) == trigger:
                    return signal
            for signal in signals:
                if _text(signal.source_step_id) == step_id:
                    return signal
    for signal in signals:
        if _text(signal.trigger) == trigger:
            return signal
    return signals[0] if signals else None


def _matching_plan_step(
    decision: PlannerDecisionSnapshot,
    source_step_id: str,
    tool_name: str,
    signal: ReplanSignalSnapshot | None,
) -> ToolPlanStepSnapshot | None:
    steps = list(decision.plan.tool_plan.steps)
    signal_step_id = _text(getattr(signal, "source_step_id", "") if signal else "")
    for candidate in (source_step_id, signal_step_id):
        if not candidate:
            continue
        for step in steps:
            if _text(step.step_id) == candidate:
                return step
    if tool_name:
        for step in steps:
            if _text(step.tool_name) == tool_name:
                return step
    return None


def _fallback_tools(
    signal: ReplanSignalSnapshot | None,
    step: ToolPlanStepSnapshot | None,
) -> list[str]:
    values: list[str] = []
    for item in list(getattr(signal, "fallback_tools", []) if signal else []):
        clean = _text(item)
        if clean and clean not in values:
            values.append(clean)
    for item in list(getattr(step, "fallback_tools", []) if step else []):
        clean = _text(item)
        if clean and clean not in values:
            values.append(clean)
    return values


def _replan_trigger(trigger: str, failure: Mapping[str, Any]) -> str:
    clean = _text(trigger or failure.get("trigger"))
    if clean in _REPLAN_TRIGGERS:
        return clean
    status = _text(failure.get("status") or failure.get("event_type") or failure.get("event")).lower()
    detail = _failure_detail(failure).lower()
    if "unavailable" in status or "unavailable" in detail or "missing" in detail:
        return "tool_unavailable"
    if "verify" in status or "verification" in status or "verify" in detail:
        return "verification_failed"
    return "tool_failure"


def _failure_detail(failure: Mapping[str, Any]) -> str:
    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    parts = [
        _text(failure.get("detail")),
        _text(failure.get("error")),
        _text(result.get("error")),
        _text(result.get("hint")),
        _text(result.get("stderr"))[:500],
    ]
    clean_parts = [part for part in parts if part]
    if clean_parts:
        return "；".join(clean_parts)
    if failure:
        try:
            return json.dumps(dict(failure), ensure_ascii=False)[:1000]
        except Exception:
            return str(failure)[:1000]
    return ""


def _replan_prompt(
    decision: PlannerDecisionSnapshot,
    *,
    trigger: str,
    source_step_id: str,
    source_tool_name: str,
    target_capability_id: str,
    failure_detail: str,
    fallback_tools: list[str],
    task_context: Mapping[str, Any] | None = None,
) -> str:
    parts = [
        decision.prompt,
        "",
        "Runtime replan request:",
        f"- trigger: {trigger}",
    ]
    if source_step_id:
        parts.append(f"- failed_step: {source_step_id}")
    if source_tool_name:
        parts.append(f"- failed_tool: {source_tool_name}")
    if target_capability_id:
        parts.append(f"- target_capability: {target_capability_id}")
    if failure_detail:
        parts.append(f"- failure_detail: {failure_detail}")
    if fallback_tools:
        parts.append(f"- preferred_fallback_tools: {', '.join(fallback_tools)}")
    task_lines = _task_core_replan_prompt_lines(task_context or {})
    if task_lines:
        parts.extend(["", "Task workspace context:", *task_lines])
    parts.append(
        "Continue from the existing task workspace. Do not restart completed steps; "
        "inspect current state, choose the next safe observable action, and keep approval gates."
    )
    return "\n".join(parts)


def _task_core_replan_context(
    decision: PlannerDecisionSnapshot,
    source_step_id: str,
    *,
    matched_step_id: str = "",
) -> dict[str, Any]:
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return {}
    workspace = getattr(task_core, "workspace", None)
    context = {
        "core_id": _text(getattr(task_core, "core_id", "")),
        "workspace_id": _text(getattr(workspace, "workspace_id", "")),
        "workspace_title": _text(getattr(workspace, "title", "")),
        "source_step_id": _text(source_step_id),
        "planner_step_id": _text(matched_step_id),
    }
    source_step = _text(source_step_id)
    plan_step = _text(matched_step_id or source_step_id)
    workspace_items = _context_rows(
        getattr(workspace, "items", []) or [],
        focus=lambda item: _text(getattr(item, "source_step_id", "")) in {source_step, plan_step},
        include=lambda item: _text(getattr(item, "kind", "")) in {"input", "artifact", "scratch"},
        serialize=lambda item: {
            "item_id": _text(getattr(item, "item_id", "")),
            "title": _text(getattr(item, "title", "")),
            "kind": _text(getattr(item, "kind", "")),
            "path": _text(getattr(item, "path", "")),
            "status": _text(getattr(item, "status", "")),
            "source_step_id": _text(getattr(item, "source_step_id", "")),
        },
        limit=8,
    )
    todos = _context_rows(
        getattr(task_core, "todos", []) or [],
        focus=lambda item: _text(getattr(item, "step_id", "")) == plan_step,
        include=lambda item: _text(getattr(item, "status", ""))
        in {"blocked", "in_progress", "pending", "waiting_approval"},
        serialize=lambda item: {
            "todo_id": _text(getattr(item, "todo_id", "")),
            "title": _text(getattr(item, "title", "")),
            "status": _text(getattr(item, "status", "")),
            "step_id": _text(getattr(item, "step_id", "")),
            "tool_name": _text(getattr(item, "tool_name", "")),
            "capability_id": _text(getattr(item, "capability_id", "")),
            "approval_required": bool(getattr(item, "approval_required", False)),
        },
        limit=8,
    )
    checkpoints = _context_rows(
        getattr(task_core, "checkpoints", []) or [],
        focus=lambda item: _text(getattr(item, "after_step_id", "")) == plan_step,
        include=lambda item: _text(getattr(item, "status", ""))
        in {"blocked", "planned", "ready", "waiting_approval"},
        serialize=lambda item: {
            "checkpoint_id": _text(getattr(item, "checkpoint_id", "")),
            "title": _text(getattr(item, "title", "")),
            "status": _text(getattr(item, "status", "")),
            "after_step_id": _text(getattr(item, "after_step_id", "")),
            "verifies": _text_list(getattr(item, "verifies", []), limit=6),
        },
        limit=5,
    )
    replan_signals = _context_rows(
        getattr(task_core, "replan_signals", []) or [],
        focus=lambda item: _text(getattr(item, "source_step_id", "")) == plan_step,
        include=lambda _item: True,
        serialize=lambda item: {
            "signal_id": _text(getattr(item, "signal_id", "")),
            "trigger": _text(getattr(item, "trigger", "")),
            "source_step_id": _text(getattr(item, "source_step_id", "")),
            "target": _text(getattr(item, "target", "")),
            "fallback_tools": _text_list(getattr(item, "fallback_tools", []), limit=6),
        },
        limit=5,
    )
    if workspace_items:
        context["workspace_items"] = workspace_items
    if todos:
        context["todos"] = todos
    if checkpoints:
        context["checkpoints"] = checkpoints
    if replan_signals:
        context["replan_signals"] = replan_signals
    verification_targets = _task_core_replan_verification_targets(
        decision,
        task_core,
        plan_step,
    )
    if verification_targets:
        context["task_verification_targets"] = verification_targets
    return {key: value for key, value in context.items() if value not in ("", [], {})}


def _context_rows(
    values: Any,
    *,
    focus: Any,
    include: Any,
    serialize: Any,
    limit: int,
) -> list[dict[str, Any]]:
    items = list(values or [])
    ordered = [*filter(focus, items), *filter(include, items)]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ordered:
        key = _context_item_key(item)
        if key in seen:
            continue
        row = _compact_mapping(serialize(item))
        if row:
            rows.append(row)
            seen.add(key)
        if len(rows) >= limit:
            break
    return rows


def _context_item_key(item: Any) -> str:
    for attribute in (
        "item_id",
        "todo_id",
        "checkpoint_id",
        "signal_id",
        "step_id",
        "source_step_id",
    ):
        value = _text(getattr(item, attribute, ""))
        if value:
            return f"{attribute}:{value}"
    return str(id(item))


def _task_core_replan_verification_targets(
    decision: PlannerDecisionSnapshot,
    task_core: Any,
    step_id: str,
) -> list[dict[str, Any]]:
    target_step_ids = _task_core_replan_verified_step_ids(decision, task_core, step_id)
    if not target_step_ids:
        return []
    workspace = getattr(task_core, "workspace", None)
    targets: list[dict[str, Any]] = []
    for target_step_id in target_step_ids:
        target: dict[str, Any] = {"step_id": target_step_id}
        todo = _task_core_replan_todo(task_core, target_step_id)
        if todo:
            target["todo"] = todo
        checkpoints = _task_core_replan_checkpoints(task_core, target_step_id)
        if checkpoints:
            target["checkpoints"] = checkpoints
        workspace_items = _task_core_replan_workspace_items(workspace, target_step_id)
        if workspace_items:
            target["workspace_items"] = workspace_items
        if len(target) > 1:
            targets.append(target)
    return targets


def _task_core_replan_verified_step_ids(
    decision: PlannerDecisionSnapshot,
    task_core: Any,
    step_id: str,
) -> list[str]:
    ids: list[str] = []
    for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
        if _text(getattr(checkpoint, "after_step_id", "")) != step_id:
            continue
        payload = getattr(checkpoint, "payload", {})
        if isinstance(payload, Mapping):
            ids.extend(_text_list(payload.get("verified_step_ids"), limit=8))
    if ids:
        return _ordered_text_list(ids)
    step = _matching_plan_step(decision, step_id, "", None)
    if step is None:
        return []
    stage = _task_core_replan_step_runtime_stage(task_core, step_id)
    if stage != "verify" and _text(getattr(step, "action", "")) not in {"read_ui", "verify"}:
        return []
    return _ordered_text_list(getattr(step, "depends_on", []) or [])


def _task_core_replan_step_runtime_stage(task_core: Any, step_id: str) -> str:
    for todo in list(getattr(task_core, "todos", []) or []):
        if _text(getattr(todo, "step_id", "")) != step_id:
            continue
        metadata = getattr(todo, "metadata", {})
        if isinstance(metadata, Mapping):
            stage = _text(metadata.get("runtime_stage"))
            if stage:
                return stage
    for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
        if _text(getattr(checkpoint, "after_step_id", "")) != step_id:
            continue
        payload = getattr(checkpoint, "payload", {})
        if isinstance(payload, Mapping):
            stage = _text(payload.get("runtime_stage"))
            if stage:
                return stage
    return ""


def _task_core_replan_todo(task_core: Any, step_id: str) -> dict[str, Any]:
    for todo in list(getattr(task_core, "todos", []) or []):
        if _text(getattr(todo, "step_id", "")) == step_id:
            return _model_payload(todo)
    return {}


def _task_core_replan_checkpoints(task_core: Any, step_id: str) -> list[dict[str, Any]]:
    return [
        payload
        for checkpoint in list(getattr(task_core, "checkpoints", []) or [])
        if _text(getattr(checkpoint, "after_step_id", "")) == step_id
        for payload in [_model_payload(checkpoint)]
        if payload
    ]


def _task_core_replan_workspace_items(workspace: Any, step_id: str) -> list[dict[str, Any]]:
    return [
        payload
        for item in list(getattr(workspace, "items", []) if workspace is not None else [])
        if _text(getattr(item, "source_step_id", "")) == step_id
        for payload in [_model_payload(item)]
        if payload
    ]


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _ordered_text_list(values: Any) -> list[str]:
    ordered: list[str] = []
    for value in _text_list(values, limit=100):
        if value and value not in ordered:
            ordered.append(value)
    return ordered


def _task_core_replan_prompt_lines(context: Mapping[str, Any]) -> list[str]:
    if not context:
        return []
    lines: list[str] = []
    workspace_title = _text(context.get("workspace_title"))
    workspace_id = _text(context.get("workspace_id"))
    if workspace_title or workspace_id:
        label = workspace_title or workspace_id
        suffix = f" ({workspace_id})" if workspace_title and workspace_id else ""
        lines.append(f"- workspace: {label}{suffix}")
    source_step_id = _text(context.get("source_step_id"))
    if source_step_id:
        lines.append(f"- source_step: {source_step_id}")
    planner_step_id = _text(context.get("planner_step_id"))
    if planner_step_id and planner_step_id != source_step_id:
        lines.append(f"- planner_step: {planner_step_id}")
    _append_context_rows(
        lines,
        "workspace_items",
        context.get("workspace_items"),
        _workspace_item_prompt_label,
    )
    _append_context_rows(lines, "todos", context.get("todos"), _todo_prompt_label)
    _append_context_rows(
        lines,
        "checkpoints",
        context.get("checkpoints"),
        _checkpoint_prompt_label,
    )
    _append_context_rows(
        lines,
        "replan_signals",
        context.get("replan_signals"),
        _replan_signal_prompt_label,
    )
    return lines


def _append_context_rows(
    lines: list[str],
    label: str,
    rows: Any,
    formatter: Any,
) -> None:
    if not isinstance(rows, list):
        return
    rendered = [formatter(row) for row in rows if isinstance(row, Mapping)]
    rendered = [row for row in rendered if row]
    if rendered:
        lines.append(f"- {label}: {'; '.join(rendered)}")


def _workspace_item_prompt_label(row: Mapping[str, Any]) -> str:
    return _joined_label(
        row.get("kind"),
        row.get("status"),
        row.get("path") or row.get("title"),
    )


def _todo_prompt_label(row: Mapping[str, Any]) -> str:
    return _joined_label(row.get("step_id"), row.get("status"), row.get("tool_name"))


def _checkpoint_prompt_label(row: Mapping[str, Any]) -> str:
    return _joined_label(row.get("after_step_id"), row.get("status"), row.get("title"))


def _replan_signal_prompt_label(row: Mapping[str, Any]) -> str:
    return _joined_label(row.get("source_step_id"), row.get("trigger"), row.get("target"))


def _joined_label(*parts: Any) -> str:
    return " · ".join(_text(part) for part in parts if _text(part))


def _compact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", [], {})}


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _default_recovery_tools(
    target_capability: str,
    step: ToolPlanStepSnapshot | None,
    failure: Mapping[str, Any],
) -> list[str]:
    if _foreground_focus_unverified_target_app(failure):
        return ["app.open", "desktop.active_window"]
    capability = _text(target_capability)
    step_action = _text(getattr(step, "action", "") if step is not None else "")
    step_input = getattr(step, "input_preview", {}) if step is not None else {}
    input_preview = step_input if isinstance(step_input, Mapping) else {}
    request_input = _failure_tool_input(failure)
    if _text(failure.get("trigger")) == "verification_failed" and (
        capability in {"desktop.app_discovery", "desktop.ui_operation"}
        or step_action in {"read_ui", "inspect_app", "click", "type_text"}
    ):
        return ["desktop.active_window", "desktop.ui_elements", "screen.capture"]
    if capability == "desktop.app_control" or step_action in {
        "open_app",
        "focus_app",
        "safe_shortcut",
        "open_path_with_selected_app",
    }:
        if _desktop_discovery_query(request_input, input_preview):
            return ["desktop.list_apps"]
    return []


def _fallback_recovery_actions(
    fallback_tools: list[str],
    step: ToolPlanStepSnapshot | None,
    failure: Mapping[str, Any],
    *,
    source_step_id: str,
    target_capability_id: str,
    task_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    step_input = getattr(step, "input_preview", {}) if step is not None else {}
    input_preview = step_input if isinstance(step_input, Mapping) else {}
    request_input = _failure_tool_input(failure)
    for tool_name in fallback_tools:
        action = _fallback_recovery_action(
            _text(tool_name),
            request_input,
            input_preview,
            failure,
            source_step_id=source_step_id,
            target_capability_id=target_capability_id,
            task_context=task_context,
        )
        if not action:
            continue
        action_input = action.get("input") if isinstance(action.get("input"), Mapping) else {}
        signature = (_text(action.get("tool")), repr(sorted(dict(action_input).items())))
        if signature in seen:
            continue
        seen.add(signature)
        actions.append(action)
    return actions


def _desktop_loop_retry_tool(failure: Mapping[str, Any]) -> str:
    desktop_loop = _mapping(failure.get("desktop_loop"))
    if not desktop_loop or desktop_loop.get("can_auto_retry") is not True:
        return ""
    tool_name = _text(desktop_loop.get("retry_tool"))
    if not tool_name or not _fallback_recovery_tool_metadata(tool_name):
        return ""
    return tool_name


def _desktop_loop_recovery_actions(
    failure: Mapping[str, Any],
    *,
    source_step_id: str,
    target_capability_id: str,
    task_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    desktop_loop = _mapping(failure.get("desktop_loop"))
    tool_name = _desktop_loop_retry_tool(failure)
    if not desktop_loop or not tool_name:
        return []
    metadata = _fallback_recovery_tool_metadata(tool_name)
    action = {
        "label": metadata["label"],
        "tool": tool_name,
        "input": _mapping(desktop_loop.get("retry_input")),
        "planning_reason": "planner_desktop_loop_auto_retry",
        "permission_target": metadata["permission_target"],
        "risk_level": metadata["risk_level"],
        "approval_required": metadata["approval_required"],
        "source_step_id": _text(source_step_id),
        "target_capability_id": _text(target_capability_id),
        "action_target": _mapping(failure.get("action_target")),
        "observation_evidence": _mapping(failure.get("observation_evidence")),
        "observation_retry": (
            _mapping(failure.get("observation_retry"))
            or _desktop_loop_observation_retry(desktop_loop)
        ),
        "metadata": _desktop_loop_recovery_metadata(failure, desktop_loop),
    }
    verification_targets = _task_context_verification_targets(task_context)
    if verification_targets:
        action["verification_targets"] = verification_targets
        action["task_verification_targets"] = verification_targets
    return [_compact_mapping(action)]


def _dedupe_recovery_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        action_input = action.get("input") if isinstance(action.get("input"), Mapping) else {}
        signature = (_text(action.get("tool")), repr(sorted(dict(action_input).items())))
        if not signature[0] or signature in seen:
            continue
        seen.add(signature)
        result.append(action)
    return result


def _fallback_recovery_action(
    tool_name: str,
    request_input: Mapping[str, Any],
    input_preview: Mapping[str, Any],
    failure: Mapping[str, Any],
    *,
    source_step_id: str,
    target_capability_id: str,
    task_context: Mapping[str, Any],
) -> dict[str, Any]:
    if not tool_name:
        return {}
    tool_input = _fallback_recovery_tool_input(tool_name, request_input, input_preview, failure)
    if tool_input is None:
        return {}
    metadata = _fallback_recovery_tool_metadata(tool_name)
    if not metadata:
        return {}
    action = {
        "label": metadata["label"],
        "tool": tool_name,
        "input": tool_input,
        "planning_reason": "planner_replan_runtime_recovery_action",
        "permission_target": metadata["permission_target"],
        "risk_level": metadata["risk_level"],
        "approval_required": metadata["approval_required"],
        "source_step_id": _text(source_step_id),
        "target_capability_id": _text(target_capability_id),
    }
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = _mapping(failure.get(key))
        if value:
            action[key] = value
    focus_target_app = _foreground_focus_unverified_target_app(failure)
    if focus_target_app and tool_name in {
        "app.open",
        "app.focus",
        "desktop.open_app",
        "desktop.focus_app",
    }:
        action.update(
            _foreground_focus_unverified_recovery_context(
                tool_name=tool_name,
                tool_input=tool_input,
                source_step_id=source_step_id,
                source_tool_name=_text(
                    failure.get("source_tool_name") or failure.get("tool_name")
                ),
                target_app_name=focus_target_app,
                failure=failure,
            )
        )
    verification_targets = _task_context_verification_targets(task_context)
    if verification_targets:
        action["verification_targets"] = verification_targets
        action["task_verification_targets"] = verification_targets
    return _compact_mapping(action)


def _fallback_recovery_tool_input(
    tool_name: str,
    request_input: Mapping[str, Any],
    input_preview: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> dict[str, Any] | None:
    if tool_name == "desktop.list_apps":
        query = _desktop_discovery_query(request_input, input_preview)
        if not query:
            return None
        limit = _positive_int(
            request_input.get("limit")
            or input_preview.get("limit")
            or 20
        )
        return {"query": query, "limit": limit or 20}
    if tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
        payload = {
            key: request_input.get(key) or input_preview.get(key)
            for key in ("app_name", "role_filter", "limit")
            if request_input.get(key) or input_preview.get(key)
        }
        if "limit" not in payload:
            payload["limit"] = 80
        return dict(payload)
    if tool_name in {"screen.capture", "browser.screenshot"}:
        reason = _text(
            request_input.get("reason")
            or input_preview.get("reason")
            or failure.get("detail")
            or failure.get("error")
        )
        return {"reason": reason} if reason else {}
    if tool_name in {"desktop.active_window", "browser.current_page"}:
        return {}
    if tool_name == "desktop.running_apps":
        return {}
    if tool_name in {"workspace.read", "file.read", "fs.read_file"}:
        path = _first_text(
            request_input.get("path"),
            input_preview.get("path"),
            request_input.get("source"),
            input_preview.get("source"),
        )
        return {"path": path} if path else None
    if tool_name in {"app.open", "app.focus", "app.status", "desktop.list_windows"}:
        app_name = _first_text(
            request_input.get("app_name"),
            input_preview.get("app_name"),
            _foreground_focus_unverified_target_app(failure),
        )
        if not app_name or app_name == "<selected app from desktop.list_apps>":
            return None
        return {"app_name": app_name}
    if tool_name in {"terminal.run", "python.run"}:
        command = _first_text(
            request_input.get("cmd"),
            request_input.get("command"),
            request_input.get("code"),
            input_preview.get("cmd"),
            input_preview.get("command"),
            input_preview.get("code"),
        )
        if not command:
            return None
        return {"cmd": command} if tool_name == "terminal.run" else {"code": command}
    return None


def _fallback_recovery_tool_metadata(tool_name: str) -> dict[str, Any]:
    return {
        "desktop.list_apps": {
            "label": "重新发现应用",
            "permission_target": "app_discovery",
            "risk_level": "low",
            "approval_required": False,
        },
        "desktop.running_apps": {
            "label": "重新检查运行中应用",
            "permission_target": "app_discovery",
            "risk_level": "low",
            "approval_required": False,
        },
        "desktop.ui_elements": {
            "label": "重新读取界面",
            "permission_target": "ui_inspection",
            "risk_level": "low",
            "approval_required": False,
        },
        "desktop.read_ui": {
            "label": "重新读取界面",
            "permission_target": "ui_inspection",
            "risk_level": "low",
            "approval_required": False,
        },
        "screen.capture": {
            "label": "重新截图验证",
            "permission_target": "screen_recording",
            "risk_level": "low",
            "approval_required": False,
        },
        "desktop.active_window": {
            "label": "重新检查前台窗口",
            "permission_target": "window_inspection",
            "risk_level": "low",
            "approval_required": False,
        },
        "browser.current_page": {
            "label": "重新读取当前网页",
            "permission_target": "browser_read",
            "risk_level": "low",
            "approval_required": False,
        },
        "browser.screenshot": {
            "label": "重新截取网页",
            "permission_target": "browser_capture",
            "risk_level": "low",
            "approval_required": False,
        },
        "workspace.read": {
            "label": "重新读取文件",
            "permission_target": "workspace_read",
            "risk_level": "low",
            "approval_required": False,
        },
        "file.read": {
            "label": "重新读取文件",
            "permission_target": "workspace_read",
            "risk_level": "low",
            "approval_required": False,
        },
        "fs.read_file": {
            "label": "重新读取文件",
            "permission_target": "workspace_read",
            "risk_level": "low",
            "approval_required": False,
        },
        "app.open": {
            "label": "重新打开应用",
            "permission_target": "app_control",
            "risk_level": "low",
            "approval_required": False,
        },
        "app.focus": {
            "label": "重新聚焦应用",
            "permission_target": "app_control",
            "risk_level": "low",
            "approval_required": False,
        },
        "app.status": {
            "label": "重新检查应用状态",
            "permission_target": "app_inspection",
            "risk_level": "low",
            "approval_required": False,
        },
        "desktop.list_windows": {
            "label": "重新检查窗口",
            "permission_target": "window_inspection",
            "risk_level": "low",
            "approval_required": False,
        },
        "terminal.run": {
            "label": "运行终端恢复命令",
            "permission_target": "terminal_execution",
            "risk_level": "medium",
            "approval_required": True,
        },
        "python.run": {
            "label": "运行 Python 恢复代码",
            "permission_target": "code_execution",
            "risk_level": "medium",
            "approval_required": True,
        },
    }.get(tool_name, {})


def _desktop_loop_observation_retry(desktop_loop: Mapping[str, Any]) -> dict[str, Any]:
    retry = {
        "tool": _text(desktop_loop.get("retry_tool")),
        "input": _mapping(desktop_loop.get("retry_input")),
        "reason": _text(desktop_loop.get("retry_reason")),
    }
    return _mapping(retry)


def _desktop_loop_recovery_metadata(
    failure: Mapping[str, Any],
    desktop_loop: Mapping[str, Any],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "desktop_execution_loop",
        "desktop_loop": dict(desktop_loop),
        "desktop_loop_retry_reason": _text(desktop_loop.get("retry_reason")),
        "runtime_stage": _text(desktop_loop.get("stage") or failure.get("runtime_stage")),
        "runtime_role": _text(desktop_loop.get("role") or failure.get("runtime_role")),
        "source_tool": _text(desktop_loop.get("source_tool")),
    }
    for key in ("replan_triggers", "replan_signal_ids"):
        values = _text_list(failure.get(key), limit=8)
        if values:
            metadata[key] = values
    verification_ids = _text_list(
        desktop_loop.get("verification_target_step_ids"),
        limit=8,
    )
    if verification_ids:
        metadata["verification_target_step_ids"] = verification_ids
    return _compact_mapping(metadata)


def _foreground_focus_unverified_recovery_context(
    *,
    tool_name: str,
    tool_input: Mapping[str, Any],
    source_step_id: str,
    source_tool_name: str,
    target_app_name: str,
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    verification_target = {
        "app_name": target_app_name,
        **({"source_tool": source_tool_name} if source_tool_name else {}),
    }
    verify_request = {
        "tool": "desktop.active_window",
        "input": {},
        "source": "runtime_replan_recovery",
        "planning_reason": "planner_replan_verify_foreground_focus",
        "replan_triggers": ["verification_failed"],
        "verification_target": verification_target,
    }
    if source_step_id:
        verify_request["step_id"] = source_step_id
        verify_request["planner_step_id"] = source_step_id
    return {
        "selected": True,
        "action_target": _mapping(failure.get("action_target")),
        "observation_evidence": (
            _mapping(failure.get("observation_evidence"))
            or _foreground_focus_observation_evidence(failure)
        ),
        "observation_retry": _compact_mapping(
            {
                "tool": tool_name,
                "input": dict(tool_input),
                "reason": "foreground_focus_unverified",
                "source_tool": source_tool_name,
            }
        ),
        "deferred_continuation": [verify_request],
        "metadata": {
            "runtime_replan_auto_start_eligible": True,
            "runtime_replan_auto_start_reason": "safe_low_risk_runtime_replan_recovery",
            "runtime_replan_auto_start_blockers": [],
            "replan_recovery_reason": "foreground_focus_unverified",
        },
    }


def _foreground_focus_unverified_target_app(failure: Mapping[str, Any]) -> str:
    if not _failure_has_condition(failure, "foreground_focus_unverified"):
        return ""
    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    verification_target = _mapping(failure.get("verification_target"))
    action_target = _mapping(failure.get("action_target"))
    request_input = _failure_tool_input(failure)
    return _first_text(
        verification_target.get("app_name"),
        verification_target.get("target_app_name"),
        verification_target.get("expected_app_name"),
        action_target.get("app_name"),
        action_target.get("target_app_name"),
        action_target.get("expected_app_name"),
        request_input.get("app_name"),
        request_input.get("target_app_name"),
        request_input.get("expected_app_name"),
        result.get("app_name"),
        result.get("target_app_name"),
        result.get("expected_app_name"),
        data.get("app_name"),
        data.get("target_app_name"),
        data.get("expected_app_name"),
    )


def _foreground_focus_observation_evidence(failure: Mapping[str, Any]) -> dict[str, Any]:
    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    return _compact_mapping(
        {
            "expected_app_name": _first_text(
                result.get("expected_app_name"),
                data.get("expected_app_name"),
                _foreground_focus_unverified_target_app(failure),
            ),
            "active_app_name": _first_text(
                result.get("active_app_name"),
                data.get("active_app_name"),
            ),
            "focus_verified": data.get("focus_verified"),
            "blocking_condition": _first_text(
                result.get("blocking_condition"),
                data.get("blocking_condition"),
            ),
        }
    )


def _failure_has_condition(failure: Mapping[str, Any], condition: str) -> bool:
    clean_condition = _text(condition)
    if not clean_condition:
        return False
    result = failure.get("result") if isinstance(failure.get("result"), Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    values = [
        failure.get("error"),
        failure.get("detail"),
        failure.get("status"),
        failure.get("blocking_condition"),
        result.get("error"),
        result.get("hint"),
        result.get("status"),
        result.get("blocking_condition"),
        data.get("error"),
        data.get("hint"),
        data.get("status"),
        data.get("blocking_condition"),
    ]
    values.extend(_text_list(failure.get("blocking_conditions"), limit=8))
    values.extend(_text_list(result.get("blocking_conditions"), limit=8))
    values.extend(_text_list(data.get("blocking_conditions"), limit=8))
    for value in values:
        clean_value = _text(value)
        if clean_value == clean_condition or clean_condition in clean_value:
            return True
    return False


def _failure_tool_input(failure: Mapping[str, Any]) -> dict[str, Any]:
    value = failure.get("tool_input")
    return dict(value) if isinstance(value, Mapping) else {}


def _desktop_discovery_query(
    request_input: Mapping[str, Any],
    input_preview: Mapping[str, Any],
) -> str:
    return _first_text(
        request_input.get("query"),
        input_preview.get("query"),
        request_input.get("app_name"),
        input_preview.get("app_name"),
        request_input.get("target_app_name"),
        input_preview.get("target_app_name"),
    )


def _task_context_verification_targets(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = context.get("task_verification_targets")
    if isinstance(targets, list):
        return [dict(item) for item in targets if isinstance(item, Mapping)]
    step_id = _text(context.get("source_step_id") or context.get("planner_step_id"))
    if not step_id:
        return []
    target: dict[str, Any] = {"step_id": step_id}
    todos = context.get("todos")
    todo = _context_row_for_step(todos, "step_id", step_id)
    if todo:
        for key, value in (
            ("todo_id", todo.get("todo_id")),
            ("todo_title", todo.get("title")),
        ):
            if value:
                target[key] = value
    checkpoints = context.get("checkpoints")
    if isinstance(checkpoints, list):
        checkpoint_ids = [
            _text(checkpoint.get("checkpoint_id"))
            for checkpoint in checkpoints
            if isinstance(checkpoint, Mapping)
            and _text(checkpoint.get("after_step_id")) == step_id
            and _text(checkpoint.get("checkpoint_id"))
        ]
        if checkpoint_ids:
            target["checkpoint_ids"] = checkpoint_ids
    return [target]


def _context_row_for_step(value: Any, key: str, step_id: str) -> Mapping[str, Any]:
    if not isinstance(value, list):
        return {}
    for item in value:
        if isinstance(item, Mapping) and _text(item.get(key)) == step_id:
            return item
    return {}


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _first_text(*values: Any) -> str:
    for value in values:
        clean = _text(value)
        if clean:
            return clean
    return ""


def _signal_metadata(signal: ReplanSignalSnapshot | None) -> dict[str, Any]:
    if signal is None:
        return {}
    return {
        "signal_id": signal.signal_id,
        "signal_trigger": signal.trigger,
    }


def _optional_text(value: Any) -> str | None:
    clean = _text(value)
    return clean or None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        clean = _text(item)
        if clean:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\n".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
