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
    request_metadata = {
        **dict(metadata or {}),
        **_signal_metadata(signal),
        "original_intent_kind": _text(decision.selected_intent.kind),
    }
    if task_context:
        request_metadata["task_core_context"] = task_context
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
        include=lambda item: _text(getattr(item, "kind", "")) in {"input", "artifact"},
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
