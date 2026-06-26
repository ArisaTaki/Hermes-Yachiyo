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
