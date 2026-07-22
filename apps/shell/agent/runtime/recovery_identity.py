"""Stable identities and retry evidence for runtime replan recovery actions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


_RECOVERY_IDENTITY_KEY = "replan_recovery_identity"
_RECOVERY_IDENTITIES_KEY = "replan_recovery_identities"
_APP_PLACEHOLDER_PREFIX = "<selected app from "
_SELECTED_APP_IDENTITY = "<selected app>"
_APP_SCOPED_OBSERVATION_TOOLS = {
    "desktop.active_window",
    "desktop.inspect_app",
    "desktop.list_windows",
    "desktop.read_ui",
    "desktop.ui_elements",
    "desktop.verify",
    "desktop.windows",
}
_REASON_ONLY_OBSERVATION_TOOLS = {
    "desktop.active_window",
    "desktop.running_apps",
    "screen.capture",
}
_NEW_EVIDENCE_EVENT_TYPES = {
    "agent.model.followup_context",
    "agent.tool.input_resolved",
    "agent.user.choice",
    "user.choice",
}


def ensure_recovery_action_identity(request: dict[str, Any]) -> str:
    """Attach and return a deterministic identity for one recovery action."""
    identity = recovery_action_identity(request)
    if identity:
        request[_RECOVERY_IDENTITY_KEY] = identity
    return identity


def recovery_action_identity(
    request: Mapping[str, Any],
    *,
    replan_request_id: str = "",
) -> str:
    existing = str(request.get(_RECOVERY_IDENTITY_KEY) or "").strip()
    if existing:
        return existing
    request_id = str(
        replan_request_id
        or request.get("replan_request_id")
        or request.get("request_id")
        or ""
    ).strip()
    tool_name = str(
        request.get("recovery_action_tool")
        or request.get("selected_tool_name")
        or request.get("tool")
        or request.get("tool_name")
        or ""
    ).strip()
    if not request_id or not tool_name:
        return ""
    source_step_id = str(
        request.get("source_step_id")
        or request.get("planner_step_id")
        or request.get("step_id")
        or request.get("selected_step_id")
        or ""
    ).strip()
    identity_payload = {
        "input": normalized_recovery_input(request),
        "replan_request_id": request_id,
        "source_step_id": source_step_id,
        "tool": tool_name,
    }
    encoded = json.dumps(
        identity_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "replan-recovery-" + hashlib.sha256(encoded).hexdigest()[:24]


def normalized_recovery_input(request: Mapping[str, Any]) -> dict[str, Any]:
    tool_name = str(
        request.get("recovery_action_tool")
        or request.get("selected_tool_name")
        or request.get("tool")
        or request.get("tool_name")
        or ""
    ).strip()
    raw_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    normalized = dict(raw_input)
    raw_app_name = str(normalized.get("app_name") or "").strip()
    target_app_name = _recovery_target_app_name(request)
    selected_app_context = _recovery_uses_selected_app_placeholder(request)
    if (
        tool_name in _APP_SCOPED_OBSERVATION_TOOLS
        and selected_app_context
    ):
        normalized["app_name"] = _SELECTED_APP_IDENTITY
        normalized.pop("selection_source", None)
        normalized.pop("query", None)
    elif (
        tool_name in _APP_SCOPED_OBSERVATION_TOOLS
        and raw_app_name.casefold().startswith(_APP_PLACEHOLDER_PREFIX)
        and target_app_name
    ):
        normalized["app_name"] = target_app_name
        normalized.pop("selection_source", None)
        normalized.pop("query", None)
    if tool_name in _REASON_ONLY_OBSERVATION_TOOLS:
        normalized.pop("reason", None)
    return _normalize_mapping(normalized)


def recovery_action_identities_from_timeline(
    timeline: Iterable[Mapping[str, Any]],
) -> set[str]:
    identities: set[str] = set()
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        for container in (event, payload):
            identity = str(container.get(_RECOVERY_IDENTITY_KEY) or "").strip()
            if identity:
                identities.add(identity)
            raw_identities = container.get(_RECOVERY_IDENTITIES_KEY)
            if isinstance(raw_identities, list):
                identities.update(
                    str(item).strip() for item in raw_identities if str(item).strip()
                )
    return identities


def recovery_request_repeats_stalled_discovery(
    request: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> bool:
    """Reject an identical immediate discovery retry until new evidence arrives."""
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    if tool_name != "desktop.list_apps":
        return False
    expected_input = normalized_recovery_input(request)
    latest_matching_index = -1
    start = max(0, int(tool_timeline_start or 0))
    for index, event in enumerate(timeline[start:], start=start):
        if str(event.get("event") or "").strip() != "agent.tool.call":
            continue
        if str(event.get("detail") or "").strip() != tool_name:
            continue
        event_input = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        comparable = {**dict(request), "input": dict(event_input)}
        comparable.pop(_RECOVERY_IDENTITY_KEY, None)
        if normalized_recovery_input(comparable) == expected_input:
            latest_matching_index = index
    if latest_matching_index < 0:
        return False
    return not _timeline_has_new_recovery_evidence(
        timeline[latest_matching_index + 1 :],
        repeated_tool=tool_name,
        repeated_input=expected_input,
    )


def _recovery_target_app_name(request: Mapping[str, Any]) -> str:
    direct = str(request.get("target_app_name") or "").strip()
    if direct:
        return direct
    for key in ("action_target", "verification_target", "observation_evidence"):
        target = request.get(key) if isinstance(request.get(key), Mapping) else {}
        app_name = str(
            target.get("app_name")
            or target.get("expected_app_name")
            or target.get("resolved_app_name")
            or ""
        ).strip()
        if app_name and not app_name.casefold().startswith(_APP_PLACEHOLDER_PREFIX):
            return app_name
    return ""


def _recovery_uses_selected_app_placeholder(request: Mapping[str, Any]) -> bool:
    request_input = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    sources = [request_input]
    for key in ("observation_retry", "action_target", "observation_evidence"):
        value = request.get(key) if isinstance(request.get(key), Mapping) else {}
        sources.append(value)
        nested_input = value.get("input") if isinstance(value.get("input"), Mapping) else {}
        sources.append(nested_input)
    return any(
        str(source.get("app_name") or "").strip().casefold().startswith(
            _APP_PLACEHOLDER_PREFIX
        )
        for source in sources
    )


def _timeline_has_new_recovery_evidence(
    events: Iterable[Mapping[str, Any]],
    *,
    repeated_tool: str,
    repeated_input: Mapping[str, Any],
) -> bool:
    for event in events:
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if event_type in _NEW_EVIDENCE_EVENT_TYPES:
            return True
        if event_type != "agent.tool.call":
            continue
        result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
        if result.get("ok") is not True or result.get("approval_required"):
            continue
        event_tool = str(event.get("detail") or event.get("tool") or "").strip()
        event_input = (
            event.get("input_preview")
            if isinstance(event.get("input_preview"), Mapping)
            else {}
        )
        comparable = {"tool": event_tool, "input": dict(event_input)}
        if event_tool != repeated_tool or normalized_recovery_input(comparable) != dict(
            repeated_input
        ):
            return True
    return False


def _normalize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _normalize_value(item)
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_normalize_value(item) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
