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
    tool_names = [
        str(step.tool_name or "").strip()
        for step in decision.plan.tool_plan.steps
        if str(step.tool_name or "").strip()
    ]
    return {
        "yachiyo_runtime_planner": True,
        "yachiyo_plan_source": decision.source,
        "yachiyo_decision_id": decision.decision_id,
        "yachiyo_plan_id": decision.plan.plan_id,
        "yachiyo_intent_kind": decision.selected_intent.kind,
        "yachiyo_intent_confidence": round(float(decision.selected_intent.confidence or 0), 3),
        "yachiyo_route_to_studio": decision.plan.route_to_studio,
        "yachiyo_plan_tools": tool_names,
        "yachiyo_missing_capabilities": list(decision.plan.tool_plan.missing_capabilities),
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
) -> dict[str, Any]:
    planner_request_list = _request_list(planner_requests)
    legacy_request_list = _request_list(legacy_requests)
    selected_request_list = _request_list(selected_requests)
    payload: dict[str, Any] = {
        "source": "runtime_planner",
        "selection_source": str(selected_source or "").strip(),
        "selection_reason": str(selected_reason or "").strip(),
        "planner_tools": _tool_names(planner_request_list),
        "legacy_tools": _tool_names(legacy_request_list),
        "selected_tools": _tool_names(selected_request_list),
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
    return payload


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
