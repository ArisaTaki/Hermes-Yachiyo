"""Projection helpers for runtime planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import PlannerDecisionSnapshot
from .runtime_planner import RuntimePlanner


def runtime_planner_decision(
    prompt: str,
    *,
    allowed_tools: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PlannerDecisionSnapshot | None:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        return None
    return RuntimePlanner().decision(
        clean_prompt,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )


def runtime_planner_metadata(
    decision: PlannerDecisionSnapshot | None,
) -> dict[str, Any]:
    if decision is None:
        return {}
    tool_plan = decision.plan.tool_plan
    tool_names = [
        str(step.tool_name or "").strip()
        for step in tool_plan.steps
        if str(step.tool_name or "").strip()
    ]
    return {
        "yachiyo_runtime_planner": True,
        "yachiyo_plan_source": decision.source,
        "yachiyo_decision_id": decision.decision_id,
        "yachiyo_plan_id": decision.plan.plan_id,
        "yachiyo_intent_kind": decision.selected_intent.kind,
        "yachiyo_intent_confidence": round(float(decision.selected_intent.confidence or 0), 3),
        "yachiyo_candidate_intents": _candidate_intent_summaries(decision),
        "yachiyo_route_to_studio": decision.plan.route_to_studio,
        "yachiyo_plan_tools": tool_names,
        "yachiyo_plan_capabilities": _plan_capability_ids(decision),
        "yachiyo_plan_approvals_required": list(tool_plan.approvals_required),
        "yachiyo_plan_artifacts_expected": list(tool_plan.artifacts_expected),
        "yachiyo_plan_open_questions": list(tool_plan.open_questions),
        "yachiyo_required_capabilities": _required_capability_ids(decision),
        "yachiyo_missing_capabilities": list(tool_plan.missing_capabilities),
    }


def planner_enriched_chat_request(
    request: Mapping[str, Any],
    *,
    allowed_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    payload = dict(request)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    decision = runtime_planner_decision(
        str(payload.get("prompt") or payload.get("goal") or ""),
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    if decision is None:
        return payload
    payload["metadata"] = {
        **dict(metadata),
        **runtime_planner_metadata(decision),
    }
    return payload


def _candidate_intent_summaries(decision: PlannerDecisionSnapshot) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for intent in decision.candidate_intents:
        kind = str(intent.kind or "").strip()
        if not kind:
            continue
        summaries.append(
            {
                "kind": kind,
                "title": str(intent.title or "").strip(),
                "confidence": round(float(intent.confidence or 0), 3),
            }
        )
    return summaries


def planner_timeline_events(
    decision: PlannerDecisionSnapshot | None,
) -> list[dict[str, Any]]:
    if decision is None:
        return []
    events: list[dict[str, Any]] = []
    for event_type, payload in planner_run_event_payloads(decision):
        events.append(
            {
                "event": event_type,
                "detail": _planner_timeline_detail(event_type, payload),
                "status": "planned",
                "source": decision.source,
                "decision_id": decision.decision_id,
                "plan_id": decision.plan.plan_id,
                "payload": payload,
            }
        )
    return events


def planner_selection_payload(
    *,
    decision: Any | None,
    planner_requests: Iterable[Mapping[str, Any]],
    legacy_requests: Iterable[Mapping[str, Any]],
    selected_requests: Iterable[Mapping[str, Any]],
    selected_source: str,
    selected_reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    planner_request_list = _request_list(planner_requests)
    legacy_request_list = _request_list(legacy_requests)
    selected_request_list = _request_list(selected_requests)
    selected_source_value = str(selected_source or "").strip()
    selected_reason_value = str(selected_reason or "").strip()
    selection_role = _selection_role(selected_source_value)
    plan_tools = _plan_tool_names(decision)
    plan_steps = _plan_steps(decision)
    plan_capabilities = _plan_capability_ids(decision)
    missing_capabilities = _missing_capability_ids(decision)
    approvals_required = _tool_plan_values(decision, "approvals_required")
    artifacts_expected = _tool_plan_values(decision, "artifacts_expected")
    open_questions = _tool_plan_values(decision, "open_questions")
    payload: dict[str, Any] = {
        "source": "runtime_planner",
        "selection_source": selected_source_value,
        "selection_role": selection_role,
        "selection_reason": selected_reason_value,
        "legacy_fallback": selection_role == "legacy_desktop_intent_fallback",
        "plan_tools": plan_tools,
        "plan_capabilities": plan_capabilities,
        "required_capabilities": _required_capability_ids(decision),
        "missing_capabilities": missing_capabilities,
        "approvals_required": approvals_required,
        "artifacts_expected": artifacts_expected,
        "open_questions": open_questions,
        "planner_tools": _tool_names(planner_request_list),
        "legacy_tools": _tool_names(legacy_request_list),
        "selected_tools": _tool_names(selected_request_list),
        "plan_step_count": len(plan_steps),
        "plan_capability_count": len(plan_capabilities),
        "missing_capability_count": len(missing_capabilities),
        "approval_count": len(approvals_required),
        "artifact_count": len(artifacts_expected),
        "open_question_count": len(open_questions),
        "planner_request_count": len(planner_request_list),
        "legacy_request_count": len(legacy_request_list),
        "selected_request_count": len(selected_request_list),
    }
    decision_id = str(getattr(decision, "decision_id", "") or "").strip()
    if decision_id:
        payload["decision_id"] = decision_id
    plan = getattr(decision, "plan", None)
    plan_id = str(getattr(plan, "plan_id", "") or "").strip()
    if plan_id:
        payload["plan_id"] = plan_id
    intent = getattr(decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    if intent_kind:
        payload["intent_kind"] = intent_kind
    route_to_studio = getattr(plan, "route_to_studio", None)
    if isinstance(route_to_studio, bool):
        payload["route_to_studio"] = route_to_studio
    payload.update(_selection_entrypoint_payload(metadata))
    return payload


def _selection_entrypoint_payload(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    payload: dict[str, Any] = {}
    key_map = {
        "planner_entrypoint": "planner_entrypoint",
        "source": "entrypoint_source",
        "launcher_mode": "launcher_mode",
        "launcher_surface": "launcher_surface",
        "runnable_kind": "runnable_kind",
    }
    for key, payload_key in key_map.items():
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[payload_key] = value
    if isinstance(metadata.get("daily_desktop_intent"), bool):
        payload["entrypoint_daily_desktop_intent"] = bool(metadata.get("daily_desktop_intent"))
    return payload


def _selection_role(selected_source: str) -> str:
    if selected_source == "daily_desktop_intent":
        return "legacy_desktop_intent_fallback"
    if selected_source == "runtime_planner":
        return "runtime_planner_primary"
    return selected_source or "none"


def planner_selection_timeline_event(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    event_payload = dict(payload)
    detail = str(
        event_payload.get("selection_source")
        or event_payload.get("selection_reason")
        or "direct_tool_selection"
    ).strip()
    return {
        "event": "agent.plan.selection",
        "detail": detail,
        "status": "planned",
        "source": str(event_payload.get("source") or "runtime_planner"),
        "decision_id": str(event_payload.get("decision_id") or ""),
        "plan_id": str(event_payload.get("plan_id") or ""),
        "payload": event_payload,
    }


def _planner_timeline_detail(event_type: str, payload: Mapping[str, Any]) -> str:
    if event_type == "agent.intent.selected":
        intent = payload.get("intent") if isinstance(payload.get("intent"), Mapping) else {}
        return str(intent.get("kind") or "").strip()
    if event_type == "agent.plan.created":
        plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else {}
        tool_plan = plan.get("tool_plan") if isinstance(plan.get("tool_plan"), Mapping) else {}
        return str(tool_plan.get("title") or plan.get("plan_id") or "").strip()
    if event_type == "agent.plan.step":
        step = payload.get("step") if isinstance(payload.get("step"), Mapping) else {}
        return str(step.get("title") or step.get("step_id") or "").strip()
    return event_type


def planner_run_event_payloads(
    decision: PlannerDecisionSnapshot | None,
) -> list[tuple[str, dict[str, Any]]]:
    if decision is None:
        return []
    payloads: list[tuple[str, dict[str, Any]]] = [
        (
            "agent.intent.selected",
            {
                "source": decision.source,
                "decision_id": decision.decision_id,
                "plan_id": decision.plan.plan_id,
                "intent": decision.selected_intent.model_dump(mode="json"),
                "candidate_intents": [
                    intent.model_dump(mode="json")
                    for intent in decision.candidate_intents
                ],
                "route_to_studio": decision.plan.route_to_studio,
            },
        ),
        (
            "agent.plan.created",
            {
                "source": decision.source,
                "decision_id": decision.decision_id,
                "plan": decision.plan.model_dump(mode="json"),
            },
        ),
    ]
    for step in decision.plan.tool_plan.steps:
        payloads.append(
            (
                "agent.plan.step",
                {
                    "source": decision.source,
                    "decision_id": decision.decision_id,
                    "plan_id": decision.plan.plan_id,
                    "step": step.model_dump(mode="json"),
                },
            )
        )
    return payloads


def _request_list(
    requests: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [request for request in requests if isinstance(request, Mapping)]


def _tool_names(requests: Iterable[Mapping[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if str(request.get("tool") or "").strip()
    ]


def _plan_steps(decision: Any | None) -> list[Any]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = getattr(tool_plan, "steps", None)
    return [step for step in steps or [] if step is not None]


def _plan_tool_names(decision: Any | None) -> list[str]:
    return [
        str(getattr(step, "tool_name", "") or "").strip()
        for step in _plan_steps(decision)
        if str(getattr(step, "tool_name", "") or "").strip()
    ]


def _plan_capability_ids(decision: Any | None) -> list[str]:
    plan = getattr(decision, "plan", None)
    capabilities = getattr(plan, "capabilities", None)
    return _unique_strings(
        str(getattr(capability, "capability_id", "") or "").strip()
        for capability in capabilities or []
    )


def _required_capability_ids(decision: Any | None) -> list[str]:
    intent = getattr(decision, "selected_intent", None)
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    tool_plan_required = _unique_strings(getattr(tool_plan, "required_capabilities", None) or [])
    if tool_plan_required:
        return tool_plan_required
    return _unique_strings(getattr(intent, "required_capabilities", None) or [])


def _missing_capability_ids(decision: Any | None) -> list[str]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    return _unique_strings(getattr(tool_plan, "missing_capabilities", None) or [])


def _tool_plan_values(decision: Any | None, attribute: str) -> list[str]:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    return _unique_strings(getattr(tool_plan, attribute, None) or [])


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items
