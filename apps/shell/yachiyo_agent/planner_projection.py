"""Projection helpers for runtime planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import PlannerDecisionSnapshot
from .planner_execution import planner_orchestration_requests
from .runtime_planner import RuntimePlanner

_MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"


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
    payload = {
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
    followup_target = _selection_followup_target_payload(decision)
    if followup_target:
        payload["yachiyo_followup_target"] = followup_target
    return payload


def planner_enriched_chat_request(
    request: Mapping[str, Any],
    *,
    allowed_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    payload = dict(request)
    runnable_id = str(payload.get("agent_id") or payload.get("runnable_id") or "").strip()
    if runnable_id and runnable_id != _MAIN_CHAT_AGENT_ID:
        return payload
    metadata = _normalized_entrypoint_metadata(
        payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    )
    decision = runtime_planner_decision(
        str(payload.get("prompt") or payload.get("goal") or ""),
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    if decision is None:
        return payload
    orchestration_metadata = _planner_orchestration_metadata(
        str(payload.get("prompt") or payload.get("goal") or ""),
        metadata=metadata,
    )
    payload["metadata"] = {
        **dict(metadata),
        **runtime_planner_metadata(decision),
        **orchestration_metadata,
    }
    return payload


def _normalized_entrypoint_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(metadata)
    source = _metadata_text(normalized, "entrypoint_source") or _metadata_text(normalized, "source")
    launcher_mode = _metadata_text(normalized, "launcher_mode")
    launcher_surface = _metadata_text(normalized, "launcher_surface")
    is_launcher = (
        source == "launcher"
        or launcher_mode in {"bubble", "live2d"}
        or bool(launcher_surface)
    )
    if is_launcher:
        normalized.setdefault("source", "launcher")
        normalized.setdefault("entrypoint_source", "launcher")
        if launcher_mode in {"bubble", "live2d"}:
            normalized.setdefault("planner_entrypoint", f"{launcher_mode}_default")
        else:
            normalized.setdefault("planner_entrypoint", "launcher_default")
        normalized.setdefault("launcher_surface", launcher_surface or "desktop_launcher")
        normalized.setdefault("runnable_kind", "main")
        return normalized

    normalized.setdefault("entrypoint_source", "chat_window")
    normalized.setdefault("planner_entrypoint", "chat_window")
    return normalized


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    return str(metadata.get(key) or "").strip()


def _planner_orchestration_metadata(
    prompt: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requests = planner_orchestration_requests(prompt, metadata=metadata)
    if not requests:
        return {}
    request = requests[0]
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    return {
        "yachiyo_orchestration": True,
        "yachiyo_orchestration_kind": str(request.get("orchestration_kind") or ""),
        "yachiyo_orchestration_target": str(request_input.get("target_name") or ""),
        "yachiyo_orchestration_planning_reason": str(request.get("planning_reason") or ""),
        "yachiyo_orchestration_route_to_studio": bool(request.get("route_to_studio")),
    }


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
    if decision is not None:
        payload.update(_decision_trace_payload(decision))
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
    followup_target = _selection_followup_target_payload(decision)
    if followup_target:
        payload["followup_target"] = followup_target
    route_to_studio = getattr(plan, "route_to_studio", None)
    if isinstance(route_to_studio, bool):
        payload["route_to_studio"] = route_to_studio
    payload.update(_selection_entrypoint_payload(metadata))
    return payload


def _decision_trace_payload(decision: Any) -> dict[str, Any]:
    trace: dict[str, Any] = {}
    selected_intent = getattr(decision, "selected_intent", None)
    if selected_intent is not None and hasattr(selected_intent, "model_dump"):
        trace["selected_intent"] = selected_intent.model_dump(mode="json")
    candidate_intents = getattr(decision, "candidate_intents", None)
    if isinstance(candidate_intents, Iterable) and not isinstance(candidate_intents, (str, bytes)):
        trace["candidate_intents"] = [
            intent.model_dump(mode="json")
            for intent in candidate_intents
            if hasattr(intent, "model_dump")
        ]
    plan = getattr(decision, "plan", None)
    if plan is not None and hasattr(plan, "model_dump"):
        trace["runtime_plan"] = plan.model_dump(mode="json")
    tool_plan = getattr(plan, "tool_plan", None)
    if tool_plan is not None and hasattr(tool_plan, "model_dump"):
        trace["tool_plan"] = tool_plan.model_dump(mode="json")
    return trace


def _selection_followup_target_payload(decision: Any | None) -> dict[str, Any]:
    intent = getattr(decision, "selected_intent", None)
    inputs = getattr(intent, "inputs", None)
    if not isinstance(inputs, Mapping):
        return {}
    desktop_discovered_app_target = _desktop_discovered_app_followup_target(inputs)
    if desktop_discovered_app_target:
        return desktop_discovered_app_target
    target_app = str(inputs.get("target_app_hint") or "").strip()
    target_action = str(inputs.get("target_action_hint") or "").strip()
    context_source = str(inputs.get("context_source") or "").strip()
    if target_app and target_action == "app_paste":
        payload: dict[str, Any] = {
            "kind": "app_write",
            "app_name": target_app,
            "target_action": target_action,
            "body_source": "model_generated_content",
        }
        container_action = str(inputs.get("target_container_action_hint") or "").strip()
        if container_action:
            payload["container_action"] = container_action
        if context_source:
            payload["context_source"] = context_source
        return payload

    communication_target = _communication_followup_hint(inputs)
    if not communication_target:
        return {}
    recipient = str(communication_target.get("recipient") or "").strip()
    if not recipient:
        return {}
    payload = {
        "kind": "communication_message",
        "recipient": recipient,
        "body_source": "model_generated_content",
        "send_action": str(communication_target.get("send_action") or "send").strip(),
        "mode": str(communication_target.get("mode") or "focus").strip() or "focus",
    }
    for source_key, target_key in (
        ("app_name", "app_name"),
        ("channel", "channel"),
        ("content_transform_hint", "transform"),
    ):
        value = str(communication_target.get(source_key) or "").strip()
        if value:
            payload[target_key] = value
    return payload


def _desktop_discovered_app_followup_target(inputs: Mapping[str, Any]) -> dict[str, Any]:
    app_capability = inputs.get("app_capability_hint")
    desktop_discovery = inputs.get("desktop_discovery_hint")
    if not isinstance(app_capability, Mapping) or not isinstance(desktop_discovery, Mapping):
        return {}
    if str(desktop_discovery.get("action") or "").strip() != "discover_apps":
        return {}
    query = str(desktop_discovery.get("query") or app_capability.get("query") or "").strip()
    if not query:
        return {}
    payload: dict[str, Any] = {
        "kind": "desktop_discovered_app_action",
        "app_query": query,
        "app_name_source": "desktop.list_apps",
    }
    description = str(app_capability.get("description") or "").strip()
    if description:
        payload["capability_description"] = description
    safe_shortcut = inputs.get("safe_shortcut_hint")
    if isinstance(safe_shortcut, Mapping):
        action = str(safe_shortcut.get("action") or "").strip()
        if action:
            payload["target_action"] = "safe_shortcut"
            payload["safe_shortcut_action"] = action
    target_path = str(inputs.get("selected_app_target_path_hint") or "").strip()
    if target_path:
        payload["target_action"] = "open_path_with_selected_app"
        payload["target_path"] = target_path
    if "target_action" not in payload:
        payload["target_action"] = "open_app"
    compose_text = str(inputs.get("foreground_compose_text_hint") or "").strip()
    if compose_text:
        payload["compose_text"] = compose_text
        payload["body_source"] = "explicit_user_text"
    creative_canvas = inputs.get("creative_canvas_hint")
    if isinstance(creative_canvas, Mapping):
        payload["creative_canvas"] = dict(creative_canvas)
    ui_inspection = inputs.get("ui_inspection_hint")
    if isinstance(ui_inspection, Mapping):
        payload["post_action_observation"] = {
            "tool": "desktop.ui_elements",
            "input": {
                key: ui_inspection[key]
                for key in ("role_filter", "limit")
                if key in ui_inspection and ui_inspection[key] not in (None, "")
            },
        }
    return payload


def _communication_followup_hint(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("communication_target_hint", "direct_message_hint"):
        target = inputs.get(key)
        if isinstance(target, Mapping):
            return target
    return {}


def _selection_entrypoint_payload(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    payload: dict[str, Any] = {}
    key_map = {
        "planner_entrypoint": "planner_entrypoint",
        "launcher_mode": "launcher_mode",
        "launcher_surface": "launcher_surface",
        "runnable_kind": "runnable_kind",
    }
    for key, payload_key in key_map.items():
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[payload_key] = value
    entrypoint_source = (
        str(metadata.get("entrypoint_source") or "").strip()
        or str(metadata.get("source") or "").strip()
    )
    if entrypoint_source:
        payload["entrypoint_source"] = entrypoint_source
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
