"""Convert runtime planner decisions into existing tool request payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .desktop_plan_hints import (
    app_control_mode,
    app_control_tool_candidates,
    app_foreground_tool_candidates,
    click_target_hint,
    media_tool_preview,
    safe_type_text_hint,
    submit_action_hint,
    type_into_ui_hint,
)
from .runtime_planner import RuntimePlanner


def planner_desktop_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return []
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=allowed,
        metadata=metadata,
    )
    if decision.selected_intent.kind == "media_playback":
        return _media_tool_requests(decision.selected_intent.inputs, allowed)
    if decision.selected_intent.kind != "desktop_operation":
        return []

    app_name = str(decision.selected_intent.inputs.get("app_name_hint") or "").strip()
    mode = app_control_mode(prompt)
    click_target = click_target_hint(prompt)
    type_target = type_into_ui_hint(prompt, app_name=app_name)
    safe_type_text = "" if type_target else safe_type_text_hint(prompt)
    submit_action = submit_action_hint(prompt)

    app_type_tool = _app_tool(mode, "type_into_ui_element", allowed)
    if app_name and type_target and app_type_tool:
        requests = [
            _request(
                app_type_tool,
                {
                    "app_name": app_name,
                    "target": type_target["target"],
                    "text": type_target["text"],
                    "role_filter": type_target["role_filter"],
                    "limit": 80,
                },
            )
        ]
        if submit_action and "desktop.submit_foreground" in allowed:
            requests.append(_request("desktop.submit_foreground", {"action": submit_action}))
        return requests

    app_safe_type_tool = _app_tool(mode, "safe_type_text", allowed)
    if app_name and safe_type_text and app_safe_type_tool:
        requests = [
            _request(
                app_safe_type_tool,
                {
                    "app_name": app_name,
                    "text": safe_type_text,
                },
            )
        ]
        if submit_action and "desktop.submit_foreground" in allowed:
            requests.append(_request("desktop.submit_foreground", {"action": submit_action}))
        return requests

    app_click_tool = _app_tool(mode, "click_ui_element", allowed)
    if app_name and click_target and app_click_tool:
        requests = [
            _request(
                app_click_tool,
                {
                    "app_name": app_name,
                    "target": click_target["target"],
                    "role_filter": click_target["role_filter"],
                    "limit": 80,
                    "click_count": click_target["click_count"],
                },
            )
        ]
        if submit_action and "desktop.submit_foreground" in allowed:
            requests.append(_request("desktop.submit_foreground", {"action": submit_action}))
        return requests

    requests: list[dict[str, Any]] = []
    app_control_tool = _app_tool(mode, "control", allowed)
    if app_name and app_control_tool:
        requests.append(_request(app_control_tool, {"app_name": app_name}))

    if type_target and "desktop.type_into_ui_element" in allowed:
        requests.append(
            _request(
                "desktop.type_into_ui_element",
                {
                    "target": type_target["target"],
                    "text": type_target["text"],
                    "role_filter": type_target["role_filter"],
                    "limit": 80,
                },
            )
        )
    elif safe_type_text and "desktop.safe_type_text" in allowed:
        requests.append(_request("desktop.safe_type_text", {"text": safe_type_text}))

    if click_target and "desktop.click_ui_element" in allowed:
        requests.append(
            _request(
                "desktop.click_ui_element",
                {
                    "target": click_target["target"],
                    "role_filter": click_target["role_filter"],
                    "limit": 80,
                    "click_count": click_target["click_count"],
                },
            )
        )

    if submit_action and requests and "desktop.submit_foreground" in allowed:
        requests.append(_request("desktop.submit_foreground", {"action": submit_action}))

    return requests


def _request(
    tool: str,
    payload: dict[str, Any],
    *,
    planning_reason: str = "planner_fallback_desktop_operation",
) -> dict[str, Any]:
    return {
        "protocol": "json_fallback",
        "tool": tool,
        "input": payload,
        "source": "runtime_planner",
        "planning_reason": planning_reason,
    }


def _media_tool_requests(inputs: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = media_tool_preview(inputs, allowed)
    if not tool_name:
        return []
    return [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_media_playback",
        )
    ]


def _app_tool(mode: str, action: str, allowed: set[str]) -> str:
    if action == "control":
        candidates = app_control_tool_candidates(mode)
    else:
        candidates = app_foreground_tool_candidates(mode, action)
    for tool in candidates:
        if tool in allowed:
            return tool
    return ""
