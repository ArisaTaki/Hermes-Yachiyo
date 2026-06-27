"""Convert runtime planner decisions into existing tool request payloads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.app_aliases import APP_ALIASES

from .capture_plan_hints import capture_tool_preview
from .data_analysis_plan_hints import data_source_kind_hint
from .clipboard_plan_hints import clipboard_tool_preview
from .desktop_plan_hints import media_app_query_search_plan, media_tool_preview
from .file_access_plan_hints import file_access_tool_preview
from .runtime_planner import RuntimePlanner
from .schedule_plan_hints import schedule_tool_preview
from .system_plan_hints import system_tool_preview


def planner_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _decision, requests = planner_decision_and_tool_requests(
        prompt,
        allowed_tools,
        metadata=metadata,
    )
    return requests


def planner_direct_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _decision, requests = planner_direct_decision_and_tool_requests(
        prompt,
        allowed_tools,
        metadata=metadata,
    )
    return requests


def planner_decision_and_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[Any | None, list[dict[str, Any]]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return None, []
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=allowed,
        metadata=metadata,
    )
    return decision, _tool_requests_for_decision(decision, allowed)


def planner_direct_decision_and_tool_requests(
    prompt: str,
    allowed_tools: Iterable[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[Any | None, list[dict[str, Any]]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if not allowed:
        return None, []
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=allowed,
        metadata=metadata,
    )
    return decision, _direct_tool_requests_for_decision(decision, allowed)


def _tool_requests_for_decision(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if decision.selected_intent.kind == "media_playback":
        return _media_tool_requests(decision.selected_intent.inputs, allowed)
    if decision.selected_intent.kind == "data_analysis":
        return _data_analysis_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "system_control":
        return _system_tool_requests(decision.selected_intent.inputs, allowed)
    if decision.selected_intent.kind == "web_research":
        return _web_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "report_generation":
        if str(decision.selected_intent.inputs.get("context_source") or "").strip():
            return _context_source_tool_requests(
                decision,
                allowed,
                step_ids=("copy-selected-report-context", "read-report-context"),
                planning_reason="planner_prefetch_report_context",
            )
        return _context_prefetch_tool_requests(
            decision,
            allowed,
            step_ids=("gather-context",),
            planning_reason="planner_prefetch_report_context",
        )
    if decision.selected_intent.kind == "code_task":
        return _code_task_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "file_organization":
        return _context_prefetch_tool_requests(
            decision,
            allowed,
            step_ids=("inspect-file-scope",),
            planning_reason="planner_prefetch_file_scope",
        )
    if decision.selected_intent.kind == "file_access":
        return _file_access_tool_requests(decision.selected_intent.inputs, allowed)
    if decision.selected_intent.kind == "communication":
        direct_requests = _direct_communication_tool_requests(decision, allowed)
        if direct_requests:
            return direct_requests
        context_requests = _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-communication-context", "read-communication-context"),
            planning_reason="planner_prefetch_communication_context",
        )
        if context_requests:
            return context_requests
        direct_context_requests = _direct_communication_context_tool_requests(
            decision,
            allowed,
        )
        if direct_context_requests:
            return direct_context_requests
        return _context_prefetch_tool_requests(
            decision,
            allowed,
            step_ids=("discover-communication-surface",),
            planning_reason="planner_prefetch_communication_surface",
        )
    if decision.selected_intent.kind == "information_capture":
        return _information_capture_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "schedule":
        return _schedule_tool_requests(decision, allowed)
    if decision.selected_intent.kind == "clipboard_operation":
        return _clipboard_tool_requests(decision.selected_intent.inputs, allowed)
    if decision.selected_intent.kind != "desktop_operation":
        return []
    return _desktop_tool_requests(decision, allowed)


def _direct_tool_requests_for_decision(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if decision.selected_intent.kind != "desktop_operation":
        return _tool_requests_for_decision(decision, allowed)
    return _direct_desktop_tool_requests(decision, allowed)


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


def _first_allowed(candidates: Iterable[str], allowed: set[str]) -> str:
    for candidate in candidates:
        tool_name = str(candidate or "").strip()
        if tool_name and tool_name in allowed:
            return tool_name
    return ""


def _desktop_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for step in decision.plan.tool_plan.steps:
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            continue
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason=_desktop_step_planning_reason(step, tool_name),
            )
        )
    if _weak_desktop_discovery_plan(decision, requests):
        return []
    return requests


def _direct_desktop_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    step_ids = {
        str(getattr(step, "step_id", "") or "").strip()
        for step in decision.plan.tool_plan.steps
    }
    for step in decision.plan.tool_plan.steps:
        step_id = str(getattr(step, "step_id", "") or "").strip()
        if step_id in {"discover-desktop-state", "verify-desktop-result"}:
            continue
        if step_id == "list-app-windows" and "focus-app-window" in step_ids:
            continue
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            continue
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason=_desktop_step_planning_reason(step, tool_name),
            )
        )
    if _weak_desktop_discovery_plan(decision, requests):
        return []
    return requests


def _weak_desktop_discovery_plan(decision: Any, requests: list[dict[str, Any]]) -> bool:
    if len(requests) != 1:
        return False
    if str(requests[0].get("tool") or "") not in {
        "desktop.running_apps",
        "desktop.active_window",
        "screen.capture",
    }:
        return False
    intent = getattr(decision, "selected_intent", None)
    inputs = getattr(intent, "inputs", None)
    if not isinstance(inputs, Mapping):
        return False
    if str(inputs.get("app_name_hint") or "").strip():
        return False
    if str(inputs.get("operation_hint") or "").strip():
        return False
    hint_keys = {
        "window_list_hint",
        "focus_window_hint",
        "ui_inspection_hint",
        "screen_capture_hint",
        "app_management_hint",
        "foreground_management_hint",
        "safe_shortcut_hint",
        "safe_key_hint",
        "safe_scroll_hint",
        "safe_click_hint",
        "desktop_discovery_hint",
        "browser_internal_page_hint",
    }
    return not any(inputs.get(key) for key in hint_keys)


def _desktop_step_planning_reason(step: Any, tool_name: str) -> str:
    input_preview = getattr(step, "input_preview", None)
    if "hotkey" in tool_name or (
        isinstance(input_preview, Mapping)
        and input_preview.get("key")
        and input_preview.get("modifiers") is not None
    ):
        return "planner_fallback_desktop_hotkey"
    return "planner_fallback_desktop_operation"


def _desktop_request_payload(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_name.startswith("app."):
        return _canonicalize_app_payload(payload)
    if tool_name in {"desktop.running_apps", "desktop.active_window"}:
        return {}
    if tool_name == "screen.capture":
        reason = str(payload.get("reason") or "").strip()
        return {"reason": reason} if reason else {}
    if tool_name == "desktop.ui_elements":
        return {
            key: payload[key]
            for key in ("role_filter", "limit")
            if key in payload and payload[key] not in (None, "")
        }
    if tool_name == "desktop.windows":
        app_name = str(payload.get("app_name") or "").strip()
        return {"app_name": app_name} if app_name else {}
    return payload


def _canonicalize_app_payload(payload: dict[str, Any]) -> dict[str, Any]:
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return payload
    canonical = _canonical_app_name(app_name)
    if canonical == app_name:
        return payload
    return {**payload, "app_name": canonical}


def _canonical_app_name(app_name: str) -> str:
    compact = re.sub(r"[\s._-]+", "", str(app_name or "").strip().lower())
    return APP_ALIASES.get(compact, str(app_name or "").strip())


def _data_analysis_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    data_analyze_step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "tool_name", "") == "data.analyze"
        ),
        None,
    )
    if data_analyze_step is not None and "data.analyze" in allowed:
        input_preview = getattr(data_analyze_step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        if payload.get("path"):
            request_input = {
                "path": str(payload.get("path") or ""),
                "artifact_path": str(payload.get("artifact_path") or "analysis-report.md"),
            }
            artifact_paths = payload.get("artifact_paths")
            if isinstance(artifact_paths, list):
                request_input["artifact_paths"] = [
                    str(path or "").strip()
                    for path in artifact_paths
                    if str(path or "").strip()
                ]
            if payload.get("max_rows"):
                request_input["max_rows"] = int(payload.get("max_rows") or 1000)
            return [
                _request(
                    "data.analyze",
                    request_input,
                    planning_reason="planner_builtin_data_analysis",
                )
            ]

    inputs = decision.selected_intent.inputs
    context_source = str(inputs.get("context_source") or "").strip()
    if context_source in {"selection", "clipboard"}:
        return _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-data-context", "read-data-context"),
            planning_reason="planner_prefetch_data_source",
        )
    source_hint = str(inputs.get("data_source_hint") or "").strip()
    if _workspace_readable_data_source(source_hint, inputs) and "workspace.read" in allowed:
        request = _request(
            "workspace.read",
            {"path": source_hint},
            planning_reason="planner_prefetch_data_source",
        )
        request["continue_to_model"] = True
        return [request]
    if source_hint:
        return []
    source_scope = str(inputs.get("data_source_scope_hint") or "").strip()
    if source_scope and not _workspace_listable_data_scope(source_scope):
        return []
    return _context_prefetch_tool_requests(
        decision,
        allowed,
        step_ids=("inspect-data-source",),
        planning_reason="planner_prefetch_data_source",
    )


def _code_task_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    terminal_hint = inputs.get("terminal_command_hint")
    if isinstance(terminal_hint, Mapping):
        command = str(terminal_hint.get("command") or "").strip()
        if command and "terminal.run" in allowed:
            return [
                _request(
                    "terminal.run",
                    {"command": command},
                    planning_reason="planner_fallback_terminal_command",
                )
            ]
    return _context_prefetch_tool_requests(
        decision,
        allowed,
        step_ids=("inspect-workspace",),
        planning_reason="planner_prefetch_code_context",
    )


def _media_tool_requests(inputs: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    app_query_plan = media_app_query_search_plan(inputs, allowed)
    if app_query_plan:
        return [
            _request(
                tool_name,
                payload,
                planning_reason="planner_fallback_media_playback",
            )
            for tool_name, payload in app_query_plan
        ]
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


def _system_tool_requests(inputs: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = system_tool_preview(inputs, allowed)
    if not tool_name:
        return []
    requests = [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_system_control",
        )
    ]
    if (
        tool_name == "system.settings_open"
        and bool(inputs.get("inspect_ui"))
        and "desktop.ui_elements" in allowed
    ):
        requests.append(
            _request(
                "desktop.ui_elements",
                {"role_filter": "", "limit": 80},
                planning_reason="planner_fallback_system_control",
            )
        )
    return requests


def _file_access_tool_requests(inputs: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = file_access_tool_preview(inputs, allowed)
    if not tool_name:
        return []
    return [_request(tool_name, payload, planning_reason="planner_fallback_file_access")]


def _direct_communication_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    direct_hint = inputs.get("direct_message_hint")
    if not isinstance(direct_hint, Mapping):
        return []
    body_source = str(direct_hint.get("body_source") or "").strip()
    if body_source in {"selection", "current_page_link"}:
        required_step_ids = ("copy-communication-body-source",)
    else:
        required_step_ids = ()
    required_step_ids += (
        "focus-communication-recipient-search",
        "type-communication-recipient",
        "submit-communication-recipient-search",
    )
    if body_source in {"clipboard", "selection", "current_page_link"}:
        required_step_ids += ("paste-communication-message",)
    else:
        required_step_ids += ("draft-communication-message",)
    required_step_ids += (
        "send-communication-message",
    )
    steps_by_id = {
        str(getattr(step, "step_id", "") or "").strip(): step
        for step in decision.plan.tool_plan.steps
    }
    requests: list[dict[str, Any]] = []
    for step_id in required_step_ids:
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            return []
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason="planner_fallback_communication_send",
            )
        )
    return requests


def _direct_communication_context_tool_requests(
    decision: Any,
    allowed: set[str],
) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    direct_hint = inputs.get("direct_message_hint")
    if not isinstance(direct_hint, Mapping):
        return []
    source = str(direct_hint.get("body_source") or inputs.get("context_source") or "").strip()
    planning_reason = "planner_prefetch_communication_context"

    if source == "selection":
        if "desktop.safe_shortcut" not in allowed or "clipboard.read" not in allowed:
            return []
        requests = [
            _request(
                "desktop.safe_shortcut",
                {"action": "copy"},
                planning_reason=planning_reason,
            ),
            _request("clipboard.read", {}, planning_reason=planning_reason),
        ]
        requests[-1]["continue_to_model"] = True
        return requests

    if source == "clipboard":
        if "clipboard.read" not in allowed:
            return []
        request = _request("clipboard.read", {}, planning_reason=planning_reason)
        request["continue_to_model"] = True
        return [request]

    if source == "current_page_link":
        if "browser.current_page" not in allowed:
            return []
        request = _request("browser.current_page", {}, planning_reason=planning_reason)
        request["continue_to_model"] = True
        return [request]

    if source == "current_page_content":
        tool_name = _first_allowed(
            ("browser.extract_text", "browser.current_page", "desktop.ui_elements", "screen.capture"),
            allowed,
        )
        if not tool_name:
            return []
        request_payload = _context_prefetch_payload(tool_name, {})
        if request_payload is None:
            return []
        request = _request(tool_name, request_payload, planning_reason=planning_reason)
        request["continue_to_model"] = True
        return [request]

    return []


def _web_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    browser_action = str(decision.selected_intent.inputs.get("browser_action") or "").strip()
    if browser_action == "find_current_page":
        return _current_page_find_tool_requests(decision, allowed)
    if browser_action == "click":
        if "browser.click" not in allowed:
            return []
        selector = str(decision.selected_intent.inputs.get("selector") or "").strip()
        if not selector:
            return []
        payload: dict[str, Any] = {"selector": selector}
        click_count = decision.selected_intent.inputs.get("click_count")
        if click_count not in (None, ""):
            payload["click_count"] = click_count
        for key in ("fallback_x", "fallback_y"):
            value = decision.selected_intent.inputs.get(key)
            if value not in (None, ""):
                payload[key] = value
        return [
            _request(
                "browser.click",
                payload,
                planning_reason="planner_fallback_web_research",
            )
        ]
    if browser_action == "type_text":
        if "browser.type_text" not in allowed:
            return []
        selector = str(decision.selected_intent.inputs.get("selector") or "").strip()
        text = str(decision.selected_intent.inputs.get("text") or "")
        if not selector or not text:
            return []
        return [
            _request(
                "browser.type_text",
                {"selector": selector, "text": text},
                planning_reason="planner_fallback_web_research",
            )
        ]
    if _dynamic_context_browser_action(decision):
        return _dynamic_context_browser_tool_requests(decision, allowed)
    if str(decision.selected_intent.inputs.get("context_source") or "").strip() and not str(
        decision.selected_intent.inputs.get("url_hint") or ""
    ).strip():
        return _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-web-context", "read-web-context"),
            planning_reason="planner_prefetch_web_context",
        )
    step = next(
        (
            item
            for item in decision.plan.tool_plan.steps
            if getattr(item, "step_id", "")
            in {
                "open-or-read-web",
                "read-current-page",
                "extract-current-page-text",
                "capture-current-page",
                "open-web-search",
                "open-web-url",
                "extract-web-url-text",
                "capture-web-url",
            }
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
        if tool_name == "browser.open_url_and_screenshot":
            reason = str(decision.selected_intent.inputs.get("reason") or "").strip()
            if reason:
                payload["reason"] = reason
    elif tool_name not in {"browser.current_page", "browser.extract_text", "browser.screenshot"}:
        return []
    elif not browser_action and not _looks_like_current_page_request(decision.selected_intent.user_goal):
        return []
    elif tool_name == "browser.screenshot":
        reason = str(decision.selected_intent.inputs.get("reason") or "").strip()
        payload = {"reason": reason} if reason else {}

    request = _request(
        tool_name,
        payload,
        planning_reason="planner_fallback_web_research",
    )
    presentation = str(decision.selected_intent.inputs.get("presentation") or "").strip()
    if presentation:
        request["presentation"] = presentation
    if not browser_action and _web_request_needs_model_followup(decision.selected_intent.user_goal):
        request["continue_to_model"] = True
    return [request]


def _current_page_find_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    inputs = decision.selected_intent.inputs
    source = str(inputs.get("context_source") or "").strip()
    query = str(inputs.get("query") or "").strip()
    if source == "selection":
        required_step_ids = (
            "copy-selected-page-find-query",
            "open-current-page-find",
            "paste-current-page-find-query",
        )
    elif source == "clipboard":
        required_step_ids = (
            "open-current-page-find",
            "paste-current-page-find-query",
        )
    elif query:
        required_step_ids = (
            "open-current-page-find",
            "type-current-page-find-query",
        )
    else:
        return []

    steps_by_id = {
        str(getattr(step, "step_id", "") or "").strip(): step
        for step in decision.plan.tool_plan.steps
    }
    requests: list[dict[str, Any]] = []
    for step_id in required_step_ids:
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            return []
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        if step_id == "type-current-page-find-query" and not str(payload.get("text") or "").strip():
            return []
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason="planner_fallback_current_page_find",
            )
        )
    return requests


def _dynamic_context_browser_action(decision: Any) -> bool:
    inputs = decision.selected_intent.inputs
    browser_action = str(inputs.get("browser_action") or "").strip()
    source = str(inputs.get("context_source") or "").strip()
    url_hint = str(inputs.get("url_hint") or "").strip()
    return browser_action in {"open_search", "open_url"} and source in {"selection", "clipboard"} and not url_hint


def _dynamic_context_browser_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    source = str(decision.selected_intent.inputs.get("context_source") or "").strip()
    if source == "selection":
        required_step_ids = (
            "copy-selected-browser-context",
            "focus-browser-address-bar",
            "paste-browser-context",
            "submit-browser-context",
        )
    elif source == "clipboard":
        required_step_ids = (
            "focus-browser-address-bar",
            "paste-browser-context",
            "submit-browser-context",
        )
    else:
        return []

    steps_by_id = {
        str(getattr(step, "step_id", "") or "").strip(): step
        for step in decision.plan.tool_plan.steps
    }
    requests: list[dict[str, Any]] = []
    for step_id in required_step_ids:
        step = steps_by_id.get(step_id)
        tool_name = str(getattr(step, "tool_name", "") or "").strip()
        if not tool_name or tool_name not in allowed:
            return []
        input_preview = getattr(step, "input_preview", None)
        payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
        requests.append(
            _request(
                tool_name,
                _desktop_request_payload(tool_name, payload),
                planning_reason="planner_fallback_dynamic_browser_context",
            )
        )
    return requests


def _context_prefetch_tool_requests(
    decision: Any,
    allowed: set[str],
    *,
    step_ids: tuple[str, ...],
    planning_reason: str,
) -> list[dict[str, Any]]:
    for step_id in step_ids:
        step = next(
            (
                item
                for item in decision.plan.tool_plan.steps
                if getattr(item, "step_id", "") == step_id
            ),
            None,
        )
        request = _context_prefetch_request_for_step(
            step,
            allowed,
            planning_reason=planning_reason,
        )
        if request:
            return [request]
    return []


def _context_prefetch_request_for_step(
    step: Any,
    allowed: set[str],
    *,
    planning_reason: str,
) -> dict[str, Any] | None:
    tool_name = str(getattr(step, "tool_name", "") or "").strip()
    if tool_name not in allowed:
        return None
    input_preview = getattr(step, "input_preview", None)
    payload = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    request_payload = _context_prefetch_payload(tool_name, payload)
    if request_payload is None:
        return None
    request = _request(
        tool_name,
        request_payload,
        planning_reason=planning_reason,
    )
    request["continue_to_model"] = True
    return request


def _context_prefetch_payload(
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name == "workspace.list":
        path = str(payload.get("path") or "").strip()
        return {"path": path} if path else {}
    if tool_name == "workspace.read":
        path = str(payload.get("path") or "").strip()
        return {"path": path} if path else None
    if tool_name in {"browser.current_page", "browser.extract_text", "browser.screenshot"}:
        return {}
    if tool_name == "clipboard.read":
        return {}
    if tool_name == "desktop.safe_shortcut":
        action = str(payload.get("action") or "").strip()
        return {"action": action} if action else None
    if tool_name == "desktop.ui_elements":
        request_payload = {
            key: payload[key]
            for key in ("role_filter", "limit")
            if key in payload and payload[key] not in (None, "")
        }
        return request_payload
    if tool_name in {"desktop.active_window", "desktop.running_apps"}:
        return {}
    if tool_name == "screen.capture":
        reason = str(payload.get("reason") or "").strip()
        return {"reason": reason} if reason else {}
    if tool_name in {"desktop.reveal_path", "desktop.open_path"}:
        path = str(payload.get("path") or "").strip()
        return {"path": path} if path else None
    return None


def _schedule_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = schedule_tool_preview(decision.selected_intent.user_goal, allowed)
    if not tool_name or not payload:
        return _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-schedule-context", "read-schedule-context"),
            planning_reason="planner_prefetch_schedule_context",
        )
    return [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_schedule",
        )
    ]


def _information_capture_tool_requests(decision: Any, allowed: set[str]) -> list[dict[str, Any]]:
    tool_name, payload = capture_tool_preview(decision.selected_intent.inputs, allowed)
    if tool_name != "notes.create" or not payload.get("body"):
        return _context_source_tool_requests(
            decision,
            allowed,
            step_ids=("copy-selected-note-context", "read-note-context"),
            planning_reason="planner_prefetch_information_capture_context",
        )
    return [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_information_capture",
        )
    ]


def _context_source_tool_requests(
    decision: Any,
    allowed: set[str],
    *,
    step_ids: tuple[str, ...],
    planning_reason: str,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for step_id in step_ids:
        step = next(
            (
                item
                for item in decision.plan.tool_plan.steps
                if getattr(item, "step_id", "") == step_id
            ),
            None,
        )
        request = _context_prefetch_request_for_step(
            step,
            allowed,
            planning_reason=planning_reason,
        )
        if request:
            request.pop("continue_to_model", None)
            requests.append(request)
    if requests:
        requests[-1]["continue_to_model"] = True
    return requests


def _clipboard_tool_requests(inputs: dict[str, Any], allowed: set[str]) -> list[dict[str, Any]]:
    action = str(inputs.get("action") or "").strip()
    if action == "copy_selection_read":
        if "desktop.safe_shortcut" not in allowed or "clipboard.read" not in allowed:
            return []
        return [
            _request(
                "desktop.safe_shortcut",
                {"action": "copy"},
                planning_reason="planner_fallback_clipboard",
            ),
            _request(
                "clipboard.read",
                {},
                planning_reason="planner_fallback_clipboard",
            ),
        ]
    tool_name, payload = clipboard_tool_preview(inputs, allowed)
    if not tool_name:
        return []
    if tool_name == "clipboard.write" and not payload.get("text"):
        return []
    return [
        _request(
            tool_name,
            payload,
            planning_reason="planner_fallback_clipboard",
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


def _workspace_readable_data_source(source_hint: str, inputs: Mapping[str, Any]) -> bool:
    if not source_hint or source_hint.startswith(("/", "~")):
        return False
    if re.search(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source_hint):
        return False
    if any(part == ".." for part in source_hint.replace("\\", "/").split("/")):
        return False
    source_kind = str(inputs.get("data_source_kind") or "").strip()
    if not source_kind or source_kind == "unknown":
        source_kind = data_source_kind_hint(source_hint)
    return source_kind in {"csv", "tsv", "json", "jsonl", "text", "text_table"}


def _workspace_listable_data_scope(scope_hint: str) -> bool:
    if not scope_hint or scope_hint.startswith(("/", "~")):
        return False
    if re.search(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", scope_hint):
        return False
    return not any(part == ".." for part in scope_hint.replace("\\", "/").split("/"))


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(term or "").lower() in lowered for term in terms)
