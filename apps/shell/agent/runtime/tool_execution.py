"""Tool call execution coordinator for Agent runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    default_desktop_execution_provider_registry,
    desktop_execution_route_allows_provider_execution,
    desktop_execution_route_payload,
    desktop_execution_route_requires_provider,
)
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.event_scopes import (
    runtime_replan_base_event_type as _runtime_replan_base_event_type,
    runtime_replan_request_event_payload as _runtime_replan_event_payload,
    runtime_replan_request_event_type as _runtime_replan_event_type,
)
from apps.shell.agent.runtime.task_progress import append_task_progress_events_for_tool_result
from apps.shell.yachiyo_agent.capability_registry import capability_recovery_tools
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    desktop_execution_policy_mode as _public_desktop_execution_policy_mode,
    desktop_execution_route_decision,
    sandbox_desktop_provider_status,
)
from apps.shell.yachiyo_agent.isolated_provider_session import (
    start_isolated_desktop_provider_session,
)
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode_for_input
from packages.security import redact_api_error_text

_TOOL_REQUEST_TRACE_TEXT_KEYS = (
    "source",
    "planning_reason",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "capability_title",
    "capability_status",
    "capability_reason",
    "core_id",
    "workspace_id",
    "task_id",
    "run_id",
    "run_group_id",
    "group_run_id",
    "group_id",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
    "replan_request_id",
    "replan_trigger",
    "risk_level",
    "policy_reason",
    "target_app_name",
    "target_app_query",
    "target_search_text",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
    "control_action",
    "api_route",
    "diagnostic_route",
)

_TOOL_REQUEST_TRACE_BOOL_KEYS = (
    "requires_observation",
    "requires_post_action_verification",
)

_TOOL_REQUEST_TRACE_LIST_KEYS = (
    "capability_selected_tools",
    "capability_planned_step_ids",
    "replan_triggers",
    "replan_signal_ids",
)

_TOOL_REQUEST_TRACE_MAPPING_KEYS = (
    "followup_target",
    "action_target",
    "observation_evidence",
    "observation_retry",
    "desktop_execution_policy",
    "desktop_execution_route",
    "sandbox_provider",
    "sandbox_desktop_provider",
)

_ARTIFACT_BODY_TEXT_TOOLS = {
    "app.focus_and_safe_type_text",
    "app.open_and_safe_type_text",
    "app.focus_and_type_into_ui_element",
    "app.open_and_type_into_ui_element",
    "desktop.safe_type_text",
    "desktop.type",
    "desktop.type_text",
    "desktop.type_into_ui_element",
}

_ARTIFACT_BODY_SOURCES = {
    "analysis_artifact",
    "analysis_result",
    "artifact",
    "artifact_content",
    "data_analysis",
    "report_artifact",
    "research_artifact",
}

_ARTIFACT_BODY_TEXT_LIMIT = 20000

_DESKTOP_PROVIDER_SESSION_CONTROL_SOURCES = {
    "agent_studio_group_replan_recovery",
    "agent_studio_replan_recovery",
    "yachiyo_chat_replan_recovery",
}

_INPUT_PREVIEW_TRACE_KEYS = (
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "capability_title",
    "capability_status",
    "capability_reason",
    "core_id",
    "workspace_id",
    "task_id",
    "run_id",
    "run_group_id",
    "group_run_id",
    "group_id",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
    "replan_request_id",
    "replan_trigger",
    "risk_level",
    "policy_reason",
    "target_app_name",
    "target_app_query",
    "target_search_text",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
    "requires_observation",
    "requires_post_action_verification",
    "capability_selected_tools",
    "capability_planned_step_ids",
    "replan_triggers",
    "replan_signal_ids",
)

_ARTIFACT_CONTEXT_KEYS = (
    "source",
    "planning_reason",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "step_id",
    "planner_step_id",
    "capability_id",
    "capability_title",
    "capability_status",
    "capability_reason",
    "capability_selected_tools",
    "capability_planned_step_ids",
    "core_id",
    "workspace_id",
    "task_id",
    "run_group_id",
    "group_run_id",
    "group_id",
    "workflow_id",
    "workflow_run_id",
    "workflow_node_id",
    "workflow_node_label",
    "replan_request_id",
    "replan_trigger",
    "risk_level",
    "policy_reason",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
)


def _default_allows_tool(tool_name: str, allowed_tools: list[str]) -> bool:
    return tool_name in set(str(tool or "").strip() for tool in allowed_tools)


def _tool_request_trace_payload(tool_request: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _TOOL_REQUEST_TRACE_TEXT_KEYS:
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in _TOOL_REQUEST_TRACE_BOOL_KEYS:
        value = tool_request.get(key)
        if isinstance(value, bool):
            payload[key] = value
    for key in _TOOL_REQUEST_TRACE_LIST_KEYS:
        values = _string_list(tool_request.get(key))
        if values:
            payload[key] = values
    for key in _TOOL_REQUEST_TRACE_MAPPING_KEYS:
        value = tool_request.get(key)
        if isinstance(value, Mapping) and value:
            payload[key] = dict(value)
    return payload


def _is_desktop_provider_session_start_control(
    tool_name: str,
    tool_request: Mapping[str, Any],
) -> bool:
    control_action = str(tool_request.get("control_action") or "").strip()
    return (
        str(tool_name or "").strip() == "desktop.provider_session.start"
        and control_action == "desktop_provider_session.start"
    )


def _control_action_allows_tool(tool_name: str, tool_request: Mapping[str, Any]) -> bool:
    if not _is_desktop_provider_session_start_control(tool_name, tool_request):
        return False
    source = str(tool_request.get("source") or "").strip()
    if source not in _DESKTOP_PROVIDER_SESSION_CONTROL_SOURCES:
        return False
    return any(
        str(tool_request.get(key) or "").strip()
        for key in ("replan_recovery_action_id", "action_id", "replan_request_id")
    )


def _desktop_provider_session_start_request(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    request: dict[str, Any] = {}
    for key in ("host", "provider_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            request[key] = value
    port = payload.get("port")
    if isinstance(port, int):
        request["port"] = port
    elif isinstance(port, str) and port.strip():
        try:
            request["port"] = int(port.strip())
        except ValueError:
            pass
    tools = _string_list(payload.get("tools")) or _string_list(payload.get("tool_names"))
    if tools:
        request["tools"] = tools
    return request


def _public_desktop_provider_session(session: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "ok",
        "status",
        "running",
        "started",
        "stopped",
        "pid",
        "provider_id",
        "url",
        "source",
        "needed",
        "reason",
    ):
        value = session.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    for key in ("request_ids", "tool_names"):
        values = _string_list(session.get(key))
        if values:
            payload[key] = values
    return payload


def _desktop_provider_session_start_control_result(
    tool_request: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    request = _desktop_provider_session_start_request(payload)
    try:
        session = start_isolated_desktop_provider_session(request)
    except Exception as exc:
        session = {
            "ok": False,
            "status": "start_failed",
            "running": False,
            "error": redact_api_error_text(exc),
            "source": "isolated_provider_session_manager",
        }
    public_session = _public_desktop_provider_session(session)
    if "error" in session:
        public_session["error"] = redact_api_error_text(session.get("error"))
    provider_id = str(public_session.get("provider_id") or "local-isolated-desktop")
    ok = bool(public_session.get("ok", True)) and str(
        public_session.get("status") or ""
    ) != "start_failed"
    status = str(public_session.get("status") or ("running" if ok else "start_failed"))
    return {
        "ok": ok,
        "tool": "desktop.provider_session.start",
        "status": status,
        "control_action": "desktop_provider_session.start",
        "desktop_provider_session": public_session,
        "provider_id": provider_id,
        "running": bool(public_session.get("running")),
        "started": bool(public_session.get("started")),
        "summary": (
            f"Isolated desktop provider is {status}: {provider_id}"
            if ok
            else f"Failed to start isolated desktop provider: {provider_id}"
        ),
        "source": str(tool_request.get("source") or "runtime_tool_request_runner"),
    }


def _desktop_provider_session_control_event(
    tool_result: Mapping[str, Any],
) -> tuple[str, str, dict[str, Any]] | None:
    session = tool_result.get("desktop_provider_session")
    if not isinstance(session, Mapping) or not session:
        return None
    payload = {
        "desktop_provider_session": dict(session),
        "control_action": "desktop_provider_session.start",
        "tool": "desktop.provider_session.start",
    }
    if bool(tool_result.get("ok")) is False or str(session.get("status") or "") == "start_failed":
        return (
            "desktop.provider_session.failed",
            "Isolated desktop provider start failed",
            payload,
        )
    if bool(session.get("started")):
        return (
            "desktop.provider_session.started",
            "Isolated desktop provider started",
            payload,
        )
    if bool(session.get("running")):
        return (
            "desktop.provider_session.ready",
            "Isolated desktop provider already running",
            payload,
        )
    return None


def _input_preview_with_trace_payload(
    input_preview: Any,
    trace_payload: dict[str, Any],
) -> Any:
    return input_preview


def _artifact_context_from_trace_payload(trace_payload: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in _ARTIFACT_CONTEXT_KEYS:
        value = trace_payload.get(key)
        if value in (None, "", [], {}):
            continue
        context[key] = value
    return context


def _artifact_with_context(
    artifact: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not context:
        return artifact
    enriched = dict(artifact)
    for key, value in context.items():
        enriched.setdefault(key, value)
    return enriched


def _event_payload_with_artifact_context(
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not context:
        return payload
    enriched = dict(payload)
    for key, value in context.items():
        enriched.setdefault(key, value)
    artifact = enriched.get("artifact")
    if isinstance(artifact, dict):
        nested_artifact = dict(artifact)
        for key, value in context.items():
            nested_artifact.setdefault(key, value)
        enriched["artifact"] = nested_artifact
    return enriched


def _event_payload_with_trace_context(
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not context:
        return payload
    enriched = dict(payload)
    for key, value in context.items():
        enriched.setdefault(key, value)
    input_preview = enriched.get("input_preview")
    if isinstance(input_preview, dict):
        preview = dict(input_preview)
        for key, value in context.items():
            preview.setdefault(key, value)
        enriched["input_preview"] = preview
    return enriched


def _tool_result_requests_user_recovery(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return bool(
        result.get("permission_error")
        or data.get("permission_error")
        or result.get("blocked_by_runtime_readiness")
        or result.get("blocked_by_app_resolution")
        or result.get("blocked_by_file_resolution")
        or result.get("blocked_by_desktop_execution_policy")
        or result.get("recovery_actions")
        or data.get("recovery_actions")
        or result.get("permission_targets")
        or data.get("permission_targets")
    )


def _desktop_execution_policy_skip_result(
    tool_name: str,
    tool_request: Mapping[str, Any],
    input_preview: Any,
) -> dict[str, Any] | None:
    policy = _desktop_execution_policy_from_request(tool_request)
    policy_mode = _desktop_execution_policy_mode(policy)
    execution_mode = desktop_tool_execution_mode_for_input(
        tool_name,
        input_preview if isinstance(input_preview, Mapping) else {},
    )
    execution_payload = execution_mode.model_dump(mode="json")
    sandbox_required_by_policy = _desktop_execution_policy_requires_sandbox(
        policy,
        execution_payload,
    )
    if policy_mode == "allow" and not sandbox_required_by_policy:
        return None
    if (
        policy_mode == "preview_input"
        and not _desktop_execution_policy_blocks_input_tool(
            tool_name,
            policy,
            execution_payload,
        )
    ):
        return None
    if not (
        bool(execution_mode.foreground_control)
        or bool(execution_mode.keyboard_mouse_capture)
    ):
        return None

    sandbox_provider = sandbox_desktop_provider_status(tool_request)
    route_decision = desktop_execution_route_payload(tool_request) or desktop_execution_route_decision(
        tool_name,
        policy=policy,
        execution_mode=execution_payload,
        metadata=tool_request,
    )
    if desktop_execution_route_allows_provider_execution(route_decision):
        return None
    route_blockers = [
        str(item).strip()
        for item in route_decision.get("blocking_conditions", [])
        if str(item or "").strip()
    ]
    if policy_mode == "allow" and sandbox_required_by_policy:
        blocking_condition = route_blockers[0] if route_blockers else "desktop_execution_sandbox_required"
        status = str(route_decision.get("status") or "provider_required")
    else:
        blocking_condition = (
            "desktop_execution_handoff_required"
            if policy_mode == "handoff"
            else "desktop_execution_preview_required"
        )
        status = "handoff_required" if policy_mode == "handoff" else "preview_required"
    return {
        "ok": False,
        "tool": tool_name,
        "status": status,
        "error": "desktop_execution_policy_blocked",
        "summary": "Desktop foreground execution was blocked by the runtime execution policy.",
        "blocked_by_desktop_execution_policy": True,
        "blocking_condition": blocking_condition,
        "blocking_conditions": [blocking_condition],
        "desktop_execution_policy": policy,
        "desktop_execution_mode": execution_payload,
        "desktop_execution_route": route_decision,
        "execution_mode": str(execution_payload.get("mode") or ""),
        "foreground_control": bool(execution_payload.get("foreground_control")),
        "keyboard_mouse_capture": bool(
            execution_payload.get("keyboard_mouse_capture")
        ),
        "sandbox_recommended": bool(execution_payload.get("sandbox_recommended")),
        "sandbox_provider": sandbox_provider,
        "user_handoff_recommended": policy_mode == "handoff",
        "input_preview": input_preview if isinstance(input_preview, dict) else {},
        "recommended_tools": [
            "screen.capture",
            "desktop.active_window",
            "desktop.ui_elements",
        ],
        "recovery_actions": _desktop_execution_policy_recovery_actions(
            tool_name,
            tool_request,
            policy=policy,
            policy_mode=policy_mode,
            execution_mode=execution_payload,
            sandbox_provider=sandbox_provider,
            route_decision=route_decision,
        ),
        "hint": (
            "Switch the run to supervised_live, continue in Agent Studio, or let the "
            "user perform the foreground step manually."
        ),
    }


def _desktop_execution_policy_requires_sandbox(
    policy: Mapping[str, Any],
    execution_payload: Mapping[str, Any],
) -> bool:
    if not isinstance(policy, Mapping):
        return False
    requires_keyboard_mouse_sandbox = bool(
        policy.get("require_sandbox_for_keyboard_mouse")
    ) and bool(execution_payload.get("keyboard_mouse_capture"))
    avoids_foreground_takeover = bool(
        policy.get("avoid_user_foreground_takeover")
    ) and (
        bool(execution_payload.get("foreground_control"))
        or bool(execution_payload.get("keyboard_mouse_capture"))
    )
    return requires_keyboard_mouse_sandbox or avoids_foreground_takeover


def _tool_request_with_desktop_execution_route(
    tool_name: str,
    tool_request: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(tool_request)
    if desktop_execution_route_payload(payload):
        return payload
    policy = _desktop_execution_policy_from_request(payload)
    if not policy:
        return payload
    raw_input = payload.get("input") if isinstance(payload.get("input"), Mapping) else {}
    execution_mode = desktop_tool_execution_mode_for_input(
        tool_name,
        raw_input,
    ).model_dump(mode="json")
    route_decision = desktop_execution_route_decision(
        tool_name,
        policy=policy,
        execution_mode=execution_mode,
        metadata=payload,
    )
    if route_decision:
        payload["desktop_execution_route"] = dict(route_decision)
        payload.setdefault("sandbox_provider", sandbox_desktop_provider_status(payload))
    return payload


def _desktop_execution_policy_recovery_actions(
    tool_name: str,
    tool_request: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    policy_mode: str,
    execution_mode: Mapping[str, Any],
    sandbox_provider: Mapping[str, Any],
    route_decision: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_input = tool_request.get("input")
    tool_input = dict(raw_input) if isinstance(raw_input, Mapping) else {}
    action_target = tool_request.get("action_target")
    observation_evidence = tool_request.get("observation_evidence")
    observation_retry = tool_request.get("observation_retry")
    supervised_policy = {
        "mode": "supervised_live",
        "allow_live_foreground": True,
        "source": "desktop_execution_policy_recovery",
        "reason": "User selected an Agent Studio supervised live retry.",
    }
    sandbox_policy = {
        "mode": "sandbox_preferred",
        "source": "desktop_execution_policy_recovery",
        "reason": "Prefer a sandbox desktop/session before touching the real foreground desktop.",
    }
    sandbox_blockers = [
        str(item).strip()
        for item in route_decision.get("blocking_conditions", [])
        if str(item or "").strip()
    ] or [
        str(item).strip()
        for item in sandbox_provider.get("blocking_conditions", [])
        if str(item or "").strip()
    ] or ["sandbox_desktop_provider_required"]
    manual_metadata = {
        "runtime_replan_auto_start_eligible": False,
        "runtime_replan_auto_start_reason": "desktop_execution_policy_requires_supervision",
        "runtime_replan_auto_start_blockers": [
            "desktop_execution_policy",
            *(
                ["keyboard_mouse_capture"]
                if bool(execution_mode.get("keyboard_mouse_capture"))
                else []
            ),
            *(
                ["foreground_control"]
                if bool(execution_mode.get("foreground_control"))
                else []
            ),
        ],
        "desktop_execution_policy": supervised_policy,
        "desktop_execution_route": dict(route_decision),
        "blocked_desktop_execution_policy": dict(policy),
        "blocked_desktop_execution_policy_mode": policy_mode,
        "desktop_execution_mode": dict(execution_mode),
    }
    actions: list[dict[str, Any]] = [
        {
            "label": "Inspect active desktop state",
            "tool": "desktop.active_window",
            "input": {},
            "permission_target": "desktop_observation",
            "risk_level": "low",
            "planning_reason": "desktop_execution_policy_observation_recovery",
            "recovery_action_kind": "observe_desktop_state",
            "metadata": {
                "runtime_replan_auto_start_eligible": True,
                "desktop_execution_policy": dict(policy),
                "blocked_tool": tool_name,
            },
        },
        {
            "label": "Inspect visible desktop controls",
            "tool": "desktop.ui_elements",
            "input": {},
            "permission_target": "desktop_observation",
            "risk_level": "low",
            "planning_reason": "desktop_execution_policy_observation_recovery",
            "recovery_action_kind": "observe_desktop_controls",
            "metadata": {
                "runtime_replan_auto_start_eligible": True,
                "desktop_execution_policy": dict(policy),
                "blocked_tool": tool_name,
            },
        },
    ]
    if bool(execution_mode.get("sandbox_recommended")):
        actions.append(
            {
                "label": "Prepare sandbox desktop handoff",
                "tool": "screen.capture",
                "input": {"reason": "sandbox_desktop_handoff"},
                "permission_target": "sandbox_desktop",
                "risk_level": "low",
                "planning_reason": "desktop_execution_policy_sandbox_handoff",
                "recovery_action_kind": "sandbox_desktop_handoff",
                "desktop_execution_policy": sandbox_policy,
                "desktop_execution_route": dict(route_decision),
                "sandbox_provider": dict(sandbox_provider),
                "deferred_continuation": [
                    {
                        "tool": tool_name,
                        "input": tool_input,
                        "desktop_execution_policy": sandbox_policy,
                        "desktop_execution_route": dict(route_decision),
                        "sandbox_provider": dict(sandbox_provider),
                        "planning_reason": "desktop_execution_policy_sandbox_deferred_tool",
                        "source": "desktop_execution_policy_recovery",
                    }
                ],
                "metadata": {
                    "runtime_replan_auto_start_eligible": False,
                    "runtime_replan_auto_start_reason": "sandbox_desktop_handoff_required",
                    "runtime_replan_auto_start_blockers": sandbox_blockers,
                    "desktop_execution_policy": sandbox_policy,
                    "desktop_execution_route": dict(route_decision),
                    "sandbox_provider": dict(sandbox_provider),
                    "blocked_desktop_execution_policy": dict(policy),
                    "blocked_desktop_execution_policy_mode": policy_mode,
                    "desktop_execution_mode": dict(execution_mode),
                    "sandbox_desktop_handoff": True,
                    "sandbox_original_tool": tool_name,
                    "sandbox_original_input": tool_input,
                },
            }
        )
    actions.append(
        {
            "label": "Continue in Agent Studio supervised live",
            "tool": tool_name,
            "input": tool_input,
            "permission_target": "desktop_foreground_execution",
            "risk_level": _desktop_execution_policy_recovery_risk(execution_mode),
            "approval_required": True,
            "planning_reason": "desktop_execution_policy_supervised_live_recovery",
            "recovery_action_kind": "supervised_live_retry",
            "desktop_execution_policy": supervised_policy,
            "metadata": manual_metadata,
        }
    )
    if isinstance(action_target, Mapping) and action_target:
        actions[-1]["action_target"] = dict(action_target)
    if isinstance(observation_evidence, Mapping) and observation_evidence:
        actions[-1]["observation_evidence"] = dict(observation_evidence)
    if isinstance(observation_retry, Mapping) and observation_retry:
        actions[-1]["observation_retry"] = dict(observation_retry)
    return actions


def _desktop_execution_policy_recovery_risk(
    execution_mode: Mapping[str, Any],
) -> str:
    if bool(execution_mode.get("keyboard_mouse_capture")):
        return "high"
    if bool(execution_mode.get("foreground_control")):
        return "medium"
    return "low"


def _desktop_execution_policy_blocks_input_tool(
    tool_name: str,
    policy: Mapping[str, Any],
    execution_mode: Mapping[str, Any],
) -> bool:
    if not bool(execution_mode.get("keyboard_mouse_capture")):
        return False
    clean_tool = str(tool_name or "").strip()
    if clean_tool.startswith("media.") and policy.get("allow_media_control") is not False:
        return False
    return True


def _desktop_execution_policy_from_request(
    tool_request: Mapping[str, Any],
) -> dict[str, Any]:
    for key in (
        "desktop_execution_policy",
        "yachiyo_desktop_execution_policy",
        "desktop_interaction_policy",
    ):
        raw = tool_request.get(key)
        if isinstance(raw, Mapping):
            return dict(raw)
        if isinstance(raw, str) and raw.strip():
            return {"mode": raw.strip()}
    metadata = tool_request.get("metadata")
    if isinstance(metadata, Mapping):
        return _desktop_execution_policy_from_request(metadata)
    return {}


def _desktop_execution_policy_mode(policy: Mapping[str, Any]) -> str:
    return _public_desktop_execution_policy_mode(policy)


def _tool_result_with_runtime_recovery_defaults(
    tool_name: str,
    tool_request: Mapping[str, Any],
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(tool_result, dict):
        return tool_result
    if tool_result.get("approval_required"):
        return tool_result
    if _tool_request_has_runtime_recovery_metadata(tool_request):
        return tool_result
    if tool_result.get("ok") is not False and tool_result.get("verification_failed") is not True:
        return tool_result
    fallback_tools = _runtime_default_replan_fallback_tools(tool_name)
    if not fallback_tools:
        fallback_tools = _runtime_capability_replan_fallback_tools(tool_request)
    recovery_actions = _runtime_default_replan_recovery_actions(
        tool_name,
        raw_input,
        fallback_tools,
    )
    if not fallback_tools and not recovery_actions:
        return tool_result
    enriched = dict(tool_result)
    if fallback_tools:
        enriched["recommended_tools"] = _string_list([
            *_string_list(enriched.get("recommended_tools")),
            *fallback_tools,
        ])
    if recovery_actions:
        enriched["recovery_actions"] = _dedupe_runtime_replan_recovery_actions([
            *_mapping_list(enriched.get("recovery_actions")),
            *recovery_actions,
        ])
    return enriched


def _tool_request_has_runtime_recovery_metadata(tool_request: Mapping[str, Any]) -> bool:
    return bool(
        _string_list(tool_request.get("replan_signal_ids"))
        or _string_list(tool_request.get("replan_triggers"))
        or _string_list(tool_request.get("fallback_tools"))
        or _mapping_list(tool_request.get("recovery_actions"))
        or _first_mapping(tool_request.get("observation_retry"))
        or bool(tool_request.get("requires_observation"))
        or bool(tool_request.get("requires_post_action_verification"))
    )


def _normalized_app_lookup(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


_SELECTED_DESKTOP_APP_NAME = "<selected app from desktop.list_apps>"
_SELECTED_RUNNING_DESKTOP_APP_NAME = "<selected app from desktop.running_apps>"
_DESKTOP_APP_SELECTION_SOURCE = "desktop.list_apps"
_DESKTOP_RUNNING_APP_SELECTION_SOURCE = "desktop.running_apps"
_DESKTOP_APP_SELECTION_SOURCES = {
    _DESKTOP_APP_SELECTION_SOURCE,
    _DESKTOP_RUNNING_APP_SELECTION_SOURCE,
}
_SELECTED_WORKSPACE_FILE_PATH = "<selected file from workspace.list>"
_SELECTED_WORKSPACE_FILES_PATH = "<selected files from workspace.list>"
_SELECTED_WORKSPACE_FILE_PATHS = {
    _SELECTED_WORKSPACE_FILE_PATH,
    _SELECTED_WORKSPACE_FILES_PATH,
}


def _app_lookups_related(left: Any, right: Any) -> bool:
    clean_left = _normalized_app_lookup(left)
    clean_right = _normalized_app_lookup(right)
    if not clean_left or not clean_right:
        return False
    if clean_left == clean_right:
        return True
    shorter, longer = (
        (clean_left, clean_right)
        if len(clean_left) <= len(clean_right)
        else (clean_right, clean_left)
    )
    return f" {shorter} " in f" {longer} "


def _apps_from_list_apps_result(result: dict[str, Any]) -> list[Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    for container in (data, result):
        apps = container.get("apps")
        if isinstance(apps, list):
            return apps
        matches = container.get("matches")
        if isinstance(matches, list):
            return matches
    return []


def _desktop_app_selection_source(value: Any) -> str:
    clean = str(value or "").strip()
    if clean in _DESKTOP_APP_SELECTION_SOURCES:
        return clean
    return ""


def _selected_desktop_app_placeholder_source(app_name: Any) -> str:
    clean = str(app_name or "").strip()
    if clean == _SELECTED_RUNNING_DESKTOP_APP_NAME:
        return _DESKTOP_RUNNING_APP_SELECTION_SOURCE
    if clean == _SELECTED_DESKTOP_APP_NAME:
        return _DESKTOP_APP_SELECTION_SOURCE
    return ""


def _app_match_score(app: dict[str, Any]) -> int | None:
    for key in ("match_score", "score", "app_resolution_score"):
        value = app.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _app_candidate_name(app: Mapping[str, Any]) -> str:
    return str(
        app.get("name")
        or app.get("app_name")
        or app.get("resolved_app_name")
        or ""
    ).strip()


def _app_candidate_path(app: Mapping[str, Any]) -> str:
    return str(app.get("path") or app.get("resolved_app_path") or "").strip()


def _contains_non_ascii(value: Any) -> bool:
    return any(ord(char) > 127 for char in str(value or ""))


def _app_match_is_high_confidence(app: dict[str, Any], query: str) -> bool:
    score = _app_match_score(app)
    if score is not None and score < 80:
        return False
    clean_query = _normalized_app_lookup(query)
    clean_name = _normalized_app_lookup(_app_candidate_name(app))
    if (
        clean_query
        and clean_name
        and clean_query != clean_name
        and _contains_non_ascii(query)
        and clean_name.endswith(clean_query)
    ):
        return False
    return True


def _best_match_from_list_apps_result(result: dict[str, Any]) -> dict[str, Any] | None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    for container in (data, result):
        best_match = container.get("best_match")
        if isinstance(best_match, dict):
            return best_match
        resolution = container.get("resolution")
        if isinstance(resolution, dict) and _app_candidate_name(resolution):
            return {
                "name": _app_candidate_name(resolution),
                "path": _app_candidate_path(resolution),
                "match_score": resolution.get("app_resolution_score"),
                "match_confidence": resolution.get("app_resolution_confidence"),
                "match_reason": resolution.get("app_resolution_reason"),
                "matched_name": resolution.get("app_resolution_matched_name"),
                "matched_name_source": resolution.get("app_resolution_matched_name_source"),
                "matched_capability": resolution.get("app_resolution_matched_capability"),
            }
    return None


def _discovered_app_name_for_query(
    timeline: list[dict[str, Any]],
    query: str,
    *,
    source_tool: str = _DESKTOP_APP_SELECTION_SOURCE,
) -> str:
    clean_query = _normalized_app_lookup(query)
    if not clean_query:
        return ""
    clean_source_tool = _desktop_app_selection_source(source_tool) or _DESKTOP_APP_SELECTION_SOURCE
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        if str(event.get("detail") or "") != clean_source_tool:
            continue
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if (
            clean_source_tool == _DESKTOP_APP_SELECTION_SOURCE
            and not _app_lookups_related(input_preview.get("query"), clean_query)
        ):
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if clean_source_tool == _DESKTOP_RUNNING_APP_SELECTION_SOURCE:
            running_match = _best_running_app_match_for_query(result, query)
            if running_match:
                return _app_candidate_name(running_match)
            continue
        best_match = _best_match_from_list_apps_result(result)
        if best_match is not None and _app_match_is_high_confidence(best_match, query):
            app_name = str(best_match.get("name") or "").strip()
            if app_name:
                return app_name
        discovered_apps = [
            app
            for app in _apps_from_list_apps_result(result)
            if isinstance(app, dict) and _app_candidate_name(app)
        ]
        for app in discovered_apps:
            app_name = _app_candidate_name(app)
            if _normalized_app_lookup(app_name) == clean_query:
                return app_name
        for app in discovered_apps:
            if not _app_match_is_high_confidence(app, query):
                continue
            app_name = _app_candidate_name(app)
            if _app_lookups_related(app_name, clean_query):
                return app_name
        for app in discovered_apps:
            score = _app_match_score(app)
            if score is not None and score >= 80 and _app_match_is_high_confidence(app, query):
                return _app_candidate_name(app)
    return ""


def _latest_selected_app_candidate(
    timeline: list[dict[str, Any]],
    *,
    source_tool: str = _DESKTOP_APP_SELECTION_SOURCE,
) -> dict[str, Any]:
    clean_source_tool = (
        _desktop_app_selection_source(source_tool) or _DESKTOP_APP_SELECTION_SOURCE
    )
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        if str(event.get("detail") or "") != clean_source_tool:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        candidate = _selected_app_candidate_from_result(
            result,
            source_tool=clean_source_tool,
        )
        if candidate:
            return candidate
    return {}


def _selected_app_candidate_from_result(
    result: dict[str, Any],
    *,
    source_tool: str,
) -> dict[str, Any]:
    best_match = _best_match_from_list_apps_result(result)
    if isinstance(best_match, dict) and _app_candidate_name(best_match):
        return best_match
    apps = [
        app
        for app in _apps_from_list_apps_result(result)
        if isinstance(app, dict) and _app_candidate_name(app)
    ]
    if source_tool == _DESKTOP_RUNNING_APP_SELECTION_SOURCE:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        frontmost_name = str(
            data.get("frontmost") or result.get("frontmost") or ""
        ).strip()
        if frontmost_name:
            for app in apps:
                if _normalized_app_lookup(
                    _app_candidate_name(app)
                ) == _normalized_app_lookup(frontmost_name):
                    return {
                        **app,
                        "match_reason": (
                            app.get("match_reason") or "frontmost_running_app"
                        ),
                    }
        for app in apps:
            if bool(app.get("frontmost")):
                return {
                    **app,
                    "match_reason": (
                        app.get("match_reason") or "frontmost_running_app"
                    ),
                }
    if len(apps) == 1:
        return apps[0]
    return {}


def _best_running_app_match_for_query(
    result: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    running_apps = [
        app
        for app in _apps_from_list_apps_result(result)
        if isinstance(app, dict) and _app_candidate_name(app)
    ]
    if not running_apps:
        return {}
    clean_query = _normalized_app_lookup(query)
    for app in running_apps:
        app_name = _app_candidate_name(app)
        if _normalized_app_lookup(app_name) == clean_query:
            return {**app, "match_score": app.get("match_score", 100)}
    installed_candidates = _installed_app_candidates_for_query(query)
    for candidate in installed_candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_name = _app_candidate_name(candidate)
        if not candidate_name or not _app_match_is_high_confidence(dict(candidate), query):
            continue
        for app in running_apps:
            if _app_lookups_related(_app_candidate_name(app), candidate_name):
                return {**dict(candidate), **dict(app), "name": _app_candidate_name(app)}
    for app in running_apps:
        app_name = _app_candidate_name(app)
        if _app_lookups_related(app_name, clean_query):
            return {**app, "match_score": app.get("match_score", 80)}
    return {}


def _installed_app_candidates_for_query(query: str) -> list[dict[str, Any]]:
    try:
        from apps.shell.agent.tools import desktop

        candidates = desktop._installed_app_match_candidates(query)  # type: ignore[attr-defined]
    except Exception:
        return []
    if not isinstance(candidates, list):
        return []
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def _tool_request_with_discovered_app_name(
    tool_request: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    resolution = _tool_request_app_name_resolution(tool_request, timeline)
    return _tool_request_with_app_name_resolution(tool_request, resolution)


def _tool_request_with_app_name_resolution(
    tool_request: dict[str, Any],
    resolution: dict[str, str],
) -> dict[str, Any]:
    if not resolution:
        return tool_request
    tool_name = str(tool_request.get("tool") or "").strip()
    if not _tool_request_input_accepts_app_name_resolution(tool_name):
        return {
            **tool_request,
            "input_resolution": resolution,
        }
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    resolved_input = {
        **raw_input,
        "app_name": str(resolution.get("resolved_app_name") or "").strip(),
    }
    if (
        _selected_desktop_app_placeholder_source(raw_input.get("app_name"))
        or _desktop_app_selection_source(raw_input.get("selection_source"))
    ):
        resolved_input.pop("selection_source", None)
        resolved_input.pop("query", None)
    return {
        **tool_request,
        "input_resolution": resolution,
        "input": resolved_input,
    }


def _tool_request_existing_app_name_resolution(
    tool_request: dict[str, Any],
) -> dict[str, str]:
    resolution = (
        tool_request.get("input_resolution")
        if isinstance(tool_request.get("input_resolution"), dict)
        else {}
    )
    if not resolution:
        return {}
    if (
        str(resolution.get("field") or "").strip() == "app_name"
        or str(resolution.get("resolved_app_name") or "").strip()
    ):
        app_resolution_keys = {
            "field",
            "requested_app_name",
            "resolved_app_name",
            "source_tool",
            "app_resolution_score",
            "app_resolution_confidence",
            "app_resolution_reason",
            "app_resolution_matched_name",
            "app_resolution_matched_name_source",
            "app_resolution_matched_capability",
            "resolved_app_path",
            "tool",
        }
        app_resolution = {
            str(key): str(value)
            for key, value in resolution.items()
            if key in app_resolution_keys and key != "field" and value is not None
        }
        app_resolution["field"] = "app_name"
        return app_resolution
    return {}


def _tool_request_workspace_file_resolution(
    tool_request: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    if not _tool_request_uses_selected_workspace_file(raw_input):
        return {}
    field = _selected_workspace_file_field(raw_input) or "path"
    candidate = _selected_workspace_file_from_timeline(raw_input, timeline)
    if not candidate:
        return {}
    requested_path = str(
        raw_input.get(field)
        or raw_input.get("path")
        or raw_input.get("target_path")
        or _SELECTED_WORKSPACE_FILE_PATH
    ).strip()
    if _tool_request_uses_selected_workspace_files(raw_input):
        candidates = _selected_workspace_files_from_timeline(raw_input, timeline)
        paths = [str(item.get("path") or "").strip() for item in candidates]
        paths = [path for path in paths if path]
        if not paths:
            return {}
        resolution = {
            "field": field,
            "requested_path": requested_path,
            "resolved_path": paths[0],
            "resolved_paths": paths,
            "resolved_file_count": len(paths),
            "source_tool": str(candidates[0].get("source_tool") or "workspace.list").strip(),
        }
        source_path = str(candidates[0].get("source_path") or "").strip()
        if source_path:
            resolution["source_path"] = source_path
        names = [
            str(item.get("name") or "").strip()
            for item in candidates
            if str(item.get("name") or "").strip()
        ]
        if names:
            resolution["resolved_file_names"] = names
            resolution["resolved_file_name"] = names[0]
        selection = str(raw_input.get("selection") or "").strip()
        if selection:
            resolution["selection"] = selection
        return resolution
    resolution = {
        "field": field,
        "requested_path": requested_path,
        "resolved_path": str(candidate.get("path") or "").strip(),
        "source_tool": str(candidate.get("source_tool") or "workspace.list").strip(),
    }
    source_path = str(candidate.get("source_path") or "").strip()
    if source_path:
        resolution["source_path"] = source_path
    entry_name = str(candidate.get("name") or "").strip()
    if entry_name:
        resolution["resolved_file_name"] = entry_name
    selection = str(raw_input.get("selection") or "").strip()
    if selection:
        resolution["selection"] = selection
    return resolution


def _tool_request_with_workspace_file_resolution(
    tool_request: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    if not resolution:
        return tool_request
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    resolved_path = str(resolution.get("resolved_path") or "").strip()
    resolved_paths = [
        str(path or "").strip()
        for path in resolution.get("resolved_paths", [])
        if str(path or "").strip()
    ] if isinstance(resolution.get("resolved_paths"), list) else []
    if not resolved_path and not resolved_paths:
        return tool_request
    field = str(resolution.get("field") or "path").strip() or "path"
    resolved_input = dict(raw_input)
    if resolved_paths:
        resolved_input.pop(field, None)
        resolved_input["paths"] = resolved_paths
    else:
        resolved_input[field] = resolved_path
        if field == "target_path":
            resolved_input.setdefault("path", resolved_path)
    if str(resolved_input.get("path") or "").strip() in _SELECTED_WORKSPACE_FILE_PATHS:
        if resolved_paths:
            resolved_input.pop("path", None)
        else:
            resolved_input["path"] = resolved_path
    if str(resolved_input.get("target_path") or "").strip() in _SELECTED_WORKSPACE_FILE_PATHS:
        if resolved_paths:
            resolved_input.pop("target_path", None)
        else:
            resolved_input["target_path"] = resolved_path
    if str(resolved_input.get("selection_source") or "").strip() == "workspace.list":
        for key in (
            "selection_source",
            "source_scope",
            "source_path",
            "selection",
            "selection_hint",
            "pattern",
            "file_type",
        ):
            resolved_input.pop(key, None)
    existing_resolution = (
        tool_request.get("input_resolution")
        if isinstance(tool_request.get("input_resolution"), dict)
        else {}
    )
    merged_resolution = {**existing_resolution, **resolution}
    if str(existing_resolution.get("resolved_app_name") or "").strip():
        merged_resolution = {
            **existing_resolution,
            "file_field": str(resolution.get("field") or "").strip(),
            "requested_path": str(resolution.get("requested_path") or "").strip(),
            "resolved_path": resolved_path,
            "file_resolution_source_tool": str(resolution.get("source_tool") or "").strip(),
        }
        for key in ("source_path", "resolved_file_name", "selection"):
            value = str(resolution.get(key) or "").strip()
            if value:
                merged_resolution[key] = value
        resolved_names = resolution.get("resolved_file_names")
        if isinstance(resolved_names, list) and resolved_names:
            merged_resolution["resolved_file_names"] = [
                str(name or "").strip() for name in resolved_names if str(name or "").strip()
            ]
        if resolved_paths:
            merged_resolution["resolved_paths"] = resolved_paths
            merged_resolution["resolved_file_count"] = len(resolved_paths)
    return {
        **tool_request,
        "input_resolution": merged_resolution,
        "input": resolved_input,
    }


def _tool_request_uses_selected_workspace_file(raw_input: dict[str, Any]) -> bool:
    if _selected_workspace_file_field(raw_input):
        return True
    if str(raw_input.get("selection_source") or "").strip() != "workspace.list":
        return False
    path_value = str(
        raw_input.get("path") or raw_input.get("target_path") or raw_input.get("file_path") or ""
    ).strip()
    return not path_value or (path_value.startswith("<") and path_value.endswith(">"))


def _selected_workspace_file_field(raw_input: dict[str, Any]) -> str:
    for field in ("path", "target_path", "file_path"):
        if str(raw_input.get(field) or "").strip() in _SELECTED_WORKSPACE_FILE_PATHS:
            return field
    return ""


def _tool_request_uses_selected_workspace_files(raw_input: dict[str, Any]) -> bool:
    field = _selected_workspace_file_field(raw_input)
    if not field:
        return False
    return str(raw_input.get(field) or "").strip() == _SELECTED_WORKSPACE_FILES_PATH


def _tool_request_artifact_body_resolution(
    tool_request: dict[str, Any],
    broker: Any,
    artifacts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    tool_name = str(tool_request.get("tool") or "").strip()
    if tool_name not in _ARTIFACT_BODY_TEXT_TOOLS:
        return {}
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    if str(raw_input.get("text") or "").strip():
        return {}
    body_source = str(raw_input.get("body_source") or "").strip()
    if body_source not in _ARTIFACT_BODY_SOURCES:
        return {}
    artifact_path = _artifact_body_path(raw_input, artifacts)
    if not artifact_path:
        return {}
    content, metadata = _read_broker_text_artifact(broker, artifact_path)
    if not content:
        return {}
    return {
        "_resolved_text": content,
        "field": "text",
        "body_source": body_source,
        "artifact_path": artifact_path,
        "source_tool": _artifact_source_tool(artifact_path, artifacts) or "data.analyze",
        **metadata,
    }


def _tool_request_with_artifact_body_resolution(
    tool_request: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    content = str(resolution.get("_resolved_text") or "")
    if not content:
        return tool_request
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    resolved_input = {**raw_input, "text": content}
    existing_resolution = (
        tool_request.get("input_resolution")
        if isinstance(tool_request.get("input_resolution"), dict)
        else {}
    )
    public_resolution = _public_artifact_body_resolution(resolution)
    if str(existing_resolution.get("resolved_app_name") or "").strip():
        merged_resolution = {
            **existing_resolution,
            "text_field": "text",
            "text_body_source": str(public_resolution.get("body_source") or "").strip(),
            "text_artifact_path": str(public_resolution.get("artifact_path") or "").strip(),
            "text_source_tool": str(public_resolution.get("source_tool") or "").strip(),
        }
        for key in ("resolved_text_bytes", "resolved_text_truncated"):
            value = public_resolution.get(key)
            if value not in (None, "", [], {}):
                merged_resolution[key] = value
    else:
        merged_resolution = {**existing_resolution, **public_resolution}
    return {
        **tool_request,
        "input_resolution": merged_resolution,
        "input": resolved_input,
    }


def _public_artifact_body_resolution(resolution: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in resolution.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }


def _artifact_body_path(
    raw_input: Mapping[str, Any],
    artifacts: list[dict[str, Any]] | None,
) -> str:
    direct_path = str(raw_input.get("artifact_path") or raw_input.get("path") or "").strip()
    if direct_path:
        return direct_path
    for artifact in reversed(artifacts or []):
        if not isinstance(artifact, Mapping):
            continue
        path = str(artifact.get("path") or artifact.get("artifact_path") or "").strip()
        if not path:
            continue
        kind = str(artifact.get("kind") or "").strip().lower()
        mime_type = str(artifact.get("mime_type") or "").strip().lower()
        if kind in {"markdown", "text", "report", "csv"} or mime_type.startswith("text/"):
            return path
    return ""


def _artifact_source_tool(
    artifact_path: str,
    artifacts: list[dict[str, Any]] | None,
) -> str:
    clean_path = str(artifact_path or "").strip()
    if not clean_path:
        return ""
    for artifact in reversed(artifacts or []):
        if not isinstance(artifact, Mapping):
            continue
        path = str(artifact.get("path") or artifact.get("artifact_path") or "").strip()
        if path != clean_path:
            continue
        return str(artifact.get("source_tool") or "").strip()
    return ""


def _read_broker_text_artifact(
    broker: Any,
    artifact_path: str,
) -> tuple[str, dict[str, Any]]:
    root_value = getattr(broker, "artifact_root", None)
    if root_value is None:
        return "", {}
    rel_path = Path(str(artifact_path or "").strip())
    if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
        return "", {}
    root = Path(root_value).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return "", {}
    if not target.is_file():
        return "", {}
    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(content) > _ARTIFACT_BODY_TEXT_LIMIT:
        content = content[:_ARTIFACT_BODY_TEXT_LIMIT].rstrip()
        truncated = True
    metadata: dict[str, Any] = {
        "resolved_text_bytes": len(content.encode("utf-8")),
    }
    if truncated:
        metadata["resolved_text_truncated"] = True
    return content.strip(), metadata


def _selected_workspace_file_from_timeline(
    raw_input: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, str]:
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        source_tool = str(event.get("detail") or "").strip()
        if source_tool not in {"workspace.list", "file.search", "fs.find_files"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if result.get("ok") is False:
            continue
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if not _workspace_file_selection_event_matches(raw_input, input_preview, result):
            continue
        source_path = _workspace_file_source_path(input_preview, result)
        entries = _workspace_file_entries_from_result(result)
        entry = _select_workspace_file_entry(entries, raw_input, source_path)
        if not entry:
            continue
        path = _workspace_file_entry_path(entry, source_path)
        if not path:
            continue
        return {
            "path": path,
            "name": str(entry.get("name") or "").strip(),
            "source_tool": source_tool,
            "source_path": source_path,
        }
    return {}


def _selected_workspace_files_from_timeline(
    raw_input: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> list[dict[str, str]]:
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        source_tool = str(event.get("detail") or "").strip()
        if source_tool not in {"workspace.list", "file.search", "fs.find_files"}:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if result.get("ok") is False:
            continue
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if not _workspace_file_selection_event_matches(raw_input, input_preview, result):
            continue
        source_path = _workspace_file_source_path(input_preview, result)
        entries = _workspace_file_entries_from_result(result)
        selected_entries = _select_workspace_file_entries(entries, raw_input, source_path)
        candidates: list[dict[str, str]] = []
        for entry in selected_entries:
            path = _workspace_file_entry_path(entry, source_path)
            if not path:
                continue
            candidates.append(
                {
                    "path": path,
                    "name": str(entry.get("name") or "").strip(),
                    "source_tool": source_tool,
                    "source_path": source_path,
                }
            )
        if candidates:
            return candidates
    return []


def _workspace_file_selection_event_matches(
    raw_input: dict[str, Any],
    input_preview: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    source_scope = str(
        raw_input.get("source_scope")
        or raw_input.get("source_path")
        or raw_input.get("directory")
        or ""
    ).strip()
    if source_scope:
        event_path = _workspace_file_source_path(input_preview, result)
        if _normalized_workspace_path(event_path) != _normalized_workspace_path(source_scope):
            return False
    pattern = str(raw_input.get("pattern") or "").strip()
    event_pattern = str(input_preview.get("pattern") or "").strip()
    if pattern and event_pattern and pattern != event_pattern:
        return False
    file_type = str(raw_input.get("source_kind") or raw_input.get("file_type") or "").strip()
    event_file_type = str(input_preview.get("file_type") or "").strip()
    if file_type and event_file_type and file_type != event_file_type:
        return False
    return True


def _workspace_file_source_path(
    input_preview: dict[str, Any],
    result: dict[str, Any],
) -> str:
    return str(result.get("path") or input_preview.get("path") or ".").strip() or "."


def _workspace_file_entries_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for container in (result, result.get("data") if isinstance(result.get("data"), dict) else {}):
        if not isinstance(container, dict):
            continue
        for key in ("entries", "files", "matches", "results"):
            raw_entries = container.get(key)
            if not isinstance(raw_entries, list):
                continue
            entries.extend(entry for entry in raw_entries if isinstance(entry, dict))
    return entries


def _select_workspace_file_entry(
    entries: list[dict[str, Any]],
    raw_input: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    if _tool_request_uses_selected_workspace_files(raw_input):
        selected = _select_workspace_file_entries(entries, raw_input, source_path)
        return selected[0] if selected else {}
    files = _workspace_file_entry_files(entries, source_path)
    if not files:
        return {}
    selection = str(raw_input.get("selection") or raw_input.get("selection_hint") or "").casefold()
    if any(token in selection for token in ("最近", "最新", "latest", "newest", "recent")):
        with_mtime = [
            (entry, _workspace_file_entry_mtime(entry))
            for entry in files
            if _workspace_file_entry_mtime(entry) is not None
        ]
        if with_mtime:
            return max(with_mtime, key=lambda item: item[1] or 0)[0]
        return {}
    if any(token in selection for token in ("最后", "last")):
        return files[-1]
    if any(token in selection for token in ("第一个", "第1个", "first", "top")):
        return files[0]
    if len(files) == 1:
        return files[0]
    return {}


def _select_workspace_file_entries(
    entries: list[dict[str, Any]],
    raw_input: dict[str, Any],
    source_path: str,
) -> list[dict[str, Any]]:
    files = _workspace_file_entry_files(entries, source_path)
    if not files:
        return []
    selection = str(raw_input.get("selection") or raw_input.get("selection_hint") or "").casefold()
    if any(token in selection for token in ("所有", "全部", "all", "every", "each")):
        return files
    if any(token in selection for token in ("多个", "多份", "multiple", "several", "比较", "对比", "compare")):
        return files
    return files if _tool_request_uses_selected_workspace_files(raw_input) else []


def _workspace_file_entry_files(
    entries: list[dict[str, Any]],
    source_path: str,
) -> list[dict[str, Any]]:
    files = [
        entry
        for entry in entries
        if _workspace_file_entry_path(entry, source_path)
        and str(entry.get("type") or entry.get("kind") or "file").strip() not in {
            "dir",
            "directory",
        }
    ]
    return files


def _workspace_file_entry_mtime(entry: dict[str, Any]) -> float | None:
    for key in ("mtime", "modified_at", "last_modified", "mtime_ns"):
        value = entry.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _workspace_file_entry_path(entry: dict[str, Any], source_path: str) -> str:
    for key in ("path", "relative_path", "relpath", "display_path"):
        path = str(entry.get(key) or "").strip()
        if path:
            return _normalized_workspace_path(path)
    name = str(entry.get("name") or "").strip()
    if not name:
        return ""
    base = _normalized_workspace_path(source_path)
    if not base or base == ".":
        return name
    return f"{base.rstrip('/')}/{name}"


def _normalized_workspace_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/") or "."


def _tool_request_input_accepts_app_name_resolution(tool_name: str) -> bool:
    clean_tool = str(tool_name or "").strip()
    if clean_tool.startswith("app."):
        return True
    return clean_tool in {
        "desktop.open_app",
        "desktop.focus_app",
        "desktop.show_app",
        "desktop.hide_app",
        "desktop.quit_app",
        "desktop.inspect_app",
        "desktop.list_windows",
        "desktop.windows",
        "desktop.verify",
        "desktop.read_ui",
        "desktop.ui_elements",
        "desktop.open_path_with_app",
        "app.open_path_with_app",
        "media.music_app_open_and_play",
        "media.music_app_control",
    }


def _tool_request_with_open_path_app_input(
    tool_request: dict[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    if tool_name not in {"desktop.open_path_with_app", "app.open_path_with_app"}:
        return tool_request
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    app_name = str(raw_input.get("app_name") or "").strip()
    if not app_name or _selected_desktop_app_placeholder_source(app_name):
        return tool_request
    if _desktop_app_selection_source(raw_input.get("selection_source")):
        return tool_request
    path = str(raw_input.get("path") or raw_input.get("target_path") or "").strip()
    if not path or (path.startswith("<") and path.endswith(">")):
        return tool_request
    return {
        **tool_request,
        "input": {
            "app_name": app_name,
            "path": path,
        },
    }


def _tool_request_with_verification_target(
    tool_request: dict[str, Any],
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    if not target:
        return tool_request
    if str(tool_request.get("tool") or "").strip() != "desktop.active_window":
        return tool_request
    if isinstance(tool_request.get("verification_target"), dict):
        return tool_request
    app_name = str(target.get("app_name") or "").strip()
    if not app_name:
        return tool_request
    return {
        **tool_request,
        "verification_target": {
            "app_name": app_name,
            **(
                {"source_tool": str(target.get("source_tool") or "").strip()}
                if str(target.get("source_tool") or "").strip()
                else {}
            ),
        },
    }


_FOREGROUND_APP_CONTEXT_TOOLS = {
    "desktop.inspect_app",
    "desktop.list_windows",
    "desktop.windows",
    "desktop.read_ui",
    "desktop.ui_elements",
    "desktop.verify",
}


def _tool_request_with_foreground_app_context(
    tool_request: dict[str, Any],
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    if not target:
        return tool_request
    tool_name = str(tool_request.get("tool") or "").strip()
    if tool_name not in _FOREGROUND_APP_CONTEXT_TOOLS:
        return tool_request
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    if str(raw_input.get("app_name") or "").strip():
        return tool_request
    if _desktop_app_selection_source(raw_input.get("selection_source")):
        return tool_request
    app_name = str(target.get("app_name") or "").strip()
    if not app_name:
        return tool_request
    return {
        **tool_request,
        "input": {**raw_input, "app_name": app_name},
    }


def _tool_request_app_name_resolution(
    tool_request: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, str]:
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    raw_app_name = str(raw_input.get("app_name") or "").strip()
    selection_source = _desktop_app_selection_source(raw_input.get("selection_source"))
    selected_app_query = str(raw_input.get("query") or "").strip()
    placeholder_source = _selected_desktop_app_placeholder_source(raw_app_name)
    source_tool = selection_source or placeholder_source or _DESKTOP_APP_SELECTION_SOURCE
    uses_selected_app_placeholder = (
        bool(placeholder_source)
        or bool(selection_source)
    )
    requested_app_name = (
        selected_app_query
        if uses_selected_app_placeholder and selected_app_query
        else raw_app_name
    )
    selected_candidate: dict[str, Any] = {}
    if uses_selected_app_placeholder and not selected_app_query:
        selected_candidate = _latest_selected_app_candidate(
            timeline,
            source_tool=source_tool,
        )
        discovered_app_name = _app_candidate_name(selected_candidate)
    else:
        discovered_app_name = _discovered_app_name_for_query(
            timeline,
            requested_app_name,
            source_tool=source_tool,
        )
    if not discovered_app_name:
        if (
            selection_source == _DESKTOP_APP_SELECTION_SOURCE
            and raw_app_name
            and not placeholder_source
            and (
                not selected_app_query
                or _app_lookups_related(raw_app_name, selected_app_query)
            )
        ):
            return {
                "tool": str(tool_request.get("tool") or "").strip(),
                "field": "app_name",
                "requested_app_name": requested_app_name or raw_app_name,
                "resolved_app_name": raw_app_name,
                "source_tool": selection_source,
                "app_resolution_confidence": "explicit",
                "app_resolution_reason": "explicit_app_name_without_selection_evidence",
            }
        return {}
    if (
        not uses_selected_app_placeholder
        and _normalized_app_lookup(discovered_app_name) == _normalized_app_lookup(
            requested_app_name
        )
    ):
        return {}
    evidence = (
        _discovered_app_best_match_evidence(selected_candidate)
        if selected_candidate
        else _discovered_app_resolution_evidence(
            timeline,
            requested_app_name,
            discovered_app_name,
            source_tool=source_tool,
        )
    )
    if selected_candidate and "app_resolution_reason" not in evidence:
        evidence["app_resolution_reason"] = f"latest_{source_tool}_selection"
    return {
        "tool": str(tool_request.get("tool") or "").strip(),
        "field": "app_name",
        "requested_app_name": requested_app_name,
        "resolved_app_name": discovered_app_name,
        "source_tool": source_tool,
        **evidence,
    }


def _discovered_app_resolution_evidence(
    timeline: list[dict[str, Any]],
    requested_app_name: str,
    resolved_app_name: str,
    *,
    source_tool: str = _DESKTOP_APP_SELECTION_SOURCE,
) -> dict[str, str]:
    clean_requested = _normalized_app_lookup(requested_app_name)
    clean_resolved = _normalized_app_lookup(resolved_app_name)
    if not clean_requested or not clean_resolved:
        return {}
    clean_source_tool = _desktop_app_selection_source(source_tool) or _DESKTOP_APP_SELECTION_SOURCE
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        if str(event.get("detail") or "") != clean_source_tool:
            continue
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if (
            clean_source_tool == _DESKTOP_APP_SELECTION_SOURCE
            and not _app_lookups_related(input_preview.get("query"), clean_requested)
        ):
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        if clean_source_tool == _DESKTOP_RUNNING_APP_SELECTION_SOURCE:
            running_match = _best_running_app_match_for_query(result, requested_app_name)
            if (
                isinstance(running_match, dict)
                and _normalized_app_lookup(_app_candidate_name(running_match)) == clean_resolved
            ):
                return _discovered_app_best_match_evidence(running_match)
            continue
        best_match = _best_match_from_list_apps_result(result)
        if (
            isinstance(best_match, dict)
            and _normalized_app_lookup(_app_candidate_name(best_match)) == clean_resolved
        ):
            return _discovered_app_best_match_evidence(best_match)
        for app in _apps_from_list_apps_result(result):
            if not isinstance(app, dict):
                continue
            if _normalized_app_lookup(_app_candidate_name(app)) != clean_resolved:
                continue
            return _discovered_app_best_match_evidence(app)
    return {}


def _discovered_app_best_match_evidence(app: Mapping[str, Any]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    score = _app_match_score(dict(app))
    if score is not None:
        evidence["app_resolution_score"] = str(score)
    confidence = str(
        app.get("match_confidence")
        or app.get("confidence")
        or app.get("app_resolution_confidence")
        or ""
    ).strip()
    if confidence:
        evidence["app_resolution_confidence"] = confidence
    reason = str(
        app.get("match_reason")
        or app.get("reason")
        or app.get("app_resolution_reason")
        or ""
    ).strip()
    if reason:
        evidence["app_resolution_reason"] = reason
    matched_name = str(
        app.get("matched_name")
        or app.get("app_resolution_matched_name")
        or ""
    ).strip()
    if matched_name:
        evidence["app_resolution_matched_name"] = matched_name
    matched_name_source = str(
        app.get("matched_name_source")
        or app.get("app_resolution_matched_name_source")
        or ""
    ).strip()
    if matched_name_source:
        evidence["app_resolution_matched_name_source"] = matched_name_source
    matched_capability = str(
        app.get("matched_capability")
        or app.get("app_resolution_matched_capability")
        or ""
    ).strip()
    if matched_capability:
        evidence["app_resolution_matched_capability"] = matched_capability
    path = _app_candidate_path(app)
    if path:
        evidence["resolved_app_path"] = path
    return evidence


def _input_preview_with_app_name_resolution(
    input_preview: Any,
    resolution: dict[str, str],
) -> Any:
    if not resolution:
        return input_preview
    preview = dict(input_preview) if isinstance(input_preview, dict) else {}
    requested_app_name = str(resolution.get("requested_app_name") or "").strip()
    resolved_app_name = str(resolution.get("resolved_app_name") or "").strip()
    source_tool = str(resolution.get("source_tool") or "").strip()
    if (
        requested_app_name
        and resolved_app_name
        and _normalized_app_lookup(requested_app_name)
        == _normalized_app_lookup(resolved_app_name)
    ):
        current_app_name = str(preview.get("app_name") or "").strip()
        if (
            not current_app_name
            or _normalized_app_lookup(current_app_name)
            == _normalized_app_lookup(resolved_app_name)
        ):
            preview["app_name"] = resolved_app_name
            return preview
    if resolved_app_name:
        preview.setdefault("app_name", resolved_app_name)
        preview.setdefault("resolved_app_name", resolved_app_name)
    if requested_app_name:
        preview.setdefault("requested_app_name", requested_app_name)
    if source_tool:
        preview.setdefault("app_resolution_source", source_tool)
    for key in (
        "app_resolution_score",
        "app_resolution_confidence",
        "app_resolution_reason",
        "app_resolution_matched_name",
        "app_resolution_matched_name_source",
        "app_resolution_matched_capability",
        "resolved_app_path",
    ):
        value = str(resolution.get(key) or "").strip()
        if value:
            preview.setdefault(key, value)
    return preview


def _tool_event_input_preview(tool_name: str, input_preview: Any) -> Any:
    if str(tool_name or "").strip() not in {"desktop.ui_elements", "desktop.read_ui"}:
        return input_preview
    if not isinstance(input_preview, dict):
        return input_preview
    trace_scope_keys = {
        "app_name",
        "selection_source",
        "app_selection_source",
        "query",
        "requested_app_name",
        "resolved_app_name",
        "resolved_app_path",
        "app_resolution_source",
        "app_resolution_score",
        "app_resolution_confidence",
        "app_resolution_reason",
        "app_resolution_matched_name",
        "app_resolution_matched_name_source",
        "app_resolution_matched_capability",
    }
    if input_preview and all(key in trace_scope_keys for key in input_preview):
        return {}
    return input_preview


def _tool_result_artifact(tool_name: str, tool_result: dict[str, Any]) -> dict[str, Any] | None:
    if not tool_result.get("ok"):
        return None
    if tool_name == "artifact.write":
        return {"kind": "tool_artifact", **tool_result}
    raw_artifact = tool_result.get("artifact")
    if not isinstance(raw_artifact, dict):
        return None
    artifact = {"kind": "tool_artifact", "source_tool": tool_name, **raw_artifact}
    if not artifact.get("source_tool"):
        artifact["source_tool"] = tool_name
    return artifact


def _tool_result_extra_artifacts(
    tool_name: str,
    tool_result: dict[str, Any],
    primary_artifact: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    raw_artifacts = tool_result.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return []
    primary_path = str((primary_artifact or {}).get("path") or "")
    artifacts: list[dict[str, Any]] = []
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            continue
        artifact = {"kind": "tool_artifact", "source_tool": tool_name, **raw_artifact}
        if not artifact.get("source_tool"):
            artifact["source_tool"] = tool_name
        if primary_path and str(artifact.get("path") or "") == primary_path:
            continue
        if artifact not in artifacts:
            artifacts.append(artifact)
    return artifacts


_BROKER_APPROVAL_POLICY_EXCEPTIONS = {
    "file.organize",
    "terminal.run",
    "workspace.write_patch",
}


def _pre_execution_approval_required_result(
    tool_name: str,
    tool_request: Mapping[str, Any],
    broker: Any,
    *,
    approved: bool,
) -> dict[str, Any] | None:
    if approved:
        return None
    request_requires_approval = bool(tool_request.get("approval_required"))
    broker_approvals = getattr(broker, "approvals", None)
    broker_requires_approval = (
        isinstance(broker_approvals, Mapping)
        and bool(broker_approvals.get(tool_name))
        and tool_name not in _BROKER_APPROVAL_POLICY_EXCEPTIONS
    )
    if not request_requires_approval and not broker_requires_approval:
        return None
    policy_reason = str(
        tool_request.get("policy_reason")
        or tool_request.get("approval_reason")
        or (
            "当前工具策略要求人工确认后再执行。"
            if broker_requires_approval
            else "This planned tool request requires approval before execution."
        )
    ).strip()
    result: dict[str, Any] = {
        "ok": False,
        "approval_required": True,
        "tool": tool_name,
        "status": "approval_required",
        "policy_reason": policy_reason,
    }
    for key in ("risk_level", "plugin_id", "approval_id", "step_id", "planner_step_id"):
        value = tool_request.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    return result


class RuntimeToolCallExecutor:
    """Executes one tool call while preserving policy, budget, and event gates."""

    def __init__(
        self,
        *,
        normalize_tool_name: Callable[[Any], str],
        input_preview: Callable[[Any], Any],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        validate_tool_payload: Callable[[str, dict[str, Any]], None],
        limit_tool_result: Callable[[dict[str, Any]], dict[str, Any]],
        timeline_factory: Callable[..., dict[str, Any]],
        tool_call_events: Any,
        trace_events: Any,
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        allows_tool: Callable[[str, list[str]], bool] | None = None,
        desktop_provider_registry: Any | None = None,
    ) -> None:
        self._normalize_tool_name = normalize_tool_name
        self._input_preview = input_preview
        self._run_budget = run_budget
        self._validate_tool_payload = validate_tool_payload
        self._limit_tool_result = limit_tool_result
        self._timeline = timeline_factory
        self._tool_call_events = tool_call_events
        self._trace_events = trace_events
        self._append_run_event = append_run_event
        self._allows_tool = allows_tool or _default_allows_tool
        self._desktop_provider_registry = (
            desktop_provider_registry or default_desktop_execution_provider_registry()
        )

    def execute(
        self,
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: Any,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        approved: bool = False,
        run_id: str = "",
        budget: Any = None,
    ) -> dict[str, Any]:
        tool_name = self._normalize_tool_name(tool_request.get("tool"))
        tool_request = _tool_request_with_desktop_execution_route(tool_name, tool_request)
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        input_preview = self._input_preview(payload)
        input_resolution = (
            tool_request.get("input_resolution")
            if isinstance(tool_request.get("input_resolution"), dict)
            else {}
        )
        trace_payload = _tool_request_trace_payload(tool_request)
        input_preview = _input_preview_with_app_name_resolution(input_preview, input_resolution)
        input_preview = _input_preview_with_trace_payload(input_preview, trace_payload)
        input_preview = _tool_event_input_preview(tool_name, input_preview)
        budget = budget or self._run_budget(run_id, timeline)
        trusted_control_action = _control_action_allows_tool(tool_name, tool_request)
        if not self._allows_tool(tool_name, allowed_tools) and not trusted_control_action:
            budget.claim_tool_call(tool_name)
            timeline.append(
                self._timeline(
                    "agent.tool.denied",
                    tool_name,
                    input_preview=input_preview,
                    **trace_payload,
                )
            )
            self._tool_call_events.denied(
                run_id,
                tool_name,
                input_preview,
                trace=trace_payload,
            )
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
        self._tool_call_events.requested(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
            trace=trace_payload,
        )
        if not trusted_control_action:
            try:
                self._validate_tool_payload(tool_name, payload)
            except AgentRuntimeError as exc:
                self._tool_call_events.failed(
                    run_id,
                    tool_name,
                    input_preview,
                    approved=approved,
                    pre_validation=True,
                    error=exc,
                    trace=trace_payload,
                )
                raise
        runtime_skip = (
            None
            if trusted_control_action
            else _desktop_execution_policy_skip_result(
                tool_name,
                tool_request,
                input_preview,
            )
        )
        if runtime_skip is not None:
            budget.claim_tool_call(tool_name)
            self._tool_call_events.result(
                run_id,
                tool_name,
                input_preview,
                runtime_skip,
                approved=approved,
                trace=trace_payload,
            )
            timeline.append(
                self._timeline(
                    "agent.tool.skipped",
                    tool_name,
                    input_preview=input_preview,
                    result=runtime_skip,
                    **trace_payload,
                )
            )
            if run_id:
                self._append_run_event(
                    run_id,
                    "agent.tool.skipped",
                    {
                        "tool": tool_name,
                        "input_preview": input_preview,
                        "result": runtime_skip,
                        **trace_payload,
                    },
                )
            return runtime_skip
        budget.claim_tool_call(
            tool_name,
            terminal_execution=tool_name in {"terminal.run", "python.run"} and approved,
        )
        self._tool_call_events.started(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
            trace=trace_payload,
        )
        timeline.append(
            self._timeline(
                "agent.tool.started",
                tool_name,
                input_preview=input_preview,
                status="running",
                **trace_payload,
            )
        )
        try:
            tool_result = _pre_execution_approval_required_result(
                tool_name,
                tool_request,
                broker,
                approved=approved,
            )
            if tool_result is None:
                if trusted_control_action:
                    tool_result = _desktop_provider_session_start_control_result(
                        tool_request,
                        payload,
                    )
                else:
                    tool_result = self._desktop_provider_registry.execute_if_routed(
                        tool_name,
                        payload,
                        tool_request=tool_request,
                        broker=broker,
                        approved=approved,
                    )
                if tool_result is None:
                    tool_result = broker.call(tool_name, payload, approved=approved)
        except AgentRuntimeError as exc:
            if not tool_name.startswith("workspace."):
                self._tool_call_events.failed(
                    run_id,
                    tool_name,
                    input_preview,
                    approved=approved,
                    error=exc,
                    trace=trace_payload,
                )
                raise
            terminal_hint = (
                " If the required target is outside the configured workspace, "
                "use terminal.run and wait for approval."
                if "terminal.run" in allowed_tools
                else ""
            )
            tool_result = {
                "ok": False,
                "tool": tool_name,
                "error": redact_api_error_text(exc),
                "hint": (
                    "Workspace tools only accept relative paths within the configured Default Workdir. "
                    "Use a valid relative path and do not retry the same invalid path."
                    f"{terminal_hint}"
                ),
                **(
                    {"suggested_tool": "terminal.run"}
                    if "terminal.run" in allowed_tools
                    else {}
                ),
            }
        tool_result = self._limit_tool_result(tool_result)
        tool_result = _tool_result_with_active_window_verification_target(
            tool_name,
            tool_result,
            (
                tool_request.get("verification_target")
                if isinstance(tool_request.get("verification_target"), dict)
                else {}
            ),
        )
        self._tool_call_events.result(
            run_id,
            tool_name,
            input_preview,
            tool_result,
            approved=approved,
            trace=trace_payload,
        )
        timeline.append(
            self._timeline(
                "agent.tool.call",
                tool_name,
                input_preview=input_preview,
                result=tool_result,
                **trace_payload,
            )
        )
        if run_id:
            self._tool_call_events.agent_tool_call(
                run_id,
                tool_name,
                input_preview,
                tool_result,
                approved=approved,
                trace=trace_payload,
            )
            trace_event = self._trace_events.memory_skill_trace_event(
                tool_name,
                input_preview,
                tool_result,
            )
            if trace_event is not None:
                self._append_run_event(
                    run_id,
                    trace_event["event_type"],
                    _event_payload_with_trace_context(
                        trace_event["payload"],
                        _artifact_context_from_trace_payload(trace_payload),
                    ),
                )
            provider_session_event = _desktop_provider_session_control_event(tool_result)
            if provider_session_event is not None:
                event_type, detail, event_payload = provider_session_event
                event_payload = _event_payload_with_trace_context(event_payload, trace_payload)
                timeline.append(self._timeline(event_type, detail, **event_payload))
                self._append_run_event(run_id, event_type, event_payload)
        artifact = _tool_result_artifact(tool_name, tool_result)
        extra_artifacts = _tool_result_extra_artifacts(tool_name, tool_result, artifact)
        artifact_context = _artifact_context_from_trace_payload(trace_payload)
        if artifact is not None:
            artifact = _artifact_with_context(artifact, artifact_context)
        extra_artifacts = [
            _artifact_with_context(extra_artifact, artifact_context)
            for extra_artifact in extra_artifacts
        ]
        if artifact is not None and artifacts is not None:
            if artifact not in artifacts:
                artifacts.append(artifact)
        for extra_artifact in extra_artifacts:
            if artifacts is not None and extra_artifact not in artifacts:
                artifacts.append(extra_artifact)
        if artifact is not None and run_id:
            self._append_run_event(
                run_id,
                "artifact.created",
                _event_payload_with_artifact_context(
                    self._trace_events.artifact_created_payload(
                        tool_result,
                        run_id=run_id,
                        source_tool=tool_name,
                    ),
                    artifact_context,
                ),
            )
        if run_id:
            for extra_artifact in extra_artifacts:
                self._append_run_event(
                    run_id,
                    "artifact.created",
                    _event_payload_with_artifact_context(
                        self._trace_events.artifact_created_payload(
                            {"ok": True, "artifact": extra_artifact},
                            run_id=run_id,
                            source_tool=tool_name,
                        ),
                        artifact_context,
                    ),
                )
        return tool_result


class RuntimeToolRequestRunner:
    """Runs model-requested tools while preserving pause and projection behavior."""

    def __init__(
        self,
        *,
        normalize_tool_name: Callable[[Any], str],
        input_preview: Callable[[Any], Any],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        user_goal_from_messages: Callable[[list[dict[str, Any]]], str],
        goal_disallows_tool: Callable[[str, str], str],
        timeline_factory: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        tool_loop_projection: Any,
        pending_approval_builder: Any,
        call_agent_tool: Callable[..., dict[str, Any]],
    ) -> None:
        self._normalize_tool_name = normalize_tool_name
        self._input_preview = input_preview
        self._run_budget = run_budget
        self._user_goal_from_messages = user_goal_from_messages
        self._goal_disallows_tool = goal_disallows_tool
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._tool_loop_projection = tool_loop_projection
        self._pending_approval_builder = pending_approval_builder
        self._call_agent_tool = call_agent_tool

    def run(
        self,
        tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        next_iteration: int,
        run_id: str = "",
        budget: Any = None,
    ) -> None:
        budget = budget or self._run_budget(run_id, timeline)
        user_goal = self._user_goal_from_messages(messages)
        foreground_readiness_blocker: dict[str, Any] | None = None
        active_window_verification_target: dict[str, Any] | None = None
        for index, tool_request in enumerate(tool_requests):
            app_name_resolution = _tool_request_existing_app_name_resolution(tool_request)
            if not app_name_resolution:
                app_name_resolution = _tool_request_app_name_resolution(tool_request, timeline)
            tool_request = _tool_request_with_app_name_resolution(
                tool_request,
                app_name_resolution,
            )
            file_resolution = _tool_request_workspace_file_resolution(tool_request, timeline)
            tool_request = _tool_request_with_workspace_file_resolution(
                tool_request,
                file_resolution,
            )
            artifact_body_resolution = _tool_request_artifact_body_resolution(
                tool_request,
                broker,
                artifacts,
            )
            tool_request = _tool_request_with_artifact_body_resolution(
                tool_request,
                artifact_body_resolution,
            )
            artifact_body_resolution = _public_artifact_body_resolution(
                artifact_body_resolution,
            )
            tool_name = self._normalize_tool_name(tool_request.get("tool"))
            tool_request = _tool_request_with_verification_target(
                tool_request,
                active_window_verification_target,
            )
            tool_request = _tool_request_with_foreground_app_context(
                tool_request,
                active_window_verification_target,
            )
            tool_request = _tool_request_with_open_path_app_input(tool_request, tool_name)
            tool_request = _tool_request_with_desktop_execution_route(tool_name, tool_request)
            raw_input = (
                tool_request.get("input")
                if isinstance(tool_request.get("input"), dict)
                else {}
            )
            for resolution in (app_name_resolution, file_resolution, artifact_body_resolution):
                if not resolution:
                    continue
                resolution_payload = {**resolution, "tool": tool_name}
                timeline.append(
                    self._timeline(
                        "agent.tool.input_resolved",
                        tool_name,
                        **resolution_payload,
                    )
                )
                if run_id:
                    self._append_run_event(
                        run_id,
                        "agent.tool.input_resolved",
                        resolution_payload,
                    )
            input_preview = _input_preview_with_app_name_resolution(
                self._input_preview(raw_input),
                app_name_resolution,
            )
            trace_payload = _tool_request_trace_payload(tool_request)
            input_preview = _input_preview_with_trace_payload(input_preview, trace_payload)
            input_preview = _tool_event_input_preview(tool_name, input_preview)
            runtime_skip = _desktop_execution_policy_skip_result(
                tool_name,
                tool_request,
                input_preview,
            )
            runtime_skip = runtime_skip or _unresolved_discovered_app_skip_result(
                tool_name,
                raw_input,
                app_name_resolution,
            )
            runtime_skip = runtime_skip or _unresolved_workspace_file_skip_result(
                tool_name,
                raw_input,
                file_resolution,
            )
            provider_route_required = desktop_execution_route_requires_provider(
                desktop_execution_route_payload(tool_request)
            )
            if not provider_route_required and not _broker_requires_approval(broker, tool_name):
                runtime_skip = runtime_skip or _runtime_readiness_skip_result(
                    tool_name,
                    raw_input,
                    foreground_readiness_blocker,
                )
            if runtime_skip is not None:
                budget.claim_tool_call(tool_name)
                timeline.append(
                    self._timeline(
                        "agent.tool.skipped",
                        tool_name,
                        input_preview=input_preview,
                        result=runtime_skip,
                        **trace_payload,
                    )
                )
                if run_id:
                    self._append_run_event(
                        run_id,
                        "agent.tool.skipped",
                        {
                            "tool": tool_name,
                            "input_preview": input_preview,
                            "result": runtime_skip,
                            **trace_payload,
                        },
                    )
                self._append_tool_result_progress(
                    tool_request,
                    tool_name=tool_name,
                    tool_event_type="agent.tool.skipped",
                    tool_result=runtime_skip,
                    timeline=timeline,
                    run_id=run_id,
                )
                self._tool_loop_projection.append_tool_result_message(
                    messages,
                    {**tool_request, "tool": tool_name},
                    runtime_skip,
                )
                if _tool_result_requests_user_recovery(runtime_skip):
                    break
                continue
            goal_block_reason = self._goal_disallows_tool(user_goal, tool_name)
            if goal_block_reason:
                budget.claim_tool_call(tool_name)
                tool_result = {
                    "ok": False,
                    "blocked_by_user_goal": True,
                    "tool": tool_name,
                    "error": goal_block_reason,
                    "hint": (
                        "Do not ask for approval. Continue with an inline answer "
                        "that follows the user's stated constraint."
                    ),
                }
                timeline.append(
                    self._timeline(
                        "agent.tool.skipped",
                        tool_name,
                        input_preview=input_preview,
                        result=tool_result,
                        **trace_payload,
                    )
                )
                if run_id:
                    self._append_run_event(
                        run_id,
                        "agent.tool.skipped",
                        {
                            "tool": tool_name,
                            "input_preview": input_preview,
                            "result": tool_result,
                            **trace_payload,
                        },
                    )
                self._append_tool_result_progress(
                    tool_request,
                    tool_name=tool_name,
                    tool_event_type="agent.tool.skipped",
                    tool_result=tool_result,
                    timeline=timeline,
                    run_id=run_id,
                )
                self._tool_loop_projection.append_tool_result_message(
                    messages,
                    {**tool_request, "tool": tool_name},
                    tool_result,
                )
                continue
            tool_result = self._call_agent_tool(
                tool_request,
                allowed_tools,
                broker,
                timeline,
                artifacts=artifacts,
                run_id=run_id,
                budget=budget,
            )
            if tool_result.get("approval_required"):
                self._append_tool_result_progress(
                    tool_request,
                    tool_name=tool_name,
                    tool_event_type="agent.tool.call",
                    tool_result=tool_result,
                    timeline=timeline,
                    run_id=run_id,
                )
                pending_approval = self._pending_approval_builder.build(
                    tool_request,
                    messages=messages,
                    next_iteration=next_iteration,
                    remaining_tool_requests=tool_requests[index + 1 :],
                )
                for key in ("risk_level", "policy_reason", "plugin_id"):
                    value = str(tool_result.get(key) or "").strip()
                    if value:
                        pending_approval[key] = value
                raise AgentApprovalRequired(pending_approval)
            tool_result = _tool_result_with_runtime_recovery_defaults(
                tool_name,
                tool_request,
                raw_input,
                tool_result,
            )
            fatal_failure = self._tool_loop_projection.fatal_failure_detail(
                tool_name,
                tool_request,
                tool_result,
            )
            if fatal_failure:
                timeline.append(
                    self._timeline(
                        "agent.tool.failed",
                        tool_name,
                        input_preview=input_preview,
                        result=tool_result,
                        status="failed",
                        **trace_payload,
                    )
                )
                self._append_tool_result_progress(
                    tool_request,
                    tool_name=tool_name,
                    tool_event_type="agent.tool.failed",
                    tool_result=tool_result,
                    timeline=timeline,
                    run_id=run_id,
                )
                raise AgentRuntimeError(fatal_failure)
            self._tool_loop_projection.append_tool_result_message(
                messages,
                tool_request,
                tool_result,
            )
            self._append_tool_result_progress(
                tool_request,
                tool_name=tool_name,
                tool_event_type="agent.tool.call",
                tool_result=tool_result,
                timeline=timeline,
                run_id=run_id,
            )
            previous_readiness_blocker = foreground_readiness_blocker
            next_readiness_blocker = _updated_foreground_readiness_blocker(
                foreground_readiness_blocker,
                tool_name,
                raw_input,
                tool_result,
            )
            if previous_readiness_blocker is not None and next_readiness_blocker is None:
                recovered_payload = _foreground_readiness_recovered_payload(
                    previous_readiness_blocker,
                    tool_name,
                    input_preview,
                    tool_result,
                )
                timeline.append(
                    self._timeline(
                        "agent.desktop.readiness_recovered",
                        tool_name,
                        **recovered_payload,
                    )
                )
                if run_id:
                    self._append_run_event(
                        run_id,
                        "agent.desktop.readiness_recovered",
                        recovered_payload,
                    )
            foreground_readiness_blocker = next_readiness_blocker
            if _tool_result_requests_user_recovery(tool_result):
                if _remaining_request_can_handle_foreground_readiness(
                    foreground_readiness_blocker,
                    tool_requests[index + 1 :],
                ):
                    continue
                break
            if tool_name == "desktop.active_window":
                active_window_verification_target = None
            else:
                next_active_window_target = _active_window_target_from_tool_result(
                    tool_name,
                    raw_input,
                    tool_result,
                )
                if next_active_window_target is not None:
                    active_window_verification_target = next_active_window_target

    def _append_tool_result_progress(
        self,
        tool_request: dict[str, Any],
        *,
        tool_name: str,
        tool_event_type: str,
        tool_result: dict[str, Any],
        timeline: list[dict[str, Any]],
        run_id: str,
    ) -> None:
        traced_request = {**tool_request, "tool": tool_name}
        tool_event = {
            "event": tool_event_type,
            "detail": tool_name,
            "result": tool_result,
        }
        append_task_progress_events_for_tool_result(
            tool_request=traced_request,
            tool_event=tool_event,
            timeline=timeline,
            timeline_factory=self._timeline,
            append_run_event=self._append_run_event,
            run_id=run_id,
        )
        append_replan_request_event_for_tool_result(
            tool_request=traced_request,
            tool_event=tool_event,
            timeline=timeline,
            timeline_factory=self._timeline,
            append_run_event=self._append_run_event,
            run_id=run_id,
        )


def append_replan_request_event_for_tool_result(
    *,
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    timeline_factory: Callable[..., dict[str, Any]],
    append_run_event: Callable[[str, str, dict[str, Any]], Any] | None = None,
    run_id: str = "",
) -> None:
    payload = _runtime_replan_request_payload_for_tool_result(
        tool_request,
        tool_event,
        run_id=run_id,
    )
    if not payload or _runtime_replan_request_exists(timeline, payload):
        return
    event_type = _runtime_replan_event_type(payload)
    event_payload = _runtime_replan_event_payload(payload, event_type)
    detail = (
        str(payload.get("reason") or "").strip()
        or str(payload.get("failure_detail") or "").strip()
        or str(payload.get("trigger") or "replan requested")
    )
    timeline.append(
        timeline_factory(
            event_type,
            detail,
            status="requested",
            source="runtime_tool_request_runner",
            decision_id=str(payload.get("decision_id") or ""),
            plan_id=str(payload.get("plan_id") or ""),
            **_runtime_replan_context_payload(event_payload),
            payload=event_payload,
        )
    )
    if run_id and append_run_event is not None:
        append_run_event(run_id, event_type, event_payload)


def _runtime_replan_request_payload_for_tool_result(
    tool_request: Mapping[str, Any],
    tool_event: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    result = _runtime_replan_tool_event_result(tool_event)
    if not _tool_event_requests_runtime_replan(tool_event, result):
        return {}
    replan_signal_ids = _string_list(tool_request.get("replan_signal_ids"))
    replan_triggers = _string_list(tool_request.get("replan_triggers"))
    parent_replan_request_id = str(tool_request.get("replan_request_id") or "").strip()
    request_fallback_tools = _string_list(tool_request.get("fallback_tools"))
    fallback_tools = _runtime_replan_fallback_tools(tool_request, result)
    user_recovery_requested = _tool_result_requests_user_recovery(result)
    if not (
        replan_signal_ids
        or replan_triggers
        or parent_replan_request_id
        or request_fallback_tools
        or fallback_tools
        or user_recovery_requested
        or bool(tool_request.get("requires_observation"))
        or bool(tool_request.get("requires_post_action_verification"))
    ):
        return {}

    trigger = _runtime_replan_trigger(tool_event, result, replan_triggers)
    source_step_id = str(
        tool_request.get("step_id") or tool_request.get("planner_step_id") or ""
    ).strip()
    source_tool_name = str(
        tool_request.get("tool") or tool_request.get("tool_name") or tool_event.get("detail") or ""
    ).strip()
    failure_event_type = str(tool_event.get("event") or tool_event.get("event_type") or "").strip()
    failure_detail = _runtime_replan_failure_detail(tool_event, result)
    request_id = _runtime_replan_request_id(
        decision_id=str(tool_request.get("decision_id") or ""),
        plan_id=str(tool_request.get("plan_id") or ""),
        source_step_id=source_step_id,
        source_tool_name=source_tool_name,
        trigger=trigger,
    )
    input_preview = _runtime_replan_input_preview(tool_request)
    result_preview = _runtime_replan_result_preview(result)
    payload: dict[str, Any] = {
        "request_id": request_id,
        "trigger": trigger,
        "status": "requested",
        "run_id": run_id or str(tool_request.get("run_id") or ""),
        "task_id": str(tool_request.get("task_id") or ""),
        "decision_id": str(tool_request.get("decision_id") or ""),
        "plan_id": str(tool_request.get("plan_id") or ""),
        "core_id": str(tool_request.get("core_id") or ""),
        "workspace_id": str(tool_request.get("workspace_id") or ""),
        "source_step_id": source_step_id,
        "source_tool_name": source_tool_name,
        "target_capability_id": str(
            tool_request.get("target_capability_id") or tool_request.get("capability_id") or ""
        ),
        "input_preview": input_preview,
        "failure_event_type": failure_event_type,
        "failure_detail": failure_detail,
        "fallback_tools": fallback_tools,
        "replan_signal_ids": replan_signal_ids,
        "replan_triggers": replan_triggers,
        "reason": "Runtime requested a replan after a failed or unverified step.",
        "source": "runtime_tool_request_runner",
        "metadata": {
            "input_preview": input_preview,
            "result_preview": result_preview,
            "runtime_stage": str(tool_request.get("runtime_stage") or ""),
            "runtime_role": str(tool_request.get("runtime_role") or ""),
        },
    }
    _runtime_replan_enrich_recovery_context(
        payload,
        tool_request,
        result,
        trigger=trigger,
        source_step_id=source_step_id,
        source_tool_name=source_tool_name,
        input_preview=input_preview,
        result_preview=result_preview,
        failure_detail=failure_detail,
    )
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    recovery_actions = metadata.get("recovery_actions")
    if isinstance(recovery_actions, list) and recovery_actions:
        payload["recovery_actions"] = list(recovery_actions)
    for key in (
        "run_group_id",
        "group_run_id",
        "group_id",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        value = str(tool_request.get(key) or "").strip()
        if value:
            payload[key] = value
    return payload


def _tool_event_requests_runtime_replan(
    tool_event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    if result.get("approval_required") or tool_event.get("approval_required"):
        return False
    if result.get("verification_failed") is True or tool_event.get("verification_failed") is True:
        return True
    if result.get("ok") is False:
        return True
    status = str(tool_event.get("status") or result.get("status") or "").strip().lower()
    if status in {"failed", "failure", "error", "unavailable", "rejected", "cancelled"}:
        return True
    event_type = str(tool_event.get("event") or tool_event.get("event_type") or "").strip().lower()
    return event_type.endswith(".failed") or event_type.endswith("_failed")


def _runtime_replan_tool_event_result(tool_event: Mapping[str, Any]) -> dict[str, Any]:
    raw_result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
    result = dict(raw_result)
    if tool_event.get("verification_failed") is True:
        result["verification_failed"] = True
    return result


def _runtime_replan_trigger(
    tool_event: Mapping[str, Any],
    result: Mapping[str, Any],
    replan_triggers: list[str],
) -> str:
    if result.get("verification_failed"):
        return "verification_failed"
    event_text = " ".join(
        str(value or "").lower()
        for value in (
            tool_event.get("event"),
            tool_event.get("status"),
            result.get("status"),
            result.get("error"),
            result.get("blocking_condition"),
        )
    )
    if "unavailable" in event_text or "not_found" in event_text:
        return "tool_unavailable"
    return replan_triggers[0] if replan_triggers else "tool_failure"


def _runtime_replan_failure_detail(
    tool_event: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    for value in (
        result.get("error"),
        result.get("hint"),
        result.get("summary"),
        tool_event.get("detail"),
        result.get("status"),
        tool_event.get("status"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "tool result failed"


def _runtime_replan_fallback_tools(
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    tool_name = str(
        tool_request.get("tool") or tool_request.get("tool_name") or ""
    ).strip()
    tools = [
        *_string_list(tool_request.get("fallback_tools")),
        *_string_list(result.get("suggested_tool")),
        *_string_list(result.get("recommended_tools")),
    ]
    observation_retry_tool = _runtime_observation_retry_tool(
        _first_mapping(
            tool_request.get("observation_retry"),
            result.get("observation_retry"),
            data.get("observation_retry"),
        )
    )
    if observation_retry_tool:
        tools.append(observation_retry_tool)
    recovery_actions = result.get("recovery_actions")
    if isinstance(recovery_actions, list):
        for action in recovery_actions:
            if isinstance(action, Mapping):
                tools.extend(_string_list(action.get("tool")))
    if not _string_list(tools):
        if _runtime_focus_unverified_target_app(tool_request, result):
            tools.extend(["app.open", "desktop.active_window"])
    if not _string_list(tools):
        tools.extend(_runtime_default_replan_fallback_tools(tool_name))
    if not _string_list(tools):
        tools.extend(_runtime_capability_replan_fallback_tools(tool_request))
    return _string_list(tools)


def _runtime_capability_replan_fallback_tools(
    tool_request: Mapping[str, Any],
) -> list[str]:
    capability_id = str(
        tool_request.get("target_capability_id") or tool_request.get("capability_id") or ""
    ).strip()
    return capability_recovery_tools(capability_id)


def _runtime_default_replan_fallback_tools(tool_name: str) -> list[str]:
    clean_tool = str(tool_name or "").strip()
    if clean_tool in {
        "app.open",
        "desktop.open_app",
        "media.music_app_open_and_play",
        "media.apple_music_open_and_play",
    }:
        return ["desktop.list_apps", "app.open", "desktop.active_window"]
    if clean_tool in {
        "app.focus",
        "desktop.focus_app",
        "app.focus_window",
        "app.show",
        "media.music_app_control",
        "media.system_control",
    }:
        return [
            "desktop.running_apps",
            "app.open",
            "desktop.active_window",
            "screen.capture",
        ]
    if clean_tool in {
        "desktop.active_window",
        "desktop.running_apps",
        "desktop.windows",
        "desktop.list_windows",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.verify",
        "screen.capture",
    }:
        return ["desktop.permissions", "screen.capture"]
    if clean_tool.startswith(("app.open_and_", "app.focus_and_")):
        return ["desktop.active_window", "desktop.ui_elements", "screen.capture"]
    if clean_tool in _FOREGROUND_READINESS_GATED_TOOLS:
        return ["desktop.active_window", "desktop.ui_elements", "screen.capture"]
    return []


def _runtime_default_replan_recovery_actions(
    tool_name: str,
    raw_input: Mapping[str, Any],
    fallback_tools: list[str],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    app_name = str(
        raw_input.get("app_name") or raw_input.get("target_app_name") or ""
    ).strip()
    query = str(raw_input.get("query") or raw_input.get("app_query") or app_name).strip()
    for fallback_tool in fallback_tools:
        action_input = _runtime_default_recovery_input(
            fallback_tool,
            raw_input,
            app_name=app_name,
            query=query,
        )
        if action_input is None:
            continue
        risk_level = _runtime_default_recovery_risk_level(fallback_tool)
        approval_required = _runtime_default_recovery_approval_required(fallback_tool)
        action: dict[str, Any] = {
            "label": _runtime_default_recovery_label(fallback_tool),
            "tool": fallback_tool,
            "input": action_input,
            "permission_target": _runtime_default_recovery_permission_target(
                fallback_tool
            ),
            "risk_level": risk_level,
            "observation_retry": {
                "tool": fallback_tool,
                "input": action_input,
                "reason": "tool_failure",
                "source_tool": tool_name,
            },
        }
        if approval_required:
            action["approval_required"] = True
        actions.append(
            action
        )
    return actions


def _runtime_default_recovery_input(
    fallback_tool: str,
    raw_input: Mapping[str, Any],
    *,
    app_name: str,
    query: str,
) -> dict[str, Any] | None:
    if fallback_tool == "desktop.list_apps":
        return {"query": query, "limit": 20} if query else {"limit": 20}
    if fallback_tool == "desktop.running_apps":
        return {}
    if fallback_tool == "browser.current_page":
        return {}
    if fallback_tool in {"workspace.read", "fs.read_file", "file.read"}:
        path = str(
            raw_input.get("path")
            or raw_input.get("file_path")
            or raw_input.get("source_path")
            or raw_input.get("data_source_hint")
            or ""
        ).strip()
        return {"path": path} if path else None
    if fallback_tool in {"app.open", "desktop.open_app", "app.focus", "desktop.focus_app"}:
        return {"app_name": app_name} if app_name else None
    if fallback_tool == "desktop.active_window":
        return {}
    if fallback_tool in {"desktop.ui_elements", "desktop.read_ui"}:
        payload: dict[str, Any] = {"limit": raw_input.get("limit", 80)}
        if app_name:
            payload["app_name"] = app_name
        role_filter = str(raw_input.get("role_filter") or "").strip()
        if role_filter:
            payload["role_filter"] = role_filter
        return payload
    if fallback_tool == "screen.capture":
        return {"reason": "recover failed desktop tool"}
    if fallback_tool == "desktop.permissions":
        return {}
    if fallback_tool == "python.run":
        code = _runtime_default_python_recovery_code(raw_input)
        return {"code": code} if code else None
    if fallback_tool == "terminal.run":
        command = _runtime_default_terminal_recovery_command(raw_input)
        return {"command": command} if command else None
    return None


def _runtime_default_python_recovery_code(raw_input: Mapping[str, Any]) -> str:
    explicit_code = _runtime_default_recovery_text_value(
        raw_input,
        "code",
        "python_code",
        "script",
    )
    if explicit_code:
        return explicit_code
    path = _runtime_default_recovery_text_value(
        raw_input,
        "path",
        "file_path",
        "source_path",
        "data_source_hint",
    )
    if not path:
        return ""
    return "\n".join(
        [
            "from pathlib import Path",
            "import pandas as pd",
            "",
            f"path = Path({path!r})",
            "suffix = path.suffix.lower()",
            "if suffix == '.csv':",
            "    df = pd.read_csv(path)",
            "elif suffix in {'.xlsx', '.xls'}:",
            "    df = pd.read_excel(path)",
            "elif suffix == '.json':",
            "    df = pd.read_json(path)",
            "else:",
            "    df = pd.read_csv(path)",
            "print('rows:', len(df), 'columns:', len(df.columns))",
            "print(df.head(20).to_string(index=False))",
            "print(df.describe(include='all').to_string())",
        ]
    )


def _runtime_default_terminal_recovery_command(raw_input: Mapping[str, Any]) -> str:
    return _runtime_default_recovery_text_value(
        raw_input,
        "command",
        "cmd",
        "shell_command",
    )


def _runtime_default_recovery_text_value(
    payload: Mapping[str, Any],
    *keys: str,
) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _runtime_default_recovery_label(tool_name: str) -> str:
    return {
        "desktop.list_apps": "Discover installed apps",
        "desktop.running_apps": "Inspect running apps",
        "app.open": "Open target app",
        "desktop.open_app": "Open target app",
        "desktop.active_window": "Observe active window",
        "desktop.ui_elements": "Inspect foreground UI",
        "desktop.read_ui": "Inspect foreground UI",
        "screen.capture": "Capture screen",
        "desktop.permissions": "Check desktop permissions",
        "python.run": "Run Python analysis fallback",
        "terminal.run": "Run terminal fallback",
    }.get(tool_name, "Run recovery tool")


def _runtime_default_recovery_permission_target(tool_name: str) -> str:
    if tool_name == "desktop.list_apps":
        return "app_discovery"
    if tool_name == "desktop.permissions":
        return "desktop_permissions"
    if tool_name == "app.open":
        return "app_launch"
    if tool_name in {"python.run", "terminal.run"}:
        return "terminal_execution"
    return "runtime_observation"


def _runtime_default_recovery_risk_level(tool_name: str) -> str:
    if tool_name in {"python.run", "terminal.run"}:
        return "high"
    return "low"


def _runtime_default_recovery_approval_required(tool_name: str) -> bool:
    return tool_name in {"python.run", "terminal.run"}


def _runtime_replan_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in ("ok", "error", "status", "summary", "hint", "blocking_condition"):
        value = result.get(key)
        if value not in (None, "", [], {}):
            preview[key] = value
    return preview


def _runtime_replan_input_preview(tool_request: Mapping[str, Any]) -> dict[str, Any]:
    value = tool_request.get("input")
    return dict(value) if isinstance(value, Mapping) else {}


def _runtime_replan_enrich_recovery_context(
    payload: dict[str, Any],
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    trigger: str,
    source_step_id: str,
    source_tool_name: str,
    input_preview: Mapping[str, Any],
    result_preview: Mapping[str, Any],
    failure_detail: str,
) -> None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    metadata = dict(metadata)
    payload["metadata"] = metadata

    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = _first_mapping(tool_request.get(key), result.get(key), metadata.get(key))
        if value:
            payload[key] = dict(value)
            metadata[key] = dict(value)

    recovery_failure_metadata = _runtime_replan_recovery_failure_metadata(
        tool_request,
        result_preview=result_preview,
    )
    if recovery_failure_metadata:
        metadata.update(recovery_failure_metadata)

    recovery_actions = _runtime_replan_recovery_actions(tool_request, result)
    if trigger == "verification_failed":
        verification_context = _runtime_replan_verification_failure_context(
            tool_request,
            source_step_id=source_step_id,
            source_tool_name=source_tool_name,
            input_preview=input_preview,
            result_preview=result_preview,
            failure_detail=failure_detail,
        )
        verification_targets = verification_context.get("verification_targets")
        if isinstance(verification_targets, list) and verification_targets:
            payload.setdefault("verification_targets", verification_targets)
            metadata.setdefault("verification_targets", verification_targets)
        for key in ("action_target", "observation_evidence", "observation_retry"):
            value = verification_context.get(key)
            if isinstance(value, Mapping) and value:
                payload.setdefault(key, dict(value))
                metadata.setdefault(key, dict(value))
        label = str(verification_context.get("recovery_action_label") or "").strip()
        if label:
            payload.setdefault("recovery_action_label", label)
            metadata.setdefault("recovery_action_label", label)
        for key in ("target_app_name", "target_app_query", "target_search_text"):
            value = str(verification_context.get(key) or "").strip()
            if value:
                payload.setdefault(key, value)
                metadata.setdefault(key, value)
        recovery_actions.extend(_mapping_list(verification_context.get("recovery_actions")))

    if not recovery_actions:
        recovery_actions.extend(
            _runtime_default_replan_recovery_actions(
                source_tool_name,
                input_preview,
                _string_list(payload.get("fallback_tools")),
            )
        )

    recovery_actions = _dedupe_runtime_replan_recovery_actions(recovery_actions)
    if recovery_actions:
        recovery_actions = [
            _runtime_replan_recovery_action_with_auto_start_context(action)
            for action in recovery_actions
        ]
        metadata["recovery_actions"] = recovery_actions


def _runtime_replan_recovery_failure_metadata(
    tool_request: Mapping[str, Any],
    *,
    result_preview: Mapping[str, Any],
) -> dict[str, Any]:
    parent_request_id = str(tool_request.get("replan_request_id") or "").strip()
    if not parent_request_id:
        return {}
    request_input = (
        tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    )
    metadata: dict[str, Any] = {
        "replan_recovery_failed": True,
        "parent_replan_request_id": parent_request_id,
        "failed_recovery_tool": str(
            tool_request.get("tool") or tool_request.get("tool_name") or ""
        ).strip(),
        "failed_recovery_input": dict(request_input),
    }
    for key, value in (
        ("parent_replan_trigger", tool_request.get("replan_trigger")),
        (
            "failed_recovery_action_id",
            tool_request.get("replan_recovery_action_id") or tool_request.get("action_id"),
        ),
        ("failed_recovery_action_label", tool_request.get("recovery_action_label")),
        (
            "failed_recovery_step_id",
            tool_request.get("step_id") or tool_request.get("planner_step_id"),
        ),
        ("failed_recovery_source", tool_request.get("source")),
        (
            "failed_recovery_target_capability_id",
            tool_request.get("target_capability_id") or tool_request.get("capability_id"),
        ),
        ("original_source_step_id", tool_request.get("source_step_id")),
        ("original_source_tool_name", tool_request.get("source_tool_name")),
    ):
        text = str(value or "").strip()
        if text:
            metadata[key] = text
    replan_triggers = _string_list(tool_request.get("replan_triggers"))
    if replan_triggers:
        metadata["replan_triggers"] = replan_triggers
    replan_signal_ids = _string_list(tool_request.get("replan_signal_ids"))
    if replan_signal_ids:
        metadata["replan_signal_ids"] = replan_signal_ids
    verification_targets = _mapping_list(
        tool_request.get("verification_targets")
        or tool_request.get("task_verification_targets")
    )
    if verification_targets:
        metadata["failed_recovery_verification_targets"] = [
            dict(target) for target in verification_targets
        ]
    if result_preview:
        metadata["failed_recovery_result_preview"] = dict(result_preview)
    return {key: value for key, value in metadata.items() if value not in ("", [], {})}


def _runtime_replan_verification_failure_context(
    tool_request: Mapping[str, Any],
    *,
    source_step_id: str,
    source_tool_name: str,
    input_preview: Mapping[str, Any],
    result_preview: Mapping[str, Any],
    failure_detail: str,
) -> dict[str, Any]:
    verification_targets = _runtime_replan_verification_targets(tool_request)
    if not verification_targets:
        return {}
    target = verification_targets[0]
    action_target = _runtime_replan_verification_action_target(
        target,
        source_step_id=source_step_id,
        source_tool_name=source_tool_name,
        input_preview=input_preview,
    )
    observation_evidence = {
        "source_tool": source_tool_name,
        "source_step_id": source_step_id,
        "verification_failed": True,
        "input_preview": dict(input_preview),
        "result_preview": dict(result_preview),
    }
    if failure_detail:
        observation_evidence["failure_detail"] = failure_detail
    observation_retry = {
        "tool": source_tool_name,
        "input": dict(input_preview),
        "source_step_id": source_step_id,
        "reason": "verification_failed",
    }
    target_app_name = _runtime_replan_first_text(
        ("target_app_name", "app_name", "expected_app_name"),
        target,
        action_target,
        input_preview,
    )
    target_app_query = _runtime_replan_first_text(
        ("target_app_query", "app_query", "query"),
        target,
        action_target,
        input_preview,
    )
    target_search_text = _runtime_replan_first_text(
        ("target_search_text", "target", "selector", "text", "value"),
        target,
        action_target,
        input_preview,
    )
    recovery_actions: list[dict[str, Any]] = []
    focus_recovery = _runtime_focus_unverified_recovery_action(
        target_app_name=target_app_name,
        source_step_id=source_step_id,
        source_tool_name=source_tool_name,
        action_target=action_target,
        observation_evidence=observation_evidence,
        failure_detail=failure_detail,
    )
    if focus_recovery:
        recovery_actions.append(focus_recovery)
    if source_tool_name:
        recovery_action: dict[str, Any] = {
            "label": "Re-observe failed verification target",
            "tool": source_tool_name,
            "input": dict(input_preview),
            "permission_target": "runtime_verification",
            "risk_level": "low",
            "action_target": action_target,
            "observation_evidence": observation_evidence,
            "observation_retry": observation_retry,
        }
        recovery_actions.append(recovery_action)
    return {
        "verification_targets": verification_targets,
        "action_target": action_target,
        "observation_evidence": observation_evidence,
        "observation_retry": observation_retry,
        "recovery_action_label": "Re-observe failed verification target",
        "recovery_actions": recovery_actions,
        **({"target_app_name": target_app_name} if target_app_name else {}),
        **({"target_app_query": target_app_query} if target_app_query else {}),
        **({"target_search_text": target_search_text} if target_search_text else {}),
    }


def _runtime_focus_unverified_target_app(
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str:
    if not _runtime_result_has_condition(result, "foreground_focus_unverified"):
        return ""
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    verification_target = (
        tool_request.get("verification_target")
        if isinstance(tool_request.get("verification_target"), Mapping)
        else {}
    )
    action_target = (
        tool_request.get("action_target")
        if isinstance(tool_request.get("action_target"), Mapping)
        else {}
    )
    raw_input = (
        tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    )
    return _runtime_replan_first_text(
        ("app_name", "target_app_name", "expected_app_name"),
        verification_target,
        action_target,
        raw_input,
        result,
        data,
    )


def _runtime_result_has_condition(result: Mapping[str, Any], condition: str) -> bool:
    clean_condition = str(condition or "").strip()
    if not clean_condition:
        return False
    values = [
        result.get("error"),
        result.get("blocking_condition"),
        result.get("status"),
    ]
    values.extend(_string_list(result.get("blocking_conditions")))
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    values.extend(
        [
            data.get("error"),
            data.get("blocking_condition"),
            data.get("status"),
        ]
    )
    values.extend(_string_list(data.get("blocking_conditions")))
    return clean_condition in {str(value or "").strip() for value in values}


def _runtime_focus_unverified_recovery_action(
    *,
    target_app_name: str,
    source_step_id: str,
    source_tool_name: str,
    action_target: Mapping[str, Any],
    observation_evidence: Mapping[str, Any],
    failure_detail: str,
) -> dict[str, Any]:
    clean_app_name = str(target_app_name or "").strip()
    if not clean_app_name or "foreground_focus_unverified" not in str(failure_detail or ""):
        return {}
    verify_request = {
        "tool": "desktop.active_window",
        "input": {},
        "source": "runtime_replan_recovery",
        "planning_reason": "planner_replan_verify_foreground_focus",
        "replan_triggers": ["verification_failed"],
        "verification_target": {
            "app_name": clean_app_name,
            **({"source_tool": source_tool_name} if source_tool_name else {}),
        },
    }
    if source_step_id:
        verify_request["step_id"] = source_step_id
        verify_request["planner_step_id"] = source_step_id
    return {
        "label": "Bring expected app to foreground",
        "tool": "app.open",
        "input": {"app_name": clean_app_name},
        "permission_target": "app_launch",
        "risk_level": "low",
        "selected": True,
        "action_target": dict(action_target),
        "observation_evidence": dict(observation_evidence),
        "observation_retry": {
            "tool": "app.open",
            "input": {"app_name": clean_app_name},
            "reason": "foreground_focus_unverified",
            "source_tool": source_tool_name,
        },
        "deferred_continuation": [verify_request],
    }


def _runtime_replan_verification_targets(
    tool_request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for target in _mapping_list(tool_request.get("task_verification_targets")):
        step_id = str(target.get("step_id") or "").strip()
        todo = target.get("todo") if isinstance(target.get("todo"), Mapping) else {}
        checkpoints = _mapping_list(target.get("checkpoints"))
        snapshot: dict[str, Any] = {}
        if step_id:
            snapshot["step_id"] = step_id
        todo_id = str(todo.get("todo_id") or "").strip()
        if todo_id:
            snapshot["todo_id"] = todo_id
        todo_title = str(todo.get("title") or "").strip()
        if todo_title:
            snapshot["todo_title"] = todo_title
        tool_name = str(todo.get("tool_name") or todo.get("tool") or "").strip()
        if tool_name:
            snapshot["tool_name"] = tool_name
        checkpoint_ids = [
            str(checkpoint.get("checkpoint_id") or "").strip()
            for checkpoint in checkpoints
            if str(checkpoint.get("checkpoint_id") or "").strip()
        ]
        if checkpoint_ids:
            snapshot["checkpoint_ids"] = checkpoint_ids
        checkpoint_titles = [
            str(checkpoint.get("title") or "").strip()
            for checkpoint in checkpoints
            if str(checkpoint.get("title") or "").strip()
        ]
        if checkpoint_titles:
            snapshot["checkpoint_titles"] = checkpoint_titles
        if snapshot:
            targets.append(snapshot)
    explicit_target = _runtime_replan_explicit_verification_target(tool_request)
    if explicit_target:
        targets.append(explicit_target)
    return targets


def _runtime_replan_explicit_verification_target(
    tool_request: Mapping[str, Any],
) -> dict[str, Any]:
    verification_target = (
        tool_request.get("verification_target")
        if isinstance(tool_request.get("verification_target"), Mapping)
        else {}
    )
    input_preview = (
        tool_request.get("input")
        if isinstance(tool_request.get("input"), Mapping)
        else {}
    )
    if not verification_target and not any(
        str(tool_request.get(key) or "").strip()
        for key in ("target_app_name", "target_app_query", "target_search_text")
    ):
        return {}
    app_name = _runtime_replan_first_text(
        ("app_name", "target_app_name", "expected_app_name"),
        verification_target,
        tool_request,
        input_preview,
    )
    app_query = _runtime_replan_first_text(
        ("target_app_query", "app_query", "query"),
        verification_target,
        tool_request,
        input_preview,
    )
    search_text = _runtime_replan_first_text(
        ("target_search_text", "target", "selector", "text", "value"),
        verification_target,
        tool_request,
        input_preview,
    )
    if not any((app_name, app_query, search_text)):
        return {}
    snapshot: dict[str, Any] = {"kind": "desktop_verification_target"}
    step_id = str(
        tool_request.get("step_id") or tool_request.get("planner_step_id") or ""
    ).strip()
    if step_id:
        snapshot["step_id"] = step_id
    tool_name = str(tool_request.get("tool") or tool_request.get("tool_name") or "").strip()
    if tool_name:
        snapshot["tool_name"] = tool_name
    if app_name:
        snapshot["app_name"] = app_name
        snapshot["target_app_name"] = app_name
    if app_query:
        snapshot["app_query"] = app_query
        snapshot["target_app_query"] = app_query
    if search_text:
        snapshot["target_search_text"] = search_text
    source_tool = str(verification_target.get("source_tool") or "").strip()
    if source_tool:
        snapshot["source_tool"] = source_tool
    return snapshot


def _runtime_replan_verification_action_target(
    target: Mapping[str, Any],
    *,
    source_step_id: str,
    source_tool_name: str,
    input_preview: Mapping[str, Any],
) -> dict[str, Any]:
    action_target: dict[str, Any] = {
        "kind": str(target.get("kind") or "task_verification_target").strip(),
        "action": "verify_after_action",
        "verified_by_step_id": source_step_id,
        "verification_tool": source_tool_name,
    }
    for key in ("step_id", "todo_id", "todo_title", "tool_name"):
        value = str(target.get(key) or "").strip()
        if value:
            action_target[key] = value
    for key in ("checkpoint_ids", "checkpoint_titles"):
        values = _string_list(target.get(key))
        if values:
            action_target[key] = values
    for source_key, target_key in (
        ("app_name", "app_name"),
        ("target_app_name", "app_name"),
        ("query", "app_query"),
        ("app_query", "app_query"),
        ("target", "target"),
        ("selector", "target"),
        ("text", "text"),
        ("value", "text"),
    ):
        value = str(target.get(source_key) or input_preview.get(source_key) or "").strip()
        if value and not str(action_target.get(target_key) or "").strip():
            action_target[target_key] = value
    return {key: value for key, value in action_target.items() if value not in ("", [], {})}


def _runtime_replan_first_text(
    keys: tuple[str, ...],
    *sources: Mapping[str, Any],
) -> str:
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _runtime_replan_recovery_actions(
    tool_request: Mapping[str, Any],
    result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    actions: list[dict[str, Any]] = []
    for source in (
        tool_request.get("recovery_actions"),
        result.get("recovery_actions"),
        data.get("recovery_actions"),
    ):
        actions.extend(_mapping_list(source))
    observation_retry_action = _runtime_observation_retry_recovery_action(
        observation_retry=_first_mapping(
            tool_request.get("observation_retry"),
            result.get("observation_retry"),
            data.get("observation_retry"),
        ),
        action_target=_first_mapping(
            tool_request.get("action_target"),
            result.get("action_target"),
            data.get("action_target"),
        ),
        observation_evidence=_first_mapping(
            tool_request.get("observation_evidence"),
            result.get("observation_evidence"),
            data.get("observation_evidence"),
        ),
    )
    if observation_retry_action:
        actions.append(observation_retry_action)
    return [dict(action) for action in actions]


_RUNTIME_OBSERVATION_RETRY_TOOLS = {
    "desktop.list_apps",
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.windows",
    "desktop.list_windows",
    "desktop.ui_elements",
    "desktop.read_ui",
    "desktop.verify",
    "screen.capture",
}

_RUNTIME_REPLAN_AUTO_SAFE_TOOLS = {
    "app.focus",
    "app.open",
    "browser.current_page",
    "browser.screenshot",
    "desktop.active_window",
    "desktop.focus_app",
    "desktop.list_apps",
    "desktop.open_app",
    "desktop.read_ui",
    "desktop.running_apps",
    "desktop.ui_elements",
    "desktop.windows",
    "file.read",
    "fs.read_file",
    "screen.capture",
    "workspace.read",
}


def _runtime_observation_retry_recovery_action(
    *,
    observation_retry: Mapping[str, Any],
    action_target: Mapping[str, Any],
    observation_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = _runtime_observation_retry_tool(observation_retry)
    if not tool_name:
        return {}
    retry_input = (
        observation_retry.get("input")
        if isinstance(observation_retry.get("input"), Mapping)
        else {}
    )
    action: dict[str, Any] = {
        "label": _runtime_observation_retry_label(tool_name, observation_retry),
        "tool": tool_name,
        "input": dict(retry_input),
        "permission_target": _runtime_observation_retry_permission_target(tool_name),
        "risk_level": "low",
        "observation_retry": dict(observation_retry),
    }
    if action_target:
        action["action_target"] = dict(action_target)
    if observation_evidence:
        action["observation_evidence"] = dict(observation_evidence)
    return action


def _runtime_observation_retry_tool(observation_retry: Mapping[str, Any]) -> str:
    tool_name = str(
        observation_retry.get("tool")
        or observation_retry.get("from_tool")
        or observation_retry.get("source_tool")
        or ""
    ).strip()
    if tool_name not in _RUNTIME_OBSERVATION_RETRY_TOOLS:
        return ""
    return tool_name


def _runtime_observation_retry_label(
    tool_name: str,
    observation_retry: Mapping[str, Any],
) -> str:
    reason = str(observation_retry.get("reason") or "").strip()
    if tool_name == "desktop.list_apps" or reason == "resolve_desktop_app":
        return "Re-run desktop app discovery"
    if reason == "verification_failed":
        return "Re-run runtime observation"
    return "Run runtime observation retry"


def _runtime_observation_retry_permission_target(tool_name: str) -> str:
    if tool_name == "desktop.list_apps":
        return "app_discovery"
    return "runtime_observation"


def _dedupe_runtime_replan_recovery_actions(
    actions: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        tool_name = str(action.get("tool") or "").strip()
        if not tool_name:
            continue
        action_input = action.get("input") if isinstance(action.get("input"), Mapping) else {}
        signature = (tool_name, repr(sorted(dict(action_input).items())))
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(dict(action))
    return deduped


def _runtime_replan_recovery_action_with_auto_start_context(
    action: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(action)
    metadata = (
        dict(payload.get("metadata"))
        if isinstance(payload.get("metadata"), Mapping)
        else {}
    )
    auto_start = _runtime_replan_recovery_action_auto_start_context(payload)
    metadata["runtime_replan_auto_start_eligible"] = auto_start["eligible"]
    metadata["runtime_replan_auto_start_reason"] = auto_start["reason"]
    metadata["runtime_replan_auto_start_blockers"] = list(auto_start["blockers"])
    payload["metadata"] = metadata
    return payload


def _runtime_replan_recovery_action_auto_start_context(
    action: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
    risk_level = str(action.get("risk_level") or "").strip().lower()
    approval_required = bool(action.get("approval_required")) or str(
        action.get("approval_status") or ""
    ).strip().lower() in {
        "pending",
        "required",
        "approval_required",
        "waiting_approval",
    }
    if not tool_name:
        blockers.append("missing_tool")
    if approval_required:
        blockers.append("approval_required")
    if risk_level in {"high", "critical"}:
        blockers.append("high_risk")
    if tool_name and tool_name not in _RUNTIME_REPLAN_AUTO_SAFE_TOOLS:
        blockers.append("tool_not_auto_safe")
    return {
        "eligible": not blockers,
        "reason": (
            "safe_low_risk_runtime_replan_recovery"
            if not blockers
            else "manual_runtime_replan_recovery_required"
        ),
        "blockers": blockers,
    }


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _runtime_replan_context_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key
        in {
            "run_group_id",
            "group_run_id",
            "group_id",
            "workflow_id",
            "workflow_run_id",
            "workflow_node_id",
            "workflow_node_label",
            "core_id",
            "workspace_id",
            "task_id",
        }
        and value not in (None, "", [], {})
    }


def _runtime_replan_request_exists(
    timeline: list[dict[str, Any]],
    payload: Mapping[str, Any],
) -> bool:
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return False
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if _runtime_replan_base_event_type(event_type) != "agent.replan.requested":
            continue
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else event
        if str(event_payload.get("request_id") or "").strip() == request_id:
            return True
    return False


def _runtime_replan_request_id(
    *,
    decision_id: str,
    plan_id: str,
    source_step_id: str,
    source_tool_name: str,
    trigger: str,
) -> str:
    parts = [
        value.replace(":", "_")
        for value in (decision_id, plan_id, source_step_id, source_tool_name, trigger)
        if value
    ]
    return "runtime-replan:" + ":".join(parts or ["request"])


_FOREGROUND_READINESS_GATED_TOOLS = {
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.focus_and_safe_key",
    "app.open_and_safe_scroll",
    "app.focus_and_safe_scroll",
    "app.open_and_safe_click",
    "app.focus_and_safe_click",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.focus_and_type_into_ui_element",
    "app.open_and_hotkey",
    "app.focus_and_hotkey",
    "desktop.safe_shortcut",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.safe_click",
    "desktop.safe_type_text",
    "desktop.hotkey",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.submit_foreground",
    "desktop.click",
    "desktop.type_text",
}

_FOREGROUND_READINESS_RESET_TOOLS = {
    "app.open",
    "app.focus",
    "app.focus_window",
    "app.show",
    "desktop.list_apps",
    "desktop.active_window",
    "desktop.inspect_app",
}


def _runtime_readiness_skip_result(
    tool_name: str,
    raw_input: dict[str, Any],
    blocker: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if blocker is None or tool_name not in _FOREGROUND_READINESS_GATED_TOOLS:
        return None
    blocked_app = str(blocker.get("app_name") or "").strip()
    requested_app = str(raw_input.get("app_name") or "").strip()
    if blocked_app and requested_app and requested_app != blocked_app:
        return None
    conditions = _string_list(blocker.get("blocking_conditions")) or ["foreground_not_ready"]
    recovery_actions = blocker.get("recovery_actions")
    recommended_tools = blocker.get("recommended_tools")
    result: dict[str, Any] = {
        "ok": False,
        "skipped": True,
        "blocked_by_runtime_readiness": True,
        "tool": tool_name,
        "action": tool_name,
        "error": conditions[0],
        "blocking_condition": conditions[0],
        "blocking_conditions": conditions,
        "source_tool": "desktop.inspect_app",
        "source_summary": str(blocker.get("summary") or "").strip(),
        "hint": (
            "desktop.inspect_app did not prove the target app is ready for foreground "
            "input. Run one of the recovery actions or inspect again before mutating UI."
        ),
        "data": {
            "app_name": blocked_app,
            "requested_app_name": str(blocker.get("requested_app_name") or "").strip(),
            "skipped_tool": tool_name,
            "skipped_input": raw_input,
            "readiness_checks": blocker.get("checks") if isinstance(blocker.get("checks"), dict) else {},
        },
    }
    if isinstance(recovery_actions, list) and recovery_actions:
        result["recovery_actions"] = recovery_actions
    if isinstance(recommended_tools, list) and recommended_tools:
        result["recommended_tools"] = recommended_tools
    return result


def _remaining_request_can_handle_foreground_readiness(
    blocker: dict[str, Any] | None,
    remaining_requests: list[dict[str, Any]],
) -> bool:
    if blocker is None:
        return False
    for request in remaining_requests:
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or "").strip()
        raw_input = request.get("input") if isinstance(request.get("input"), dict) else {}
        if _runtime_readiness_skip_result(tool_name, raw_input, blocker) is not None:
            return True
        if _request_may_clear_foreground_readiness(blocker, tool_name, raw_input):
            return True
    return False


def _request_may_clear_foreground_readiness(
    blocker: dict[str, Any],
    tool_name: str,
    raw_input: dict[str, Any],
) -> bool:
    if tool_name not in _FOREGROUND_READINESS_RESET_TOOLS:
        return False
    if tool_name == "desktop.active_window":
        return True
    if tool_name == "desktop.list_apps":
        query = str(raw_input.get("query") or "").strip()
        return not query or _name_matches_blocked_app(blocker, query)
    app_name = str(raw_input.get("app_name") or "").strip()
    return not app_name or _name_matches_blocked_app(blocker, app_name)


def _unresolved_discovered_app_skip_result(
    tool_name: str,
    raw_input: dict[str, Any],
    app_name_resolution: dict[str, str],
) -> dict[str, Any] | None:
    if app_name_resolution:
        return None
    requested_app = _selected_discovered_app_requested_name(raw_input)
    if not requested_app:
        return None
    selection_source = (
        _desktop_app_selection_source(raw_input.get("selection_source"))
        or _selected_desktop_app_placeholder_source(raw_input.get("app_name"))
        or _DESKTOP_APP_SELECTION_SOURCE
    )
    source_label = (
        "running app"
        if selection_source == _DESKTOP_RUNNING_APP_SELECTION_SOURCE
        else "installed app"
    )
    recovery_input = (
        {}
        if selection_source == _DESKTOP_RUNNING_APP_SELECTION_SOURCE
        else {"query": requested_app, "limit": 20}
    )
    result: dict[str, Any] = {
        "ok": False,
        "skipped": True,
        "blocked_by_app_resolution": True,
        "tool": tool_name,
        "action": tool_name,
        "error": "app_resolution_failed",
        "blocking_condition": "app_resolution_failed",
        "blocking_conditions": ["app_resolution_failed"],
        "source_tool": selection_source,
        "source_summary": f"No {source_label} was selected for {requested_app}.",
        "hint": (
            f"{selection_source} did not return a high-confidence app match. "
            "Discover the app again or ask the user to choose a candidate before executing."
        ),
        "data": {
            "requested_app_name": requested_app,
            "selection_source": selection_source,
            "skipped_tool": tool_name,
            "skipped_input": raw_input,
        },
        "recommended_tools": [selection_source],
        "recovery_actions": [
            {
                "label": "重新发现应用",
                "tool": selection_source,
                "input": recovery_input,
                "permission_target": "app_discovery",
                "risk_level": "low",
            }
        ],
    }
    return result


def _unresolved_workspace_file_skip_result(
    tool_name: str,
    raw_input: dict[str, Any],
    file_resolution: dict[str, Any],
) -> dict[str, Any] | None:
    if file_resolution:
        return None
    if not _tool_request_uses_selected_workspace_file(raw_input):
        return None
    requested_path = str(
        raw_input.get("path")
        or raw_input.get("target_path")
        or raw_input.get("file_path")
        or _SELECTED_WORKSPACE_FILE_PATH
    ).strip()
    source_scope = str(raw_input.get("source_scope") or raw_input.get("source_path") or "").strip()
    recovery_input: dict[str, Any] = {"path": source_scope or "."}
    pattern = str(raw_input.get("pattern") or "").strip()
    if pattern:
        recovery_input["pattern"] = pattern
    source_kind = str(raw_input.get("source_kind") or raw_input.get("file_type") or "").strip()
    if source_kind:
        recovery_input["file_type"] = source_kind
    if str(raw_input.get("selection") or "").strip():
        recovery_input["include_metadata"] = True
    return {
        "ok": False,
        "skipped": True,
        "blocked_by_file_resolution": True,
        "tool": tool_name,
        "action": tool_name,
        "error": "file_resolution_failed",
        "blocking_condition": "file_resolution_failed",
        "blocking_conditions": ["file_resolution_failed"],
        "source_tool": "workspace.list",
        "source_summary": "No workspace file was selected from workspace.list.",
        "hint": (
            "workspace.list did not return a unique usable file candidate for this step. "
            "List the target directory again or ask the user to choose a candidate before executing."
        ),
        "data": {
            "requested_path": requested_path,
            "selection_source": "workspace.list",
            "skipped_tool": tool_name,
            "skipped_input": raw_input,
        },
        "recommended_tools": ["workspace.list"],
        "recovery_actions": [
            {
                "label": "重新列出候选文件",
                "tool": "workspace.list",
                "input": recovery_input,
                "permission_target": "workspace_discovery",
                "risk_level": "low",
            }
        ],
    }


def _selected_discovered_app_requested_name(raw_input: dict[str, Any]) -> str:
    raw_app_name = str(raw_input.get("app_name") or "").strip()
    selection_source = _desktop_app_selection_source(raw_input.get("selection_source"))
    if not _selected_desktop_app_placeholder_source(raw_app_name) and not selection_source:
        return ""
    return str(raw_input.get("query") or raw_app_name or "").strip()


def _broker_requires_approval(broker: Any, tool_name: str) -> bool:
    approvals = getattr(broker, "approvals", None)
    if not isinstance(approvals, dict):
        return False
    return bool(approvals.get(str(tool_name or "").strip()))


def _tool_result_with_active_window_verification_target(
    tool_name: str,
    tool_result: dict[str, Any],
    verification_target: dict[str, Any],
) -> dict[str, Any]:
    if tool_name != "desktop.active_window":
        return tool_result
    expected_app = str(verification_target.get("app_name") or "").strip()
    if not expected_app or tool_result.get("ok") is not True:
        return tool_result
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    active_app = str(data.get("app_name") or data.get("frontmost_app") or "").strip()
    verified = _app_names_match(active_app, expected_app)
    updated_data = {
        **data,
        "expected_app_name": expected_app,
        "active_app_name": active_app,
        "focus_verified": verified,
    }
    if verified:
        return {**tool_result, "data": updated_data}
    return {
        **tool_result,
        "ok": False,
        "error": "foreground_focus_unverified",
        "verification_failed": True,
        "blocking_condition": "foreground_focus_unverified",
        "blocking_conditions": ["foreground_focus_unverified"],
        "expected_app_name": expected_app,
        "active_app_name": active_app,
        "hint": (
            "The active window does not match the app that was just opened or focused. "
            "Focus the expected app again or inspect windows before continuing."
        ),
        "data": updated_data,
    }


def _active_window_target_from_tool_result(
    tool_name: str,
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_result.get("ok") is not True or tool_result.get("approval_required"):
        return None
    if not _tool_can_change_active_app(tool_name):
        return None
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    app_name = str(
        data.get("app_name")
        or data.get("discovered_app_name")
        or raw_input.get("app_name")
        or ""
    ).strip()
    if not app_name:
        return None
    return {"app_name": app_name, "source_tool": tool_name}


def _tool_can_change_active_app(tool_name: str) -> bool:
    clean_tool = str(tool_name or "").strip()
    return bool(
        clean_tool in {
            "app.open",
            "app.focus",
            "app.focus_window",
            "desktop.open_app",
            "desktop.focus_app",
            "desktop.open_path_with_app",
            "app.open_path_with_app",
        }
        or clean_tool.startswith("app.open_and_")
        or clean_tool.startswith("app.focus_and_")
    )


def _app_names_match(left: str, right: str) -> bool:
    return _app_lookups_related(left, right)


def _foreground_readiness_blocker(
    tool_name: str,
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name != "desktop.inspect_app":
        return None
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    if tool_result.get("ok") is True and data.get("ready_for_foreground_action") is True:
        return None
    conditions = _inspect_app_blocking_conditions(tool_result, data, checks)
    return {
        "app_name": str(data.get("app_name") or raw_input.get("app_name") or "").strip(),
        "requested_app_name": str(
            data.get("requested_app_name") or raw_input.get("app_name") or ""
        ).strip(),
        "summary": str(tool_result.get("summary") or "").strip(),
        "blocking_conditions": conditions,
        "checks": checks,
        "recommended_tools": (
            tool_result.get("recommended_tools")
            if isinstance(tool_result.get("recommended_tools"), list)
            else data.get("recommended_tools")
        ),
        "recovery_actions": (
            tool_result.get("recovery_actions")
            if isinstance(tool_result.get("recovery_actions"), list)
            else data.get("recovery_actions")
        ),
    }


def _updated_foreground_readiness_blocker(
    blocker: dict[str, Any] | None,
    tool_name: str,
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any] | None:
    inspect_blocker = _foreground_readiness_blocker(tool_name, raw_input, tool_result)
    if inspect_blocker is not None:
        return inspect_blocker
    if tool_name == "desktop.inspect_app":
        return None
    if not _clears_foreground_readiness_blocker(blocker, tool_name, raw_input, tool_result):
        return blocker
    return None


def _foreground_readiness_recovered_payload(
    blocker: dict[str, Any],
    tool_name: str,
    input_preview: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "recovery_tool": tool_name,
        "input_preview": input_preview,
        "status": "recovered",
        "app_name": str(blocker.get("app_name") or "").strip(),
        "requested_app_name": str(blocker.get("requested_app_name") or "").strip(),
        "blocking_conditions": _string_list(blocker.get("blocking_conditions")),
        "source_tool": str(blocker.get("source_tool") or "desktop.inspect_app").strip(),
        "source_summary": str(blocker.get("summary") or "").strip(),
        "result_summary": str(tool_result.get("summary") or "").strip(),
    }


def _clears_foreground_readiness_blocker(
    blocker: dict[str, Any] | None,
    tool_name: str,
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> bool:
    if blocker is None or tool_name not in _FOREGROUND_READINESS_RESET_TOOLS:
        return False
    if tool_result.get("ok") is not True:
        return False
    if tool_name == "desktop.list_apps":
        return _list_apps_result_resolves_blocker(blocker, raw_input, tool_result)
    if tool_name == "desktop.active_window":
        return _active_window_result_resolves_blocker(blocker, tool_result)
    return _tool_app_name_matches_blocker(blocker, raw_input, tool_result)


def _list_apps_result_resolves_blocker(
    blocker: dict[str, Any],
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> bool:
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    if not apps:
        return False
    query = str(data.get("query") or raw_input.get("query") or "").strip()
    return _name_matches_blocked_app(blocker, query)


def _active_window_result_resolves_blocker(
    blocker: dict[str, Any],
    tool_result: dict[str, Any],
) -> bool:
    conditions = set(_string_list(blocker.get("blocking_conditions")))
    if conditions - {"foreground_focus_unverified", "foreground_not_ready"}:
        return False
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    active_name = str(data.get("app_name") or data.get("frontmost_app") or "").strip()
    return _name_matches_blocked_app(blocker, active_name)


def _tool_app_name_matches_blocker(
    blocker: dict[str, Any],
    raw_input: dict[str, Any],
    tool_result: dict[str, Any],
) -> bool:
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    app_name = str(
        data.get("app_name")
        or data.get("discovered_app_name")
        or raw_input.get("app_name")
        or ""
    ).strip()
    return _name_matches_blocked_app(blocker, app_name)


def _name_matches_blocked_app(blocker: dict[str, Any], app_name: str) -> bool:
    clean_name = str(app_name or "").strip().casefold()
    if not clean_name:
        return False
    blocked_names = {
        str(blocker.get("app_name") or "").strip().casefold(),
        str(blocker.get("requested_app_name") or "").strip().casefold(),
    }
    return clean_name in {name for name in blocked_names if name}


def _inspect_app_blocking_conditions(
    tool_result: dict[str, Any],
    data: dict[str, Any],
    checks: dict[str, Any],
) -> list[str]:
    conditions: list[str] = []
    if tool_result.get("ok") is False and str(tool_result.get("error") or "").strip():
        conditions.append(str(tool_result.get("error") or "").strip())
    if data.get("app_found") is False or checks.get("discovered_app") is False:
        conditions.append("app_not_found")
    if data.get("running") is False or checks.get("status_running") is False:
        conditions.append("app_not_running")
    if data.get("focus_verified") is False or checks.get("focus_verified") is False:
        conditions.append("foreground_focus_unverified")
    if data.get("visibility_limited") is True:
        conditions.append("foreground_visibility_limited")
    if checks.get("ui_query_ok") is False:
        conditions.append("ui_inspection_failed")
    if data.get("ui_element_count") == 0 or checks.get("named_ui_elements_nonempty") is False:
        conditions.append("ui_elements_empty")
    if data.get("control_like_count") == 0 or checks.get("control_like_ui_visible") is False:
        conditions.append("no_actionable_controls")
    if checks.get("ready_for_foreground_action") is False:
        conditions.append("foreground_not_ready")
    return _string_list(conditions) or ["foreground_not_ready"]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items
