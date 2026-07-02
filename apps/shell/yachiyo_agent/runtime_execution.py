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
) -> RuntimeExecutionEnvelopeSnapshot | None:
    if decision is None:
        return None
    clean_allowed = _allowed_tools(decision, allowed_tools)
    request_payloads = planner_tool_requests_for_decision(
        decision,
        clean_allowed,
        direct=direct,
        execution_normalized=True,
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
    )


def runtime_execution_envelope_payload(
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None = None,
    direct: bool = False,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        direct=direct,
    )
    if envelope is None:
        return {}
    return envelope.model_dump(mode="json")


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
        projected_request = _tool_request_from_execution_request(request)
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
        source=str(request.get("source") or "runtime_planner"),
    )


def _tool_request_from_execution_request(request: Mapping[str, Any]) -> dict[str, Any]:
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
    ):
        value = request.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


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
