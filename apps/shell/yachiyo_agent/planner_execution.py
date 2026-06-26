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
from .schedule_plan_hints import schedule_tool_preview


def planner_tool_requests(
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
    if decision.selected_intent.kind == "web_research":
        return _web_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "schedule":
        return _schedule_tool_requests(decision.selected_intent.user_goal, allowed)
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


def planner_desktop_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return planner_tool_requests(
        prompt,
        allowed_tools,
        metadata=metadata,
    )


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


def _web_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "") == "open-or-read-web"
        ),
        None,
    )
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if tool_name not in allowed:
        return []
    url = str(decision.selected_intent.inputs.get("url_hint") or "").strip()
    payload: dict[str, Any] = {}
    if tool_name in {
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
    }:
        if not url:
            return []
        payload = {"url": url}
    elif tool_name not in {"browser.current_page", "browser.extract_text", "browser.screenshot"}:
        return []
    elif not _looks_like_current_page_request(decision.selected_intent.user_goal):
        return []

    request = _request(
        tool_name,
        payload,
        planning_reason="planner_fallback_web_research",
    )
    if _web_request_needs_model_followup(decision.selected_intent.user_goal):
        request["continue_to_model"] = True
    return [request]


def _schedule_tool_requests(prompt: str, allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = schedule_tool_preview(prompt, allowed)
    if not tool_name or not payload:
        return []
    return [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_schedule",
        )
    ]


def _looks_like_current_page_request(prompt: str) -> bool:
    return _contains_any(
        prompt,
        (
            "current page",
            "this page",
            "current tab",
            "当前页面",
            "当前网页",
            "当前标签",
            "页面正文",
            "网页正文",
        ),
    )


def _web_request_needs_model_followup(prompt: str) -> bool:
    return _contains_any(
        prompt,
        (
            "summary",
            "summarize",
            "report",
            "research",
            "analyze",
            "总结",
            "报告",
            "调研",
            "分析",
            "输出",
        ),
    )


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(term or "").lower() in lowered for term in terms)


def _app_tool(mode: str, action: str, allowed: set[str]) -> str:
    if action == "control":
        candidates = app_control_tool_candidates(mode)
    else:
        candidates = app_foreground_tool_candidates(mode, action)
    for tool in candidates:
        if tool in allowed:
            return tool
    return ""
