"""Projection helpers for runtime planner decisions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import PlannerDecisionSnapshot, TaskCoreSnapshot
from .capability_registry import runtime_execution_tool_names
from .desktop_execution_policy import with_daily_entrypoint_desktop_execution_policy
from .desktop_plan_hints import (
    discovered_app_open_needs_model_followup,
    discovered_app_pending_user_action,
)
from .isolated_provider_session import (
    annotate_envelope_with_desktop_provider_session,
    ensure_isolated_desktop_provider_session_for_envelope,
)
from .planner_execution import planner_orchestration_requests
from .replans import (
    task_replan_request_from_failure,
    task_replan_run_event_payload,
    task_replan_timeline_event,
)
from .runtime_planner import RuntimePlanner
from .runtime_execution import (
    runtime_execution_blocked_requests_from_envelope_payload,
    runtime_execution_envelope_payload,
    runtime_execution_requests_from_envelope_payload,
)
from .task_core_event_projection import (
    task_core_initial_progress_event_payloads,
    task_core_progress_event_detail,
)
from .task_progress_snapshots import task_progress_summary_from_task_core

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
    *,
    allowed_tools: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
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
        "yachiyo_capability_plan": _capability_plan_payload(decision),
        "yachiyo_plan_approvals_required": list(tool_plan.approvals_required),
        "yachiyo_plan_artifacts_expected": list(tool_plan.artifacts_expected),
        "yachiyo_plan_open_questions": list(tool_plan.open_questions),
        "yachiyo_required_capabilities": _required_capability_ids(decision),
        "yachiyo_missing_capabilities": list(tool_plan.missing_capabilities),
    }
    if decision.plan.task_core is not None:
        payload["yachiyo_task_core"] = decision.plan.task_core.model_dump(mode="json")
        task_progress = task_progress_summary_from_task_core(decision.plan.task_core)
        if task_progress is not None:
            payload["yachiyo_task_progress"] = task_progress.model_dump(mode="json")
    execution_envelope = runtime_execution_envelope_payload(
        decision,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    if execution_envelope:
        _apply_execution_envelope_metadata(payload, execution_envelope)
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
    request_allowed_tools = _request_allowed_tools(payload)
    effective_allowed_tools = allowed_tools or request_allowed_tools
    decision = runtime_planner_decision(
        str(payload.get("prompt") or payload.get("goal") or ""),
        allowed_tools=effective_allowed_tools,
        metadata=metadata,
    )
    if decision is None:
        return payload
    orchestration_metadata = _planner_orchestration_metadata(
        str(payload.get("prompt") or payload.get("goal") or ""),
        metadata=metadata,
    )
    planner_metadata = runtime_planner_metadata(
        decision,
        allowed_tools=effective_allowed_tools,
        metadata=metadata,
    )
    execution_allowed_tools = _entrypoint_runtime_execution_allowed_tools(
        decision,
        explicit_allowed_tools=effective_allowed_tools,
    )
    execution_decision = (
        runtime_planner_decision(
            str(payload.get("prompt") or payload.get("goal") or ""),
            allowed_tools=execution_allowed_tools,
            metadata=metadata,
        )
        or decision
    )
    runtime_execution_envelope = _runtime_execution_envelope_payload_for_chat_start(
        execution_decision,
        allowed_tools=execution_allowed_tools,
        full_plan=True,
        metadata=metadata,
    )
    if runtime_execution_envelope:
        _apply_execution_envelope_metadata(
            planner_metadata,
            runtime_execution_envelope,
        )
    if "allowed_tools" not in payload and execution_allowed_tools:
        payload["allowed_tools"] = execution_allowed_tools
        planner_metadata["yachiyo_entrypoint_allowed_tools"] = list(
            execution_allowed_tools
        )
    compatible_plan_tools = _daily_desktop_compatible_plan_tools(decision, metadata)
    if compatible_plan_tools:
        planner_metadata["yachiyo_plan_tools"] = compatible_plan_tools
    payload_metadata = {
        **dict(metadata),
        **planner_metadata,
        **orchestration_metadata,
    }
    payload["metadata"] = payload_metadata
    if runtime_execution_envelope:
        payload["runtime_execution_envelope"] = runtime_execution_envelope
        if "direct_tool_requests" not in payload:
            direct_tool_requests = runtime_execution_requests_from_envelope_payload(
                runtime_execution_envelope,
                allowed_tools=execution_allowed_tools,
            )
            direct_tool_requests = [
                request
                for request in direct_tool_requests
                if not _direct_request_route_blocked(request)
            ]
            if direct_tool_requests:
                payload["direct_tool_requests"] = direct_tool_requests
            blocked_requests = runtime_execution_blocked_requests_from_envelope_payload(
                runtime_execution_envelope,
                allowed_tools=execution_allowed_tools,
            )
            if blocked_requests:
                payload["blocked_direct_tool_requests"] = blocked_requests
                payload_metadata["yachiyo_runtime_blocked"] = True
                payload_metadata["yachiyo_blocked_execution_requests"] = [
                    request.get("tool")
                    for request in blocked_requests
                    if request.get("tool")
                ]
                payload_metadata["yachiyo_blocked_execution_reasons"] = _unique_strings(
                    request.get("policy_reason") or request.get("blocked_by")
                    for request in blocked_requests
                )
    return payload


def _direct_request_route_blocked(request: Mapping[str, Any]) -> bool:
    route = request.get("desktop_execution_route")
    if not isinstance(route, Mapping):
        return False
    return route.get("can_execute") is False


def _runtime_execution_envelope_payload_for_chat_start(
    decision: PlannerDecisionSnapshot,
    *,
    allowed_tools: Iterable[str] | None = None,
    full_plan: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_payload(
        decision,
        allowed_tools=allowed_tools,
        full_plan=full_plan,
        metadata=metadata,
    )
    if not envelope:
        return {}
    session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
    if session.get("needed") and session.get("running"):
        refreshed = runtime_execution_envelope_payload(
            decision,
            allowed_tools=allowed_tools,
            full_plan=full_plan,
            metadata=metadata,
        )
        if refreshed:
            envelope = refreshed
    return annotate_envelope_with_desktop_provider_session(envelope, session)


def _entrypoint_runtime_execution_allowed_tools(
    decision: PlannerDecisionSnapshot,
    *,
    explicit_allowed_tools: Iterable[str] | None,
) -> list[str] | None:
    if explicit_allowed_tools is not None:
        return [
            str(tool or "").strip()
            for tool in explicit_allowed_tools
            if str(tool or "").strip()
        ] or None
    return runtime_execution_tool_names(
        intent_kind=decision.selected_intent.kind,
        prefer_low_level=True,
    )


def _request_allowed_tools(payload: Mapping[str, Any]) -> list[str] | None:
    value = payload.get("allowed_tools")
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return None
    tools = [str(tool or "").strip() for tool in value if str(tool or "").strip()]
    return tools or None


def _execution_request_payloads(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return []
    return [request for request in requests if isinstance(request, Mapping)]


def _apply_execution_envelope_metadata(
    payload: dict[str, Any],
    envelope: Mapping[str, Any],
) -> None:
    execution_requests = _execution_request_payloads(envelope)
    payload["yachiyo_execution_envelope"] = dict(envelope)
    payload["yachiyo_execution_requests"] = [
        request.get("tool_name")
        for request in execution_requests
        if request.get("tool_name")
    ]
    execution_previews = _execution_request_previews(execution_requests)
    if execution_previews:
        payload["yachiyo_execution_request_previews"] = execution_previews
    else:
        payload.pop("yachiyo_execution_request_previews", None)
    task_core = _execution_envelope_task_core(envelope)
    if task_core is not None:
        payload["yachiyo_task_core"] = task_core.model_dump(mode="json")
        task_progress = task_progress_summary_from_task_core(task_core)
        if task_progress is not None:
            payload["yachiyo_task_progress"] = task_progress.model_dump(mode="json")


def _execution_envelope_task_core(
    envelope: Mapping[str, Any],
) -> TaskCoreSnapshot | None:
    task_core = envelope.get("task_core")
    if not isinstance(task_core, Mapping):
        return None
    try:
        return TaskCoreSnapshot.model_validate(task_core)
    except ValueError:
        return None


def _execution_request_previews(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for request in requests:
        tool_name = str(request.get("tool_name") or request.get("tool") or "").strip()
        if not tool_name:
            continue
        preview: dict[str, Any] = {"tool_name": tool_name}
        for key in (
            "request_id",
            "step_id",
            "capability_id",
            "runtime_stage",
            "runtime_role",
            "status",
            "planning_reason",
            "source",
        ):
            value = request.get(key)
            if value not in (None, "", [], {}):
                preview[key] = value
        request_input = request.get("input")
        if isinstance(request_input, Mapping) and request_input:
            preview["input"] = dict(request_input)
        for key in (
            "approval_required",
            "continue_to_model",
            "requires_observation",
            "requires_post_action_verification",
        ):
            if bool(request.get(key)):
                preview[key] = True
        for key in ("depends_on", "fallback_tools", "replan_signal_ids", "replan_triggers"):
            value = request.get(key)
            if isinstance(value, list) and value:
                preview[key] = list(value)
        desktop_loop = request.get("desktop_loop")
        if isinstance(desktop_loop, Mapping) and desktop_loop:
            preview["desktop_loop"] = dict(desktop_loop)
        previews.append(preview)
    return previews


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
        surface = launcher_mode if launcher_mode in {"bubble", "live2d"} else "launcher"
        return with_daily_entrypoint_desktop_execution_policy(
            normalized,
            surface=surface,
        )

    normalized.setdefault("entrypoint_source", "chat_window")
    normalized.setdefault("planner_entrypoint", "chat_window")
    return with_daily_entrypoint_desktop_execution_policy(normalized, surface="chat")


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    return str(metadata.get(key) or "").strip()


def _daily_desktop_compatible_plan_tools(
    decision: PlannerDecisionSnapshot,
    metadata: Mapping[str, Any],
) -> list[str]:
    if not bool(metadata.get("daily_desktop_intent")):
        return []
    source = _metadata_text(metadata, "entrypoint_source") or _metadata_text(metadata, "source")
    if source == "launcher" or _metadata_text(metadata, "launcher_mode"):
        return []
    intent = decision.selected_intent
    if intent.kind == "media_playback" and str(intent.inputs.get("query") or "").strip():
        return [
            "desktop.list_apps",
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "media.music_app_open_and_play",
            "desktop.ui_elements",
        ]
    return []


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
        "selected_tools": _selection_display_tool_names(selected_request_list),
        "plan_step_count": len(plan_steps),
        "plan_capability_count": len(plan_capabilities),
        "missing_capability_count": len(missing_capabilities),
        "approval_count": len(approvals_required),
        "artifact_count": len(artifacts_expected),
        "open_question_count": len(open_questions),
        "planner_request_count": len(planner_request_list),
        "legacy_request_count": len(legacy_request_list),
        "selected_request_count": len(_selection_display_tool_names(selected_request_list)),
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
    orchestration = _selection_orchestration_payload(decision)
    if orchestration:
        payload["orchestration"] = orchestration
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
    task_core = getattr(plan, "task_core", None)
    if task_core is not None and hasattr(task_core, "model_dump"):
        trace["task_core"] = task_core.model_dump(mode="json")
    return trace


def _selection_followup_target_payload(decision: Any | None) -> dict[str, Any]:
    intent = getattr(decision, "selected_intent", None)
    inputs = getattr(intent, "inputs", None)
    if not isinstance(inputs, Mapping):
        return {}
    desktop_file_open_target = _desktop_file_open_followup_target(inputs)
    if desktop_file_open_target:
        return desktop_file_open_target
    discovered_app_write_target = _discovered_app_write_followup_target(inputs, decision)
    if discovered_app_write_target:
        return discovered_app_write_target
    media_app_target = _media_app_playback_followup_target(inputs)
    if media_app_target:
        return media_app_target
    generated_app_write_target = _desktop_generated_app_write_followup_target(inputs)
    if generated_app_write_target:
        return generated_app_write_target
    dynamic_context_discovered_app_target = _dynamic_context_discovered_app_followup_target(
        inputs,
        decision,
    )
    if dynamic_context_discovered_app_target:
        return dynamic_context_discovered_app_target
    desktop_discovered_app_target = _desktop_discovered_app_followup_target(
        inputs,
        decision,
    )
    if desktop_discovered_app_target:
        return desktop_discovered_app_target
    desktop_observed_action_target = _desktop_observed_action_followup_target(
        inputs,
        decision,
    )
    if desktop_observed_action_target:
        return desktop_observed_action_target
    note_write_target = _note_write_followup_target(inputs)
    if note_write_target:
        return note_write_target
    target_app = str(inputs.get("target_app_hint") or "").strip()
    target_action = str(inputs.get("target_action_hint") or "").strip()
    context_source = str(inputs.get("context_source") or "").strip()
    if target_action == "current_input_write":
        payload = {
            "kind": "current_input_write",
            "target_action": target_action,
            "body_source": "model_generated_content",
        }
        if context_source:
            payload["context_source"] = context_source
        return _with_generated_artifact_write(payload, decision)
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
    if communication_target:
        recipient = str(communication_target.get("recipient") or "").strip()
        if recipient:
            body = str(communication_target.get("body") or "").strip()
            payload = {
                "kind": "communication_message",
                "recipient": recipient,
                "body_source": "explicit_user_text" if body else "model_generated_content",
                "send_action": str(communication_target.get("send_action") or "send").strip(),
                "mode": str(communication_target.get("mode") or "focus").strip() or "focus",
            }
            if body:
                payload["body"] = body
            for source_key, target_key in (
                ("app_name", "app_name"),
                ("channel", "channel"),
                ("content_transform_hint", "transform"),
            ):
                value = str(communication_target.get(source_key) or "").strip()
                if value:
                    payload[target_key] = value
            app_query = _communication_app_query_for_channel(str(payload.get("channel") or ""))
            if not payload.get("app_name") and app_query:
                compose_payload = {
                    "recipient": recipient,
                    "send_action": str(payload.get("send_action") or "send").strip(),
                }
                channel = str(payload.get("channel") or "").strip()
                if channel:
                    compose_payload["channel"] = channel
                discovered_payload: dict[str, Any] = {
                    "kind": "desktop_discovered_app_action",
                    "app_query": app_query,
                    "app_name_source": "desktop.list_apps",
                    "target_action": "safe_shortcut",
                    "safe_shortcut_action": "new_message",
                    "body_source": "model_generated_content",
                    "communication_compose": compose_payload,
                    "post_action_observation": {
                        "tool": "desktop.ui_elements",
                        "input": {},
                    },
                }
                transform = str(payload.get("transform") or "").strip()
                if transform:
                    discovered_payload["content_transform_hint"] = transform
                return _with_generated_artifact_write(discovered_payload, decision)
            return _with_generated_artifact_write(payload, decision)
    return _artifact_write_followup_target(decision, inputs)


def _artifact_write_followup_target(
    decision: Any | None,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    intent = getattr(decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    if intent_kind not in {"report_generation", "web_research"}:
        return {}
    artifact_paths = _tool_plan_values(decision, "artifacts_expected")
    if not artifact_paths:
        return {}
    payload = {
        "kind": "artifact_write",
        "target_action": "write_artifact",
        "path": artifact_paths[0],
        "body_source": "model_generated_content",
        "tool": "artifact.write",
    }
    context_source = str(inputs.get("context_source") or "").strip()
    if context_source:
        payload["context_source"] = context_source
    if intent_kind:
        payload["intent_kind"] = intent_kind
    return payload


def _with_generated_artifact_write(
    payload: dict[str, Any],
    decision: Any | None,
) -> dict[str, Any]:
    intent = getattr(decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    if intent_kind not in {
        "multi_agent",
        "report_generation",
        "web_research",
        "workflow_orchestration",
    }:
        return payload
    artifact_paths = _tool_plan_values(decision, "artifacts_expected")
    if not artifact_paths:
        return payload
    return {
        **payload,
        "artifact_write": {
            "target_action": "write_artifact",
            "path": artifact_paths[0],
            "body_source": "model_generated_content",
            "tool": "artifact.write",
            "intent_kind": intent_kind,
        },
    }


def _note_write_followup_target(inputs: Mapping[str, Any]) -> dict[str, Any]:
    if str(inputs.get("action") or "").strip() != "create_note_from_context":
        return {}
    context_source = str(inputs.get("source") or inputs.get("context_source") or "").strip()
    if not context_source:
        return {}
    payload = {
        "kind": "note_write",
        "target_action": "create_note",
        "body_source": "model_generated_content",
        "context_source": context_source,
        "tool": "notes.create",
    }
    return payload


def _desktop_observed_action_followup_target(
    inputs: Mapping[str, Any],
    decision: Any | None = None,
) -> dict[str, Any]:
    plan_target = _desktop_observed_action_followup_target_from_plan(inputs, decision)
    if plan_target:
        return plan_target
    browser_action = str(inputs.get("browser_action") or "").strip()
    if browser_action not in {"click", "type_text"}:
        return {}
    selector = str(inputs.get("selector") or "").strip()
    role_filter = _desktop_role_filter_from_observed_selector(
        selector,
        default="text field" if browser_action == "type_text" else "button",
    )
    target = _desktop_target_from_observed_selector(selector)
    if browser_action == "click":
        target = target or "requested element"
        payload: dict[str, Any] = {
            "kind": "desktop_observed_action",
            "target_action": "click",
            "target": target,
            "role_filter": role_filter,
            "click_count": _safe_int(inputs.get("click_count"), default=1),
            "limit": 80,
            "observation_source": "desktop.read_ui",
        }
        return payload
    text = str(inputs.get("text") or "")
    if not text:
        return {}
    return {
        "kind": "desktop_observed_action",
        "target_action": "type_text",
        "target": target or "text input",
        "text": text,
        "role_filter": role_filter,
        "limit": 80,
        "body_source": "explicit_user_text",
        "observation_source": "desktop.read_ui",
    }


def _desktop_observed_action_followup_target_from_plan(
    inputs: Mapping[str, Any],
    decision: Any | None,
) -> dict[str, Any]:
    operation_step = _planner_step_by_id(decision, "operate-foreground-ui")
    if str(getattr(operation_step, "action", "") or "").strip() != "observe_ui_target":
        return {}
    input_preview = getattr(operation_step, "input_preview", None)
    payload = input_preview if isinstance(input_preview, Mapping) else {}
    target = str(payload.get("target") or "").strip()
    if not target:
        return {}
    operation_hint = str(inputs.get("operation_hint") or "").strip()
    target_action = "type_text" if operation_hint in {"type", "type_text"} else "click"
    result: dict[str, Any] = {
        "kind": "desktop_observed_action",
        "target_action": target_action,
        "target": target,
        "role_filter": str(payload.get("role_filter") or "").strip(),
        "limit": _safe_int(payload.get("limit"), default=80),
        "observation_source": str(
            getattr(operation_step, "tool_name", "") or "desktop.ui_elements"
        ).strip(),
    }
    app_name = str(inputs.get("app_name_hint") or "").strip()
    if app_name:
        result["app_name"] = app_name
    app_capability = (
        inputs.get("app_capability_hint")
        if isinstance(inputs.get("app_capability_hint"), Mapping)
        else {}
    )
    app_query = str(app_capability.get("query") or "").strip()
    if app_query:
        result["app_query"] = app_query
    if target_action == "click":
        result["click_count"] = _safe_int(payload.get("click_count"), default=1)
        return {
            key: value
            for key, value in result.items()
            if value not in ("", None, [], {})
        }
    text = str(payload.get("text") or inputs.get("safe_type_text_hint") or "")
    if not text:
        return {}
    result["text"] = text
    result["body_source"] = "explicit_user_text"
    submit_action = str(inputs.get("foreground_submit_action_hint") or "").strip()
    if submit_action:
        result["submit_action"] = submit_action
    return {
        key: value
        for key, value in result.items()
        if value not in ("", None, [], {})
    }


def _planner_step_by_id(decision: Any | None, step_id: str) -> Any | None:
    clean_step_id = str(step_id or "").strip()
    if not clean_step_id:
        return None
    steps = list(
        getattr(
            getattr(getattr(decision, "plan", None), "tool_plan", None),
            "steps",
            [],
        )
        or []
    )
    for step in steps:
        if str(getattr(step, "step_id", "") or "").strip() == clean_step_id:
            return step
    return None


def _model_generated_content_hint_payload(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    value = inputs.get("model_generated_content_hint")
    return value if isinstance(value, Mapping) else {}


def _desktop_generated_app_write_followup_target(
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    if not _model_generated_content_hint_payload(inputs):
        return {}
    app_name = str(inputs.get("app_name_hint") or "").strip()
    if not app_name:
        return {}
    payload: dict[str, Any] = {
        "kind": "app_write",
        "app_name": app_name,
        "target_action": "app_paste",
        "body_source": "model_generated_content",
    }
    safe_shortcut = inputs.get("safe_shortcut_hint")
    if isinstance(safe_shortcut, Mapping):
        action = str(safe_shortcut.get("action") or "").strip()
        if action in {"new_document", "new_note"}:
            payload["container_action"] = action
    return payload


def _desktop_target_from_observed_selector(selector: str) -> str:
    clean = str(selector or "").strip()
    if clean.startswith("text="):
        return clean.removeprefix("text=").strip()
    lowered = clean.lower()
    if "textarea" in lowered or "contenteditable" in lowered:
        return "text input"
    if "," in lowered and "input" in lowered:
        return "text input"
    if "search" in lowered:
        return "search field"
    if "input" in lowered:
        return "text input"
    return ""


def _desktop_role_filter_from_observed_selector(selector: str, *, default: str) -> str:
    clean = str(selector or "").strip().lower()
    if not clean:
        return default
    if "textarea" in clean or "contenteditable" in clean:
        return "text field"
    if "input" in clean:
        return "text field"
    if "button" in clean or clean.startswith("text="):
        return "button"
    if "a[" in clean or clean == "a":
        return "link"
    return default


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _selection_orchestration_payload(decision: Any | None) -> dict[str, Any]:
    intent = getattr(decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    if intent_kind == "workflow_orchestration":
        orchestration_kind = "workflow"
        surface = "Workflow"
    elif intent_kind == "multi_agent":
        orchestration_kind = "group_run"
        surface = "GroupRun"
    else:
        return {}
    inputs = getattr(intent, "inputs", None)
    if not isinstance(inputs, Mapping):
        inputs = {}
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = getattr(tool_plan, "steps", []) if tool_plan is not None else []
    first_step = next(
        (step for step in steps if str(getattr(step, "capability_id", "") or "").strip()),
        None,
    )
    payload: dict[str, Any] = {
        "kind": orchestration_kind,
        "surface": surface,
        "handoff": True,
        "route_to_studio": bool(getattr(plan, "route_to_studio", False)),
        "target_name": str(inputs.get("target_name_hint") or "").strip(),
    }
    workflow_action = str(inputs.get("workflow_action_hint") or "").strip()
    if workflow_action:
        payload["action"] = workflow_action
    if first_step is not None:
        tool_name = str(getattr(first_step, "tool_name", "") or "").strip()
        capability_id = str(getattr(first_step, "capability_id", "") or "").strip()
        step_action = str(getattr(first_step, "action", "") or "").strip()
        if tool_name:
            payload["tool"] = tool_name
        if capability_id:
            payload["capability_id"] = capability_id
        if step_action:
            payload["step_action"] = step_action
    return payload


def _desktop_file_open_followup_target(inputs: Mapping[str, Any]) -> dict[str, Any]:
    file_hint = inputs.get("file_open_discovery_hint")
    if not isinstance(file_hint, Mapping):
        return {}
    app_name = str(inputs.get("app_name_hint") or file_hint.get("app_name") or "").strip()
    if not app_name:
        return {}
    file_query = {
        str(key): str(file_hint.get(key) or "").strip()
        for key in ("path", "pattern", "file_type", "selection")
        if str(file_hint.get(key) or "").strip()
    }
    if not file_query:
        return {}
    return {
        "kind": "desktop_file_open_with_app",
        "app_name": app_name,
        "target_action": "open_path_with_app",
        "target_path_source": "workspace.list",
        "file_query": file_query,
    }


def _media_app_playback_followup_target(inputs: Mapping[str, Any]) -> dict[str, Any]:
    app_capability = inputs.get("target_app_capability_hint")
    app_query = ""
    app_name = str(inputs.get("app_name") or "").strip()
    if isinstance(app_capability, Mapping):
        app_query = str(app_capability.get("query") or "").strip()
    if not app_query and app_name:
        app_query = app_name
    if not app_query:
        return {}
    if str(inputs.get("action") or "").strip() != "play":
        return {}
    media_query = str(inputs.get("query") or "").strip()
    if not media_query:
        payload = {
            "kind": "desktop_discovered_media_playback",
            "app_query": app_query,
            "app_name_source": "desktop.list_apps",
            "target_action": "play_control",
            "result_selection": {
                "target": "play 播放",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
            "post_action_observation": {
                "tool": "desktop.ui_elements",
                "input": {},
            },
        }
        if app_name:
            payload["app_name"] = app_name
        return payload
    payload = {
        "kind": "desktop_discovered_media_playback",
        "app_query": app_query,
        "app_name_source": "desktop.list_apps",
        "target_action": "safe_shortcut",
        "safe_shortcut_action": "find",
        "media_playback_query": media_query,
        "result_selection": {
            "target": "first result",
            "role_filter": "",
            "limit": 80,
            "click_count": 1,
        },
        "post_action_observation": {
            "tool": "desktop.ui_elements",
            "input": {},
        },
    }
    if app_name:
        payload["app_name"] = app_name
    return payload


def _discovered_app_write_followup_target(
    inputs: Mapping[str, Any],
    decision: Any | None = None,
) -> dict[str, Any]:
    app_capability = inputs.get("target_app_capability_hint")
    if not isinstance(app_capability, Mapping):
        return {}
    if str(inputs.get("target_action_hint") or "").strip() != "app_paste":
        return {}
    query = str(app_capability.get("query") or "").strip()
    if not query:
        return {}
    payload: dict[str, Any] = {
        "kind": "desktop_discovered_app_action",
        "app_query": query,
        "app_name_source": "desktop.list_apps",
        "target_action": "safe_shortcut",
        "body_source": "model_generated_content",
        "post_action_observation": {
            "tool": "desktop.ui_elements",
            "input": {},
        },
    }
    description = str(app_capability.get("description") or "").strip()
    if description:
        payload["capability_description"] = description
    container_action = str(inputs.get("target_container_action_hint") or "").strip()
    if container_action:
        payload["safe_shortcut_action"] = container_action
    intent = getattr(decision, "selected_intent", None)
    if str(getattr(intent, "kind", "") or "").strip() == "web_research":
        payload["body_source"] = "research_artifact"
        return _with_generated_artifact_write(payload, decision)
    return payload


def _desktop_discovered_app_followup_target(
    inputs: Mapping[str, Any],
    decision: Any | None = None,
) -> dict[str, Any]:
    desktop_discovery = inputs.get("desktop_discovery_hint")
    if not isinstance(desktop_discovery, Mapping):
        return {}
    if str(desktop_discovery.get("action") or "").strip() != "discover_apps":
        return {}
    app_capability = _desktop_discovery_capability_hint(inputs)
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
    app_search = _desktop_discovered_app_search_payload(inputs, decision)
    if app_search:
        payload["target_action"] = "app_search"
        payload["safe_shortcut_action"] = "find"
        payload["app_search"] = app_search
        if app_search.get("verify"):
            payload["post_action_observation"] = {
                "tool": "desktop.ui_elements",
                "input": {},
            }
    target_path = str(inputs.get("selected_app_target_path_hint") or "").strip()
    if target_path:
        payload["target_action"] = "open_path_with_selected_app"
        payload["target_path"] = target_path
    if "target_action" not in payload:
        payload["target_action"] = "open_app"
    compose_text = str(inputs.get("foreground_compose_text_hint") or "").strip()
    generated_content = _model_generated_content_hint_payload(inputs)
    if generated_content:
        payload["body_source"] = "model_generated_content"
        payload["post_action_observation"] = {
            "tool": "desktop.ui_elements",
            "input": {},
        }
    elif compose_text:
        payload["compose_text"] = compose_text
        payload["body_source"] = "explicit_user_text"
        payload["post_action_observation"] = {
            "tool": "desktop.ui_elements",
            "input": {},
        }
    communication_compose = inputs.get("communication_compose_hint")
    if isinstance(communication_compose, Mapping):
        compose_payload = {
            str(key): str(communication_compose.get(key) or "").strip()
            for key in ("channel", "recipient", "body", "send_action")
            if str(communication_compose.get(key) or "").strip()
        }
        if compose_payload:
            payload["communication_compose"] = compose_payload
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
    user_goal = str(
        getattr(getattr(decision, "selected_intent", None), "user_goal", "") or ""
    )
    needs_open_followup = discovered_app_open_needs_model_followup(inputs, user_goal)
    if "post_action_observation" not in payload and needs_open_followup:
        payload["post_action_observation"] = {
            "tool": "desktop.ui_elements",
            "input": {"limit": 80},
            "continue_to_model": True,
        }
    if needs_open_followup:
        pending_user_action = discovered_app_pending_user_action(user_goal)
        if pending_user_action:
            payload["pending_user_action"] = pending_user_action
    return payload


def _dynamic_context_discovered_app_followup_target(
    inputs: Mapping[str, Any],
    decision: Any | None = None,
) -> dict[str, Any]:
    transfer = inputs.get("dynamic_context_ui_transfer_hint")
    if not isinstance(transfer, Mapping):
        return {}
    if str(transfer.get("action") or "").strip() != "transfer_context":
        return {}
    if str(transfer.get("target_kind") or "").strip() != "app_paste":
        return {}
    desktop_discovery = inputs.get("desktop_discovery_hint")
    if not isinstance(desktop_discovery, Mapping):
        return {}
    if str(desktop_discovery.get("action") or "").strip() != "discover_apps":
        return {}
    app_capability = _desktop_discovery_capability_hint(inputs)
    query = str(desktop_discovery.get("query") or app_capability.get("query") or "").strip()
    if not query:
        return {}
    source = str(transfer.get("source") or "").strip()
    if source not in {"clipboard", "selection", "current_page_link", "current_page_content"}:
        return {}
    payload: dict[str, Any] = {
        "kind": "desktop_discovered_app_action",
        "app_query": query,
        "app_name_source": "desktop.list_apps",
        "target_action": "safe_shortcut",
        "safe_shortcut_action": "paste",
        "body_source": source,
        "context_source": source,
        "dynamic_context_transfer": {
            key: str(transfer.get(key) or "").strip()
            for key in ("source", "action", "target_kind", "target", "mode")
            if str(transfer.get(key) or "").strip()
        },
        "post_action_observation": _dynamic_context_discovered_app_observation(decision),
    }
    source_action = _dynamic_context_source_action(source)
    if source_action:
        payload["source_action"] = source_action
    description = str(app_capability.get("description") or "").strip()
    if description:
        payload["capability_description"] = description
    return payload


def _dynamic_context_discovered_app_observation(decision: Any | None) -> dict[str, Any]:
    verify_step = _decision_plan_step(decision, "verify-selected-discovered-app-action")
    action_payload = _decision_step_action_payload(verify_step)
    if action_payload:
        return action_payload
    return {"tool": "desktop.ui_elements", "input": {"limit": 80}}


def _dynamic_context_source_action(source: str) -> str:
    clean_source = str(source or "").strip()
    if clean_source == "selection":
        return "copy"
    if clean_source == "current_page_link":
        return "copy_current_page_link"
    if clean_source == "current_page_content":
        return "select_all_then_copy"
    if clean_source == "clipboard":
        return "use_existing_clipboard"
    return ""


def _desktop_discovered_app_search_payload(
    inputs: Mapping[str, Any],
    decision: Any | None,
) -> dict[str, Any]:
    app_search = inputs.get("app_search_hint")
    if not isinstance(app_search, Mapping):
        return {}
    query = str(app_search.get("query") or "").strip()
    if not query:
        return {}
    payload: dict[str, Any] = {"query": query}
    target = str(app_search.get("target") or "").strip()
    if target:
        payload["target"] = target
    scope = str(app_search.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope
    focus_payload = _decision_step_focus_payload(
        _decision_plan_step(decision, "focus-app-search-field")
    )
    if focus_payload:
        payload["focus"] = focus_payload
    if _decision_plan_has_step(decision, "submit-app-search"):
        payload["submit"] = True
    if _decision_plan_has_step(decision, "confirm-app-search-result"):
        payload["submit"] = True
        payload["submit_action"] = "confirm"
    if _decision_plan_has_step(decision, "select-app-search-result-with-key"):
        payload["select_result"] = "arrow_down"
        payload["result_selection"] = {
            "action": "key_confirm",
            "key": _decision_step_action_payload(
                _decision_plan_step(decision, "select-app-search-result-with-key")
            ),
            "confirm": _decision_step_action_payload(
                _decision_plan_step(decision, "confirm-app-search-result")
            ),
        }
    click_selection = _decision_step_action_payload(
        _decision_plan_step(decision, "select-app-search-result")
    )
    if click_selection:
        payload["result_selection"] = {
            "action": "click",
            **click_selection,
        }
    if _decision_plan_has_step(decision, "verify-desktop-result"):
        payload["verify"] = True
    return payload


def _decision_step_action_payload(step: Any | None) -> dict[str, Any]:
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if not tool_name:
        return {}
    raw_input = getattr(step, "input_preview", {})
    input_preview = dict(raw_input) if isinstance(raw_input, Mapping) else {}
    return {
        "tool": tool_name,
        "input": input_preview,
    }


def _decision_step_focus_payload(step: Any | None) -> dict[str, Any]:
    return _decision_step_action_payload(step)


def _decision_plan_step(decision: Any | None, step_id: str) -> Any | None:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = getattr(tool_plan, "steps", None)
    if not isinstance(steps, Iterable) or isinstance(steps, (str, bytes)):
        return None
    expected = str(step_id or "").strip()
    if not expected:
        return None
    for step in steps:
        if str(getattr(step, "step_id", "") or "").strip() == expected:
            return step
    return None


def _decision_plan_has_step(decision: Any | None, step_id: str) -> bool:
    return _decision_plan_step(decision, step_id) is not None


def _desktop_discovery_capability_hint(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in (
        "app_capability_hint",
        "generic_browser_discovery_hint",
        "generic_music_app_discovery_hint",
        "generic_file_manager_discovery_hint",
        "generic_terminal_app_discovery_hint",
        "generic_communication_app_discovery_hint",
    ):
        value = inputs.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _communication_followup_hint(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("communication_target_hint", "direct_message_hint"):
        target = inputs.get(key)
        if isinstance(target, Mapping):
            return target
    return {}


def _communication_app_query_for_channel(channel: str) -> str:
    clean_channel = str(channel or "").strip()
    if clean_channel == "email":
        return "email"
    if clean_channel in {"message", "chat"}:
        return "chat"
    return ""


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


def planner_replan_request(
    decision: PlannerDecisionSnapshot,
    failure: Mapping[str, Any] | None = None,
    **kwargs: Any,
):
    return task_replan_request_from_failure(decision, failure, **kwargs)


def planner_replan_timeline_event(
    decision: PlannerDecisionSnapshot,
    failure: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    request = task_replan_request_from_failure(decision, failure, **kwargs)
    if request is None:
        return None
    return task_replan_timeline_event(request)


def planner_replan_run_event_payload(
    decision: PlannerDecisionSnapshot,
    failure: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[str, dict[str, Any]] | None:
    request = task_replan_request_from_failure(decision, failure, **kwargs)
    if request is None:
        return None
    return task_replan_run_event_payload(request)


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
    if event_type == "agent.task_core.created":
        task_core = payload.get("task_core") if isinstance(payload.get("task_core"), Mapping) else {}
        workspace = task_core.get("workspace") if isinstance(task_core.get("workspace"), Mapping) else {}
        return str(workspace.get("title") or task_core.get("core_id") or "").strip()
    if event_type in {"agent.task.todo.updated", "agent.task.checkpoint.updated"}:
        return task_core_progress_event_detail(event_type, dict(payload))
    return event_type


def planner_run_event_payloads(
    decision: PlannerDecisionSnapshot | None,
    *,
    runtime_execution_envelope: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if decision is None:
        return []
    execution_envelope = (
        dict(runtime_execution_envelope)
        if isinstance(runtime_execution_envelope, Mapping)
        else runtime_execution_envelope_payload(
            decision,
            full_plan=True,
            metadata=metadata,
        )
    )
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
                "capability_plan": _capability_plan_payload(decision),
                "runtime_execution_envelope": execution_envelope,
                "execution_request_count": len(
                    execution_envelope.get("requests")
                    if isinstance(execution_envelope.get("requests"), list)
                    else []
                ),
                "execution_stage_counts": (
                    execution_envelope.get("runtime_stage_counts")
                    if isinstance(execution_envelope.get("runtime_stage_counts"), Mapping)
                    else {}
                ),
            },
        ),
    ]
    task_core = decision.plan.task_core
    if task_core is not None:
        payloads.append(
            (
                "agent.task_core.created",
                {
                    "source": decision.source,
                    "decision_id": decision.decision_id,
                    "plan_id": decision.plan.plan_id,
                    "core_id": task_core.core_id,
                    "task_core": task_core.model_dump(mode="json"),
                    "workspace_item_count": len(task_core.workspace.items),
                    "todo_count": len(task_core.todos),
                    "checkpoint_count": len(task_core.checkpoints),
                    "replan_signal_count": len(task_core.replan_signals),
                },
            )
        )
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
    if task_core is not None:
        payloads.extend(
            task_core_initial_progress_event_payloads(
                task_core,
                source=decision.source,
                decision_id=decision.decision_id,
                plan_id=decision.plan.plan_id,
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


def _selection_display_tool_names(requests: Iterable[Mapping[str, Any]]) -> list[str]:
    items = _request_list(requests)
    tools: list[str] = []
    index = 0
    while index < len(items):
        request = items[index]
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            index += 1
            continue
        next_request = items[index + 1] if index + 1 < len(items) else None
        if _is_app_focus_or_open(tool_name) and next_request is not None:
            next_tool = str(next_request.get("tool") or "").strip()
            if (
                next_tool in {"app.focus_and_safe_shortcut", "app.open_and_safe_shortcut"}
                and _same_or_unspecified_app(request, next_request)
            ):
                tools.append(next_tool)
                index += 2
                continue
            if (
                next_tool == "desktop.safe_shortcut"
                and _shortcut_action(next_request)
                and _same_or_unspecified_app(request, next_request)
                and not _preceded_by_app_prepare(items, index - 1)
                and not _followed_by_context_transfer_shortcut(items, index + 2)
            ):
                prefix = "app.open" if tool_name in {"app.open", "desktop.open_app"} else "app.focus"
                tools.append(f"{prefix}_and_safe_shortcut")
                index += 2
                continue
        tools.append(tool_name)
        index += 1
    return tools


def _is_app_focus_or_open(tool_name: str) -> bool:
    return tool_name in {"app.open", "desktop.open_app", "app.focus", "desktop.focus_app"}


def _same_or_unspecified_app(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> bool:
    first_app = _request_app_name(first)
    second_app = _request_app_name(second)
    return not first_app or not second_app or first_app == second_app


def _request_app_name(request: Mapping[str, Any]) -> str:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    return str(payload.get("app_name") or "").strip().lower()


def _shortcut_action(request: Mapping[str, Any]) -> str:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    return str(payload.get("action") or "").strip()


def _followed_by_context_transfer_shortcut(
    requests: list[Mapping[str, Any]],
    index: int,
) -> bool:
    if index >= len(requests):
        return False
    request = requests[index]
    if str(request.get("tool") or "").strip() != "desktop.safe_shortcut":
        return False
    return _shortcut_action(request) in {"copy", "paste"}


def _preceded_by_app_prepare(
    requests: list[Mapping[str, Any]],
    index: int,
) -> bool:
    if index < 0 or index >= len(requests):
        return False
    tool_name = str(requests[index].get("tool") or "").strip()
    return _is_app_focus_or_open(tool_name)


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
    capability_plan = getattr(plan, "capability_plan", None)
    plan_items = getattr(capability_plan, "items", None)
    if plan_items:
        return _unique_strings(
            str(getattr(item, "capability_id", "") or "").strip()
            for item in plan_items
        )
    capabilities = getattr(plan, "capabilities", None)
    return _unique_strings(
        str(getattr(capability, "capability_id", "") or "").strip()
        for capability in capabilities or []
    )


def _capability_plan_payload(decision: Any | None) -> dict[str, Any]:
    plan = getattr(decision, "plan", None)
    capability_plan = getattr(plan, "capability_plan", None)
    if capability_plan is None:
        return {}
    if hasattr(capability_plan, "model_dump"):
        return capability_plan.model_dump(mode="json")
    if isinstance(capability_plan, Mapping):
        return dict(capability_plan)
    return {}


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
