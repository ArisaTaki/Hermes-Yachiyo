"""Runtime execution envelopes derived from planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    PlannerDecisionSnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RuntimeExecutionRequestSnapshot,
    ToolPlanStepSnapshot,
)
from .planner_execution import planner_tool_requests_for_decision


def runtime_execution_envelope_from_decision(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
    full_plan: bool = False,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    if decision is None:
        return None
    clean_allowed = _allowed_tools(decision, allowed_tools)
    request_payloads = (
        _full_plan_tool_requests_from_decision(decision, clean_allowed)
        if full_plan and _supports_full_plan_projection(decision)
        else planner_tool_requests_for_decision(
            decision,
            clean_allowed,
            direct=direct,
            execution_normalized=True,
        )
    )
    steps = _steps_by_id(decision)
    requests = [
        _execution_request_snapshot(
            request,
            index=index,
            decision=decision,
            steps=steps,
        )
        for index, request in enumerate(request_payloads, start=1)
    ]
    tool_plan = decision.plan.tool_plan
    runtime_metadata = _execution_envelope_runtime_metadata(requests, decision)
    return RuntimeExecutionEnvelopeSnapshot(
        envelope_id=f"execution-envelope-{decision.plan.plan_id}",
        decision_id=decision.decision_id,
        plan_id=decision.plan.plan_id,
        intent_kind=str(decision.selected_intent.kind or ""),
        requests=requests,
        task_core=decision.plan.task_core,
        approvals_required=list(tool_plan.approvals_required),
        artifacts_expected=list(tool_plan.artifacts_expected),
        open_questions=list(tool_plan.open_questions),
        route_to_studio=bool(decision.plan.route_to_studio),
        runtime_doctrine=runtime_metadata["runtime_doctrine"],
        runtime_stage_counts=runtime_metadata["runtime_stage_counts"],
        replan_signal_count=runtime_metadata["replan_signal_count"],
    )


def runtime_execution_envelope_payload(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
    full_plan: bool = False,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        direct=direct,
        full_plan=full_plan,
    )
    if envelope is None:
        return {}
    return envelope.model_dump(mode="json")


def _supports_full_plan_projection(decision: PlannerDecisionSnapshot) -> bool:
    return str(decision.selected_intent.kind or "").strip() in {
        "data_analysis",
        "report_generation",
    }


def _full_plan_tool_requests_from_decision(
    decision: PlannerDecisionSnapshot,
    allowed_tools: set[str],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for step in list(decision.plan.tool_plan.steps or []):
        tool_name = _text(getattr(step, "tool_name", None))
        if not tool_name or tool_name not in allowed_tools:
            continue
        status = _text(getattr(step, "status", None)) or "planned"
        if status in {"unavailable", "skipped"}:
            continue
        input_preview = getattr(step, "input_preview", None)
        request_input = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        step_id = _text(getattr(step, "step_id", None))
        capability_id = _text(getattr(step, "capability_id", None))
        request: dict[str, Any] = {
            "protocol": "json_fallback",
            "tool": tool_name,
            "input": request_input,
            "source": "runtime_planner",
            "planning_reason": f"planner_full_plan_{decision.selected_intent.kind}",
            "approval_required": bool(getattr(step, "approval_required", False)),
            "status": status,
        }
        if step_id:
            request["step_id"] = step_id
            request["planner_step_id"] = step_id
        if capability_id:
            request["capability_id"] = capability_id
        requests.append(request)
    return requests


def runtime_execution_requests_from_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    allowed_tools: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(metadata, Mapping):
        return []
    return runtime_execution_requests_from_envelope_payload(
        metadata.get("yachiyo_execution_envelope"),
        allowed_tools=allowed_tools,
    )


def runtime_execution_requests_from_envelope_payload(
    envelope_payload: Any,
    *,
    allowed_tools: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(envelope_payload, RuntimeExecutionEnvelopeSnapshot):
        envelope = envelope_payload.model_dump(mode="json")
    elif isinstance(envelope_payload, Mapping):
        envelope = dict(envelope_payload)
    else:
        return []

    allowed = {
        str(tool or "").strip()
        for tool in (allowed_tools or [])
        if str(tool or "").strip()
    }
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return []
    projected: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        projected_request = _tool_request_from_execution_request(request, envelope=envelope)
        tool_name = str(projected_request.get("tool") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            continue
        projected.append(projected_request)
    return projected


def _execution_request_snapshot(
    request: Mapping[str, Any],
    *,
    index: int,
    decision: PlannerDecisionSnapshot,
    steps: Mapping[str, ToolPlanStepSnapshot],
) -> RuntimeExecutionRequestSnapshot:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    step_id = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
    step = steps.get(step_id)
    capability_id = str(
        request.get("capability_id")
        or (step.capability_id if step is not None else "")
        or ""
    ).strip()
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    runtime_metadata = _execution_request_runtime_metadata(request, step, decision)
    replan_metadata = _execution_request_replan_metadata(step_id, step, decision)
    return RuntimeExecutionRequestSnapshot(
        request_id=str(
            request.get("request_id")
            or request.get("tool_call_id")
            or f"{decision.plan.plan_id}:request:{index}:{tool_name or 'tool'}"
        ),
        step_id=step_id or None,
        capability_id=capability_id or None,
        tool_name=tool_name or "tool",
        protocol=str(request.get("protocol") or "json_fallback"),
        input=dict(request_input),
        planning_reason=str(request.get("planning_reason") or ""),
        approval_required=bool(
            request.get("approval_required")
            or (step.approval_required if step is not None else False)
        ),
        continue_to_model=bool(request.get("continue_to_model")),
        depends_on=list(step.depends_on) if step is not None else [],
        fallback_tools=list(step.fallback_tools) if step is not None else [],
        status=str(request.get("status") or (step.status if step is not None else "planned")),
        runtime_doctrine=runtime_metadata["runtime_doctrine"],
        runtime_stage=runtime_metadata["runtime_stage"],
        runtime_role=runtime_metadata["runtime_role"],
        requires_observation=runtime_metadata["requires_observation"],
        requires_post_action_verification=runtime_metadata[
            "requires_post_action_verification"
        ],
        replan_triggers=replan_metadata["replan_triggers"],
        replan_signal_ids=replan_metadata["replan_signal_ids"],
        source=str(request.get("source") or "runtime_planner"),
    )


def _tool_request_from_execution_request(
    request: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    payload: dict[str, Any] = {
        "protocol": str(request.get("protocol") or "json_fallback"),
        "tool": str(request.get("tool_name") or request.get("tool") or "").strip(),
        "input": dict(request_input),
        "source": str(request.get("source") or "runtime_planner"),
        "planning_reason": str(request.get("planning_reason") or ""),
    }
    for key in (
        "request_id",
        "step_id",
        "capability_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "intent_kind",
        "approval_required",
        "continue_to_model",
        "status",
        "runtime_doctrine",
        "runtime_stage",
        "runtime_role",
        "requires_observation",
        "requires_post_action_verification",
        "replan_triggers",
        "replan_signal_ids",
    ):
        value = request.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    if isinstance(envelope, Mapping):
        _apply_envelope_task_context(payload, envelope)
    return payload


def _apply_envelope_task_context(
    payload: dict[str, Any],
    envelope: Mapping[str, Any],
) -> None:
    for key in ("decision_id", "plan_id", "intent_kind"):
        value = envelope.get(key)
        if key not in payload and value not in (None, "", [], {}):
            payload[key] = value

    task_core = _task_core_payload(envelope)
    if not task_core:
        return
    if "core_id" not in payload:
        core_id = str(task_core.get("core_id") or "").strip()
        if core_id:
            payload["core_id"] = core_id
    workspace_id = _task_workspace_id(task_core)
    if workspace_id and "workspace_id" not in payload:
        payload["workspace_id"] = workspace_id

    step_id = str(payload.get("step_id") or payload.get("planner_step_id") or "").strip()
    if not step_id:
        return

    todo = _task_todo_for_step(task_core, step_id)
    if todo and "task_todo" not in payload:
        payload["task_todo"] = todo
    checkpoints = _task_checkpoints_for_step(task_core, step_id)
    if checkpoints and "task_checkpoints" not in payload:
        payload["task_checkpoints"] = checkpoints
    workspace_items = _task_workspace_items_for_step(task_core, step_id)
    if workspace_items and "task_workspace_items" not in payload:
        payload["task_workspace_items"] = workspace_items


def _task_core_payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    task_core = envelope.get("task_core")
    return task_core if isinstance(task_core, Mapping) else {}


def _task_workspace_id(task_core: Mapping[str, Any]) -> str:
    workspace = task_core.get("workspace")
    if not isinstance(workspace, Mapping):
        return ""
    return str(workspace.get("workspace_id") or "").strip()


def _task_todo_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> dict[str, Any]:
    for todo in _mapping_list(task_core.get("todos")):
        if str(todo.get("step_id") or "").strip() == step_id:
            return dict(todo)
    return {}


def _task_checkpoints_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(checkpoint)
        for checkpoint in _mapping_list(task_core.get("checkpoints"))
        if str(checkpoint.get("after_step_id") or "").strip() == step_id
    ]


def _task_workspace_items_for_step(
    task_core: Mapping[str, Any],
    step_id: str,
) -> list[dict[str, Any]]:
    workspace = task_core.get("workspace")
    if not isinstance(workspace, Mapping):
        return []
    return [
        dict(item)
        for item in _mapping_list(workspace.get("items"))
        if str(item.get("source_step_id") or "").strip() == step_id
    ]


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _execution_envelope_runtime_metadata(
    requests: list[RuntimeExecutionRequestSnapshot],
    decision: PlannerDecisionSnapshot,
) -> dict[str, Any]:
    stage_counts: dict[str, int] = {}
    doctrine = ""
    for request in requests:
        stage = str(request.runtime_stage or "").strip()
        if not stage:
            continue
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        doctrine = doctrine or str(request.runtime_doctrine or "").strip()
    if not doctrine and stage_counts:
        doctrine = "discover_operate_verify"
    return {
        "runtime_doctrine": doctrine,
        "runtime_stage_counts": stage_counts,
        "replan_signal_count": _task_replan_signal_count(decision),
    }


def _execution_request_runtime_metadata(
    request: Mapping[str, Any],
    step: ToolPlanStepSnapshot | None,
    decision: PlannerDecisionSnapshot,
) -> dict[str, Any]:
    step_id = _text(
        request.get("step_id")
        or request.get("planner_step_id")
        or (step.step_id if step is not None else "")
    )
    metadata = {
        **_task_core_step_runtime_metadata(decision, step_id),
        **_mapping_subset(
            request,
            (
                "runtime_doctrine",
                "runtime_stage",
                "runtime_role",
                "requires_observation",
                "requires_post_action_verification",
            ),
        ),
    }
    runtime_stage = _text(metadata.get("runtime_stage"))
    return {
        "runtime_doctrine": _text(metadata.get("runtime_doctrine")),
        "runtime_stage": runtime_stage,
        "runtime_role": _text(metadata.get("runtime_role")),
        "requires_observation": bool(metadata.get("requires_observation")),
        "requires_post_action_verification": bool(
            metadata.get("requires_post_action_verification")
        ),
    }


def _execution_request_replan_metadata(
    step_id: str,
    step: ToolPlanStepSnapshot | None,
    decision: PlannerDecisionSnapshot,
) -> dict[str, list[str]]:
    clean_step_id = _text(step_id or (step.step_id if step is not None else ""))
    signal_ids: list[str] = []
    triggers: list[str] = []
    for signal in _task_replan_signals(decision):
        if _text(signal.source_step_id) != clean_step_id:
            continue
        signal_id = _text(signal.signal_id)
        trigger = _text(signal.trigger)
        if signal_id and signal_id not in signal_ids:
            signal_ids.append(signal_id)
        if trigger and trigger not in triggers:
            triggers.append(trigger)
    return {
        "replan_triggers": triggers,
        "replan_signal_ids": signal_ids,
    }


def _task_core_step_runtime_metadata(
    decision: PlannerDecisionSnapshot,
    step_id: str,
) -> dict[str, Any]:
    if not step_id:
        return {}
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return {}
    for todo in list(getattr(task_core, "todos", []) or []):
        if _text(getattr(todo, "step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(todo, "metadata", {}))
            if metadata:
                return metadata
    for checkpoint in list(getattr(task_core, "checkpoints", []) or []):
        if _text(getattr(checkpoint, "after_step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(checkpoint, "payload", {}))
            if metadata:
                return metadata
    workspace = getattr(task_core, "workspace", None)
    for item in list(getattr(workspace, "items", []) or []):
        if _text(getattr(item, "source_step_id", None)) == step_id:
            metadata = _runtime_metadata_subset(getattr(item, "metadata", {}))
            if metadata:
                return metadata
    return {}


def _runtime_metadata_subset(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return _mapping_subset(
        value,
        (
            "runtime_doctrine",
            "runtime_stage",
            "runtime_role",
            "requires_observation",
            "requires_post_action_verification",
        ),
    )


def _mapping_subset(value: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


def _task_replan_signals(decision: PlannerDecisionSnapshot) -> list[Any]:
    task_core = getattr(decision.plan, "task_core", None)
    if task_core is None:
        return []
    return list(getattr(task_core, "replan_signals", []) or [])


def _task_replan_signal_count(decision: PlannerDecisionSnapshot) -> int:
    return len(_task_replan_signals(decision))


def _allowed_tools(
    decision: PlannerDecisionSnapshot,
    allowed_tools: Iterable[str] | None,
) -> list[str]:
    explicit = [
        str(tool or "").strip()
        for tool in (allowed_tools or [])
        if str(tool or "").strip()
    ]
    if explicit:
        return explicit
    tools: list[str] = []
    for step in decision.plan.tool_plan.steps:
        tool_name = str(step.tool_name or "").strip()
        if tool_name:
            tools.append(tool_name)
        tools.extend(
            str(tool or "").strip()
            for tool in step.fallback_tools
            if str(tool or "").strip()
        )
    return _dedupe(tools)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _steps_by_id(
    decision: PlannerDecisionSnapshot,
) -> dict[str, ToolPlanStepSnapshot]:
    return {
        str(step.step_id or "").strip(): step
        for step in decision.plan.tool_plan.steps
        if str(step.step_id or "").strip()
    }


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
