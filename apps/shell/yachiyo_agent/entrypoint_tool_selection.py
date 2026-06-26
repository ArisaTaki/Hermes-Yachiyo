"""Planner-first direct tool selection for lightweight Chat entrypoints."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .planner_execution import planner_direct_decision_and_tool_requests
from .planner_projection import planner_selection_payload

LegacyToolRequestProvider = Callable[[str, list[str]], list[dict[str, Any]]]
LegacyToolRequestPostprocess = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


@dataclass(frozen=True)
class DirectToolSelection:
    decision: Any | None
    requests: list[dict[str, Any]]
    event_payload: dict[str, Any]
    selected_source: str


def planner_first_direct_decision_and_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
    legacy_tool_requests: LegacyToolRequestProvider | None = None,
    legacy_postprocess: LegacyToolRequestPostprocess | None = None,
) -> tuple[Any | None, list[dict[str, Any]]]:
    selection = planner_first_direct_tool_selection(
        prompt,
        allowed_tools,
        metadata=metadata,
        legacy_tool_requests=legacy_tool_requests,
        legacy_postprocess=legacy_postprocess,
    )
    return selection.decision, selection.requests


def planner_first_direct_tool_selection(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
    legacy_tool_requests: LegacyToolRequestProvider | None = None,
    legacy_postprocess: LegacyToolRequestPostprocess | None = None,
) -> DirectToolSelection:
    allowed = [str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()]
    decision, planner_requests = planner_direct_decision_and_tool_requests(
        prompt,
        allowed,
        metadata=metadata,
    )
    legacy_requests: list[dict[str, Any]] = []
    selected_source = "runtime_planner" if planner_requests else ""
    selected_reason = "runtime_planner_direct"
    selected_requests = planner_requests
    if _should_consult_legacy(planner_requests):
        legacy_requests = _legacy_requests(
            prompt,
            allowed,
            legacy_tool_requests=legacy_tool_requests,
            legacy_postprocess=legacy_postprocess,
        )
        if legacy_requests and not _same_tool_requests(planner_requests, legacy_requests):
            selected_source = "daily_desktop_intent"
            selected_reason = _legacy_selection_reason(planner_requests)
            selected_requests = legacy_requests
    if planner_requests:
        return DirectToolSelection(
            decision=decision,
            requests=selected_requests,
            event_payload=planner_selection_payload(
                decision=decision,
                planner_requests=planner_requests,
                legacy_requests=legacy_requests,
                selected_requests=selected_requests,
                selected_source=selected_source,
                selected_reason=selected_reason,
            ),
            selected_source=selected_source,
        )
    if selected_requests:
        return DirectToolSelection(
            decision=None,
            requests=selected_requests,
            event_payload=planner_selection_payload(
                decision=decision,
                planner_requests=planner_requests,
                legacy_requests=selected_requests,
                selected_requests=selected_requests,
                selected_source="daily_desktop_intent",
                selected_reason="legacy_available_without_planner_direct_plan",
            ),
            selected_source="daily_desktop_intent",
        )
    return DirectToolSelection(
        decision=None,
        requests=[],
        event_payload=planner_selection_payload(
            decision=decision,
            planner_requests=planner_requests,
            legacy_requests=legacy_requests,
            selected_requests=[],
            selected_source="none",
            selected_reason="no_direct_entrypoint_plan",
        ),
        selected_source="none",
    )


def _should_consult_legacy(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return True
    tools = [str(request.get("tool") or "").strip() for request in requests]
    if _runtime_planner_model_followup_owns_selection(requests):
        return False
    if _runtime_planner_communication_send_owns_selection(requests):
        return False
    if _runtime_planner_desktop_discovery_owns_selection(requests):
        return False
    if _runtime_planner_desktop_observation_owns_selection(requests):
        return False
    if _runtime_planner_system_settings_owns_selection(requests):
        return False
    if any(bool(request.get("continue_to_model")) for request in requests):
        return True
    if any(tool == "desktop.submit_foreground" for tool in tools):
        return True
    if any(tool in {"desktop.ui_elements", "screen.capture"} for tool in tools):
        return True
    if any(tool.startswith("system.") for tool in tools):
        return True
    if any(tool.startswith("clipboard.") for tool in tools):
        return True
    if any(tool in {"media.apple_music_play", "media.system_control"} for tool in tools):
        return True
    if len(requests) != 1:
        return False
    tool_name = tools[0]
    return tool_name.startswith(("app.", "desktop.", "browser."))


_RUNTIME_PLANNER_OWNED_MODEL_FOLLOWUP_REASONS = frozenset(
    {
        "planner_prefetch_information_capture_context",
        "planner_prefetch_schedule_context",
        "planner_prefetch_communication_context",
        "planner_prefetch_web_context",
    }
)


def _runtime_planner_model_followup_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    if not any(bool(request.get("continue_to_model")) for request in requests):
        return False
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    return bool(reasons) and reasons <= _RUNTIME_PLANNER_OWNED_MODEL_FOLLOWUP_REASONS


def _runtime_planner_communication_send_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    return reasons == {"planner_fallback_communication_send"}


def _runtime_planner_desktop_discovery_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    if reasons != {"planner_fallback_desktop_operation"}:
        return False
    tools = {
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    return tools == {"desktop.ui_elements"}


def _runtime_planner_desktop_observation_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    if reasons != {"planner_fallback_desktop_operation"}:
        return False
    tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict)
    ]
    if len(tools) != 2 or tools[1] != "desktop.ui_elements":
        return False
    if tools[0] not in {"app.open", "app.focus", "app.focus_window"}:
        return False
    first_request = requests[0] if isinstance(requests[0], dict) else {}
    first_input = first_request.get("input")
    if not isinstance(first_input, Mapping):
        return False
    app_name = str(first_input.get("app_name") or "").strip()
    return _runtime_observation_app_name_is_specific(app_name)


def _runtime_observation_app_name_is_specific(app_name: str) -> bool:
    if not app_name:
        return False
    if not re.search(r"[A-Za-z]", app_name):
        return False
    compact = re.sub(r"[\W_]+", "", app_name, flags=re.UNICODE).lower()
    return compact not in {
        "me",
        "my",
        "now",
        "current",
        "this",
        "foreground",
        "active",
    }


def _runtime_planner_system_settings_owns_selection(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict)
    }
    if reasons != {"planner_fallback_system_control"}:
        return False
    tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict)
    ]
    return bool(tools) and tools[0] == "system.settings_open" and set(tools) <= {
        "system.settings_open",
        "desktop.ui_elements",
    }


def _legacy_requests(
    prompt: str,
    allowed_tools: list[str],
    *,
    legacy_tool_requests: LegacyToolRequestProvider | None,
    legacy_postprocess: LegacyToolRequestPostprocess | None,
) -> list[dict[str, Any]]:
    if legacy_tool_requests is None:
        return []
    try:
        requests = legacy_tool_requests(str(prompt or ""), allowed_tools)
    except Exception:
        return []
    cleaned = [request for request in requests if isinstance(request, dict)]
    if legacy_postprocess is not None:
        try:
            cleaned = legacy_postprocess(cleaned)
        except Exception:
            return cleaned
    return cleaned


def _same_tool_requests(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    return _request_signature(left) == _request_signature(right)


def _request_signature(requests: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    signature: list[tuple[str, dict[str, Any]]] = []
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        signature.append((tool_name, dict(payload)))
    return signature


def _legacy_selection_reason(planner_requests: list[dict[str, Any]]) -> str:
    if not planner_requests:
        return "legacy_available_without_planner_direct_plan"
    if any(bool(request.get("continue_to_model")) for request in planner_requests):
        return "legacy_direct_plan_over_model_followup"
    return "legacy_more_specific_direct_plan"
