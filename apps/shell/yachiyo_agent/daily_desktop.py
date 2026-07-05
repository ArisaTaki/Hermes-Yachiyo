"""Shared daily desktop runtime helpers for Chat, Bubble, and Live2D."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_entrypoint_tool_requests,
    daily_desktop_metadata_tool_request,
    daily_desktop_recovery_prompt,
)
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES

logger = logging.getLogger(__name__)

_ENTRYPOINT_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.permissions",
}
_ENTRYPOINT_NON_PRIMARY_TOOLS = {
    *_ENTRYPOINT_DISCOVERY_TOOLS,
    "desktop.active_window",
    "desktop.windows",
    "desktop.ui_elements",
}
_ENTRYPOINT_TIMELINE_CONTEXT_KEYS = (
    "request_id",
    "step_id",
    "capability_id",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "core_id",
    "workspace_id",
    "group_run_id",
    "run_group_id",
    "group_id",
    "workflow_run_id",
    "workflow_id",
    "workflow_node_id",
    "workflow_node_label",
    "workflow_node_kind",
    "approval_required",
    "depends_on",
    "fallback_tools",
    "legacy_fallback",
    "compatibility_boundary",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
    "requires_observation",
    "requires_post_action_verification",
    "replan_triggers",
    "replan_signal_ids",
    "task_todo",
    "task_checkpoints",
    "task_workspace_items",
    "task_verification_targets",
)


def daily_desktop_allowed_tools(
    allowed_tools: Sequence[str] | None = None,
) -> list[str]:
    if allowed_tools is None:
        allowed_tools = DAILY_DESKTOP_TOOL_NAMES
    return [
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    ]


def main_chat_entrypoint_allowed_tools(
    runtime: Any | None,
    *,
    fallback: Sequence[str] | None = None,
) -> list[str]:
    for policy in _runtime_main_chat_tool_policies(runtime):
        allowed = policy.get("allowed_tools") if isinstance(policy, Mapping) else None
        if allowed:
            return daily_desktop_allowed_tools(allowed)
    return daily_desktop_allowed_tools(fallback)


def daily_desktop_entrypoint_requests(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = daily_desktop_allowed_tools(allowed_tools)
    return daily_desktop_entrypoint_tool_requests(
        str(text or ""),
        allowed,
        metadata=metadata,
    )


def planner_first_daily_desktop_entrypoint_requests(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    metadata_allowed_tools: Sequence[str] | None = None,
    execution_normalized: bool = False,
    include_runtime_context: bool = False,
) -> list[dict[str, Any]]:
    """Return daily entrypoint requests with Runtime Planner as the default."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    direct_tool_request = daily_desktop_direct_metadata_request(
        metadata,
        allowed_tools=metadata_allowed_tools if metadata_allowed_tools is not None else allowed,
    )
    if direct_tool_request:
        return [direct_tool_request]
    try:
        from .planner_execution import planner_execution_tool_requests, planner_tool_requests

        if execution_normalized and include_runtime_context:
            runtime_requests = _runtime_execution_context_entrypoint_requests(
                str(text or ""),
                allowed,
                metadata=metadata,
            )
            if runtime_requests:
                return runtime_requests

        planner_requests = planner_tool_requests(
            str(text or ""),
            allowed,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Runtime planner daily desktop candidates unavailable", exc_info=True)
        planner_requests = []
    if planner_requests:
        if execution_normalized:
            return planner_execution_tool_requests(planner_requests, allowed) or planner_requests
        return planner_requests
    return _legacy_entrypoint_compatibility_requests(
        daily_desktop_entrypoint_requests(
            text,
            metadata=metadata,
            allowed_tools=allowed,
        )
    )


def daily_desktop_runtime_execution_envelope(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the full Runtime execution envelope for daily entrypoints."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    try:
        from .runtime_execution import runtime_execution_envelope_payload
        from .runtime_planner import RuntimePlanner

        decision = RuntimePlanner().decision(
            str(text or ""),
            allowed_tools=allowed,
            metadata=metadata,
        )
        return runtime_execution_envelope_payload(
            decision,
            allowed_tools=allowed,
            full_plan=True,
        )
    except Exception:
        logger.debug("Runtime execution envelope unavailable for daily desktop", exc_info=True)
        return {}


def daily_desktop_direct_metadata_request(
    metadata: Mapping[str, Any] | None,
    *,
    allowed_tools: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    return daily_desktop_metadata_tool_request(
        metadata,
        daily_desktop_allowed_tools(allowed_tools),
    )


def daily_desktop_recovery_execution_prompt(
    prompt: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    return daily_desktop_recovery_prompt(metadata) or str(prompt or "").strip()


def daily_desktop_user_metadata(
    requests: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if not requests:
        return {}
    tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if str(request.get("tool") or "").strip()
    ]
    if not tools:
        return {}
    first_request = requests[0]
    payload: dict[str, Any] = {
        "daily_desktop_intent": True,
        "daily_desktop_source": str(first_request.get("source") or "daily_desktop_intent"),
        "daily_desktop_planning_reason": str(
            first_request.get("planning_reason") or "clear_daily_desktop_intent"
        ),
        "daily_desktop_tool": tools[0],
        "daily_desktop_tools": tools,
    }
    compatibility_boundary = str(first_request.get("compatibility_boundary") or "").strip()
    if compatibility_boundary:
        payload["daily_desktop_compatibility_boundary"] = compatibility_boundary
    if first_request.get("legacy_fallback"):
        payload["daily_desktop_legacy_fallback"] = True
    return payload


def entrypoint_plan_user_metadata(
    requests: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Project planner-first entrypoint metadata while preserving legacy keys."""

    metadata = daily_desktop_user_metadata(_visible_entrypoint_plan_requests(requests))
    if not metadata:
        return {}
    source = str(metadata.get("daily_desktop_source") or "").strip()
    reason = str(metadata.get("daily_desktop_planning_reason") or "").strip()
    tool = str(metadata.get("daily_desktop_tool") or "").strip()
    tools = metadata.get("daily_desktop_tools")
    tool_list = [str(item or "").strip() for item in tools or [] if str(item or "").strip()]
    return {
        **metadata,
        "entrypoint_plan": True,
        "entrypoint_plan_source": source,
        "entrypoint_plan_reason": reason,
        "entrypoint_plan_tool": tool,
        "entrypoint_plan_tools": tool_list,
        "entrypoint_plan_legacy_fallback": source != "runtime_planner",
    }


def _visible_entrypoint_plan_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    items = [request for request in requests or [] if isinstance(request, Mapping)]
    if len(items) <= 1:
        return items
    primary_indexes = [
        index
        for index, request in enumerate(items)
        if str(request.get("tool") or "").strip() not in _ENTRYPOINT_NON_PRIMARY_TOOLS
    ]
    if not primary_indexes:
        visible = list(items)
        while (
            len(visible) > 1
            and str(visible[0].get("tool") or "").strip() in _ENTRYPOINT_DISCOVERY_TOOLS
        ):
            visible = visible[1:]
        return visible
    first_primary = primary_indexes[0]
    last_primary = primary_indexes[-1]
    visible = []
    for index, request in enumerate(items):
        tool_name = str(request.get("tool") or "").strip()
        if tool_name in _ENTRYPOINT_DISCOVERY_TOOLS and (
            index < first_primary or index > last_primary
        ):
            continue
        if tool_name in _ENTRYPOINT_NON_PRIMARY_TOOLS and index > last_primary:
            continue
        visible.append(request)
    return visible or items


def _legacy_entrypoint_compatibility_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    compatible: list[dict[str, Any]] = []
    for request in requests or ():
        if not isinstance(request, Mapping):
            continue
        compatible.append(
            {
                **dict(request),
                "legacy_fallback": True,
                "compatibility_boundary": "legacy_daily_desktop_intent",
            }
        )
    return compatible


def daily_desktop_planned_timeline(
    prompt: str = "",
    *,
    requests: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    include_runtime_context: bool = False,
) -> list[dict[str, Any]]:
    planned_requests = list(requests or ())
    if not planned_requests:
        planned_requests = planner_first_daily_desktop_entrypoint_requests(
            prompt,
            metadata=metadata,
            allowed_tools=allowed_tools,
            execution_normalized=True,
            include_runtime_context=include_runtime_context,
        )
    if not planned_requests:
        return []
    timeline: list[dict[str, Any]] = []
    for request in planned_requests:
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        tool_input = request.get("input") if isinstance(request.get("input"), dict) else {}
        event = {
            "event": "agent.desktop.intent_planned",
            "detail": tool_name,
            "tool": tool_name,
            "status": "planned",
            "source": str(request.get("source") or "daily_desktop_intent"),
            "planning_reason": str(
                request.get("planning_reason") or "clear_daily_desktop_intent"
            ),
            "input_preview": dict(tool_input),
        }
        if request.get("continue_to_model"):
            event["continue_to_model"] = True
        for key in _ENTRYPOINT_TIMELINE_CONTEXT_KEYS:
            value = request.get(key)
            if _has_entrypoint_timeline_context_value(value):
                event[key] = value
        timeline.append(event)
    return timeline


def _has_entrypoint_timeline_context_value(value: Any) -> bool:
    return value not in (None, "", [], {}) and value is not False


def _runtime_execution_context_entrypoint_requests(
    text: str,
    allowed_tools: Sequence[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from .runtime_execution import runtime_execution_requests_from_envelope_payload

        envelope = daily_desktop_runtime_execution_envelope(
            text,
            metadata=metadata,
            allowed_tools=allowed_tools,
        )
        return runtime_execution_requests_from_envelope_payload(
            envelope,
            allowed_tools=allowed_tools,
        )
    except Exception:
        logger.debug("Runtime execution context entrypoint unavailable", exc_info=True)
        return []


def _runtime_main_chat_tool_policies(runtime: Any | None) -> list[Mapping[str, Any]]:
    if runtime is None:
        return []
    policies: list[Mapping[str, Any]] = []
    main_chat_tool_policy = getattr(runtime, "_main_chat_tool_policy", None)
    if callable(main_chat_tool_policy):
        try:
            policy = main_chat_tool_policy()
            if isinstance(policy, Mapping):
                policies.append(policy)
        except Exception:
            pass
    main_chat_config = getattr(runtime, "main_chat_config", None)
    config_tool_policy = getattr(main_chat_config, "tool_policy", None)
    if callable(config_tool_policy):
        try:
            policy = config_tool_policy()
            if isinstance(policy, Mapping):
                policies.append(policy)
        except Exception:
            pass
    return policies
